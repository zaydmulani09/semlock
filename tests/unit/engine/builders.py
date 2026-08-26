"""Compact IR builders for S4 engine unit tests. Tests own fixtures through code
here (mocks/ itself is S1-owned and untouched)."""
from __future__ import annotations

from semlock.ir.model import (
    FileFacts,
    Member,
    Param,
    ParamKind,
    Ref,
    RefKind,
    Resolution,
    ResolutionStatus,
    Signature,
    Span,
    Symbol,
    SymbolKind,
)
from semlock.ir.version import FORMAT_VERSION


def span(
    sl: int, sc: int = 0, el: int | None = None, ec: int = 10
) -> Span:
    return Span(
        start_line=sl,
        start_col=sc,
        end_line=el if el is not None else sl,
        end_col=ec,
    )


def param(
    name: str,
    position: int = 0,
    type_annotation: str | None = None,
    has_default: bool = False,
    kind: ParamKind = "positional",
) -> Param:
    return Param(
        name=name,
        position=position,
        kind=kind,
        type_annotation=type_annotation,
        has_default=has_default,
    )


def sig(
    params: tuple[Param, ...] = (), return_type: str | None = None
) -> Signature:
    return Signature(params=params, return_type=return_type)


def member(name: str, type_annotation: str | None = None, sl: int = 4) -> Member:
    return Member(name=name, type_annotation=type_annotation, span=span(sl, 4))


def symbol(
    symbol_id: str,
    name: str | None = None,
    kind: SymbolKind = "function",
    exports: bool = True,
    sl: int = 2,
    signature: Signature | None = None,
    members: tuple[Member, ...] = (),
    bases: tuple[str, ...] = (),
) -> Symbol:
    return Symbol(
        id=symbol_id,
        name=name or symbol_id.rsplit("::", 1)[-1].rsplit(".", 1)[-1],
        kind=kind,
        span=span(sl),
        exports=exports,
        bases=bases,
        signature=signature,
        members=members,
    )


def resolution(
    status: ResolutionStatus, target_id: str | None = None
) -> Resolution:
    """Model-enforced: only `resolved` may carry a target_id."""
    effective_target = target_id if status == "resolved" else None
    return Resolution(status=status, target_id=effective_target)


def ref(
    name: str,
    kind: RefKind = "call",
    target: str | None = None,
    status: ResolutionStatus | None = None,
    sl: int = 5,
    col: int = 0,
    module_specifier: str | None = None,
    imported_name: str | None = None,
) -> Ref:
    effective_status: ResolutionStatus
    if status is not None:
        effective_status = status
    else:
        effective_status = "resolved" if target else "unresolved"
    return Ref(
        name=name,
        kind=kind,
        span=span(sl, col),
        resolution=resolution(effective_status, target),
        module_specifier=module_specifier,
        imported_name=imported_name,
    )


def facts(
    path: str,
    symbols: tuple[Symbol, ...] = (),
    refs: tuple[Ref, ...] = (),
    ref_label: str = "head",
    language: str = "python",
) -> FileFacts:
    canonical_symbols = tuple(
        sorted(
            symbols,
            key=lambda s: (s.span.start_line, s.span.start_col, s.id),
        )
    )
    canonical_refs = tuple(
        sorted(refs, key=lambda r: (r.span.start_line, r.span.start_col, r.name))
    )
    return FileFacts(
        format_version=FORMAT_VERSION,
        path=path,
        language=language,  # type: ignore[arg-type]
        ref=ref_label,
        symbols=canonical_symbols,
        refs=canonical_refs,
    )
