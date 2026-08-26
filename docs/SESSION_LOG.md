# SESSION_LOG

Append one line per merge (cross-session rule 17): what landed, what's consumable.

- 2026-08-25 S1: Founding contract files on main (IR_CONTRACT, SEMANTIC_INVARIANTS,
  S1_DAY1_CHECKLIST, schema/ir.schema.json, ownership.yaml, ownership_guard.py).
- 2026-08-25 S1: IR FROZEN at 0.2.0 ΓÇö added Reference.module_specifier +
  imported_name (S3 #3), ratified module_path::qualified_name grammar,
  ADR-0008 + TS ownership + tree-sitter deps landed. Post-freeze changes
  require ADR.
- 2026-08-25 S1: S2 and S3 cleared to rebase onto 0.2.0. Their PRs will pass the
  ownership guard (S2: semlock/extractors/python/, tests/unit+fixtures/python/;
  S3: semlock/extractors/typescript/, semlock/resolution/, tests/unit+fixtures/
  typescript/) and the schema guard via ADR-0008 (referenced by this freeze).
  Runtime deps tree-sitter/tree-sitter-python/tree-sitter-typescript now in
  pyproject ΓÇö CI installs them with `-e .[dev]`. Verified: ownership guard passes
  for an S3-authored TS path and fails an S2-authored TS path; ruff+mypy --strict+
  pytest (39) green; serialize round-trip byte-identical rerun confirmed.
- 2026-08-25 S1: IR provisional + mocks + seam landed ΓÇö S2-S6 go.
  Consumable now: `semlock/ir/model.py` (+`serialize`, `version`=0.1.0 PROVISIONAL),
  `semlock/extractors/base.py` (Extractor+Resolver ABCs) + `registry.py`,
  `mocks/` (RESOLVED ir_fixtures seeded from pkg.models.User.greet; 4 conflict
  scenarios + 1 clean-merge TN in changeset_fixtures/conflict_fixtures),
  `docs/PROJECT_CONSTITUTION.md` (binding), ADR-0001. CI: ruff+mypy --strict+
  pytest all green locally; GitHub workflow lands with this merge.
- 2026-08-26 S1: S5 arbitration (#8) ΓÇö action/ granted to S5 (ownership.yaml +
  CODEOWNERS); `[project.scripts] semlock = "semlock.cli.main:main"` added;
  ADR-0006 (git worktree + merge-base) ratified; docs/SESSION_LOG.md made
  common so rule-17 appends pass the guard for every session.
