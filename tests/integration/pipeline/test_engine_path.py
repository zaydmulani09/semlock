"""S5 integration tests: the REAL engine path (facts -> changeset -> evaluate ->
Finding adaptation -> text/JSON rendering).

Uses mock RESOLVED FileFacts (post-Resolver artifacts, S1-authored) because
extractors have not landed; everything downstream of resolution here is the
real committed engine. Skips cleanly if semlock.engine is ever absent.
"""
from __future__ import annotations

import importlib.util

import pytest

from mocks import changeset_fixtures as cs
from mocks import ir_fixtures as fx
from semlock.output import findings as findings_mod
from semlock.output import json_out, text
from semlock.output.findings import Finding

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("semlock.engine") is None,
    reason="semlock.engine not landed",
)

CONFLICT_SCENARIOS = (
    "signature_changed_param_renamed",
    "removed_export_function_deleted",
    "field_removed_email",
    "return_changed_greet_type",
)


def _engine_triple(scenario_name):
    scenario = cs.get_scenario(scenario_name)
    engine = pytest.importorskip("semlock.engine")
    base = (fx.models_main(ref="merge-base"),)
    changeset = engine.build_changeset(base, scenario.side_a, scenario.side_b)
    return scenario, engine.evaluate(changeset)


@pytest.mark.parametrize("name", CONFLICT_SCENARIOS)
def test_engine_conflict_flows_through_s5_model(name) -> None:
    scenario, result = _engine_triple(name)

    classes = {c.conflict_class for c in result.conflicts}
    assert classes == {scenario.expected_class}
    assert all(c.changed_side in ("A", "B") for c in result.conflicts)

    adapted = [findings_mod.from_engine(c) for c in result.conflicts]
    assert all(isinstance(f, Finding) for f in adapted)
    # Dual-sided evidence always present on both views (INV-9 shape).
    for f in adapted:
        assert f.evidence_a.path is not None
        assert f.evidence_b.path is not None
        assert {f.evidence_a.role, f.evidence_b.role} == {
            findings_mod.ROLE_CHANGED,
            findings_mod.ROLE_CONSUMER,
        }


def test_engine_finding_dict_matches_published_key_order() -> None:
    _scenario, result = _engine_triple("signature_changed_param_renamed")
    conflict = result.conflicts[0]

    mine = findings_mod.from_engine(conflict).to_dict()
    theirs = pytest.importorskip("semlock.engine.evidence").conflict_to_dict(conflict)

    assert list(mine) == list(theirs)
    assert mine == theirs  # adapter must be a faithful dumb printer


def test_clean_scenario_yields_zero_findings_end_to_end() -> None:
    _scenario, result = _engine_triple("clean_merge_new_method")

    assert result.conflicts == ()
    findings = tuple(findings_mod.from_engine(c) for c in result.conflicts)
    out = text.render_text("a", "b", "deadbeef", findings)
    assert "no cross-branch semantic conflicts" in out


def test_text_rendering_is_deterministic_with_dual_evidence() -> None:
    _scenario, result = _engine_triple("signature_changed_param_renamed")
    findings = tuple(findings_mod.from_engine(c) for c in result.conflicts)

    first = text.render_text("feat/a", "feat/b", "abc123def456", findings)
    second = text.render_text("feat/a", "feat/b", "abc123def456", findings)
    assert first == second
    assert "[signature_changed]" in first
    assert "A pkg/models.py:" in first or "B pkg/models.py:" in first
    assert "pkg/app.py:" in first


def test_json_report_embeds_engine_stats_verbatim() -> None:
    _scenario, result = _engine_triple("signature_changed_param_renamed")
    findings = tuple(findings_mod.from_engine(c) for c in result.conflicts)

    report = json_out.report_dict(
        ref_a="feat/a",
        ref_b="feat/b",
        merge_base_sha="abc123",
        files_changed_a=1,
        files_changed_b=2,
        findings=findings,
        engine_stats=result.to_dict()["stats"],
    )
    payload = json_out.to_json(report)
    assert '"engine_stats"' in payload
    assert report["conflict_count"] == len(report["findings"]) >= 1
