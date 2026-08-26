# ADR-0004: Declarative, language-agnostic rule registry

Date: 2026-08-25 (Day 2+) · Status: Accepted · Owner: S1 (ratify) / S4 (implement) ·
Requested by: S4

## Context
The four conflict classes could be hard-coded as engine branches. That couples conflict
semantics to engine plumbing, makes rules untestable in isolation, and invites
language-specific special cases to leak into evaluation.

## Decision
Each conflict class is a **declarative rule**: a pure predicate over one
`(surface change, eligible dependency edge)` pairing plus read-only `RuleContext`
(base/provider/consumer claim graphs). Rules live in a fixed-order registry
(`semlock/engine/rules/`).

Binding constraints on every rule:
1. See ONLY eligible deps (`status == "resolved"` with concrete `target_id`).
   `evaluate.py` enforces upstream; each rule re-checks defensively — the INV-2 choke
   is structural AND per-rule.
2. ZERO language-specific logic. No `if language == ...` — ever.
3. Return `None` when evidence is inconclusive instead of fabricating a verdict
   (INV-8). Rules may never weaken this stance to raise recall.
4. Registration order is fixed and deterministic (INV-1).

## Consequences
- New conflict classes = new registered predicate + corpus cases; no engine surgery.
- Every rule needs oracle-graded TP + TN cases (Constitution §7.2); the registry makes
  per-rule grading mechanical for S6.
- Language knowledge stays in extractors/resolvers (ADR-0008); the engine layer stays
  language-blind by construction.
