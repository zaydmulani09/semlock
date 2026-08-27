"""Real-world recall investigation tooling (session 2026-08-27).

See tests/fixtures/real/README.md for the full writeup: this package's
`verify_candidate` script is the reusable verification methodology used to
check every candidate found there — an "A-alone" isolation test (is the
error the provider's own pre-existing issue, independent of any second
branch?) and a real-git-merge test (does bench.synth.materialize_case's
naive same-file overlay agree with an actual `git merge-tree`?). Not wired
into the benchmark harness; this is investigation tooling, not a scoring
path — it changes no engine or precision behavior.
"""
