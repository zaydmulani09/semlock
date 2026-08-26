"""Conflict engine (S4-owned): three-way ChangeSet, declarative rules, evaluation,
dual-sided evidence. Consumes resolved FileFacts; language-agnostic by construction.

Public API:
    build_changeset(base, a, b) -> ChangeSet   # semlock.engine.changeset
    evaluate(changeset) -> EvaluationResult    # semlock.engine.evaluate
"""
from semlock.engine.changeset import (
    ChangeKind,
    ChangeSet,
    SurfaceChange,
    SymbolSnapshot,
    build_changeset,
    diff_graphs,
)
from semlock.engine.evaluate import (
    EvaluationResult,
    EvaluationStats,
    eligible_deps,
    evaluate,
)
from semlock.engine.evidence import Conflict, EvidenceSide, conflict_to_dict

__all__ = [
    "ChangeKind",
    "ChangeSet",
    "Conflict",
    "EvaluationResult",
    "EvaluationStats",
    "EvidenceSide",
    "SurfaceChange",
    "SymbolSnapshot",
    "build_changeset",
    "conflict_to_dict",
    "diff_graphs",
    "eligible_deps",
    "evaluate",
]
