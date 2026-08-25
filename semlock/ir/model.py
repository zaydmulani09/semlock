"""FileFacts IR — implemented VERBATIM from docs/IR_CONTRACT.md (v0.1.0, PROVISIONAL).

Invariants enforced here: INV-3 (span semantics), INV-4 (frozen/tuples), and the
Resolution consistency rule backing INV-2 (only `resolved` carries a target_id).
Serialization lives in semlock.ir.serialize; this module is pure data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

ParamKind = Literal["positional", "keyword_only", "varargs", "kwargs"]
SymbolKind = Literal[
    "function", "method", "class", "interface", "type_alias", "variable"
]
RefKind = Literal["call", "read", "write", "import", "attribute"]
ResolutionStatus = Literal["unresolved", "resolved", "external", "ambiguous"]
Language = Literal["python", "typescript"]

LANGUAGES: Final[tuple[str, ...]] = ("python", "typescript")
UNRESOLVED: Final = "unresolved"
RESOLVED: Final = "resolved"


@dataclass(frozen=True, slots=True)
class Span:
    """Half-open [start, end): lines 1-indexed, cols 0-indexed (INV-3)."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int

    def __post_init__(self) -> None:
        if self.start_line < 1 or self.end_line < 1:
            raise ValueError(f"Span lines are 1-indexed: {self}")
        if self.start_col < 0 or self.end_col < 0:
            raise ValueError(f"Span cols are 0-indexed: {self}")


@dataclass(frozen=True, slots=True)
class Param:
    name: str
    position: int
    kind: ParamKind
    type_annotation: str | None
    has_default: bool

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Param.name must be non-empty")
        if self.position < 0:
            raise ValueError(f"Param.position must be >= 0: {self}")


@dataclass(frozen=True, slots=True)
class Signature:
    params: tuple[Param, ...] = field(default=())
    return_type: str | None = None


@dataclass(frozen=True, slots=True)
class Member:
    """Class/interface field (field_removed surface)."""

    name: str
    type_annotation: str | None
    span: Span

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Member.name must be non-empty")


@dataclass(frozen=True, slots=True)
class Symbol:
    id: str
    name: str
    kind: SymbolKind
    span: Span
    exports: bool
    bases: tuple[str, ...] = ()
    signature: Signature | None = None
    members: tuple[Member, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError(f"Symbol.id and .name must be non-empty: {self!r}")


@dataclass(frozen=True, slots=True)
class Resolution:
    """Binding of a use-site to a definition. Only Extractors' downstream Resolver may
    upgrade status away from 'unresolved'; only status == 'resolved' carries target_id.
    """

    status: ResolutionStatus = UNRESOLVED
    target_id: str | None = None

    def __post_init__(self) -> None:
        if self.status == RESOLVED:
            if not self.target_id:
                raise ValueError("Resolution(resolved) requires non-empty target_id")
        elif self.target_id is not None:
            raise ValueError(
                f"target_id must be None unless status == 'resolved': {self!r}"
            )


@dataclass(frozen=True, slots=True)
class Ref:
    """Use-site awaiting resolution. Constructed unresolved by Extractors.

    0.2.0: `module_specifier` carries the import source as written ("./config",
    "pkg.models") for kind="import" refs; None otherwise. `imported_name` carries the
    ORIGINAL exported name when the local binding is aliased ("useState" for
    `import { useState as useSt }`); None when not aliased or not an import.
    """

    name: str
    kind: RefKind
    span: Span
    resolution: Resolution = Resolution()
    module_specifier: str | None = None
    imported_name: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Ref.name must be non-empty")
        if self.imported_name is not None and self.module_specifier is None:
            raise ValueError(
                "Ref.imported_name requires module_specifier (an aliased import "
                f"must know its source): {self!r}"
            )


@dataclass(frozen=True, slots=True)
class FileFacts:
    format_version: str
    path: str
    language: Language
    ref: str
    symbols: tuple[Symbol, ...] = ()
    refs: tuple[Ref, ...] = ()

    def __post_init__(self) -> None:
        if "\\" in self.path:
            raise ValueError(
                f"path must be repo-relative with '/' separators: {self.path!r}"
            )
        if not self.ref:
            raise ValueError("FileFacts.ref must be non-empty")
        if self.language not in LANGUAGES:
            raise ValueError(f"unknown language {self.language!r}")
