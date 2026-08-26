"""Declarative rule registry (ADR-0004 intent).

One module per rule; each module exposes a module-level `RULE` instance. REGISTRY
below is the single fixed-order tuple evaluate.py iterates -- adding a rule is one
new module plus one registry line, nothing else. Order is part of determinism.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from semlock.engine.rules.base import Rule, RuleContext
from semlock.engine.rules.field_removed import RULE as FIELD_REMOVED
from semlock.engine.rules.removed_or_renamed_export import (
    RULE as REMOVED_OR_RENAMED_EXPORT,
)
from semlock.engine.rules.return_changed import RULE as RETURN_CHANGED
from semlock.engine.rules.signature_changed import RULE as SIGNATURE_CHANGED

REGISTRY: Final[Sequence[Rule]] = (
    SIGNATURE_CHANGED,
    REMOVED_OR_RENAMED_EXPORT,
    FIELD_REMOVED,
    RETURN_CHANGED,
)

__all__ = ["REGISTRY", "Rule", "RuleContext"]
