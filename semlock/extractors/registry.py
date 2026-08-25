"""Language -> (Extractor, Resolver) registry. S1 owns the seam; S2/S3 register."""
from __future__ import annotations

from semlock.extractors.base import Extractor, Resolver

_REGISTRY: dict[str, tuple[type[Extractor], type[Resolver]]] = {}


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
    try:
        return _REGISTRY[language]
    except KeyError:
        known = ", ".join(languages()) or "<none>"
        raise KeyError(
            f"no Extractor/Resolver registered for {language!r} (known: {known})"
        ) from None


def languages() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))
