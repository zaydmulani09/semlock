"""field_removed: a class/interface member removed vs live reads/writes.

Fires when the provider side removed a Member from a symbol and the opposite head
has a resolved read/write/attribute dependency bound to the member's OWN canonical
id `<owner_id>.<member>` (ADR-0008). Comparison is on the Member SET only -- never
any language AST.
"""
from __future__ import annotations

from typing import ClassVar

from semlock.engine.changeset import SurfaceChange
from semlock.engine.evidence import Conflict, make_conflict
from semlock.engine.rules.base import Rule, RuleContext
from semlock.graph.model import DependencyEdge

_MEMBER_DEP_KINDS = ("read", "write", "attribute")


class FieldRemovedRule(Rule):
    rule_id: ClassVar[str] = "field_removed"
    conflict_class: ClassVar[str] = "field_removed"

    def evaluate(
        self,
        change: SurfaceChange,
        dep: DependencyEdge,
        ctx: RuleContext,
    ) -> Conflict | None:
        if not self._guard(change, dep):
            return None
        if change.kind != "member_removed":
            return None
        if dep.kind not in _MEMBER_DEP_KINDS:
            return None
        assert dep.target_id is not None
        if dep.target_id != change.symbol_id:
            return None
        before, member = change.before, change.removed_member
        if before is None or member is None:
            return None
        annotation = (
            f" of type {member.type_annotation}" if member.type_annotation else ""
        )
        explanation = (
            f"Rule field_removed: branch {ctx.provider_side} removed field "
            f"'{member.name}'{annotation} from {change.owner_id} "
            f"({before.source_path}); the binding {change.symbol_id} no longer "
            f"exists there, but branch {ctx.consumer_side} still accesses it as "
            f"'{dep.name}' at {dep.path}:{dep.span.start_line}. The attribute "
            f"access breaks at runtime."
        )
        return make_conflict(
            rule=self.rule_id,
            conflict_class=self.conflict_class,
            changed_symbol_id=change.symbol_id,
            changed_side=ctx.provider_side,
            # The member's own span is the precise evidence location.
            changed_path=before.source_path,
            changed_line=member.span.start_line,
            changed_col=member.span.start_col,
            consumer_ref_name=dep.name,
            consumer_ref_kind=dep.kind,
            consumer_path=dep.path,
            consumer_span=dep.span,
            target_id=dep.target_id,
            explanation=explanation,
        )


RULE: Rule = FieldRemovedRule()
