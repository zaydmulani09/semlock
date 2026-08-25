# TypeScript Extractor + Resolver — Spike Report (S3, Day 1)

Status: SPIKE QUALITY, deliberately unpolished pending the 0.2.0 IR freeze.
Consumes S1's provisional IR (FORMAT_VERSION 0.1.0) verbatim. Implements the
same `Extractor` / `Resolver` ABCs as every other language package
(`semlock/extractors/base.py`) so the engine consumes both identically.

## Layout

| File | Role |
|---|---|
| `extractor.py` | tree-sitter walk -> UNRESOLVED `FileFacts`; fixed id grammar |
| `resolver.py` | ref-wide binding -> fills `Resolution`; coverage metric |
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
- `import`: one ref per bound local name (+ original-name companion ref when
  the import is aliased — dual-ref convention, documented in tests);
- `attribute`: property reads; `write`: assignment-target properties;
- `read`: type identifiers in annotations/heritage/generics, plus
  extends/implements heads (JS globals + lowercase primitives filtered out).
Nothing needs dropping. Needed ADDITIONS to make imports/aliases/resolvers
static: `Ref.module_specifier`, `Ref.imported_name` (see issue #3).

### Q5 resolution

Evidence rules (ref-wide over one changeset side):
- `resolved`: exactly ONE distinct candidate symbol id matches under the kind's
  candidate set — imports bind against exported top-level names, calls against
  top-level + member names, reads against top-level names, attribute/write
  against member names (direct join to member ids);
- `ambiguous`: >= 2 distinct candidates (e.g. structural typing makes
  `Shape.area` vs `Square.area` genuinely ambiguous — marked, never guessed);
- `external`: well-known JS/TS globals (filtered mostly at extraction);
- `unresolved`: zero candidates, aliased/default imports whose local name
  differs from the original, member calls whose receiver type is lost.
Ambiguity is made rare by specifier-directed lookup + receiver evidence —
i.e., by issue #3's fields, not by heuristics.

## Measured resolution coverage (fixtures committed under tests/fixtures/)

Raw counts over all 11 fixture sides (base sides are healthy code; head sides
of conflict scenarios contain the intentional break, which legitimately lowers
their numbers):

| Side | Refs | Resolved | Coverage |
|---|---|---|---|
| clean_pair/base | 2 | 2 | 100% |
| clean_pair/head | 7 | 3 | 43% |
| signature_changed/base | 4 | 4 | 100% |
| signature_changed/head | 4 | 4 | 100% |
| removed_export/base | 5 | 5 | 100% |
| removed_export/head | 5 | 3 | 60% |
| field_removed/base | 6 | 5 | 83% |
| field_removed/head | 6 | 2 | 33% |
| return_changed/base | 5 | 5 | 100% |
| return_changed/head | 5 | 5 | 100% |
| resolution_matrix/base (barrels, statics, generics, ns-import) | 17 | 12 | 71% |
| **Healthy base sides aggregate** | **39** | **33** | **84.6%** |

Post-break drops are BY DESIGN: e.g. after `email` is removed from `Account`,
the consumer's `account.email` edges become explicitly unresolved instead of
silently matching something else (INV-2 working as intended).

Known loss buckets visible above: builtin instance methods (`toUpperCase`,
`reduce`), aliased named imports, structurally-typed member calls (marked
ambiguous), namespace-import inner bindings.

## Honesty-gate verdict

TS resolution via unique-name matching — WITHOUT specifier/receiver evidence in
the IR — is materially weaker than specifier-directed resolution. It is still
useful (84.6% on healthy small fixtures, precision-safe because
unresolved/ambiguous can never produce findings under INV-2), but expect this
number to FALL on large real trees where duplicate export names accumulate.
Per the honesty gate we do NOT claim Python-parity for TypeScript until issue
#3's fields land in 0.2.0. Recommendation to S1: fold
`Ref.module_specifier` + `Ref.imported_name` (+ ideally receiver evidence)
into the single Day-2 revision; otherwise scope TypeScript as experimental for
v1 with coverage reported beside every benchmark run.

## Limits (explicit, none hidden)

- No type inference anywhere; annotation-driven evidence only.
- Aliased (`import {a as b}`) and default imports bind only if the local name
  equals the original exported name; anonymous default exports are unbindable.
- Barrel `export * from` chains are followed only implicitly via name matching;
  renamed re-export aliases are lost (no IR channel).
- tsconfig path aliases (`@/x`) are recognized syntactically (`_paths.py`) but
  cannot be applied until specifiers ride the IR.
- node_modules / ambient modules surface as `unresolved` (never misclassified
  as local ids); proper `external` classification needs specifiers.
- Destructured object parameters, computed member access (`obj[key]`),
  decorators, and JSX-specific surfaces are out of spike scope.

## Consumable now

```python
from semlock.extractors.typescript import (
    TypeScriptExtractor,
    TypeScriptResolver,
    measure_resolution,   # Constitution §4 coverage metric
)
facts = TypeScriptExtractor().extract_file("src/x/y.ts", "main", source)
resolved = TypeScriptResolver().resolve((facts,))
```
