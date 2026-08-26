"""S5 e2e: the skeptical-engineer demo as a test.

Scenario: two branches that GIT MERGES CLEANLY (disjoint files / regions) but
which semantically break each other. SEMLock's git layer runs for real against
the mini-repo; findings come from S1's ground-truth fixtures via the explicit
--inject-fixtures harness while S2/S3/S4 land. The demo proves: correct exit
codes, dual-sided file:line evidence, byte-identical reruns, and — critically —
that plain `git merge` reports no conflict for the same pair.

Runs the CLI exactly as a user would: `python -m semlock.cli.main`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFLICT_SCENARIO = "signature_changed_param_renamed"
CLEAN_SCENARIO = "clean_merge_new_method"


def run_cli(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "semlock.cli.main", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(REPO_ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


def assert_textual_merge_is_clean(
    repo_path: Path, branch_a: str, branch_b: str
) -> None:
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "merge-tree", "--write-tree", branch_a, branch_b],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "premise broken: git reported a textual conflict; "
        f"stderr={proc.stderr.strip()}"
    )


def build_skeptical_repo(mini_repo) -> Path:
    r = mini_repo
    r.commit(
        "pkg/models.py",
        "class User:\n"
        "    email = 'a@b.c'\n"
        "\n"
        "    def greet(self, name):\n"
        "        return 'Hello, ' + name\n",
        "base models",
    )
    r.git("checkout", "-b", "feat/greeting-surface")
    r.commit(
        "pkg/models.py",
        "class User:\n"
        "    email = 'a@b.c'\n"
        "\n"
        "    def greet(self, greeting):\n"
        "        return 'Hello, ' + greeting\n",
        "a renames greet param",
    )
    r.git("checkout", "main")
    r.git("checkout", "-b", "feat/app")
    r.commit(
        "pkg/app.py",
        "from pkg.models import User\n"
        "\n"
        "def welcome():\n"
        "    return User().greet(name='Ada')\n",
        "b consumes greet(name=)",
    )
    r.git("checkout", "main")
    return r.path


def test_git_merges_clean_but_semlock_flags(mini_repo) -> None:
    repo_path = build_skeptical_repo(mini_repo)
    a, b = "feat/greeting-surface", "feat/app"

    # The premise: git sees NO conflict.
    assert_textual_merge_is_clean(repo_path, a, b)

    code, out, err = run_cli(
        "check", a, b, "--repo", str(repo_path), "--inject-fixtures", CONFLICT_SCENARIO
    )

    assert err == "", f"unexpected stderr: {err}"
    assert code == 1
    assert "[signature_changed] pkg.models::User.greet" in out
    assert "A pkg/models.py:" in out  # changed surface (definition side)
    assert "B pkg/app.py:" in out  # consumer use-site
    assert "call 'greet'" in out


def test_same_pair_reports_clean_for_true_negative_scenario(mini_repo) -> None:
    repo_path = build_skeptical_repo(mini_repo)

    code, out, _err = run_cli(
        "check",
        "feat/greeting-surface",
        "feat/app",
        "--repo",
        str(repo_path),
        "--inject-fixtures",
        CLEAN_SCENARIO,
    )

    assert code == 0
    assert "no cross-branch semantic conflicts" in out


def test_json_reruns_are_byte_identical(mini_repo) -> None:
    repo_path = build_skeptical_repo(mini_repo)
    argv = (
        "check",
        "feat/greeting-surface",
        "feat/app",
        "--repo",
        str(repo_path),
        "--json",
        "--inject-fixtures",
        CONFLICT_SCENARIO,
    )

    code1, out1, _ = run_cli(*argv)
    code2, out2, _ = run_cli(*argv)

    assert code1 == code2 == 1
    assert out1 == out2


def test_module_entry_point_exists() -> None:
    """`python -m semlock.cli.main` with no args must fail with usage (exit 2)."""
    proc = subprocess.run(
        [sys.executable, "-m", "semlock.cli.main"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 2
