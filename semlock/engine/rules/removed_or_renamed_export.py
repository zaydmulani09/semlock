"""removed_or_renamed_export: an exported symbol the other head imports is gone.

Fires when the provider side REMOVED a symbol (id vanished) or UNEXPORTED it
(exports True -> False) while the opposite head still holds a resolved IMPORT-kind
dependency bound to that id (renames surface as removal of the old id).

Re-export chains (INV-7 briefing): when the imported id was an alias-shaped
re-export site (variable/type_alias with no signature/members), the rule follows the
base graph's import edges to find the ORIGINAL id. If the original survives intact,
the explanation says so -- but the conflict still fires, because B's import path is
broken either way. If evidence for the chain is missing, the plain removal verdict
stands; the chain only ever ENRICHES the explanation, never manufactures one.
"""
from __future__ import annotations

from typing import ClassVar

from semlock.engine.changeset import SurfaceChange
from semlock.engine.evidence import Conflict, make_conflict
from semlock.engine.rules.base import Rule, RuleContext
from semlock.graph.model import ClaimGraph, DependencyEdge, SymbolNode


class RemovedOrRenamedExportRule(Rule):
    rule_id: ClassVar[str] = "removed_or_renamed_export"
    conflict_class: ClassVar[str] = "removed_export"

    def evaluate(
        self,
        change: SurfaceChange,
        dep: DependencyEdge,
        ctx: RuleContext,
    ) -> Conflict | None:
        if not self._guard(change, dep):
            return None
        if change.kind not in ("removed", "unexported"):
            return None
        if dep.kind != "import":
            return None
        assert dep.target_id is not None
        if dep.target_id != change.symbol_id:
            return None
        before = change.before
        if before is None:
            return None

        origin_note = _reexport_note(dep.target_id, ctx.base_graph, ctx.provider_graph)
        where = (
            "deleted from"
            if change.kind == "removed"
            else "no longer exported by"
        )
        explanation = (
            f"Rule removed_or_renamed_export: branch {ctx.provider_side} "
            f"{where} {change.symbol_id} ({before.source_path}), but branch "
            f"{ctx.consumer_side} still imports it as '{dep.name}' at "
            f"{dep.path}:{dep.span.start_line}.{origin_note}"
        )
        # For a pure removal the definition no longer exists on the provider side;
        # evidence points at its former base location via the `before` snapshot.
        return make_conflict(
            rule=self.rule_id,
            conflict_class=self.conflict_class,
            changed_symbol_id=change.symbol_id,
            changed_side=ctx.provider_side,
            changed_path=before.source_path,
            changed_line=before.span.start_line,
            changed_col=before.span.start_col,
            consumer_ref_name=dep.name,
            consumer_ref_kind=dep.kind,
            consumer_path=dep.path,
            consumer_span=dep.span,
            target_id=dep.target_id,
            explanation=explanation,
        )


def _reexport_note(
    target_id: str, base_graph: ClaimGraph, provider_graph: ClaimGraph
) -> str:
    """Follow one re-export hop in the BASE graph; enrich or stay silent."""
    node = _find(base_graph, target_id)
    if node is None or node.kind not in ("variable", "type_alias"):
        return ""
    if node.signature is not None or node.members:
        return ""
    origin_id = _origin_via_import(base_graph, node)
    if origin_id is None or origin_id == target_id:
        return ""
    survivor = _find(provider_graph, origin_id)
    if survivor is not None:
        return (
            f" Note: '{target_id}' was a re-export of '{origin_id}', which still "
            f"exists on branch {provider_graph.ref}; only the re-export path broke."
        )
    return (
        f" Note: '{target_id}' was a re-export of '{origin_id}', which is also "
        f"missing on branch {provider_graph.ref}."
    )


def _find(graph: ClaimGraph, symbol_id: str) -> SymbolNode | None:
    for n in graph.nodes:
        if n.id == symbol_id:
            return n
    return None


def _origin_via_import(base_graph: ClaimGraph, node: SymbolNode) -> str | None:
    """The resolved import in the re-export site's file whose binding name matches
    the re-exported symbol name."""
    candidates = [
        e.target_id
        for e in base_graph.dep_edges
        if e.is_eligible
        and e.kind == "import"
        and e.path == node.source_path
        and (
            e.name == node.name
            or e.target_id == f"{_module_of(node.id)}::{node.name}"
        )
    ]
    unique = sorted({t for t in candidates if t})
    if len(unique) == 1:
        return unique[0]
    return None


def _module_of(symbol_id: str) -> str:
    return symbol_id.rsplit("::", 1)[0] if "::" in symbol_id else symbol_id


RULE: Rule = RemovedOrRenamedExportRule()
