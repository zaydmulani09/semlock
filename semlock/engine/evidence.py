"""Conflict + dual-sided evidence shapes (S4-owned; published for S5 rendering).

INV-9 (briefing): every Conflict carries evidence on BOTH sides -- the provider-side
definition location (a_file:a_line when A changed the surface, b_file:b_line when B
did) AND the consumer-side use-site location on the opposite head -- plus a plain-
English explanation naming BOTH symbols and the rule that fired. A bare "semantic
conflict detected" is never emitted.

All strings are assembled deterministically; `conflict_to_dict` fixes key order so
S5's renderer can be a dumb printer (INV-1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from semlock.ir.model import Span

Side = Literal["A", "B"]

ROLE_CHANGED: Final = "changed_definition"
ROLE_CONSUMER: Final = "consuming_use"


@dataclass(frozen=True, slots=True)
class EvidenceSide:
    """One side's location evidence. `line` is 1-indexed, `col` 0-indexed (INV-3)."""

    path: str
    line: int
    col: int
    role: str

    def render(self) -> str:
        return f"{self.path}:{self.line}:{self.col}"


@dataclass(frozen=True)
class Conflict:
    """A detected cross-branch semantic break.

    changed_side/consumer_side are always opposite heads. `evidence_a`/`evidence_b`
    are the A-file/B-file views respectively (NOT provider/consumer order): when
    changed_side == 'A', evidence_a describes the changed definition and evidence_b
    the consuming use; mirrored when 'B'.
    """

    rule: str
    conflict_class: str
    changed_symbol_id: str
    changed_side: Side
    consumer_ref_name: str
    consumer_ref_kind: str
    consumer_path: str
    consumer_span: Span
    consumer_side: Side
    target_id: str
    explanation: str
    evidence_a: EvidenceSide
    evidence_b: EvidenceSide


def make_conflict(
    *,
    rule: str,
    conflict_class: str,
    changed_symbol_id: str,
    changed_side: Side,
    changed_path: str,
    changed_line: int,
    changed_col: int,
    consumer_ref_name: str,
    consumer_ref_kind: str,
    consumer_path: str,
    consumer_span: Span,
    target_id: str,
    explanation: str,
) -> Conflict:
    """Assemble a Conflict with correct DUAL-SIDED evidence orientation.

    `evidence_a` is always the A-side view and `evidence_b` the B-side view: the
    changed definition lands on `changed_side`'s file:line, the consuming use on
    the opposite head's file:line.
    """
    changed = EvidenceSide(
        path=changed_path,
        line=changed_line,
        col=changed_col,
        role=ROLE_CHANGED,
    )
    consumer = EvidenceSide(
        path=consumer_path,
        line=consumer_span.start_line,
        col=consumer_span.start_col,
        role=ROLE_CONSUMER,
    )
    if changed_side == "A":
        evidence_a, evidence_b = changed, consumer
    else:
        evidence_a, evidence_b = consumer, changed
    return Conflict(
        rule=rule,
        conflict_class=conflict_class,
        changed_symbol_id=changed_symbol_id,
        changed_side=changed_side,
        consumer_ref_name=consumer_ref_name,
        consumer_ref_kind=consumer_ref_kind,
        consumer_path=consumer_path,
        consumer_span=consumer_span,
        consumer_side="B" if changed_side == "A" else "A",
        target_id=target_id,
        explanation=explanation,
        evidence_a=evidence_a,
        evidence_b=evidence_b,
    )


def conflict_to_dict(conflict: Conflict) -> dict[str, Any]:
    """Fixed key order for S5 output (INV-1)."""
    return {
        "rule": conflict.rule,
        "conflict_class": conflict.conflict_class,
        "changed_symbol_id": conflict.changed_symbol_id,
        "changed_side": conflict.changed_side,
        "consumer_ref_name": conflict.consumer_ref_name,
        "consumer_ref_kind": conflict.consumer_ref_kind,
        "consumer_path": conflict.consumer_path,
        "consumer_span": {
            "start_line": conflict.consumer_span.start_line,
            "start_col": conflict.consumer_span.start_col,
            "end_line": conflict.consumer_span.end_line,
            "end_col": conflict.consumer_span.end_col,
        },
        "consumer_side": conflict.consumer_side,
        "target_id": conflict.target_id,
        "explanation": conflict.explanation,
        "evidence_a": _evidence_to_dict(conflict.evidence_a),
        "evidence_b": _evidence_to_dict(conflict.evidence_b),
    }


def _evidence_to_dict(evidence: EvidenceSide) -> dict[str, Any]:
    return {
        "path": evidence.path,
        "line": evidence.line,
        "col": evidence.col,
        "role": evidence.role,
    }
