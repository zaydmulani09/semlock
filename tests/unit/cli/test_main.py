"""S5 unit tests: CLI arg handling, exit codes 0/1/2, writer determinism.

The real-pipeline path must refuse cleanly while S2/S3/S4 are unlanded;
conflict paths use --inject-fixtures (explicitly a reporting-machinery
harness, not source analysis).
"""
from __future__ import annotations

import json

import pytest

from semlock.cli import main as cli_main

CONFLICT_ARGS = ("signature_changed_param_renamed",)
CLEAN_ARGS = ("clean_merge_new_method",)


def _check_argv(repo_path, ref_a="feat/a", ref_b="feat/b", extra=()):
    return ["check", ref_a, ref_b, "--repo", str(repo_path), *extra]


def test_version_reports_ir_format(capsys) -> None:
    assert cli_main.main(["version"]) == 0
    out = capsys.readouterr().out
    assert "semlock" in out
    assert "0.2.0" in out  # IR format version


def test_check_rejects_non_repo_paths(tmp_path, capsys) -> None:
    assert cli_main.main(["check", "a", "b", "--repo", str(tmp_path / "nope")]) == 2
    plain = tmp_path / "plain"
    plain.mkdir()
    assert cli_main.main(["check", "a", "b", "--repo", str(plain)]) == 2
    assert "error" in capsys.readouterr().err


def test_check_bad_ref_is_exit_2(two_branch_repo, capsys) -> None:
    code = cli_main.main(_check_argv(two_branch_repo.path, "nope-1", "feat/b"))
    assert code == 2
    assert "failed" in capsys.readouterr().err


def test_check_real_pipeline_refuses_cleanly_until_engine_lands(
    two_branch_repo, capsys
) -> None:
    code = cli_main.main(_check_argv(two_branch_repo.path))
    assert code == 2
    err = capsys.readouterr().err.lower()
    assert "engine" in err or "extractor" in err


def test_check_injected_conflict_exits_1_with_dual_evidence(
    two_branch_repo, capsys
) -> None:
    argv = _check_argv(
        two_branch_repo.path, extra=("--inject-fixtures", CONFLICT_ARGS[0])
    )
    assert cli_main.main(argv) == 1
    out = capsys.readouterr().out
    assert "[signature_changed] pkg.models::User.greet" in out
    assert "pkg/models.py:8" in out  # A-side definition line (fixture facts)
    assert "pkg/app.py:4" in out  # B-side call site
    assert "call 'greet'" in out


def test_check_injected_clean_scenario_exits_0(two_branch_repo, capsys) -> None:
    argv = _check_argv(two_branch_repo.path, extra=("--inject-fixtures", CLEAN_ARGS[0]))
    assert cli_main.main(argv) == 0
    assert "no cross-branch semantic conflicts" in capsys.readouterr().out


def test_check_unknown_scenario_name_is_exit_2(two_branch_repo, capsys) -> None:
    argv = _check_argv(two_branch_repo.path, extra=("--inject-fixtures", "zzz"))
    assert cli_main.main(argv) == 2
    assert "unknown scenario" in capsys.readouterr().err.lower()


def test_check_json_report_shape_and_determinism(two_branch_repo, capsys) -> None:
    argv = _check_argv(
        two_branch_repo.path,
        extra=("--json", "--inject-fixtures", "field_removed_email"),
    )
    assert cli_main.main(argv) == 1
    first = capsys.readouterr().out
    assert cli_main.main(argv) == 1
    second = capsys.readouterr().out
    assert first == second  # INV-1: byte-identical reruns

    report = json.loads(first)
    assert report["schema"] == "semlock.check-report"
    assert report["ir_format_version"] == "0.2.0"
    assert report["conflict_count"] == len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["conflict_class"] == "field_removed"
    assert finding["changed_symbol_id"] == "pkg.models::User.email"
    assert finding["changed_side"] == "A"
    assert finding["consumer_side"] == "B"
    assert finding["consumer_path"] == "pkg/app.py"
    assert finding["evidence_a"]["path"] == "pkg/models.py"
    # The member itself is gone on side A (that IS the conflict); evidence
    # falls back to the owning User class span (line 3), never fabricated.
    assert finding["evidence_a"]["line"] == 3
    assert finding["evidence_b"]["path"] == "pkg/app.py"
    assert finding["evidence_b"]["role"] == "consuming_use"
    # Fixed key order (INV-1).
    assert list(report) == [
        "schema",
        "report_format_version",
        "ir_format_version",
        "ref_a",
        "ref_b",
        "merge_base",
        "files_changed_a",
        "files_changed_b",
        "conflict_count",
        "engine_stats",
        "findings",
    ]
    assert report["engine_stats"] is None  # fixture mode: no engine ran


def test_sarif_reserved_and_mutually_exclusive(two_branch_repo, capsys) -> None:
    # Reach the writer branch via fixture mode (the real path refuses earlier).
    base = _check_argv(
        two_branch_repo.path, extra=("--inject-fixtures", CONFLICT_ARGS[0])
    )
    assert cli_main.main([*base, "--sarif"]) == 2
    assert "SARIF" in capsys.readouterr().err
    plain = _check_argv(two_branch_repo.path)
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main([*plain, "--json", "--sarif"])
    assert excinfo.value.code == 2
    capsys.readouterr()


def test_config_must_exist_when_given(two_branch_repo, capsys) -> None:
    argv = _check_argv(two_branch_repo.path, extra=("--config", "absent.toml"))
    assert cli_main.main(argv) == 2
    assert "config" in capsys.readouterr().err.lower()


def test_graph_pending_engine_is_exit_2(two_branch_repo, capsys) -> None:
    argv = ["graph", "feat/a", "--repo", str(two_branch_repo.path)]
    assert cli_main.main(argv) == 2
    assert "not landed" in capsys.readouterr().err.lower()


def test_graph_bad_ref_is_exit_2(two_branch_repo, capsys) -> None:
    argv = ["graph", "ghost", "--repo", str(two_branch_repo.path)]
    assert cli_main.main(argv) == 2
