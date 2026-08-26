"""Read-only git plumbing: refs, merge-base, changed files, file content at ref.

ADR-0006: SEMLock compares each side against the merge-base (three-way), so the
primitive operations here are exactly those needed to (a) pin two user refs to
commits, (b) find their merge-base, and (c) list/read the files that differ.

Determinism (INV-1): all commands are invoked with explicit args, output is
decoded as UTF-8 with errors replaced regardless of machine locale, and no
timestamps or environment state leak into results. Nothing here mutates the
repository (no checkout of the main worktree, no ref updates).
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """A git plumbing command failed or returned unusable output."""


def _run_git(repo: Path, *args: str) -> bytes:
    """Run `git -C <repo> <args...>` and return raw stdout bytes.

    Raises GitError on a non-zero exit or a missing git executable. stderr is
    surfaced in the exception message for diagnosability; stdout is always
    decoded by callers with a fixed encoding so locale cannot alter output.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {err}")
    return proc.stdout


def resolve_ref(repo: Path, ref: str) -> str:
    """Pin any rev expression to a full 40-hex commit sha.

    Accepts branches, tags, shas, and expressions like HEAD~3. Raises GitError
    for unknown/ambiguous refs. `--end-of-options` prevents refs beginning
    with '-' from being parsed as flags.
    """
    out = _run_git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"
    )
    sha = out.decode("utf-8", errors="replace").strip()
    if not sha:
        raise GitError(f"git resolved {ref!r} to an empty value in {repo}")
    return sha


def merge_base(repo: Path, ref_a: str, ref_b: str) -> str:
    """Compute the merge-base commit of two refs (three-way comparison base)."""
    sha_a = resolve_ref(repo, ref_a)
    sha_b = resolve_ref(repo, ref_b)
    out = _run_git(repo, "merge-base", sha_a, sha_b)
    base = out.decode("utf-8", errors="replace").strip()
    if not base:
        raise GitError(
            f"no merge-base between {ref_a!r} and {ref_b!r} (disconnected histories?)"
        )
    return base


def changed_files(repo: Path, base_ref: str, head_ref: str) -> tuple[str, ...]:
    """Repo-relative paths changed between `base_ref` (inclusive) and `head_ref`.

    Uses three-dot semantics (`base...head`): the diff from the merge-base to
    `head_ref`, which is exactly "what this side contributes" for ADR-0006's
    three-way comparison. Output is NUL-delimited (`-z`) so paths with unusual
    characters survive intact, then sorted for INV-1 determinism.
    """
    out = _run_git(repo, "diff", "--name-only", "-z", f"{base_ref}...{head_ref}")
    entries = [e for e in out.decode("utf-8", errors="replace").split("\0") if e]
    return tuple(sorted(entries))


def read_text_at(repo: Path, ref: str, path: str) -> str | None:
    """Return file content at `path` as of `ref`, UTF-8 decoded, or None if absent.

    Decoding uses errors="replace" so exotic encodings never crash the pipeline;
    span fidelity is the extractor's concern once handed the text. Returns None
    when the path does not exist at the ref (deleted on that side).
    """
    try:
        out = _run_git(repo, "show", "--end-of-options", f"{ref}:{path}")
    except GitError:
        return None
    return out.decode("utf-8", errors="replace")


def is_git_repo(path: Path) -> bool:
    """True when `path` is inside a git work tree."""
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == b"true"
