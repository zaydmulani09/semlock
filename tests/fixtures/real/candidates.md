# Investigated candidates — full table

All 26 candidates that surfaced from the two search strategies described in
`README.md`. "Case" links back to the mined-pair directory
(`bench/repos.yaml` repos, PR numbers) or issue number. All mined cases share
merge-base `git merge-base(A.base_sha, B.base_sha)`, verified isolated per
side, verified textually-clean merge (`_mutually_independent` +
`_paths_unchanged_between` in `bench/mine.py`, run against real GitHub PR
history 2026-08-27).

## Mining-derived candidates (`bench.oracle.*.scan_breaks`, counterfactual-subtracted)

| # | Case | Site | Class hint(s) | Verdict | Evidence |
|---|------|------|----------------|---------|----------|
| 1 | encode/httpx #1572 x #1575 | `httpx/_client.py:890,1533` `on_close` call-arg | signature_changed | **REJECTED — harness artifact** | Real `git merge-tree --write-tree --merge-base=<mb> <a-head> <b-head>` (tree `f120917...`) shows `httpx/_client.py` has **zero** `on_close` occurrences — A's own fix to its caller survives the real merge cleanly (different regions than B's edit). `materialize_case()`'s naive last-overlay-wins copy discarded A's fix because B also touches this file and is applied second. |
| 2 | pydantic/pydantic #12147 x #12333 | `pydantic/json_schema.py:426` assignment | return_changed | **REJECTED — A-alone** | Identical error reproduces in `base + side_a` only (no B; B touches `config.py`/docs only, never `json_schema.py`). |
| 3 | (same pair) | `json_schema.py:592` assignment | return_changed | **REJECTED — A-alone** | Same test, same result. |
| 4 | (same pair) | `json_schema.py:603` assignment | return_changed | **REJECTED — A-alone** | Same test, same result. |
| 5 | (same pair) | `json_schema.py:2113` arg-type | signature/return_changed | **REJECTED — A-alone** | Same test, same result. |
| 6 | pydantic/pydantic #12289 x #12292 | `_known_annotated_metadata.py:192,223` + `experimental/pipeline.py` (34 sites) | removed_export/field_removed/return_changed | **REJECTED — A-alone** (38 sites, one root cause) | All 38 sites reproduce in `base + side_a` only (B touches `_generate_schema.py`, `_generics.py`, `_serializers.py`, `json_schema.py`, docs, pyproject — never these two files). One underlying type-narrowing bug in A's own PR, manifesting at every `.copy()`/`[]=` call on the narrowed type. |
| 7 | pytest-dev/pytest #13857 x #13859 | `src/_pytest/helpconfig.py:55` attr-defined `_parser` | removed_export/field_removed/return_changed | **REJECTED — oracle module-identity artifact** | `src/_pytest` package resolves to two identities (`src._pytest.X` vs `_pytest.X`) depending on absolute-vs-relative mypy invocation target. Reproduced only with the oracle's exact invocation (absolute path, `cwd=state_dir`); a relative-path or subdir-target rerun makes it vanish. Not a real type error. |
| 8 | (same pair) | `src/_pytest/config/__init__.py:1266` arg-type `install_importhook` | signature/return_changed | **REJECTED — same artifact** | Error message itself names both identities: `"src._pytest.config.Config"; expected "_pytest.config.Config"` — the two names are the same class, confused by mypy's package-root inference for this exact invocation shape. |
| 9 | pytest-dev/pytest #12129 x #14369 | `src/_pytest/python.py:1662` arg-type `TopRequest` | signature/return_changed | **REJECTED — both A-alone AND module-identity artifact** | Reproduces in `base + side_a` alone; also shows the identical `src._pytest.python.Function` vs `_pytest.python.Function` identity split. |
| 10 | vitest-dev/vitest #10962 x #10964 | `packages/vitest/src/node/pools/browser.ts:67,69` TS2345 | signature/return_changed | **REJECTED — A-alone** | Reproduces in `base + side_a` only (B touches `poolRunner.ts`, `forksWorker.ts` — never `browser.ts`). Verified with the oracle's exact tsconfig (`bench/oracle/tsc_oracle.py::_write_tsconfig`). |
| 11 | vitest-dev/vitest #10963 x #10962 | `packages/vitest/src/node/core.ts:1495` TS2339 `moduleGraph` | signature/field_removed/return_changed | **REJECTED — A-alone** | Reproduces in `base + side_a` only. |
| 12 | (same pair) | `core.ts:1639` TS2339 `unref` | same | **REJECTED — A-alone** | Same. |
| 13 | (same pair) | `runtime/workers/vm.ts:186` TS2339 `close` | same | **REJECTED — A-alone** | Same. |
| 14 | vitest-dev/vitest #10076 x #10090 | `node/config/resolveConfig.ts` (10 sites: lines 81, 84, 87, 113, 654, 655, 733, 735, 869, 870) | signature/return_changed | **REJECTED — A-alone** (10 sites, one root cause) | All reproduce in `base + side_a` only (B touches `runner/*`, `snapshot/chai.ts`, `printError.ts` — never `resolveConfig.ts`). One `ApiConfig` type-narrowing issue in A's own PR. |
| 15 | (same pair) | `node/packageInstaller.ts:43,53` TS2307 module-not-found | removed_export | **REJECTED — A-alone** | Reproduces in `base + side_a` alone; also plausibly missing-devDependency noise (`prompts`, `@antfu/install-pkg` not installed), independent of B either way. |

(Rows 3–5, 6, 12–13, 14–15 are grouped duplicates of one underlying root
cause at multiple call sites; counted as one candidate each in the README's
headline "22 candidates" / "8 of 21 pairs" figures where the distinct
(case, root-cause) pairs are: #1, #2/3/4/5, #6, #7/8, #9, #10, #11/12/13,
#14, #15 = 9 distinct root causes across 8 cases; 22 is the raw per-site
count before grouping.)

## Issue-tracker candidates (independent of mining)

| # | Repo | Issue | Verdict | Evidence |
|---|------|-------|---------|----------|
| 16 | encode/httpx | #2013 / PR #2016 "Fix for stream uploads that subclass Sync/AsyncByteStream" | **REJECTED — single-PR bug** | The fix (`b7dc0c3d`) changes one `hasattr` check's own logic; no second branch's dependency on an old surface is involved. |
| 17 | pallets/click | #3189 "AttributeError in make_default_short_help(None)" | **REJECTED — single-function bug** | Missing null-check in one utility function; no concurrent branch. |
| 18 | pallets/click | #3731 "echo_via_pager on Windows... (8.4.0 regression)" | **REJECTED — single-PR refactor bug** | The `get_pager_file`/`_pager_contextmanager` rewrite (one PR) introduced its own `_has_binary_buffer` detection bug; not a merge interaction. |
| 19 | textualize/rich | #3540 "Regression: cannot export captured output since v13.8.0" | **REJECTED — off-shape** | Genuine regression, but a runtime capture-buffer logic bug, not a signature/export/field/return-type surface change. |

Additional issues triaged by title/summary only and set aside as clearly
off-shape (message-formatting requests, docs, unrelated validation-behavior
questions, dependency-install errors unrelated to click/pytest/rich/joi
source): pydantic #12726, #13134, #13133, #13373, #13415, #13424 (checked in
full — see README "Search strategy 1" note on `#eval_type_backport` removal:
internal-only removal, no external caller reachable in the sampled corpus);
joi #3140, #3094, #3083, #3071, #3060, #3059, #3058, #3047, #3036, #3033,
#3008, #3003, #3000, #2971, #2966, #2963, #2956 (validation-behavior/message
requests, not surface-change breakage).
