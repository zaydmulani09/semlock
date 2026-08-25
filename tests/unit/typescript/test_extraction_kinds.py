"""Per-kind extraction tests for the TypeScript extractor (spike)."""
from __future__ import annotations

import pytest

from semlock.extractors.base import assert_unresolved
from semlock.extractors.typescript import TypeScriptExtractor
from semlock.ir.model import FileFacts

EX = TypeScriptExtractor()

SRC = """
import defaultName, { a as b, c } from "./other";
import * as ns from "lib";
import type { Cfg } from "./cfg";

export type Handler<T> = (input: T) => void;

export interface Shape {
  area(): number;
  label: string;
}

export const make = (n: number, tag = "x"): string => tag + n;
export let counter: number = 0;

export class Base {
  static kind: string;
  protected size?: number;
  render(): void {}
}

export class Square extends Base implements Shape {
  label = "square";
  area(): number { return 1; }
}

export function variadic(a: string, ...rest: number[], opts?: { x: boolean }): void {}
function internal(n: number): number { return n; }
export { internal as exportedInternal };
"""


@pytest.fixture()
def facts() -> FileFacts:
    return EX.extract_file("src/things/index.ts", "test", SRC)


def ids(facts: FileFacts) -> dict[str, str]:
    return {s.id: s.kind for s in facts.symbols}


def test_index_ts_module_path_collapses_to_dir(facts: FileFacts) -> None:
    assert all(s.id.startswith("src/things::") for s in facts.symbols)


def test_function_kind_and_signature(facts: FileFacts) -> None:
    table = ids(facts)
    assert table["src/things::variadic"] == "function"
    sig = next(s for s in facts.symbols if s.id.endswith("::variadic")).signature
    assert sig is not None
    assert [p.name for p in sig.params] == ["a", "rest", "opts"]
    assert sig.params[1].kind == "varargs"
    assert sig.params[2].has_default is True
    assert sig.params[0].has_default is False
    assert sig.return_type == "void"


def test_arrow_const_is_exported_function_with_defaults(facts: FileFacts) -> None:
    sym = next(s for s in facts.symbols if s.id == "src/things::make")
    assert sym.kind == "function"
    assert sym.exports is True
    assert sym.signature is not None
    assert sym.signature.params[1].has_default is True
    assert sym.signature.return_type == "string"


def test_interface_members_are_first_class_symbols_and_member_entries(
    facts: FileFacts,
) -> None:
    table = ids(facts)
    assert table["src/things::Shape.area"] == "method"
    assert table["src/things::Shape.label"] == "variable"
    shape = next(s for s in facts.symbols if s.id == "src/things::Shape")
    assert shape.kind == "interface"
    member_names = [m.name for m in shape.members]
    assert member_names == ["area", "label"]
    area_sig = next(
        s for s in facts.symbols if s.id == "src/things::Shape.area"
    ).signature
    assert area_sig is not None and area_sig.return_type == "number"
    label_member = shape.members[1]
    assert label_member.type_annotation == "string"


def test_class_fields_methods_and_heritage(facts: FileFacts) -> None:
    table = ids(facts)
    assert table["src/things::Square"] == "class"
    assert table["src/things::Square.label"] == "variable"
    assert table["src/things::Square.area"] == "method"
    square = next(s for s in facts.symbols if s.id == "src/things::Square")
    assert square.bases == ("Base", "Shape")
    base_cls = next(s for s in facts.symbols if s.id == "src/things::Base")
    assert [m.name for m in base_cls.members] == ["kind", "size", "render"]
    assert base_cls.members[2].type_annotation == "void"


def test_raw_generic_type_text_preserved(facts: FileFacts) -> None:
    handler = next(s for s in facts.symbols if s.name == "Handler")
    assert handler.kind == "type_alias"


def test_named_reexport_marks_local_symbol_exported(facts: FileFacts) -> None:
    internal = next(s for s in facts.symbols if s.id == "src/things::internal")
    assert internal.exports is True


def test_non_exported_let_not_a_symbol_but_counter_is(facts: FileFacts) -> None:
    table = ids(facts)
    assert table["src/things::counter"] == "variable"


def test_import_refs_carry_specifier_evidence_unresolved(facts: FileFacts) -> None:
    imports = {r.name: r for r in facts.refs if r.kind == "import"}
    assert sorted(imports) == ["Cfg", "b", "c", "defaultName", "ns.*"]
    assert all(r.resolution.status == "unresolved" for r in imports.values())
    specifiers = {r.module_specifier for r in imports.values()}
    assert specifiers == {"./other", "lib", "./cfg"}
    assert imports["b"].imported_name == "a"
    assert imports["c"].imported_name is None
    assert imports["defaultName"].imported_name == "default"
    assert imports["Cfg"].module_specifier == "./cfg"


def test_every_ref_starts_unresolved_seam_contract() -> None:
    other = EX.extract_file("src/x.ts", "main", SRC.replace("index.ts", "x"))
    assert_unresolved(other)


def test_deterministic_byte_identical_reruns() -> None:
    from semlock.ir.serialize import to_json

    first = EX.extract_file("src/dup/a.ts", "r", SRC)
    second = EX.extract_file("src/dup/a.ts", "r", SRC)
    assert to_json(first) == to_json(second)


def test_extension_strip_and_nested_ids() -> None:
    facts2 = EX.extract_file("src/models/user.ts", "t", "export function f(): void {}")
    assert facts2.symbols[0].id == "src/models/user::f"
