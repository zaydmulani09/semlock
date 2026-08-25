"""Module-path computation for TypeScript symbol ids (S3-owned).

Canonical grammar (briefing, fixed): ``<module_path>::<Qualified.Name>`` where
``module_path`` is the repo-relative path with the extension stripped and
``index.ts`` collapsed to its directory. Path aliases are resolved BEFORE this
computation runs on import specifiers (resolver side); a file's own module path
never involves aliases.
"""
from __future__ import annotations

from typing import Final

TS_EXTENSIONS: Final = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")

INDEX_STEMS: Final = ("index",)


def module_path_of(path: str) -> str:
    """`src/models/user.ts` -> `src/models/user`; `index.ts` collapses to dir."""
    normalized = path.replace("\\", "/")
    for ext in sorted(TS_EXTENSIONS, key=len, reverse=True):
        if normalized.endswith(ext):
            normalized = normalized[: -len(ext)]
            break
    stem = normalized.rsplit("/", 1)[-1]
    if stem in INDEX_STEMS:
        parent = normalized.rsplit("/", 1)[0]
        return parent if "/" in normalized or parent else normalized
    return normalized


def resolve_relative(specifier: str, from_module_path: str) -> str | None:
    """Resolve `./x`, `../x`, `../../x` against the importing file's module path.

    Returns None when the specifier is not relative.
    """
    if not specifier.startswith("."):
        return None
    base_parts = from_module_path.split("/")[:-1] if "/" in from_module_path else []
    if not base_parts and from_module_path:
        base_parts = []
    parts = list(base_parts)
    segment = specifier
    while segment.startswith("./") or segment == ".":
        segment = segment[2:] if segment.startswith("./") else ""
    while True:
        if segment.startswith("../"):
            if parts:
                parts.pop()
            segment = segment[3:]
        elif segment.startswith("./"):
            segment = segment[2:]
        else:
            break
    for piece in segment.split("/"):
        if piece and piece != ".":
            parts.append(piece)
    target = "/".join(parts) if parts else segment
    return strip_extension_and_collapse(target)


def strip_extension_and_collapse(module_like: str) -> str:
    for ext in sorted(TS_EXTENSIONS, key=len, reverse=True):
        if module_like.endswith(ext):
            module_like = module_like[: -len(ext)]
            break
    head, _, tail = module_like.rpartition("/")
    if tail in INDEX_STEMS:
        return head if head else module_like
    return module_like


def is_relative(specifier: str) -> bool:
    return specifier.startswith(".")


def looks_aliased(specifier: str) -> bool:
    """True for non-relative, non-node_modules bare specifiers (`@/lib/helper`)."""
    return not is_relative(specifier) and not specifier.startswith("@types/")
