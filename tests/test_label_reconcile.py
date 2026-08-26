"""Label reconciliation unit tests on fabricated artifacts (no checkers)."""
from __future__ import annotations

import json
from pathlib import Path

from bench.label import LabelRow, reconcile, write_labels


def _write_results(tmp_path: Path, artifact: dict) -> Path:  # type: ignore[type-arg]
    results = tmp_path / "results.json"
    results.write_text(json.dumps(artifact), encoding="utf-8")
    return results


def _write_meta(
    tmp_path: Path, case_id: str, predictions: list[dict]  # type: ignore[type-arg]
) -> None:
    case_dir = tmp_path / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "meta.json").write_text(
        json.dumps({"case_id": case_id, "predictions": predictions}),
        encoding="utf-8",
    )


def test_fp_gets_category_from_family_tag(tmp_path: Path) -> None:
    artifact = {
        "schema": "bench.run.v1",
        "predictor_kind": "mock:v0",
        "results": [
            {
                "case_id": "c1",
                "language": "python",
                "family_tag": "fp_shadow_misresolution",
                "predictions": [
                    {
                        "prediction_id": "c1-p0",
                        "conflict_class": "removed_export",
                        "resolution_status": "resolved",
                        "verdict": "false_positive",
                        "evidence": {"tool": "mypy", "notes": []},
                    }
                ],
                "fn_candidates": [],
            }
        ],
    }
    _write_meta(tmp_path, "c1", [])
    results = _write_results(tmp_path, artifact)
    rows = reconcile(results, tmp_path)
    assert len(rows) == 1
    assert rows[0].verdict == "false_positive"
    assert rows[0].category == "fp_shadow_misresolution"
    assert rows[0].needs_review is False


def test_uncovered_declared_candidate_becomes_fn(tmp_path: Path) -> None:
    planted = [
        {
            "ref_path": "pkg/app.py",
            "ref_start_line": 5,
            "ref_end_line": 5,
            "conflict_class": "field_removed",
        }
    ]
    _write_meta(tmp_path, "c2", planted)
    artifact = {
        "schema": "bench.run.v1",
        "predictor_kind": "mock:v0",
        "results": [
            {
                "case_id": "c2",
                "language": "python",
                "family_tag": "",
                "predictions": [],
                "fn_candidates": [
                    {
                        "path": "pkg/app.py",
                        "line": 5,
                        "code": "attr-defined",
                        "message": "'User' has no attribute 'email'",
                        "class_hints": ["field_removed"],
                    }
                ],
            }
        ],
    }
    results = _write_results(tmp_path, artifact)
    rows = reconcile(results, tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row.verdict == "false_negative"
    assert row.conflict_class == "field_removed"
    assert row.needs_review is False


def test_ambiguous_hint_marks_needs_review(tmp_path: Path) -> None:
    planted = [
        {
            "ref_path": "pkg/app.py",
            "ref_start_line": 7,
            "ref_end_line": 7,
            "conflict_class": "return_changed",
        }
    ]
    _write_meta(tmp_path, "c3", planted)
    artifact = {
        "schema": "bench.run.v1",
        "predictor_kind": "mock:v0",
        "results": [
            {
                "case_id": "c3",
                "language": "python",
                "family_tag": "",
                "predictions": [],
                "fn_candidates": [
                    {
                        "path": "pkg/app.py",
                        "line": 7,
                        "code": "misc",
                        "message": "?",
                        "class_hints": [
                            "return_changed",
                            "signature_changed",
                        ],
                    }
                ],
            }
        ],
    }
    results = _write_results(tmp_path, artifact)
    rows = reconcile(results, tmp_path)
    assert rows[0].verdict == "false_negative"
    assert rows[0].conflict_class == "ambiguous"
    assert rows[0].needs_review is True


def test_skipped_case_yields_inconclusive_label(tmp_path: Path) -> None:
    artifact = {
        "schema": "bench.run.v1",
        "predictor_kind": "mock:v0",
        "results": [
            {
                "case_id": "c4",
                "language": "typescript",
                "family_tag": "",
                "predictions": [],
                "fn_candidates": [],
                "skipped": "tsc not found; set SEMLOCK_TSC",
            }
        ],
    }
    _write_meta(tmp_path, "c4", [])
    results = _write_results(tmp_path, artifact)
    rows = reconcile(results, tmp_path)
    assert rows[0].verdict == "inconclusive"
    assert rows[0].category == "oracle_unavailable"


def test_write_labels_is_sorted_and_roundtrips(tmp_path: Path) -> None:
    row_b = LabelRow("z-case", "z-p0", "python", "field_removed", "", "resolved",
                     "true_positive")
    row_a = LabelRow("a-case", "a-p0", "python", "field_removed", "", "resolved",
                     "false_positive", category="fp_dead_code")
    out = write_labels((row_b, row_a), tmp_path / "l.jsonl")
    from bench.label import load_labels

    loaded = load_labels(out)
    assert [str(r["case_id"]) for r in loaded] == ["a-case", "z-case"]
    assert str(loaded[0]["category"]) == "fp_dead_code"
