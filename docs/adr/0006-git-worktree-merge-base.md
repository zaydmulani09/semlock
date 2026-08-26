# ADR-0006: Three-way comparison via merge-base + detached temporary worktrees

Date: 2026-08-25 (Day 2+) · Status: Accepted (ratified post-implementation) ·
Owner: S1 (ratify) / S4+S5 (implement) · Requested by: S5 (issue #8)

## Context
`semlock check REFA REFB` must compare two concurrent branches against their common
ancestor without disturbing the user's checkout, without mutating any refs, and
without letting machine locale or environment state influence results.

## Decision
1. **Three-way model.** Each side (A, B) is compared against the merge-base of the
   two user refs. The primitives in `semlock/git/refs.py` are exactly: pin a ref to a
   commit, find the merge-base, list files changed relative to it, and read file
   content at a ref.
2. **Detached temporary worktrees for fact collection.** `collect_side(repo, ref,
   base)` checks out exactly one commit into `git worktree add --detach` under a
   temp dir, reads only that side's changed files, and dispatches them through the
   language registry (Extractor → Resolver) to produce RESOLVED FileFacts. The main
   worktree is never checked out or mutated; worktrees are removed after collection.
3. **Determinism & purity (INV-1/INV-7).** Git is invoked with explicit args;
   stdout decoded as fixed UTF-8 with errors replaced so locale cannot alter output;
   no timestamps or environment state leak; nothing mutates the repository.
4. **Seam honesty.** The plumbing sequences stages and fabricates nothing:
   extraction/resolution come exclusively from the registry (S2/S3);
   `PipelineUnavailableError` names any missing stage rather than faking output.
   INV-6 version gating applies to every FileFacts collected; INV-2 direction is
   preserved (extractors emit unresolved; only resolvers upgrade).

## Consequences
- Works on any git repo with zero configuration; no hooks, no index games, no ref
  updates — safe by construction on user machines.
- Cost is one temp checkout per side per run (acceptable at SEMLock's scale; S5's
  cache layer may dedupe later without changing this contract).
- Any change to the three-way model or worktree lifecycle requires an ADR.
