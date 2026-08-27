"""Per-side fact collection via temporary worktrees (ADR-0006).

For `semlock check REFA REFB` each side is compared against the merge-base:
`collect_side(repo, ref, base)` checks out exactly one commit into a detached
temporary worktree (`git worktree add --detach`), reads only the files that
side changed relative to the base, and dispatches them through the language
registry (Extractor -> Resolver) to produce RESOLVED FileFacts.

Seam rules honored here:
- This module never fabricates facts: extraction/resolution come exclusively
  from the registry (S2/S3 implementations). When a language has no registered
  Extractor/Resolver, PipelineUnavailableError names the missing stage.
- INV-6: FileFacts whose format_version differs from FORMAT_VERSION are
  refused, never guessed around.
- INV-2: extractors emit unresolved refs; the ref-wide Resolver upgrades them.
  This module only sequences the stages and never touches resolutions.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from semlock.extractors import registry
from semlock.extractors.base import Extractor, Resolver
from semlock.git import refs
from semlock.ir.model import FileFacts
from semlock.ir.version import FORMAT_VERSION

EXTENSION_LANGUAGE: Final[dict[str, str]] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
}


class PipelineUnavailableError(RuntimeError):
    """A downstream stage (extractor/resolver/engine) is not available yet."""


def language_for_path(
    path: str, languages: tuple[str, ...] | None = None
) -> str | None:
    """Map a repo-relative path to its SEMLock language, or None if unsupported.

    `languages` optionally restricts the accepted set (config hook; None = all).
    """
    dot = path.rfind(".")
    if dot < 0:
        return None
    lang = EXTENSION_LANGUAGE.get(path[dot:].lower())
    if lang is None:
        return None
    if languages is not None and lang not in languages:
        return None
    return lang


@contextlib.contextmanager
def worktree_at(repo: Path, sha: str) -> Iterator[Path]:
    """Yield the path of a detached temporary worktree pinned at `sha`.

    The worktree lives outside the user's tree (temp dir) and is removed on
    exit; removal failures fall back to `worktree prune` plus a best-effort
    rmtree so repeated runs never accumulate worktrees. Read-only with respect
    to the repository's own working tree and refs.
    """
    root = Path(tempfile.mkdtemp(prefix="semlock-wt-"))
    refs._run_git(repo, "worktree", "add", "--detach", "--quiet", str(root), sha)
    try:
        yield root
    finally:
        try:
            refs._run_git(repo, "worktree", "remove", "--force", str(root))
        except refs.GitError:
            refs._run_git(repo, "worktree", "prune")
            shutil.rmtree(root, ignore_errors=True)


def _registered_pair(
    language: str,
) -> tuple[type[Extractor], type[Resolver]]:
    """Fetch (Extractor, Resolver) for a language or raise PipelineUnavailable."""
    try:
        extractor_cls, resolver_cls = registry.get(language)
    except KeyError as exc:
        raise PipelineUnavailableError(
            f"no Extractor/Resolver registered for {language!r} "
            f"(extraction/resolution stages not landed yet; known: "
            f"{', '.join(registry.languages()) or '<none>'})"
        ) from exc
    return extractor_cls, resolver_cls


def collect_side(
    repo: Path,
    ref_label: str,
    ref_sha: str,
    base_sha: str,
    languages: tuple[str, ...] | None = None,
) -> tuple[FileFacts, ...]:
    """Extract + resolve one side: the FULL supported-file set at that ref.

    Why the whole tree and not just changed files: the ref-wide Resolver (S3)
    needs definition context to bind import edges — a side consuming
    `pkg.models` must carry its own copy of models.py or those refs stay
    unresolved and INV-2's choke would silence real conflicts. The engine's
    base->head graph diff likewise needs complete graphs on both ends.
    Changed-vs-base listing remains available via refs.changed_files for
    reporting and future narrowing.

    Returns RESOLVED FileFacts in deterministic (sorted-path, grouped by
    language) order. Raises PipelineUnavailableError before any work if a
    needed language has no registered implementation.
    """
    del base_sha  # kept in signature for call-site symmetry; see docstring

    with worktree_at(repo, ref_sha) as wt_root:
        selected = sorted(_walk_supported(wt_root, languages))

        by_language: dict[str, list[str]] = {}
        for path in selected:
            lang = language_for_path(path, languages)
            assert lang is not None  # _walk_supported guarantees this
            by_language.setdefault(lang, []).append(path)
        pairs = {lang: _registered_pair(lang) for lang in by_language}

        out: list[FileFacts] = []
        for lang in sorted(by_language):
            extractor_cls, resolver_cls = pairs[lang]
            extractor = extractor_cls()
            resolver = resolver_cls()
            facts: list[FileFacts] = []
            for rel_path in sorted(by_language[lang]):
                file_on_disk = wt_root / rel_path
                try:
                    source = file_on_disk.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue  # vanished mid-walk; skip
                facts.append(extractor.extract_file(rel_path, ref_label, source))
            resolved = resolver.resolve(tuple(facts))
            for item in resolved:
                if item.format_version != FORMAT_VERSION:
                    raise PipelineUnavailableError(
                        f"{item.path}: format_version {item.format_version!r} != "
                        f"supported {FORMAT_VERSION!r} (INV-6: refuse, never guess)"
                    )
            out.extend(resolved)
    return tuple(out)


def _walk_supported(
    root: Path, languages: tuple[str, ...] | None = None
) -> list[str]:
    """Repo-relative ('/'-separated) supported files under a worktree, sorted."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in filenames:
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if language_for_path(rel, languages) is not None:
                found.append(rel)
    return sorted(found)


@dataclass(frozen=True, slots=True)
class ThreeWayFacts:
    """Base + both sides' resolved facts plus the pinned commits they came from.

    side_base/side_a/side_b feed semlock.engine.build_changeset(base, a, b).
    """

    ref_a: str
    ref_b: str
    sha_a: str
    sha_b: str
    base_sha: str
    files_a: int
    files_b: int
    changed_paths_a: tuple[str, ...]
    changed_paths_b: tuple[str, ...]
    side_base: tuple[FileFacts, ...]
    side_a: tuple[FileFacts, ...]
    side_b: tuple[FileFacts, ...]


def collect_three_way(
    repo: Path,
    ref_a: str,
    ref_b: str,
    languages: tuple[str, ...] | None = None,
) -> ThreeWayFacts:
    """Resolve merge-base AND both sides (ADR-0006 three-way shape)."""
    sha_a = refs.resolve_ref(repo, ref_a)
    sha_b = refs.resolve_ref(repo, ref_b)
    base_sha = refs.merge_base(repo, sha_a, sha_b)
    changed_paths_a = refs.changed_files(repo, base_sha, sha_a)
    changed_paths_b = refs.changed_files(repo, base_sha, sha_b)
    side_base = collect_side(
        repo, f"{base_sha} (merge-base)", base_sha, base_sha, languages
    )
    side_a = collect_side(repo, ref_a, sha_a, base_sha, languages)
    side_b = collect_side(repo, ref_b, sha_b, base_sha, languages)
    return ThreeWayFacts(
        ref_a=ref_a,
        ref_b=ref_b,
        sha_a=sha_a,
        sha_b=sha_b,
        base_sha=base_sha,
        files_a=len(changed_paths_a),
        files_b=len(changed_paths_b),
        changed_paths_a=changed_paths_a,
        changed_paths_b=changed_paths_b,
        side_base=side_base,
        side_a=side_a,
        side_b=side_b,
    )
