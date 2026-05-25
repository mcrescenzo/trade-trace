## What I did

- Performed a read-only simplification review of the assigned `tools-ledger-memory-workflows` domain in `/home/hermes/code/trade-trace`.
- Confirmed repository commit: `d37136e9684138d9f9540f2a71860f36eba354f5`.
- Inspected in-scope tool modules, especially:
  - `src/trade_trace/tools/ledger/source.py`
  - `src/trade_trace/tools/ledger/decision.py`
  - `src/trade_trace/tools/playbook.py`
  - `src/trade_trace/playbook_predicates.py`
  - `src/trade_trace/tools/strategy.py`
  - adjacent schema/contract surfaces
- Ran a targeted validation suite:

```bash
pytest -q \
  tests/contracts/test_tool_schema_runtime_parity.py \
  tests/contracts/test_write_tools_have_schemas.py \
  tests/integration/test_source_attach_to_memory_node.py \
  tests/integration/test_strategy_tools.py \
  tests/unit/test_playbook_predicates.py
```

Result: `80 passed in 1.23s`.

No files were created or modified.

---

# Coverage accounting

## In-scope areas inspected

- Tool registration and schema surfaces:
  - `decision.add`
  - `source.add`
  - `source.attach_to_*`
  - `playbook.*`
  - `decision.record_adherence`
  - `strategy.*`
- Ledger workflow handlers:
  - idempotency replay paths
  - event emission
  - endpoint validation
  - append/update escape hatches for inline source metadata
- Playbook predicate workflow:
  - closed predicate validation
  - decision lookup/evaluation
  - source/link predicate evaluation
- Strategy workflow:
  - create/update/list/show
  - response normalization
  - idempotency replay shape
  - health-summary coupling

## Prior-backlog duplicate exclusions

I intentionally did **not** raise candidates for these areas because they overlap with the supplied prior coverage list:

- `memory.recall` decomposition.
- `forecast.add` / `forecast.supersede` write-kernel extraction.
- `review.bundle` decomposition.
- `source.attach` registration table centralization.
- Strategy create/update response construction.
- Meta JSON parsing in memory retain/reflect.
- Decision matrix guidance.
- CLI/dispatcher envelope centralization.
- Fixture seed decomposition.
- Report algorithm internals.

The candidates below are additive and behavior-preserving, and each targets current avoidable complexity not covered by those prior backlog items.

---

# Candidate records

---

## Candidate TT-SIMP-TLMW-01

### id

`TT-SIMP-TLMW-01`

### title

Extract a shared internal source-attachment write kernel for public and in-UoW memory-node attach paths

### complexity class

Duplicate transactional workflow / divergent write-kernel risk.

### evidence

`src/trade_trace/tools/ledger/source.py` contains two near-parallel implementations of source attachment:

- Public generated handler from `_make_source_attacher(target_kind)`:
  - lines ~264-371
  - validates source existence
  - validates target existence using `_SOURCE_ATTACH_TARGETS`
  - derives `edge_type`
  - checks idempotency replay
  - inserts `edges`
  - appends inline source metadata
  - emits `source.attached`
  - returns the public response shape

- Internal memory-node-specific in-UoW helper:
  - `_source_attach_to_memory_node_in_uow`
  - lines ~374-447
  - repeats most of the same logic, but hard-codes `target_kind="memory_node"` and receives an existing `UnitOfWork`.

This duplication is behaviorally meaningful, not cosmetic: the two paths must stay aligned on:

- NOT_FOUND envelope details
- stance-to-edge-type mapping
- idempotency replay behavior
- inline-source metadata append behavior
- emitted event payload
- response shape

The file already centralized **registration** via `_SOURCE_ATTACH_TARGETS`; this candidate targets the remaining duplicated **write kernel**, which appears not covered by the prior “source.attach registration” backlog item.

### current behavior contract

Preserve:

- Public tools:
  - `source.attach_to_thesis`
  - `source.attach_to_decision`
  - `source.attach_to_forecast`
  - `source.attach_to_memory_node`
- Internal `_source_attach_to_memory_node_in_uow` callable used by memory workflows.
- Error envelopes:
  - missing source: `NOT_FOUND`, `entity_kind="source"`
  - missing target: `NOT_FOUND`, `entity_kind=<target_kind>`
  - unsupported target kind: `VALIDATION_ERROR`
- Edge type derivation:
  - source stance `supports` / `contradicts` maps directly
  - otherwise `about`
- Idempotency replay semantics.
- Inline source metadata append for forecast, decision, and memory node.
- `source.attached` event emission.
- Response fields:
  - `id`
  - `source_id`
  - `target_kind`
  - `target_id`
  - `edge_type`
  - `created_at`

### cost

Small-to-medium.

Likely implementation:

- Add a private helper such as:

```python
def _source_attach_in_uow(
    args: dict[str, Any],
    ctx: ToolContext,
    uow: UnitOfWork,
    *,
    target_kind: str,
) -> dict[str, Any]:
    ...
```

- Public handler opens DB/UoW and calls the kernel.
- `_source_attach_to_memory_node_in_uow` becomes a thin wrapper around the kernel with `target_kind="memory_node"`.

### benefit

- Removes duplicated attachment logic.
- Reduces chance of future divergence between direct public memory-node attachment and memory-layer in-transaction attachment.
- Makes future target additions safer because validation, event emission, inline metadata append, and response shape stay in one place.
- Keeps the existing public registration table intact.

### refactor shape

1. Extract common validation:
   - source lookup
   - target metadata lookup
   - target row lookup
2. Extract common edge construction:
   - idempotency replay
   - insert edge
   - append inline source metadata
   - emit event
3. Replace `_source_attach_to_memory_node_in_uow` body with wrapper call.
4. Keep `_make_source_attacher` responsible only for opening/closing DB and passing the appropriate target kind.

### non-goals

- Do not add a generic public `source.attach` tool.
- Do not change supported target kinds.
- Do not change append-only trigger behavior.
- Do not alter source inline metadata shape.
- Do not modify report/source-quality semantics.

### behavior-preservation plan

- Characterization tests should compare both paths:
  - public `source.attach_to_memory_node`
  - memory-layer path that invokes `_source_attach_to_memory_node_in_uow`
- Verify both paths produce:
  - same edge row shape
  - same `source.attached` event payload
  - same inline metadata append
  - same replay behavior
  - same NOT_FOUND envelopes

### validation command / gap

Existing targeted validation command passed:

```bash
pytest -q \
  tests/contracts/test_tool_schema_runtime_parity.py \
  tests/contracts/test_write_tools_have_schemas.py \
  tests/integration/test_source_attach_to_memory_node.py \
  tests/integration/test_strategy_tools.py \
  tests/unit/test_playbook_predicates.py
```

Recommended additional validation after refactor:

```bash
pytest -q \
  tests/integration/test_source_attach_to_memory_node.py \
  tests/integration/test_memory_layer.py \
  tests/integration/test_memory_link.py \
  tests/integration/test_review_bundle_contract.py \
  tests/integration/test_manual_ledger_flow.py
```

### size / risk / priority / confidence

- Size: S/M
- Risk: Medium-low
- Priority: High within this lane
- Confidence: High

### why-not-style

This is not a style cleanup. It removes duplicated state-changing behavior across two call paths that must maintain exact event/idempotency/edge semantics.

### intentional complexity check

Some complexity is intentional:

- public tools remain separate by design
- source attachment direction is meaningful
- inline metadata append intentionally bypasses append-only triggers

The avoidable complexity is the duplicated implementation of the same attachment transaction, not the public surface itself.

### duplicate / overlap notes

- Does **not** duplicate prior “source.attach registration” work; that prior work centralized the target metadata/registration table.
- This candidate addresses the still-duplicated transaction/write kernel.

### proposed bead title

Simplify source attachment by sharing the public/internal write kernel

### proposed bead body

`source.attach_to_memory_node` and `_source_attach_to_memory_node_in_uow` currently duplicate source validation, target validation, stance-to-edge mapping, idempotency replay, edge insert, inline-source metadata append, event emission, and response construction. Extract a private `_source_attach_in_uow(..., target_kind=...)` helper and make both public generated attachers and the memory-node in-UoW wrapper call it. Preserve all public tool names, response shapes, error envelopes, idempotency semantics, and inline metadata behavior.

### proposed acceptance

- Public `source.attach_to_*` tool names and schemas unchanged.
- `_source_attach_to_memory_node_in_uow` remains available to memory workflows.
- Existing source attach, memory layer, and review bundle tests pass.
- New/updated regression confirms public memory-node attach and in-UoW memory-node attach produce equivalent edge/event/metadata behavior.
- No generic public `source.attach` tool is introduced.

### coordinator disposition recommendation

Create backlog bead. This is a good additive simplification candidate with localized scope and clear behavioral tests.

---

## Candidate TT-SIMP-TLMW-02

### id

`TT-SIMP-TLMW-02`

### title

Introduce small endpoint-validation helpers for playbook workflow handlers

### complexity class

Repeated domain validation / error-envelope boilerplate.

### evidence

`src/trade_trace/tools/playbook.py` repeats similar endpoint validation blocks in multiple write/read workflow handlers:

- `_playbook_propose_version`, lines ~431-462:
  - validate playbook exists
  - validate `provenance_reflection_node_id` exists in `memory_nodes`
  - validate node type is `reflection`

- `_decision_record_adherence`, lines ~591-630:
  - validate decision exists
  - validate playbook version exists
  - validate `rule_node_id` exists in `memory_nodes`
  - validate node type is `playbook_rule`

- `_playbook_adherence`, lines ~710-721:
  - validate playbook exists before delegating to report

These checks are intentionally explicit, but they repeat the same envelope construction pattern:

- query `SELECT 1` or `SELECT node_type`
- raise `ToolError(ErrorCode.NOT_FOUND, ..., details={...})`
- for node type mismatch, raise `VALIDATION_ERROR` with `field`, `memory_node_id`, and `actual_node_type`

The repeated shape increases the chance that future playbook workflow additions drift in error details or validation order.

### current behavior contract

Preserve:

- `playbook.propose_version`:
  - requires existing playbook
  - requires existing memory node with `node_type='reflection'`
- `decision.record_adherence`:
  - requires existing decision
  - requires existing playbook version
  - requires existing memory node with `node_type='playbook_rule'`
  - preserves adherence status validation
  - emits `playbook_rule.followed` or `playbook_rule.overridden`
- `playbook.adherence`:
  - rejects unknown playbook with `NOT_FOUND` rather than silently returning empty report rows
- Existing error messages and `details` payloads where contract tests depend on them.

### cost

Small.

Likely helpers:

```python
def _require_row_exists(conn, *, table, id_value, entity_kind, detail_key) -> None:
    ...

def _require_memory_node_type(
    conn,
    *,
    node_id: str,
    expected_type: str,
    field: str,
    not_found_label: str,
) -> None:
    ...
```

Or more domain-specific helpers:

```python
def _require_playbook(conn, playbook_id): ...
def _require_playbook_version(conn, playbook_version_id): ...
def _require_decision(conn, decision_id): ...
def _require_memory_node_type(conn, node_id, expected_type, *, field): ...
```

Domain-specific helpers are probably safer because they preserve tailored messages.

### benefit

- Reduces repeated validation/error-envelope code in a high-churn workflow module.
- Makes validation contracts easier to audit.
- Encourages future playbook tools to reuse the same NOT_FOUND / VALIDATION_ERROR shapes.
- Keeps handlers focused on workflow-specific write behavior rather than endpoint boilerplate.

### refactor shape

1. Extract domain-specific private validators near the top of `playbook.py`.
2. Replace repeated blocks in:
   - `_playbook_propose_version`
   - `_decision_record_adherence`
   - `_playbook_adherence`
3. Preserve current error strings/details initially; only centralize construction.
4. Optionally add narrow regression assertions around error detail shapes.

### non-goals

- Do not change playbook storage model.
- Do not alter playbook predicate evaluation.
- Do not change `decision.record_adherence` event naming.
- Do not introduce generalized repository-wide validation framework.
- Do not move report logic into tools.

### behavior-preservation plan

- Snapshot current error envelopes for:
  - missing playbook
  - missing playbook version
  - missing decision
  - missing reflection node
  - wrong reflection node type
  - missing rule node
  - wrong rule node type
- Refactor helpers.
- Confirm same `ToolError.code`, message, and `details` values.

### validation command / gap

Existing targeted command passed:

```bash
pytest -q \
  tests/contracts/test_tool_schema_runtime_parity.py \
  tests/contracts/test_write_tools_have_schemas.py \
  tests/integration/test_source_attach_to_memory_node.py \
  tests/integration/test_strategy_tools.py \
  tests/unit/test_playbook_predicates.py
```

Recommended after refactor:

```bash
pytest -q \
  tests/integration/test_playbook_layer.py \
  tests/contracts/test_tool_schema_runtime_parity.py \
  tests/contracts/test_cli_command_help.py \
  tests/unit/test_playbook_predicates.py
```

Potential gap: if current tests do not assert wrong-node-type error details, add small regression tests before refactor.

### size / risk / priority / confidence

- Size: S
- Risk: Low
- Priority: Medium
- Confidence: Medium-high

### why-not-style

This is not formatting or taste. It centralizes repeated domain validation behavior that produces externally visible typed error envelopes.

### intentional complexity check

The validation itself is intentional and should remain explicit at the workflow level. The avoidable complexity is repeated low-level envelope construction across handlers.

### duplicate / overlap notes

- Does not duplicate prior “CLI/dispatcher envelope centralization”; this is domain endpoint validation inside playbook workflows, not dispatcher-level envelope handling.
- Does not duplicate playbook predicate or decision matrix work.

### proposed bead title

Simplify playbook workflow endpoint validation with shared domain helpers

### proposed bead body

`playbook.propose_version`, `decision.record_adherence`, and `playbook.adherence` repeat playbook/decision/version/memory-node existence and node-type checks with hand-built `ToolError` envelopes. Extract small private domain validators in `tools/playbook.py` to preserve the same NOT_FOUND / VALIDATION_ERROR behavior while reducing drift risk in future playbook workflow changes.

### proposed acceptance

- Existing playbook workflow behavior unchanged.
- Missing playbook, decision, playbook version, reflection node, and rule node still return the same error codes/details.
- Wrong memory node type still returns `VALIDATION_ERROR` with `field`, `memory_node_id`, and `actual_node_type`.
- `tests/integration/test_playbook_layer.py` and schema/help contract tests pass.
- No changes to report algorithms or predicate semantics.

### coordinator disposition recommendation

Create backlog bead if there is appetite for small localized simplification. Lower priority than TT-SIMP-TLMW-01 but still valid.

---

## Candidate TT-SIMP-TLMW-03

### id

`TT-SIMP-TLMW-03`

### title

Create a small decision-row loader for playbook predicate evaluation to avoid duplicate SELECT/description logic

### complexity class

Local query duplication / avoidable evaluator ceremony.

### evidence

`src/trade_trace/playbook_predicates.py` in `evaluate_predicate` performs two equivalent decision queries:

- lines ~203-204:

```python
rows = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchall()
```

- lines ~209-210:

```python
names = [d[0] for d in conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).description]
decision = dict(zip(names, row, strict=True))
```

The second `execute` appears to be used only to access `.description`; it repeats the same SQL. This is small but current, concrete accidental complexity in a closed-set evaluator whose correctness depends on deterministic local DB reads.

### current behavior contract

Preserve:

- Missing decision returns:
  - `PredicateEvaluation(status="not_computable", caveats=["decision_id not found"])`
- Multiple rows returns:
  - `PredicateEvaluation(status="ambiguous", caveats=["multiple decision rows found"])`
- Successful decision load returns a dict containing all current decision columns.
- Scope checks and downstream predicate semantics unchanged.
- No arbitrary SQL, expression parsing, or external data access.

### cost

Small.

Likely helper:

```python
def _load_single_decision(conn, decision_id: str) -> tuple[dict[str, Any] | None, PredicateEvaluation | None]:
    cursor = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,))
    rows = cursor.fetchall()
    ...
    names = [d[0] for d in cursor.description]
    return dict(zip(names, rows[0], strict=True)), None
```

Or narrower:

```python
def _decision_row_dict(conn, decision_id: str) -> tuple[list[sqlite3.Row], list[str]]:
    ...
```

### benefit

- Removes duplicate query.
- Gives the predicate evaluator one named place for the “exactly one decision row” contract.
- Makes `evaluate_predicate` easier to scan; its core dispatch over predicate families becomes clearer.
- Reduces accidental DB work, though performance is not the primary benefit.

### refactor shape

1. Introduce `_load_decision_for_predicate(conn, decision_id, family, rule_node_id)`.
2. Have it return either:
   - decision dict and `None`, or
   - `None` and a ready `PredicateEvaluation`
3. Replace the duplicated query block in `evaluate_predicate`.
4. Keep error statuses/caveats byte-for-byte if tests rely on them.

### non-goals

- Do not change supported predicate families.
- Do not change closed-set validation.
- Do not broaden evaluator capabilities.
- Do not switch to row factory globally.
- Do not alter source/link evaluation semantics.

### behavior-preservation plan

- Add or rely on unit tests for:
  - missing decision
  - field predicates
  - source/link predicates
  - scoped not-applicable predicates
  - forecast resolution rule predicate
- Confirm `PredicateEvaluation.to_dict()` output unchanged for representative cases.

### validation command / gap

Existing targeted command passed:

```bash
pytest -q tests/unit/test_playbook_predicates.py
```

Also passed as part of the broader targeted run.

Recommended after refactor:

```bash
pytest -q \
  tests/unit/test_playbook_predicates.py \
  tests/integration/test_playbook_layer.py
```

Potential gap: add a direct unit assertion for missing decision if not already covered.

### size / risk / priority / confidence

- Size: XS/S
- Risk: Low
- Priority: Low-medium
- Confidence: High

### why-not-style

This is not stylistic rearrangement; it removes a duplicate database query and names a correctness-sensitive “load exactly one decision” contract.

### intentional complexity check

The evaluator’s closed-set family dispatch is intentional and safety-relevant. This candidate does not collapse the dispatch or generalize predicates; it only removes redundant loading ceremony.

### duplicate / overlap notes

- Does not overlap with prior memory recall, decision matrix, or report decomposition coverage.
- It is limited to `playbook_predicates.py`.

### proposed bead title

Simplify playbook predicate decision loading

### proposed bead body

`evaluate_predicate` currently runs `SELECT * FROM decisions WHERE id = ?` twice: once to fetch rows and again to access cursor description for column names. Extract a small private decision loader that executes once, preserves the missing/multiple-row `PredicateEvaluation` behavior, and returns the decision dict for predicate dispatch.

### proposed acceptance

- `tests/unit/test_playbook_predicates.py` passes.
- Missing and duplicate decision behavior remains unchanged.
- Predicate outputs for existing families remain unchanged.
- No new predicate language, SQL input, or external data access is introduced.

### coordinator disposition recommendation

Optional backlog bead. Very low risk but smaller payoff than the source attachment kernel candidate.

---

# Candidates considered but rejected

## Rejected: Decompose `memory.py` by line count

- Reason: prior coverage explicitly includes `memory.recall` decomposition and meta JSON parsing in memory retain/reflect.
- Additional memory simplification would require deeper behavioral proof beyond this lane’s time budget.
- LOC alone is insufficient per task instruction.

## Rejected: Decompose `forecast.add` / `forecast.supersede`

- Reason: explicitly listed as prior coverage.
- Current large functions are known hotspots, but duplicate backlog would be wasteful.

## Rejected: Further centralize strategy response construction

- Reason: prior coverage explicitly includes strategy create/update response construction.
- I inspected `strategy.py`; current helpers `_strategy_response`, `_strategy_row_to_dict`, and `_strategy_full_row_to_dict` already show this has been addressed.

## Rejected: Source attach registration simplification

- Reason: explicitly prior-covered.
- The current table `_SOURCE_ATTACH_TARGETS` already centralizes registration/target metadata. The valid new candidate is the write-kernel duplication left after that work, not registration.

---

# Files created or modified

None.

Read-only review only.

---

# Issues encountered

None. Targeted tests passed cleanly.