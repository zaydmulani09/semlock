"""return_changed: declared return type changed vs consumers relying on the old one.

Fires ONLY when `Signature.return_type` is statically comparable on BOTH sides --
both non-null annotations -- and the texts differ (INV-8: an unknown/null return on
either side means NO finding; inconclusive is the honest answer).
"""
from __future__ import annotations

from typing import ClassVar

from semlock.engine.changeset import SurfaceChange
from semlock.engine.evidence import Conflict, make_conflict
from semlock.engine.rules.base import Rule, RuleContext
from semlock.graph.model import DependencyEdge

_CONSUMER_DEP_KINDS = ("call", "read")


class ReturnChangedRule(Rule):
    rule_id: ClassVar[str] = "return_changed"
    conflict_class: ClassVar[str] = "return_changed"

    def evaluate(
        self,
        change: SurfaceChange,
        dep: DependencyEdge,
        ctx: RuleContext,
    ) -> Conflict | None:
        if not self._guard(change, dep):
            return None
        if change.kind != "return_changed":
            return None
        if dep.kind not in _CONSUMER_DEP_KINDS:
            return None
        assert dep.target_id is not None
        if dep.target_id != change.symbol_id:
            return None
        before, after = change.before, change.after
        if before is None or after is None:
            return None
        old_t, new_t = before.return_type, after.return_type
        # INV-8 choke for this class: both sides must be statically comparable.
        if old_t is None or new_t is None or old_t == new_t:
            return None
        explanation = (
            f"Rule return_changed: branch {ctx.provider_side} changed the declared "
            f"return type of {change.symbol_id} from {old_t} to {new_t} "
            f"({after.source_path}), but branch {ctx.consumer_side} consumes its "
            f"result as '{dep.name}' at {dep.path}:{dep.span.start_line}, relying "
            f"on the old type."
        )
        return make_conflict(
            rule=self.rule_id,
            conflict_class=self.conflict_class,
            changed_symbol_id=change.symbol_id,
            changed_side=ctx.provider_side,
            changed_path=after.source_path,
            changed_line=after.span.start_line,
            changed_col=after.span.start_col,
            consumer_ref_name=dep.name,
            consumer_ref_kind=dep.kind,
            consumer_path=dep.path,
            consumer_span=dep.span,
            target_id=dep.target_id,
            explanation=explanation,
        )


RULE: Rule = ReturnChangedRule()
