"""Git integration for SEMLock (S5).

Read-only plumbing around the git CLI: ref resolution, merge-base computation,
changed-file listing, and per-ref worktree checkouts (ADR-0006). No network,
no mutation of the user's working tree or refs (worktrees are temporary).
"""
