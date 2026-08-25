"""S1-owned: mock validity — the unblock gate for S2-S6. Mocks must be internally
consistent, schema-valid, and honor the seam rules (INV-2 direction checks included).
"""
from __future__ import annotations

import pytest

from mocks import changeset_fixtures as cs
from mocks import conflict_fixtures as cf
from mocks import ir_fixtures as fx
from semlock.extractors.base import assert_unresolved
from semlock.ir import serialize


def test_scenario_names_are_unique() -> None:
    names = [s.name for s in cs.all_scenarios()]
    assert len(names) == len(set(names))


def test_every_scenario_is_schema_valid() -> None:
    for scenario in cs.all_scenarios():
        for facts in (*scenario.side_a, *scenario.side_b):
            assert serialize.to_json(facts)


def test_every_scenario_declares_a_known_class_or_clean() -> None:
    for scenario in cs.all_scenarios():
        assert (
            scenario.expected_class is None
            or scenario.expected_class in cf.CONFLICT_CLASSES
        )


def test_every_conflict_class_has_positive_and_negative_case() -> None:
    declared = {s.expected_class for s in cs.all_scenarios()}
    for klass in cf.CONFLICT_CLASSES:
        assert klass in declared, f"no positive scenario for {klass}"
        negatives = [s for s in cs.all_scenarios() if s.expected_class is None]
        assert negatives, "no true-negative (clean merge) scenario"


def test_expectations_cover_all_scenarios() -> None:
    for scenario in cs.all_scenarios():
        expected = cf.expected_for(scenario.name)
        if scenario.expected_class is None:
            assert expected == (), f"{scenario.name} must expect no conflicts"
        else:
            assert expected, f"{scenario.name} must expect >=1 conflict"
            for exp in expected:
                assert exp.conflict_class == scenario.expected_class


def test_side_b_refs_are_resolved_not_unresolved() -> None:
    """Mocks are post-Resolver artifacts: B-side dependency edges MUST carry
    'resolved' status so INV-2 negative tests are meaningful."""
    for scenario in cs.all_scenarios():
        for facts in scenario.side_b:
            statuses = {ref.resolution.status for ref in facts.refs}
            assert statuses == {"resolved"}, f"{scenario.name}/{facts.path}: {statuses}"


def test_assert_unresolved_flags_resolved_mocks() -> None:
    with pytest.raises(AssertionError):
        assert_unresolved(fx.app_consumer())


def test_assert_unresolved_passes_on_fresh_facts() -> None:
    from semlock.ir.model import FileFacts, Ref, Span
    from semlock.ir.version import FORMAT_VERSION

    fresh = FileFacts(
        format_version=FORMAT_VERSION,
        path="a.py",
        language="python",
        ref="main",
        refs=(Ref(name="f", kind="call", span=Span(1, 0, 1, 1)),),
    )
    assert_unresolved(fresh)  # must not raise


def test_registry_rejects_conflicting_language_declaration() -> None:
    from semlock.extractors import registry
    from semlock.extractors.base import Extractor, Resolver

    class WrongExtractor(Extractor):
        language = "typescript"

        def extract_file(self, path, ref, source):  # type: ignore[no-untyped-def]
            raise NotImplementedError

    class PyResolver(Resolver):
        language = "python"

        def resolve(self, files):  # type: ignore[no-untyped-def]
            return files

    with pytest.raises(ValueError):
        registry.register("python", WrongExtractor, PyResolver)
