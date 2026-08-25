# SEMLock

Deterministic, local-first CLI that detects semantic conflicts between two concurrent
code changes that `git merge` reports as clean.

**Status: pre-alpha, Day 1.** The IR contract (`docs/IR_CONTRACT.md`) is provisional at
0.1.0 and freezes at 0.2.0 Day 2 EOD. No benchmark numbers exist yet; this section will
lead with S6's real measured numbers (precision, recall, resolution coverage) once the
benchmark lands — never before.

## How it works

```
worktrees -> extractors (per language) -> FileFacts (refs unresolved)
          -> resolver (ref-wide)       -> FileFacts (resolution filled)
          -> conflict engine           -> findings
```

Four conflict classes in v1: `signature_changed`, `removed_export`, `field_removed`,
`return_changed`. Languages: Python + TypeScript. Core: stdlib + tree-sitter only —
no network, no keys, no LLM, no cloud in the correctness path.

## What it can't see (honesty section — will grow, never shrink)

- Anything dynamic: monkey-patching, `getattr` strings, reflection.
- Unresolvable references are **never** reported as conflicts (unresolved != match).
- Type-inference gaps where annotations are absent.

## Development

- Constitution: `docs/PROJECT_CONSTITUTION.md` (binding).
- IR contract + schema: `docs/IR_CONTRACT.md`, `schema/ir.schema.json`.
- Build against mocks until real extractors land: `mocks/`.

```bash
py -m pip install -e ".[dev]"
py -m pytest -q
py -m mypy semlock mocks
py -m ruff check .
```
