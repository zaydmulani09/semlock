"""Integration: extractor-shaped resolved fixtures -> graph -> changeset -> engine.

Runs S1's ground-truth mock corpus (mocks/changeset_fixtures.py) through the REAL
pipeline and grades it against mocks/conflict_fixtures.py expectations:

  - every expected (class, changed_symbol_id, consumer_ref_name) triple must appear,
  - no conflict of an unexpected class may appear,
  - the clean-merge scenario must produce ZERO findings.

Expected triples are matched as a SET: one expected break may manifest at several
use-sites (e.g. B's own caller plus B's unchanged copy of models.py), and each site
gets its own Conflict with its own dual-sided evidence.
"""
from __future__ import annotations

import pytest

from mocks import ir_fixtures as fx
from mocks.changeset_fixtures import all_scenarios
from mocks.conflict_fixtures import CONFLICT_CLASSES, expected_for
from semlock.engine import build_changeset, evaluate

BASE_FILES = (fx.models_main(ref=fx.MAIN),)


def _triples(conflicts):
    return {
        (c.conflict_class, c.changed_symbol_id, c.consumer_ref_name)
        for c in conflicts
    }


@pytest.mark.parametrize("scenario", all_scenarios(), ids=lambda s: s.name)
def test_scenario_ground_truth(scenario) -> None:
    cs = build_changeset(BASE_FILES, scenario.side_a, scenario.side_b)
    result = evaluate(cs)
    expected = expected_for(scenario.name)

    if not expected:
        assert result.conflicts == (), (
            f"{scenario.name}: clean merge must produce ZERO findings, got "
            f"{_triples(result.conflicts)}"
        )
        return

    produced = _triples(result.conflicts)
    wanted = {
        (e.conflict_class, e.changed_symbol_id, e.consumer_ref_name)
        for e in expected
    }
    missing = wanted - produced
    assert not missing, f"{scenario.name}: engine missed {missing}"
    unexpected_classes = {c for c, _, _ in produced} - {
        e.conflict_class for e in expected
    }
    assert not unexpected_classes, (
        f"{scenario.name}: engine invented classes {unexpected_classes}"
    )
    assert all(c.conflict_class in CONFLICT_CLASSES for c in result.conflicts)


@pytest.mark.parametrize("scenario", all_scenarios(), ids=lambda s: s.name)
def test_every_conflict_carries_dual_sided_evidence(scenario) -> None:
    """INV-9: never a bare 'semantic conflict detected'."""
    cs = build_changeset(BASE_FILES, scenario.side_a, scenario.side_b)
    for c in evaluate(cs).conflicts:
        assert c.rule and c.conflict_class
        assert c.evidence_a.path and c.evidence_a.line >= 1
        assert c.evidence_b.path and c.evidence_b.line >= 1
        assert c.evidence_a.role != c.evidence_b.role
        provider = (
            c.evidence_a if c.changed_side == "A" else c.evidence_b
        )
        consumer = (
            c.evidence_b if c.changed_side == "A" else c.evidence_a
        )
        assert provider.role == "changed_definition"
        assert consumer.role == "consuming_use"
        # Explanation names both symbols and both locations.
        assert c.changed_symbol_id in c.explanation
        assert f"{c.consumer_path}:{c.consumer_span.start_line}" in c.explanation
        assert c.rule in c.explanation


def test_mock_corpus_stats_fully_resolved() -> None:
    """The mock corpus is post-resolver: coverage must be 100% here."""
    for scenario in all_scenarios():
        cs = build_changeset(BASE_FILES, scenario.side_a, scenario.side_b)
        result = evaluate(cs)
        total = len(cs.a_graph.dep_edges) + len(cs.b_graph.dep_edges)
        assert result.stats.deps_total == total
        assert result.stats.deps_eligible == total  # nothing chocked in mocks
