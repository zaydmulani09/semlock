"""Resolution tests: correct id binding, ambiguity, external, explicit unresolved."""
from __future__ import annotations

import pytest

from semlock.extractors.typescript import TypeScriptExtractor, TypeScriptResolver
from semlock.ir.model import FileFacts

EX = TypeScriptExtractor()
RS = TypeScriptResolver()

PROVIDER = """
export interface Account {
  id: string;
  email: string;
}

export function find(id: string): Account | undefined {
  return undefined as Account | undefined;
}
"""

CONSUMER = """
import { Account, find } from "./provider";

export function label(account: Account): string {
  account.email = account.email.trim();
  return account.id + " " + String(find(account.id)?.email);
}
"""


def _resolve_pair(
    consumer_path: str, consumer_src: str, *extra: tuple[str, str]
) -> tuple[FileFacts, ...]:
    files = [
        EX.extract_file("src/ui/provider.ts", "main", PROVIDER),
        EX.extract_file(consumer_path, "main", consumer_src),
    ]
    for path, src in extra:
        files.append(EX.extract_file(path, "main", src))
    return RS.resolve(tuple(files))


def test_member_refs_bind_to_member_own_ids() -> None:
    resolved = _resolve_pair("src/ui/panel.ts", CONSUMER)
    panel = next(f for f in resolved if f.path == "src/ui/panel.ts")
    by_name = {r.name: r for r in panel.refs}
    assert (
        by_name["email"].resolution.target_id
        == "src/ui/provider::Account.email"
    )
    assert by_name["email"].resolution.status == "resolved"
    write_ref = next(r for r in panel.refs if r.kind == "write")
    assert write_ref.resolution.target_id == "src/ui/provider::Account.email"


def test_import_and_call_bind_to_canonical_symbol_ids() -> None:
    resolved = _resolve_pair("src/ui/panel.ts", CONSUMER)
    panel = next(f for f in resolved if f.path == "src/ui/panel.ts")
    by_name = {r.name: r for r in panel.refs}
    assert by_name["Account"].resolution.target_id == "src/ui/provider::Account"
    assert by_name["find"].resolution.target_id == "src/ui/provider::find"
    call = next(r for r in panel.refs if r.kind == "call" and r.name == "find")
    assert call.resolution.status == "resolved"


def test_unresolved_is_explicit_never_faked() -> None:
    lonely = EX.extract_file(
        "src/solo.ts", "main", 'import { Ghost } from "./nowhere";\nconst g = Ghost();'
    )
    (resolved,) = RS.resolve((lonely,))
    statuses = {r.name: r.resolution.status for r in resolved.refs}
    assert statuses["Ghost"] == "unresolved"
    assert all(r.resolution.target_id is None for r in resolved.refs)


def test_ambiguous_when_two_modules_export_same_name() -> None:
    left = 'export function helper(): number { return 1; }\n'
    right = 'export function helper(): string { return ""; }\n'
    consumer = (
        'import { helper } from "./left";\n'
        "export const useIt = () => helper();\n"
    )
    files = [
        EX.extract_file("src/a/left.ts", "main", left),
        EX.extract_file("src/b/right.ts", "main", right),
        EX.extract_file("src/c/consumer.ts", "main", consumer),
    ]
    (resolved_consumer,) = [
        f for f in RS.resolve(tuple(files)) if f.path.endswith("consumer.ts")
    ]
    call = next(r for r in resolved_consumer.refs if r.kind == "call")
    imp = next(r for r in resolved_consumer.refs if r.kind == "import")
    assert call.resolution.status == "ambiguous"
    assert imp.resolution.status == "ambiguous"
    assert call.resolution.target_id is None


def test_same_module_non_exported_call_resolves() -> None:
    src = (
        "function internal(n: number): number { return n; }\n"
        "export function outer(n: number): number { return internal(n); }\n"
    )
    (facts,) = RS.resolve((EX.extract_file("src/x/mod.ts", "main", src),))
    call = next(r for r in facts.refs if r.kind == "call" and r.name == "internal")
    assert call.resolution.target_id == "src/x/mod::internal"


def test_extends_and_implements_read_refs_resolve(facts_fixture: None = None) -> None:
    base_src = (
        "export class Base {\n  kind: string;\n}\n"
        "export interface Shape {\n  area(): number;\n}\n"
    )
    child_src = (
        'import { Base, Shape } from "./base";\n'
        "export class Impl extends Base implements Shape {\n"
        "  area(): number { return 0; }\n}\n"
    )
    files = [
        EX.extract_file("src/h/base.ts", "main", base_src),
        EX.extract_file("src/h/impl.ts", "main", child_src),
    ]
    resolved = RS.resolve(tuple(files))
    impl = next(f for f in resolved if f.path.endswith("impl.ts"))
    reads = {r.name: r for r in impl.refs if r.kind == "read"}
    assert reads["Base"].resolution.target_id == "src/h/base::Base"
    assert reads["Shape"].resolution.target_id == "src/h/base::Shape"
    impl_class = next(s for s in impl.symbols if s.id == "src/h/impl::Impl")
    assert impl_class.bases == ("Base", "Shape")


def test_resolver_preserves_everything_except_resolution_fields() -> None:
    files = (
        EX.extract_file("src/ui/provider.ts", "main", PROVIDER),
        EX.extract_file("src/ui/panel.ts", "main", CONSUMER),
    )
    resolved = RS.resolve(files)
    assert len(resolved) == len(files)
    for before, after in zip(files, resolved, strict=True):
        assert before.path == after.path
        assert before.ref == after.ref
        assert before.language == after.language
        assert before.format_version == after.format_version
        assert before.symbols == after.symbols
        assert [r.span for r in before.refs] == [r.span for r in after.refs]
        assert [r.name for r in before.refs] == [r.name for r in after.refs]
        assert [r.kind for r in before.refs] == [r.kind for r in after.refs]


@pytest.mark.parametrize(
    ("source", "forbidden"),
    [
        ('const x: Promise<string> = Promise.resolve("a");\n', "Promise"),
        ('console.log("hi");\n', "log"),
        ('export const n: number = Number("3");\n', "Number"),
    ],
)
def test_stdlib_surface_not_treated_as_dependency_edges(
    source: str, forbidden: str
) -> None:
    facts = EX.extract_file("src/g/g.ts", "main", source)
    assert forbidden not in {r.name for r in facts.refs}


def test_structural_typing_yields_honest_ambiguity() -> None:
    shape_src = (
        "export interface Shape {\n  area(): number;\n}\n"
        "export class Square implements Shape {\n  area(): number { return 1; }\n}\n"
    )
    user_src = (
        'import { Shape } from "./geo";\n'
        "export function total(s: Shape): number { return s.area(); }\n"
    )
    files = [
        EX.extract_file("src/m/geo.ts", "main", shape_src),
        EX.extract_file("src/m/use.ts", "main", user_src),
    ]
    use = next(f for f in RS.resolve(tuple(files)) if f.path.endswith("use.ts"))
    call = next(r for r in use.refs if r.kind == "call" and r.name == "area")
    assert call.resolution.status == "ambiguous"
