"""Determinism of the bench pipeline: identical inputs -> byte-identical
results.json (INV-1 discipline for S6 artifacts). Timings are excluded by
design (performance is not identity). When the S5 CLI lands, the same helper
gains a CLI-mode variant; scope today is the mock-predictor pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path

from bench.harness import MockPredictor, run_pipeline
from bench.synth import builtin_cases, load_adversarial_fixtures, write_case


def _build_corpus(workdir: Path) -> Path:
    for case in (*builtin_cases(), *load_adversarial_fixtures()):
        write_case(workdir, case)
    return workdir / "cases"


def test_pipeline_results_byte_identical(
    tmp_path: Path, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("SEMLOCK_TSC", "")
    corpus_a = _build_corpus(tmp_path / "a")
    corpus_b = _build_corpus(tmp_path / "b")
    out_a = run_pipeline(corpus_a, tmp_path / "a", MockPredictor())
    out_b = run_pipeline(corpus_b, tmp_path / "b", MockPredictor())
    bytes_a = out_a.read_bytes()
    bytes_b = out_b.read_bytes()
    # Tool versions embed environment identity; strip them for cross-env
    # byte-identity. Within one machine they are equal anyway.
    art_a = json.loads(bytes_a.decode("utf-8"))
    art_b = json.loads(bytes_b.decode("utf-8"))
    art_a.pop("oracles", None)
    art_b.pop("oracles", None)
    canon_a = json.dumps(art_a, indent=2).encode("utf-8")
    canon_b = json.dumps(art_b, indent=2).encode("utf-8")
    assert canon_a == canon_b
    # And on this machine, full raw files are identical too.
    assert bytes_a == bytes_b


def test_labels_derive_deterministically(tmp_path: Path) -> None:
    from bench.label import reconcile, write_labels

    corpus = _build_corpus(tmp_path)
    out = run_pipeline(corpus, tmp_path, MockPredictor())
    rows_a = reconcile(out, tmp_path)
    path_a = write_labels(rows_a, tmp_path / "labels_a.jsonl")
    rows_b = reconcile(out, tmp_path)
    path_b = write_labels(rows_b, tmp_path / "labels_b.jsonl")
    assert path_a.read_bytes() == path_b.read_bytes()
