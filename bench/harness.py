"""Benchmark harness: run predictor + oracles over the case corpus.

Produces two artifact tiers:
* results.json  — DETERMINISTIC. Byte-identical across reruns on identical
  inputs (INV-1 discipline extended to bench artifacts). Contains every
  prediction verdict, oracle evidence, and FN candidates. No wall-clock data.
* timings.json  — NON-deterministic performance measurements, kept separate
  so determinism comparisons never touch them.

Predictors:
* MockPredictor ("mock:v0") replays the planted predictions stored in case
  metas. PLUMBING ONLY: it exercises the pipeline without a product CLI and
  its numbers are NEVER publishable as SEMLock results.
* CliPredictor ("cli") shells out to the real installed `semlock` binary
  (black-box: subprocess only, no importing SEMLock internals) and adapts its
  JSON findings into Predictions. Materializes each case's base/side_a/side_b
  states as commits in a throwaway git repo (`side_a`/`side_b` branches off a
  shared `base`) so the real `semlock check` seam runs unmodified.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from bench.oracle.base import (
    CaseContext,
    CheckerUnavailable,
    Oracle,
    OracleResult,
    Prediction,
    SiteError,
    Verdict,
)
from bench.oracle.mypy_oracle import MypyOracle
from bench.synth import materialize_case

RUN_SCHEMA = "bench.run.v1"


class PredictorUnavailable(RuntimeError):
    """Raised when a predictor backend is not available in this environment."""


@dataclass(frozen=True, slots=True)
class CaseMeta:
    """Parsed view of one case's meta.json."""

    case_id: str
    language: str
    source: str
    description: str
    classes: tuple[str, ...]
    predictions: tuple[Prediction, ...]
    expectation: dict[str, str]
    notes: str
    family_tag: str  # adversarial FP-category tag; "" for non-adversarial
    surface_paths: frozenset[str]


def load_case_meta(case_dir: Path) -> CaseMeta:
    document = json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))
    predictions = []
    for raw in document.get("predictions", []):
        pred = Prediction(
            prediction_id=raw["prediction_id"],
            case_id=document["case_id"],
            language=document["language"],
            conflict_class=raw["conflict_class"],
            symbol_id=raw["symbol_id"],
            ref_path=raw["ref_path"],
            ref_start_line=int(raw["ref_start_line"]),
            ref_end_line=int(raw["ref_end_line"]),
            resolution_status=raw["resolution_status"],
        )
        pred.validate()
        predictions.append(pred)
    return CaseMeta(
        case_id=document["case_id"],
        language=document["language"],
        source=document.get("source", "synthetic"),
        description=document.get("description", ""),
        classes=tuple(document.get("classes", ())),
        predictions=tuple(predictions),
        expectation=dict(document.get("expectation", {})),
        notes=document.get("notes", ""),
        family_tag=document.get("family_tag", ""),
        surface_paths=frozenset(document.get("surface_paths", ())),
    )


def discover_cases(cases_root: Path) -> tuple[Path, ...]:
    """All case directories under root, ordered by case_id (deterministic)."""
    if not cases_root.is_dir():
        return ()
    return tuple(
        sorted(
            (d for d in cases_root.iterdir() if (d / "meta.json").is_file()),
            key=lambda d: d.name,
        )
    )


class Predictor(ABC):
    kind: str = "abstract"

    @abstractmethod
    def predict(self, meta: CaseMeta) -> tuple[Prediction, ...]:
        """Predictions for one case."""


class MockPredictor(Predictor):
    """Replays meta-embedded predictions. Plumbing only — never publishable."""

    kind = "mock:v0"

    def predict(self, meta: CaseMeta) -> tuple[Prediction, ...]:
        return meta.predictions


def _run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if proc.returncode != 0:
        raise PredictorUnavailable(f"git {args}: {proc.stderr.strip()}")
    return proc.stdout


def _init_case_repo(repo: Path) -> None:
    _run_git(repo, "init", "-q", "-b", "base")
    _run_git(repo, "config", "user.email", "bench@semlock.local")
    _run_git(repo, "config", "user.name", "SEMLock Bench")
    _run_git(repo, "config", "core.autocrlf", "false")
    _run_git(repo, "config", "commit.gpgsign", "false")


def _overlay_dir(repo: Path, layer_dir: Path) -> None:
    """Copy every file under layer_dir into repo, preserving relative paths."""
    if not layer_dir.is_dir():
        return
    for src in sorted(layer_dir.rglob("*")):
        if src.is_file():
            rel = src.relative_to(layer_dir)
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())


def _commit_state(
    repo: Path, states: Path, branch: str, layer: str, message: str
) -> None:
    """Check out `branch` from `base`, overlay `layer`'s files, commit."""
    _run_git(repo, "checkout", "-q", "-b", branch, "base")
    _overlay_dir(repo, states / layer)
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", message, "--allow-empty")


def _build_case_repo(states: Path, repo: Path) -> None:
    """base branch = states/base; side_a/side_b branch off it with overlays."""
    _init_case_repo(repo)
    _overlay_dir(repo, states / "base")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "base", "--allow-empty")
    _commit_state(repo, states, "side_a", "side_a", "side a")
    _run_git(repo, "checkout", "-q", "base")
    _commit_state(repo, states, "side_b", "side_b", "side b")


class CliPredictor(Predictor):
    """Adapts real `semlock check --json` findings into Predictions.

    Black-box only: invokes the installed `semlock` binary as a subprocess,
    never imports SEMLock internals. Each case's states/{base,side_a,side_b}
    directories are materialized as commits in a throwaway git repo so the
    real check REFA REFB seam (git worktrees + merge-base) runs unmodified.
    """

    kind = "cli"

    def __init__(self, semlock_bin: str, cases_root: Path) -> None:
        self._bin = semlock_bin
        self._cases_root = cases_root
        self._resolved = 0
        self._total_edges = 0

    @property
    def resolution_stats(self) -> dict[str, int]:
        """Accumulated resolution coverage across every case predicted so
        far (Constitution §4: reported first-class beside precision/recall)."""
        return {"resolved": self._resolved, "total_edges": self._total_edges}

    def predict(self, meta: CaseMeta) -> tuple[Prediction, ...]:
        states = self._cases_root / meta.case_id / "states"
        if not states.is_dir():
            raise PredictorUnavailable(f"no states/ directory for {meta.case_id}")

        with tempfile.TemporaryDirectory(prefix="semlock-bench-repo-") as tmp:
            repo = Path(tmp)
            _build_case_repo(states, repo)
            proc = subprocess.run(
                [self._bin, "check", "side_a", "side_b", "--repo", str(repo), "--json"],
                capture_output=True, text=True, encoding="utf-8", check=False,
            )
            if proc.returncode not in (0, 1):
                err = proc.stderr.strip()[:300]
                raise PredictorUnavailable(
                    f"semlock check exited {proc.returncode}: {err}"
                )
            report = json.loads(proc.stdout)

        resolution = (report.get("engine_stats") or {}).get("resolution")
        if isinstance(resolution, dict):
            self._resolved += int(resolution.get("resolved", 0))
            self._total_edges += int(resolution.get("total", 0))

        predictions = []
        for i, finding in enumerate(report.get("findings", [])):
            span = finding["consumer_span"]
            pred = Prediction(
                prediction_id=f"{meta.case_id}#{i}",
                case_id=meta.case_id,
                language=meta.language,
                conflict_class=finding["conflict_class"],
                symbol_id=finding["changed_symbol_id"],
                ref_path=finding["consumer_path"],
                ref_start_line=int(span["start_line"]),
                ref_end_line=int(span["end_line"]),
                # The engine only ever emits findings for RESOLVED refs
                # (INV-2); the CLI's JSON report carries no separate
                # resolution field on findings because of that guarantee.
                resolution_status="resolved",
            )
            pred.validate()
            predictions.append(pred)
        return tuple(predictions)


def _oracle_for(language: str, tsc_bin: str | None) -> Oracle:
    if language == "python":
        return MypyOracle()
    if language == "typescript":
        from bench.oracle.tsc_oracle import TscOracle

        return TscOracle(tsc_bin)
    raise ValueError(f"unsupported language {language!r}")


def _serialize_error(err: SiteError) -> dict[str, object]:
    return {
        "path": err.path,
        "line": err.line,
        "column": err.column,
        "code": err.code,
        "message": err.message,
    }


def run_pipeline(
    cases_root: Path,
    workdir: Path,
    predictor: Predictor,
    tsc_bin: str | None = None,
) -> Path:
    """Run all cases; write results.json (+timings.json) into workdir/runs."""
    out_dir = workdir / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    tool_versions = _capture_tool_versions(tsc_bin)
    timings: dict[str, float] = {}
    results: list[dict[str, object]] = []

    for case_dir in discover_cases(cases_root):
        meta = load_case_meta(case_dir)
        started = time.perf_counter()
        merged_dir, counterfactual_dir = materialize_case(case_dir)
        ctx = CaseContext(
            case_id=meta.case_id,
            language=meta.language,
            merged_dir=merged_dir,
            counterfactual_dir=counterfactual_dir,
            surface_paths=frozenset(meta.surface_paths),
        )
        try:
            oracle = _oracle_for(meta.language, tsc_bin)
            predictions = predictor.predict(meta)
            verdicts = []
            for pred in predictions:
                result: OracleResult = oracle.evaluate(ctx, pred)
                verdicts.append(_prediction_entry(pred, result))
            candidates = [
                _candidate_entry(candidate, oracle)
                for candidate in oracle.scan_breaks(ctx)
            ]
        except (
            CheckerUnavailable,
            PredictorUnavailable,
            ValueError,
            subprocess.TimeoutExpired,
        ) as exc:
            # A single slow/broken case (e.g. an oracle timing out on an
            # unusually large mined state) must not lose every other case's
            # results — record it skipped and keep going (INV-8 spirit:
            # inconclusive is a valid, honestly-reported outcome).
            results.append(_skipped_case_entry(meta, exc))
            continue
        timings[meta.case_id] = round(time.perf_counter() - started, 6)
        results.append(
            {
                "case_id": meta.case_id,
                "language": meta.language,
                "source": meta.source,
                "family_tag": meta.family_tag,
                "predictions": verdicts,
                "fn_candidates": candidates,
            }
        )

    artifact: dict[str, object] = {
        "schema": RUN_SCHEMA,
        "predictor_kind": predictor.kind,
        "oracles": tool_versions,
        "results": results,
    }
    resolution_stats = getattr(predictor, "resolution_stats", None)
    if isinstance(resolution_stats, dict):
        artifact["resolution_stats"] = resolution_stats
    out = out_dir / "results.json"
    out.write_text(
        json.dumps(artifact, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    (out_dir / "timings.json").write_text(
        json.dumps(timings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return out


def _prediction_entry(pred: Prediction, result: OracleResult) -> dict[str, object]:
    return {
        "prediction_id": pred.prediction_id,
        "conflict_class": pred.conflict_class,
        "symbol_id": pred.symbol_id,
        "ref_path": pred.ref_path,
        "ref_start_line": pred.ref_start_line,
        "ref_end_line": pred.ref_end_line,
        "resolution_status": pred.resolution_status,
        "verdict": result.verdict.value,
        "evidence": {
            "tool": result.tool,
            "site_errors": [_serialize_error(e) for e in result.site_errors],
            "interaction_error_count": len(result.interaction_errors),
            "notes": list(result.notes),
        },
    }


def _candidate_entry(candidate: SiteError, oracle: Oracle) -> dict[str, object]:
    hints = [
        cls for cls in ("signature_changed", "removed_export", "field_removed",
                        "return_changed")
        if oracle.error_matches_class(candidate, cls)
    ]
    entry = _serialize_error(candidate)
    entry["class_hints"] = hints
    return entry


def _skipped_case_entry(meta: CaseMeta, exc: Exception) -> dict[str, object]:
    return {
        "case_id": meta.case_id,
        "language": meta.language,
        "source": meta.source,
        "family_tag": meta.family_tag,
        "predictions": [],
        "fn_candidates": [],
        "skipped": str(exc).splitlines()[0][:300],
    }


def _capture_tool_versions(tsc_bin: str | None) -> dict[str, object]:
    versions: dict[str, object] = {}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "mypy", "--version"],
            capture_output=True, text=True, check=False, timeout=60,
        )
        versions["python"] = {"tool": "mypy", "version": proc.stdout.strip()}
    except OSError:
        versions["python"] = {"tool": "mypy", "version": "unavailable"}
    try:
        from bench.oracle.tsc_oracle import TscOracle

        proc = subprocess.run(
            [*TscOracle(tsc_bin).version_argv(), "--version"],
            capture_output=True, text=True, check=False, timeout=60,
        )
        versions["typescript"] = {"tool": "tsc", "version": proc.stdout.strip()}
    except (OSError, CheckerUnavailable):
        versions["typescript"] = {"tool": "tsc", "version": "unavailable"}
    return versions


VERDICTS: frozenset[str] = frozenset(v.value for v in Verdict)
