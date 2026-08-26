"""Deterministic claim-graph export (S4-owned).

`semlock graph` consumes this WITHOUT running conflict evaluation: the graph dump is
an independent, inspectable artifact (ADR-0003 intent -- the engine must never be a
prerequisite for seeing what a side claims).

Wire shape (v0.1.0; S1 to freeze as schema/claim-graph.schema.json -- S4 drives the
shape, S1 owns schema/):

    {
      "format_version": "<claim-graph format>",
      "ir_format_version": "<IR the facts came from>",
      "ref": "<changeset side label>",
      "nodes": [ {id, name, kind, exports, source_path,
                  span{start_line,start_col,end_line,end_col},
                  bases[], signature|null{params[],return_type}, members[]} ],
      "depends_on": [ {path, name, kind, status, target_id, span{...}} ],
      "inherits": [ {child_id, base_name} ]
    }

Determinism (INV-1/INV-5): fixed key order as above; nodes by id, depends_on by
(path, span, name, target_id), inherits by (child_id, base_name), members by name;
UTF-8, 2-space indent, trailing newline. Identical inputs => byte-identical output.
"""
from __future__ import annotations

import json
from typing import Any, Final

from semlock.graph.model import (
    ClaimGraph,
    DependencyEdge,
    InheritanceEdge,
    SymbolNode,
)
from semlock.ir.model import Member
from semlock.ir.serialize import (
    member_sort_key,
    signature_to_dict,
    span_to_dict,
)
from semlock.ir.version import FORMAT_VERSION

CLAIM_GRAPH_FORMAT_VERSION: Final = "0.1.0"


class ClaimGraphExportError(ValueError):
    """Raised when a payload does not match the claim-graph wire shape."""


def symbol_node_to_dict(node: SymbolNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "kind": node.kind,
        "exports": node.exports,
        "source_path": node.source_path,
        "span": span_to_dict(node.span),
        "bases": list(node.bases),
        "signature": (
            signature_to_dict(node.signature) if node.signature else None
        ),
        "members": [
            _member_to_dict(m) for m in sorted(node.members, key=member_sort_key)
        ],
    }


def _member_to_dict(member: Member) -> dict[str, Any]:
    return {
        "name": member.name,
        "type_annotation": member.type_annotation,
        "span": span_to_dict(member.span),
    }


def dependency_edge_to_dict(edge: DependencyEdge) -> dict[str, Any]:
    return {
        "path": edge.path,
        "name": edge.name,
        "kind": edge.kind,
        "status": edge.status,
        "target_id": edge.target_id,
        "span": span_to_dict(edge.span),
    }


def inheritance_edge_to_dict(edge: InheritanceEdge) -> dict[str, Any]:
    return {"child_id": edge.child_id, "base_name": edge.base_name}


def claim_graph_to_dict(graph: ClaimGraph) -> dict[str, Any]:
    """Canonical dict in fixed key order (INV-5). Inputs arrive pre-sorted from
    graph/build.py; members are re-sorted defensively so export never trusts
    upstream ordering."""
    return {
        "format_version": CLAIM_GRAPH_FORMAT_VERSION,
        "ir_format_version": FORMAT_VERSION,
        "ref": graph.ref,
        "nodes": [
            symbol_node_to_dict(n) for n in sorted(graph.nodes, key=lambda n: n.id)
        ],
        "depends_on": [
            dependency_edge_to_dict(e) for e in graph.dep_edges
        ],
        "inherits": [
            inheritance_edge_to_dict(i) for i in graph.inherits_edges
        ],
    }


def claim_graph_to_json(graph: ClaimGraph) -> str:
    payload = claim_graph_to_dict(graph)
    errors = validate_payload(payload)
    if errors:
        raise ClaimGraphExportError("; ".join(errors))
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------- shape validation


def validate_payload(payload: Any) -> list[str]:
    """Structural checks for exactly the shape documented above. Stdlib-only; when
    S1 freezes schema/claim-graph.schema.json the JSON-Schema validator replaces
    this without changing the wire bytes."""
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(f"$: {msg}")

    if not isinstance(payload, dict):
        fail("payload must be an object")
        return errors
    for key in ("format_version", "ir_format_version", "ref"):
        if not isinstance(payload.get(key), str):
            fail(f"{key} must be a string")
    if not isinstance(payload.get("nodes"), list):
        fail("nodes must be an array")
        return errors
    if not isinstance(payload.get("depends_on"), list):
        fail("depends_on must be an array")
        return errors
    if not isinstance(payload.get("inherits"), list):
        fail("inherits must be an array")
        return errors
    ids: set[str] = set()
    for i, node in enumerate(payload["nodes"]):
        where = f"nodes[{i}]"
        errs = _validate_node(node, where)
        errors.extend(errs)
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            if node["id"] in ids:
                errors.append(f"{where}: duplicate id {node['id']!r}")
            ids.add(node["id"])
    for i, edge in enumerate(payload["depends_on"]):
        errors.extend(_validate_dep_edge(edge, f"depends_on[{i}]"))
    for i, edge in enumerate(payload["inherits"]):
        errors.extend(_validate_inherit(edge, f"inherits[{i}]"))
    return errors


def _require_keys(
    value: Any, keys: tuple[str, ...], where: str, errors: list[str]
) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{where}: must be an object")
        return False
    for key in keys:
        if key not in value:
            errors.append(f"{where}: missing required property {key!r}")
    return True


def _validate_span(span: Any, where: str, errors: list[str]) -> None:
    if not _require_keys(
        span,
        ("start_line", "start_col", "end_line", "end_col"),
        where,
        errors,
    ):
        return
    assert isinstance(span, dict)
    for key in ("start_line", "start_col", "end_line", "end_col"):
        v = span[key]
        if not isinstance(v, int) or isinstance(v, bool):
            errors.append(f"{where}.{key}: must be an integer")


def _validate_node(node: Any, where: str) -> list[str]:
    errors: list[str] = []
    if not _require_keys(
        node,
        (
            "id",
            "name",
            "kind",
            "exports",
            "source_path",
            "span",
            "bases",
            "signature",
            "members",
        ),
        where,
        errors,
    ):
        return errors
    assert isinstance(node, dict)
    for key in ("id", "name", "kind", "source_path"):
        if not isinstance(node.get(key), str) or not node.get(key):
            errors.append(f"{where}.{key}: must be a non-empty string")
    if not isinstance(node.get("exports"), bool):
        errors.append(f"{where}.exports: must be a boolean")
    if not isinstance(node.get("bases"), list):
        errors.append(f"{where}.bases: must be an array")
    _validate_span(node.get("span"), f"{where}.span", errors)
    sig = node.get("signature")
    if sig is not None:
        if not _require_keys(
            sig, ("params", "return_type"), f"{where}.signature", errors
        ):
            return errors
        assert isinstance(sig, dict)
        if not isinstance(sig["params"], list):
            errors.append(f"{where}.signature.params: must be an array")
        rt = sig.get("return_type")
        if rt is not None and not isinstance(rt, str):
            errors.append(f"{where}.signature.return_type: must be a string or null")
    if not isinstance(node.get("members"), list):
        errors.append(f"{where}.members: must be an array")
    else:
        for i, m in enumerate(node["members"]):
            mw = f"{where}.members[{i}]"
            if not _require_keys(m, ("name", "type_annotation", "span"), mw, errors):
                continue
            assert isinstance(m, dict)
            if not isinstance(m.get("name"), str) or not m.get("name"):
                errors.append(f"{mw}.name: must be a non-empty string")
            ta = m.get("type_annotation")
            if ta is not None and not isinstance(ta, str):
                errors.append(f"{mw}.type_annotation: must be a string or null")
            _validate_span(m.get("span"), f"{mw}.span", errors)
    return errors


def _validate_dep_edge(edge: Any, where: str) -> list[str]:
    errors: list[str] = []
    if not _require_keys(
        edge,
        ("path", "name", "kind", "status", "target_id", "span"),
        where,
        errors,
    ):
        return errors
    assert isinstance(edge, dict)
    for key in ("path", "name", "kind", "status"):
        if not isinstance(edge.get(key), str) or not edge.get(key):
            errors.append(f"{where}.{key}: must be a non-empty string")
    tid = edge.get("target_id")
    if tid is not None and not isinstance(tid, str):
        errors.append(f"{where}.target_id: must be a string or null")
    if edge.get("status") == "resolved" and not tid:
        errors.append(f"{where}: resolved edge requires non-empty target_id (INV-2)")
    if edge.get("status") != "resolved" and tid is not None:
        errors.append(f"{where}: non-resolved edge must have null target_id (INV-2)")
    _validate_span(edge.get("span"), f"{where}.span", errors)
    return errors


def _validate_inherit(edge: Any, where: str) -> list[str]:
    errors: list[str] = []
    if not _require_keys(edge, ("child_id", "base_name"), where, errors):
        return errors
    assert isinstance(edge, dict)
    for key in ("child_id", "base_name"):
        if not isinstance(edge.get(key), str) or not edge.get(key):
            errors.append(f"{where}.{key}: must be a non-empty string")
    return errors
