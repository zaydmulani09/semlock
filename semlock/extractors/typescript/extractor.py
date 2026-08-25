"""TypeScript extractor (S3, spike quality): TS source -> UNRESOLVED FileFacts.

Emits the fixed id grammar ``<module_path>::<Qualified.Name>``. Interface/class
members are emitted BOTH as Member entries on their owner (the field_removed
diff surface) AND as first-class symbols whose own ids member refs bind to
(`src/models::User.name`), per the fixed resolution rule.

Every Ref leaves resolution at the default 'unresolved'; only the Resolver
upgrades statuses. Known v0.1.0 limitation: Ref has no module-specifier or
import-alias fields, so that evidence is lost at the seam (interface-request
filed; see docs/SESSION_LOG.md).
"""
from __future__ import annotations

from typing import ClassVar

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from semlock.extractors.base import Extractor
from semlock.extractors.typescript._paths import module_path_of
from semlock.ir.model import (
    FileFacts,
    Member,
    Param,
    ParamKind,
    Ref,
    Signature,
    Span,
    Symbol,
    SymbolKind,
)
from semlock.ir.version import FORMAT_VERSION

_LANG_TS = Language(tree_sitter_typescript.language_typescript())
_LANG_TSX = Language(tree_sitter_typescript.language_tsx())
_PARSERS: dict[str, Parser] = {}

_TYPE_NAME_NODES = {"type_identifier", "nested_type_identifier", "generic_type"}

_GLOBAL_IDENTIFIERS = {
    "Promise", "Array", "Map", "Set", "WeakMap", "WeakSet", "Object",
    "Function", "Boolean", "String", "Number", "Date", "RegExp", "Error",
    "JSON", "Math", "console", "window", "document", "globalThis", "Record",
    "Partial", "Required", "Readonly", "Pick", "Omit", "Exclude", "Extract",
    "NonNullable", "ReturnType", "Parameters", "Awaited", "Iterable",
    "IterableIterator", "Iterator", "ReadonlyArray", "ReadonlyMap",
    "ReadonlySet", "Symbol",
}

_LEAF_SKIP = {
    "identifier", "property_identifier", "shorthand_property_identifier",
    "shorthand_property_identifier_pattern", "string_fragment", "number",
    "comment", "regex", "jsx_text",
}


def _parser_for(path: str) -> Parser:
    key = "tsx" if path.endswith(".tsx") else "ts"
    if key not in _PARSERS:
        _PARSERS[key] = Parser(_LANG_TSX if key == "tsx" else _LANG_TS)
    return _PARSERS[key]


def _span(node: Node) -> Span:
    return Span(
        start_line=node.start_point.row + 1,
        start_col=node.start_point.column,
        end_line=node.end_point.row + 1,
        end_col=node.end_point.column,
    )


def _text(node: Node) -> str:
    return node.text.decode("utf-8") if node.text is not None else ""


def _child(node: Node, *types: str) -> Node | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _children(node: Node, *types: str) -> list[Node]:
    return [child for child in node.children if child.type in types]


def _strip_annotation(colon_node: Node | None) -> str | None:
    """`': Promise<string>'` -> `'Promise<string>'` (raw text as written)."""
    if colon_node is None:
        return None
    text = _text(colon_node)
    if text.startswith(":"):
        text = text[1:]
    stripped = text.strip()
    return stripped or None


class TypeScriptExtractor(Extractor):
    language: ClassVar[str] = "typescript"

    def extract_file(self, path: str, ref: str, source: str) -> FileFacts:
        tree = _parser_for(path).parse(source.encode("utf-8"))
        ctx = _FileContext(module_path=module_path_of(path))
        root = tree.root_node
        statements = (
            list(root.children) if root.type == "program" else [root]
        )
        for statement in statements:
            self._visit_statement(statement, ctx, exported=False)
        ctx.apply_export_clauses()
        return FileFacts(
            format_version=FORMAT_VERSION,
            path=path,
            language="typescript",
            ref=ref,
            symbols=tuple(ctx.symbols),
            refs=tuple(ctx.refs),
        )

    # ------------------------------------------------------------ statements

    def _visit_statement(self, node: Node, ctx: _FileContext, exported: bool) -> None:
        kind = node.type
        if kind == "import_statement":
            self._visit_import(node, ctx)
            return
        if kind == "export_statement":
            self._visit_export(node, ctx)
            return
        if kind == "function_declaration":
            self._emit_callable(
                node, ctx, qualified_prefix=(), exports=exported, fn_kind="function"
            )
            return
        if kind in ("class_declaration", "class"):
            self._emit_class(node, ctx, exports=exported)
            return
        if kind == "interface_declaration":
            self._emit_interface(node, ctx, exports=exported)
            return
        if kind == "type_alias_declaration":
            self._emit_type_alias(node, ctx, exports=exported)
            return
        if kind in ("lexical_declaration", "variable_declaration"):
            self._emit_variables(node, ctx, exported=exported)
            return
        self._collect_refs(node, ctx)

    def _visit_export(self, node: Node, ctx: _FileContext) -> None:
        clause = None
        target = None
        source_text: str | None = None
        star = False
        for child in node.children:
            kind = child.type
            if kind in ("export", "default", "=", ",", ";"):
                continue
            if kind == "export_clause":
                clause = child
                continue
            if kind == "string":
                source_text = self._specifier_of_string(child)
                continue
            if kind == "from" or _text(child) == "from":
                continue
            if _text(child) == "*":
                star = True
                continue
            if target is None:
                target = child
        if source_text is not None:
            self._emit_reexport_edges(
                node, ctx, clause=clause, star=star, source=source_text
            )
            return
        if clause is not None:
            ctx.pending_exports.extend(self._specifier_names(clause))
            return
        if target is None:
            return
        self._visit_statement(target, ctx, exported=True)

    def _emit_reexport_edges(
        self,
        node: Node,
        ctx: _FileContext,
        clause: Node | None,
        star: bool,
        source: str,
    ) -> None:
        """Barrel evidence: `export {X as Y} from "m"` / `export * from "m"`."""
        span = _span(node)
        if star:
            ctx.refs.append(
                Ref(name="*", kind="import", span=span, module_specifier=source)
            )
            return
        if clause is None:
            return
        for specifier in _children(clause, "export_specifier"):
            identifiers = [
                _text(c) for c in specifier.children if c.type == "identifier"
            ]
            if not identifiers:
                continue
            original = identifiers[0]
            facing = identifiers[-1]
            ctx.refs.append(
                Ref(
                    name=facing,
                    kind="import",
                    span=_span(specifier),
                    module_specifier=source,
                    # ES semantics: the name as exported by the SOURCE module.
                    # Always set so the resolver can tell re-export edges from
                    # ordinary imports (which leave it None unless aliased).
                    imported_name=original,
                )
            )

    @staticmethod
    def _specifier_of_string(string_node: Node) -> str | None:
        fragment = _child(string_node, "string_fragment")
        return _text(fragment) if fragment is not None else None

    @staticmethod
    def _specifier_names(clause: Node) -> list[str]:
        """Original (pre-alias) names in an `export { ... }` clause."""
        names: list[str] = []
        for specifier in _children(clause, "export_specifier"):
            identifiers = [
                _text(c) for c in specifier.children if c.type == "identifier"
            ]
            if identifiers:
                names.append(identifiers[0])
        return names

    # --------------------------------------------------------------- imports

    def _visit_import(self, node: Node, ctx: _FileContext) -> None:
        specifier = self._statement_specifier(node)
        clause = _child(node, "import_clause")
        if clause is None or specifier is None:
            return
        for child in clause.children:
            if child.type == "identifier":
                ctx.refs.append(
                    Ref(
                        name=_text(child),
                        kind="import",
                        span=_span(child),
                        module_specifier=specifier,
                        imported_name="default",
                    )
                )
            elif child.type == "namespace_import":
                local = _text(child).split()[-1]
                ctx.refs.append(
                    Ref(
                        name=f"{local}.*",
                        kind="import",
                        span=_span(child),
                        module_specifier=specifier,
                    )
                )
            elif child.type == "named_imports":
                for spec in _children(child, "import_specifier"):
                    original, alias = self._import_specifier_pair(spec)
                    ctx.refs.append(
                        Ref(
                            name=alias or original,
                            kind="import",
                            span=_span(spec),
                            module_specifier=specifier,
                            imported_name=original if alias else None,
                        )
                    )

    def _statement_specifier(self, node: Node) -> str | None:
        string_node = _child(node, "string")
        if string_node is None:
            return None
        return self._specifier_of_string(string_node)

    @staticmethod
    def _import_specifier_pair(specifier: Node) -> tuple[str, str]:
        identifiers = [
            _text(c) for c in specifier.children if c.type == "identifier"
        ]
        if len(identifiers) >= 2:
            return identifiers[0], identifiers[-1]
        if len(identifiers) == 1:
            return identifiers[0], ""
        return "", ""

    # ------------------------------------------------------------- callables

    def _signature_of(self, callable_node: Node) -> Signature | None:
        params_node = _child(callable_node, "formal_parameters")
        params: list[Param] = []
        if params_node is not None:
            position = 0
            for child in params_node.children:
                if child.type in ("required_parameter", "optional_parameter"):
                    param = self._param(child, position)
                    if param is not None:
                        params.append(param)
                        position += 1
        return_type = self._return_annotation(callable_node, params_node)
        if not params and return_type is None:
            return None
        return Signature(params=tuple(params), return_type=return_type)

    @staticmethod
    def _return_annotation(
        callable_node: Node, params_node: Node | None
    ) -> str | None:
        candidates = [
            c
            for c in callable_node.children
            if c.type == "type_annotation"
            and (params_node is None or c.start_byte >= params_node.end_byte)
        ]
        return _strip_annotation(candidates[-1]) if candidates else None

    def _param(self, node: Node, position: int) -> Param | None:
        pattern = _child(node, "identifier", "rest_pattern", "object_pattern")
        if pattern is None:
            return None
        name = _text(pattern)
        has_default = node.type == "optional_parameter"
        pkind: ParamKind = "positional"
        if pattern.type == "rest_pattern":
            inner = pattern.children[-1]
            name = _text(inner)
            pkind = "varargs"
        elif _child(node, "=") is not None:
            has_default = True
        annotation = _strip_annotation(_child(node, "type_annotation"))
        if name.startswith("{") or name.startswith("["):
            return None
        return Param(
            name=name,
            position=position,
            kind=pkind,
            type_annotation=annotation,
            has_default=has_default,
        )

    def _emit_callable(
        self,
        node: Node,
        ctx: _FileContext,
        qualified_prefix: tuple[str, ...],
        exports: bool,
        fn_kind: SymbolKind,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node)
        qualified = (*qualified_prefix, name)
        ctx.add(
            Symbol(
                id=f"{ctx.module_path}::{'.'.join(qualified)}",
                name=name,
                kind=fn_kind,
                span=_span(node),
                exports=exports,
                signature=self._signature_of(node),
            )
        )
        body = _child(node, "statement_block")
        if body is not None:
            self._collect_refs(body, ctx)

    # ------------------------------------------------------------------ class

    def _emit_class(self, node: Node, ctx: _FileContext, exports: bool) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node)
        bases = self._heritage_bases(node, ctx)
        members: list[Member] = []
        member_symbols: list[Symbol] = []
        body = _child(node, "class_body")
        if body is not None:
            for child in body.children:
                if child.type == "public_field_definition":
                    field = self._field_member(child)
                    if field is not None:
                        members.append(field)
                        member_symbols.append(self._member_symbol(ctx, name, field))
                elif child.type == "method_definition":
                    method_name_node = child.child_by_field_name("name")
                    if method_name_node is None:
                        continue
                    mname = _text(method_name_node)
                    members.append(
                        Member(
                            mname,
                            self._return_annotation(
                                child, _child(child, "formal_parameters")
                            ),
                            _span(child),
                        )
                    )
                    self._emit_callable(
                        child,
                        ctx,
                        qualified_prefix=(name,),
                        exports=False,
                        fn_kind="method",
                    )
        ctx.add_with(
            Symbol(
                id=f"{ctx.module_path}::{name}",
                name=name,
                kind="class",
                span=_span(node),
                exports=exports,
                bases=bases,
                members=tuple(members),
            ),
            member_symbols,
        )
        if body is not None:
            self._collect_refs(body, ctx)

    def _member_symbol(self, ctx: _FileContext, owner: str, field: Member) -> Symbol:
        return Symbol(
            id=f"{ctx.module_path}::{owner}.{field.name}",
            name=field.name,
            kind="variable",
            span=field.span,
            exports=False,
        )

    @staticmethod
    def _field_member(node: Node) -> Member | None:
        name_node = node.child_by_field_name("name")
        if name_node is None or name_node.type != "property_identifier":
            return None
        annotation = _strip_annotation(_child(node, "type_annotation"))
        return Member(_text(name_node), annotation, _span(node))

    def _heritage_bases(self, node: Node, ctx: _FileContext) -> tuple[str, ...]:
        heritage = _child(node, "class_heritage")
        if heritage is None:
            return ()
        bases: list[str] = []
        for clause_type in ("extends_clause", "implements_clause"):
            clause = _child(heritage, clause_type)
            if clause is None:
                continue
            for child in clause.children:
                if child.type in ("extends", "implements"):
                    continue
                head = self._heritage_head(child)
                if head is None:
                    continue
                bases.append(_text(child))
                ctx.refs.append(Ref(name=head, kind="read", span=_span(child)))
        return tuple(bases)

    def _heritage_head(self, node: Node) -> str | None:
        if node.type in ("identifier", "type_identifier"):
            return _text(node)
        if node.type == "generic_type":
            return self._heritage_head(node.children[0]) if node.children else None
        if node.type == "member_expression":
            parts = [
                _text(c)
                for c in node.children
                if c.type in ("identifier", "property_identifier")
            ]
            return parts[-1] if parts else None
        if node.type in _TYPE_NAME_NODES:
            return _text(node)
        return None

    # -------------------------------------------------------------- interface

    def _emit_interface(self, node: Node, ctx: _FileContext, exports: bool) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _text(name_node)
        members: list[Member] = []
        member_symbols: list[Symbol] = []
        body = _child(node, "interface_body")
        if body is not None:
            for child in body.children:
                if child.type == "property_signature":
                    field = self._signature_property(child)
                    if field is not None:
                        members.append(field)
                        member_symbols.append(self._member_symbol(ctx, name, field))
                elif child.type == "method_signature":
                    method_name_node = child.child_by_field_name("name")
                    if method_name_node is None:
                        continue
                    mname = _text(method_name_node)
                    annotations = [
                        c for c in child.children if c.type == "type_annotation"
                    ]
                    return_text = (
                        _strip_annotation(annotations[-1]) if annotations else None
                    )
                    members.append(Member(mname, return_text, _span(child)))
                    ctx.add(
                        Symbol(
                            id=f"{ctx.module_path}::{name}.{mname}",
                            name=mname,
                            kind="method",
                            span=_span(child),
                            exports=False,
                            signature=self._signature_of(child),
                        )
                    )
        bases = self._interface_extends(node, ctx)
        ctx.add_with(
            Symbol(
                id=f"{ctx.module_path}::{name}",
                name=name,
                kind="interface",
                span=_span(node),
                exports=exports,
                bases=bases,
                members=tuple(members),
            ),
            member_symbols,
        )

    def _interface_extends(self, node: Node, ctx: _FileContext) -> tuple[str, ...]:
        extends = _child(node, "extends_type_clause")
        if extends is None:
            return ()
        base_names = []
        for child in extends.children:
            if child.type == "extends":
                continue
            head = self._heritage_head(child)
            if head is None:
                continue
            base_names.append(_text(child))
            ctx.refs.append(Ref(name=head, kind="read", span=_span(child)))
        return tuple(base_names)

    def _signature_property(self, node: Node) -> Member | None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None
        annotation = _strip_annotation(_child(node, "type_annotation"))
        return Member(_text(name_node), annotation, _span(node))

    # ------------------------------------------------------------- type alias

    def _emit_type_alias(self, node: Node, ctx: _FileContext, exports: bool) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        ctx.add(
            Symbol(
                id=f"{ctx.module_path}::{_text(name_node)}",
                name=_text(name_node),
                kind="type_alias",
                span=_span(node),
                exports=exports,
            )
        )
        value = node.child_by_field_name("value")
        if value is not None:
            self._collect_refs(value, ctx)

    # -------------------------------------------------------------- variables

    def _emit_variables(self, node: Node, ctx: _FileContext, exported: bool) -> None:
        for declarator in _children(node, "variable_declarator"):
            name_node = declarator.child_by_field_name("name")
            value = declarator.child_by_field_name("value")
            if name_node is None or name_node.type != "identifier":
                continue
            name = _text(name_node)
            if value is not None and value.type in (
                "arrow_function",
                "function_expression",
            ):
                ctx.add(
                    Symbol(
                        id=f"{ctx.module_path}::{name}",
                        name=name,
                        kind="function",
                        span=_span(value),
                        exports=exported,
                        signature=self._signature_of(value),
                    )
                )
                body = _child(value, "statement_block")
                self._collect_refs(body if body is not None else value, ctx)
                continue
            if not exported:
                self._collect_refs(declarator, ctx)
                continue
            ann_node = _child(declarator, "type_annotation")
            if ann_node is not None:
                self._collect_refs(ann_node, ctx)
            ctx.add(
                Symbol(
                    id=f"{ctx.module_path}::{name}",
                    name=name,
                    kind="variable",
                    span=_span(declarator),
                    exports=exported,
                )
            )
            if value is not None:
                self._collect_refs(value, ctx)

    # -------------------------------------------------------------- ref sweep

    def _collect_refs(self, node: Node, ctx: _FileContext) -> None:
        kind = node.type
        if kind == "call_expression":
            callee = node.child_by_field_name("function")
            if callee is not None and not (
                _receiver_is_global(callee)
                or (
                    callee.type == "identifier"
                    and _text(callee) in _GLOBAL_IDENTIFIERS
                )
            ):
                ref_name = self._callee_name(callee)
                if ref_name is not None:
                    ctx.refs.append(
                        Ref(name=ref_name, kind="call", span=_span(callee))
                    )
                if callee.type == "member_expression":
                    obj = callee.child_by_field_name("object")
                    if obj is not None:
                        self._collect_refs(obj, ctx)
            args = node.child_by_field_name("arguments")
            if args is not None:
                self._collect_refs(args, ctx)
            return
        if kind == "new_expression":
            callee = node.child_by_field_name("constructor") or _child(
                node, "identifier"
            )
            if callee is not None and _text(callee) not in _GLOBAL_IDENTIFIERS:
                ref_name = self._callee_name(callee)
                if ref_name is not None:
                    ctx.refs.append(
                        Ref(name=ref_name, kind="call", span=_span(callee))
                    )
            args = node.child_by_field_name("arguments")
            if args is not None:
                self._collect_refs(args, ctx)
            return
        if kind == "assignment_expression":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is not None and left.type == "member_expression":
                prop = left.child_by_field_name("property")
                if prop is not None:
                    ctx.refs.append(
                        Ref(name=_text(prop), kind="write", span=_span(prop))
                    )
            if right is not None:
                self._collect_refs(right, ctx)
            return
        if kind == "member_expression":
            prop = node.child_by_field_name("property")
            if prop is not None and not _receiver_is_global(node):
                ctx.refs.append(
                    Ref(name=_text(prop), kind="attribute", span=_span(prop))
                )
            obj = node.child_by_field_name("object")
            if obj is not None:
                self._collect_refs(obj, ctx)
            return
        if kind == "type_annotation":
            for child in node.children:
                self._collect_refs(child, ctx)
            return
        if kind in _TYPE_NAME_NODES:
            self._type_ref(node, ctx)
            if node.type == "nested_type_identifier":
                for child in node.children:
                    if child.type not in ("identifier", "property_identifier"):
                        self._collect_refs(child, ctx)
            return
        if kind == "type_identifier":
            self._plain_type_ref(node, ctx)
            return
        if kind in _LEAF_SKIP:
            return
        for child in node.children:
            self._collect_refs(child, ctx)

    def _type_ref(self, node: Node, ctx: _FileContext) -> None:
        head = self._heritage_head(node)
        if head is not None:
            self._emit_type_read(head, node, ctx)
        if node.type == "generic_type":
            targs = _child(node, "type_arguments")
            if targs is not None:
                for child in targs.children:
                    if child.type in ("<", ">"):
                        continue
                    self._collect_refs(child, ctx)

    def _plain_type_ref(self, node: Node, ctx: _FileContext) -> None:
        self._emit_type_read(_text(node), node, ctx)

    def _emit_type_read(self, name: str, node: Node, ctx: _FileContext) -> None:
        if not name or name[0].islower() or name in _GLOBAL_IDENTIFIERS:
            return
        ctx.refs.append(Ref(name=name, kind="read", span=_span(node)))

    @staticmethod
    def _callee_name(callee: Node) -> str | None:
        if callee.type == "identifier":
            return _text(callee)
        if callee.type == "member_expression":
            prop = callee.child_by_field_name("property")
            return _text(prop) if prop is not None else None
        if callee.type in ("parenthesized_expression", "await_expression"):
            return None
        return None


def _receiver_is_global(node: Node) -> bool:
    """True for `<Global>.prop` receivers (Promise.resolve, console.log)."""
    if node.type != "member_expression":
        return False
    obj = node.child_by_field_name("object")
    if obj is None:
        return False
    if obj.type == "identifier":
        return _text(obj) in _GLOBAL_IDENTIFIERS
    if obj.type == "member_expression":
        return _receiver_is_global(obj)
    return False


class _FileContext:
    """Accumulator for one file's symbols/refs."""

    def __init__(self, module_path: str) -> None:
        self.module_path = module_path
        self.symbols: list[Symbol] = []
        self.refs: list[Ref] = []
        self.pending_exports: list[str] = []

    def add(self, symbol: Symbol) -> None:
        self.symbols.append(symbol)

    def add_with(self, symbol: Symbol, extra: list[Symbol]) -> None:
        self.symbols.append(symbol)
        self.symbols.extend(extra)

    def apply_export_clauses(self) -> None:
        if not self.pending_exports:
            return
        pending = set(self.pending_exports)
        updated: list[Symbol] = []
        for symbol in self.symbols:
            symbol_path = symbol.id.split("::", 1)[1]
            top_level = "." not in symbol_path
            if top_level and symbol.name in pending:
                updated.append(
                    Symbol(
                        id=symbol.id,
                        name=symbol.name,
                        kind=symbol.kind,
                        span=symbol.span,
                        exports=True,
                        bases=symbol.bases,
                        signature=symbol.signature,
                        members=symbol.members,
                    )
                )
            else:
                updated.append(symbol)
        self.symbols = updated
