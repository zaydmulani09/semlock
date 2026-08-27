"""Corpus miner: crawl clean-merge PR pairs where one side changes a symbol
surface the other side depends on (build-time only; SEMLOCK_GITHUB_TOKEN).

STATUS: exercised end-to-end against real GitHub history (`python -m
bench.mine --workdir <dir>`, or `--repos-manifest` for a subset). Mining
protocol:

1. For each repo in repos.yaml: list up to MAX_PRS_PER_REPO recent merged
   PRs, size-capped (MAX_PR_CHANGED_FILES/MAX_PR_DIFF_LINES) to focused,
   single-surface-change shapes — not mechanical repo-wide codemods (see the
   cap constants' comment for the pallets/click#2270 typing-modernization
   incident that motivated them).
2. For each merged PR A with an in-scope surface-changing file: candidate
   partners B are merged PRs within CANDIDATE_WINDOW positions of A in
   merge-chronological order, scored by directory/file overlap
   (MIN_PAIR_SCORE threshold) and verified mutually independent (neither PR's
   merge is an ancestor of the other's base — genuinely concurrent, not
   sequential-with-integration).
3. Each candidate's changed files must be byte-identical between the true
   merge-base (git merge-base(A.base_sha, B.base_sha)) and that PR's own
   base_sha (_paths_unchanged_between) — otherwise `side_a`'s materialized
   content at A.head_sha would silently include whatever ELSE landed in
   those files between the merge-base and A's own branch point, misattributed
   as "A's own change." This is strict (most nearby, overlapping-file
   candidates fail it — busy/shared files are exactly the ones something
   else is also likely to touch in between) but is the only reliable way to
   materialize each side's state as base + EXACTLY that PR's own diff without
   a full patch-replay implementation. Pairs that fail are dropped, not
   guessed around; yield is honestly lower than TOP_K_PER_REPO some repos.
4. Materialize each kept pair as bench cases: `states/base` = full
   module_dirs subtree at the merge-base; `states/side_a` / `states/side_b`
   = ONLY that PR's own changed files (write_pr_files), at that PR's head
   content — a delta overlay, matching how synthetic cases are built.

Honesty rules binding the miner:
- No cherry-picking: candidate selection thresholds are fixed BEFORE scoring
  and recorded in the committed corpus manifest.
- Every mined case keeps provenance (repo, PR urls, SHAs, scorer version).
- Cases where side A alone fails its own type check are flagged type_dirty;
  they are graded with the strict interaction rule and reported separately.
"""
from __future__ import annotations

import argparse
import fnmatch
import io
import json
import os
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

GITHUB_API = "https://api.github.com"

# Fixed BEFORE scoring (Constitution §8.5 / repos.yaml honesty rules): changing
# these requires S6 sign-off and a full re-run.
MAX_PRS_PER_REPO = 600
MIN_PAIR_SCORE = 0.5
TOP_K_PER_REPO = 3
# Scope PRs to a focused, single-surface-change shape matching the product
# thesis (concurrent branches, one symbol's surface). Set after the first
# real mining run hit a 300-prediction storm from pallets/click#2270
# ("Delay evaluation of type hint imports" — a repo-wide typing-syntax
# modernization, `Optional[X]` -> `X | None` etc. across 18 files):
# mechanical codemods aren't the scenario SEMLock targets, and their
# annotation-text churn isn't something a textual signature diff can tell
# apart from a real retype without full type-expression normalization.
# Applied uniformly to both A and B candidates, pre-registered before running
# the remaining 9 repos.
MAX_PR_CHANGED_FILES = 8
MAX_PR_DIFF_LINES = 300


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
    language: str,
    score: float,
) -> Path:
    """Write case skeleton with full provenance; states filled separately by
    the git-replay step (`_write_states`) once network mining runs for real."""
    case_dir = out_dir / pair_id
    case_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "case_id": pair_id,
        "language": language,
        "source": "mined",
        "description": (
            f"{pull_a.repo}#{pull_a.number} x #{pull_b.number} "
            f"(pair_score={score})"
        ),
        "classes": [],
        "provenance": {
            "side_a": {"repo": pull_a.repo, "pr": pull_a.number,
                       "merge_commit": pull_a.merge_commit,
                       "base_sha": pull_a.base_sha,
                       "head_sha": pull_a.head_sha},
            "side_b": {"repo": pull_b.repo, "pr": pull_b.number,
                       "merge_commit": pull_b.merge_commit,
                       "base_sha": pull_b.base_sha,
                       "head_sha": pull_b.head_sha},
            "pair_score": score,
        },
        "notes": "mined case: no planted predictions, no declared sites",
        "family_tag": "",
        "predictions": [],  # filled by CliPredictor adapter at run time
        "expectation": {},  # NEVER populated for mined cases
    }
    (case_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return case_dir


# --------------------------------------------------------------------------
# Crawler driver: GitHub API pagination, git replay, repo-manifest iteration.
# --------------------------------------------------------------------------


def _api_get_with_retry(path: str, token: str | None, attempts: int = 3) -> object:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return github_get(path, token)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in (403, 429) and attempt < attempts - 1:
                time.sleep(2**attempt)
                continue
            raise
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
                continue
            raise
    assert last_exc is not None
    raise last_exc


def list_merged_prs(
    repo: str, token: str | None, max_prs: int = MAX_PRS_PER_REPO
) -> list[dict[str, object]]:
    """Recent merged PRs for `repo` (owner/name), most-recently-updated first."""
    owner, name = repo.split("/")
    out: list[dict[str, object]] = []
    page = 1
    while len(out) < max_prs:
        data = _api_get_with_retry(
            f"/repos/{owner}/{name}/pulls?state=closed&sort=updated"
            f"&direction=desc&per_page=100&page={page}",
            token,
        )
        assert isinstance(data, list)
        if not data:
            break
        for pr in data:
            assert isinstance(pr, dict)
            if pr.get("merged_at"):
                out.append(pr)
        if len(data) < 100:
            break
        page += 1
    return out[:max_prs]


def fetch_pr_files(
    repo: str, number: int, token: str | None
) -> list[dict[str, object]]:
    owner, name = repo.split("/")
    files: list[dict[str, object]] = []
    page = 1
    while True:
        data = _api_get_with_retry(
            f"/repos/{owner}/{name}/pulls/{number}/files"
            f"?per_page=100&page={page}",
            token,
        )
        assert isinstance(data, list)
        if not data:
            break
        files.extend(f for f in data if isinstance(f, dict))
        if len(data) < 100:
            break
        page += 1
    return files


def _diff_lines(patch: str) -> tuple[set[str], set[str]]:
    """Added/removed line CONTENT (marker stripped) from a unified diff hunk."""
    added: set[str] = set()
    removed: set[str] = set()
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added.add(line[1:])
        elif line.startswith("-"):
            removed.add(line[1:])
    return added, removed


def _in_scope(path: str, module_dirs: list[str], exclude: list[str]) -> bool:
    if not any(path == d or path.startswith(d.rstrip("/") + "/") for d in module_dirs):
        return False
    return not any(fnmatch.fnmatch(path, pat) for pat in exclude)


def _as_int(value: object) -> int:
    assert isinstance(value, int)
    return value


def _as_str_list(value: object) -> list[str]:
    assert isinstance(value, list)
    return [str(v) for v in value]


def _pull_ref(repo: str, pr: dict[str, object]) -> PullRef:
    base = pr["base"]
    head = pr["head"]
    assert isinstance(base, dict) and isinstance(head, dict)
    return PullRef(
        repo=repo,
        number=_as_int(pr["number"]),
        merge_commit=str(pr.get("merge_commit_sha") or ""),
        base_sha=str(base["sha"]),
        head_sha=str(head["sha"]),
        merged_at=str(pr.get("merged_at") or ""),
        changed_files=(),
    )


# Fixed BEFORE scoring alongside MIN_PAIR_SCORE/TOP_K_PER_REPO above: how many
# chronologically-nearby merged PRs count as candidate partners for A. An
# exact-shared-base-SHA requirement (the initial design) turned out to be too
# rare in real history to find surface-changing pairs at all; a real
# concurrent-branch scenario only requires that neither PR had already seen
# the other's merge when it branched — checked via git ancestry below, not by
# requiring identical starting commits.
CANDIDATE_WINDOW = 60


def _mutually_independent(clone_path: Path, pull_a: PullRef, pull_b: PullRef) -> bool:
    """True iff neither PR's base already contains the other's merge — i.e.
    they were genuinely concurrent, not sequential-with-integration."""
    for merge_sha, base_sha in (
        (pull_a.merge_commit, pull_b.base_sha),
        (pull_b.merge_commit, pull_a.base_sha),
    ):
        if not merge_sha or not base_sha:
            return False
        proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", merge_sha, base_sha],
            cwd=clone_path, capture_output=True, check=False,
        )
        if proc.returncode == 0:  # merge_sha IS an ancestor of base_sha
            return False
    return True


def find_candidate_pairs(
    repo_cfg: dict[str, object], token: str | None, clone_path: Path
) -> list[tuple[PullRef, PullRef, float, tuple[SurfaceDelta, ...]]]:
    """Merged PRs within CANDIDATE_WINDOW of each other chronologically,
    verified mutually independent by git ancestry, scored and thresholded
    per the fixed MIN_PAIR_SCORE/TOP_K_PER_REPO constants."""
    repo = str(repo_cfg["repo"])
    module_dirs = _as_str_list(repo_cfg.get("module_dirs", []))
    exclude = _as_str_list(repo_cfg.get("exclude", []))

    prs = sorted(list_merged_prs(repo, token), key=lambda p: str(p["merged_at"]))
    file_cache: dict[int, list[dict[str, object]]] = {}
    delta_cache: dict[int, tuple[SurfaceDelta, ...]] = {}
    paths_cache: dict[int, tuple[str, ...]] = {}

    def files_for(pr: dict[str, object]) -> list[dict[str, object]]:
        num = _as_int(pr["number"])
        if num not in file_cache:
            file_cache[num] = fetch_pr_files(repo, num, token)
        return file_cache[num]

    def in_pr_size_cap(pr: dict[str, object]) -> bool:
        files = files_for(pr)
        if len(files) > MAX_PR_CHANGED_FILES:
            return False
        total_lines = sum(
            _as_int(f.get("additions", 0)) + _as_int(f.get("deletions", 0))
            for f in files
        )
        return total_lines <= MAX_PR_DIFF_LINES

    def deltas_for(pr: dict[str, object]) -> tuple[SurfaceDelta, ...]:
        num = _as_int(pr["number"])
        if num not in delta_cache:
            if not in_pr_size_cap(pr):
                delta_cache[num] = ()
                return delta_cache[num]
            raw = [
                f for f in files_for(pr)
                if _in_scope(str(f["filename"]), module_dirs, exclude)
            ]
            all_deltas = tuple(
                classify_surface_change(
                    str(f["filename"]), *_diff_lines(str(f.get("patch", "")))
                )
                for f in raw
            )
            delta_cache[num] = tuple(d for d in all_deltas if d.classes)
        return delta_cache[num]

    def paths_for(pr: dict[str, object]) -> tuple[str, ...]:
        num = _as_int(pr["number"])
        if num not in paths_cache:
            if not in_pr_size_cap(pr):
                paths_cache[num] = ()
                return paths_cache[num]
            paths_cache[num] = tuple(
                str(f["filename"]) for f in files_for(pr)
                if _in_scope(str(f["filename"]), module_dirs, exclude)
            )
        return paths_cache[num]

    scored: list[tuple[PullRef, PullRef, float, tuple[SurfaceDelta, ...]]] = []
    seen: set[frozenset[int]] = set()
    for i, pr_a in enumerate(prs):
        a_deltas = deltas_for(pr_a)
        if not a_deltas:
            continue
        for pr_b in prs[max(0, i - CANDIDATE_WINDOW):i + CANDIDATE_WINDOW + 1]:
            if pr_b is pr_a:
                continue
            key = frozenset({_as_int(pr_a["number"]), _as_int(pr_b["number"])})
            if key in seen:
                continue
            b_paths = paths_for(pr_b)
            if not b_paths:
                continue
            score = pair_score(a_deltas, b_paths)
            if score < MIN_PAIR_SCORE:
                continue
            pull_a, pull_b = _pull_ref(repo, pr_a), _pull_ref(repo, pr_b)
            if not _mutually_independent(clone_path, pull_a, pull_b):
                continue
            seen.add(key)
            scored.append((pull_a, pull_b, score, a_deltas))
    scored.sort(key=lambda t: (-t[2], t[0].number, t[1].number))
    # No truncation here: mine_repo() drops candidates whose changed files
    # aren't isolated from intervening history (see _paths_unchanged_between)
    # — often most of them, since real PRs rarely branch from the exact
    # commit their eventual pairing partner also branched from — and takes
    # the first TOP_K_PER_REPO that pass, by score order.
    return scored


def _run_git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {args}: {proc.stderr.strip()[:500]}")
    return proc.stdout


def clone_or_update(repo: str, cache_dir: Path) -> Path:
    """Blobless clone (fetches all commit/tree history, blobs on demand) so
    any historical SHA is checkoutable without a full clone's size/time cost."""
    dest = cache_dir / repo.replace("/", "__")
    if (dest / ".git").is_dir():
        _run_git("fetch", "--all", "--quiet", cwd=dest)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run_git(
        "clone", "--filter=blob:none", "--quiet",
        f"https://github.com/{repo}.git", str(dest),
    )
    return dest


def archive_tree(
    clone_path: Path, sha: str, module_dirs: list[str], dest: Path
) -> None:
    """Extract `module_dirs` subtrees at `sha` into `dest` (plain directory,
    no .git) via `git archive` — fast, no worktree/checkout side effects on
    the shared clone."""
    dest.mkdir(parents=True, exist_ok=True)
    args = ["archive", sha, *module_dirs] if module_dirs else ["archive", sha]
    proc = subprocess.run(
        ["git", *args], cwd=clone_path, capture_output=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git archive {sha}: {proc.stderr.decode(errors='replace')[:500]}"
        )
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        # "data" filter requires Python 3.12+; fall back on older runtimes
        # (CI matrix includes 3.10). Content comes from a git archive of a
        # repo we chose to clone, not untrusted user input.
        try:
            tar.extractall(dest, filter="data")
        except TypeError:
            tar.extractall(dest)


def write_pr_files(
    clone_path: Path, sha: str, paths: list[str], dest: Path
) -> None:
    """Write ONLY `paths` (as they exist at `sha`) into `dest` — a delta
    overlay of exactly one PR's own changed files, not the full tree at its
    head. The full-tree-at-head approach materialized side_a/side_b THROUGH
    every commit each PR's base_sha happened to sit behind the true
    merge-base, not just that PR's own diff — when A and B's base_sha differ
    (the common case once pairing moved off exact-base-SHA matching), that
    confounding intervening history got misattributed as "the concurrent
    branch's own change," producing predictions with no relationship to
    either PR's actual diff. A delta overlay (matching how synthetic cases
    are built: base's full tree + only the changed files) avoids this."""
    dest.mkdir(parents=True, exist_ok=True)
    for path in paths:
        proc = subprocess.run(
            ["git", "show", f"{sha}:{path}"],
            cwd=clone_path, capture_output=True, check=False,
        )
        if proc.returncode != 0:
            continue  # deleted/renamed at this sha; best-effort overlay
        out_path = dest / path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(proc.stdout)


def _paths_unchanged_between(
    clone_path: Path, sha_a: str, sha_b: str, paths: list[str]
) -> bool:
    """True iff every path is byte-identical at both commits — i.e. nothing
    OTHER than the PR itself touched these files between the true merge-base
    and this PR's own base_sha, so `write_pr_files` at the PR's head is
    exactly that PR's own diff with no confounding intervening history."""
    if not paths:
        return True
    proc = subprocess.run(
        ["git", "diff", "--quiet", sha_a, sha_b, "--", *paths],
        cwd=clone_path, capture_output=True, check=False,
    )
    return proc.returncode == 0


def mine_repo(
    repo_cfg: dict[str, object],
    token: str | None,
    cases_out: Path,
    clone_cache: Path,
) -> list[Path]:
    repo = str(repo_cfg["repo"])
    language = str(repo_cfg["language"])
    module_dirs = _as_str_list(repo_cfg.get("module_dirs", []))
    exclude = _as_str_list(repo_cfg.get("exclude", []))

    clone_path = clone_or_update(repo, clone_cache)
    candidates = find_candidate_pairs(repo_cfg, token, clone_path)
    if not candidates:
        return []

    written: list[Path] = []
    for pull_a, pull_b, score, _deltas in candidates:
        if len(written) >= TOP_K_PER_REPO:
            break
        merge_base_sha = _run_git(
            "merge-base", pull_a.base_sha, pull_b.base_sha, cwd=clone_path
        ).strip()
        a_paths = [
            str(f["filename"]) for f in fetch_pr_files(repo, pull_a.number, token)
            if _in_scope(str(f["filename"]), module_dirs, exclude)
        ]
        b_paths = [
            str(f["filename"]) for f in fetch_pr_files(repo, pull_b.number, token)
            if _in_scope(str(f["filename"]), module_dirs, exclude)
        ]
        # A/B's own changed files must be untouched by anything else between
        # the true merge-base and that PR's own base_sha, or head-sha content
        # for those paths would silently include unrelated intervening
        # history, not just this PR's diff. Drop the pair rather than guess.
        a_isolated = _paths_unchanged_between(
            clone_path, merge_base_sha, pull_a.base_sha, a_paths
        )
        b_isolated = _paths_unchanged_between(
            clone_path, merge_base_sha, pull_b.base_sha, b_paths
        )
        if not (a_isolated and b_isolated):
            continue
        pair_id = f"{repo.replace('/', '-')}-{pull_a.number}x{pull_b.number}"
        case_dir = materialize_pair_case(
            pair_id, pull_a, pull_b, cases_out, language, score
        )
        states = case_dir / "states"
        archive_tree(clone_path, merge_base_sha, module_dirs, states / "base")
        write_pr_files(clone_path, pull_a.head_sha, a_paths, states / "side_a")
        write_pr_files(clone_path, pull_b.head_sha, b_paths, states / "side_b")
        written.append(case_dir)
    return written


def main() -> int:
    import yaml  # type: ignore[import-untyped]

    parser = argparse.ArgumentParser(prog="bench.mine")
    parser.add_argument("--workdir", required=True)
    parser.add_argument(
        "--repos-manifest", default=str(Path(__file__).parent / "repos.yaml")
    )
    args = parser.parse_args()

    workdir = Path(args.workdir)
    cases_out = workdir / "cases"
    clone_cache = workdir / "clones"
    cases_out.mkdir(parents=True, exist_ok=True)
    clone_cache.mkdir(parents=True, exist_ok=True)

    manifest = yaml.safe_load(Path(args.repos_manifest).read_text(encoding="utf-8"))
    token = token_from_env()

    summary: dict[str, int] = {}
    for repo_cfg in manifest["repos"]:
        repo = str(repo_cfg["repo"])
        try:
            written = mine_repo(repo_cfg, token, cases_out, clone_cache)
        except Exception as exc:  # noqa: BLE001 - report and continue other repos
            print(f"[mine] {repo}: FAILED — {exc}")
            summary[repo] = -1
            continue
        summary[repo] = len(written)
        print(f"[mine] {repo}: {len(written)} pair(s) mined")

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
