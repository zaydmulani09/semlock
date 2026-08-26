"""The S5 finding model, shared by BOTH pipelines (mock-fixture and engine).

Shape alignment: Finding.to_dict() emits EXACTLY the key order of
semlock.engine.evidence.conflict_to_dict (S4 publishes dicts "so S5's renderer
can be a dumb printer", INV-1). Fixture-mode findings are filled into that same
shape so both modes share one JSON/text contract.

INV-2/INV-8 honesty rules encoded here:
- The mock path only enriches S1-authored EXPECTED_CONFLICTS with file:line
  lookups; it never invents conflicts or conflict logic (cross-session rule 5).
- Missing evidence renders as null / <unlocated>; nothing is fabricated.

No static import of semlock.engine anywhere: the engine may be absent (CI
before S4 lands). The engine path adapts runtime objects duck-typed by
ConflictLike.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

from mocks import conflict_fixtures as cf
from mocks.changeset_fixtures import ChangesetScenario
from semlock.ir.model import FileFacts, Ref, Span, Symbol

REPORT_FORMAT_VERSION: Final = "0.1.0"

ROLE_CHANGED: Final = "changed_definition"
ROLE_CONSUMER: Final = "consuming_use"

ChangedSideT = Literal["A", "B"]


@dataclass(frozen=True, slots=True)
class SideEvidence:
    """One side's location evidence (mirrors engine EvidenceSide)."""

    path: str | None
    line: int | None
    col: int | None
    role: str

    def render(self) -> str:
        if self.path is None or self.line is None:
            return "<unlocated>"
        return f"{self.path}:{self.line}"


class EvidenceLike(Protocol):
    """Structural view of engine EvidenceSide (path/line/col/role)."""

    path: str
    line: int
    col: int
    role: str


class ConflictLike(Protocol):
    """Structural view of semlock.engine.evidence.Conflict (runtime duck-typed).

    Attribute types mirror the engine's declarations exactly so this protocol
    stays assignment-compatible without importing the module statically.
    """

    rule: str
    conflict_class: str
    changed_symbol_id: str
    changed_side: ChangedSideT
    consumer_ref_name: str
    consumer_ref_kind: str
    consumer_path: str
    consumer_span: Span
    consumer_side: ChangedSideT
    target_id: str
    explanation: str
    evidence_a: EvidenceLike
    evidence_b: EvidenceLike


@dataclass(frozen=True, slots=True)
class Finding:
    """One cross-branch semantic conflict, ready for any S5 writer."""

    rule: str
    conflict_class: str
    changed_symbol_id: str
    changed_side: ChangedSideT
    consumer_ref_name: str
    consumer_ref_kind: str
    consumer_path: str | None
    consumer_span: Span | None
    consumer_side: ChangedSideT
    target_id: str
    explanation: str
    evidence_a: SideEvidence
    evidence_b: SideEvidence

    def sort_key(self) -> tuple[str, str, str, int, int, str, str]:
        # Mirrors the engine's conflict sort key; None-safe for fixture gaps.
        span = self.consumer_span
        return (
            self.conflict_class,
            self.changed_symbol_id,
            self.consumer_path or "",
            span.start_line if span else 0,
            span.start_col if span else 0,
            self.consumer_ref_name,
            self.rule,
        )

    def to_dict(self) -> dict[str, Any]:
        """Fixed key order, identical to engine conflict_to_dict (INV-1)."""
        span = self.consumer_span
        return {
            "rule": self.rule,
            "conflict_class": self.conflict_class,
            "changed_symbol_id": self.changed_symbol_id,
            "changed_side": self.changed_side,
            "consumer_ref_name": self.consumer_ref_name,
            "consumer_ref_kind": self.consumer_ref_kind,
            "consumer_path": self.consumer_path,
            "consumer_span": (
                None
                if span is None
                else {
                    "start_line": span.start_line,
                    "start_col": span.start_col,
                    "end_line": span.end_line,
                    "end_col": span.end_col,
                }
            ),
            "consumer_side": self.consumer_side,
            "target_id": self.target_id,
            "explanation": self.explanation,
            "evidence_a": _side_evidence_to_dict(self.evidence_a),
            "evidence_b": _side_evidence_to_dict(self.evidence_b),
        }


def _side_evidence_to_dict(ev: SideEvidence) -> dict[str, Any]:
    return {"path": ev.path, "line": ev.line, "col": ev.col, "role": ev.role}


def from_engine(conflict: ConflictLike) -> Finding:
    """Adapt a runtime engine Conflict into the S5 finding model.

    evidence_a/evidence_b are the A-view/B-view respectively (engine contract);
    we rebuild SideEvidence pairs keyed by which side changed so writers can
    print provider/consumer orientation without knowing the convention.
    """
    changed_ev_raw = (
        conflict.evidence_a if changed_is_a(conflict) else conflict.evidence_b
    )
    consumer_ev_raw = (
        conflict.evidence_b if changed_is_a(conflict) else conflict.evidence_a
    )
    changed_ev = SideEvidence(
        path=str(changed_ev_raw.path),
        line=int(changed_ev_raw.line),
        col=int(changed_ev_raw.col),
        role=ROLE_CHANGED,
    )
    consumer_ev = SideEvidence(
        path=str(consumer_ev_raw.path),
        line=int(consumer_ev_raw.line),
        col=int(consumer_ev_raw.col),
        role=ROLE_CONSUMER,
    )
    return Finding(
        rule=str(conflict.rule),
        conflict_class=str(conflict.conflict_class),
        changed_symbol_id=str(conflict.changed_symbol_id),
        changed_side="A" if changed_is_a(conflict) else "B",
        consumer_ref_name=str(conflict.consumer_ref_name),
        consumer_ref_kind=str(conflict.consumer_ref_kind),
        consumer_path=str(conflict.consumer_path),
        consumer_span=conflict.consumer_span,
        consumer_side="B" if changed_is_a(conflict) else "A",
        target_id=str(conflict.target_id),
        explanation=str(conflict.explanation),
        evidence_a=changed_ev if changed_is_a(conflict) else consumer_ev,
        evidence_b=consumer_ev if changed_is_a(conflict) else changed_ev,
    )


def changed_is_a(conflict: ConflictLike) -> bool:
    return conflict.changed_side == "A"


# ------------------------------------------------------------- fixture enrichment


def _iter_symbols(
    side: tuple[FileFacts, ...],
) -> Iterator[tuple[FileFacts, Symbol]]:
    for facts in side:
        for symbol in facts.symbols:
            yield facts, symbol


def locate_symbol(
    side: tuple[FileFacts, ...], symbol_id: str
) -> tuple[str, Symbol] | None:
    """Find the defining file + symbol for `symbol_id`, accepting member ids.

    Member ids (`pkg.models::User.email`) bind to the owning class's member
    (ADR-0008). If the member itself is absent on this side — exactly the
    field_removed case — evidence falls back to the OWNING symbol's location,
    mirroring what a correct engine reports for a removal.
    """
    for facts, symbol in _iter_symbols(side):
        if symbol.id == symbol_id:
            return facts.path, symbol
        for member in symbol.members:
            if f"{symbol.id}.{member.name}" == symbol_id:
                return facts.path, symbol
    owner_id = symbol_id.rsplit(".", 1)[0]
    if "::" in owner_id and owner_id != symbol_id:
        for facts, symbol in _iter_symbols(side):
            if symbol.id == owner_id:
                return facts.path, symbol
    return None


def _ref_sort_key(ref: Ref) -> tuple[int, int, str]:
    return (ref.span.start_line, ref.span.start_col, ref.name)


def locate_consumer(
    side: tuple[FileFacts, ...], ref_name: str
) -> tuple[str, Ref] | None:
    """First (canonical order) use-site named `ref_name` across the side."""
    candidates = [
        (facts.path, ref)
        for facts in side
        for ref in facts.refs
        if ref.name == ref_name
    ]
    if not candidates:
        return None
    best_path, best_ref = min(
        candidates, key=lambda item: (_ref_sort_key(item[1]), item[0])
    )
    return best_path, best_ref


def findings_from_scenario(
    scenario: ChangesetScenario,
    side_a: tuple[FileFacts, ...],
    side_b: tuple[FileFacts, ...],
) -> tuple[Finding, ...]:
    """Ground-truth expectations + fixture facts -> enriched Findings.

    The scenario's EXPECTED_CONFLICTS are S1-authored ground truth for what a
    correct engine emits; this function adds file:line evidence by looking ids
    and ref names up in the corresponding resolved fact sets. Fixtures describe
    the canonical orientation (A mutates a surface; B consumes it).
    """
    expected = cf.expected_for(scenario.name)
    findings: list[Finding] = []
    for exp in expected:
        changed_hit = locate_symbol(side_a, exp.changed_symbol_id)
        consumer_hit = locate_consumer(side_b, exp.consumer_ref_name)

        consumer_path = consumer_hit[0] if consumer_hit else None
        consumer_ref = consumer_hit[1] if consumer_hit else None
        changed_path = changed_hit[0] if changed_hit else None
        changed_line = changed_hit[1].span.start_line if changed_hit else None
        changed_col = changed_hit[1].span.start_col if changed_hit else None

        findings.append(
            Finding(
                rule=exp.conflict_class,  # fixture granularity: rule == class
                conflict_class=exp.conflict_class,
                changed_symbol_id=exp.changed_symbol_id,
                changed_side="A",
                consumer_ref_name=exp.consumer_ref_name,
                consumer_ref_kind=consumer_ref.kind if consumer_ref else "?",
                consumer_path=consumer_path,
                consumer_span=consumer_ref.span if consumer_ref else None,
                consumer_side="B",
                target_id=exp.changed_symbol_id,
                explanation=exp.note,
                evidence_a=SideEvidence(
                    path=changed_path,
                    line=changed_line,
                    col=changed_col,
                    role=ROLE_CHANGED,
                ),
                evidence_b=SideEvidence(
                    path=consumer_path,
                    line=consumer_ref.span.start_line if consumer_ref else None,
                    col=consumer_ref.span.start_col if consumer_ref else None,
                    role=ROLE_CONSUMER,
                ),
            )
        )
    return tuple(sorted(findings, key=Finding.sort_key))
