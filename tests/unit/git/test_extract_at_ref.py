"""S5 unit tests: worktree checkout + registry dispatch (extract_at_ref).

Pins the CONTRACT: clean refusal naming the missing stage when a language has
no registered Extractor/Resolver, correct language routing by extension, and
leak-free worktree lifecycle. The refusal tests monkeypatch the registry
empty rather than relying on an unregistered language existing process-wide,
since python/typescript are both registered once S2/S3 land.
"""
from __future__ import annotations

import pytest

from semlock.extractors import registry
from semlock.git import extract_at_ref, refs


def test_language_for_path_maps_extensions() -> None:
    assert extract_at_ref.language_for_path("a/b.py") == "python"
    assert extract_at_ref.language_for_path("src/x.TS") == "typescript"
    assert extract_at_ref.language_for_path("src/y.tsx") == "typescript"
    assert extract_at_ref.language_for_path("README.md") is None
    assert extract_at_ref.language_for_path("noext") is None


def test_language_for_path_respects_restriction() -> None:
    langs = ("python",)
    assert extract_at_ref.language_for_path("src/x.ts", langs) is None
    assert extract_at_ref.language_for_path("m/x.py", langs) == "python"


def test_worktree_at_checks_out_and_cleans_up(two_branch_repo) -> None:
    sha_a = refs.resolve_ref(two_branch_repo.path, "feat/a")

    with extract_at_ref.worktree_at(two_branch_repo.path, sha_a) as wt:
        assert (wt / "pkg" / "models.py").read_text(encoding="utf-8") == "value = 2\n"

    listing = two_branch_repo.git("worktree", "list", "--porcelain")
    assert listing.count("worktree ") == 1  # only the main checkout remains


def test_collect_side_refuses_cleanly_without_registered_extractors(
    two_branch_repo, monkeypatch
) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {})
    monkeypatch.setattr(registry, "_bootstrapped", True)
    repo = two_branch_repo.path
    sha_a = refs.resolve_ref(repo, "feat/a")
    base = refs.merge_base(repo, "feat/a", "feat/b")

    with pytest.raises(extract_at_ref.PipelineUnavailableError, match="python"):
        extract_at_ref.collect_side(repo, "feat/a", sha_a, base)


def test_collect_three_way_fails_fast_before_any_extraction(
    two_branch_repo, monkeypatch
) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {})
    monkeypatch.setattr(registry, "_bootstrapped", True)
    with pytest.raises(extract_at_ref.PipelineUnavailableError):
        extract_at_ref.collect_three_way(two_branch_repo.path, "feat/a", "feat/b")


def test_collect_side_with_no_supported_changes_is_empty(mini_repo) -> None:
    """A side that changed ONLY unsupported files dispatches nothing and must
    return empty facts without consulting the (empty) registry."""
    mini_repo.commit("docs/readme.md", "hi\n", "base")
    sha = refs.resolve_ref(mini_repo.path, "HEAD")

    facts = extract_at_ref.collect_side(mini_repo.path, "HEAD", sha, sha)
    assert facts == ()
