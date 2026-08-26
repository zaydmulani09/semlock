"""Declarative rule contract (ADR-0004 intent).

A rule is a PURE PREDICATE over one (surface change, eligible dependency edge)
pairing plus read-only graph context. Rules:
  - see ONLY eligible deps (resolution.status == 'resolved'); evaluate.py enforces
    this upstream, every rule re-checks defensively (INV-2 belt-and-suspenders),
  - contain ZERO language-specific logic (no `if language == ...` -- ever),
  - return None when evidence is inconclusive instead of fabricating a verdict
    (INV-8), and may never weaken that stance to raise recall,
  - are registered in REGISTRY in fixed declaration order (deterministic, INV-1).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from semlock.engine.changeset import SurfaceChange
from semlock.engine.evidence import Conflict, Side
from semlock.graph.model import ClaimGraph, DependencyEdge


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Read-only view for one evaluation direction (provider -> consumer)."""

    provider_side: Side
    consumer_side: Side
    base_graph: ClaimGraph
    provider_graph: ClaimGraph
    consumer_graph: ClaimGraph


class Rule(ABC):
    """One conflict class. `rule_id` is stable across versions (S5 renders it)."""

    rule_id: ClassVar[str]
    conflict_class: ClassVar[str]

    @abstractmethod
    def evaluate(
        self,
        change: SurfaceChange,
        dep: DependencyEdge,
        ctx: RuleContext,
    ) -> Conflict | None:
        """Decide whether THIS change breaking THIS resolved dependency is a
        conflict of this rule's class. Return None for no / inconclusive."""
        raise NotImplementedError

    def _guard(self, change: SurfaceChange, dep: DependencyEdge) -> bool:
        """Common INV-2 defense: only resolved edges participate, always."""
        return dep.status == "resolved" and dep.target_id is not None
