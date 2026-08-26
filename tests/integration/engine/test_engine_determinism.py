"""Integration: INV-1 determinism + published wire shapes for S5."""
from __future__ import annotations

import json

from mocks import ir_fixtures as fx
from mocks.changeset_fixtures import all_scenarios
from semlock.engine import build_changeset, evaluate
from semlock.graph import build_claim_graph, claim_graph_to_json

BASE_FILES = (fx.models_main(ref=fx.MAIN),)


def test_evaluation_output_byte_deterministic() -> None:
    runs = []
    for _ in range(2):
        dumps = []
        for scenario in all_scenarios():
            cs = build_changeset(BASE_FILES, scenario.side_a, scenario.side_b)
            res = evaluate(cs)
            dumps.append(json.dumps(res.to_dict(), sort_keys=False))
        runs.append(dumps)
    assert runs[0] == runs[1]


def test_conflict_dict_key_order_is_fixed() -> None:
    cs = build_changeset(BASE_FILES, all_scenarios()[0].side_a,
                         all_scenarios()[0].side_b)
    conflict = evaluate(cs).conflicts[0]
    d = conflict.to_dict() if hasattr(conflict, "to_dict") else None
    from semlock.engine.evidence import conflict_to_dict

    payload = d or conflict_to_dict(conflict)
    assert list(payload.keys()) == [
        "rule",
        "conflict_class",
        "changed_symbol_id",
        "changed_side",
        "consumer_ref_name",
        "consumer_ref_kind",
        "consumer_path",
        "consumer_span",
        "consumer_side",
        "target_id",
        "explanation",
        "evidence_a",
        "evidence_b",
    ]
    assert list(payload["evidence_a"].keys()) == ["path", "line", "col", "role"]


def test_claim_graph_export_independent_of_engine() -> None:
    """`semlock graph` consumable without running conflict evaluation."""
    files = (fx.models_main(ref=fx.MAIN), fx.app_consumer(ref=fx.MAIN))
    dump = claim_graph_to_json(build_claim_graph(files))
    payload = json.loads(dump)
    assert payload["ref"] == fx.MAIN
    assert {n["id"] for n in payload["nodes"]} >= {
        "pkg.models::User",
        "pkg.app::welcome",
    }
