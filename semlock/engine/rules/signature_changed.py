"""signature_changed: callee's parameter surface changed vs a live caller.

Fires when the provider side changed a symbol's `Signature.params` (added / removed /
renamed / reordered / retyped / default-flipped) and the OPPOSITE head has a resolved
dependency binding to that exact symbol id.

Does NOT fire when either side lacks a Signature entirely (incomparable -> INV-8).
"""
from __future__ import annotations

from typing import ClassVar

from semlock.engine.changeset import SurfaceChange
from semlock.engine.evidence import Conflict, make_conflict
from semlock.engine.rules.base import Rule, RuleContext
from semlock.graph.model import DependencyEdge


class SignatureChangedRule(Rule):
    rule_id: ClassVar[str] = "signature_changed"
    conflict_class: ClassVar[str] = "signature_changed"

    def evaluate(
        self,
        change: SurfaceChange,
        dep: DependencyEdge,
        ctx: RuleContext,
    ) -> Conflict | None:
        if not self._guard(change, dep):
            return None
        if change.kind != "signature_changed":
            return None
        assert dep.target_id is not None
        if dep.target_id != change.symbol_id:
            return None
        before, after = change.before, change.after
        if before is None or after is None:
            return None
        explanation = (
            f"Rule signature_changed: branch {ctx.provider_side} changed the "
            f"parameters of {change.symbol_id} ({change.detail}); branch "
            f"{ctx.consumer_side} still calls it as '{dep.name}' at "
            f"{dep.path}:{dep.span.start_line} using the old parameter form. "
            f"Git can merge this textually clean; the call site breaks at runtime."
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


RULE: Rule = SignatureChangedRule()
