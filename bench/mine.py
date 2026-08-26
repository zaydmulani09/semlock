"""Corpus miner: crawl clean-merge PR pairs where one side changes a symbol
surface the other side depends on (build-time only; SEMLOCK_GITHUB_TOKEN).

STATUS: scaffold. The pure, unit-testable pieces (pair scoring, surface-change
classification from file lists) are implemented and deterministic; the network
crawler is wired but not yet exercised end-to-end. Mining protocol:

1. For each repo in repos.yaml: list merged PRs (last N months).
2. For each merged PR A: fetch changed files; classify surface changes
   (signature/return/member/export edits) using the same four classes.
3. Candidate partner B: a DIFFERENT merged PR touching files that import from
   A's changed modules, merged within the window [A.base..A.merge + K days].
4. Score pairs by dependency evidence (import graph overlap x surface delta);
   keep the top-K per repo for oracle adjudication.
5. Materialize each kept pair as bench cases: base = merge-base commit,
   side_a = A's tree over base, side_b = B's tree over base; meta records
   SHAs so any case replays byte-identically.

Honesty rules binding the miner:
- No cherry-picking: candidate selection thresholds are fixed BEFORE scoring
  and recorded in the committed corpus manifest.
- Every mined case keeps provenance (repo, PR urls, SHAs, scorer version).
- Cases where side A alone fails its own type check are flagged type_dirty;
  they are graded with the strict interaction rule and reported separately.
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

GITHUB_API = "https://api.github.com"


@dataclass(frozen=True, slots=True)
class SurfaceDelta:
    """Classification of one changed file against the four classes."""

    path: str
    classes: tuple[str, ...]  # subset of CONFLICT_CLASSES


@dataclass(frozen=True, slots=True)
class PullRef:
    repo: str
    number: int
    merge_commit: str
    base_sha: str
    head_sha: str
    merged_at: str
    changed_files: tuple[str, ...]


def token_from_env() -> str | None:
    return os.environ.get("SEMLOCK_GITHUB_TOKEN") or None


def github_get(path: str, token: str | None, accept: str = "") -> object:
    """Minimal stdlib GitHub API GET honoring build-time-only usage."""
    request = urllib.request.Request(f"{GITHUB_API}{path}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if accept:
        request.add_header("Accept", accept)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def classify_surface_change(
    path: str,
    patch_added: set[str],
    patch_removed: set[str],
) -> SurfaceDelta:
    """Heuristic class hints from diff line contents (pure function).

    Deliberately coarse: candidates only. The ORACLE decides truth later;
    this classifier just ranks which pairs deserve an oracle run.
    """
    classes: list[str] = []
    lines = (*patch_added, *patch_removed)
    if path.endswith(".py"):
        if any("def " in line for line in lines):
            classes.append("signature_changed")
        if any("-> " in line for line in lines):
            classes.append("return_changed")
        if any(
            line.strip().startswith(("def ", "class ")) for line in patch_removed
        ):
            classes.append("removed_export")
        if any(line.strip().startswith("self.") for line in patch_removed):
            classes.append("field_removed")
    elif path.endswith((".ts", ".tsx")):
        if any("(" in line and ")" in line for line in lines):
            classes.append("signature_changed")
        if any(line.strip().startswith("export ") for line in patch_removed):
            classes.append("removed_export")
        if any(
            ":" in line and ";" in line and "=>" not in line
            for line in patch_removed
        ):
            classes.append("field_removed")
    # de-dup, preserve order
    seen: dict[str, None] = {}
    for cls in classes:
        seen[cls] = None
    return SurfaceDelta(path=path, classes=tuple(seen))


def pair_score(a_files: tuple[SurfaceDelta, ...],
               b_files: tuple[str, ...]) -> float:
    """Ranking score: B touches files that import from A's changed dirs.

    Pure heuristic on paths; real dependency evidence comes from SEMLock's
    resolver during grading, never from this score. Deterministic.
    """
    if not a_files:
        return 0.0
    b_dirs = {Path(p).parent.as_posix() for p in b_files}
    score = 0.0
    for delta in a_files:
        delta_dir = Path(delta.path).parent.as_posix()
        stem = Path(delta.path).stem
        for b_dir in b_dirs:
            if b_dir == delta_dir:
                score += 1.0
            elif stem in b_dir:
                score += 0.5
        score += 0.25 * len(delta.classes)
    return round(score, 3)


def materialize_pair_case(
    pair_id: str,
    pull_a: PullRef,
    pull_b: PullRef,
    out_dir: Path,
) -> Path:
    """Write case skeleton with full provenance; states filled by git replay.

    Git replay step (clone once per repo into a shared cache, then:
      git worktree add base <merge_base>, apply A tree, apply B tree) is
    invoked by the crawler driver once network mining runs for real; the
    schema below is already final so labels remain stable across that work.
    """
    case_dir = out_dir / pair_id
    case_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "case_id": pair_id,
        "source": "mined",
        "provenance": {
            "side_a": {"repo": pull_a.repo, "pr": pull_a.number,
                       "merge_commit": pull_a.merge_commit,
                       "base_sha": pull_a.base_sha},
            "side_b": {"repo": pull_b.repo, "pr": pull_b.number,
                       "merge_commit": pull_b.merge_commit,
                       "base_sha": pull_b.base_sha},
        },
        "predictions": [],  # filled by CliPredictor adapter at run time
        "expectation": {},  # NEVER populated for mined cases
    }
    (case_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return case_dir
