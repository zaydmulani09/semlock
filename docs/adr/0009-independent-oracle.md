# ADR-0009: Independent type-checker oracle for benchmark ground truth

Date: 2026-08-25
Owner: S6
Status: Accepted
Related: PROJECT_CONSTITUTION §4 (Oracle), §8 (Benchmark rules);
SEMANTIC_INVARIANTS INV-2, INV-7, INV-8; docs/IR_CONTRACT.md §4

## Context

SEMLock claims to detect cross-branch semantic breaks that git merges cleanly.
Grading that claim with SEMLock itself would be self-certification. The
constitution mandates an independent oracle; the practical questions were how
to (a) establish ground truth without contaminating it with pre-existing repo
dirt, (b) attribute checker diagnostics to a SPECIFIC predicted relationship,
and (c) handle cases where truth cannot be established.

## Decision

1. **Oracle abstraction** (`bench/oracle/base.py`): `Oracle` ABC with
   `check_state(dir) -> tuple[SiteError, ...]`, `evaluate(ctx, pred) ->
   OracleResult`, `scan_breaks(ctx) -> candidates`, and class attribution via
   `error_matches_class`. Verdicts: `true_positive`, `false_positive`,
   `false_negative`, `inconclusive`.
2. **Backends**: mypy for Python (`MypyOracle`), tsc for TypeScript
   (`TscOracle`). Both run hermetically (no inherited config, no incremental
   cache reuse) over materialized state directories.
3. **Counterfactual subtraction is mandatory.** Ground truth compares errors
   on the MERGED tree against the counterfactual tree (base + side B WITHOUT
   side A). Only interaction-attributable errors may confirm or deny a
   prediction; pre-existing dirt can never make SEMLock look right or wrong.
   Without a counterfactual the verdict is INCONCLUSIVE — never guessed.
4. **Site-first attribution.** A prediction is confirmed by an interaction
   error at its predicted use-site whose error code/message category matches
   the conflict class. Exception: re-export/shim indirection localizes some
   real breaks off-site; an interaction error ON THE CAUSAL CHAIN counts when
   its message names the changed symbol AND it lies outside side A's surface
   files (`CaseContext.surface_paths`). Notes record which rule fired.
5. **A-side self-inconsistency is not a merge break.** Errors already present
   in side A's own files are excluded from confirming consumer predictions;
   such cases form the named FP category `fp_a_self_inconsistent`.
6. **FN detection**: `scan_breaks` yields interaction errors independent of
   predictions. Reconciliation marks a false negative when no true-positive
   prediction covers a declared planted site (synthetic) or, for mined cases
   once prediction-bearing, any candidate site the resolver should have seen.
   Class-ambiguous candidates become FN rows flagged `needs_review`, never
   forced attributions.
7. **Publishability gate**: only runs whose predictor kind is `cli` (real S5
   CLI findings) produce publishable numbers. Mock-predictor plumbing runs are
   stamped NOT PUBLISHABLE in every report they generate.
8. **Determinism tiering**: results.json is byte-identical across identical
   reruns (no wall clock); timings.json carries performance separately.

## Consequences

+ SEMLock is graded exclusively by tools that do not share its code or its
  failure modes (constitution §8.1).
+ Conservative attribution trades some recall-measurement sensitivity for
  zero contamination; inconclusive rates are reported first-class (INV-8).
− Checker majors differ in flags and exit codes (tsc 6 exits 1 for plain
  diagnostics); the oracle parses output rather than exit codes and records
  tool versions per run. Corpus replays pin nothing at runtime but reports
  name the exact versions used.
− Off-site attribution relies on message tethering; exotic indirections may
  yield INCONCLUSIVE instead of TP. Accepted until corpus evidence says
  otherwise.
+ TS resolution strength (S3's flag) is quantified independently through the
  same pipeline as Python, enabling an apples-to-apples positioning check.
