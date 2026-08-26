"""Conflict evaluation -- the Law-3 choke (S4-owned).

THE choke, stated once and enforced structurally:

    eligible(deps) = [d for d in deps if d.resolution.status == "resolved"]

Every rule sees ONLY eligible deps. A dependency whose resolution is unresolved,
ambiguous, or external can never reach a rule, never match a provides-delta change,
and never produce a finding -- in either direction (INV-2). Deltas are matched
against the OPPOSITE head's resolved deps and NOTHING else: deltas are never diffed
against each other nor against the base's deps.

A conflict fires ONLY when a resolved dep's target_symbol_id equals a provides_delta
change's symbol_id. Additions (`kind == "added"`) are never provider breaks and are
excluded before any rule runs.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from semlock.engine.changeset import ChangeSet
from semlock.engine.evidence import Conflict, Side, conflict_to_dict
from semlock.engine.rules import REGISTRY
from semlock.engine.rules.base import Rule, RuleContext
from semlock.graph.model import ClaimGraph, DependencyEdge


@dataclass(frozen=True, slots=True)
class EvaluationStats:
    """Observability around the choke -- reported, never hidden."""

    deps_total: int
    deps_eligible: int
    deps_chocked: int
    changes_considered: int
    pairings_evaluated: int


@dataclass(frozen=True)
class EvaluationResult:
    conflicts: tuple[Conflict, ...]
    stats: EvaluationStats

    def to_dict(self) -> dict[str, object]:
        """Fixed key order for S5 rendering (INV-1)."""
        return {
            "conflicts": [conflict_to_dict(c) for c in self.conflicts],
            "stats": {
                "deps_total": self.stats.deps_total,
                "deps_eligible": self.stats.deps_eligible,
                "deps_chocked": self.stats.deps_chocked,
                "changes_considered": self.stats.changes_considered,
                "pairings_evaluated": self.stats.pairings_evaluated,
            },
        }


def eligible_deps(deps: Sequence[DependencyEdge]) -> list[DependencyEdge]:
    """Law-3 choke, verbatim: only resolved bindings may ever match."""
    return [d for d in deps if d.status == "resolved" and d.target_id is not None]


def _conflict_sort_key(c: Conflict) -> tuple[str, str, str, int, int, str, str]:
    return (
        c.conflict_class,
        c.changed_symbol_id,
        c.consumer_path,
        c.consumer_span.start_line,
        c.consumer_span.start_col,
        c.consumer_ref_name,
        c.rule,
    )


def evaluate(
    changeset: ChangeSet, rules: Sequence[Rule] = REGISTRY
) -> EvaluationResult:
    """Evaluate both directions (A's changes vs B's deps; B's changes vs A's deps)."""
    index_a = _index_eligible(changeset.a_graph)
    index_b = _index_eligible(changeset.b_graph)

    found: set[Conflict] = set()
    deps_total = len(changeset.a_graph.dep_edges) + len(changeset.b_graph.dep_edges)
    eligible_count = sum(len(v) for v in index_a.values()) + sum(
        len(v) for v in index_b.values()
    )
    changes_considered = 0
    pairings = 0

    for provider, consumer, delta, index in (
        ("A", "B", changeset.provides_delta_a, index_b),
        ("B", "A", changeset.provides_delta_b, index_a),
    ):
        assert provider in ("A", "B") and consumer in ("A", "B")
        ctx = RuleContext(
            provider_side=_side(provider),
            consumer_side=_side(consumer),
            base_graph=changeset.base_graph,
            provider_graph=(
                changeset.a_graph if provider == "A" else changeset.b_graph
            ),
            consumer_graph=(
                changeset.b_graph if provider == "A" else changeset.a_graph
            ),
        )
        for change in delta:
            if change.kind == "added":
                continue  # additions break nobody
            changes_considered += 1
            for dep in index.get(change.symbol_id, ()):
                for rule in rules:
                    pairings += 1
                    conflict = rule.evaluate(change, dep, ctx)
                    if conflict is not None:
                        found.add(conflict)

    ordered = tuple(sorted(found, key=_conflict_sort_key))
    stats = EvaluationStats(
        deps_total=deps_total,
        deps_eligible=eligible_count,
        deps_chocked=deps_total - eligible_count,
        changes_considered=changes_considered,
        pairings_evaluated=pairings,
    )
    return EvaluationResult(conflicts=ordered, stats=stats)


def _index_eligible(graph: ClaimGraph) -> Mapping[str, tuple[DependencyEdge, ...]]:
    buckets: dict[str, list[DependencyEdge]] = {}
    for dep in eligible_deps(graph.dep_edges):
        assert dep.target_id is not None
        buckets.setdefault(dep.target_id, []).append(dep)
    # Edges arrive pre-sorted from the builder; preserve that order per bucket.
    return {k: tuple(v) for k, v in buckets.items()}


def _side(label: str) -> Side:
    return "A" if label == "A" else "B"
