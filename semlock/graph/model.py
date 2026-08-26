"""Claim-graph data model (S4-owned).

The claim graph is the semantic model of ONE changeset side (a merge-base, branch A,
or branch B): nodes are declared symbols, edges are use-sites (`Ref`s with their
resolution status attached) and inheritance (`bases`). A ChangeSet is the diff of two
claim graphs (see semlock/engine/changeset.py) -- ONE model, ONE owner (S4).

Invariants honored here: INV-1 (all collections serialize in a defined sort order,
enforced by graph/build.py and graph/export.py), INV-3 (spans copied verbatim from
IR), INV-4 (frozen dataclasses, tuples everywhere). This module is pure data; the
builder lives in semlock/graph/build.py, serialization in semlock/graph/export.py.

Dependency edges deliberately carry ALL use-sites regardless of resolution status --
the graph is ground truth about what each side knows. Only the conflict engine
(semlock/engine/evaluate.py) filters to eligible edges, and it NEVER treats a
non-resolved edge as a match (INV-2).
"""
from __future__ import annotations

from dataclasses import dataclass

from semlock.ir.model import (
    Member,
    RefKind,
    ResolutionStatus,
    Signature,
    Span,
    SymbolKind,
)


@dataclass(frozen=True, slots=True)
class SymbolNode:
    """One declared symbol, projected from the IR with its declaring file attached."""

    id: str
    name: str
    kind: SymbolKind
    span: Span
    exports: bool
    source_path: str
    bases: tuple[str, ...] = ()
    signature: Signature | None = None
    members: tuple[Member, ...] = ()


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    """One use-site (`Ref`) with its post-resolution binding attached.

    `status`/`target_id` mirror `resolution`; convenience accessors keep rule code
    honest about the INV-2 choke (only status == 'resolved' may ever match).
    """

    path: str
    name: str
    kind: RefKind
    span: Span
    status: ResolutionStatus
    target_id: str | None

    @property
    def is_eligible(self) -> bool:
        """INV-2 choke, edge-side view: resolved AND bound to a concrete target."""
        return self.status == "resolved" and self.target_id is not None


@dataclass(frozen=True, slots=True)
class InheritanceEdge:
    """`child_id` declares `base_name` among its bases (name AS WRITTEN; the v1
    resolver does not bind base names to symbol ids, so this edge is nominal)."""

    child_id: str
    base_name: str


@dataclass(frozen=True, slots=True)
class ClaimGraph:
    """The semantic claims of one changeset side.

    Collections arrive pre-sorted from graph/build.py:
      nodes         by (id,)
      dep_edges     by (path, span.start_line, span.start_col, name, target_id)
      inherits_edges by (child_id, base_name)
      source_paths  by (path,)
    Do not rely on dict/list insertion order anywhere downstream; re-sort instead.
    """

    ref: str
    nodes: tuple[SymbolNode, ...]
    dep_edges: tuple[DependencyEdge, ...]
    inherits_edges: tuple[InheritanceEdge, ...]
    source_paths: tuple[str, ...]

    def node(self, symbol_id: str) -> SymbolNode | None:
        """Linear scan is intentional: graphs are small and this keeps the model
        free of derived mutable state. Hot paths build their own index once."""
        for n in self.nodes:
            if n.id == symbol_id:
                return n
        return None

    def eligible_deps(self) -> tuple[DependencyEdge, ...]:
        """Edges that may EVER produce a conflict (INV-2 choke, graph-side view)."""
        return tuple(e for e in self.dep_edges if e.is_eligible)

    @property
    def unresolved_dep_count(self) -> int:
        """Strictly status == 'unresolved'. External/ambiguous are reported via
        eligible_deps()/dep_edges statuses -- never conflated."""
        return sum(1 for e in self.dep_edges if e.status == "unresolved")
