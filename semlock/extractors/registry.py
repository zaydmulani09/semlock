"""Language -> (Extractor, Resolver) registry. S1 owns the seam; S2/S3 register."""
from __future__ import annotations

import contextlib
import importlib

from semlock.extractors.base import Extractor, Resolver

_REGISTRY: dict[str, tuple[type[Extractor], type[Resolver]]] = {}

# Language implementation packages that self-register on import (each calls
# register() in its __init__.py). Nothing else in the codebase imports them,
# so callers going through get()/languages() must trigger that import first;
# _bootstrap() does so lazily, once, tolerating packages not landed yet.
_LANGUAGE_PACKAGES = ("semlock.extractors.python", "semlock.extractors.typescript")
_bootstrapped = False


def _bootstrap() -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    for module_name in _LANGUAGE_PACKAGES:
        with contextlib.suppress(ImportError):
            importlib.import_module(module_name)


def register(
    language: str,
    extractor: type[Extractor],
    resolver: type[Resolver],
) -> None:
    if language in _REGISTRY:
        raise ValueError(f"language {language!r} already registered")
    for cls in (extractor, resolver):
        declared = getattr(cls, "language", None)
        if declared is not None and declared != language:
            raise ValueError(
                f"{cls.__name__}.language={declared!r} contradicts registration "
                f"as {language!r}"
            )
    _REGISTRY[language] = (extractor, resolver)


def get(language: str) -> tuple[type[Extractor], type[Resolver]]:
    _bootstrap()
    try:
        return _REGISTRY[language]
    except KeyError:
        known = ", ".join(languages()) or "<none>"
        raise KeyError(
            f"no Extractor/Resolver registered for {language!r} (known: {known})"
        ) from None


def languages() -> tuple[str, ...]:
    _bootstrap()
    return tuple(sorted(_REGISTRY))
