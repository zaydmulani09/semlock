"""Reproducible benchmark entrypoint (runnable from a clean clone).

Usage:
    python -m bench.run_benchmark --workdir <dir> \\
        [--corpus builtin|adversarial|all|mined] [--mined-cases DIR]

Stages: materialize corpus -> run pipeline -> reconcile labels -> render
report. Artifacts land under <workdir>/runs/ and <workdir>/labels/.

`--corpus mined` runs against cases already materialized by `bench.mine`
(default: <workdir>/cases, i.e. the same workdir passed to `bench.mine
--workdir`; override with --mined-cases if they live elsewhere) instead of
building the synthetic/adversarial corpus.

Environment:
    SEMLOCK_TSC   path/hint for tsc when TS cases are included; TS cases are
                  recorded skipped (inconclusive) when absent.
    SEMLOCK_MYPY  optional explicit mypy binary; defaults to this interpreter.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bench.harness import CliPredictor, MockPredictor, Predictor, run_pipeline
from bench.label import reconcile, write_labels
from bench.report import attach_resolution_coverage, compute_metrics, render_report
from bench.synth import (
    builtin_cases,
    load_adversarial_fixtures,
    write_case,
)


def build_corpus(workdir: Path, which: str, mined_cases: Path | None) -> Path:
    if which == "mined":
        cases = mined_cases if mined_cases is not None else workdir / "cases"
        if not cases.is_dir():
            raise SystemExit(
                f"--corpus mined: {cases} does not exist; run `python -m "
                "bench.mine --workdir <dir>` first (or pass --mined-cases)"
            )
        return cases
    cases = workdir / "cases"
    if which in ("builtin", "all"):
        for case in builtin_cases():
            write_case(workdir, case)
    if which in ("adversarial", "all"):
        for case in load_adversarial_fixtures():
            write_case(workdir, case)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(prog="run_benchmark")
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--corpus", default="all",
                        choices=("builtin", "adversarial", "all", "mined"))
    parser.add_argument("--mined-cases", default=None,
                         help="cases/ dir from a prior `bench.mine` run "
                              "(default: <workdir>/cases)")
    parser.add_argument("--predictor", default="mock", choices=("mock", "cli"))
    args = parser.parse_args()

    workdir = Path(args.workdir)
    mined_cases = Path(args.mined_cases) if args.mined_cases else None
    corpus = build_corpus(workdir, args.corpus, mined_cases)

    predictor: Predictor
    if args.predictor == "cli":
        predictor = CliPredictor("semlock", corpus)
    else:
        predictor = MockPredictor()

    results_path = run_pipeline(corpus, workdir, predictor)
    rows = reconcile(results_path, workdir)
    labels_path = write_labels(rows, workdir / "labels" / "labels.jsonl")

    metrics = compute_metrics(labels_path)
    metrics = attach_resolution_coverage(metrics, results_path)
    timings_path = workdir / "runs" / "timings.json"
    runtime: float | None = None
    if timings_path.is_file():
        timing_map = json.loads(timings_path.read_text(encoding="utf-8"))
        assert isinstance(timing_map, dict)
        runtime = float(sum(float(v) for v in timing_map.values()))
    report = render_report(
        metrics, predictor.kind, runtime_seconds=runtime
    )
    report_path = workdir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"artifacts: {results_path} {labels_path} {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
