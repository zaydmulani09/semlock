# Real-world recall investigation (S1 session, 2026-08-27)

## Task
Build a labeled corpus of REAL historical cross-branch conflicts (SEMLock's four
classes: `signature_changed`, `removed_export`, `field_removed`, `return_changed`)
and measure SEMLock's recall against it — the one number the prior benchmark runs
never measured (precision was measured on synthetic+adversarial+mined-real corpora;
recall was measured only on synthetic).

## Result: 0 confirmed cases found (target was 8–12)

This is a reported finding, not a failure to search. Two independent search
strategies were used across 7 real repos (encode/httpx, pydantic/pydantic,
pytest-dev/pytest, pallets/click, textualize/rich, vitest-dev/vitest,
hapijs/joi) and every candidate that surfaced was individually, rigorously
verified and rejected with a specific documented reason. No case was discarded
without a reason, and no borderline case was "rounded up" to inflate the count.

## Search strategy 1: mined concurrent-PR pairs, oracle `scan_breaks`

The 21 already-validated mined pairs from the precision kill-test (see
`bench/mine.py`, `docs/SESSION_LOG.md`) are, by construction, real concurrent
PR pairs sharing a verified-clean textual merge (`git merge-tree`) and an
isolated diff per side (`_paths_unchanged_between`) — i.e. they already satisfy
the "concurrent, clean-merge" half of the task's validity definition. Their
`results.json` (from the precision kill-test run) already contains
`fn_candidates`: oracle-confirmed (mypy/tsc, counterfactual-subtracted) errors
present in the merged state that SEMLock did not predict. Any class-relevant
candidate (`class_hints` non-empty) is a recall-test candidate for free.

22 class-relevant candidates surfaced across 8 of the 21 pairs. Every one was
checked with two independent falsification tests before being trusted:

1. **A-alone test**: does the error already appear in `base + side_a` (no B
   at all)? If yes, it's the provider's own pre-existing/self-inconsistent
   issue (ADR-0009 §5 `fp_a_self_inconsistent` territory) — not a break B's
   dependency caused, and not a valid case per the task's own definition
   ("Branch/PR B... depended on the OLD surface"). **17 of 22 candidates
   failed here.**
2. **Real-merge test**: `bench/synth.py::materialize_case()`'s "merged" state
   is built by overlaying `states/side_a` then `states/side_b` onto
   `states/base` as whole-file copies — not a real 3-way text merge. When
   both PRs touch the *same file*, whichever side's directory was copied
   *last* wins **entirely** for that file, silently discarding the other
   side's edits to it. This can fabricate errors that a real `git merge`
   would never produce. Verified with `git merge-tree --write-tree
   --merge-base=<mb> <a-head> <b-head>` on the real clone. **1 of the
   remaining 5 candidates failed here** (`encode-httpx-1572x1575`).
3. The remaining 4 candidates (2 pytest cases) turned out to share a THIRD,
   separate artifact: mypy resolves the same class under two different
   module identities (`src._pytest.X` vs `_pytest.X`) depending on whether
   it's invoked with an absolute vs. relative target path against a
   src-layout package — `bench/oracle/mypy_oracle.py::check_state` passes an
   absolute path, which triggers this. Reproduced with the oracle's exact
   invocation (`cwd=state_dir`, absolute target path, no cache) vs. a
   relative-path rerun that made the error vanish. **All 4 failed this way**
   (2 of them also independently failed the A-alone test).

**22/22 candidates rejected.** See `candidates.md` for the full per-candidate
table with exact evidence.

## Search strategy 2: targeted issue-tracker search

Independent of mining, searched each repo's issue tracker for
`AttributeError`/`TypeError`/`regression`/`broken` in titles, prioritizing
issues that explicitly named a version regression. Investigated the most
promising hits in full (issue body, linked PR, root-cause commit):

- httpx #2016 (streaming byte-stream regression) — single PR's own logic bug
  (an `isinstance` check needed refining), not a two-branch interaction.
- click #3189 (`make_default_short_help(None)` AttributeError) — missing
  null-check in one function, one author, no concurrent branch involved.
- click #3731 ("8.4.0 regression", `echo_via_pager` on Windows) — a single
  refactor PR shipped its own bug (`_has_binary_buffer` stopped detecting
  `NamedTemporaryFile`'s wrapper); not caused by merging with anything else.
- rich #3540 ("Regression: cannot export captured output since v13.8.0") — a
  genuine regression, but a runtime *logic* bug (capture buffer stops
  recording), not a symbol-surface change SEMLock's four classes describe.

**0/4 investigated issues matched the task's definition.** (Several more were
triaged by title alone and set aside as clearly off-shape: message-formatting
requests, docs typos, unrelated validation-behavior questions.)

## Why the yield is (honestly) zero, not low

Every rejected candidate falls into one of three buckets, and none of them is
"SEMLock missed something real":

1. **Self-inconsistent within one PR** (17 candidates + 3 issues): the
   "break" was the provider's own bug, present with or without any second
   branch. Constitution/ADR-0009 already excludes this category from
   precision *and* it was never going to be a recall case either — there is
   no second branch depending on anything.
2. **Harness/tooling artifacts** (5 candidates): a naive same-file overlay
   standing in for a real git merge, and a mypy package-identity quirk on
   src-layout repos. Real findings about the *benchmark infrastructure*, not
   about SEMLock, and not about real-world conflict frequency.
3. **Off-shape regressions** (1 issue): a real regression that isn't one of
   SEMLock's four target classes at all.

Once those are excluded, the honest reading is that **actively-maintained,
CI-gated, code-reviewed OSS repos rarely let a genuine "two concurrent,
mutually-unaware branches, clean textual merge, real semantic break of a
signature/export/field/return" scenario reach `main` at all** — the two
guardrails those repos already have (fast CI on every PR, and maintainers who
notice overlapping work) catch most of what SEMLock targets before it merges.
That doesn't mean the scenario doesn't happen — the whole project's thesis,
and the synthetic+adversarial corpus (recall 1.0, precision 0.75, see
`docs/SESSION_LOG.md`), demonstrate SEMLock catches it correctly when it does
happen — it means finding real *historical* instances via after-the-fact
archaeology of 7 repos' history was not fruitful in the time available.

## What's committed here

- `candidates.md` — full table of all 26 investigated candidates (22 mined +
  4 issue-tracker), each with its specific rejection evidence.
- `bench/real_recall/verify_candidate.py` — the reusable verification script
  (A-alone test + real-merge test) used to check every mined candidate. Not
  wired into the benchmark harness (no engine/precision behavior changed);
  reusable for a future recall search with a longer time budget or a
  different repo set.

## Recommended follow-ups (not done in this pass — out of this task's scope)

1. Fix `materialize_case()`'s overlay to do a real merge (or at minimum
   detect and skip/flag same-file-both-sides cases) — a genuine benchmark
   correctness bug, independent of this recall search.
2. Fix or work around the mypy module-identity issue for src-layout repos
   (likely: pass a relative target path, or add `explicit_package_bases`
   handling that pins the package root unambiguously) before trusting any
   future Python mined-corpus oracle result for src-layout packages
   (`pytest-dev/pytest` is the only src-layout repo in `bench/repos.yaml`,
   so this affects pytest's mined precision numbers too — worth a targeted
   re-check).
3. If a real recall number is still wanted, the highest-yield next step is
   almost certainly widening the repo pool (more, and larger, actively
   concurrent-PR projects) rather than searching harder within these 7 — the
   two searches used here were reasonably thorough for this set.
