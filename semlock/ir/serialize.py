"""Canonical JSON serialization of FileFacts, validated against schema/ir.schema.json.

Determinism (INV-1/INV-5): explicit key order matching schema property order;
symbols/members/refs emitted in canonical sort order; UTF-8, 2-space indent, trailing
newline. The validator is a stdlib-only subset evaluator covering exactly the JSON
Schema constructs used by ir.schema.json — no third-party dependency (Constitution §9).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final, cast

from semlock.ir.model import (
    FileFacts,
    Member,
    Param,
    Ref,
    Resolution,
    Signature,
    Span,
    Symbol,
)

_SCHEMA_PATH: Final[Path] = (
    Path(__file__).resolve().parents[2] / "schema" / "ir.schema.json"
)


class SerializationError(ValueError):
    """Raised when JSON does not validate against schema/ir.schema.json."""


# ---------------------------------------------------------------- schema validation


def load_schema() -> dict[str, Any]:
    with _SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        loaded: Any = json.load(fh)
    return cast("dict[str, Any]", loaded)


_TYPE_MAP: Final[dict[str, type | tuple[type, ...]]] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


def _check_type(value: Any, expected: str) -> bool:
    typ = _TYPE_MAP[expected]
    if expected == "integer" and isinstance(value, bool):
        return False
    if expected == "boolean":
        return isinstance(value, bool)
    return isinstance(value, typ)


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node  # type: ignore[no-any-return]


def _validate(
    value: Any, schema: dict[str, Any], root: dict[str, Any], where: str
) -> list[str]:
    errors: list[str] = []

    def fail(msg: str) -> None:
        errors.append(f"{where}: {msg}")

    if "const" in schema and value != schema["const"]:
        fail(f"expected const {schema['const']!r}, got {value!r}")
        return errors
    if "enum" in schema and value not in schema["enum"]:
        fail(f"{value!r} not in enum {schema['enum']!r}")
        return errors

    if "$ref" in schema:
        errors.extend(
            _validate(value, _resolve_ref(root, schema["$ref"]), root, where)
        )
        return errors

    if "oneOf" in schema:
        ok = sum(not _validate(value, sub, root, where) for sub in schema["oneOf"])
        if ok != 1:
            fail(f"exactly-one-of violated ({ok} matched)")
        return errors

    if "allOf" in schema:
        for sub in schema["allOf"]:
            errors.extend(_validate(value, sub, root, where))
        if "if" in schema:
            if not _validate(value, schema["if"], root, where):
                if "then" in schema:
                    errors.extend(_validate(value, schema["then"], root, where))

    declared = schema.get("type")
    types = [declared] if isinstance(declared, str) else (declared or [])
    if types and not any(_check_type(value, t) for t in types):
        fail(f"expected type {types}, got {type(value).__name__}")
        return errors

    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                fail(f"missing required property {req!r}")
        props = schema.get("properties", {})
        extra_allowed = schema.get("additionalProperties", True)
        for key, sub in props.items():
            if key in value:
                errors.extend(_validate(value[key], sub, root, f"{where}.{key}"))
        if extra_allowed is False:
            for key in value:
                if key not in props:
                    fail(f"unexpected property {key!r}")

    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(_validate(item, schema["items"], root, f"{where}[{i}]"))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            fail(f"shorter than minLength={schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            fail(f"{value!r} does not match pattern {schema['pattern']!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            fail(f"{value} < minimum {schema['minimum']}")

    return errors


# ------------------------------------------------------------- canonical sort orders


def symbol_sort_key(symbol: Symbol) -> tuple[int, int, str]:
    return (symbol.span.start_line, symbol.span.start_col, symbol.id)


def member_sort_key(member: Member) -> tuple[str]:
    return (member.name,)


def ref_sort_key(ref: Ref) -> tuple[int, int, str]:
    return (ref.span.start_line, ref.span.start_col, ref.name)


# ------------------------------------------------------------------- to_json / dicts


def span_to_dict(span: Span) -> dict[str, Any]:
    return {
        "start_line": span.start_line,
        "start_col": span.start_col,
        "end_line": span.end_line,
        "end_col": span.end_col,
    }


def param_to_dict(param: Param) -> dict[str, Any]:
    return {
        "name": param.name,
        "position": param.position,
        "kind": param.kind,
        "type_annotation": param.type_annotation,
        "has_default": param.has_default,
    }


def signature_to_dict(signature: Signature) -> dict[str, Any]:
    return {
        "params": [param_to_dict(p) for p in signature.params],
        "return_type": signature.return_type,
    }


def member_to_dict(member: Member) -> dict[str, Any]:
    return {
        "name": member.name,
        "type_annotation": member.type_annotation,
        "span": span_to_dict(member.span),
    }


def symbol_to_dict(symbol: Symbol) -> dict[str, Any]:
    return {
        "id": symbol.id,
        "name": symbol.name,
        "kind": symbol.kind,
        "span": span_to_dict(symbol.span),
        "exports": symbol.exports,
        "bases": list(symbol.bases),
        "signature": (
            signature_to_dict(symbol.signature) if symbol.signature else None
        ),
        "members": [
            member_to_dict(m) for m in sorted(symbol.members, key=member_sort_key)
        ],
    }


def resolution_to_dict(resolution: Resolution) -> dict[str, Any]:
    return {"status": resolution.status, "target_id": resolution.target_id}


def ref_to_dict(ref: Ref) -> dict[str, Any]:
    return {
        "name": ref.name,
        "kind": ref.kind,
        "span": span_to_dict(ref.span),
        "resolution": resolution_to_dict(ref.resolution),
    }


def file_facts_to_dict(facts: FileFacts) -> dict[str, Any]:
    """Canonical dict: schema property order, canonical collection order (INV-5)."""
    return {
        "format_version": facts.format_version,
        "path": facts.path,
        "language": facts.language,
        "ref": facts.ref,
        "symbols": [
            symbol_to_dict(s) for s in sorted(facts.symbols, key=symbol_sort_key)
        ],
        "refs": [ref_to_dict(r) for r in sorted(facts.refs, key=ref_sort_key)],
    }


def to_json(facts: FileFacts, schema: dict[str, Any] | None = None) -> str:
    payload = file_facts_to_dict(facts)
    root = schema or load_schema()
    errors = _validate(payload, root, root, "$")
    if errors:
        raise SerializationError("; ".join(errors))
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


# ------------------------------------------------------------------ from_json / parse


def _span_from_dict(d: dict[str, Any]) -> Span:
    return Span(
        start_line=d["start_line"],
        start_col=d["start_col"],
        end_line=d["end_line"],
        end_col=d["end_col"],
    )


def _param_from_dict(d: dict[str, Any]) -> Param:
    return Param(
        name=d["name"],
        position=d["position"],
        kind=d["kind"],
        type_annotation=d["type_annotation"],
        has_default=d["has_default"],
    )


def _signature_from_dict(d: dict[str, Any]) -> Signature:
    return Signature(
        params=tuple(_param_from_dict(p) for p in d["params"]),
        return_type=d["return_type"],
    )


def _member_from_dict(d: dict[str, Any]) -> Member:
    return Member(d["name"], d["type_annotation"], _span_from_dict(d["span"]))


def _symbol_from_dict(d: dict[str, Any]) -> Symbol:
    return Symbol(
        id=d["id"],
        name=d["name"],
        kind=d["kind"],
        span=_span_from_dict(d["span"]),
        exports=d["exports"],
        bases=tuple(d["bases"]),
        signature=_signature_from_dict(d["signature"]) if d["signature"] else None,
        members=tuple(_member_from_dict(m) for m in d["members"]),
    )


def _resolution_from_dict(d: dict[str, Any]) -> Resolution:
    return Resolution(status=d["status"], target_id=d["target_id"])


def _ref_from_dict(d: dict[str, Any]) -> Ref:
    return Ref(
        name=d["name"],
        kind=d["kind"],
        span=_span_from_dict(d["span"]),
        resolution=_resolution_from_dict(d["resolution"]),
    )


def from_json(text: str, schema: dict[str, Any] | None = None) -> FileFacts:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SerializationError(f"invalid JSON: {exc}") from exc
    root = schema or load_schema()
    errors = _validate(payload, root, root, "$")
    if errors:
        raise SerializationError("; ".join(errors))
    try:
        facts = FileFacts(
            format_version=payload["format_version"],
            path=payload["path"],
            language=payload["language"],
            ref=payload["ref"],
            symbols=tuple(_symbol_from_dict(s) for s in payload["symbols"]),
            refs=tuple(_ref_from_dict(r) for r in payload["refs"]),
        )
    except ValueError as exc:
        raise SerializationError(
            f"schema-valid JSON violates IR invariants: {exc}"
        ) from exc
    # Canonicalize in-memory order too, so round-trips are byte-stable.
    return FileFacts(
        format_version=facts.format_version,
        path=facts.path,
        language=facts.language,
        ref=facts.ref,
        symbols=tuple(sorted(facts.symbols, key=symbol_sort_key)),
        refs=tuple(sorted(facts.refs, key=ref_sort_key)),
    )
