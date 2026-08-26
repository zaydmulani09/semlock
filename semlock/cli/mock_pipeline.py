"""Mock pipeline: fixture-driven stand-in for extract->resolve->engine (today only).

While S2/S3/S4 stages have not landed, `--inject-fixtures SCENARIO` lets the CLI
run its REAL git plumbing (ref resolution, merge-base, changed-file listing)
and then produce findings from S1's ground-truth expectations over the mock
changesets (mocks/changeset_fixtures.py + conflict_fixtures.py).

This is explicitly a TEST harness for S5's own layers. It never claims to have
analyzed the repository's sources; help text and docs say so. It imports
mocks/, which ships only in repository checkouts — so semlock.cli.main imports
this module lazily and an installed console script never touches it unless the
user passes --inject-fixtures. The moment the real engine exposes its full
flow, this module gets deleted.
"""
from __future__ import annotations

from mocks import changeset_fixtures as cs
from mocks import conflict_fixtures as cf
from mocks.changeset_fixtures import ChangesetScenario
from semlock.ir.model import FileFacts, Ref
from semlock.output.findings import (
    ROLE_CHANGED,
    ROLE_CONSUMER,
    Finding,
    SideEvidence,
    locate_consumer,
    locate_symbol,
)


def load_scenario(name: str) -> ChangesetScenario:
    """Look up a named mock scenario; KeyError propagates to the CLI mapping."""
    return cs.get_scenario(name)


def _ref_sort_key(ref: Ref) -> tuple[int, int, str]:
    return (ref.span.start_line, ref.span.start_col, ref.name)


def findings_from_scenario(
    scenario: ChangesetScenario,
    side_a: tuple[FileFacts, ...],
    side_b: tuple[FileFacts, ...],
) -> tuple[Finding, ...]:
    """Ground-truth expectations + fixture facts -> enriched Findings.

    The scenario's EXPECTED_CONFLICTS are S1-authored ground truth for what a
    correct engine emits; this function adds file:line evidence by looking ids
    and ref names up in the corresponding resolved fact sets. Fixtures describe
    the canonical orientation (A mutates a surface; B consumes it).
    """
    expected = cf.expected_for(scenario.name)
    findings: list[Finding] = []
    for exp in expected:
        changed_hit = locate_symbol(side_a, exp.changed_symbol_id)
        consumer_hit = locate_consumer(side_b, exp.consumer_ref_name)

        consumer_path = consumer_hit[0] if consumer_hit else None
        consumer_ref = consumer_hit[1] if consumer_hit else None
        changed_path = changed_hit[0] if changed_hit else None
        changed_line = changed_hit[1].span.start_line if changed_hit else None
        changed_col = changed_hit[1].span.start_col if changed_hit else None

        findings.append(
            Finding(
                rule=exp.conflict_class,  # fixture granularity: rule == class
                conflict_class=exp.conflict_class,
                changed_symbol_id=exp.changed_symbol_id,
                changed_side="A",
                consumer_ref_name=exp.consumer_ref_name,
                consumer_ref_kind=consumer_ref.kind if consumer_ref else "?",
                consumer_path=consumer_path,
                consumer_span=consumer_ref.span if consumer_ref else None,
                consumer_side="B",
                target_id=exp.changed_symbol_id,
                explanation=exp.note,
                evidence_a=SideEvidence(
                    path=changed_path,
                    line=changed_line,
                    col=changed_col,
                    role=ROLE_CHANGED,
                ),
                evidence_b=SideEvidence(
                    path=consumer_path,
                    line=consumer_ref.span.start_line if consumer_ref else None,
                    col=consumer_ref.span.start_col if consumer_ref else None,
                    role=ROLE_CONSUMER,
                ),
            )
        )
    return tuple(sorted(findings, key=Finding.sort_key))


def scenario_findings(scenario: ChangesetScenario) -> tuple[Finding, ...]:
    """Enriched findings for a scenario (evidence lookup, never conflict logic)."""
    return findings_from_scenario(scenario, scenario.side_a, scenario.side_b)
