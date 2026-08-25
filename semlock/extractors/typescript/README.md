# TypeScript Extractor + Resolver (S3)

Status: Day-2 — wired to the FROZEN IR 0.2.0 (`Ref.module_specifier` /
`Ref.imported_name`, ratified `module_path::qualified_name` id grammar,
ADR-0008). Implements the same `Extractor` / `Resolver` ABCs as every other
language package so the engine consumes both identically.

## Layout

| File | Role |
|---|---|
| `extractor.py` | tree-sitter walk -> UNRESOLVED `FileFacts`; fixed id grammar; import/re-export evidence |
| `resolver.py` | specifier-directed binding -> fills `Resolution`; coverage metric |
| `_paths.py` | module-path canonicalization (ext strip, index collapse) |
| `queries/typescript.scm` | declarative spec mirror; compile-checked in CI |

## Fixed decisions implemented here

- Symbol id = `module_path::Qualified.Name` (e.g. `src/models/user::User.greet`;
  index files collapse: `src/api/index.ts` -> `src/api`). STABLE across refs.
- Member refs resolve to the MEMBER's own canonical symbol id
  (`src/models::Account.email`) — never a suffixed parent id. Interface/class
  fields AND methods are emitted both as `Member` entries on the owner (the
  field_removed diff surface) and as first-class symbols (kind `variable` /
  `method`) so refs bind by direct id join.
- Every extracted ref starts `unresolved`; only the resolver upgrades (INV-2).
- Deterministic: byte-identical serialized output across reruns/processes.

## The five spike questions (IR_CONTRACT.md §6)

### Q1 identity

Dotted-only ids are INSUFFICIENT for TypeScript. Counterexamples:
(1) directory names may contain dots (`src/v1.2/util.ts` -> dotted
`src.v1.2.util.f` is unparseable back into module vs symbol);
(2) `src/api/index.ts` collapsing to `src/api` collides with a hypothetical
`src.api` package namespace under dotting. The `::` grammar separates module
path from symbol path and fixes both. ADOPTED here; recommend 0.2.0 adopt it
and update mocks (`pkg.models.User.greet` -> `pkg/models::User.greet`).

### Q2 params

Keep kinds. TS maps cleanly: `rest_pattern` -> `varargs`; there is no TS
kwargs equivalent (destructured object parameters are skipped entirely, counted
as an honest extraction gap). TS `?: T` optional markers map to
`has_default=True` (omissible ~ default `undefined`), explicit `=` likewise.
Flagged signature deltas: add/remove/reorder/retype params, optionality flips,
return-type changes.

### Q3 returns

Declared-only is acceptable for TS v1. When unannotated we store `null`, never
an inference guess — invented types would poison determinism and the oracle
contract. Consequence: `return_changed` fires only when BOTH sides declare
types (annotation removal is invisible unless S4 compares null-vs-type as a
delta — recommended, cheap, honest).

### Q4 use-sites

Reliably produced per kind:
- `call`: bare-callee calls, `new` ctors, method calls through members;
- `import`: one ref per bound local name. 0.2.0 evidence on every import ref:
  `module_specifier` (source AS WRITTEN), `imported_name` = the ORIGINAL
  exported name for aliased imports, `"default"` for default imports (ES
  literally exports defaults under that name). Namespace imports use the
  contract-sanctioned producer encoding `name="<local>.*"`. Barrel files emit
  their re-export edges as import refs (`export {X} from "m"` ->
  `imported_name=X`; `export * from "m"` -> `name="*"`).
- `attribute`: property reads; `write`: assignment-target properties;
- `read`: type identifiers in annotations/heritage/generics, plus
  extends/implements heads (JS globals + lowercase primitives filtered out).
Nothing needs dropping; receiver-type evidence remains a known gap.

### Q5 resolution

Evidence rules (ref-wide over one changeset side):
- imports are SPECIFIER-DIRECTED: specifier -> module of this side (relative
  anchored on the importing file's directory, exact match, then tsconfig-style
  aliases — explicit `TypeScriptResolver(path_aliases={"@/*": "src/*"})`, or
  the built-in `@/` -> `src/` convention applied ONLY when the mapped module
  exists on the side); binding follows named re-export chains and `export *`
  sources transitively to the ORIGINAL symbol id (INV-7 chain);
- calls/reads consult their own file's resolved import bindings first (static
  scoping), then unique-name candidates;
- attribute/write bind to member symbols by direct id join;
- `resolved`: exactly ONE distinct candidate id under those rules;
  `ambiguous`: >= 2 (e.g. structural typing makes `Shape.area` vs
  `Square.area` genuinely ambiguous — marked, never guessed);
- `external`: bare specifiers (node_modules/builtins) and in-repo modules
  absent from this side (identical across branches by definition, so nothing
  is lost);
- namespace/star edges resolve MODULE-granular (`target_id` = bare
  `module_path`, ADR-0008 §3).

## Measured resolution coverage (fixtures committed under tests/fixtures/)

Re-measured AFTER wiring 0.2.0 specifier-directed binding (Day 2):

| Side | Refs | Resolved | Coverage | vs Day 1 |
|---|---|---|---|---|
| clean_pair/base | 2 | 2 | 100% | = |
| clean_pair/head | 7 | 5 | 71% | 43% -> 71% |
| signature_changed/base | 4 | 4 | 100% | = |
| signature_changed/head | 4 | 4 | 100% | = |
| removed_export/base | 7 | 7 | 100% | = |
| removed_export/head | 6 | 4 | 67% | 60% -> 67% |
| field_removed/base | 6 | 5 | 83% | = |
| field_removed/head | 6 | 2 | 33% | = |
| return_changed/base | 5 | 5 | 100% | = |
| return_changed/head | 5 | 5 | 100% | = |
| resolution_matrix/base (barrels, statics, generics, ns-import) | 19 | 15 | 79% | 71% -> 79% |
| **Healthy base sides aggregate** | **43** | **38** | **88.4%** | **84.6% -> 88.4%** |

Denominators grew honestly: barrel re-export/star edges are now first-class
refs and every import ref carries its module_specifier. The remaining gaps:

- builtin instance methods (`reduce`, `toUpperCase`) — unresolved by design
  (stdlib surface is not a SEMLock dependency edge candidate);
- structurally-typed member calls (`s.area()` on a `Shape` param) stay
  `ambiguous` when several owners declare the member — receiver-type evidence
  is not part of 0.2.0;
- post-break drops remain BY DESIGN: after `email` leaves `Account`, the
  consumer's `account.email` edges become explicitly unresolved instead of
  silently matching something else (INV-2 working as intended).

## Honesty-gate verdict (revised Day 2)

With 0.2.0's specifier + imported_name fields, TS binding is no longer fuzzy
name-matching: aliased/default/namespace imports, barrel chains, and star-only
members all bind deterministically to original ids. Healthy-side coverage rose
84.6% -> **88.4%**, and the residual ambiguity is concentrated exactly where
the IR legitimately lacks evidence (receiver types, stdlib instance methods).
Remaining ceiling for v1: receiver-typed member calls. If S1 ever wants >90%
on annotation-heavy real trees, the follow-up request would be an optional
`Ref.receiver_symbol_id` (post-freeze: ADR required). TypeScript stays
full-scope; no experimental downgrade needed.

## Limits (explicit, none hidden)

- No type inference anywhere; annotation-driven evidence only.
- Receiver-typed member calls (`u.greet()` where `u: User`) cannot use the
  annotation — `Ref` carries no receiver evidence in 0.2.0. Such refs bind
  only when the member name is unique on the side, else `ambiguous`.
- Default imports bind only when the target module's export surface is
  unambiguous (exactly one exported top-level symbol) — 0.2.0 has no
  default-export flag on `Symbol`; multi-export modules stay unresolved.
- Namespace-import member access (`fs.readFile`) is not linked to the
  namespace binding (no receiver field); the namespace ref itself binds at
  module granularity.
- A call of a locally-shadowed import name (local `const greet` shadowing an
  imported `greet` inside a function body) would follow the import binding;
  top-level shadowing is impossible in TS, function-local shadowing is a rare,
  documented conservative risk.
- tsconfig `paths` are honored through the explicit `path_aliases` constructor
  parameter (S5 config can wire the real tsconfig later); without it, only the
  built-in, existence-checked `@/` -> `src/` convention applies.
- Destructured object parameters, computed member access (`obj[key]`),
  decorators, and JSX-specific surfaces remain out of scope.
- Side-effect-only imports (`import "./polyfill"`) are not emitted.

## Consumable now

```python
from semlock.extractors.typescript import (
    TypeScriptExtractor,
    TypeScriptResolver,
    measure_resolution,   # Constitution §4 coverage metric
)
facts = TypeScriptExtractor().extract_file("src/x/y.ts", "main", source)
resolver = TypeScriptResolver(path_aliases={"@/*": "src/*"})  # optional
resolved = resolver.resolve((facts,))
```
