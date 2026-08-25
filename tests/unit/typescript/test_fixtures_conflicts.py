"""Fixture-pair tests: one per conflict class + clean pair + coverage report.

These assert the exact fact-level preconditions S4's engine consumes:
provider-side deltas joined to consumer-side refs RESOLVED to stable ids.
"""
from __future__ import annotations

import json
import sys

from conftest import (
    FIXTURES,
    REPO_ROOT,
    extract_side,
    measure_resolution,
    resolve_fixture,
    symbol_map,
)

from semlock.extractors.typescript import TypeScriptResolver


class TestSignatureChanged:
    def test_consumer_call_resolves_to_provider_id_both_sides(self) -> None:
        base = resolve_fixture("conflict/signature_changed", "base")
        head = resolve_fixture("conflict/signature_changed", "head")
        target = "src/models/user::formatGreeting"
        for side in (base, head):
            main = next(f for f in side if f.path.endswith("app/main.ts"))
            call = next(
                r for r in main.refs if r.kind == "call" and r.name == "formatGreeting"
            )
            assert call.resolution.status == "resolved"
            assert call.resolution.target_id == target

    def test_signature_delta_is_visible_across_sides(self) -> None:
        base = symbol_map(resolve_fixture("conflict/signature_changed", "base"))
        head = symbol_map(resolve_fixture("conflict/signature_changed", "head"))
        assert base["src/models/user::formatGreeting"].signature is not None
        assert head["src/models/user::formatGreeting"].signature is not None
        assert (
            len(base["src/models/user::formatGreeting"].signature.params)
            != len(head["src/models/user::formatGreeting"].signature.params)
        )


class TestRemovedExport:
    @staticmethod
    def _import_ref(files, name="fetchProfile"):
        widget = next(f for f in files if f.path.endswith("client/widget.ts"))
        return next(
            r for r in widget.refs if r.kind == "import" and r.name == name
        )

    def test_base_side_import_resolves_through_barrel(self) -> None:
        base = resolve_fixture("conflict/removed_export", "base")
        imp = self._import_ref(base)
        assert imp.resolution.target_id == "src/api/profile::fetchProfile"

    def test_head_side_symbol_gone_and_ref_explicitly_unresolved(self) -> None:
        head = resolve_fixture("conflict/removed_export", "head")
        ids = set(symbol_map(head))
        assert "src/api/profile::fetchProfile" not in ids
        imp = self._import_ref(head)
        assert imp.resolution.status == "unresolved"
        assert imp.resolution.target_id is None

    def test_s4_precondition_base_target_missing_from_head(self) -> None:
        base = resolve_fixture("conflict/removed_export", "base")
        head = resolve_fixture("conflict/removed_export", "head")
        targets = {
            r.resolution.target_id
            for r in next(
                f for f in base if f.path.endswith("client/widget.ts")
            ).refs
            if r.resolution.status == "resolved"
        }
        assert targets & set(symbol_map(base))
        missing = targets - set(symbol_map(head))
        assert {"src/api/profile::fetchProfile"} <= missing


class TestFieldRemoved:
    def test_field_reads_writes_resolve_to_member_own_id_on_base(self) -> None:
        base = resolve_fixture("conflict/field_removed", "base")
        form = next(f for f in base if f.path.endswith("forms/account_form.ts"))
        member_refs = [
            r
            for r in form.refs
            if r.name == "email" and r.kind in ("attribute", "write")
        ]
        assert len(member_refs) >= 2
        assert all(
            r.resolution.target_id == "src/entities/user::Account.email"
            for r in member_refs
        )

    def test_head_side_field_absent_from_members_and_symbols(self) -> None:
        head = symbol_map(resolve_fixture("conflict/field_removed", "head"))
        account = head["src/entities/user::Account"]
        assert [m.name for m in account.members] == ["id"]
        assert "src/entities/user::Account.email" not in head


class TestReturnChanged:
    def test_return_type_delta_on_shared_canonical_id(self) -> None:
        base = symbol_map(resolve_fixture("conflict/return_changed", "base"))
        head = symbol_map(resolve_fixture("conflict/return_changed", "head"))
        assert base["src/payments/processor::charge"].signature.return_type == "Receipt"
        assert (
            head["src/payments/processor::charge"].signature.return_type
            == "Promise<Receipt>"
        )
        receipt = next(
            f
            for f in resolve_fixture("conflict/return_changed", "base")
            if f.path.endswith("reporting/receipt.ts")
        )
        call = next(r for r in receipt.refs if r.name == "charge" and r.kind == "call")
        assert call.resolution.target_id == "src/payments/processor::charge"


class TestCleanPair:
    def test_no_consumer_facing_surface_breaks(self) -> None:
        base = resolve_fixture("clean/clean_pair", "base")
        head = resolve_fixture("clean/clean_pair", "head")
        base_ids = symbol_map(base)
        head_ids = symbol_map(head)
        shared_targets = {
            r.resolution.target_id
            for f in base
            for r in f.refs
            if r.resolution.status == "resolved"
        }
        for target in shared_targets:
            assert target in head_ids
            assert head_ids[target].exports == base_ids[target].exports
            assert head_ids[target].signature == base_ids[target].signature


def test_resolution_coverage_reported_for_all_fixtures() -> None:
    sides = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in FIXTURES.rglob("base")
        if p.is_dir()
    ) + sorted(
        str(p.relative_to(REPO_ROOT))
        for p in FIXTURES.rglob("head")
        if p.is_dir()
    )
    assert sides
    report: dict[str, object] = {}
    for side in sides:
        facts = TypeScriptResolver().resolve(extract_side(FIXTURES / side))
        report[side] = measure_resolution(facts)
    print(json.dumps(report, indent=2), file=sys.stderr)
    for payload in report.values():
        by_kind = payload["by_kind"]
        counts = [sum(c.values()) for c in by_kind.values()]
        assert sum(counts) == payload["refs"]
        for kind_counts in by_kind.values():
            allowed = {"resolved", "external", "ambiguous", "unresolved"}
            assert set(kind_counts) <= allowed
        coverage = payload["coverage"]
        assert 0.0 <= coverage <= 1.0


def test_query_spec_compiles_against_grammar() -> None:
    import tree_sitter_typescript
    from tree_sitter import Language, Parser, Query, QueryCursor

    scm_path = (
        REPO_ROOT
        / "semlock" / "extractors" / "typescript" / "queries" / "typescript.scm"
    )
    scm = scm_path.read_text(encoding="utf-8")
    lang = Language(tree_sitter_typescript.language_typescript())
    cursor = QueryCursor(Query(lang, scm))
    src = "export function hi(): void {}\nexport class A { b(): void {} }\n"
    tree = Parser(lang).parse(src.encode())
    captures = cursor.captures(tree.root_node)
    assert {"function.def", "method.def"} <= set(captures)
