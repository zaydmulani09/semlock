"""Canonical Python module-path computation (SEMANTIC_INVARIANTS module-path scheme).

A repo-relative POSIX path maps to a dotted module path WITHOUT consulting the
filesystem: every directory component is treated as a (namespace) package and a
file named ``__init__.py`` denotes its parent directory as the module. Extraction
therefore stays a pure function of (path, source) — INV-1/INV-7.

Shared by the Python extractor and resolver so both derive IDENTICAL module paths
and package contexts from the same ``FileFacts.path``.
"""

from __future__ import annotations


def module_info(path: str) -> tuple[str, bool]:
    """Map a repo-relative ``.py`` path to ``(module_path, is_package)``.

    ``pkg/models.py``    -> ``("pkg.models", False)``
    ``pkg/__init__.py``  -> ``("pkg", True)``
    """
    rel = path[:-3] if path.endswith(".py") else path
    parts = [p for p in rel.split("/") if p]
    is_package = bool(parts) and parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def package_of(module_path: str, is_package: bool) -> str:
    """The package context used to resolve relative imports.

    A package's own ``__init__.py`` lives IN its package; a plain module's
    package is its parent.
    """
    if is_package:
        return module_path
    if "." in module_path:
        return module_path.rsplit(".", 1)[0]
    return ""


def split_relative(origin_written: str) -> tuple[int, str]:
    """Split a written import origin into ``(level, remainder)``.

    ``".rel.mod"`` -> ``(1, "rel.mod")``; ``"..up.pkg"`` -> ``(2, "up.pkg")``;
    ``"pkg.mod"`` -> ``(0, "pkg.mod")``.
    """
    level = len(origin_written) - len(origin_written.lstrip("."))
    return level, origin_written[level:]


def absolutize(
    origin_written: str, importer_module: str, importer_is_package: bool
) -> str:
    """Resolve a written import origin (absolute or relative) against the importing
    module, producing the absolute dotted module path it refers to."""
    level, remainder = split_relative(origin_written)
    if level == 0:
        return remainder
    base = package_of(importer_module, importer_is_package)
    for _ in range(level - 1):
        if "." not in base:
            base = ""
            break
        base = base.rsplit(".", 1)[0]
    if not base:
        return remainder
    return f"{base}.{remainder}" if remainder else base
