"""TypeScript Extractor + Resolver (S3-owned). Importing registers the pair."""
from __future__ import annotations

from semlock.extractors.base import Extractor, Resolver
from semlock.extractors.registry import register
from semlock.extractors.typescript.extractor import TypeScriptExtractor
from semlock.extractors.typescript.resolver import (
    TypeScriptResolver,
    measure_resolution,
)

__all__ = [
    "TypeScriptExtractor",
    "TypeScriptResolver",
    "measure_resolution",
]

register("typescript", TypeScriptExtractor, TypeScriptResolver)


def _registration_check() -> tuple[type[Extractor], type[Resolver]]:
    from semlock.extractors.registry import get

    return get("typescript")
