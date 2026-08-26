"""Claim-graph builder + deterministic export (S4 unit tests)."""
from __future__ import annotations

import json

import pytest
from builders import facts, ref, symbol

from semlock.graph import (
    CLAIM_GRAPH_FORMAT_VERSION,
    InheritanceEdge,
    VersionMismatchError,
    build_claim_graph,
    claim_graph_to_dict,
    claim_graph_to_json,
)
from semlock.graph.export import validate_payload


def test_nodes_edges_and_sort_orders() -> None:
    g = build_claim_graph(
        (
            facts(
                "b.py",
                symbols=(symbol("m::B", sl=3, bases=("Base",)),),
                refs=(ref("b_use", target="m::B", sl=9),),
            ),
            facts(
                "a.py",
                symbols=(
                    symbol("m::A", sl=2),
                    symbol("m::A.run", kind="method", sl=4),
                ),
                refs=(
                    ref("run", target="m::A.run", sl=7),
                    ref("print", status="external", sl=1),
                ),
            ),
        ),
        ref="side",
    )
    assert [n.id for n in g.nodes] == sorted(n.id for n in g.nodes)
    assert [n.id for n in g.nodes] == ["m::A", "m::A.run", "m::B"]
    assert all(
        e.path <= f.path
        for e, f in zip(g.dep_edges, g.dep_edges[1:], strict=False)
    )
    assert g.dep_edges[0].target_id is None  # external ref kept, status recorded
    assert list(g.inherits_edges) == [InheritanceEdge("m::B", "Base")]
    assert g.source_paths == ("a.py", "b.py")
    assert g.ref == "side"
    # INV-2 view: only resolved edges are eligible.
    eligible = g.eligible_deps()
    assert len(eligible) == 2 and all(e.is_eligible for e in eligible)
    assert g.unresolved_dep_count == 0  # external != unresolved; both non-resolved:
    assert sum(1 for e in g.dep_edges if e.status == "external") == 1


def test_version_gate_refuses_mismatch() -> None:
    bad = facts("x.py", symbols=())
    object.__setattr__(bad, "format_version", "9.9.9")
    with pytest.raises(VersionMismatchError):
        build_claim_graph((bad,))


def test_duplicate_id_resolved_by_canonical_path_order() -> None:
    """Same id in two files: first declaration in sorted-path order wins, and the
    outcome cannot depend on input iteration order."""
    early = symbol("m::Dup", sl=5)
    late = symbol("m::Dup", sl=6)
    forward = build_claim_graph(
        (facts("a.py", symbols=(early,)), facts("z.py", symbols=(late,)))
    )
    backward = build_claim_graph(
        (facts("z.py", symbols=(late,)), facts("a.py", symbols=(early,)))
    )
    assert len(forward.nodes) == len(backward.nodes) == 1
    assert forward.nodes[0].source_path == backward.nodes[0].source_path == "a.py"
    assert forward.nodes[0].span.start_line == 5


def test_export_is_schema_shaped_and_byte_deterministic() -> None:
    files = (
        facts(
            "pkg/models.py",
            symbols=(symbol("pkg.models::User", sl=3),),
            refs=(ref("User", kind="import", target="pkg.models::User", sl=1),),
        ),
    )
    j1 = claim_graph_to_json(build_claim_graph(files))
    j2 = claim_graph_to_json(build_claim_graph(files))
    assert j1 == j2  # INV-1: byte-identical reruns

    payload = json.loads(j1)
    assert validate_payload(payload) == []
    assert list(payload.keys()) == [
        "format_version",
        "ir_format_version",
        "ref",
        "nodes",
        "depends_on",
        "inherits",
    ]
    assert payload["format_version"] == CLAIM_GRAPH_FORMAT_VERSION
    node = payload["nodes"][0]
    assert list(node.keys()) == [
        "id",
        "name",
        "kind",
        "exports",
        "source_path",
        "span",
        "bases",
        "signature",
        "members",
    ]
    edge = payload["depends_on"][0]
    assert list(edge.keys()) == ["path", "name", "kind", "status", "target_id", "span"]


def test_export_validator_catches_broken_payloads() -> None:
    assert validate_payload({"nope": True}) != []
    payload = claim_graph_to_dict(
        build_claim_graph((facts("a.py", symbols=(symbol("m::A"),)),))
    )
    assert validate_payload(payload) == []
    payload["depends_on"].append(
        {"path": "a.py", "name": "x", "kind": "call", "status": "resolved",
         "target_id": None, "span": {"start_line": 1, "start_col": 0,
                                     "end_line": 1, "end_col": 1}}
    )
    errors = validate_payload(payload)
    assert any("INV-2" in e for e in errors)


def test_export_works_without_conflict_evaluation() -> None:
    """ADR-0003 intent: the graph dump is an independent artifact."""
    files = (facts("a.py", symbols=(symbol("m::A"),)),)
    graph = build_claim_graph(files)
    dump = claim_graph_to_json(graph)  # no evaluate() anywhere in scope
    assert '"ref"' in dump
