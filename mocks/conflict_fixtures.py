"""Expected-conflict fixtures: what a CORRECT engine (S4) must emit per scenario.

Ground truth for the mock corpus. Every conflict class has one positive case here AND
the clean_merge scenario enforces the true-negative side (Constitution §7.2).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExpectedConflict:
    conflict_class: str
    changed_symbol_id: str  # A-side symbol whose consumed surface changed
    consumer_ref_name: str  # B-side ref name depending on the old surface
    note: str = ""


# Scenario name -> expected conflicts (order-insensitive).
EXPECTED_CONFLICTS: dict[str, tuple[ExpectedConflict, ...]] = {
    "signature_changed_param_renamed": (
        ExpectedConflict(
            conflict_class="signature_changed",
            changed_symbol_id="pkg.models.User.greet",
            consumer_ref_name="greet",
            note="param 'name' renamed to 'greeting'; B calls greet(name=...)",
        ),
    ),
    "removed_export_function_deleted": (
        ExpectedConflict(
            conflict_class="removed_export",
            changed_symbol_id="pkg.models.format_greeting",
            consumer_ref_name="format_greeting",
            note="export deleted; B imports and calls it",
        ),
    ),
    "field_removed_email": (
        ExpectedConflict(
            conflict_class="field_removed",
            changed_symbol_id="pkg.models.User.email",
            consumer_ref_name="email",
            note="member removed; B reads user.email (provisional convention)",
        ),
    ),
    "return_changed_greet_type": (
        ExpectedConflict(
            conflict_class="return_changed",
            changed_symbol_id="pkg.models.User.greet",
            consumer_ref_name="greet",
            note="declared return str -> GreetingResult; B consumes result as str",
        ),
    ),
    # True negative: clean merge must produce NOTHING.
    "clean_merge_new_method": (),
}

CONFLICT_CLASSES: tuple[str, ...] = (
    "signature_changed",
    "removed_export",
    "field_removed",
    "return_changed",
)


def expected_for(scenario_name: str) -> tuple[ExpectedConflict, ...]:
    try:
        return EXPECTED_CONFLICTS[scenario_name]
    except KeyError:
        known = ", ".join(sorted(EXPECTED_CONFLICTS))
        raise KeyError(
            f"no expectations registered for {scenario_name!r} (known: {known})"
        ) from None
