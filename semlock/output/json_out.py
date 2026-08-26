"""JSON writer for `semlock check --json`.

Emits a check report whose `findings` entries use EXACTLY the key order of
semlock.engine.evidence.conflict_to_dict (S4 publishes these dicts for S5; the
mock-fixture path fills the same shape). The envelope's own key order is fixed
below. Byte-identical reruns for identical inputs (INV-1): sorted findings,
indent=2, ensure_ascii=False, trailing newline.

The report envelope is S5-owned (REPORT_FORMAT_VERSION 0.1.0); a formal
schema/check-report.schema.json is proposed to S1 via interface-request.
"""
from __future__ import annotations

import json
from typing import Any

from semlock.ir.version import FORMAT_VERSION as IR_FORMAT_VERSION
from semlock.output.findings import REPORT_FORMAT_VERSION, Finding

# Fixed property order (INV-1). Keys appended in exactly this order.
_REPORT_KEYS: tuple[str, ...] = (
    "schema",
    "report_format_version",
    "ir_format_version",
    "ref_a",
    "ref_b",
    "merge_base",
    "files_changed_a",
    "files_changed_b",
    "conflict_count",
    "engine_stats",
    "findings",
)


def report_dict(
    ref_a: str,
    ref_b: str,
    merge_base_sha: str,
    files_changed_a: int,
    files_changed_b: int,
    findings: tuple[Finding, ...],
    engine_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical report dict; findings in canonical sort order."""
    ordered_findings = sorted(findings, key=Finding.sort_key)
    report: dict[str, Any] = {
        "schema": "semlock.check-report",
        "report_format_version": REPORT_FORMAT_VERSION,
        "ir_format_version": IR_FORMAT_VERSION,
        "ref_a": ref_a,
        "ref_b": ref_b,
        "merge_base": merge_base_sha,
        "files_changed_a": files_changed_a,
        "files_changed_b": files_changed_b,
        "conflict_count": len(ordered_findings),
        # Real-pipeline runs embed the engine's observability stats verbatim;
        # fixture-mode runs report null (mode is explicit, never hidden).
        "engine_stats": engine_stats,
        "findings": [f.to_dict() for f in ordered_findings],
    }
    assert tuple(report) == _REPORT_KEYS  # guard the canonical order
    return report


def to_json(report: dict[str, Any]) -> str:
    """Serialize with fixed formatting: 2-space indent, trailing newline."""
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"
