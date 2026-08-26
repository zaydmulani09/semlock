"""INV-2: UNRESOLVED IS NEVER A MATCH -- the choke, proven end-to-end.

Unresolved / ambiguous / external deps must yield ZERO conflicts even when the very
symbol they WOULD bind to changed on the other side. The IR makes this structural
(non-resolved resolutions cannot carry target_id), and evaluate.py re-enforces it
with an explicit eligible-only index plus per-rule guards. All three layers are
tested here.
"""
from __future__ import annotations

import pytest
from builders import facts, param, ref, sig, symbol

from semlock.engine import build_changeset, eligible_deps, evaluate
from semlock.engine.rules import REGISTRY
from semlock.graph.model import DependencyEdge
from semlock.ir.model import Span


def _base_files():
    """mb carries the OLD surface, so the provider side genuinely emits a
    signature_changed delta for m::greet."""
    return facts(
        "mb.py",
        symbols=(
            symbol(
                "m::greet",
                sl=2,
                signature=sig((param("self", 0), param("name", 1, "str")), "str"),
            ),
        ),
    )


def _changed_provider_files():
    return facts(
        "a/models.py",
        symbols=(
            symbol(
                "m::greet",
                sl=2,
                signature=sig((param("self", 0), param("greeting", 1, "str")), "str"),
            ),
        ),
    )


def _consumer_files(refs):
    return facts("b/app.py", symbols=(symbol("m::app", sl=1),), refs=tuple(refs))


@pytest.mark.parametrize("status", ["unresolved", "ambiguous", "external"])
def test_non_resolved_status_never_matches(status: str) -> None:
    """The dep 'would' target m::greet -- but only resolved edges carry targets."""
    cs = build_changeset(
        (_base_files(),),
        (_changed_provider_files(),),
        (_consumer_files((ref("greet", kind="call", target="m::greet",
                            status=status,  # type: ignore[arg-type]
                            sl=4),)),),
    )
    result = evaluate(cs)
    assert result.conflicts == ()
    assert result.stats.pairings_evaluated == 0
    assert result.stats.deps_eligible == 0
    assert result.stats.deps_chocked >= 1


def test_mixed_resolved_and_chocked_only_resolved_counts() -> None:
    cs = build_changeset(
        (_base_files(),),
        (_changed_provider_files(),),
        (
            _consumer_files(
                (
                    ref("greet_u", status="unresolved", sl=1),      # chocked
                    ref("greet_a", status="ambiguous", sl=2),       # chocked
                    ref("print", status="external", sl=3),          # chocked
                    ref("greet", target="m::greet", sl=4),          # resolved: fires
                )
            ),
        ),
    )
    result = evaluate(cs)
    assert len(result.conflicts) == 1  # exactly the resolved one
    assert result.stats.deps_eligible == 1
    assert result.stats.deps_chocked == 3


def test_eligible_deps_helper_is_the_law() -> None:
    edges = [
        DependencyEdge(
            path="b.py", name="x", kind="call",
            span=Span(1, 0, 1, 5),
            status="resolved", target_id="m::f",
        )
    ]
    assert [e.target_id for e in eligible_deps(edges)] == ["m::f"]


def test_rules_defensively_reject_unresolved_even_if_handled_one() -> None:
    """Belt-and-suspenders: calling rules DIRECTLY with an unresolved edge returns
    None even though evaluate.py would never hand them one."""
    from semlock.engine.changeset import diff_graphs
    from semlock.engine.rules.base import RuleContext
    from semlock.graph import build_claim_graph

    base_g = build_claim_graph(
        (_base_files(),)
    )
    head_g = build_claim_graph((_changed_provider_files(),))
    change = next(
        c for c in diff_graphs(base_g, head_g) if c.kind == "signature_changed"
    )
    unresolved = DependencyEdge(
        path="b.py", name="greet", kind="call",
        span=Span(4, 0, 4, 9),
        status="unresolved", target_id=None,
    )
    ctx = RuleContext(
        provider_side="A",
        consumer_side="B",
        base_graph=base_g,
        provider_graph=head_g,
        consumer_graph=base_g,
    )
    for rule in REGISTRY:
        assert rule.evaluate(change, unresolved, ctx) is None
