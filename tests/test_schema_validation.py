"""S1-owned: schema-validation tests — the validator must reject malformed IR."""
from __future__ import annotations

import pytest

from mocks import ir_fixtures as fx
from semlock.ir import serialize


def mutated(base: str, old: str, new: str) -> str:
    assert old in base, f"mutation target not found: {old!r}"
    return base.replace(old, new, 1)


def test_rejects_missing_required_field() -> None:
    text = mutated(
        serialize.to_json(fx.canonical_example()), '"ref": "main",', ""
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_rejects_unknown_symbol_kind() -> None:
    text = mutated(
        serialize.to_json(fx.canonical_example()),
        '"kind": "method"',
        '"kind": "macro"',
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_rejects_resolved_without_target_id() -> None:
    text = mutated(
        serialize.to_json(fx.canonical_example()),
        '"status": "external"',
        '"status": "resolved"',
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_rejects_target_on_unresolved() -> None:
    text = serialize.to_json(fx.canonical_example())
    text = text.replace('"status": "external"', '"status": "unresolved"', 1)
    text = text.replace('"target_id": null', '"target_id": "pkg.x"', 1)
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_rejects_unknown_language() -> None:
    text = mutated(
        serialize.to_json(fx.canonical_example()),
        '"language": "python"',
        '"language": "rust"',
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_rejects_backslash_path() -> None:
    text = mutated(
        serialize.to_json(fx.canonical_example()),
        'pkg/models.py',
        'pkg\\models.py',
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_rejects_zero_indexed_line() -> None:
    text = mutated(
        serialize.to_json(fx.canonical_example()),
        '"start_line": 2,',
        '"start_line": 0,',
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_rejects_unknown_property() -> None:
    text = mutated(
        serialize.to_json(fx.canonical_example()),
        '"ref": "main",',
        '"ref": "main", "extra": 1,',
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_model_enforces_resolution_invariants() -> None:
    from semlock.ir.model import Resolution

    with pytest.raises(ValueError):
        Resolution(status="resolved")
    with pytest.raises(ValueError):
        Resolution(status="unresolved", target_id="pkg.x")


def test_all_mocks_validate() -> None:
    for name in (
        fx.canonical_example,
        fx.models_main,
        fx.app_consumer,
        fx.models_signature_changed,
        fx.models_field_removed,
        fx.models_return_changed,
        fx.models_export_removed,
        fx.models_new_method_added,
    ):
        # to_json validates before serializing; failure raises SerializationError.
        assert serialize.to_json(name())
