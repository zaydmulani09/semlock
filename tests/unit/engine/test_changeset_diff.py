"""Three-way ChangeSet diff (S4 unit tests): delta kinds, direction, determinism."""
from __future__ import annotations

import pytest
from builders import facts, member, param, ref, sig, symbol

from semlock.engine.changeset import build_changeset, diff_graphs
from semlock.graph import build_claim_graph


def _cs(base, a, b):
    return build_changeset(
        (facts("mb.py", symbols=base),), (facts("a.py", symbols=a),),
        (facts("b.py", symbols=b),),
    )


def test_param_rename_is_signature_changed() -> None:
    old = symbol("m::f", sl=2, signature=sig((param("name", 0, "str"),), "str"))
    new = symbol("m::f", sl=2, signature=sig((param("greeting", 0, "str"),), "str"))
    cs = _cs((old,), (new,), (old,))
    kinds = [c.kind for c in cs.provides_delta_a]
    assert kinds == ["signature_changed"]
    change = cs.provides_delta_a[0]
    assert "'name' -> 'greeting'" in change.detail
    # Direction law: mb->A only; B untouched => empty.
    assert cs.provides_delta_b == ()


def test_return_type_change_and_inconclusive_cases() -> None:
    base = symbol("m::f", sl=2, signature=sig((), "str"))
    changed = symbol("m::f", sl=2, signature=sig((), "GreetingResult"))
    annotation_removed = symbol("m::f", sl=2, signature=sig((), None))
    cs = _cs((base,), (changed,), (annotation_removed,))
    assert [c.kind for c in cs.provides_delta_a] == ["return_changed"]
    # INV-8: str -> null is statically incomparable on one side => NO change.
    assert cs.provides_delta_b == ()


def test_missing_signature_on_either_side_is_inconclusive() -> None:
    no_sig = symbol("m::f", sl=2)
    with_sig = symbol("m::f", sl=2, signature=sig((param("x", 0),), "int"))
    cs = _cs((no_sig,), (with_sig,), (no_sig,))
    assert cs.provides_delta_a == ()  # cannot know the old form -> nothing


def test_member_removed_uses_member_own_id() -> None:
    base = symbol(
        "pkg.models::User",
        kind="class",
        members=(member("email", "str | None"), member("id", "int")),
    )
    head = symbol("pkg.models::User", kind="class", members=(member("id", "int"),))
    cs = _cs((base,), (head,), (base,))
    changes = cs.provides_delta_a
    assert len(changes) == 1
    c = changes[0]
    assert c.kind == "member_removed"
    assert c.symbol_id == "pkg.models::User.email"  # ADR-0008 member id
    assert c.owner_id == "pkg.models::User"
    assert c.removed_member is not None and c.removed_member.name == "email"


def test_removed_unexported_added_kinds() -> None:
    gone = symbol("m::gone", exports=True, sl=2)
    hidden = symbol("m::hidden", exports=True, sl=3)
    still = symbol("m::still", sl=4)
    base = (gone, hidden, still)
    head = (symbol("m::hidden", exports=False, sl=3), still,
            symbol("m::fresh", sl=5))
    cs = _cs(base, head, base)
    by_id = {c.symbol_id: c for c in cs.provides_delta_a}
    assert by_id["m::gone"].kind == "removed"
    assert by_id["m::hidden"].kind == "unexported"
    assert by_id["m::fresh"].kind == "added"
    assert set(by_id) == {"m::gone", "m::hidden", "m::fresh"}


def test_simultaneous_sig_and_return_changes_both_emitted() -> None:
    base = symbol("m::f", sl=2, signature=sig((param("a", 0),), "str"))
    head = symbol("m::f", sl=2, signature=sig((param("b", 0),), "bytes"))
    cs = _cs((base,), (head,), (base,))
    assert sorted(c.kind for c in cs.provides_delta_a) == [
        "return_changed",
        "signature_changed",
    ]


def test_dep_edges_do_not_influence_deltas() -> None:
    """Deltas are pure surface diffs; refs ride along on graphs, not deltas."""
    base = (
        symbol("m::f", sl=2, signature=sig((param("x", 0),), None)),
        )
    cs = _cs(base, base, base)
    assert cs.provides_delta_a == () and cs.provides_delta_b == ()
    assert cs.base_graph.dep_edges == ()


def test_diff_is_order_deterministic() -> None:
    old = symbol("m::f", sl=2, signature=sig((param("name", 0, "str"),), "str"))
    new = symbol("m::f", sl=2, signature=sig((param("greeting", 0, "str"),), "str"))
    g1 = build_claim_graph((facts("p.py", symbols=(old,)),))
    g2 = build_claim_graph((facts("p.py", symbols=(new,)),))
    assert diff_graphs(g1, g2) == diff_graphs(g1, g2)


@pytest.mark.parametrize(
    "left,right",
    [(param("a", 0, "int"), param("a", 0, "str")),   # retyped
     (param("a", 0, "int", True), param("a", 0, "int", False)),  # default flipped
     (param("a", 0), param("a", 0, kind="keyword_only"))],        # kind changed
)
def test_param_fieldwise_deltas_fire(left, right) -> None:
    base = symbol("m::f", sl=2, signature=sig((left,), "int"))
    head = symbol("m::f", sl=2, signature=sig((right,), "int"))
    cs = _cs((base,), (head,), (base,))
    assert [c.kind for c in cs.provides_delta_a] == ["signature_changed"]


def test_ref_kinds_survive_into_graphs() -> None:
    cs = _cs(
        (), (),
        (symbol("m::h", sl=1),),
    )
    # trivial: no symbols anywhere -> empty deltas, empty edges
    assert cs.a_graph.dep_edges == ()


def test_refs_are_kept_on_graphs() -> None:
    from semlock.engine.changeset import ChangeSet as _  # noqa: F401

    base_files = (
        facts("c.py", symbols=(symbol("m::f", sl=2),),
              refs=(ref("f", target="m::f", sl=6),)),
    )
    cs = build_changeset(base_files, base_files, base_files)
    assert len(cs.b_graph.dep_edges) == 1
    assert cs.b_graph.eligible_deps()[0].target_id == "m::f"
