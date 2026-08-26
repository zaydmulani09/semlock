"""Human-readable text writer: dual-sided file:line evidence per finding.

Shape (stable contract, tests assert it):

    SEMLock: 1 cross-branch semantic conflict(s)
    merge-base abc123def456  A: feat/a  B: feat/b

    [signature_changed] pkg.models::User.greet
      A pkg/models.py:8   changed definition
      B pkg/app.py:4      call 'greet'
      why: param 'name' renamed ...

Evidence that could not be located renders as <unlocated> — never fabricated.
Deterministic: findings in canonical sort order, fixed line layout, no colors,
no locale-dependent formatting (INV-1).
"""
from __future__ import annotations

from semlock.output.findings import ROLE_CHANGED, Finding


def render_text(
    ref_a: str,
    ref_b: str,
    merge_base_sha: str,
    findings: tuple[Finding, ...],
) -> str:
    """Render the default human output. Ends with exactly one trailing newline."""
    lines: list[str] = []
    if not findings:
        lines.append("SEMLock: no cross-branch semantic conflicts detected")
        lines.append(f"merge-base {merge_base_sha[:12]}  A: {ref_a}  B: {ref_b}")
        return "\n".join(lines) + "\n"

    lines.append(f"SEMLock: {len(findings)} cross-branch semantic conflict(s)")
    lines.append(f"merge-base {merge_base_sha[:12]}  A: {ref_a}  B: {ref_b}")
    for f in sorted(findings, key=Finding.sort_key):
        lines.append("")
        rule_suffix = f" (rule {f.rule})" if f.rule != f.conflict_class else ""
        lines.append(f"[{f.conflict_class}] {f.changed_symbol_id}{rule_suffix}")
        for letter, ev in (("A", f.evidence_a), ("B", f.evidence_b)):
            if ev.role == ROLE_CHANGED:
                label = "changed definition"
            else:
                label = f"{f.consumer_ref_kind or '?'} '{f.consumer_ref_name}'"
            lines.append(f"  {letter} {ev.render()}   {label}")
        if f.explanation:
            lines.append(f"  why: {f.explanation}")
    return "\n".join(lines) + "\n"
