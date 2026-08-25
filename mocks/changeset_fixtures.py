"""Changeset fixtures: pairs of fully-resolved fact sets representing two concurrent
branches (side A mutates a surface; side B consumes it). S4/S6 build test scenarios on
these; every conflict scenario has a matching entry in mocks/conflict_fixtures.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from mocks import ir_fixtures as fx
from semlock.ir.model import FileFacts


@dataclass(frozen=True, slots=True)
class ChangesetScenario:
    name: str
    expected_class: str | None  # None => clean merge, no findings allowed
    description: str
    side_a: tuple[FileFacts, ...]
    side_b: tuple[FileFacts, ...]


def _b_side() -> tuple[FileFacts, ...]:
    # B's side carries its own unchanged copy of models.py so imports resolve there.
    return (
        fx.app_consumer(ref=fx.SIDE_B),
        fx.models_main(ref=fx.SIDE_B),
    )


def all_scenarios() -> tuple[ChangesetScenario, ...]:
    return (
        ChangesetScenario(
            name="signature_changed_param_renamed",
            expected_class="signature_changed",
            description="A renames greet param name->greeting; B calls greet(name=).",
            side_a=(fx.models_signature_changed(),),
            side_b=_b_side(),
        ),
        ChangesetScenario(
            name="removed_export_function_deleted",
            expected_class="removed_export",
            description="A deletes exported format_greeting; B still imports/calls it.",
            side_a=(fx.models_export_removed(),),
            side_b=_b_side(),
        ),
        ChangesetScenario(
            name="field_removed_email",
            expected_class="field_removed",
            description="A removes User.email member; B reads user.email.",
            side_a=(fx.models_field_removed(),),
            side_b=_b_side(),
        ),
        ChangesetScenario(
            name="return_changed_greet_type",
            expected_class="return_changed",
            description="A changes greet return to GreetingResult; B consumes result.",
            side_a=(fx.models_return_changed(),),
            side_b=_b_side(),
        ),
        ChangesetScenario(
            name="clean_merge_new_method",
            expected_class=None,
            description="A adds User.shout; old surface untouched. No findings.",
            side_a=(fx.models_new_method_added(),),
            side_b=_b_side(),
        ),
    )


def get_scenario(name: str) -> ChangesetScenario:
    for scenario in all_scenarios():
        if scenario.name == name:
            return scenario
    known = ", ".join(s.name for s in all_scenarios())
    raise KeyError(f"unknown scenario {name!r} (known: {known})")
