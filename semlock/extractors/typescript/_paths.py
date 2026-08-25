"""Module-path computation for TypeScript symbol ids (S3-owned).

Canonical grammar (ADR-0008, ratified at IR 0.2.0): ``<module_path>::<Qualified.Name>``
where ``module_path`` is the repo-relative path with the extension stripped and
``index.ts`` collapsed to its directory. Import specifiers are resolved to
module paths by the RESOLVER (relative anchors on the importing FILE's
directory; tsconfig-style aliases via ``TypeScriptResolver(path_aliases=...)``).
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
