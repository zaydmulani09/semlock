"""Fixture-pair tests: one scenario dir per conflict class under
tests/fixtures/python/{conflict,clean}/.

Each scenario provides:
  main__pkg_models.py — the shared surface both branches start from
  a__pkg_models.py    — branch A's version of the same module path
  b__app.py           — branch B's consumer

Sides are resolved INDEPENDENTLY (as the engine will see them): B's side =
main-surface models + consumer; A's side = A's models. Physical file names are
storage only; each is extracted under its canonical worktree path.
"""

from __future__ import annotations

import pathlib

import pytest

from semlock.extractors.python import PythonExtractor  # noqa: F401 (registers)
from semlock.extractors.python.resolver import PythonResolver, resolution_coverage
from semlock.ir.model import FileFacts, Ref, Symbol

FIXTURES = pathlib.Path(__file__).parents[2] / "fixtures" / "python"
EX = PythonExtractor()
RESOLVE = PythonResolver()

SCENARIOS = ["signature_changed", "removed_export", "field_removed", "return_changed"]


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _b_side(scenario_dir: pathlib.Path) -> tuple[FileFacts, ...]:
    """Branch B's full view: old surface + its consumers."""
    facts = [
        EX.extract_file(
            "pkg/models.py", "feat/b", _read(scenario_dir / "main__pkg_models.py")
        ),
        EX.extract_file("pkg/app.py", "feat/b", _read(scenario_dir / "b__app.py")),
    ]
    return RESOLVE.resolve(tuple(facts))


def _a_side(scenario_dir: pathlib.Path) -> tuple[FileFacts, ...]:
    """Branch A's full view of the changed module."""
    facts = EX.extract_file(
        "pkg/models.py", "feat/a", _read(scenario_dir / "a__pkg_models.py")
    )
    return RESOLVE.resolve((facts,))


def _symbol_by_id(files: tuple[FileFacts, ...], sym_id: str) -> Symbol | None:
    for f in files:
        for s in f.symbols:
            if s.id == sym_id:
                return s
    return None


def _ref(files: tuple[FileFacts, ...], path: str, kind: str, name: str) -> Ref:
    for f in files:
        if f.path == path:
            for r in f.refs:
                if r.kind == kind and r.name == name:
                    return r
    raise AssertionError(f"missing ref {path} {kind} {name}")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_consumer_edges_resolve_on_b_side(scenario: str) -> None:
    """INV-2 gate for fixtures: B's dependency edges must be resolved, else the
    engine could never fire on them (and tests would be vacuous)."""
    files = _b_side(FIXTURES / "conflict" / scenario)
    cov = resolution_coverage(files)
    assert cov.resolved >= 2, f"{scenario}: expected resolved dependency edges"


def test_signature_changed_conflict_precondition() -> None:
    b = _b_side(FIXTURES / "conflict" / "signature_changed")
    a = _a_side(FIXTURES / "conflict" / "signature_changed")
    call = _ref(b, "pkg/app.py", "call", "user.greet")
    assert call.resolution.status == "resolved"
    assert call.resolution.target_id == "pkg.models::User.greet"
    old = _symbol_by_id(b, "pkg.models::User.greet")
    new = _symbol_by_id(a, "pkg.models::User.greet")
    assert old is not None and new is not None
    old_names = [p.name for p in old.signature.params]
    new_names = [p.name for p in new.signature.params]
    assert old_names != new_names  # param renamed: kw-callers break


def test_signature_changed_clean_is_compatible() -> None:
    b = _b_side(FIXTURES / "clean" / "signature_changed")
    a = _a_side(FIXTURES / "clean" / "signature_changed")
    call = _ref(b, "pkg/app.py", "call", "user.greet")
    assert call.resolution.status == "resolved"
    old = _symbol_by_id(b, "pkg.models::User.greet")
    new = _symbol_by_id(a, "pkg.models::User.greet")
    old_params = old.signature.params
    new_params = new.signature.params
    assert len(new_params) >= len(old_params)
    for o, n in zip(old_params, new_params, strict=False):
        assert (o.name, o.kind) == (n.name, n.kind)
    added = new_params[len(old_params) :]
    assert all(p.has_default for p in added)  # compatible additions only


def test_removed_export_conflict_precondition() -> None:
    b = _b_side(FIXTURES / "conflict" / "removed_export")
    a = _a_side(FIXTURES / "conflict" / "removed_export")
    imp = _ref(b, "pkg/app.py", "import", "format_greeting=pkg.models.format_greeting")
    assert imp.resolution.status == "resolved"
    assert imp.resolution.target_id == "pkg.models::format_greeting"
    call = _ref(b, "pkg/app.py", "call", "format_greeting")
    assert call.resolution.target_id == "pkg.models::format_greeting"
    assert _symbol_by_id(a, "pkg.models::format_greeting") is None


def test_removed_export_clean_keeps_surface() -> None:
    a = _a_side(FIXTURES / "clean" / "removed_export")
    assert _symbol_by_id(a, "pkg.models::format_greeting") is not None
    assert _symbol_by_id(a, "pkg.models::shout") is not None


def test_field_removed_conflict_precondition() -> None:
    b = _b_side(FIXTURES / "conflict" / "field_removed")
    a = _a_side(FIXTURES / "conflict" / "field_removed")
    load = _ref(b, "pkg/app.py", "attribute", "user.email")
    store = _ref(b, "pkg/app.py", "write", "user.email")
    assert load.resolution.status == "resolved"
    assert load.resolution.target_id == "pkg.models::User.email"
    assert store.resolution.status == "resolved"
    assert store.resolution.target_id == "pkg.models::User.email"
    user_head = _symbol_by_id(a, "pkg.models::User")
    assert user_head is not None
    assert "email" not in {m.name for m in user_head.members}


def test_field_removed_clean_adds_field_only() -> None:
    b = _b_side(FIXTURES / "clean" / "field_removed")
    a = _a_side(FIXTURES / "clean" / "field_removed")
    load = _ref(b, "pkg/app.py", "attribute", "user.email")
    assert load.resolution.target_id == "pkg.models::User.email"
    user_head = _symbol_by_id(a, "pkg.models::User")
    assert {"email", "phone"} <= {m.name for m in user_head.members}


def test_return_changed_conflict_precondition() -> None:
    b = _b_side(FIXTURES / "conflict" / "return_changed")
    a = _a_side(FIXTURES / "conflict" / "return_changed")
    call = _ref(b, "pkg/app.py", "call", "user.greet")
    assert call.resolution.status == "resolved"
    assert call.resolution.target_id == "pkg.models::User.greet"
    old = _symbol_by_id(b, "pkg.models::User.greet")
    new = _symbol_by_id(a, "pkg.models::User.greet")
    assert old.signature.return_type == "str"
    assert new.signature.return_type == "GreetingResult"


def test_return_changed_clean_keeps_declared_return() -> None:
    b = _b_side(FIXTURES / "clean" / "return_changed")
    a = _a_side(FIXTURES / "clean" / "return_changed")
    call = _ref(b, "pkg/app.py", "call", "user.greet")
    assert call.resolution.target_id == "pkg.models::User.greet"
    old = _symbol_by_id(b, "pkg.models::User.greet")
    new = _symbol_by_id(a, "pkg.models::User.greet")
    assert old.signature.return_type == new.signature.return_type == "str"
