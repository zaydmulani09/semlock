"""S1-owned: IR JSON round-trip + determinism tests (INV-1, INV-5, INV-6)."""
from __future__ import annotations

import json

import pytest

from mocks import ir_fixtures as fx
from semlock.ir import serialize
from semlock.ir.model import FileFacts
from semlock.ir.version import FORMAT_VERSION


@pytest.mark.parametrize(
    "factory",
    [
        fx.canonical_example,
        fx.models_main,
        fx.app_consumer,
        fx.models_signature_changed,
        fx.models_field_removed,
        fx.models_return_changed,
        fx.models_export_removed,
        fx.models_new_method_added,
    ],
)
def test_round_trip_is_byte_identical(factory) -> None:
    facts = factory()
    once = serialize.to_json(facts)
    twice = serialize.to_json(serialize.from_json(once))
    assert once == twice


def test_canonical_example_matches_contract_doc() -> None:
    payload = json.loads(serialize.to_json(fx.canonical_example()))
    assert payload["format_version"] == FORMAT_VERSION == "0.1.0"
    assert payload["symbols"][0]["id"] == "pkg.models.User.greet"
    assert payload["symbols"][0]["signature"]["return_type"] == "str"
    assert payload["refs"][0]["resolution"] == {"status": "external", "target_id": None}


def test_determinism_same_input_same_bytes() -> None:
    a = serialize.to_json(fx.models_main())
    b = serialize.to_json(fx.models_main())
    assert a == b


def test_canonical_ordering_is_input_order_independent() -> None:
    base = fx.models_main()
    shuffled = FileFacts(
        format_version=base.format_version,
        path=base.path,
        language=base.language,
        ref=base.ref,
        symbols=tuple(reversed(base.symbols)),
        refs=tuple(reversed(base.refs)),
    )
    assert serialize.to_json(shuffled) == serialize.to_json(base)


def test_key_order_follows_schema_property_order() -> None:
    text = serialize.to_json(fx.canonical_example())
    top_keys = list(json.loads(text).keys())
    assert top_keys == [
        "format_version",
        "path",
        "language",
        "ref",
        "symbols",
        "refs",
    ]


def test_version_gate_refuses_unknown_format() -> None:
    text = serialize.to_json(fx.canonical_example()).replace(
        '"format_version": "0.1.0"', '"format_version": "9.9.9"'
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_irreversible_mutations_are_blocked_by_frozen_model() -> None:
    facts = fx.canonical_example()
    with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError on 3.10+
        facts.ref = "other"  # type: ignore[misc]
