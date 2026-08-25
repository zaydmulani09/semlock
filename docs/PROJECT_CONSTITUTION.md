# SEMLock — PROJECT_CONSTITUTION

Binding on all six sessions. **Constitution wins** over any other document or habit.
Normative companions (linked, not restated here): [`docs/SEMANTIC_INVARIANTS.md`](SEMANTIC_INVARIANTS.md)
(INV-1..INV-8) and [`docs/IR_CONTRACT.md`](IR_CONTRACT.md) (the FileFacts IR).

---

## 1. Thesis

Git merge is textual. Two branches can each change code cleanly and still break each
other *semantically*: branch A changes a symbol's consumed surface; branch B depends on
that old surface; git reports no conflict. **SEMLock detects the cross-branch break
pre-merge**, deterministically and locally.

## 2. The four conflict classes (v1 scope — closed without ADR)

| Class | Meaning |
|---|---|
| `signature_changed` | callee's parameters changed (added/removed/reordered/retyped) vs a caller that still uses the old form |
| `removed_export` | an exported symbol removed or renamed while the other branch imports it |
| `field_removed` | a class/interface field removed while the other branch reads/writes it |
| `return_changed` | a declared return type changed while consumers rely on the old one |

## 3. Non-goals (v1)

No runtime analysis, no type inference beyond what tree-sitter + annotations give,
no fix suggestions, no IDE plugin, no server mode, no multi-repo analysis, no dynamic
language features beyond the four classes, no languages beyond Python + TypeScript.
Expanding scope requires an ADR (cross-session rule 7).

## 4. Terminology

- **Resolution** — the act of binding a use-site (`Ref`) in one file to its defining
  `Symbol` (possibly in another file of the same changeset side). Statuses:
  `resolved`, `external`, `ambiguous`, `unresolved`.
- **Oracle** — the independent arbiter of truth for benchmarks: for Python, mypy/pyright;
  for TypeScript, tsc. A case counts as a true positive only if the oracle confirms the
  breakage. SEMLock never grades itself.
- **Resolution coverage** — fraction of dependency edges with `resolution.status ==
  "resolved"`. First-class benchmark metric, reported beside precision/recall. Low
  coverage caps achievable recall; hiding it is methodology violation.
- **Inconclusive** — a valid outcome when evidence is insufficient (INV-8).

## 5. Architecture (with the resolution stage)

```
git worktrees (S5) ──▶ Extractors per language (S2) ──▶ FileFacts (all refs unresolved)
                                                              │
                                              Resolver, ref-wide (S3)
                                                              ▼
                                            FileFacts (resolution filled)
                                                              │
                                    Claim-graph builder (S4) ─┤
                                                              ▼
                              Conflict engine: 4 rules over base/head fact pairs (S4)
                                                              ▼
                                              Findings ──▶ CLI/output (S5)
```

Seams are exactly: Extractor (`extract_file(path, ref, source) -> FileFacts`),
Resolver (`resolve(files) -> files`, fills `resolution`), then S4 consumes resolved
facts. Nobody writes another stage's output types.

## 6. Determinism law

INV-1. Identical inputs ⇒ byte-identical outputs. Enforced by round-trip and golden
tests; any nondeterminism found is a P0 defect.

## 7. Testing rules

1. **Unresolved != match** (INV-2). Every conflict test suite includes negative cases
   where edges are unresolved/external/ambiguous and NO finding may be emitted.
2. **Every rule needs TP + TN**: each of the four classes has at least one true-positive
   corpus case (oracle-confirmed break) AND one true-negative case (clean merge, no
   finding). A rule without both is not done.
3. Tests own fixtures through `mocks/`; never weaken tests to pass CI (rule 8).
4. No test may depend on network, keys, machine locale, or wall-clock time.

## 8. Benchmark rules

1. Independent type-checker oracle decides ground truth; SEMLock output is graded
   against it, never against itself.
2. **S6 veto**: only S6 changes benchmark methodology, corpus, or scoring. Other sessions'
   "improvements" that touch grading are vetoed.
3. Resolution coverage is reported first-class next to precision/recall.
4. Inconclusive/unresolved outcomes are valid results and are reported as such (INV-8).
5. No cherry-picking: corpus cases are fixed before scoring; adding cases mid-run
   requires S6 sign-off and re-running everything.

## 9. Dependency policy

Runtime deps: stdlib + tree-sitter (+ per-language tree-sitter grammars) ONLY.
Any new runtime dependency needs: a GitHub issue, S1 approval, a pyproject entry,
and justification against INV-7. Dev-only tools (ruff/mypy/pytest) live under `[dev]`.

## 10. ADRs & git workflow

- Architectural changes → `docs/adr/NNNN-title.md` (context / decision / consequences).
- Shared interfaces/schemas never change silently: ADR + version bump + S1 arbitration.
- Protected `main`: PRs only; CI green required (ownership guard + schema guard).
  Work happens on `session/N-*` branches; small coherent buildable commits.
- Schema guard: edits to `schema/**` or `semlock/ir/model.py` require an
  `IR-CHANGE-ADR:` line referencing the ADR in the PR body.

## 11. Definition of Done (per deliverable)

Code merged to main with: tests covering the behavior (incl. TP+TN where applicable),
lint+mypy clean, docs updated, no TODO standing in for a contract, determinism holds.

## 12. Release criteria (v1.0)

1. All four classes have oracle-graded TP+TN cases in the frozen corpus.
2. Precision/recall/resolution-coverage published from the real benchmark run.
3. Determinism audit clean (byte-identical reruns across machines).
4. README claims == benchmark numbers, includes an honest limitations section.
5. CI enforcing ownership + schema guards is active and has bitten at least once.

## 13. Scope control & cut order

If time runs short, cut in this order (last cut first): TypeScript support →
`return_changed` → `field_removed` → resolver sophistication (keep import-level
resolution) → polish. Never cut: determinism, INV-2, the oracle, honesty of reporting.
