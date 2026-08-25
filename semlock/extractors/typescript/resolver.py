"""TypeScript resolver (S3): bind use-site refs to canonical member/symbol ids.

Fixed rule: a field/property/method reference resolves to the MEMBER's own
canonical symbol id (``module_path::Owner.member``) -- never a suffixed parent
id. Member symbols are emitted by the extractor precisely so this binding is a
direct id join.

Statuses (INV-2 downstream): ``resolved`` iff exactly ONE candidate symbol id
matches across the changeset side under the binding rules below;
``ambiguous`` iff >= 2 DISTINCT ids match; ``external`` for well-known JS/TS
globals; ``unresolved`` otherwise. UNRESOLVED IS NEVER A MATCH.

Known v0.1.0 limits (honest): Ref carries no module-specifier/alias/receiver-
type fields, so (a) import binding falls back to unique-name matching rather
than specifier-directed lookup, (b) aliased/default imports whose local name
differs from the original stay unresolved, and (c) member refs on annotated
receivers cannot use the receiver's declared type. All three need the 0.2.0
IR revision (interface-request filed).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import ClassVar

from semlock.extractors.base import Resolver
from semlock.extractors.typescript._paths import module_path_of
from semlock.ir.model import (
    FileFacts,
    Ref,
    Resolution,
    ResolutionStatus,
)

_GLOBAL_IDENTIFIERS = frozenset(
    {
        "Promise", "Array", "Map", "Set", "WeakMap", "WeakSet", "Object",
        "Function", "Boolean", "String", "Number", "Date", "RegExp", "Error",
        "JSON", "Math", "console", "window", "document", "globalThis",
        "Symbol",
    }
)


class TypeScriptResolver(Resolver):
    language: ClassVar[str] = "typescript"

    def resolve(self, files: tuple[FileFacts, ...]) -> tuple[FileFacts, ...]:
        index = _SymbolIndex.build(files)
        resolved: list[FileFacts] = []
        for facts in files:
            own_module = module_path_of(facts.path)
            new_refs = tuple(
                self._resolve_ref(ref, facts, own_module, index) for ref in facts.refs
            )
            resolved.append(
                FileFacts(
                    format_version=facts.format_version,
                    path=facts.path,
                    language=facts.language,
                    ref=facts.ref,
                    symbols=facts.symbols,
                    refs=new_refs,
                )
            )
        return tuple(resolved)

    def _resolve_ref(
        self,
        ref: Ref,
        facts: FileFacts,
        own_module: str,
        index: _SymbolIndex,
    ) -> Ref:
        if ref.resolution.status != "unresolved":
            return ref
        if ref.kind == "import":
            status, target = self._bind_unique(
                index.exported_top_level.get(ref.name, ())
            )
        elif ref.kind == "call":
            if ref.name in _GLOBAL_IDENTIFIERS:
                return _with(ref, Resolution(status="external"))
            candidates: Sequence[str] = tuple(index.top_level.get(ref.name, ()))
            candidates = (
                *candidates,
                *index.exported_top_level.get(ref.name, ()),
                *index.members.get(ref.name, ()),
            )
            status, target = self._bind_unique(candidates)
        elif ref.kind == "read":
            if ref.name in _GLOBAL_IDENTIFIERS:
                return _with(ref, Resolution(status="external"))
            candidates = tuple(index.top_level.get(ref.name, ()))
            candidates = (
                *candidates,
                *index.exported_top_level.get(ref.name, ()),
            )
            status, target = self._bind_unique(candidates)
        elif ref.kind in ("attribute", "write"):
            status, target = self._bind_unique(index.members.get(ref.name, ()))
        else:
            status, target = "unresolved", None
        if status == "resolved" and target is not None:
            return _with(ref, Resolution(status="resolved", target_id=target))
        return _with(ref, Resolution(status=status))

    @staticmethod
    def _bind_unique(
        candidate_ids: Sequence[str],
    ) -> tuple[ResolutionStatus, str | None]:
        distinct = sorted(set(candidate_ids))
        if len(distinct) == 1:
            return "resolved", distinct[0]
        if len(distinct) > 1:
            return "ambiguous", None
        return "unresolved", None


def _with(ref: Ref, resolution: Resolution) -> Ref:
    return Ref(name=ref.name, kind=ref.kind, span=ref.span, resolution=resolution)


class _SymbolIndex:
    """Name -> candidate symbol-id tuples over one changeset side."""

    def __init__(
        self,
        exported_top_level: dict[str, tuple[str, ...]],
        top_level: dict[str, tuple[str, ...]],
        members: dict[str, tuple[str, ...]],
    ) -> None:
        self.exported_top_level = exported_top_level
        self.top_level = top_level
        self.members = members

    @classmethod
    def build(cls, files: tuple[FileFacts, ...]) -> _SymbolIndex:
        exported: dict[str, list[str]] = defaultdict(list)
        top: dict[str, list[str]] = defaultdict(list)
        members: dict[str, list[str]] = defaultdict(list)
        for facts in files:
            for symbol in facts.symbols:
                qualified = symbol.id.split("::", 1)[1] if "::" in symbol.id else ""
                if "." in qualified:
                    members[symbol.name].append(symbol.id)
                else:
                    top[symbol.name].append(symbol.id)
                    if symbol.exports:
                        exported[symbol.name].append(symbol.id)
        return cls(
            exported_top_level={k: tuple(v) for k, v in exported.items()},
            top_level={k: tuple(v) for k, v in top.items()},
            members={k: tuple(v) for k, v in members.items()},
        )


def measure_resolution(
    files: tuple[FileFacts, ...],
) -> dict[str, float | dict[str, dict[str, int]]]:
    """Resolution coverage per Constitution §4: fraction of refs with status
    == 'resolved'. External/unresolved/ambiguous reported separately."""
    per_kind: dict[str, dict[str, int]] = defaultdict(
        lambda: {"resolved": 0, "external": 0, "ambiguous": 0, "unresolved": 0}
    )
    for facts in files:
        for ref in facts.refs:
            per_kind[ref.kind][ref.resolution.status] += 1
    total = sum(sum(counts.values()) for counts in per_kind.values())
    resolved_total = sum(counts["resolved"] for counts in per_kind.values())
    coverage = (resolved_total / total) if total else 1.0
    detail = {kind: dict(counts) for kind, counts in sorted(per_kind.items())}
    return {"coverage": coverage, "refs": total, "by_kind": detail}
