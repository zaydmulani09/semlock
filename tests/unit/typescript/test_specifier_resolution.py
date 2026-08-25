"""0.2.0 specifier-directed binding tests (module_specifier / imported_name)."""
from __future__ import annotations

from semlock.extractors.typescript import TypeScriptExtractor, TypeScriptResolver

EX = TypeScriptExtractor()


def _resolve(*modules: tuple[str, str], aliases: dict[str, str] | None = None):
    files = tuple(EX.extract_file(p, "main", s) for p, s in modules)
    return TypeScriptResolver(path_aliases=aliases).resolve(files)


def pick(files, suffix):
    return next(f for f in files if f.path.endswith(suffix))


def test_aliased_import_binds_via_imported_name() -> None:
    provider = 'export function useState(): number { return 0; }\n'
    consumer = (
        'import { useState as useSt } from "./prov";\n'
        "export const n: number = useSt();\n"
    )
    resolved = _resolve(
        ("src/ui/prov.ts", provider),
        ("src/ui/panel.ts", consumer),
    )
    panel = pick(resolved, "panel.ts")
    imp = next(r for r in panel.refs if r.kind == "import" and r.name == "useSt")
    assert imp.imported_name == "useState"
    assert imp.resolution.status == "resolved"
    assert imp.resolution.target_id == "src/ui/prov::useState"


def test_named_reexport_chain_follows_to_original_id() -> None:
    inner = 'export function ping(): string { return "p"; }\n'
    barrel = 'export { ping } from "./inner";\n'
    consumer = 'import { ping } from "../lib/barrel";\nexport const p = () => ping();\n'
    resolved = _resolve(
        ("src/lib/inner.ts", inner),
        ("src/lib/barrel.ts", barrel),
        ("src/app/main.ts", consumer),
    )
    main = pick(resolved, "app/main.ts")
    imp = next(r for r in main.refs if r.name == "ping" and r.kind == "import")
    assert imp.resolution.target_id == "src/lib/inner::ping"
    call = next(r for r in main.refs if r.name == "ping" and r.kind == "call")
    assert call.resolution.target_id == "src/lib/inner::ping"


def test_star_only_barrel_member_resolves_to_original_id() -> None:
    inner = 'export const SCALE: number = 2;\n'
    barrel = 'export * from "./inner";\n'
    consumer = 'import { SCALE } from "../lib";\nexport const n = SCALE;\n'
    resolved = _resolve(
        ("src/lib/inner.ts", inner),
        ("src/lib/index.ts", barrel),
        ("src/app/main.ts", consumer),
    )
    main = pick(resolved, "app/main.ts")
    imp = next(r for r in main.refs if r.name == "SCALE" and r.kind == "import")
    assert imp.resolution.target_id == "src/lib/inner::SCALE"


def test_star_edge_itself_binds_module_granular() -> None:
    inner = 'export const SCALE: number = 2;\n'
    barrel = 'export * from "./inner";\n'
    resolved = _resolve(
        ("src/lib/inner.ts", inner),
        ("src/lib/index.ts", barrel),
    )
    index = pick(resolved, "index.ts")
    star = next(r for r in index.refs if r.name == "*")
    assert star.resolution.status == "resolved"
    assert star.resolution.target_id == "src/lib/inner"
    assert "::" not in star.resolution.target_id


def test_namespace_import_binds_module_granular() -> None:
    util = 'export function readFile(): string { return ""; }\n'
    consumer = 'import * as fs from "./util";\nexport const s = fs.readFile();\n'
    resolved = _resolve(
        ("src/x/util.ts", util),
        ("src/x/use.ts", consumer),
    )
    use = pick(resolved, "use.ts")
    ns = next(r for r in use.refs if r.kind == "import")
    assert ns.name == "fs.*"
    assert ns.resolution.status == "resolved"
    assert ns.resolution.target_id == "src/x/util"


def test_bare_specifier_is_external() -> None:
    consumer = 'import { Component } from "react";\nexport type C = Component;\n'
    files = (EX.extract_file("src/a.ts", "main", consumer),)
    (resolved,) = TypeScriptResolver().resolve(files)
    imp = next(r for r in resolved.refs if r.kind == "import")
    assert imp.resolution.status == "external"
    assert imp.resolution.target_id is None


def test_relative_module_outside_side_is_external() -> None:
    consumer = 'import { X } from "../shared/x";\nexport type Y = X;\n'
    files = (EX.extract_file("src/app/a.ts", "main", consumer),)
    (resolved,) = TypeScriptResolver().resolve(files)
    imp = next(r for r in resolved.refs if r.kind == "import")
    assert imp.resolution.status == "external"


def test_default_import_binds_only_when_export_surface_unambiguous() -> None:
    single = 'export default function boot(): void {}\n'
    multi = 'export default function boot(): void {}\nexport const also: number = 1;\n'
    consume_single = 'import boot from "./single";\nboot();\n'
    consume_multi = 'import boot from "./multi";\nboot();\n'

    ok = _resolve(("src/m/single.ts", single), ("src/m/main.ts", consume_single))
    imp = next(r for r in pick(ok, "main.ts").refs if r.kind == "import")
    assert imp.imported_name == "default"
    assert imp.resolution.target_id == "src/m/single::boot"

    hard = _resolve(("src/m/multi.ts", multi), ("src/m/main.ts", consume_multi))
    imp2 = next(r for r in pick(hard, "main.ts").refs if r.kind == "import")
    assert imp2.resolution.status == "unresolved"


def test_builtin_alias_convention_and_explicit_path_aliases() -> None:
    helper = 'export function helper(): number { return 1; }\n'
    consumer = 'import { helper } from "@/lib/helper";\nexport const n = helper();\n'
    feature = 'export function widget(): string { return ""; }\n'
    feature_use = (
        'import { widget } from "~/features/widget";\n'
        "export const w = widget();\n"
    )

    builtin = _resolve(
        ("src/lib/helper.ts", helper), ("src/app/m.ts", consumer)
    )
    imp = next(r for r in pick(builtin, "m.ts").refs if r.kind == "import")
    assert imp.resolution.target_id == "src/lib/helper::helper"

    custom = _resolve(
        ("src/lib/helper.ts", helper),
        ("src/app/m.ts", consumer),
        ("src/features/widget.ts", feature),
        ("src/ui/u.ts", feature_use),
        aliases={"~/*": "src/*"},
    )
    imp2 = next(r for r in pick(custom, "u.ts").refs if r.kind == "import")
    assert imp2.resolution.target_id == "src/features/widget::widget"


def test_resolver_preserves_specifier_evidence_fields() -> None:
    src = 'import { X as Y } from "./p";\nexport const v = Y();\n'
    provider = 'export function X(): number { return 0; }\n'
    files = (
        EX.extract_file("src/z/p.ts", "main", provider),
        EX.extract_file("src/z/c.ts", "main", src),
    )
    resolved = TypeScriptResolver().resolve(files)
    for before, after in zip(files, resolved, strict=True):
        for rb, ra in zip(before.refs, after.refs, strict=True):
            assert rb.module_specifier == ra.module_specifier
            assert rb.imported_name == ra.imported_name


def test_broken_barrel_import_stays_explicitly_unresolved() -> None:
    """INV-2 guard: a name missing from the barrel's chains must NOT fall back
    to a module-granular or fuzzy match."""
    inner = 'export function keep(): number { return 1; }\n'
    barrel = 'export { keep } from "./inner";\n'
    consumer = 'import { dropped } from "../lib/barrel";\ndropped();\n'
    resolved = _resolve(
        ("src/lib/inner.ts", inner),
        ("src/lib/barrel.ts", barrel),
        ("src/app/main.ts", consumer),
    )
    main = pick(resolved, "app/main.ts")
    imp = next(r for r in main.refs if r.kind == "import")
    assert imp.resolution.status == "unresolved"
    call = next(r for r in main.refs if r.name == "dropped" and r.kind == "call")
    assert call.resolution.status == "unresolved"
