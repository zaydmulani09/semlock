"""`semlock` entry point: check / graph / version.

Orchestration only: git plumbing (semlock.git), fact collection
(semlock.git.extract_at_ref), findings (semlock.output.findings), and writers
(semlock.output.text/json_out). No extraction, resolution, or conflict logic
lives here — those are S2/S3/S4 seams, consumed via the registry and the
engine's public entry point once landed.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from semlock.git import extract_at_ref, refs
from semlock.ir.version import FORMAT_VERSION
from semlock.output import findings as findings_mod
from semlock.output import json_out, text
from semlock.output.findings import Finding

EXIT_OK = 0
EXIT_CONFLICT = 1
EXIT_ERROR = 2


def _pkg_version() -> str:
    try:
        from importlib.metadata import version

        return version("semlock")
    except Exception:
        return "0+unknown"


def _force_utf8_stdout() -> None:
    """Pin stdout to UTF-8 so output bytes never depend on machine locale."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):  # pragma: no cover - exotic consoles
            pass


def _fail(message: str) -> int:
    print(f"semlock: error: {message}", file=sys.stderr)
    return EXIT_ERROR


def _validate_repo(path: Path) -> str | None:
    if not path.is_dir():
        return f"repo path is not a directory: {path}"
    if not refs.is_git_repo(path):
        return f"not a git repository: {path}"
    return None


# --------------------------------------------------------------------- engine seam


class _EngineUnavailable(RuntimeError):
    """Raised when the real pipeline stages cannot run yet."""


def _import_optional(module_name: str) -> tuple[Any | None, str]:
    """Import an optional upstream module at runtime (never statically).

    Returns (module, "") or (None, reason). Static imports would break CI for
    as long as the owning session's PR has not landed; runtime feature
    detection lets S5 code merge early and light up automatically.
    """
    if importlib.util.find_spec(module_name) is None:
        return None, f"{module_name} not present"
    try:
        return importlib.import_module(module_name), ""
    except Exception as exc:  # broken/partial install counts as unavailable
        return None, f"importing {module_name} failed: {exc}"


def _resolution_stats(files: tuple[Any, ...]) -> dict[str, Any]:
    """Resolution coverage (Constitution §4): language-agnostic, reads only
    the IR's Resolution.status — every language stamps the same shape."""
    counts = {"resolved": 0, "external": 0, "ambiguous": 0, "unresolved": 0}
    for facts in files:
        for ref in facts.refs:
            counts[ref.resolution.status] += 1
    total = sum(counts.values())
    coverage = counts["resolved"] / total if total else 0.0
    return {"total": total, "coverage": round(coverage, 4), **counts}


def _run_real_pipeline(
    repo: Path, ref_a: str, ref_b: str
) -> tuple[tuple[Finding, ...], dict[str, Any]]:
    """git -> extract -> resolve -> graph -> engine, via the frozen seams.

    Stage availability is detected at runtime; missing stages raise
    _EngineUnavailable with actionable guidance. When S2/S3 register
    extractors/resolvers and S4's package lands, this lights up without CLI
    changes (signatures consumed: engine.build_changeset(base, a, b),
    engine.evaluate(changeset) -> result with .conflicts).

    Returns (findings, engine_stats); engine_stats carries first-class
    resolution coverage over every ref collected for this run (base+A+B).
    """
    three = extract_at_ref.collect_three_way(repo, ref_a, ref_b)
    stats = {
        "resolution": _resolution_stats(
            three.side_base + three.side_a + three.side_b
        )
    }

    engine_mod, why = _import_optional("semlock.engine")
    if engine_mod is None:
        raise _EngineUnavailable(
            f"conflict engine unavailable ({why}); "
            "use --inject-fixtures SCENARIO to exercise reporting machinery"
        )
    build_changeset = getattr(engine_mod, "build_changeset", None)
    evaluate = getattr(engine_mod, "evaluate", None)
    if not callable(build_changeset) or not callable(evaluate):
        raise _EngineUnavailable(
            "semlock.engine lacks build_changeset(base_files, a_files, b_files) "
            "+ evaluate(changeset); expected API filed via interface-request"
        )

    changeset = build_changeset(
        three.side_base,
        three.side_a,
        three.side_b,
        changed_paths_a=frozenset(three.changed_paths_a),
        changed_paths_b=frozenset(three.changed_paths_b),
    )
    result = evaluate(changeset)
    conflicts = getattr(result, "conflicts", None)
    if conflicts is None:
        raise _EngineUnavailable("engine returned no .conflicts attribute")
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        eval_stats = to_dict().get("stats")
        if isinstance(eval_stats, dict):
            stats["evaluation"] = eval_stats
    return tuple(findings_mod.from_engine(c) for c in conflicts), stats


def _run_graph_export(
    repo: Path,
    ref_label: str,
    ref_sha: str,
) -> str:
    """Build the claim graph at one ref and return its deterministic JSON.

    Consumed graph API (S4): semlock.graph.build_claim_graph(files, ref=...)
    + claim_graph_to_json(graph). Raises PipelineUnavailableError when the
    graph package is absent.
    """
    graph_mod, why = _import_optional("semlock.graph")
    if graph_mod is None:
        raise extract_at_ref.PipelineUnavailableError(
            f"graph builder unavailable ({why}); `semlock graph` exports "
            "claim graphs once S4's package lands (interface-request filed)"
        )
    facts = extract_at_ref.collect_side(repo, ref_label, ref_sha, ref_sha)
    build_claim_graph = getattr(graph_mod, "build_claim_graph", None)
    claim_graph_to_json = getattr(graph_mod, "claim_graph_to_json", None)
    if not callable(build_claim_graph) or not callable(claim_graph_to_json):
        raise extract_at_ref.PipelineUnavailableError(
            "semlock.graph lacks build_claim_graph/claim_graph_to_json; "
            "expected API filed via interface-request"
        )
    return str(claim_graph_to_json(build_claim_graph(facts, ref=ref_label)))


# ---------------------------------------------------------------------- subcommands


def _cmd_check(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    if (problem := _validate_repo(repo)) is not None:
        return _fail(problem)

    config_path = args.config
    if config_path is not None and not Path(config_path).is_file():
        return _fail(f"config file not found: {config_path}")

    try:
        sha_a = refs.resolve_ref(repo, args.ref_a)
        sha_b = refs.resolve_ref(repo, args.ref_b)
        base_sha = refs.merge_base(repo, sha_a, sha_b)
        files_a = len(refs.changed_files(repo, base_sha, sha_a))
        files_b = len(refs.changed_files(repo, base_sha, sha_b))
    except refs.GitError as exc:
        return _fail(str(exc))

    findings: tuple[Finding, ...]
    engine_stats: dict[str, Any] | None = None
    if args.inject_fixtures is not None:
        # Lazy, test-only: mocks/ ships in repository checkouts, not wheels.
        try:
            from semlock.cli import mock_pipeline

            scenario = mock_pipeline.load_scenario(args.inject_fixtures)
        except ImportError:
            return _fail(
                "--inject-fixtures requires a repository checkout "
                "(mocks/ is a test-only fixture tree)"
            )
        except KeyError as exc:
            return _fail(str(exc.args[0]))
        findings = mock_pipeline.scenario_findings(scenario)
    else:
        try:
            findings, engine_stats = _run_real_pipeline(repo, args.ref_a, args.ref_b)
        except (
            _EngineUnavailable,
            extract_at_ref.PipelineUnavailableError,
        ) as exc:
            return _fail(str(exc))
        except refs.GitError as exc:
            return _fail(str(exc))

    if args.sarif:
        return _fail("SARIF writer not implemented yet (contract reserved)")

    if args.json:
        report = json_out.report_dict(
            ref_a=args.ref_a,
            ref_b=args.ref_b,
            merge_base_sha=base_sha,
            files_changed_a=files_a,
            files_changed_b=files_b,
            findings=findings,
            engine_stats=engine_stats,
        )
        sys.stdout.write(json_out.to_json(report))
    else:
        sys.stdout.write(
            text.render_text(args.ref_a, args.ref_b, base_sha, findings)
        )
    return EXIT_CONFLICT if findings else EXIT_OK


def _cmd_graph(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    if (problem := _validate_repo(repo)) is not None:
        return _fail(problem)
    try:
        ref_sha = refs.resolve_ref(repo, args.ref)
    except refs.GitError as exc:
        return _fail(str(exc))

    try:
        payload = _run_graph_export(repo, args.ref, ref_sha)
    except extract_at_ref.PipelineUnavailableError as exc:
        return _fail(str(exc))
    except refs.GitError as exc:
        return _fail(str(exc))

    if args.out is not None:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(payload)
    return EXIT_OK


def _cmd_version(_args: argparse.Namespace) -> int:
    print(f"semlock {_pkg_version()} (IR format {FORMAT_VERSION})")
    return EXIT_OK


# ------------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semlock",
        description="Detect cross-branch semantic conflicts git merge cannot see.",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    p_check = subs.add_parser("check", help="compare two refs three-way")
    p_check.add_argument("ref_a", metavar="REF_A")
    p_check.add_argument("ref_b", metavar="REF_B")
    p_check.add_argument("--repo", default=".", help="repository path (default: .)")
    fmt = p_check.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="emit JSON report")
    fmt.add_argument("--sarif", action="store_true", help="emit SARIF (reserved)")
    p_check.add_argument(
        "--config",
        default=None,
        help="path to .semlock.toml (reserved; validated for existence)",
    )
    p_check.add_argument(
        "--inject-fixtures",
        metavar="SCENARIO",
        default=None,
        help=(
            "TEST-ONLY: produce findings from a named mock changeset scenario "
            "(does NOT analyze this repo's sources)"
        ),
    )
    p_check.set_defaults(func=_cmd_check)

    p_graph = subs.add_parser("graph", help="export the claim graph at a ref")
    p_graph.add_argument("ref", metavar="REF")
    p_graph.add_argument("--repo", default=".", help="repository path (default: .)")
    p_graph.add_argument("-o", "--out", default=None, help="write to FILE")
    p_graph.set_defaults(func=_cmd_graph)

    p_ver = subs.add_parser("version", help="print version information")
    p_ver.set_defaults(func=_cmd_version)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _force_utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
