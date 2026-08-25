# IR_CONTRACT.md — FileFacts Intermediate Representation (v0.1.0 — PROVISIONAL)

**Status:** binding contract for S2 (extractors), S3 (resolvers), S4 (conflict engine),
S5 (cache/config), S6 (benchmarks). Owned by S1. Changes require an ADR with an
`IR-CHANGE-ADR:` line, a FORMAT_VERSION bump, and synchronized model+schema+mock updates.

> **THIS VERSION IS PROVISIONAL.** It ships Day 1 to unblock S2–S6 spikes. It freezes at
> **0.2.0** Day 2 EOD after exactly ONE deliberate revision driven by the spike answers
> below. Build against it; expect one break.

Normative companions: `docs/SEMANTIC_INVARIANTS.md` (invariants INV-1..INV-8),
`schema/ir.schema.json` (wire validation).

## 1. Purpose

One `FileFacts` record = everything SEMLock knows about **one file on one branch ref**:
declared symbols (functions/classes/exports/fields) and use-sites (`refs`) awaiting
resolution. The conflict engine compares facts from branch A vs branch B and detects
cross-branch semantic breaks that `git merge` cannot see.

## 2. Node reference

| Node | Fields (order = serialization order) |
|---|---|
| `Span` | `start_line`, `start_col`, `end_line`, `end_col` — lines 1-indexed, cols 0-indexed, half-open `[start,end)` (INV-3) |
| `Param` | `name`, `position`, `kind` ∈ {`positional`,`keyword_only`,`varargs`,`kwargs`}, `type_annotation` \| null, `has_default`: bool |
| `Signature` | `params`: tuple[Param], `return_type`: str \| null (textual annotation as written; null when absent/unannotated) |
| `Member` | `name`, `type_annotation` \| null, `span` |
| `Symbol` | `id`, `name`, `kind` ∈ {`function`,`method`,`class`,`interface`,`type_alias`,`variable`}, `span`, `exports`: bool, `bases`: tuple[str], `signature`: Signature \| null, `members`: tuple[Member] |
| `Resolution` | `status` ∈ {`unresolved`,`resolved`,`external`,`ambiguous`}, `target_id`: str \| null (set iff status=`resolved`) |
| `Ref` | `name`, `kind` ∈ {`call`,`read`,`write`,`import`,`attribute`}, `span`, `resolution`: Resolution (default `unresolved`) |
| `FileFacts` | `format_version`, `path` (repo-relative, `/` separators), `language` ∈ {`python`,`typescript`}, `ref`, `symbols`: tuple[Symbol], `refs`: tuple[Ref] |

Rules:

- `Symbol.id` is the dotted qualified name rooted at the module/package path
  (e.g. `pkg.models.User.greet`; TypeScript: `src/models/user.User.greet`).
  Exact scheme is Spike Question Q1.
- Every `Ref.resolution` starts `unresolved`. Only a Resolver may upgrade it (INV-2).
  An extractor that emits `resolved` is in violation of the seam.
- Sort orders: symbols by `(span, id)`; members by `name`; refs by `(span, name)` (INV-5).

## 3. Canonical example

Source (`pkg/models.py`):

```python
class User:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"
```

Serialized FileFacts (abbreviated to one symbol + one external ref):

```json
{
  "format_version": "0.1.0",
  "path": "pkg/models.py",
  "language": "python",
  "ref": "main",
  "symbols": [
    {
      "id": "pkg.models.User.greet",
      "name": "greet",
      "kind": "method",
      "span": {"start_line": 2, "start_col": 4, "end_line": 3, "end_col": 30},
      "exports": false,
      "bases": [],
      "signature": {
        "params": [
          {"name": "self", "position": 0, "kind": "positional",
           "type_annotation": null, "has_default": false},
          {"name": "name", "position": 1, "kind": "positional",
           "type_annotation": "str", "has_default": false}
        ],
        "return_type": "str"
      },
      "members": []
    }
  ],
  "refs": [
    {
      "name": "print",
      "kind": "call",
      "span": {"start_line": 9, "start_col": 4, "end_line": 9, "end_col": 15},
      "resolution": {"status": "external", "target_id": null}
    }
  ]
}
```

## 4. The four conflict classes this IR must support

| Class | Facts required | A-side | B-side |
|---|---|---|---|
| `signature_changed` | `Symbol.signature.params` | param added/removed/reordered/retyped | `Ref(kind=call)` resolving to that symbol |
| `removed_export` | `Symbol.exports`, `Symbol.id` | export removed or renamed | `Ref(kind=import)` naming old id |
| `field_removed` | `Symbol.members` | member removed | `Ref(kind=read\|write\|attribute)` on `.name` |
| `return_changed` | `Signature.return_type` | return annotation changed | consuming call/read resolved to symbol |

## 5. Seam ownership

- Extractor (S2): source bytes → `FileFacts`, every ref left `unresolved`.
- Resolver (S3): `resolve(files: tuple[FileFacts, ...]) -> tuple[FileFacts, ...]`,
  **ref-wide** across all files of one changeset side; fills `resolution`.
- Engine (S4): consumes pairs of fully-resolved FileFacts → conflicts.
- Nobody else writes into another stage's output types.

## 6. The five spike questions (answer by Day 2 EOD)

S2 + S3 must answer these; S1 turns the answers into the single 0.2.0 revision:

1. **Q1 identity:** Is the dotted qualified-name scheme sufficient for your cross-file
   matching, or do you need module-path separated from symbol path? Give one counterexample if not.
2. **Q2 params:** Do you need param *kinds* (`keyword_only`/`varargs`/`kwargs`) or are
   name+position+has_default enough? Which signature deltas do you actually flag?
3. **Q3 returns:** Is declared-only `return_type` acceptable, and what should the field
   hold when unannotated but inferable?
4. **Q4 use-sites:** Which `Ref.kind`s does your extraction reliably produce per language,
   and which must we add/drop for the four classes above?
5. **Q5 resolution:** What evidence distinguishes `resolved` / `external` / `ambiguous`
   in your implementation? What should extractors provide to make `ambiguous` rare?

## 7. Versioning

`FORMAT_VERSION` lives in `semlock/ir/version.py`. Current: **`0.1.0` (provisional)**.
Freeze target: **`0.2.0`** Day 2 EOD. After freeze, changes require ADR + bump + S4/S6
sign-off.
