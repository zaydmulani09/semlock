"""S6 oracle validation on synthetic cases (the labels-meaningfulness gate).

For every builtin case: the external checker must flag each planted break AT
the predicted site with a class-compatible diagnostic (true_positive), and
clean merges must produce zero interaction-attributable errors. TypeScript
cases skip (not fail) when no tsc is discoverable; Python skips only if mypy
itself is unavailable, which is a hard environment error for this repo.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.oracle.base import CaseContext, Prediction
from bench.oracle.mypy_oracle import MypyOracle
from bench.synth import builtin_cases, materialize_case, write_case


def _oracle_for(language: str):  # type: ignore[no-untyped-def]
    if language == "python":
        return MypyOracle()
    pytest.importorskip("shutil")
    from bench.oracle.tsc_oracle import TscOracle, discover_tsc

    try:
        discover_tsc(None)
    except Exception:  # noqa: BLE001 - any discovery failure means skip
        pytest.skip("tsc not available in this environment")
    return TscOracle()


def _make_case(tmp_path: Path, case) -> tuple[CaseContext, dict]:  # type: ignore[no-untyped-def]
    case_dir = write_case(tmp_path, case)
    merged, counterfactual = materialize_case(case_dir)
    ctx = CaseContext(
        case_id=case.case_id,
        language=case.language,
        merged_dir=merged,
        counterfactual_dir=counterfactual,
        surface_paths=frozenset(case.side_a),
    )
    meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))
    return ctx, meta


@pytest.mark.parametrize(
    "case", [c for c in builtin_cases() if c.planted], ids=lambda c: c.case_id
)
def test_planted_break_confirmed_at_predicted_site(
    tmp_path: Path, case  # type: ignore[no-untyped-def]
) -> None:
    oracle = _oracle_for(case.language)
    ctx, meta = _make_case(tmp_path, case)
    for raw in meta["predictions"]:
        pred = Prediction(
            prediction_id=str(raw["prediction_id"]),
            case_id=meta["case_id"],
            language=meta["language"],
            conflict_class=str(raw["conflict_class"]),
            symbol_id=str(raw["symbol_id"]),
            ref_path=str(raw["ref_path"]),
            ref_start_line=int(raw["ref_start_line"]),
            ref_end_line=int(raw["ref_end_line"]),
            resolution_status=str(raw["resolution_status"]),
        )
        result = oracle.evaluate(ctx, pred)
        assert result.verdict.value == "true_positive", (
            f"{case.case_id}: {result.verdict.value} notes={list(result.notes)}"
        )


@pytest.mark.parametrize(
    "case", [c for c in builtin_cases() if not c.planted], ids=lambda c: c.case_id
)
def test_clean_merge_has_no_interaction_errors(
    tmp_path: Path, case  # type: ignore[no-untyped-def]
) -> None:
    oracle = _oracle_for(case.language)
    ctx, _meta = _make_case(tmp_path, case)
    candidates = oracle.scan_breaks(ctx)
    assert candidates == (), f"{case.case_id}: unexpected {candidates}"
