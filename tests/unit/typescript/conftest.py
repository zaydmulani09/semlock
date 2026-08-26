"""Shared helpers for TS extractor/resolver tests (S3-owned)."""
from __future__ import annotations

from pathlib import Path

from semlock.extractors.typescript import (
    TypeScriptExtractor,
    TypeScriptResolver,
    measure_resolution,
)
from semlock.ir.model import FileFacts, Symbol

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "typescript"

_EXTRACTOR = TypeScriptExtractor()
_RESOLVER = TypeScriptResolver()


def extract_side(side_dir: Path) -> tuple[FileFacts, ...]:
    """Extract every .ts under `side_dir`, treating it as the repo root.

    Unit-fixture convention: the scenario tree simulates a repository, so
    FileFacts.path is relative to the side directory (e.g. src/models/user.ts).
    """
    files: list[FileFacts] = []
    for source_file in sorted(side_dir.rglob("*.ts")):
        rel = source_file.relative_to(side_dir).as_posix()
        source = source_file.read_text("utf-8")
        files.append(_EXTRACTOR.extract_file(rel, "test", source))
    return tuple(files)


def resolve_fixture(scenario: str, side: str) -> tuple[FileFacts, ...]:
    return _RESOLVER.resolve(extract_side(FIXTURES / scenario / side))


def symbol_map(files: tuple[FileFacts, ...]) -> dict[str, Symbol]:
    return {s.id: s for f in files for s in f.symbols}


def ref_targets(
    files: tuple[FileFacts, ...], kind: str | None = None
) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for facts in files:
        for ref in facts.refs:
            if kind is None or ref.kind == kind:
                out.append((ref.name, ref.resolution.status))
    return out


__all__ = [
    "FIXTURES",
    "TypeScriptExtractor",
    "TypeScriptResolver",
    "extract_side",
    "measure_resolution",
    "ref_targets",
    "resolve_fixture",
    "symbol_map",
]
