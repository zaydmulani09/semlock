"""Reconcile run artifacts into committed labels (TP/FP/FN/inconclusive).

A label row is one prediction's final grading plus the case-level FN
candidates the oracle found that SEMLock failed to predict. Labels are
deterministic functions of (results.json, case metas) and are committed under
corpus/labels/ so methodology changes force a visible diff.

FN join rule: an oracle FN candidate is covered when some prediction for the
same case has verdict true_positive AND its site overlaps the candidate line
in the same file AND the candidate's class hints include that prediction's
class. Uncovered candidates become false_negative rows; candidates whose class
cannot be attributed confidently are marked needs_review instead of forced.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

LABELS_SCHEMA = "bench.labels.v1"


@dataclass(frozen=True, slots=True)
class LabelRow:
    case_id: str
    prediction_id: str
    language: str
    conflict_class: str
    family_tag: str
    resolution_status: str
    verdict: str
    needs_review: bool = False
    category: str = ""  # FP/FN category tag ("" until categorized)
    evidence_tool: str = ""
    notes: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "schema": LABELS_SCHEMA,
            "case_id": self.case_id,
            "prediction_id": self.prediction_id,
            "language": self.language,
            "conflict_class": self.conflict_class,
            "family_tag": self.family_tag,
            "resolution_status": self.resolution_status,
            "verdict": self.verdict,
            "needs_review": self.needs_review,
            "category": self.category,
            "evidence_tool": self.evidence_tool,
            "notes": list(self.notes),
        }


def _load_results(results_path: Path) -> dict[str, object]:
    loaded: object = json.loads(results_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def reconcile(
    results_path: Path,
    cases_root: Path,
    predictor_kind: str | None = None,
) -> tuple[LabelRow, ...]:
    artifact = _load_results(results_path)
    rows: list[LabelRow] = []
    raw_results = artifact.get("results", [])
    assert isinstance(raw_results, list)
    for case_entry in raw_results:
        assert isinstance(case_entry, dict)
        rows.extend(_case_rows(artifact, case_entry, cases_root))
    return tuple(rows)


def _case_rows(
    artifact: dict[str, object],
    case_entry: dict[str, object],
    cases_root: Path,
) -> list[LabelRow]:
    case_id = str(case_entry["case_id"])
    language = str(case_entry.get("language", "?"))
    family_tag = str(case_entry.get("family_tag", ""))
    if "skipped" in case_entry:
        return [
            LabelRow(
                case_id=case_id,
                prediction_id=f"{case_id}-skipped",
                language=language,
                conflict_class="none",
                family_tag=family_tag,
                resolution_status="unresolved",
                verdict="inconclusive",
                needs_review=False,
                category="oracle_unavailable",
                notes=(str(case_entry["skipped"]),),
            )
        ]
    raw_predictions = case_entry.get("predictions", [])
    assert isinstance(raw_predictions, list)
    predictions = [p for p in raw_predictions if isinstance(p, dict)]
    rows: list[LabelRow] = []
    tp_sites: set[tuple[str, int, int]] = set()
    for pred in predictions:
        verdict = str(pred["verdict"])
        if verdict == "true_positive":
            tp_sites.add(
                (
                    str(pred["ref_path"]),
                    int(pred["ref_start_line"]),
                    int(pred["ref_end_line"]),
                )
            )
    for pred in predictions:
        evidence = pred.get("evidence", {})
        assert isinstance(evidence, dict)
        notes = tuple(str(n) for n in evidence.get("notes", []))
        verdict = str(pred["verdict"])
        conflict_class = str(pred["conflict_class"])
        category = ""
        if verdict == "false_positive":
            category = family_tag or "fp_uncategorized"
        elif verdict == "false_negative":
            category = "fn_missed_site"
        rows.append(
            LabelRow(
                case_id=case_id,
                prediction_id=str(pred["prediction_id"]),
                language=language,
                conflict_class=conflict_class,
                family_tag=family_tag,
                resolution_status=str(pred["resolution_status"]),
                verdict=verdict,
                needs_review=verdict == "inconclusive",
                category=category,
                evidence_tool=str(evidence.get("tool", "")),
                notes=notes,
            )
        )
    # FN join: oracle-seen breaks with no covering TP prediction.
    raw_meta = _raw_meta(cases_root / "cases" / case_id)
    meta_preds = raw_meta.get("predictions", [])
    assert isinstance(meta_preds, list)
    declared = {
        (str(p["ref_path"]), int(p["ref_start_line"]), int(p["ref_end_line"]))
        for p in meta_preds
        if isinstance(p, dict)
    }
    candidates = case_entry.get("fn_candidates", [])
    assert isinstance(candidates, list)
    for cand in candidates:
        assert isinstance(cand, dict)
        hints = [str(h) for h in cand.get("class_hints", [])]
        path = str(cand["path"])
        line = int(cand["line"])
        covered = any(
            site[0] == path and site[1] <= line <= site[2] for site in tp_sites
        )
        if covered:
            continue
        # FN join: oracle-seen breaks at declared planted sites that no TP
        # prediction covered. Candidates elsewhere in synthetic cases are
        # noise by design; mined cases declare no sites until they do.
        is_declared_site = any(
            site[0] == path and site[1] <= line <= site[2] for site in declared
        )
        if not is_declared_site:
            continue
        rows.append(
            LabelRow(
                case_id=case_id,
                prediction_id=f"{case_id}-fn-{path.replace('/', '_')}-{line}",
                language=language,
                conflict_class=hints[0] if len(hints) == 1 else "ambiguous",
                family_tag=family_tag,
                resolution_status="resolved",
                verdict="false_negative",
                needs_review=len(hints) != 1,
                category=family_tag or "fn_uncategorized",
                evidence_tool=_tool_for(artifact, language),
                notes=(json.dumps(cand, sort_keys=True),),
            )
        )
    return rows


def _tool_for(artifact: dict[str, object], language: str) -> str:
    oracles_raw = artifact.get("oracles", {})
    assert isinstance(oracles_raw, dict)
    entry = oracles_raw.get(language, {})
    return str(entry.get("tool", "")) if isinstance(entry, dict) else ""


def _raw_meta(case_dir: Path) -> dict[str, object]:
    meta_path = case_dir / "meta.json"
    if not meta_path.is_file():
        return {}
    loaded: object = json.loads(meta_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def write_labels(rows: tuple[LabelRow, ...], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(row.to_json(), sort_keys=False) + "\n"
        for row in sorted(rows, key=lambda r: (r.case_id, r.prediction_id))
    ]
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def load_labels(path: Path) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            assert isinstance(entry, dict)
            rows.append(entry)
    return tuple(rows)
