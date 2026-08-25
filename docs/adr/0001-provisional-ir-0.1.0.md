# ADR-0001: Provisional FileFacts IR v0.1.0

Date: 2026-08-25 (Day 1) · Status: Accepted (provisional) · Owner: S1

## Context
S2–S6 cannot start without a concrete IR. Waiting for perfect information blocks the
whole program. The IR contract (docs/IR_CONTRACT.md) must ship Day 1.

## Decision
Ship FORMAT_VERSION=0.1.0 as **provisional**: frozen dataclasses, tuples, spans
(1-indexed lines / 0-indexed cols / half-open), Resolution status enum
(unresolved|resolved|external|ambiguous), refs default-unresolved at extraction.
Field-access refs provisionally resolve to `<symbol_id>.<member>` pending spike Q5.

## Consequences
- Exactly ONE deliberate revision to 0.2.0 at Day 2 EOD, driven by the five spike
  answers; then frozen. Later changes need ADR + bump + synchronized model/schema/mocks.
- Downstream sessions build against mocks/ until real extractors land (cross-rule 14).
