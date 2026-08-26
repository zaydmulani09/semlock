"""Mock pipeline: fixture-driven stand-in for extract->resolve->engine (today only).

While S2/S3/S4 stages have not landed, `--inject-fixtures SCENARIO` lets the CLI
run its REAL git plumbing (ref resolution, merge-base, changed-file listing)
and then produce findings from S1's ground-truth expectations over the mock
changesets (mocks/changeset_fixtures.py + conflict_fixtures.py).

This is explicitly a TEST harness for S5's own layers. It never claims to have
analyzed the repository's sources; help text and docs say so. The moment the
real engine exposes its API, this module gets deleted.
"""
from __future__ import annotations

from mocks import changeset_fixtures as cs
from mocks.changeset_fixtures import ChangesetScenario
from semlock.output.findings import Finding, findings_from_scenario


def load_scenario(name: str) -> ChangesetScenario:
    """Look up a named mock scenario; KeyError propagates to the CLI mapping."""
    return cs.get_scenario(name)


def scenario_findings(scenario: ChangesetScenario) -> tuple[Finding, ...]:
    """Enriched findings for a scenario (evidence lookup, never conflict logic)."""
    return findings_from_scenario(scenario, scenario.side_a, scenario.side_b)
