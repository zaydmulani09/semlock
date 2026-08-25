# S1_DAY1_CHECKLIST.md — S1 exact task list (Day 1)

Execute in order. Items marked **[GATE]** unblock S2–S6.

- [ ] 1. `docs/PROJECT_CONSTITUTION.md`: thesis; 4 conflict classes; non-goals;
       terminology (incl. resolution, oracle, resolution coverage); architecture WITH
       the resolution stage; determinism law; testing rules (unresolved != match; every
       rule needs TP+TN); benchmark rules (independent type-checker oracle, S6 veto,
       resolution coverage first-class, inconclusive valid, no cherry-picking);
       dependency + ADR + git workflow; DoD; release criteria; scope-control + cut order.
       LINK SEMANTIC_INVARIANTS.md and IR_CONTRACT.md as binding; do not restate them.
- [ ] 2. `semlock/ir/model.py` + `semlock/ir/version.py` — dataclasses from
       IR_CONTRACT.md VERBATIM (frozen dataclasses, tuples not lists),
       FORMAT_VERSION="0.1.0". PROVISIONAL: freezes Day 2 EOD after exactly one revision.
- [ ] 3. `semlock/ir/serialize.py` — to_json/from_json validated against
       schema/ir.schema.json. Deterministic key order; symbols/members/refs sorted by
       span then id/name. Round-trip test.
- [ ] 4. `semlock/extractors/base.py` — TWO ABCs: `Extractor`
       (`extract_file(path, ref, source) -> FileFacts`) and `Resolver`
       (`resolve(tuple[FileFacts,...]) -> tuple[FileFacts,...]`, ref-wide, fills
       `resolution`). `registry.py` maps language -> (Extractor, Resolver).
       Do NOT implement extraction or resolution yourself.
- [ ] 5. `mocks/`: `ir_fixtures.py` (RESOLVED FileFacts, schema-valid — seeded from the
       `pkg.models.User.greet` example), `changeset_fixtures.py`,
       `conflict_fixtures.py`. **[GATE — UNBLOCKS S2–S6]**
- [ ] 6. Merge steps 1–5 to main. Announce in docs/SESSION_LOG.md:
       "IR provisional + mocks + seam landed — S2-S6 go."
- [ ] 7. Parallel (does NOT block the gate): `.github/workflows/ci.yml` (lint, mypy,
       pytest, ownership guard, schema-change guard requiring an IR-CHANGE-ADR line when
       `schema/**` or `ir/model.py` changes), CODEOWNERS mirroring ownership.yaml,
       pyproject.toml.

Tests S1 owns: schema-validation, IR JSON round-trip, mock validity.
