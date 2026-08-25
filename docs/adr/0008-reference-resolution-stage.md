# ADR-0008: Reference resolution is a first-class stage inside language packages

Date: 2026-08-25 (Day 2) · Status: Accepted · Owner: S1 · Requested by: S3 (issue #1)

## Context
The S1 Day-1 seam placed resolvers abstractly under `semlock/resolution/` (S3-owned).
The TypeScript spike showed resolution cannot be language-agnostic: binding depends on
module-specifier semantics (`"./config"`, `@/lib`, node_modules), export/barrel
following, and declaration annotations. A generic resolver would guess; guessing
violates INV-8.

## Decision
1. Resolution is **first-class** and implemented by S3 **inside each language package**,
   mirroring S1's ABCs in `semlock/extractors/base.py`:
   `semlock/extractors/python/resolver.py`, `semlock/extractors/typescript/resolver.py`.
   The `semlock/resolution/` package is reserved for cross-language shared helpers only.
2. Member use-sites bind to the **member's own canonical id**
   `<module_path>::<Owner>.<member>` (e.g. `pkg.models::User.email`) — never a suffixed
   parent id (`...::User.greet.name` is malformed).
3. Identity grammar (ratified with 0.2.0): `id = "<module_path>::<qualified_name>"`,
   `::` the sole module/symbol separator. Module-granular dependencies (plain
   `import a.b`) use the bare `module_path` as `resolution.target_id`
   (grammar-distinct by absence of `::`).

## Consequences
- Extractors stay dumb (emit evidence, leave refs unresolved); resolvers own binding.
- `Ref` gains `module_specifier` / `imported_name` in 0.2.0 (issue #3) so TS binds
  aliased imports and follows re-exports to original ids deterministically.
- UNRESOLVED-NEVER-MATCHES (INV-2) unchanged: richer evidence converts honest
  unresolved/ambiguous into resolved; it never fabricates matches.
