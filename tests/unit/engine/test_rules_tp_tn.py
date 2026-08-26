"""Per-rule TP + TN (Constitution §7.2: a rule without both is not done).

Every rule is exercised through the REAL pipeline (build_changeset + evaluate) with
hand-built minimal facts -- no rule-internal shortcuts.
"""
from __future__ import annotations

from builders import facts, member, param, ref, sig, symbol

from semlock.engine import build_changeset, evaluate


def _run(base_files, a_files, b_files):
    cs = build_changeset(
        tuple(base_files), tuple(a_files), tuple(b_files)
    )
    return evaluate(cs)


# ---------------------------------------------------------------- signature_changed


def test_signature_changed_tp() -> None:
    base = (
        symbol("m::greet", sl=2,
               signature=sig((param("self", 0), param("name", 1, "str")), "str")),
    )
    changed = (
        symbol("m::greet", sl=2,
               signature=sig((param("self", 0), param("greeting", 1, "str")), "str")),
    )
    res = _run(
        [facts("mb.py", symbols=base)],
        [facts("a.py", symbols=changed)],
        [facts("b.py", symbols=base,
               refs=(ref("greet", target="m::greet", sl=7, col=4),))],
    )
    assert len(res.conflicts) == 1
    c = res.conflicts[0]
    assert (c.rule, c.conflict_class) == ("signature_changed", "signature_changed")
    assert c.changed_symbol_id == "m::greet"
    assert (c.changed_side, c.consumer_side) == ("A", "B")
    # INV-9: dual-sided evidence + explanation naming both sides and the rule.
    assert c.evidence_a.path == "a.py" and c.evidence_a.line == 2
    assert c.evidence_b.path == "b.py" and c.evidence_b.line == 7
    assert "signature_changed" in c.explanation
    assert "'name' -> 'greeting'" in c.explanation
    assert "b.py" in c.explanation


def test_signature_changed_tn_identical_params() -> None:
    same = (symbol("m::f", sl=2, signature=sig((param("x", 0, "int"),), "int")),)
    res = _run(
        [facts("mb.py", symbols=same)],
        [facts("a.py", symbols=same)],
        [facts("b.py", symbols=same, refs=(ref("f", target="m::f", sl=3),))],
    )
    assert res.conflicts == ()


def test_signature_changed_tn_base_signature_unknown() -> None:
    """INV-8: without the old Signature we cannot claim the params changed."""
    unknown = (symbol("m::f", sl=2),)
    known = (symbol("m::f", sl=2, signature=sig((param("x", 0),), None)),)
    res = _run(
        [facts("mb.py", symbols=unknown)],
        [facts("a.py", symbols=known)],
        [facts("b.py", symbols=unknown, refs=(ref("f", target="m::f", sl=3),))],
    )
    assert res.conflicts == ()


def test_signature_changed_tn_no_consumer() -> None:
    old = (symbol("m::f", sl=2, signature=sig((param("x", 0),), None)),)
    new = (symbol("m::f", sl=2, signature=sig((param("y", 0),), None)),)
    res = _run(
        [facts("mb.py", symbols=old)],
        [facts("a.py", symbols=new)],   # nobody on B binds m::f
        [facts("b.py", symbols=old)],
    )
    assert res.conflicts == ()


# ------------------------------------------------------- removed_or_renamed_export


def test_removed_export_tp() -> None:
    exported = (symbol("m::api", sl=2, exports=True),)
    gone = ()
    res = _run(
        [facts("mb.py", symbols=exported)],
        [facts("a.py", symbols=gone)],
        [facts("b.py", symbols=exported,
               refs=(ref("api", kind="import", target="m::api", sl=1,
                         module_specifier="m"),))],
    )
    assert len(res.conflicts) == 1
    c = res.conflicts[0]
    assert (c.rule, c.conflict_class) == ("removed_or_renamed_export", "removed_export")
    assert c.consumer_ref_name == "api"
    assert "imports it as 'api'" in c.explanation
    assert c.evidence_a.path == "mb.py" or c.evidence_a.path == "a.py"


def test_removed_export_tn_not_imported() -> None:
    exported = (symbol("m::api", sl=2, exports=True),)
    res = _run(
        [facts("mb.py", symbols=exported)],
        [facts("a.py", symbols=())],            # deleted...
        [facts("b.py", symbols=exported)],      # ...but B never imports it
    )
    assert res.conflicts == ()


def test_removed_export_tn_unexported_but_only_called_not_imported() -> None:
    sym = (symbol("m::u", sl=2, exports=True),)
    unexported = (symbol("m::u", sl=2, exports=False),)
    res = _run(
        [facts("mb.py", symbols=sym)],
        [facts("a.py", symbols=unexported)],
        [
            facts(
                "b.py",
                symbols=sym,
                refs=(ref("u", kind="call", target="m::u", sl=5),),
            )
        ],
    )
    assert res.conflicts == ()  # import-kind deps only for this class


def test_removed_internal_symbol_never_fires_on_import_of_other_id() -> None:
    internal_gone = (symbol("m::_priv", sl=2, exports=False),
                     symbol("m::kept", sl=3, exports=True))
    res = _run(
        [facts("mb.py", symbols=internal_gone)],
        [facts("a.py", symbols=(symbol("m::kept", sl=3, exports=True),))],
        [facts("b.py", symbols=internal_gone,
               refs=(ref("kept", kind="import", target="m::kept", sl=1),))],
    )
    assert res.conflicts == ()


# ------------------------------------------------------------------- field_removed


def test_field_removed_tp_member_own_id() -> None:
    base_cls = (
        symbol("pkg.models::User", kind="class", sl=2,
               members=(member("email", "str | None", sl=6),)),
    )
    stripped_cls = (
        symbol("pkg.models::User", kind="class", sl=2, members=()),
    )
    res = _run(
        [facts("mb/models.py", symbols=base_cls)],
        [facts("a/models.py", symbols=stripped_cls)],
        [facts("b/app.py", symbols=base_cls,
               refs=(ref("email", kind="attribute",
                         target="pkg.models::User.email", sl=9, col=8),))],
    )
    assert len(res.conflicts) == 1
    c = res.conflicts[0]
    assert (c.rule, c.conflict_class) == ("field_removed", "field_removed")
    assert c.changed_symbol_id == "pkg.models::User.email"
    assert c.evidence_a.line == 6  # the MEMBER's span, not the class's
    assert "field 'email'" in c.explanation


def test_field_removed_tn_dep_kind_call_does_not_fire() -> None:
    base_cls = (
        symbol("C::K", kind="class", sl=2, members=(member("run", sl=4),)),
    )
    res = _run(
        [facts("mb.py", symbols=base_cls)],
        [facts("a.py", symbols=(symbol("C::K", kind="class", sl=2),))],
        [facts("b.py", symbols=base_cls,
               refs=(ref("run", kind="call", target="C::K.run", sl=7),))],
    )
    assert res.conflicts == ()


def test_field_removed_tn_annotation_change_is_not_removal() -> None:
    before = (symbol("C::K", kind="class", sl=2, members=(member("x", "int"),)),)
    after = (symbol("C::K", kind="class", sl=2, members=(member("x", "str"),)),)
    res = _run(
        [facts("mb.py", symbols=before)],
        [facts("a.py", symbols=after)],
        [facts("b.py", symbols=before,
               refs=(ref("x", kind="read", target="C::K.x", sl=5),))],
    )
    assert res.conflicts == ()  # member SET unchanged -> out of v1 scope


# ------------------------------------------------------------------ return_changed


def test_return_changed_tp() -> None:
    base = (symbol("m::f", sl=2, signature=sig((param("x", 0),), "str")),)
    changed = (
        symbol("m::f", sl=2, signature=sig((param("x", 0),), "GreetingResult")),
    )
    res = _run(
        [facts("mb.py", symbols=base)],
        [facts("a.py", symbols=changed)],
        [facts("b.py", symbols=base,
               refs=(ref("f", kind="call", target="m::f", sl=8),))],
    )
    assert len(res.conflicts) == 1
    c = res.conflicts[0]
    assert (c.rule, c.conflict_class) == ("return_changed", "return_changed")
    assert "str" in c.explanation and "GreetingResult" in c.explanation


def test_return_changed_tn_null_annotation_either_side() -> None:
    typed = (symbol("m::f", sl=2, signature=sig((param("x", 0),), "str")),)
    untyped = (symbol("m::f", sl=2, signature=sig((param("x", 0),), None)),)
    dep = (ref("f", kind="call", target="m::f", sl=8),)
    a_to_untyped = _run(
        [facts("mb.py", symbols=typed)],
        [facts("a.py", symbols=untyped)],
        [facts("b.py", symbols=typed, refs=dep)],
    )
    b_to_typed = _run(
        [facts("mb.py", symbols=untyped)],
        [facts("a.py", symbols=typed)],
        [facts("b.py", symbols=untyped, refs=dep)],
    )
    assert a_to_untyped.conflicts == ()  # INV-8: inconclusive both ways
    assert b_to_typed.conflicts == ()


def test_return_changed_tn_write_kind_ignored() -> None:
    base = (symbol("m::f", sl=2, signature=sig((param("x", 0),), "str")),)
    changed = (symbol("m::f", sl=2, signature=sig((param("x", 0),), "bytes")),)
    res = _run(
        [facts("mb.py", symbols=base)],
        [facts("a.py", symbols=changed)],
        [facts("b.py", symbols=base,
               refs=(ref("f", kind="write", target="m::f", sl=8),))],
    )
    assert res.conflicts == ()


# --------------------------------------------------------------- reverse direction


def test_reverse_direction_b_changes_a_consumes() -> None:
    base = (symbol("m::f", sl=2, signature=sig((param("x", 0),), "str")),)
    changed = (symbol("m::f", sl=2, signature=sig((param("y", 0),), "str")),)
    res = _run(
        [facts("mb.py", symbols=base)],
        [facts("a.py", symbols=base,
               refs=(ref("f", kind="call", target="m::f", sl=4),))],
        [facts("b.py", symbols=changed)],
    )
    assert len(res.conflicts) == 1
    c = res.conflicts[0]
    assert (c.changed_side, c.consumer_side) == ("B", "A")
    assert c.evidence_a.role == "consuming_use"
    assert c.evidence_b.role == "changed_definition"


def test_both_sides_change_same_symbol_mutual_conflicts() -> None:
    base = (symbol("m::f", sl=2, signature=sig((param("x", 0),), "str")),)
    a_new = (symbol("m::f", sl=2, signature=sig((param("a", 0),), "str")),)
    b_new = (symbol("m::f", sl=2, signature=sig((param("b", 0),), "str")),)
    res = _run(
        [facts("mb.py", symbols=base)],
        [facts("a.py", symbols=a_new,
               refs=(ref("f", kind="call", target="m::f", sl=4),))],
        [facts("b.py", symbols=b_new,
               refs=(ref("f", kind="call", target="m::f", sl=4),))],
    )
    sides = sorted(c.changed_side for c in res.conflicts)
    assert sides == ["A", "B"]  # each side broke the other's call site
