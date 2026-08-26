"""S5 unit tests: read-only git plumbing (refs, merge-base, changed files).

Fixtures (`mini_repo`, `two_branch_repo`) are injected from tests/conftest.py.
"""
from __future__ import annotations

import pytest

from semlock.git import refs


def test_resolve_ref_pins_branch_and_sha_to_same_commit(mini_repo) -> None:
    mini_repo.commit("a.txt", "hello\n", "initial")

    from_branch = refs.resolve_ref(mini_repo.path, "main")
    from_head = refs.resolve_ref(mini_repo.path, "HEAD")
    raw = mini_repo.git("rev-parse", "HEAD").strip()

    assert from_branch == from_head == raw
    assert len(from_branch) == 40


def test_resolve_ref_supports_relative_expressions_and_rejects_unknown(
    mini_repo,
) -> None:
    mini_repo.commit("a.txt", "one\n", "c1")
    mini_repo.commit("a.txt", "two\n", "c2")

    assert refs.resolve_ref(mini_repo.path, "HEAD~1") != refs.resolve_ref(
        mini_repo.path, "HEAD"
    )
    with pytest.raises(refs.GitError, match="failed"):
        refs.resolve_ref(mini_repo.path, "no-such-ref")


def test_merge_base_returns_fork_point(mini_repo) -> None:
    mini_repo.commit("base.txt", "base\n", "base")
    fork = mini_repo.git("rev-parse", "HEAD").strip()
    mini_repo.git("checkout", "-b", "side")
    mini_repo.commit("side.txt", "side\n", "side work")
    mini_repo.git("checkout", "main")
    mini_repo.commit("main.txt", "main\n", "main work")

    assert refs.merge_base(mini_repo.path, "side", "main") == fork


def test_merge_base_disconnected_histories_raise(mini_repo) -> None:
    mini_repo.commit("a.txt", "a\n", "root a")
    mini_repo.git("checkout", "--orphan", "lonely")
    (mini_repo.path / "b.txt").write_text("b\n", encoding="utf-8")
    mini_repo.git("add", ".")
    mini_repo.git("commit", "-m", "root b")
    mini_repo.git("checkout", "main")

    with pytest.raises(refs.GitError, match="merge-base|disconnected"):
        refs.merge_base(mini_repo.path, "main", "lonely")


def test_changed_files_uses_three_dot_semantics_per_side(two_branch_repo) -> None:
    base = two_branch_repo.git("merge-base", "feat/a", "feat/b").strip()

    a_files = refs.changed_files(two_branch_repo.path, base, "feat/a")
    b_files = refs.changed_files(two_branch_repo.path, base, "feat/b")

    assert a_files == ("pkg/models.py",)
    assert b_files == ("pkg/app.py",)
    # Both sides share one comparison base: the three-way shape (ADR-0006).
    assert refs.merge_base(two_branch_repo.path, "feat/a", "feat/b") == base


def test_changed_files_sorted_deterministically(mini_repo) -> None:
    mini_repo.commit("z.txt", "z\n", "base")
    fork = mini_repo.git("rev-parse", "HEAD").strip()
    mini_repo.git("checkout", "-b", "side")
    mini_repo.commit("m.txt", "m\n", "add m")
    mini_repo.commit("a.txt", "a\n", "add a")

    assert refs.changed_files(mini_repo.path, fork, "side") == ("a.txt", "m.txt")


def test_read_text_at_reads_content_and_none_for_missing(two_branch_repo) -> None:
    sha = refs.resolve_ref(two_branch_repo.path, "feat/a")

    assert (
        refs.read_text_at(two_branch_repo.path, sha, "pkg/models.py") == "value = 2\n"
    )
    assert refs.read_text_at(two_branch_repo.path, sha, "pkg/absent.py") is None


def test_is_git_repo_true_inside_false_outside(mini_repo, tmp_path) -> None:
    assert refs.is_git_repo(mini_repo.path) is True
    plain = tmp_path / "plain"
    plain.mkdir()
    assert refs.is_git_repo(plain) is False
