"""Claim-graph package (S4-owned): model, builder, deterministic export.

Public API:
    build_claim_graph(files, ref=None) -> ClaimGraph   # semlock.graph.build
    claim_graph_to_json(graph) -> str                  # semlock.graph.export
Consumes resolved FileFacts; never imports extractor/resolver internals.
"""
from semlock.graph.build import VersionMismatchError, build_claim_graph
from semlock.graph.export import (
    CLAIM_GRAPH_FORMAT_VERSION,
    ClaimGraphExportError,
    claim_graph_to_dict,
    claim_graph_to_json,
)
from semlock.graph.model import (
    ClaimGraph,
    DependencyEdge,
    InheritanceEdge,
    SymbolNode,
)

__all__ = [
    "CLAIM_GRAPH_FORMAT_VERSION",
    "ClaimGraph",
    "ClaimGraphExportError",
    "DependencyEdge",
    "InheritanceEdge",
    "SymbolNode",
    "VersionMismatchError",
    "build_claim_graph",
    "claim_graph_to_dict",
    "claim_graph_to_json",
]
