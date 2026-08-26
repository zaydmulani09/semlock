"""Shared S5 test fixtures: disposable git repos built on pytest tmp_path.

Common-space test infrastructure (ownership.yaml: tests/ is common). Provides
only additive fixtures; no existing behavior depends on this file.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


def run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, f"git {args}: {proc.stderr}"
    return proc.stdout


def write_and_commit(repo: Path, rel_path: str, content: str, message: str) -> None:
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", message)


@dataclass(frozen=True)
class MiniRepo:
    """A tiny real repository plus convenience wrappers."""

    repo: Path

    def git(self, *args: str) -> str:
        return run_git(self.repo, *args)

    def commit(self, rel_path: str, content: str, message: str) -> None:
        write_and_commit(self.repo, rel_path, content, message)

    @property
    def path(self) -> Path:
        return self.repo


def init_repo(root: Path) -> MiniRepo:
    repo = root / "repo"
    repo.mkdir(parents=True)
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "s5@test")
    run_git(repo, "config", "user.name", "S5 Test")
    run_git(repo, "config", "core.autocrlf", "false")
    run_git(repo, "config", "commit.gpgsign", "false")
    return MiniRepo(repo)


@pytest.fixture()
def mini_repo(tmp_path: Path) -> MiniRepo:
    return init_repo(tmp_path)


@pytest.fixture()
def two_branch_repo(mini_repo: MiniRepo) -> MiniRepo:
    """main <- fork; feat/a edits pkg/models.py, feat/b adds pkg/app.py."""
    r = mini_repo
    r.commit("pkg/models.py", "value = 1\n", "base")
    r.git("checkout", "-b", "feat/a")
    r.commit("pkg/models.py", "value = 2\n", "a edits models")
    r.git("checkout", "main")
    r.git("checkout", "-b", "feat/b")
    r.commit("pkg/app.py", "import pkg.models\n", "b adds app")
    r.git("checkout", "main")
    return r
