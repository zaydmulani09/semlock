"""Python resolver: ref-wide binding of use-sites to stable symbol ids (S2-owned,
per the S2-resolution pairing of ADR-0008).

Every Reference across ALL FileFacts of one changeset side is bound against the
definitions visible in that same side's file set:

- ``resolved``   — a unique concrete definition was reached through deterministic
                   evidence: same-module lookup, imports (normal / aliased /
                   relative / package-path), re-export chains followed to the
                   ORIGINAL symbol id (never a manufactured second symbol),
                   ``__all__``-aware star imports, qualified module paths,
                   declared parameter/local types (receiver typing incl. one
                   inheritance hop), ``self``/``cls`` in methods.
- ``external``   — provably outside the analyzed set: frozen builtin names, or a
                   root imported from a module absent from the file set.
- ``ambiguous``  — two or more equally-ranked candidates (colliding star-import
                   providers, duplicated module paths).
- ``unresolved`` — insufficient static evidence (dynamic constructs, untyped
                   receivers, names plausibly created at runtime). Unresolved is
                   NOT an error and NEVER matches downstream (INV-2).

Non-resolution fields of every FileFact/Ref/Symbol are preserved bit-for-bit;
only ``Ref.resolution`` is upgraded (seam contract, base.py).

Member references bind to the MEMBER's canonical id ``<class_id>.<member>``
(e.g. ``pkg.models::User.email``) — never a suffixed parent id.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import ClassVar, Literal

from semlock.extractors.base import Resolver
from semlock.extractors.python.module_paths import absolutize, module_info
from semlock.ir.model import FileFacts, Ref, Resolution, Symbol
from semlock.ir.version import FORMAT_VERSION

# Frozen builtin names (CPython 3.10 baseline). Literal, not derived at runtime:
# deriving from the running interpreter would leak interpreter version into
# outputs and break INV-1 byte-determinism across machines.
_BUILTINS: frozenset[str] = frozenset(
    {
        "ArithmeticError",
        "AssertionError",
        "AttributeError",
        "BaseException",
        "BaseExceptionGroup",
        "BlockingIOError",
        "BrokenPipeError",
        "BufferError",
        "BytesWarning",
        "ChildProcessError",
        "ConnectionAbortedError",
        "ConnectionError",
        "ConnectionRefusedError",
        "ConnectionResetError",
        "DeprecationWarning",
        "EOFError",
        "Ellipsis",
        "EncodingWarning",
        "EnvironmentError",
        "Exception",
        "FileExistsError",
        "FileNotFoundError",
        "FloatingPointError",
        "FutureWarning",
        "GeneratorExit",
        "IOError",
        "ImportError",
        "ImportWarning",
        "IndentationError",
        "IndexError",
        "InterruptedError",
        "IsADirectoryError",
        "KeyError",
        "KeyboardInterrupt",
        "LookupError",
        "MemoryError",
        "ModuleNotFoundError",
        "NameError",
        "NotADirectoryError",
        "NotImplemented",
        "NotImplementedError",
        "OSError",
        "OverflowError",
        "PendingDeprecationWarning",
        "PermissionError",
        "ProcessLookupError",
        "PythonFinalizationError",
        "RecursionError",
        "ReferenceError",
        "ResourceWarning",
        "RuntimeError",
        "RuntimeWarning",
        "StopAsyncIteration",
        "StopIteration",
        "SyntaxError",
        "SyntaxWarning",
        "SystemError",
        "SystemExit",
        "TabError",
        "TimeoutError",
        "TypeError",
        "UnboundLocalError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "UnicodeError",
        "UnicodeTranslateError",
        "UnicodeWarning",
        "UserWarning",
        "ValueError",
        "Warning",
        "ZeroDivisionError",
        "__build_class__",
        "__debug__",
        "__doc__",
        "__import__",
        "__loader__",
        "__name__",
        "__package__",
        "__spec__",
        "abs",
        "aiter",
        "all",
        "any",
        "ascii",
        "bin",
        "bool",
        "breakpoint",
        "bytearray",
        "bytes",
        "callable",
        "chr",
        "classmethod",
        "compile",
        "complex",
        "copyright",
        "credits",
        "delattr",
        "dict",
        "dir",
        "divmod",
        "enumerate",
        "eval",
        "exec",
        "exit",
        "filter",
        "float",
        "format",
        "frozenset",
        "getattr",
        "globals",
        "hasattr",
        "hash",
        "help",
        "hex",
        "id",
        "input",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "license",
        "list",
        "locals",
        "map",
        "max",
        "memoryview",
        "min",
        "next",
        "object",
        "oct",
        "open",
        "ord",
        "pow",
        "print",
        "property",
        "quit",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "setattr",
        "slice",
        "sorted",
        "staticmethod",
        "str",
        "sum",
        "super",
        "tuple",
        "type",
        "vars",
        "zip",
    }
)


@dataclass(frozen=True)
class _Outcome:
    """Result of a binding attempt."""

    kind: Literal["symbol", "module", "external", "ambiguous", "none"]
    target: str | None = None  # symbol id or bare module path


_SYMBOL = "symbol"
_MODULE = "module"
_EXTERNAL = "external"
_AMBIGUOUS = "ambiguous"
_NONE = "none"

_EXTERNAL_OUTCOME = _Outcome("external")
_NONE_OUTCOME = _Outcome("none")


@dataclass
class _ImportBinding:
    local: str
    origin_written: str
    style: Literal["from", "plain", "star"]


@dataclass
class _ModuleTable:
    """All facts known about ONE module path within the changeset side."""

    module: str
    is_package: bool
    paths: list[str] = dc_field(default_factory=list)
    top_symbols: dict[str, Symbol] = dc_field(default_factory=dict)
    symbol_by_id: dict[str, Symbol] = dc_field(default_factory=dict)
    imports: list[tuple[_ImportBinding, str]] = dc_field(default_factory=list)


@dataclass
class _FileCtx:
    """Per-file resolution context: alias -> absolute binding, last import wins."""

    facts: FileFacts
    table: _ModuleTable
    module: str
    is_package: bool
    aliases: dict[str, _ImportBinding] = dc_field(default_factory=dict)
    alias_abs: dict[str, str] = dc_field(default_factory=dict)
    stars: list[str] = dc_field(default_factory=list)

    def symbols(self) -> tuple[Symbol, ...]:
        return self.facts.symbols


def _parse_import_ref(name: str) -> _ImportBinding | None:
    """Inverse of the extractor's encoding (see extractor.py docstring)."""
    if name.startswith("*="):
        return _ImportBinding("*", name[2:], "star")
    if "~" in name:
        local, written = name.split("~", 1)
        return _ImportBinding(local, written, "plain")
    if "=" in name:
        local, written = name.split("=", 1)
        return _ImportBinding(local, written, "from")
    return None


def _pos(span_line: int, span_col: int) -> tuple[int, int]:
    return (span_line, span_col)


def _contains(outer: Symbol, line: int, col: int) -> bool:
    start = _pos(outer.span.start_line, outer.span.start_col)
    end = _pos(outer.span.end_line, outer.span.end_col)
    return start <= _pos(line, col) < end


class _Resolver:
    def __init__(self, files: tuple[FileFacts, ...]) -> None:
        self._order = files
        for facts in files:
            if facts.format_version != FORMAT_VERSION:
                # INV-6: consumers refuse mismatched versions; never guess.
                raise ValueError(
                    f"{facts.path}: format_version {facts.format_version!r} != "
                    f"supported {FORMAT_VERSION!r} (INV-6)"
                )
        self.tables: dict[str, _ModuleTable] = {}
        self.file_ctxs: dict[str, _FileCtx] = {}  # keyed by facts.path
        for facts in files:
            module, is_package = module_info(facts.path)
            table = self.tables.get(module)
            if table is None:
                table = _ModuleTable(module=module, is_package=is_package)
                self.tables[module] = table
            table.paths.append(facts.path)
            for sym in facts.symbols:
                table.symbol_by_id[sym.id] = sym
                qualified = sym.id.split("::", 1)[1] if "::" in sym.id else sym.id
                if "." not in qualified and sym.name not in table.top_symbols:
                    table.top_symbols[sym.name] = sym
        for facts in files:
            module, is_package = module_info(facts.path)
            table = self.tables[module]
            ctx = _FileCtx(
                facts=facts, table=table, module=module, is_package=is_package
            )
            import_refs = sorted(
                (r for r in facts.refs if r.kind == "import"),
                key=lambda r: (r.span.start_line, r.span.start_col),
            )
            for ref in import_refs:
                binding = _parse_import_ref(ref.name)
                if binding is None:
                    continue
                abs_origin = absolutize(binding.origin_written, module, is_package)
                ctx.aliases[binding.local] = binding
                ctx.alias_abs[binding.local] = abs_origin
                if binding.style == "star" and abs_origin not in ctx.stars:
                    ctx.stars.append(abs_origin)
            self.file_ctxs[facts.path] = ctx

    # ------------------------------------------------------------ public API

    def resolve_all(self) -> tuple[FileFacts, ...]:
        out: list[FileFacts] = []
        for facts in self._order:
            ctx = self.file_ctxs[facts.path]
            new_refs = tuple(self._resolve_ref(ctx, r) for r in facts.refs)
            if new_refs == facts.refs:
                out.append(facts)
                continue
            out.append(
                FileFacts(
                    format_version=facts.format_version,
                    path=facts.path,
                    language=facts.language,
                    ref=facts.ref,
                    symbols=facts.symbols,
                    refs=new_refs,
                )
            )
        return tuple(out)

    # -------------------------------------------------------------- helpers

    def _resolve_ref(self, ctx: _FileCtx, ref: Ref) -> Ref:
        outcome = (
            self._resolve_import(ctx, ref)
            if ref.kind == "import"
            else self._resolve_use(ctx, ref)
        )
        status = {
            _SYMBOL: "resolved",
            _MODULE: "resolved",
            _EXTERNAL: "external",
            _AMBIGUOUS: "ambiguous",
            _NONE: "unresolved",
        }[outcome.kind]
        target = outcome.target if outcome.kind in (_SYMBOL, _MODULE) else None
        resolution = (
            Resolution(status="resolved", target_id=target)
            if status == "resolved"
            else Resolution(status=status)  # type: ignore[arg-type]
        )
        if resolution == ref.resolution:
            return ref
        return Ref(name=ref.name, kind=ref.kind, span=ref.span, resolution=resolution)

    def _resolve_import(self, ctx: _FileCtx, ref: Ref) -> _Outcome:
        binding = _parse_import_ref(ref.name)
        if binding is None:
            return _NONE_OUTCOME
        abs_origin = absolutize(binding.origin_written, ctx.module, ctx.is_package)
        if not abs_origin:
            return _NONE_OUTCOME  # degenerate origin (doctored/degenerate input)
        if binding.style == "plain":
            return self._module_outcome(abs_origin)
        if binding.style == "star":
            return self._module_outcome(abs_origin)
        tail = abs_origin.rsplit(".", 1)[-1]
        base_module = abs_origin[: -(len(tail) + 1)] if "." in abs_origin else ""
        # `from X import Y`: Y may be a symbol in X OR the submodule X.Y.
        return self._lookup_in_module(base_module, tail, frozenset())

    def _is_known_module_prefix(self, module_path: str) -> bool:
        """True when module_path is itself backed by files OR is an ancestor of
        backed modules (PEP 420 namespace packages have no ``__init__.py``)."""
        return any(
            t == module_path or t.startswith(module_path + ".") for t in self.tables
        )

    def _module_outcome(self, module_path: str) -> _Outcome:
        table = self.tables.get(module_path)
        if table is None:
            if self._is_known_module_prefix(module_path):
                return _Outcome("module", module_path)  # namespace package
            return _EXTERNAL_OUTCOME
        if len(table.paths) > 1:
            return _Outcome("ambiguous", None)
        return _Outcome("module", module_path)

    # ------------------------------------------------------- module lookups

    def _lookup_in_module(
        self, module_path: str, name: str, visited: frozenset[tuple[str, str]]
    ) -> _Outcome:
        """Find `name` as exported by `module_path`, following re-export chains
        to the ORIGINAL definition (INV-7 rule: never manufacture a second id)."""
        key = (module_path, name)
        if key in visited:
            return _NONE_OUTCOME  # cyclic re-export: insufficient evidence
        table = self.tables.get(module_path)
        if table is None:
            if module_path and self._is_known_module_prefix(module_path):
                # Namespace package: no own symbols, but submodules may exist.
                sub = f"{module_path}.{name}"
                if sub in self.tables:
                    return _Outcome("module", sub)
                return _NONE_OUTCOME
            return _EXTERNAL_OUTCOME if module_path else _NONE_OUTCOME
        if len(table.paths) > 1:
            return _Outcome("ambiguous", None)
        direct = table.top_symbols.get(name)
        if direct is not None:
            return _Outcome("symbol", direct.id)
        sub = f"{module_path}.{name}" if module_path else name
        if sub in self.tables:
            return _Outcome("module", sub)
        # Re-export chain: explicit from-imports of this name inside the module.
        for facts_path in sorted(table.paths):
            ctx = self.file_ctxs[facts_path]
            binding = ctx.aliases.get(name)
            if (
                binding is not None
                and binding.style == "from"
                and binding.local == name
            ):
                abs_origin = ctx.alias_abs[name]
                tail = abs_origin.rsplit(".", 1)[-1]
                base = abs_origin[: -(len(tail) + 1)] if "." in abs_origin else ""
                outcome = self._lookup_in_module(base, tail, visited | {key})
                if outcome.kind != _NONE:
                    return outcome
        # Star-import aggregation: collect providers of `name`.
        providers: list[_Outcome] = []
        for facts_path in sorted(table.paths):
            ctx = self.file_ctxs[facts_path]
            for star_src in sorted(ctx.stars):
                outcome = self._lookup_in_module(star_src, name, visited | {key})
                if outcome.kind == _AMBIGUOUS:
                    return outcome  # ambiguity propagates; never guess
                if outcome.kind in (_SYMBOL, _MODULE):
                    providers.append(outcome)
        if providers:
            distinct = {p.target for p in providers}
            if len(distinct) == 1:
                return providers[0]
            return _Outcome("ambiguous", None)
        return _NONE_OUTCOME

    # ------------------------------------------------------------ use-sites

    def _resolve_use(self, ctx: _FileCtx, ref: Ref) -> _Outcome:
        segments = ref.name.split(".")
        head, rest = segments[0], segments[1:]
        state = self._bind_head(ctx, ref, head)
        for seg in rest:
            state = self._advance(state, seg)
        return state

    def _bind_head(self, ctx: _FileCtx, ref: Ref, head: str) -> _Outcome:
        # 1) self / cls inside a method -> owning class.
        if head in ("self", "cls"):
            owner = self._owner_class(ctx, ref)
            if owner is not None:
                return _Outcome("symbol", owner.id)
        # 2) Declared receiver typing: params and typed locals of the enclosing
        #    function/method (extractor records both as signature/member data).
        enclosing = self._enclosing_symbol(ctx, ref)
        if enclosing is not None:
            type_name = self._declared_type(enclosing, head)
            if type_name is not None:
                cls_id = self._resolve_type_name(ctx, type_name)
                if cls_id is not None:
                    return _Outcome("symbol", cls_id)
        # 3) Import-bound alias.
        binding = ctx.aliases.get(head)
        if binding is not None:
            abs_origin = ctx.alias_abs[head]
            if binding.style == "plain":
                return self._module_outcome(abs_origin.split(".")[0])
            if binding.style == "star":
                return _NONE_OUTCOME  # wildcard alias is not addressable
            tail = abs_origin.rsplit(".", 1)[-1]
            base = abs_origin[: -(len(tail) + 1)] if "." in abs_origin else ""
            return self._lookup_in_module(base, tail, frozenset())
        # 4) Same-module top-level definition.
        direct = ctx.table.top_symbols.get(head)
        if direct is not None:
            return _Outcome("symbol", direct.id)
        # 5) Builtin -> provably outside the changeset.
        if head in _BUILTINS:
            return _EXTERNAL_OUTCOME
        # 6) Reachable through a star import?
        providers: list[_Outcome] = []
        for star_src in sorted(ctx.stars):
            outcome = self._lookup_in_module(star_src, head, frozenset())
            if outcome.kind == _AMBIGUOUS:
                return outcome  # ambiguity propagates; never guess
            if outcome.kind in (_SYMBOL, _MODULE):
                providers.append(outcome)
        if providers:
            distinct = {p.target for p in providers}
            if len(distinct) == 1:
                return providers[0]
            return _Outcome("ambiguous", None)
        return _NONE_OUTCOME

    def _advance(self, state: _Outcome, seg: str) -> _Outcome:
        if state.kind in (_EXTERNAL, _AMBIGUOUS, _NONE):
            return state
        if state.kind == _MODULE:
            module_path = state.target or ""
            sub = f"{module_path}.{seg}" if module_path else seg
            if sub in self.tables or self._is_known_module_prefix(sub):
                return self._module_outcome(sub)
            table = self.tables.get(module_path)
            if table is None:
                return _EXTERNAL_OUTCOME
            sym = table.top_symbols.get(seg)
            if sym is not None:
                return _Outcome("symbol", sym.id)
            return _NONE_OUTCOME
        # state.kind == symbol: descend into class members / nested definitions.
        assert state.target is not None
        sym = self._symbol_by_any_id(state.target)
        if sym is None:
            return _NONE_OUTCOME
        if sym.kind == "class":
            member = self._find_member(sym, seg)
            if member is not None:
                return _Outcome("symbol", member)
            nested = self._nested_class(sym, seg)
            if nested is not None:
                return _Outcome("symbol", nested)
            # One inheritance hop: bases declared in the class's own module.
            for base_id in self._base_chain(sym):
                base_sym = self._symbol_by_any_id(base_id)
                if base_sym is None:
                    continue
                member = self._find_member(base_sym, seg)
                if member is not None:
                    return _Outcome("symbol", member)
            return _NONE_OUTCOME
        return _NONE_OUTCOME  # attribute off a non-class value: dynamic

    # --------------------------------------------------------- member search

    def _find_member(self, class_sym: Symbol, name: str) -> str | None:
        for member in class_sym.members:
            if member.name == name:
                return f"{class_sym.id}.{name}"
        table = self._table_of_symbol(class_sym)
        if table is None:
            return None
        method_id = f"{class_sym.id}.{name}"
        if method_id in table.symbol_by_id:
            return method_id
        return None

    def _nested_class(self, class_sym: Symbol, name: str) -> str | None:
        table = self._table_of_symbol(class_sym)
        if table is None:
            return None
        candidate = f"{class_sym.id}.{name}"
        nested = table.symbol_by_id.get(candidate)
        if nested is not None and nested.kind == "class":
            return candidate
        return None

    def _table_of_symbol(self, sym: Symbol) -> _ModuleTable | None:
        if "::" not in sym.id:
            return None
        module_path = sym.id.split("::", 1)[0]
        return self.tables.get(module_path)

    def _symbol_by_any_id(self, sym_id: str) -> Symbol | None:
        if "::" in sym_id:
            module_path, _ = sym_id.split("::", 1)
            table = self.tables.get(module_path)
            if table is not None:
                return table.symbol_by_id.get(sym_id)
        return None

    def _base_chain(self, sym: Symbol) -> list[str]:
        """Resolved ids of base classes (one deterministic textual hop)."""
        table = self._table_of_symbol(sym)
        if table is None:
            return []
        ctx = self.file_ctxs.get(table.paths[0]) if table.paths else None
        if ctx is None:
            return []
        out: list[str] = []
        for base_text in sym.bases:
            base_name = base_text.split(".")[-1].strip("'\"")
            cls_id = self._resolve_type_name(ctx, base_name)
            if cls_id is not None and cls_id not in out:
                out.append(cls_id)
        return out

    # ------------------------------------------------------- type environment

    def _enclosing_symbol(self, ctx: _FileCtx, ref: Ref) -> Symbol | None:
        best: Symbol | None = None
        best_area: int | None = None
        for sym in ctx.facts.symbols:
            if _contains(sym, ref.span.start_line, ref.span.start_col):
                area = (sym.span.end_line - sym.span.start_line) * 10000 + (
                    sym.span.end_col - sym.span.start_col
                )
                if best_area is None or area < best_area:
                    best = sym
                    best_area = area
        return best

    def _owner_class(self, ctx: _FileCtx, ref: Ref) -> Symbol | None:
        enclosing = self._enclosing_symbol(ctx, ref)
        if enclosing is None or enclosing.kind != "method":
            return None
        best: Symbol | None = None
        best_area: int | None = None
        for sym in ctx.facts.symbols:
            if sym.kind != "class":
                continue
            if _contains(sym, enclosing.span.start_line, enclosing.span.start_col):
                area = (sym.span.end_line - sym.span.start_line) * 10000 + (
                    sym.span.end_col - sym.span.start_col
                )
                if best_area is None or area < best_area:
                    best = sym
                    best_area = area
        return best

    def _declared_type(self, enclosing: Symbol, name: str) -> str | None:
        if enclosing.signature is not None:
            for param in enclosing.signature.params:
                if param.name == name and param.type_annotation is not None:
                    return param.type_annotation
        for member in enclosing.members:
            if member.name == name and member.type_annotation is not None:
                return member.type_annotation
        return None

    def _resolve_type_name(self, ctx: _FileCtx, type_text: str) -> str | None:
        """Resolve a SIMPLE annotation text to a locally-known class symbol id."""
        stripped = type_text.strip().strip("'\"").strip()
        if not stripped or "." in stripped or " " in stripped or "[" in stripped:
            return None
        direct = ctx.table.top_symbols.get(stripped)
        if direct is not None and direct.kind == "class":
            return direct.id
        binding = ctx.aliases.get(stripped)
        if binding is not None and binding.style == "from":
            abs_origin = ctx.alias_abs[stripped]
            tail = abs_origin.rsplit(".", 1)[-1]
            base = abs_origin[: -(len(tail) + 1)] if "." in abs_origin else ""
            outcome = self._lookup_in_module(base, tail, frozenset())
            if outcome.kind == _SYMBOL and outcome.target is not None:
                sym = self._symbol_by_any_id(outcome.target)
                if sym is not None and sym.kind == "class":
                    return outcome.target
        return None


class PythonResolver(Resolver):
    """Binds Python use-sites to stable ids across one changeset side."""

    language: ClassVar[Literal["python"]] = "python"

    def resolve(self, files: tuple[FileFacts, ...]) -> tuple[FileFacts, ...]:
        return _Resolver(files).resolve_all()


@dataclass(frozen=True)
class ResolutionCoverage:
    """First-class coverage metric (Constitution §4): fraction of dependency
    edges whose resolution.status == 'resolved'."""

    total: int
    resolved: int
    external: int
    ambiguous: int
    unresolved: int

    @property
    def coverage(self) -> float:
        return self.resolved / self.total if self.total else 0.0


def resolution_coverage(files: tuple[FileFacts, ...]) -> ResolutionCoverage:
    counts = {"resolved": 0, "external": 0, "ambiguous": 0, "unresolved": 0}
    for facts in files:
        for ref in facts.refs:
            counts[ref.resolution.status] += 1
    total = sum(counts.values())
    return ResolutionCoverage(
        total=total,
        resolved=counts["resolved"],
        external=counts["external"],
        ambiguous=counts["ambiguous"],
        unresolved=counts["unresolved"],
    )
