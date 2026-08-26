"""Claim-graph builder: resolved FileFacts[] -> ClaimGraph (S4-owned).

Consumes post-Resolver FileFacts (language-agnostic -- the engine never learns which
extractor produced them) and projects them into the claim graph:

  nodes          = declared symbols (first declaration wins on duplicate ids, chosen
                   deterministically by (source_path, span) canonical file order)
  dep_edges      = every use-site with its resolution status attached
  inherits_edges = one edge per declared base name

Version gating (INV-6): facts whose format_version differs from semlock.ir.version
are REFUSED, never guessed at.
"""
from __future__ import annotations

from collections.abc import Iterable

from semlock.graph.model import (
    ClaimGraph,
    DependencyEdge,
    InheritanceEdge,
    SymbolNode,
)
from semlock.ir.model import FileFacts
from semlock.ir.version import FORMAT_VERSION


class VersionMismatchError(ValueError):
    """Raised when input facts carry a format_version this build cannot trust."""


def _check_version(facts: FileFacts) -> None:
    if facts.format_version != FORMAT_VERSION:
        raise VersionMismatchError(
            f"{facts.path}: format_version {facts.format_version!r} != supported "
            f"{FORMAT_VERSION!r} (INV-6: refuse, never guess)"
        )


def build_claim_graph(
    files: Iterable[FileFacts], ref: str | None = None
) -> ClaimGraph:
    """Build the claim graph for one changeset side.

    `ref` defaults to the (uniform) FileFacts.ref of the inputs; passing an explicit
    label is useful when a side spans several per-file ref annotations.
    """
    ordered = sorted(files, key=lambda f: f.path)
    seen_refs: set[str] = set()
    for facts in ordered:
        _check_version(facts)
        seen_refs.add(facts.ref)

    nodes_by_id: dict[str, SymbolNode] = {}
    dep_edges: list[DependencyEdge] = []
    inherits: list[InheritanceEdge] = []
    paths: list[str] = []

    for facts in ordered:
        paths.append(facts.path)
        for sym in facts.symbols:
            node = SymbolNode(
                id=sym.id,
                name=sym.name,
                kind=sym.kind,
                span=sym.span,
                exports=sym.exports,
                source_path=facts.path,
                bases=sym.bases,
                signature=sym.signature,
                members=sym.members,
            )
            # Duplicate ids across files are malformed input; first declaration in
            # canonical (path, then IR symbol order) wins -- deterministic (INV-1).
            nodes_by_id.setdefault(sym.id, node)
            for base_name in sym.bases:
                inherits.append(
                    InheritanceEdge(child_id=sym.id, base_name=base_name)
                )
        for r in facts.refs:
            dep_edges.append(
                DependencyEdge(
                    path=facts.path,
                    name=r.name,
                    kind=r.kind,
                    span=r.span,
                    status=r.resolution.status,
                    target_id=r.resolution.target_id,
                )
            )

    nodes = tuple(sorted(nodes_by_id.values(), key=lambda n: n.id))
    edges = tuple(
        sorted(
            dep_edges,
            key=lambda e: (
                e.path,
                e.span.start_line,
                e.span.start_col,
                e.name,
                e.target_id or "",
            ),
        )
    )
    inherits_sorted = tuple(
        sorted(inherits, key=lambda i: (i.child_id, i.base_name))
    )
    graph_ref = ref if ref is not None else _common_ref(seen_refs)
    return ClaimGraph(
        ref=graph_ref,
        nodes=nodes,
        dep_edges=edges,
        inherits_edges=inherits_sorted,
        source_paths=tuple(sorted(paths)),
    )


def _common_ref(seen_refs: set[str]) -> str:
    if len(seen_refs) == 1:
        return next(iter(seen_refs))
    # Mixed refs on one side: refuse rather than mislabel provenance.
    joined = ", ".join(sorted(seen_refs))
    raise ValueError(f"files carry mixed refs; pass ref= explicitly: {joined}")
