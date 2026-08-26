# ADR-0003: The claim graph is a first-class, exportable artifact

Date: 2026-08-25 (Day 2+) · Status: Accepted · Owner: S1 (schema) / S4 (shape) ·
Requested by: S4

## Context
Conflict evaluation is only as trustworthy as its inputs. If the semantic layer's view
of each side is hidden inside the engine, users (and benchmarkers) cannot inspect what
SEMLock actually saw — and every dispute about a missed conflict devolves into
guesswork.

## Decision
`semlock graph` exports each changeset side's **claim graph** — declared symbol nodes,
dependency edges (every use-site with its resolution status attached), and inheritance
edges — as a standalone JSON artifact, WITHOUT running conflict evaluation. The engine
is never a prerequisite for seeing what a side claims.

- Shape owned by S4 (`semlock/graph/export.py::claim_graph_to_json`), frozen by S1 as
  `schema/claim-graph.schema.json` (wire format `0.1.0`; embeds `ir_format_version`
  `0.2.0`). IR stays 0.2.0; this schema is additive.
- Deterministic export (INV-1/INV-5): fixed key order; nodes sorted by id;
  `depends_on` by `(path, span, name, target_id)`; `inherits` by `(child_id,
  base_name)`; members by name; UTF-8, 2-space indent, trailing newline.
- Dependency edges carry ALL use-sites regardless of resolution status: the graph is
  ground truth about what each side knows. INV-2 filtering happens ONLY in the engine.

## Consequences
- Benchmark disputes are resolvable against artifacts; resolution coverage is
  computable from any dump (S6 metric).
- S5 can render/serve dumps without touching engine code.
- Post-freeze shape changes require an ADR + claim-graph format bump + synchronized
  exporter/schema update.
