"""Three-way ChangeSet over claim graphs (S4-owned).

The ChangeSet is the DIFF OF TWO CLAIM GRAPHS -- same semantic model, same owner:

    mb        = merge-base side      -> ClaimGraph(mb)
    A         = branch A             -> ClaimGraph(A)
    B         = branch B             -> ClaimGraph(B)
    provides_delta_X = diff(graph(mb), graph(X))   # ALWAYS base->side

`provides_delta_A` lists the surfaces A changed vs mb. The dependency set paired
against it during evaluation is ALWAYS the OPPOSITE head's resolved deps (B's), and
vice versa. Deltas are never diffed against each other and never against the base's
deps -- evaluation matches provider changes to consumer bindings, both directions,
nothing else.

Every emitted SurfaceChange carries `before`/`after` snapshots so rules and evidence
never need to re-derive context. Inconclusive comparisons produce NO change (INV-8):
e.g. a params diff requires both sides to declare a Signature; a return-type diff
requires non-null annotations on BOTH sides.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from semlock.graph.build import build_claim_graph
from semlock.graph.model import ClaimGraph, SymbolNode
from semlock.ir.model import FileFacts, Member, Param, Signature, Span

ChangeKind = Literal[
    "added",
    "removed",
    "unexported",
    "signature_changed",
    "return_changed",
    "member_removed",
]

# Fixed emission order for a symbol carrying several simultaneous changes.
_KIND_ORDER: Final[dict[str, int]] = {
    "removed": 0,
    "unexported": 1,
    "signature_changed": 2,
    "return_changed": 3,
    "member_removed": 4,
    "added": 5,
}


@dataclass(frozen=True, slots=True)
class SymbolSnapshot:
    """Projection of a SymbolNode used as before/after evidence."""

    id: str
    name: str
    kind: str
    span: Span
    exports: bool
    source_path: str
    bases: tuple[str, ...]
    signature: Signature | None
    members: tuple[Member, ...]

    @property
    def return_type(self) -> str | None:
        return self.signature.return_type if self.signature else None

    @property
    def params(self) -> tuple[Param, ...]:
        return self.signature.params if self.signature else ()

    def member_by_name(self, name: str) -> Member | None:
        for m in self.members:
            if m.name == name:
                return m
        return None


def snapshot(node: SymbolNode) -> SymbolSnapshot:
    return SymbolSnapshot(
        id=node.id,
        name=node.name,
        kind=node.kind,
        span=node.span,
        exports=node.exports,
        source_path=node.source_path,
        bases=node.bases,
        signature=node.signature,
        members=node.members,
    )


@dataclass(frozen=True, slots=True)
class SurfaceChange:
    """One consumed-surface delta, always oriented base -> head.

    `symbol_id` is the id a CONSUMER's resolved dependency binds to:
    the symbol id itself, except member_removed where it is the member's own
    canonical id `<owner_id>.<member>` (ADR-0008 grammar).
    `owner_id` is the declaring symbol id (== symbol_id except member_removed).
    """

    kind: ChangeKind
    symbol_id: str
    owner_id: str
    before: SymbolSnapshot | None
    after: SymbolSnapshot | None
    detail: str
    removed_member: Member | None = None


@dataclass(frozen=True, slots=True)
class ChangeSet:
    """Three-way semantic diff. Deltas are ALWAYS mb -> side (never side vs side).

    `changed_paths_a`/`changed_paths_b`: each side's git-diff-changed paths
    relative to the merge-base (ADR-0006's three-dot diff), when the caller
    has git context to provide them. `None` means "unknown" — evaluate()
    then applies no inherited-file filtering for that side, exactly matching
    pre-existing behavior (mock/fixture callers that never had git context
    are unaffected). When both are known, evaluate() excludes a dependency
    edge whose file the consumer never touched but the provider did: post-
    merge that file is entirely the provider's own (already self-consistent)
    version, not a stale copy the consumer genuinely depends on — regardless
    of whether it's the exact file the provider's symbol change lives in or
    some other file the same PR also touched."""

    base_ref: str
    a_ref: str
    b_ref: str
    base_graph: ClaimGraph
    a_graph: ClaimGraph
    b_graph: ClaimGraph
    provides_delta_a: tuple[SurfaceChange, ...]
    provides_delta_b: tuple[SurfaceChange, ...]
    changed_paths_a: frozenset[str] | None = None
    changed_paths_b: frozenset[str] | None = None


def diff_graphs(base: ClaimGraph, head: ClaimGraph) -> tuple[SurfaceChange, ...]:
    """Diff two claim graphs (conceptually base -> head) into surface changes."""
    base_by_id = {n.id: n for n in base.nodes}
    head_by_id = {n.id: n for n in head.nodes}
    changes: list[SurfaceChange] = []

    for symbol_id, old in base_by_id.items():
        new = head_by_id.get(symbol_id)
        if new is None:
            changes.append(
                SurfaceChange(
                    kind="removed",
                    symbol_id=symbol_id,
                    owner_id=symbol_id,
                    before=snapshot(old),
                    after=None,
                    detail="symbol removed"
                    + (" (was exported)" if old.exports else ""),
                )
            )
            continue
        new_snap = snapshot(new)
        old_snap = snapshot(old)
        if old.exports and not new.exports:
            changes.append(
                SurfaceChange(
                    kind="unexported",
                    symbol_id=symbol_id,
                    owner_id=symbol_id,
                    before=old_snap,
                    after=new_snap,
                    detail="export flag dropped (exported -> not exported)",
                )
            )
        sig_detail = _params_delta(old_snap, new_snap)
        if sig_detail is not None:
            changes.append(
                SurfaceChange(
                    kind="signature_changed",
                    symbol_id=symbol_id,
                    owner_id=symbol_id,
                    before=old_snap,
                    after=new_snap,
                    detail=sig_detail,
                )
            )
        ret_detail = _return_delta(old_snap, new_snap)
        if ret_detail is not None:
            changes.append(
                SurfaceChange(
                    kind="return_changed",
                    symbol_id=symbol_id,
                    owner_id=symbol_id,
                    before=old_snap,
                    after=new_snap,
                    detail=ret_detail,
                )
            )
        changes.extend(_member_removals(symbol_id, old_snap, new_snap))

    for symbol_id, new in head_by_id.items():
        if symbol_id not in base_by_id:
            changes.append(
                SurfaceChange(
                    kind="added",
                    symbol_id=symbol_id,
                    owner_id=symbol_id,
                    before=None,
                    after=snapshot(new),
                    detail="symbol added",
                )
            )

    changes.sort(key=_change_sort_key)
    return tuple(changes)


def _change_sort_key(change: SurfaceChange) -> tuple[str, int]:
    return (change.symbol_id, _KIND_ORDER[change.kind])


def _is_compatible_widening(old: str | None, new: str | None) -> bool:
    """True when `new` textually widens `old` to also accept None, so a
    caller passing the old-typed value still satisfies the new annotation
    (str -> str | None / Optional[str]). Conservative text patterns only —
    Constitution §3 rules out real type inference; this recognizes the
    written form, nothing else."""
    if old is None or new is None or old == new:
        return False
    return new in (f"{old} | None", f"None | {old}", f"Optional[{old}]")


def _params_delta(before: SymbolSnapshot, after: SymbolSnapshot) -> str | None:
    """Param-surface diff text, or None when unchanged, incomparable (INV-8:
    a missing Signature on either side means we cannot know the old form), or
    proven backward-compatible: a new TRAILING param with a default (existing
    callers omitting it still work) or a param's type widened to also accept
    None (existing callers passing the old type still satisfy the new one)."""
    if before.signature is None or after.signature is None:
        return None
    old_p, new_p = before.params, after.params
    if old_p == new_p:
        return None
    parts: list[str] = []
    breaking = False
    for i in range(max(len(old_p), len(new_p))):
        o = old_p[i] if i < len(old_p) else None
        n = new_p[i] if i < len(new_p) else None
        if o is None:
            assert n is not None
            if n.has_default:
                continue  # compatible: existing callers can omit it
            parts.append(f"position {i}: added '{n.name}'")
            breaking = True
            continue
        if n is None:
            parts.append(f"position {i}: removed '{o.name}'")
            breaking = True
            continue
        if o.name != n.name:
            parts.append(f"position {i}: '{o.name}' -> '{n.name}'")
            breaking = True
            continue
        if o == n:
            continue
        if (
            o.kind == n.kind
            and o.has_default == n.has_default
            and _is_compatible_widening(o.type_annotation, n.type_annotation)
        ):
            continue
        fields = [
            f"{f}: {getattr(o, f)!r} -> {getattr(n, f)!r}"
            for f in ("kind", "type_annotation", "has_default")
            if getattr(o, f) != getattr(n, f)
        ]
        parts.append(f"position {i} ({o.name}): " + ", ".join(fields))
        breaking = True
    if not breaking:
        return None
    joined = "; ".join(p for p in parts if p)
    return f"parameters changed: {joined}"


def _return_delta(before: SymbolSnapshot, after: SymbolSnapshot) -> str | None:
    """Return-type diff text, or None when unchanged OR incomparable (INV-8:
    null/absent annotation on EITHER side is statically incomparable -> never fires)."""
    old_t, new_t = before.return_type, after.return_type
    if old_t is None or new_t is None:
        return None
    if old_t == new_t:
        return None
    return f"declared return type changed: {old_t} -> {new_t}"


def _member_removals(
    owner_id: str, before: SymbolSnapshot, after: SymbolSnapshot
) -> list[SurfaceChange]:
    """Member-set diff (field_removed surface). Comparison is on the Member SET --
    names plus annotations -- NEVER on any language AST."""
    old_names = {m.name for m in before.members}
    new_names = {m.name for m in after.members}
    out: list[SurfaceChange] = []
    for name in sorted(old_names - new_names):
        member = before.member_by_name(name)
        assert member is not None
        annotation = (
            f" (was {member.type_annotation})" if member.type_annotation else ""
        )
        out.append(
            SurfaceChange(
                kind="member_removed",
                symbol_id=f"{owner_id}.{name}",
                owner_id=owner_id,
                before=before,
                after=after,
                detail=f"member '{name}' removed{annotation}",
                removed_member=member,
            )
        )
    return out


def build_changeset(
    base_files: tuple[FileFacts, ...],
    a_files: tuple[FileFacts, ...],
    b_files: tuple[FileFacts, ...],
    changed_paths_a: frozenset[str] | None = None,
    changed_paths_b: frozenset[str] | None = None,
) -> ChangeSet:
    """Build all three claim graphs and their mb->side deltas (version-gated).

    `changed_paths_a`/`changed_paths_b` are optional git-diff-changed path
    sets (base->side, three-dot) that let evaluate() distinguish a side's
    genuinely-edited files from files it merely inherited unchanged from the
    merge-base — see ChangeSet's docstring and evaluate()'s same-file
    inheritance filter."""
    base_graph = build_claim_graph(base_files)
    a_graph = build_claim_graph(a_files)
    b_graph = build_claim_graph(b_files)
    return ChangeSet(
        base_ref=base_graph.ref,
        a_ref=a_graph.ref,
        b_ref=b_graph.ref,
        base_graph=base_graph,
        a_graph=a_graph,
        b_graph=b_graph,
        provides_delta_a=diff_graphs(base_graph, a_graph),
        provides_delta_b=diff_graphs(base_graph, b_graph),
        changed_paths_a=changed_paths_a,
        changed_paths_b=changed_paths_b,
    )
