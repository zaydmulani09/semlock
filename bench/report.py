"""Benchmark reporting: precision, recall, resolution coverage, honesty stats.

Reads a labels file (and optionally results/timings artifacts) and renders the
published metrics. HARD GATE: numbers produced under a non-CLI predictor are
stamped NOT PUBLISHABLE — mock runs exercise plumbing only and must never be
quoted as SEMLock performance (Constitution §8; ADR-0009).

Metrics definitions:
* precision        TP / (TP + FP)            over graded predictions
* recall           TP / (TP + FN)             over graded predictions
* inconclusive_rate INCONCLUSIVE / graded     reported beside both
* resolution_coverage: fraction of dependency edges with status=="resolved".
  Only measurable from CLI findings payloads; mock runs report null rather
  than inventing coverage (hiding low coverage is methodology violation).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

GRADED = {"true_positive", "false_positive", "false_negative"}
PUBLISHABLE_KINDS = {"cli"}


def compute_metrics(labels_path: Path) -> dict[str, object]:
    rows = _load(labels_path)
    verdicts = Counter(str(r.get("verdict")) for r in rows)
    tp = verdicts["true_positive"]
    fp = verdicts["false_positive"]
    fn = verdicts["false_negative"]
    inconclusive = verdicts["inconclusive"]

    by_language: dict[str, dict[str, float]] = {}
    for language in sorted({str(r.get("language", "?")) for r in rows}):
        subset = [r for r in rows if str(r.get("language")) == language]
        by_language[language] = _subset_counts(subset)

    by_class: dict[str, dict[str, float]] = {}
    for cls in sorted({str(r.get("conflict_class", "?")) for r in rows}):
        subset = [r for r in rows if str(r.get("conflict_class")) == cls]
        by_class[cls] = _subset_counts(subset)

    fp_categories = Counter(
        str(r.get("category") or "untagged")
        for r in rows
        if r.get("verdict") == "false_positive"
    )
    fn_categories = Counter(
        str(r.get("category") or "untagged")
        for r in rows
        if r.get("verdict") == "false_negative"
    )

    return {
        "labels_schema": str(rows[0].get("schema", "")) if rows else "",
        "total_labels": len(rows),
        "counts": {"tp": tp, "fp": fp, "fn": fn, "inconclusive": inconclusive},
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
        "inconclusive_rate": (
            round(inconclusive / len(rows), 4) if rows else None
        ),
        "by_language": by_language,
        "by_conflict_class": by_class,
        "fp_categories": dict(sorted(fp_categories.items())),
        "fn_categories": dict(sorted(fn_categories.items())),
        "needs_review": sum(
            1 for r in rows if bool(r.get("needs_review"))
        ),
        "resolution_coverage": None,  # filled by attach_resolution_coverage
    }


def _subset_counts(subset: list[dict[str, object]]) -> dict[str, float]:
    c = Counter(str(r.get("verdict")) for r in subset)
    tp, fp, fn = c["true_positive"], c["false_positive"], c["false_negative"]
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else -1.0,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) else -1.0,
    }


def attach_resolution_coverage(
    metrics: dict[str, object], results_path: Path
) -> dict[str, object]:
    """Fill resolution_coverage from CLI findings; stays None otherwise.

    Expects the artifact's optional 'resolution_stats' block written by the
    CLI adapter once S5 lands:
        {"resolved": int, "total_edges": int}
    """
    try:
        artifact = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return metrics
    stats = artifact.get("resolution_stats")
    if isinstance(stats, dict):
        total = int(stats.get("total_edges", 0))
        resolved = int(stats.get("resolved", 0))
        if total > 0:
            metrics["resolution_coverage"] = round(resolved / total, 4)
    return metrics


def render_report(
    metrics: dict[str, object],
    predictor_kind: str,
    runtime_seconds: float | None = None,
) -> str:
    publishable = predictor_kind in PUBLISHABLE_KINDS
    lines: list[str] = []
    lines.append("# SEMLock benchmark report")
    lines.append("")
    if not publishable:
        lines.append(
            "> **NOT PUBLISHABLE AS SEMLOCK NUMBERS** — predictor kind "
            f"`{predictor_kind}` is not the product CLI "
            "(plumbing/validation run only)."
        )
        lines.append("")
    counts = metrics.get("counts", {})
    assert isinstance(counts, dict)
    lines.append(f"- labels: {metrics.get('total_labels')}")
    lines.append(
        f"- TP={counts.get('tp')} FP={counts.get('fp')} "
        f"FN={counts.get('fn')} inconclusive={counts.get('inconclusive')}"
    )
    precision = metrics.get("precision")
    recall = metrics.get("recall")
    lines.append(
        f"- precision: {precision if precision is not None else 'n/a'}"
        f"   recall: {recall if recall is not None else 'n/a'}"
    )
    lines.append(f"- inconclusive rate: {metrics.get('inconclusive_rate')}")
    cov = metrics.get("resolution_coverage")
    lines.append(
        "- resolution coverage: "
        + ("n/a (requires CLI run)" if cov is None else str(cov))
    )
    by_language = metrics.get("by_language", {})
    assert isinstance(by_language, dict)
    if by_language:
        lines.append("")
        lines.append("## By language")
        for language, stats in sorted(by_language.items()):
            assert isinstance(stats, dict)
            lines.append(
                f"- {language}: TP={stats['tp']} FP={stats['fp']} "
                f"FN={stats['fn']} P={stats['precision']} R={stats['recall']}"
            )
    by_class = metrics.get("by_conflict_class", {})
    assert isinstance(by_class, dict)
    if by_class:
        lines.append("")
        lines.append("## By conflict class")
        for cls, stats in sorted(by_class.items()):
            assert isinstance(stats, dict)
            lines.append(
                f"- {cls}: TP={stats['tp']} FP={stats['fp']} "
                f"FN={stats['fn']} P={stats['precision']} R={stats['recall']}"
            )
    fp_cats = metrics.get("fp_categories", {})
    fn_cats = metrics.get("fn_categories", {})
    assert isinstance(fp_cats, dict)
    assert isinstance(fn_cats, dict)
    if fp_cats:
        lines.append("")
        lines.append("## FP categories")
        for cat, n in sorted(fp_cats.items()):
            lines.append(f"- {cat}: {n}")
    if fn_cats:
        lines.append("")
        lines.append("## FN categories")
        for cat, n in sorted(fn_cats.items()):
            lines.append(f"- {cat}: {n}")
    if runtime_seconds is not None:
        lines.append("")
        lines.append(f"- total measured runtime: {runtime_seconds:.1f}s")
    needs_review = metrics.get("needs_review")
    if isinstance(needs_review, int) and needs_review:
        lines.append("")
        lines.append(
            f"- WARNING: {needs_review} label(s) need human review "
            "(inconclusive/ambiguous evidence)"
        )
    lines.append("")
    return "\n".join(lines)


def _load(path: Path) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            assert isinstance(entry, dict)
            rows.append(entry)
    return tuple(rows)
