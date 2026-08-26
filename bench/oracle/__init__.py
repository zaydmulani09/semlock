"""Independent type-checker oracles (ADR-0009).

An Oracle arbitrates ground truth for one predicted cross-branch break against the
MERGED state, using an external static checker (mypy / tsc). SEMLock output is never
used as evidence. See docs/adr/0009-independent-oracle.md.
"""
from bench.oracle.base import (
    CaseContext,
    Oracle,
    OracleResult,
    Prediction,
    SiteError,
    Verdict,
)

__all__ = [
    "CaseContext",
    "Oracle",
    "OracleResult",
    "Prediction",
    "SiteError",
    "Verdict",
]
