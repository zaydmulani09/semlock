"""Python extractor: source bytes -> UNRESOLVED FileFacts (S2-owned).

Design notes (binding for this implementation):

- Symbol ids follow ``module_path::qualified_name`` (spike Q1 proposal): the module
  path derives from the repo-relative path (see ``module_paths``); the qualified
  name is the dotted nesting path inside the module. Functions/methods/classes
  each carry their OWN id; class fields live in ``Symbol.members`` and a field's
  canonical reference id is derivable as ``<class_id>.<member_name>`` — never a
  suffixed parent id.
- Every ``Ref`` is emitted with default resolution (INV-2); only a Resolver may
  upgrade statuses.
- Evidence the resolver needs flows through legal IR fields:
    * from-imports encode ``"<alias>=<origin-as-written>"`` in ``Ref.name``
      (wildcards: ``"*=<origin>"``); plain imports encode
      ``"<alias>~<written-module>"`` — distinct markers because they bind
      different things (tail symbol vs root package);
    * attribute-rooted uses record the written chain (``"user.greet"``,
      ``"pkg.models.User"``) in ``Ref.name``; chains whose root is not a plain
      identifier record only the trailing segments;
    * annotated locals and locals assigned straight from a constructor call are
      recorded as ``Member`` entries on the enclosing function symbol;
    * ``self.x`` stores become ``Member`` entries on the enclosing class.
- Exports: ``__all__`` wins when statically present; otherwise every top-level
  def/class/assignment not starting with ``_`` exports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal

import tree_sitter_python as tsp
from tree_sitter import Language, Node, Parser

from semlock.extractors.base import Extractor
from semlock.extractors.python.module_paths import module_info
from semlock.ir.model import (
    FileFacts,
    Member,
    Param,
    ParamKind,
    Ref,
    RefKind,
    Signature,
    Span,
    Symbol,
)
from semlock.ir.version import FORMAT_VERSION

_PARSER: Parser = Parser(Language(tsp.language()))

_MEMBER_DECORATORS: frozenset[str] = frozenset({"property", "cached_property"})


def _span(node: Node) -> Span:
    """tree-sitter Points have 0-based rows -> INV-3 lines are 1-indexed, half-open."""
    return Span(
        start_line=node.start_point.row + 1,
        start_col=node.start_point.column,
        end_line=node.end_point.row + 1,
        end_col=node.end_point.column,
    )


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8")


def _string_content(node: Node) -> Node | None:
    for sub in node.named_children:
        if sub.type == "string_content":
            return sub
    return None


def _type_text(node: Node | None, source: bytes) -> str | None:
    """Annotation text as written: whitespace-collapsed; one layer of forward-ref
    quotes removed. None when absent."""
    if node is None:
        return None
    content = _string_content(node)
    if content is None:  # forward refs nest one level down: type > string > ...
        for sub in node.named_children:
            content = _string_content(sub)
            if content is not None:
                break
    if content is not None:
        return _text(content, source)
    raw = " ".join(_text(node, source).split())
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    return raw


@dataclass
class _Scope:
    """Function-like lexical scope for bound-name analysis. Class bodies are
    transparent for name resolution (Python scoping), so they never appear here."""

    bound: set[str] = field(default_factory=set)
    escapes: set[str] = field(default_factory=set)  # declared global/nonlocal


@dataclass
class _PendingMember:
    """Member discovered during the walk; attached to its owner symbol at drain."""

    owner_id: str
    member: Member


class _Walker:
    def __init__(self, path: str, ref: str, source: bytes) -> None:
        self.path = path
        self.ref_name = ref
        self.source = source
        self.module_path, self.is_package = module_info(path)
        self.symbols: list[Symbol] = []
        self.refs: list[Ref] = []
        self.pending_members: list[_PendingMember] = []
        self.var_seen: dict[str, int] = {}  # top-level variable name -> symbol idx
        self.all_names: list[str] = []
        self.scopes: list[_Scope] = []

    # ------------------------------------------------------------------ helpers

    def _ref(self, name: str, kind: RefKind, node: Node) -> None:
        self.refs.append(Ref(name=name, kind=kind, span=_span(node)))

    def _is_locally_bound(self, name: str) -> bool:
        """True iff `name` binds in an enclosing FUNCTION-like scope without a
        global/nonlocal escape declaring otherwise. Module-scope bindings never
        suppress: they are exactly the resolvable inter-file surface."""
        for scope in reversed(self.scopes[1:]):
            if name in scope.escapes:
                return False
            if name in scope.bound:
                return True
        return False

    # ------------------------------------------------------- bound-name collection

    def _param_scope(self, node: Node, body: Node) -> _Scope:
        """Function scope: parameters PLUS everything bound in the body."""
        scope = _Scope()
        params_node = node.child_by_field_name("parameters")
        if params_node is not None:
            self._pattern_names(params_node, scope.bound)
        body_scope = self._collect_bindings(body)
        scope.bound |= body_scope.bound
        scope.escapes |= body_scope.escapes
        return scope

    def _collect_bindings(self, node: Node) -> _Scope:
        scope = _Scope()
        self._collect_into(node, scope)
        return scope

    def _collect_into(self, node: Node, scope: _Scope) -> None:
        """Dispatch on the node's OWN type; collects names it binds into `scope`.
        Does not descend into nested function/class/lambda bodies (they own their
        names); comprehensions own their targets too."""
        t = node.type
        if t in ("assignment", "augmented_assignment"):
            left = node.child_by_field_name("left")
            if left is not None:
                self._target_names(left, scope.bound)
            right = node.child_by_field_name("right")
            if right is not None:
                self._collect_into(right, scope)
            ann = node.child_by_field_name("type")
            if ann is not None:
                self._collect_into(ann, scope)
            return
        if t == "named_expression":  # walrus binds in the enclosing scope
            left = node.child_by_field_name("name")
            if left is not None:
                scope.bound.add(_text(left, self.source))
            value = node.child_by_field_name("value")
            if value is not None:
                self._collect_into(value, scope)
            return
        if t == "decorated_definition":
            inner = node.children[-1]
            if inner.type in ("function_definition", "class_definition"):
                nm = inner.child_by_field_name("name")
                if nm is not None:
                    scope.bound.add(_text(nm, self.source))
            elif inner.type not in ("comment",):
                self._collect_into(inner, scope)
            for dec in node.named_children:
                if dec.type == "decorator":
                    exprs = dec.named_children
                    if exprs:
                        self._collect_into(exprs[0], scope)
            return
        if t in ("function_definition", "class_definition"):
            nm = node.child_by_field_name("name")
            if nm is not None:
                scope.bound.add(_text(nm, self.source))
            return
        if t == "lambda":
            return  # params bind inside the lambda's own scope
        if t in ("comprehension", "generator_expression"):
            return  # own scope; targets do not leak outward
        if t in ("global_statement", "nonlocal_statement"):
            for ident in node.named_children:
                if ident.type == "identifier":
                    scope.escapes.add(_text(ident, self.source))
            return
        if t == "for_statement":
            left = node.child_by_field_name("left")
            if left is not None:
                self._target_names(left, scope.bound)
            for key in ("right", "body", "alternative"):
                sub = node.child_by_field_name(key)
                if sub is not None:
                    self._collect_into(sub, scope)
            return
        if t == "while_statement":
            for key in ("condition", "body", "alternative"):
                sub = node.child_by_field_name(key)
                if sub is not None:
                    self._collect_into(sub, scope)
            return
        if t == "if_statement":
            for key in ("condition", "consequence", "alternative"):
                sub = node.child_by_field_name(key)
                if sub is not None:
                    self._collect_into(sub, scope)
            return
        if t == "with_statement":
            for sub in node.named_children:
                if sub.type == "with_item":
                    val = sub.child_by_field_name("value")
                    if val is not None:
                        self._collect_into(val, scope)
                    target = sub.child_by_field_name("alias")
                    if target is not None:
                        self._pattern_names(target, scope.bound)
                else:
                    self._collect_into(sub, scope)
            return
        if t == "try_statement":
            for sub in node.named_children:
                if sub.type == "except_clause":
                    filt = sub.child_by_field_name("filter")
                    if filt is not None:
                        self._collect_into(filt, scope)
                    alias = sub.child_by_field_name("alias")
                    if alias is not None:
                        self._pattern_names(alias, scope.bound)
                    body = sub.child_by_field_name("body")
                    if body is not None:
                        self._collect_into(body, scope)
                else:
                    self._collect_into(sub, scope)
            return
        if t == "match_statement":
            subj = node.child_by_field_name("subject")
            if subj is not None:
                self._collect_into(subj, scope)
            for sub in node.named_children:
                if sub.type == "case_clause":
                    pattern = sub.child_by_field_name("pattern")
                    if pattern is not None:
                        self._capture_pattern(pattern, scope.bound)
                    guard = sub.child_by_field_name("guard")
                    if guard is not None:
                        self._collect_into(guard, scope)
                    body = sub.child_by_field_name("body")
                    if body is not None:
                        self._collect_into(body, scope)
            return
        if t in ("import_statement", "import_from_statement"):
            for bound_alias in self._import_aliases(node):
                scope.bound.add(bound_alias)
            return
        if t in (
            "expression_statement",
            "return_statement",
            "raise_statement",
            "assert_statement",
            "delete_statement",
        ):
            for sub in node.named_children:
                self._collect_into(sub, scope)
            return
        if t in (
            "block",
            "module",
            "else_clause",
            "elif_clause",
            "finally_clause",
            "_conditional_block",
        ):
            for sub in node.named_children:
                self._collect_into(sub, scope)
            return
        if t in (
            "comment",
            "pass_statement",
            "break_statement",
            "continue_statement",
            "string",
            "string_content",
            "integer",
            "float",
            "true",
            "false",
            "none",
            "ellipsis",
            "identifier",
        ):
            return
        # Generic conservative descent: only the constructs above ever bind.
        for sub in node.named_children:
            self._collect_into(sub, scope)

    def _capture_pattern(self, node: Node, bound: set[str]) -> None:
        if node.type in (
            "match_pattern",
            "list_pattern",
            "tuple_pattern",
            "map_pattern",
            "complex_pattern",
            "pattern",
            "identifier",
        ):
            if node.type == "identifier":
                bound.add(_text(node, self.source))
                return
            if node.type == "map_pattern":
                for sub in node.named_children:
                    self._capture_pattern(sub, bound)
                return
            for sub in node.named_children:
                self._capture_pattern(sub, bound)

    def _target_names(self, node: Node, bound: set[str]) -> None:
        if node.type == "identifier":
            bound.add(_text(node, self.source))
        elif node.type in (
            "tuple_pattern",
            "list_pattern",
            "pattern_list",
            "star_pattern",
        ):
            for sub in node.named_children:
                self._target_names(sub, bound)

    def _pattern_names(self, node: Node, bound: set[str]) -> None:
        """Collect bound names from parameter/target patterns, seeing through
        typed/default wrappers."""
        for sub in node.named_children:
            t = sub.type
            if t == "identifier":
                bound.add(_text(sub, self.source))
            elif t in (
                "typed_parameter",
                "default_parameter",
                "typed_default_parameter",
            ):
                for inner_sub in sub.named_children:
                    if inner_sub.type == "identifier":
                        bound.add(_text(inner_sub, self.source))
                        break
            elif t in ("list_splat_pattern", "dictionary_splat_pattern"):
                for inner_sub in sub.named_children:
                    if inner_sub.type == "identifier":
                        bound.add(_text(inner_sub, self.source))

    def _import_aliases(self, stmt: Node) -> list[str]:
        aliases: list[str] = []
        for child in stmt.named_children:
            if child.type == "dotted_name" and stmt.type == "import_from_statement":
                aliases.append(_text(child, self.source))
            elif child.type == "dotted_name" and stmt.type == "import_statement":
                aliases.append(_text(child, self.source).split(".")[0])
            elif child.type == "aliased_import":
                dn = child.child_by_field_name("name")
                al = child.child_by_field_name("alias")
                if dn is None:
                    continue
                default = (
                    _text(dn, self.source)
                    if stmt.type == "import_from_statement"
                    else _text(dn, self.source).split(".")[0]
                )
                aliases.append(_text(al, self.source) if al is not None else default)
        return aliases

    # ------------------------------------------------------------------ entry

    def walk(self, root: Node) -> None:
        self.scopes = [self._collect_bindings(root)]
        self._walk_block(root, class_prefix="", function_symbol=None, class_id=None)

    def _walk_block(
        self,
        block: Node,
        *,
        class_prefix: str,
        function_symbol: int | None,
        class_id: str | None,
    ) -> None:
        for stmt in block.named_children:
            self._walk_statement(
                stmt,
                class_prefix=class_prefix,
                function_symbol=function_symbol,
                class_id=class_id,
            )

    def _walk_statement(
        self,
        stmt: Node,
        *,
        class_prefix: str,
        function_symbol: int | None,
        class_id: str | None,
    ) -> None:
        t = stmt.type
        if t == "decorated_definition":
            for dec in stmt.named_children:
                if dec.type == "decorator":
                    exprs = dec.named_children
                    if exprs:
                        self._visit_load(exprs[0])
            inner = stmt.children[-1]
            self._walk_statement(
                inner,
                class_prefix=class_prefix,
                function_symbol=function_symbol,
                class_id=class_id,
            )
            return
        if t == "function_definition":
            self._handle_function(stmt, class_prefix=class_prefix)
            return
        if t == "class_definition":
            self._handle_class(stmt, class_prefix=class_prefix)
            return
        if t in ("import_statement", "import_from_statement"):
            self._handle_import(stmt)
            return
        if t == "assignment":
            self._handle_assignment(stmt, function_symbol=function_symbol)
            return
        if t == "augmented_assignment":
            self._handle_augmented(stmt, function_symbol=function_symbol)
            return
        if t == "expression_statement":
            kids = stmt.named_children
            if len(kids) == 1 and kids[0].type == "assignment":
                self._handle_assignment(kids[0], function_symbol=function_symbol)
                return
            if len(kids) == 1 and kids[0].type == "augmented_assignment":
                self._handle_augmented(kids[0], function_symbol=function_symbol)
                return
            for sub in kids:
                self._visit_load(sub)
            return
        if t == "for_statement":
            for key in ("right", "body", "alternative"):
                field_node = stmt.child_by_field_name(key)
                if field_node is not None:
                    self._dispatch_sub(
                        field_node,
                        class_prefix=class_prefix,
                        function_symbol=function_symbol,
                        class_id=class_id,
                    )
            return
        if t in ("if_statement", "while_statement"):
            for key in ("condition", "consequence", "body", "alternative"):
                field_node = stmt.child_by_field_name(key)
                if field_node is not None:
                    self._dispatch_sub(
                        field_node,
                        class_prefix=class_prefix,
                        function_symbol=function_symbol,
                        class_id=class_id,
                    )
            return
        if t == "with_statement":
            for sub in stmt.named_children:
                if sub.type == "with_item":
                    val = sub.child_by_field_name("value")
                    if val is not None:
                        self._visit_load(val)
                elif sub.type != "comment":
                    self._dispatch_sub(
                        sub,
                        class_prefix=class_prefix,
                        function_symbol=function_symbol,
                        class_id=class_id,
                    )
            return
        if t == "try_statement":
            for sub in stmt.named_children:
                if sub.type == "except_clause":
                    filt = sub.child_by_field_name("filter")
                    if filt is not None:
                        self._visit_load(filt)
                    body = sub.child_by_field_name("body")
                    if body is not None:
                        self._dispatch_sub(
                            body,
                            class_prefix=class_prefix,
                            function_symbol=function_symbol,
                            class_id=class_id,
                        )
                elif sub.type != "comment":
                    self._dispatch_sub(
                        sub,
                        class_prefix=class_prefix,
                        function_symbol=function_symbol,
                        class_id=class_id,
                    )
            return
        if t == "match_statement":
            subj = stmt.child_by_field_name("subject")
            if subj is not None:
                self._visit_load(subj)
            for sub in stmt.named_children:
                if sub.type == "case_clause":
                    guard = sub.child_by_field_name("guard")
                    if guard is not None:
                        self._visit_load(guard)
                    body = sub.child_by_field_name("body")
                    if body is not None:
                        self._dispatch_sub(
                            body,
                            class_prefix=class_prefix,
                            function_symbol=function_symbol,
                            class_id=class_id,
                        )
            return
        if t in (
            "return_statement",
            "raise_statement",
            "assert_statement",
            "delete_statement",
        ):
            for sub in stmt.named_children:
                if t == "delete_statement" and sub.type == "attribute":
                    chain = self._chain_name(sub)
                    if chain:
                        self._ref(chain, "write", sub)
                else:
                    self._visit_load(sub)
            return
        if t == "block":
            self._walk_block(
                stmt,
                class_prefix=class_prefix,
                function_symbol=function_symbol,
                class_id=class_id,
            )
            return
        if t in (
            "comment",
            "pass_statement",
            "break_statement",
            "continue_statement",
            "global_statement",
            "nonlocal_statement",
        ):
            return
        for sub in stmt.named_children:
            self._visit_load(sub)

    def _dispatch_sub(
        self,
        node: Node,
        *,
        class_prefix: str,
        function_symbol: int | None,
        class_id: str | None,
    ) -> None:
        if node.type == "block":
            self._walk_block(
                node,
                class_prefix=class_prefix,
                function_symbol=function_symbol,
                class_id=class_id,
            )
        else:
            self._walk_statement(
                node,
                class_prefix=class_prefix,
                function_symbol=function_symbol,
                class_id=class_id,
            )

    # ------------------------------------------------------------ definitions

    def _handle_function(self, node: Node, *, class_prefix: str) -> None:
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if name_node is None:
            return
        name = _text(name_node, self.source)
        qualified = f"{class_prefix}.{name}" if class_prefix else name
        sym_id = f"{self.module_path}::{qualified}"
        symbol_index = len(self.symbols)
        self.symbols.append(
            Symbol(
                id=sym_id,
                name=name,
                kind="method" if class_prefix else "function",
                span=_span(node),
                exports=False,
                signature=Signature(
                    params=self._parse_parameters(
                        node.child_by_field_name("parameters")
                    ),
                    return_type=_type_text(
                        node.child_by_field_name("return_type"), self.source
                    ),
                ),
            )
        )
        if body is not None:
            self.scopes.append(self._param_scope(node, body))
            self._walk_block(
                body, class_prefix="", function_symbol=symbol_index, class_id=None
            )
            self.scopes.pop()
            self._attach_drained(symbol_index)

    def _handle_class(self, node: Node, *, class_prefix: str) -> None:
        name_node = node.child_by_field_name("name")
        supers = node.child_by_field_name("superclasses")
        body = node.child_by_field_name("body")
        if name_node is None:
            return
        name = _text(name_node, self.source)
        qualified = f"{class_prefix}.{name}" if class_prefix else name
        sym_id = f"{self.module_path}::{qualified}"
        bases: list[str] = []
        if supers is not None:
            for arg in supers.named_children:
                if arg.type == "keyword_argument":
                    val = arg.child_by_field_name("value")
                    if val is not None:
                        self._visit_load(val)
                    continue
                bases.append(_text(arg, self.source))
                if arg.type == "identifier":
                    if not self._is_locally_bound(_text(arg, self.source)):
                        self._ref(_text(arg, self.source), "read", arg)
                elif arg.type == "attribute":
                    chain = self._chain_name(arg)
                    if chain:
                        self._ref(chain, "read", arg)
                    root = self._chain_root(arg)
                    if root is not None and root.type != "identifier":
                        self._visit_load(root)
                else:
                    self._visit_load(arg)
        symbol_index = len(self.symbols)
        self.symbols.append(
            Symbol(
                id=sym_id,
                name=name,
                kind="class",
                span=_span(node),
                exports=False,
                bases=tuple(bases),
            )
        )
        if body is not None:
            self._walk_class_body(body, class_id=sym_id, class_prefix=qualified)
            self._attach_drained(symbol_index)

    def _walk_class_body(
        self, block: Node, *, class_id: str, class_prefix: str
    ) -> None:
        for stmt in block.named_children:
            t = stmt.type
            if t == "decorated_definition":
                for dec in stmt.named_children:
                    if dec.type == "decorator":
                        exprs = dec.named_children
                        if exprs:
                            self._visit_load(exprs[0])
                inner = stmt.children[-1]
                if inner.type == "function_definition":
                    self._handle_method(
                        inner,
                        class_prefix=class_prefix,
                        class_id=class_id,
                        member_decorator=any(
                            self._decorator_is_member(dec)
                            for dec in stmt.named_children
                            if dec.type == "decorator"
                        ),
                    )
                elif inner.type == "class_definition":
                    self._handle_class(inner, class_prefix=class_prefix)
                continue
            if t == "function_definition":
                self._handle_method(
                    stmt,
                    class_prefix=class_prefix,
                    class_id=class_id,
                    member_decorator=False,
                )
                continue
            if t == "class_definition":
                self._handle_class(stmt, class_prefix=class_prefix)
                continue
            if t == "assignment":
                self._handle_class_assignment(stmt, class_id=class_id)
                continue
            if t == "expression_statement":
                for sub in stmt.named_children:
                    if sub.type == "assignment":
                        self._handle_class_assignment(sub, class_id=class_id)
                    elif sub.type != "string":
                        self._visit_load(sub)
                continue
            if t in ("comment",):
                continue
            # Conditional definitions etc.: walk as out-of-function statements.
            self._walk_statement(
                stmt, class_prefix=class_prefix, function_symbol=None, class_id=class_id
            )

    def _decorator_is_member(self, dec: Node) -> bool:
        exprs = dec.named_children
        if not exprs:
            return False
        expr = exprs[0]
        if expr.type == "identifier":
            return _text(expr, self.source) in _MEMBER_DECORATORS
        if expr.type == "attribute":
            attr = expr.child_by_field_name("attribute")
            return attr is not None and _text(attr, self.source) in _MEMBER_DECORATORS
        return False

    def _handle_method(
        self,
        node: Node,
        *,
        class_prefix: str,
        class_id: str,
        member_decorator: bool,
    ) -> None:
        self._handle_function(node, class_prefix=class_prefix)
        if not member_decorator:
            return
        # @property / @cached_property: consumers access it as DATA, so the class
        # also owns a member twin whose id is what `.prop` access binds to.
        name_node = node.child_by_field_name("name")
        ret_node = node.child_by_field_name("return_type")
        if name_node is None:
            return
        self.pending_members.append(
            _PendingMember(
                owner_id=class_id,
                member=Member(
                    _text(name_node, self.source),
                    _type_text(ret_node, self.source),
                    _span(node),
                ),
            )
        )

    def _handle_class_assignment(self, stmt: Node, *, class_id: str) -> None:
        left = stmt.child_by_field_name("left")
        type_node = stmt.child_by_field_name("type")
        right = stmt.child_by_field_name("right")
        annotation = _type_text(type_node, self.source)
        if left is None:
            return
        if left.type == "identifier":
            inferred = annotation
            if inferred is None and right is not None and right.type == "call":
                fn = right.child_by_field_name("function")
                if fn is not None and fn.type == "identifier":
                    inferred = _text(fn, self.source)
            self.pending_members.append(
                _PendingMember(
                    owner_id=class_id,
                    member=Member(_text(left, self.source), inferred, _span(stmt)),
                )
            )
            if right is not None:
                self._visit_load(right)
            return
        if left.type == "attribute":
            chain = self._chain_name(left)
            if chain:
                self._ref(chain, "write", left)
                root = self._chain_root(left)
                if root is not None and root.type != "identifier":
                    self._visit_load(root)
            if right is not None:
                self._visit_load(right)
            return
        if right is not None:
            self._visit_load(right)

    def _parse_parameters(self, params_node: Node | None) -> tuple[Param, ...]:
        if params_node is None:
            return ()
        params: list[Param] = []
        kwonly = False
        for child in params_node.named_children:
            t = child.type
            if t == "keyword_separator":
                kwonly = True
                continue
            if t == "positional_separator":
                continue
            if t == "list_splat_pattern":
                ident = child.named_children[-1]
                params.append(
                    Param(
                        _text(ident, self.source), len(params), "varargs", None, False
                    )
                )
                kwonly = True  # everything after *args is keyword-only
                continue
            if t == "dictionary_splat_pattern":
                ident = child.named_children[-1]
                params.append(
                    Param(_text(ident, self.source), len(params), "kwargs", None, False)
                )
                continue
            name_node: Node | None = None
            type_node: Node | None = None
            has_default = False
            if t == "identifier":
                name_node = child
            elif t == "typed_parameter":
                for sub in child.named_children:
                    if sub.type == "identifier" and name_node is None:
                        name_node = sub
                    elif sub.type == "type":
                        type_node = sub
            elif t == "default_parameter":
                kids = child.named_children
                name_node = kids[0] if kids else None
                has_default = True
            elif t == "typed_default_parameter":
                for sub in child.named_children:
                    if sub.type == "identifier" and name_node is None:
                        name_node = sub
                    elif sub.type == "type":
                        type_node = sub
                has_default = True
            if name_node is None:
                continue
            kind: ParamKind = "keyword_only" if kwonly else "positional"
            params.append(
                Param(
                    _text(name_node, self.source),
                    len(params),
                    kind,
                    _type_text(type_node, self.source),
                    has_default,
                )
            )
        return tuple(params)

    # ---------------------------------------------------------------- imports

    def _handle_import(self, stmt: Node) -> None:
        if stmt.type == "import_statement":
            for child in stmt.named_children:
                dn: Node | None = None
                alias: str | None = None
                if child.type == "dotted_name":
                    dn = child
                elif child.type == "aliased_import":
                    dn = child.child_by_field_name("name")
                    al = child.child_by_field_name("alias")
                    alias = _text(al, self.source) if al is not None else None
                if dn is None:
                    continue
                written = _text(dn, self.source)
                local = alias if alias is not None else written.split(".")[0]
                self._ref(f"{local}~{written}", "import", child)
            return
        module_node = stmt.child_by_field_name("module_name")
        if module_node is None:
            for child in stmt.children:
                if child.type in ("dotted_name", "relative_import"):
                    module_node = child
                    break
        origin = _text(module_node, self.source) if module_node is not None else ""
        for child in stmt.named_children:
            if module_node is not None and child.id == module_node.id:
                continue  # the module name is not an imported item
            if child.type == "dotted_name":
                written_name = _text(child, self.source)
                full = self._join_origin(origin, written_name)
                self._ref(f"{written_name}={full}", "import", child)
            elif child.type == "aliased_import":
                dn = child.child_by_field_name("name")
                al = child.child_by_field_name("alias")
                if dn is None:
                    continue
                written_name = _text(dn, self.source)
                full = self._join_origin(origin, written_name)
                local = _text(al, self.source) if al is not None else written_name
                self._ref(f"{local}={full}", "import", child)
            elif child.type == "wildcard_import":
                self._ref(f"*={origin}", "import", child)

    @staticmethod
    def _join_origin(origin: str, name: str) -> str:
        if not origin:
            return name
        if origin.endswith("."):
            return f"{origin}{name}"
        return f"{origin}.{name}"

    # ------------------------------------------------------------- assignments

    def _handle_augmented(self, stmt: Node, *, function_symbol: int | None) -> None:
        left = stmt.child_by_field_name("left")
        if left is not None:
            if left.type == "attribute":
                chain = self._chain_name(left)
                if chain:
                    self._ref(chain, "write", left)
            elif (
                left.type == "identifier"
                and function_symbol is None
                and _text(left, self.source) == "__all__"
            ):
                self._parse_all(stmt.child_by_field_name("right"))
        right = stmt.child_by_field_name("right")
        if right is not None:
            self._visit_load(right)

    def _handle_assignment(self, stmt: Node, *, function_symbol: int | None) -> None:
        left = stmt.child_by_field_name("left")
        type_node = stmt.child_by_field_name("type")
        right = stmt.child_by_field_name("right")
        annotation = _type_text(type_node, self.source)
        if (
            left is not None
            and left.type == "identifier"
            and function_symbol is None
            and _text(left, self.source) == "__all__"
        ):
            self._parse_all(stmt.child_by_field_name("right"))
            return
        if left is not None:
            self._handle_store_target(
                left,
                annotation=annotation,
                right=right,
                function_symbol=function_symbol,
                stmt=stmt,
            )
        if right is not None:
            self._visit_load(right)

    def _handle_store_target(
        self,
        left: Node,
        *,
        annotation: str | None,
        right: Node | None,
        function_symbol: int | None,
        stmt: Node,
    ) -> None:
        t = left.type
        if t == "attribute":
            chain = self._chain_name(left)
            if chain:
                self._ref(chain, "write", left)
                self._maybe_self_member(left, chain, annotation, right, function_symbol)
            root = self._chain_root(left)
            if root is not None and root.type != "identifier":
                self._visit_load(root)
            return
        if t == "identifier":
            name = _text(left, self.source)
            if function_symbol is not None:
                self._record_local(
                    self.symbols[function_symbol].id, name, annotation, right, stmt
                )
            else:
                self._record_module_variable(name, stmt)
            return
        if t in ("pattern_list", "tuple_pattern", "list_pattern"):
            for sub in left.named_children:
                self._handle_store_target(
                    sub,
                    annotation=None,
                    right=None,
                    function_symbol=function_symbol,
                    stmt=stmt,
                )
            return
        if t in ("subscript", "call"):
            self._visit_load(left)
            return
        for sub in left.named_children:
            self._handle_store_target(
                sub,
                annotation=None,
                right=None,
                function_symbol=function_symbol,
                stmt=stmt,
            )

    def _record_local(
        self,
        owner_id: str,
        name: str,
        annotation: str | None,
        right: Node | None,
        stmt: Node,
    ) -> None:
        inferred = annotation
        if inferred is None and right is not None and right.type == "call":
            fn = right.child_by_field_name("function")
            if fn is not None and fn.type == "identifier":
                inferred = _text(fn, self.source)
        if inferred is None:
            return  # untyped local with no ctor evidence: no resolvable surface
        self.pending_members.append(
            _PendingMember(
                owner_id=owner_id, member=Member(name, inferred, _span(stmt))
            )
        )

    def _record_module_variable(self, name: str, stmt: Node) -> None:
        if name == "__all__":
            return
        if name in self.var_seen:
            return  # first definition wins; deterministic
        self.var_seen[name] = len(self.symbols)
        self.symbols.append(
            Symbol(
                id=f"{self.module_path}::{name}",
                name=name,
                kind="variable",
                span=_span(stmt),
                exports=False,  # finalized in finish()
            )
        )

    def _maybe_self_member(
        self,
        attr_node: Node,
        chain: str,
        annotation: str | None,
        right: Node | None,
        function_symbol: int | None,
    ) -> None:
        parts = chain.split(".")
        if len(parts) != 2 or parts[0] != "self" or function_symbol is None:
            return
        owner = self._enclosing_class_id(function_symbol)
        if owner is None:
            return
        inferred = annotation
        if inferred is None and right is not None and right.type == "call":
            fn = right.child_by_field_name("function")
            if fn is not None and fn.type == "identifier":
                inferred = _text(fn, self.source)
        if inferred is None and right is None:
            return
        self.pending_members.append(
            _PendingMember(
                owner_id=owner, member=Member(parts[1], inferred, _span(attr_node))
            )
        )

    def _enclosing_class_id(self, function_symbol: int) -> str | None:
        meth = self.symbols[function_symbol]
        best: str | None = None
        best_area = -1
        for sym in self.symbols[:function_symbol]:
            if sym.kind != "class":
                continue
            if (
                sym.span.start_line <= meth.span.start_line
                and meth.span.end_line <= sym.span.end_line
            ):
                area = (sym.span.end_line - sym.span.start_line + 1) * 10000 + (
                    sym.span.end_col - sym.span.start_col + 1
                )
                if best is None or area < best_area:
                    best = sym.id
                    best_area = area
        return best

    # -------------------------------------------------------------- __all__

    def _parse_all(self, rhs: Node | None) -> None:
        if rhs is None:
            return
        for elem in self._literal_strings(rhs):
            if elem not in self.all_names:
                self.all_names.append(elem)

    def _merge_all(self, rhs: Node | None) -> None:
        self._parse_all(rhs)

    def _literal_strings(self, node: Node) -> list[str]:
        if node.type in ("list", "tuple"):
            out: list[str] = []
            for sub in node.named_children:
                out.extend(self._literal_strings(sub))
            return out
        if node.type == "string":
            content = _string_content(node)
            if content is not None:
                return [_text(content, self.source)]
            return []
        if node.type == "expression_list":
            out = []
            for sub in node.named_children:
                out.extend(self._literal_strings(sub))
            return out
        return []

    # ------------------------------------------------------------ expressions

    def _visit_load(self, node: Node) -> None:
        t = node.type
        if t == "call":
            fn = node.child_by_field_name("function")
            if fn is not None:
                self._emit_call_target(fn)
            args = node.child_by_field_name("arguments")
            if args is not None:
                for sub in args.named_children:
                    if sub.type == "keyword_argument":
                        val = sub.child_by_field_name("value")
                        if val is not None:
                            self._visit_load(val)
                    elif sub.type in ("list_splat", "dictionary_splat"):
                        for inner_sub in sub.named_children:
                            self._visit_load(inner_sub)
                    else:
                        self._visit_load(sub)
            return
        if t == "attribute":
            chain = self._chain_name(node)
            if chain:
                self._ref(chain, "attribute", node)
            root = self._chain_root(node)
            if root is not None:
                if root.type == "identifier":
                    self._emit_bare_read(root)
                else:
                    self._visit_load(root)
            return
        if t == "identifier":
            self._emit_bare_read(node)
            return
        if t == "keyword_argument":
            val = node.child_by_field_name("value")
            if val is not None:
                self._visit_load(val)
            return
        if t == "lambda":
            bound: set[str] = set()
            for sub in node.named_children:
                if sub.type == "lambda_parameters":
                    self._pattern_names(sub, bound)
            body = node.child_by_field_name("body")
            self.scopes.append(_Scope(bound=bound))
            if body is not None:
                self._visit_load(body)
            self.scopes.pop()
            return
        if t == "comprehension":
            self._visit_comprehension(node)
            return
        if t in ("string", "integer", "float", "true", "false", "none", "ellipsis"):
            for sub in node.named_children:
                if sub.type == "interpolation":
                    for inner_sub in sub.named_children:
                        self._visit_load(inner_sub)
            return
        if t in ("global_statement", "nonlocal_statement", "comment", "string_content"):
            return
        for sub in node.named_children:
            self._visit_load(sub)

    def _visit_comprehension(self, node: Node) -> None:
        clauses = [c for c in node.named_children if c.type == "for_in_clause"]
        first = clauses[0] if clauses else None
        if first is not None:
            right = first.child_by_field_name("right")
            if right is not None:
                self._visit_load(right)  # evaluated in the ENCLOSING scope
        bound: set[str] = set()
        for clause in clauses:
            left = clause.child_by_field_name("left")
            if left is not None:
                self._target_names(left, bound)
        self.scopes.append(_Scope(bound=bound))
        for child in node.named_children:
            if child.type == "for_in_clause":
                if child.id == (first.id if first is not None else ""):
                    continue
                right = child.child_by_field_name("right")
                if right is not None:
                    self._visit_load(right)
            elif child.type == "if_clause":
                for sub in child.named_children:
                    self._visit_load(sub)
            else:
                self._visit_load(child)
        self.scopes.pop()

    def _emit_call_target(self, fn: Node) -> None:
        if fn.type == "attribute":
            chain = self._chain_name(fn)
            if chain:
                parent = fn.parent
                self._ref(chain, "call", parent if parent is not None else fn)
            root = self._chain_root(fn)
            if root is not None:
                if root.type == "identifier":
                    self._emit_bare_read(root)
                else:
                    self._visit_load(root)
            return
        if fn.type == "identifier":
            self._emit_bare_read(fn, force_kind="call")
            return
        self._visit_load(fn)

    def _emit_bare_read(self, node: Node, force_kind: RefKind = "read") -> None:
        name = _text(node, self.source)
        if self._is_locally_bound(name):
            return
        self._ref(name, force_kind, node)

    # ------------------------------------------------------------ chain utils

    def _chain_segments(self, node: Node) -> tuple[list[str], Node | None]:
        segments: list[str] = []
        cur: Node | None = node
        while cur is not None and cur.type == "attribute":
            attr = cur.child_by_field_name("attribute")
            obj = cur.child_by_field_name("object")
            if attr is None:
                break
            segments.insert(0, _text(attr, self.source))
            cur = obj
        return segments, cur

    def _chain_name(self, node: Node) -> str | None:
        segments, root = self._chain_segments(node)
        if not segments:
            return None
        if root is not None and root.type == "identifier":
            return ".".join([_text(root, self.source), *segments])
        return ".".join(segments)

    def _chain_root(self, node: Node) -> Node | None:
        _, root = self._chain_segments(node)
        return root

    # ------------------------------------------------------------------ finish

    def _drain_pending_for(self, owner_id: str) -> tuple[Member, ...]:
        mine = [pm.member for pm in self.pending_members if pm.owner_id == owner_id]
        self.pending_members[:] = [
            pm for pm in self.pending_members if pm.owner_id != owner_id
        ]
        seen: dict[str, Member] = {}
        for m in mine:
            seen.setdefault(m.name, m)
        return tuple(sorted(seen.values(), key=lambda m: m.name))

    def _attach_drained(self, symbol_index: int) -> None:
        sym = self.symbols[symbol_index]
        members = self._drain_pending_for(sym.id)
        if not members:
            return
        self.symbols[symbol_index] = Symbol(
            id=sym.id,
            name=sym.name,
            kind=sym.kind,
            span=sym.span,
            exports=sym.exports,
            bases=sym.bases,
            signature=sym.signature,
            members=members,
        )

    def finish(self) -> FileFacts:
        exported = set(self.all_names)
        has_all = bool(self.all_names)
        final: list[Symbol] = []
        for sym in self.symbols:
            exports = sym.exports
            if "::" in sym.id:
                qualified = sym.id.split("::", 1)[1]
                if "." not in qualified:  # module-level surface
                    if has_all:
                        exports = sym.name in exported
                    else:
                        exports = not sym.name.startswith("_")
            final.append(
                Symbol(
                    id=sym.id,
                    name=sym.name,
                    kind=sym.kind,
                    span=sym.span,
                    exports=exports,
                    bases=sym.bases,
                    signature=sym.signature,
                    members=sym.members,
                )
            )
        facts = FileFacts(
            format_version=FORMAT_VERSION,
            path=self.path,
            language="python",
            ref=self.ref_name,
            symbols=tuple(
                sorted(final, key=lambda s: (s.span.start_line, s.span.start_col, s.id))
            ),
            refs=tuple(
                sorted(
                    self.refs,
                    key=lambda r: (r.span.start_line, r.span.start_col, r.name),
                )
            ),
        )
        return facts


class PythonExtractor(Extractor):
    """Extracts UNRESOLVED FileFacts from Python source (tree-sitter-python CST)."""

    language: ClassVar[Literal["python"]] = "python"

    def extract_file(self, path: str, ref: str, source: str) -> FileFacts:
        data = source.encode("utf-8")
        tree = _PARSER.parse(data)
        walker = _Walker(path, ref, data)
        walker.walk(tree.root_node)
        return walker.finish()
