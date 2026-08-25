# SEMANTIC_INVARIANTS.md — Binding Invariants

These invariants are **binding on all six sessions**. They may only change via an
ADR approved by S1 plus a version bump where indicated. `docs/PROJECT_CONSTITUTION.md`
links here as normative and does **not** restate this content.

## INV-1 — Determinism law
Identical input bytes ⇒ byte-identical output artifacts (JSON included). No timestamps,
no set/dict iteration order leakage, no locale or environment dependence anywhere in the
correctness path. All ordered collections serialize in a defined sort order (see INV-5).

## INV-2 — Unresolved is never a match
A dependency edge whose `resolution.status != "resolved"` can never produce a conflict
verdict of any class. Ambiguous, external, and unresolved edges yield no finding — ever.
This invariant outranks recall.

## INV-3 — Span semantics
Lines are 1-indexed; columns are 0-indexed; ranges are half-open `[start, end)`.
Spans refer to the file content exactly as extracted (`source` bytes decoded UTF-8).

## INV-4 — Immutability & value types
All IR nodes are frozen dataclasses. Ordered collections in the IR are tuples.
No mutable default arguments. Construction validates types; serialization never mutates.

## INV-5 — Canonical sort orders
Serialized `symbols` sort by `(span.start_line, span.start_col, id)`.
Serialized `members` sort by `(name,)`.
Serialized `refs` sort by `(span.start_line, span.start_col, name)`.
Object keys serialize in the fixed key order defined by `semlock.ir.serialize`, which
matches property order in `schema/ir.schema.json`.

## INV-6 — Version gating
Consumers MUST refuse (not guess) facts whose `format_version` differs from their own
supported version. Producers stamp `FORMAT_VERSION` from `semlock.ir.version`.
Version bumps require an ADR and a synchronized update of model + schema + mocks + tests
in one commit.

## INV-7 — Local purity
The correctness path uses stdlib + tree-sitter only. No network, no API keys, no LLM,
no cloud services. Caching/config (S5) may add I/O but never alter outputs for identical
inputs.

## INV-8 — Inconclusive is a valid outcome
When evidence is insufficient (unresolved refs, missing annotations, dynamic dispatch),
the correct answer is "inconclusive"/no-finding. Fabricating a verdict to raise recall
is a methodology violation (Constitution §Benchmarks).
