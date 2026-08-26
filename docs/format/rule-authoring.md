# Rule Authoring Guide (S4)

How to write, register, and validate a conflict rule for the SEMLock engine.
Normative baseline: `docs/PROJECT_CONSTITUTION.md`, `docs/SEMANTIC_INVARIANTS.md`
(INV-1..INV-8), `docs/IR_CONTRACT.md` (IR 0.2.0 FROZEN). This guide is owned by S4.

## 1. The model in one paragraph

Resolved `FileFacts` build a **ClaimGraph** per changeset side (`semlock/graph/`):
nodes are declared symbols; dependency edges carry every use-site WITH its
resolution status; inheritance edges record declared bases. A **ChangeSet**
(`semlock/engine/changeset.py`) is the three-way diff: `provides_delta_X =
diff(graph(mb), graph(X))` — always base→side. Evaluation
(`semlock/engine/evaluate.py`) matches each provider-side surface change against the
OPPOSITE head's resolved dependencies, both directions. Nothing else is ever
compared.

## 2. The choke you inherit (INV-2 — binding)

    eligible(deps) = [d for d in deps if d.resolution.status == "resolved"]

- evaluate.py indexes ONLY eligible deps before any rule runs;
- `Rule._guard()` re-checks defensively inside every rule;
- non-resolved resolutions cannot even name a target (`target_id` is None unless
  status == "resolved" — the IR model enforces this).

A rule therefore CANNOT fire on an unresolved/ambiguous/external edge. Never try to
route around this. It outranks recall.

## 3. Rule contract

One module per rule under `semlock/engine/rules/`, exposing module-level `RULE`.
Register it with one line in `REGISTRY` (`rules/__init__.py`) — registry order is
part of determinism.

```python
class MyRule(Rule):
    rule_id: ClassVar[str] = "my_rule"            # stable id, rendered by S5
    conflict_class: ClassVar[str] = "<one of the four>"

    def evaluate(self, change, dep, ctx) -> Conflict | None:
        if not self._guard(change, dep):          # INV-2 defense, always first
            return None
        if change.kind != "<the surface delta you handle>":
            return None
        assert dep.target_id is not None
        if dep.target_id != change.symbol_id:     # exact id match, never fuzzy
            return None
        ...                                       # class-specific gates
        return make_conflict(...)                 # or None = no / inconclusive
```

Hard rules:

1. **No language-specific logic.** No `if language == ...`, no grammar names, no
   AST shapes. The engine sees resolved IR only. Violations are P0.
2. **Match on `target_id` equality only.** Never parse `Ref.name` for semantics
   (IR_CONTRACT §2: `name` is producer-encoded evidence).
3. **Inconclusive means None** (INV-8). Missing Signature, null return annotation,
   absent snapshot → return None. Fabricating verdicts to raise recall is a
   methodology violation.
4. **Never fire on `kind == "added"`.** Additions break nobody; evaluate.py filters
   them, rules should too.
5. **Explanations name everything** (INV-9): rule id, provider symbol id, consumer
   symbol/ref, both `file:line`s, both branch sides. A bare "semantic conflict
   detected" must be impossible to construct.

## 4. Surface change kinds (what the diff emits)

| kind                | symbol_id is            | before/after | extra           |
|---------------------|-------------------------|--------------|-----------------|
| `removed`           | symbol id               | before only  | —               |
| `unexported`        | symbol id               | both         | exports T→F     |
| `signature_changed` | symbol id               | both         | detail = param delta text |
| `return_changed`    | symbol id               | both         | emitted only when BOTH return annotations are non-null and differ |
| `member_removed`    | `<owner_id>.<member>`   | owner snapshots | removed_member carries the Member (span = evidence) |
| `added`             | symbol id               | after only   | never evaluated |

Params compare fieldwise (name, position, kind, type_annotation, has_default);
members compare as NAME SETS on the Symbol — never any language AST.

## 5. Evidence contract (published to S5)

`Conflict` (frozen dataclass, `engine/evidence.py`) fixed dict key order via
`conflict_to_dict`:

    rule, conflict_class, changed_symbol_id, changed_side,
    consumer_ref_name, consumer_ref_kind, consumer_path, consumer_span,
    consumer_side, target_id, explanation, evidence_a, evidence_b

`evidence_a`/`evidence_b` are the A-view/B-view respectively (NOT
provider/consumer order): `{path, line, col, role}` where role ∈
`changed_definition | consuming_use`. For pure removals the definition side points
at the base location via the before-snapshot — reported honestly as such.

## 6. Required tests before a rule lands

Constitution §7.2 + §11:

- at least one TP through the REAL pipeline (`build_changeset` + `evaluate`);
- at least one TN for each plausible near-miss (wrong dep kind, wrong target,
  incomparable surfaces, no consumer);
- one unresolved/ambiguous/external case proving ZERO findings (add to
  `tests/unit/engine/test_inv2_choke.py`);
- determinism: identical inputs ⇒ byte-identical `to_dict()` output.

## 7. Worked example

See `semlock/engine/rules/field_removed.py`: guard → kind gate → dep-kind gate →
exact-id gate → evidence assembly with the member's own span. Its test block
(`tests/unit/engine/test_rules_tp_tn.py`) shows the TP/TN pattern including the
"annotation changed but member set unchanged" TN that keeps v1 scope tight.

## 8. Changing or REMOVING a rule

If S6's kill-test shows high FP / weak signal: narrow or remove the rule — that
outranks the original four-rule plan (briefing; Constitution §8 veto rights sit
with S6 for grading). Removal = delete module + REGISTRY line + its tests in one
commit; note it in `docs/SESSION_LOG.md`. Rule ids are never reused.
