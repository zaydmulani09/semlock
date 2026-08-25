# SESSION_LOG

Append one line per merge (cross-session rule 17): what landed, what's consumable.

- 2026-08-25 S1: Founding contract files on main (IR_CONTRACT, SEMANTIC_INVARIANTS,
  S1_DAY1_CHECKLIST, schema/ir.schema.json, ownership.yaml, ownership_guard.py).
- 2026-08-25 S1: IR provisional + mocks + seam landed — S2-S6 go.
  Consumable now: `semlock/ir/model.py` (+`serialize`, `version`=0.1.0 PROVISIONAL),
  `semlock/extractors/base.py` (Extractor+Resolver ABCs) + `registry.py`,
  `mocks/` (RESOLVED ir_fixtures seeded from pkg.models.User.greet; 4 conflict
  scenarios + 1 clean-merge TN in changeset_fixtures/conflict_fixtures),
  `docs/PROJECT_CONSTITUTION.md` (binding), ADR-0001. CI: ruff+mypy --strict+
  pytest all green locally; GitHub workflow lands with this merge.
