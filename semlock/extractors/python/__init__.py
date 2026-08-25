"""Python extractor + resolver (S2-owned). Registers both on import so
``semlock.extractors.registry.get("python")`` works once this package is loaded.
"""

from __future__ import annotations

from semlock.extractors.python.extractor import PythonExtractor
from semlock.extractors.python.resolver import (
    PythonResolver,
    ResolutionCoverage,
    resolution_coverage,
)
from semlock.extractors.registry import register

register("python", PythonExtractor, PythonResolver)

__all__ = [
    "PythonExtractor",
    "PythonResolver",
    "ResolutionCoverage",
    "resolution_coverage",
]
