# ADR-0006: Git integration via detached worktrees + merge-base three-way

**Status:** Accepted (ratified post-implementation; S5 arbitration, issue #8)
**Owner:** S5
**Consumed by:** `semlock check`, `semlock graph`; upstream: resolver (S3), engine (S4)

## Context

SEMLock must compare two branch heads against their merge-base (three-way) to detect
cross-branch semantic breaks that textual merging cannot see. The comparison needs,
per side, the *declared surfaces* and *use-sites* of source files **as they exist at
that ref** — without disturbing the user's working tree, index, or refs. Constraints:
determinism (INV-1), local purity — stdlib + git CLI only (INV-7), and honest refusal
when downstream stages are unavailable rather than partial results.

Alternatives considered:

- **`git show <ref>:<path>` per file** — no checkout needed, but gives no place to run
  a ref-wide resolver over coherent file sets and encourages piecemeal reads.
- **Temp clone per ref** — correct but pays full object-copy cost per side.
- **In-process plumbing (libgit2/pygit2)** — new runtime dependency; violates the
  dependency policy (Constitution §9) for no determinism gain.
- **Parsing `.git/` directly** — fragile, version-coupled, rejects the "stdlib +
  git CLI" boundary.

## Decision

1. **Read-only plumbing around the git CLI** (`semlock/git/refs.py`): ref resolution
   (`rev-parse --verify`), merge-base (`git merge-base`), changed-file listing with
   three-dot semantics (`diff --name-only -z base...head`), and file content at a ref.
   All invocations decode output as UTF-8 regardless of machine locale.

2. **Detached temporary worktrees** (`semlock/git/extract_at_ref.py`): each examined
   commit is materialized via `git worktree add --detach --quiet` into a private temp
   directory and removed afterwards (`worktree remove --force`, falling back to
   `worktree prune`). The user's working tree, index, and refs are never touched.

3. **THREE-WAY shape**: `collect_three_way(repo, ref_a, ref_b)` pins both heads,
   computes their merge-base, and produces fact sets for **base + A + B**. The base is
   a first-class side because the engine diffs claim graphs `base -> head` in both
   directions; two-way A-vs-B comparison is expressly out of scope.

4. **Full supported-file extraction per side**, not just files changed vs the base:
   the ref-wide Resolver needs definition context on the consuming side to bind import
   edges (a side that consumes `pkg.models` must carry its own copy of models.py or its
   refs stay unresolved and INV-2's choke silences real conflicts), and graph diffs
   need complete graphs at both ends to distinguish "changed" from "vanished".
   Changed-vs-base listings remain computed for reporting and future narrowing.

5. **Seam honesty**: this layer dispatches to whatever Extractor/Resolver the registry
   holds and refuses cleanly (`PipelineUnavailableError`) when a language is missing;
   it never fabricates facts or resolutions, and gates every produced FileFacts on
   FORMAT_VERSION (INV-6: refuse, never guess).

## Consequences

- **+** Zero disturbance of user state; safe on dirty trees, CI, and shared clones.
- **+** Deterministic outputs: same commits ⇒ same worktree contents ⇒ same facts.
- **+** Works before extractors land: CLI degrades to an actionable refusal.
- **−** Extraction cost scales with repo size per side (3 worktrees). Mitigations when
  needed: extension filtering already skips non-source trees; config-driven path
  excludes (S5) and changed-file narrowing can follow without contract changes.
- **−** Worktree cleanup depends on filesystem cooperation; the prune fallback plus
  temp-dir placement keeps failures invisible to correctness and cheap in aggregate.
- Windows note: worktrees inside OneDrive-synced paths were observed working but are
  not relied upon by tests; tests always use system temp directories.
