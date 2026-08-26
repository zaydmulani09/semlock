"""Oracle ABC + value types (ADR-0009).

Ground truth for a predicted break is established ONLY by an external static type
checker run over the materialized MERGED state, with per-site attribution:

* A prediction counts as a true positive only if the checker reports an error at (or
  directly involving) the SPECIFIC predicted use-site whose error category is
  compatible with the predicted conflict class.
* "The checker found some errors" never confirms SEMLock. Unrelated errors are not
  suppressed silently: they are recorded and excluded from verdicts by counterfactual
  subtraction (merged vs base-without-side-A), so pre-existing repo dirt cannot
  contaminate grading.
* When ground truth cannot be established the verdict is INCONCLUSIVE — never forced.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

CONFLICT_CLASSES: tuple[str, ...] = (
    "signature_changed",
    "removed_export",
    "field_removed",
    "return_changed",
)
RESOLUTION_STATUSES: tuple[str, ...] = (
    "unresolved",
    "resolved",
    "external",
    "ambiguous",
)


class Verdict(str, Enum):
    """Outcome of oracle arbitration for one prediction."""

    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"
    FALSE_NEGATIVE = "false_negative"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class Prediction:
    """Canonical form of one SEMLock-predicted cross-branch break.

    Produced by adapting real CLI findings (S5) or by a plumbing-only mock predictor.
    Artifacts record which predictor produced them; only runs with predictor kind
    "cli" are publishable as SEMLock numbers.
    """

    prediction_id: str
    case_id: str
    language: str  # "python" | "typescript"
    conflict_class: str  # one of CONFLICT_CLASSES
    symbol_id: str  # A-side changed surface id (IR grammar)
    ref_path: str  # B-side use-site file, repo-relative "/" separators
    ref_start_line: int  # inclusive, 1-indexed (checker reports lines)
    ref_end_line: int  # inclusive for attribution purposes
    resolution_status: str  # IR Resolution.status at prediction time
    raw: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if self.conflict_class not in CONFLICT_CLASSES:
            raise ValueError(f"bad conflict_class: {self.conflict_class!r}")
        if self.resolution_status not in RESOLUTION_STATUSES:
            raise ValueError(
                f"bad resolution_status: {self.resolution_status!r}"
            )
        if self.ref_start_line < 1 or self.ref_end_line < self.ref_start_line:
            raise ValueError(f"bad site span: {self!r}")
        if "\\" in self.ref_path:
            raise ValueError(f"ref_path must use '/' separators: {self.ref_path!r}")


@dataclass(frozen=True, slots=True)
class CaseContext:
    """Materialized states an Oracle evaluates against.

    merged_dir is mandatory. counterfactual_dir (base branch with side B merged
    but WITHOUT side A's change) enables contamination-free subtraction of
    pre-existing errors; when absent the oracle must return INCONCLUSIVE rather
    than guess. surface_paths lists the repo-relative files side A changed —
    diagnostics inside them are A-internal and never confirm a consumer break.
    """

    case_id: str
    language: str
    merged_dir: Path
    counterfactual_dir: Path | None
    surface_paths: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SiteError:
    """One checker diagnostic, normalized."""

    path: str  # repo-relative "/" separators
    line: int
    column: int
    code: str  # checker error code; "" when the tool emits none
    message: str  # whitespace-normalized

    def normalized_key(self) -> tuple[str, int, str, str]:
        return (self.path, self.line, self.code, self.message)

    def overlaps_site(self, pred: Prediction) -> bool:
        return (
            self.path == pred.ref_path
            and pred.ref_start_line <= self.line <= pred.ref_end_line
        )


@dataclass(slots=True)
class OracleResult:
    """Verdict plus full evidence for audit. Never discard unrelated errors."""

    prediction_id: str
    verdict: Verdict
    tool: str
    site_errors: tuple[SiteError, ...] = ()
    interaction_errors: tuple[SiteError, ...] = ()
    notes: tuple[str, ...] = ()


class Oracle(ABC):
    """Arbitrates predictions against merged-state static-checker evidence."""

    tool_name: str = "abstract"

    @abstractmethod
    def check_state(self, state_dir: Path) -> tuple[SiteError, ...]:
        """Run the checker over a materialized state; return all diagnostics.

        Raises CheckerUnavailable when the tool binary cannot be located/executed.
        A checker crash (non-run exit) also raises CheckerUnavailable with detail;
        callers translate that into INCONCLUSIVE, never into a verdict.
        """

    def evaluate(
        self, ctx: CaseContext, pred: Prediction
    ) -> OracleResult:
        """Verdict for one prediction via counterfactual subtraction."""
        pred.validate()
        notes: list[str] = []
        if ctx.counterfactual_dir is None:
            notes.append("no counterfactual state; ground truth not establishable")
            return OracleResult(
                pred.prediction_id, Verdict.INCONCLUSIVE, self.tool_name,
                notes=tuple(notes),
            )
        merged = self.check_state(ctx.merged_dir)
        counterfactual = self.check_state(ctx.counterfactual_dir)
        cf_keys = {e.normalized_key() for e in counterfactual}
        interaction = tuple(
            e for e in merged if e.normalized_key() not in cf_keys
        )
        if not interaction:
            notes.append("no interaction-attributable errors in merged state")
            return OracleResult(
                pred.prediction_id, Verdict.FALSE_POSITIVE, self.tool_name,
                site_errors=(), interaction_errors=(), notes=tuple(notes),
            )
        site_errors = tuple(e for e in interaction if e.overlaps_site(pred))
        chain_errors = tuple(
            e
            for e in interaction
            if not e.overlaps_site(pred) and self.on_causal_chain(e, pred)
        )
        confirming = tuple(
            e
            for e in (*site_errors, *chain_errors)
            if self.error_matches_class(e, pred.conflict_class)
        )
        if confirming:
            notes = [
                f"confirmed via {'site' if site_errors else 'causal-chain'} errors"
            ] + notes
            return OracleResult(
                pred.prediction_id, Verdict.TRUE_POSITIVE, self.tool_name,
                site_errors=site_errors or chain_errors,
                interaction_errors=interaction,
                notes=tuple(notes),
            )
        if site_errors:
            codes = ", ".join(sorted({e.code or "?" for e in site_errors}))
            notes.append(
                f"errors at predicted site but category incompatible with "
                f"{pred.conflict_class}: [{codes}]"
            )
            return OracleResult(
                pred.prediction_id, Verdict.INCONCLUSIVE, self.tool_name,
                site_errors=site_errors, interaction_errors=interaction,
                notes=tuple(notes),
            )
        return OracleResult(
            pred.prediction_id, Verdict.FALSE_POSITIVE, self.tool_name,
            interaction_errors=interaction, notes=tuple(notes),
        )

    @abstractmethod
    def error_matches_class(self, error: SiteError, conflict_class: str) -> bool:
        """Is this diagnostic the kind this conflict class would plant?"""

    def on_causal_chain(
        self, ctx: CaseContext, error: SiteError, pred: Prediction
    ) -> bool:
        """Does this off-site diagnostic still evidence THIS relationship?

        Checkers localize some breaks to an intermediate re-export/shim line
        rather than the consumer's use-site. An interaction error counts as on
        the causal chain only when (a) its message names the specific symbol
        whose surface changed (name-tethered, not "any error") and (b) it is
        not inside side A's own changed files (A-internal noise).
        """
        short_name = pred.symbol_id.rsplit(".", 1)[-1]
        return (
            error.path not in ctx.surface_paths
            and short_name in error.message
        )

    def scan_breaks(self, ctx: CaseContext) -> tuple[SiteError, ...]:
        """Interaction-attributed diagnostics independent of any prediction.

        Candidates for FALSE_NEGATIVE labeling: breaks the checker sees that SEMLock
        failed to predict. Empty when no counterfactual exists (never guessed).
        """
        if ctx.counterfactual_dir is None:
            return ()
        merged = self.check_state(ctx.merged_dir)
        cf_keys = {
            e.normalized_key() for e in self.check_state(ctx.counterfactual_dir)
        }
        return tuple(e for e in merged if e.normalized_key() not in cf_keys)


class CheckerUnavailable(RuntimeError):
    """Checker binary missing or crashed; callers must yield INCONCLUSIVE."""
