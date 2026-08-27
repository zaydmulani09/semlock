"""Three-way ChangeSet diff (S4 unit tests): delta kinds, direction, determinism."""
from __future__ import annotations

import pytest
from builders import facts, member, param, ref, sig, symbol

from semlock.engine import evaluate
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


def test_added_trailing_param_with_default_is_compatible() -> None:
    """Existing callers omitting the new param still work — no conflict."""
    base = symbol("m::f", sl=2, signature=sig((param("a", 0),), "int"))
    head = symbol(
        "m::f", sl=2,
        signature=sig((param("a", 0), param("b", 1, has_default=True)), "int"),
    )
    cs = _cs((base,), (head,), (base,))
    assert cs.provides_delta_a == ()


def test_added_trailing_required_param_still_fires() -> None:
    """Same shape, but the new param has NO default — existing callers break."""
    base = symbol("m::f", sl=2, signature=sig((param("a", 0),), "int"))
    head = symbol(
        "m::f", sl=2,
        signature=sig((param("a", 0), param("b", 1, has_default=False)), "int"),
    )
    cs = _cs((base,), (head,), (base,))
    assert [c.kind for c in cs.provides_delta_a] == ["signature_changed"]
    assert "added 'b'" in cs.provides_delta_a[0].detail


@pytest.mark.parametrize(
    "old_type,new_type",
    [("str", "str | None"), ("str", "None | str"), ("str", "Optional[str]")],
)
def test_param_type_widened_to_optional_is_compatible(old_type, new_type) -> None:
    """Callers passing the old type still satisfy the widened annotation."""
    base = symbol("m::f", sl=2, signature=sig((param("a", 0, old_type),), "int"))
    head = symbol("m::f", sl=2, signature=sig((param("a", 0, new_type),), "int"))
    cs = _cs((base,), (head,), (base,))
    assert cs.provides_delta_a == ()


def test_param_type_narrowed_from_optional_still_fires() -> None:
    """The reverse direction (None -> str) is a real breaking narrowing."""
    base = symbol("m::f", sl=2, signature=sig((param("a", 0, "str | None"),), "int"))
    head = symbol("m::f", sl=2, signature=sig((param("a", 0, "str"),), "int"))
    cs = _cs((base,), (head,), (base,))
    assert [c.kind for c in cs.provides_delta_a] == ["signature_changed"]


def test_widened_param_alongside_a_real_change_still_fires_for_the_real_one() -> None:
    """A compatible widening at one position must not mask a real break at
    another position in the same signature."""
    base = symbol(
        "m::f", sl=2,
        signature=sig((param("a", 0, "str"), param("b", 1, "int")), "int"),
    )
    head = symbol(
        "m::f", sl=2,
        signature=sig(
            (param("a", 0, "str | None"), param("b", 1, "bytes")), "int"
        ),
    )
    cs = _cs((base,), (head,), (base,))
    assert [c.kind for c in cs.provides_delta_a] == ["signature_changed"]
    detail = cs.provides_delta_a[0].detail
    assert "position 1" in detail
    assert "position 0" not in detail  # the compatible widening is silent


def test_refs_are_kept_on_graphs() -> None:
    from semlock.engine.changeset import ChangeSet as _  # noqa: F401

    base_files = (
        facts("c.py", symbols=(symbol("m::f", sl=2),),
              refs=(ref("f", target="m::f", sl=6),)),
    )
    cs = build_changeset(base_files, base_files, base_files)
    assert len(cs.b_graph.dep_edges) == 1
    assert cs.b_graph.eligible_deps()[0].target_id == "m::f"


# --- inherited-file filter (real-world kill-test finding) -----------------
#
# Provider (A) changes m::greet. Consumer (B)'s facts for the file the
# dependency edge lives in still show the OLD form — either because B
# genuinely never touched that file (inherited unchanged from the
# merge-base; post-merge git takes A's whole self-consistent file, so this
# is not a real break) or because B independently edited it (a real
# conflict, whether same-file-different-region or ordinary cross-file).
# Telling these apart needs BOTH sides' git-diff-changed paths — a lone
# consumer-side signal isn't enough: if the provider ALSO never touched that
# file, it's genuinely untouched by both sides (the ordinary, most basic
# conflict shape) and must never be excluded. Omitting either side's set
# (None) preserves pre-existing, unfiltered behavior for callers with no
# git context (mocks, fixtures).


def _consumer_ref_case(
    consumer_path: str,
    changed_paths_a: frozenset[str] | None,
    changed_paths_b: frozenset[str] | None,
):
    old = symbol("m::greet", sl=2, signature=sig((param("name", 0, "str"),), "str"))
    new = symbol(
        "m::greet", sl=2, signature=sig((param("greeting", 0, "str"),), "str")
    )
    base_files = (facts("pkg/models.py", symbols=(old,)),)
    a_files = (facts("pkg/models.py", symbols=(new,)),)
    b_files = (
        facts(
            consumer_path,
            symbols=(old,) if consumer_path == "pkg/models.py" else (),
            refs=(ref("greet", target="m::greet", sl=9),),
        ),
    )
    cs = build_changeset(
        base_files, a_files, b_files,
        changed_paths_a=changed_paths_a, changed_paths_b=changed_paths_b,
    )
    return evaluate(cs)


def test_ref_fires_when_no_git_context_given() -> None:
    """Either side's changed_paths missing: no filtering, matches
    pre-existing behavior."""
    result = _consumer_ref_case("pkg/models.py", None, None)
    assert len(result.conflicts) == 1
    assert result.stats.deps_same_file_inherited == 0


def test_ref_silenced_when_consumer_never_touched_provider_touched_file() -> None:
    """B's git diff doesn't include pkg/models.py, but A's does: it's an
    inherited, stale copy — post-merge the file is entirely A's
    (self-consistent) version."""
    result = _consumer_ref_case(
        "pkg/models.py",
        frozenset({"pkg/models.py"}), frozenset({"pkg/other.py"}),
    )
    assert result.conflicts == ()
    assert result.stats.deps_same_file_inherited == 1


def test_ref_still_fires_when_consumer_also_touched_that_file() -> None:
    """B's git diff DOES include pkg/models.py too: a genuine same-file,
    different-region conflict — must still fire."""
    result = _consumer_ref_case(
        "pkg/models.py",
        frozenset({"pkg/models.py"}), frozenset({"pkg/models.py"}),
    )
    assert len(result.conflicts) == 1
    assert result.stats.deps_same_file_inherited == 0


def test_ref_fires_when_untouched_by_both_sides() -> None:
    """Neither side's git diff includes the consumer's file (the ordinary,
    most basic conflict shape: an unrelated file quietly depends on what
    just changed) — never excluded, even with full git context."""
    result = _consumer_ref_case(
        "pkg/app.py",
        frozenset({"pkg/models.py"}), frozenset(),
    )
    assert len(result.conflicts) == 1
    assert result.stats.deps_same_file_inherited == 0


def test_cross_file_ref_silenced_when_provider_also_touched_it() -> None:
    """Real kill-test case (pydantic#12147 x #12333): the symbol is DEFINED
    in one file but the provider's OWN PR also edits a DIFFERENT file where
    it's consumed (its own internal caller). Consumer (B) never touches that
    second file either. Post-merge it's entirely the provider's version —
    excluded exactly like the same-file case, not just when paths match."""
    result = _consumer_ref_case(
        "pkg/app.py",
        frozenset({"pkg/models.py", "pkg/app.py"}), frozenset(),
    )
    assert result.conflicts == ()
    assert result.stats.deps_same_file_inherited == 1
