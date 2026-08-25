"""S1-owned: schema-validation tests — the validator must reject malformed IR."""
from __future__ import annotations

import pytest

from mocks import ir_fixtures as fx
from semlock.ir import serialize
from semlock.ir.version import FORMAT_VERSION


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
        fx.ts_consumer_aliased,
        fx.models_signature_changed,
        fx.models_field_removed,
        fx.models_return_changed,
        fx.models_export_removed,
        fx.models_new_method_added,
    ):
        # to_json validates before serializing; failure raises SerializationError.
        assert serialize.to_json(name())


# ------------------------------------------------------- 0.2.0 grammar & evidence


def test_rejects_second_double_colon_in_symbol_id() -> None:
    text = mutated(
        serialize.to_json(fx.canonical_example()),
        '"id": "pkg.models::User.greet"',
        '"id": "pkg::models::User.greet"',
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_rejects_dotted_id_without_module_separator() -> None:
    text = mutated(
        serialize.to_json(fx.canonical_example()),
        '"id": "pkg.models::User.greet"',
        '"id": "pkg.models.User.greet"',
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)


def test_bare_module_path_is_valid_target_id() -> None:
    """Module-granular deps (plain `import a.b`) use bare module_path (no '::')."""
    import json

    from semlock.ir.model import FileFacts, Ref, Resolution, Span

    facts = FileFacts(
        format_version=FORMAT_VERSION,
        path="a.py",
        language="python",
        ref="main",
        refs=(
            Ref(
                name="osp~os.path",
                kind="import",
                span=Span(1, 0, 1, 14),
                resolution=Resolution(status="resolved", target_id="os.path"),
            ),
        ),
    )
    payload = json.loads(serialize.to_json(facts))
    assert payload["refs"][0]["resolution"]["target_id"] == "os.path"
    assert serialize.from_json(serialize.to_json(facts)) == facts


def test_imported_name_requires_module_specifier() -> None:
    from semlock.ir.model import Ref, Span

    with pytest.raises(ValueError):
        Ref(
            name="U",
            kind="import",
            span=Span(1, 7, 1, 8),
            imported_name="User",
            module_specifier=None,
        )
    text = mutated(
        serialize.to_json(fx.ts_consumer_aliased()),
        '"imported_name": "User"',
        '"imported_name": "User", "module_specifier_x": null',
    )
    text = text.replace(
        '"module_specifier": "./models/user"', '"module_specifier": null', 1
    )
    with pytest.raises(serialize.SerializationError):
        serialize.from_json(text)
