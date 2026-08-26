"""S5 integration tests: the three-way pipeline seams on real temp repos.

Pins the ADR-0006 shape end-to-end at the git layer: one merge-base, per-side
changed-file sets computed against it, and refusal behavior of fact collection
when a language has no registered Extractor/Resolver.
"""
from __future__ import annotations

import pytest

from semlock.extractors import registry
from semlock.git import extract_at_ref, refs


def test_both_sides_share_one_merge_base(two_branch_repo) -> None:
    repo = two_branch_repo.path
    sha_a = refs.resolve_ref(repo, "feat/a")
    sha_b = refs.resolve_ref(repo, "feat/b")

    base = refs.merge_base(repo, sha_a, sha_b)

    # The base predates both tips and is an ancestor of each.
    assert base != sha_a and base != sha_b
    two_branch_repo.git("merge-base", "--is-ancestor", base, sha_a)
    two_branch_repo.git("merge-base", "--is-ancestor", base, sha_b)


def test_same_file_different_regions_merges_clean_textually(mini_repo) -> None:
    """The skeptical-engineer premise: both sides touch pkg/models.py in
    different regions; git merges clean while semantics may still break."""
    mini_repo.commit(
        "pkg/models.py",
        "def greet(name):\n    return name\n\ndef tail():\n    return 0\n",
        "base",
    )
    mini_repo.git("checkout", "-b", "feat/a")
    mini_repo.commit(
        "pkg/models.py",
        "def greet(greeting):\n    return greeting\n\ndef tail():\n    return 0\n",
        "a renames param",
    )
    mini_repo.git("checkout", "main")
    mini_repo.git("checkout", "-b", "feat/b")
    mini_repo.commit(
        "pkg/models.py",
        "def greet(name):\n    return name\n\ndef tail():\n    return 1\n",
        "b edits tail",
    )

    out = mini_repo.git("merge-tree", "--write-tree", "feat/a", "feat/b")
    assert out.strip() != ""  # a tree was produced
    # exit code 0 == no textual conflict (run_git asserts returncode == 0)

    base = refs.merge_base(mini_repo.path, "feat/a", "feat/b")
    assert refs.changed_files(mini_repo.path, base, "feat/a") == ("pkg/models.py",)
    assert refs.changed_files(mini_repo.path, base, "feat/b") == ("pkg/models.py",)


def test_collect_three_way_refusal_names_missing_stage(
    two_branch_repo, monkeypatch
) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {})
    monkeypatch.setattr(registry, "_bootstrapped", True)
    with pytest.raises(
        extract_at_ref.PipelineUnavailableError, match="python"
    ) as excinfo:
        extract_at_ref.collect_three_way(two_branch_repo.path, "feat/a", "feat/b")
    assert "Extractor/Resolver" in str(excinfo.value)


def test_worktree_repeated_use_leaves_no_litter(two_branch_repo) -> None:
    repo = two_branch_repo.path
    sha = refs.resolve_ref(repo, "feat/a")
    for _ in range(3):
        with extract_at_ref.worktree_at(repo, sha):
            pass

    listing = two_branch_repo.git("worktree", "list", "--porcelain")
    assert listing.count("worktree ") == 1
