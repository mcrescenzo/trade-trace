## Read-only simplification review lane report: `storage-events-models`

### What I did

- Inspected the assigned repository area read-only under `/home/hermes/code/trade-trace`.
- Reviewed storage, migrations, events, models-adjacent projection/export surfaces, timestamp policy, and relevant tests/docs signals.
- Used line-numbered file reads and repository searches only.
- Did **not** edit files, create/update Beads, or retain memory.

### Files inspected / sampled

- `src/trade_trace/storage/database.py`
- `src/trade_trace/storage/migrations/__init__.py`
- `src/trade_trace/storage/migrations/_runner.py`
- `src/trade_trace/events/log.py`
- `src/trade_trace/events/unit_of_work.py`
- `src/trade_trace/events/semantic_keys.py`
- `src/trade_trace/projections.py`
- `src/trade_trace/exporter.py`
- `src/trade_trace/timestamps.py`
- `tests/integration/test_outbox_export.py`
- `tests/integration/test_projection_rebuild.py`
- `tests/contracts/test_event_type_registry_alignment.py`
- Search coverage over assigned integration/security tests and prior simplification terms.

---

# Candidate records

## CAND-STORAGE-EVENTS-001

### Title

Centralize DB-row → `EventRecord` hydration for events/outbox paths.

### Complexity class

Duplication / contract drift risk / small abstraction extraction.

### Evidence

`EventRecord` construction from the same `events` table shape is duplicated:

- `src/trade_trace/events/log.py`
  - SELECT column list in `_find_existing`: lines 144-151.
  - Manual `EventRecord(...)` construction: lines 157-171.
- `src/trade_trace/exporter.py`
  - SELECT column list in `_load_event`: lines 363-370.
  - Manual `EventRecord(...)` construction: lines 376-390.
- Fresh-write construction has the same field order manually spelled out:
  - `events/log.py` lines 294-308.

The selected columns are identical in the two read paths:

```text
id, event_type, subject_kind, subject_id, payload_json,
actor_id, idempotency_key, created_at, request_id,
agent_id, model_id, environment, run_id
```

### Current behavior contract

- `EventWriter.find_existing()` / replay path must return the original event row without writing a new row.
- `drain_outbox()` must load an event row, serialize it to JSONL, and preserve deterministic output.
- Event metadata fields such as `request_id`, `agent_id`, `model_id`, `environment`, and `run_id` must survive through both paths.
- No schema or JSONL shape change.

### Cost

Small.

Likely changes:

- Add an `EVENT_RECORD_COLUMNS` constant near `EventRecord`.
- Add `EventRecord.from_row(row)` or a small private helper.
- Use the helper in `EventWriter._find_existing()` and `exporter._load_event()`.
- Optionally keep fresh-write construction unchanged because it is not row-based.

### Benefit

- Reduces accidental coupling to a positional column order copied in multiple modules.
- Makes future event metadata additions less error-prone.
- Keeps outbox/export and idempotency replay hydration behavior aligned by construction.
- Improves testability: one hydration helper can be directly unit-tested or covered through existing tests.

### Refactor shape

Behavior-preserving extraction only:

```python
EVENT_RECORD_SELECT_COLUMNS = (
    "id", "event_type", ...
)

@dataclass
class EventRecord:
    ...
    @classmethod
    def from_row(cls, row: sqlite3.Row | tuple[Any, ...]) -> "EventRecord":
        return cls(...)
```

Then compose SELECT strings from the constant or keep SQL explicit but use `from_row`.

### Non-goals

- Do not change event schema.
- Do not change append-only semantics.
- Do not change JSONL serialization.
- Do not alter idempotency comparison.

### Behavior-preservation plan

Run:

```bash
pytest tests/integration/test_idempotency.py \
       tests/integration/test_outbox_export.py \
       tests/integration/test_jsonl_contract.py \
       tests/security/test_redacted_exports.py
```

Potential additional gap:

- Add a small regression test asserting `_load_event()` and `EventWriter.find_existing()` hydrate all metadata fields consistently if no current test covers agent provenance fields through export.

### Size / risk / priority / confidence

- Size: S
- Risk: Low
- Priority: Medium
- Confidence: High

### Why not style-only

This is not a formatting cleanup. The duplicated positional row mapping is a real contract-drift risk: a future added event column or reordered SELECT can silently corrupt hydrated metadata in one path but not the other.

### Intentional complexity check

The append-only audit log, idempotency replay, outbox export, and provenance columns are intentional complexity. This candidate does **not** weaken them; it only centralizes a repeated mechanical mapping.

### Duplicate / overlap notes

Does not appear to duplicate the listed prior closed work. It is adjacent to JSONL/export and event append-only hardening, but the specific hydration duplication remains current in the inspected code.

### Proposed bead title

Centralize EventRecord row hydration across idempotency and outbox export paths

### Proposed bead body

`EventRecord` is manually hydrated from the same `events` SELECT shape in both `events/log.py` and `exporter.py`. Add a single row-hydration helper or column constant so idempotency replay and JSONL outbox loading cannot drift when event metadata columns change. Preserve schema, JSONL output, idempotency behavior, and append-only guarantees.

### Proposed acceptance

- `EventWriter._find_existing()` and `exporter._load_event()` use the same `EventRecord` hydration helper or shared column definition.
- Existing idempotency and outbox/export tests pass.
- No JSONL output shape changes.
- No event schema changes.

### Coordinator disposition recommendation

Accept as additive simplification candidate.

---

## CAND-STORAGE-EVENTS-002

### Title

Stream `rebuild_positions()` by ordered groups instead of materializing all position events into an intermediate dict.

### Complexity class

Data-flow simplification / memory reduction / projection rebuild clarity.

### Evidence

`src/trade_trace/projections.py` currently:

- Fetches all `position_events` rows into memory:
  - lines 109-127.
- Builds `by_position: dict[str, list[PositionEventRow]]`:
  - lines 129-132.
- Iterates grouped events:
  - lines 134-168.

The SQL already orders by position and stable event order:

```sql
ORDER BY pe.position_id ASC, pe.created_at ASC, pe.id ASC
```

This makes a streaming `itertools.groupby`-style rebuild possible without preserving a whole-table dict.

### Current behavior contract

From docstring and tests:

- Rebuild must be deterministic.
- Event order must be `(position_id ASC, created_at ASC, id ASC)`.
- Rebuilding twice over the same source must produce identical `positions`.
- Invalid reversal/exposure transitions must continue to raise `ToolError`.
- Caller wraps the rebuild in a transaction; function does not commit.

Relevant evidence:

- Determinism contract: `projections.py` lines 60-104.
- Existing idempotence tests: `tests/integration/test_projection_rebuild.py` lines 104-126.
- Signed quantity tests: `test_projection_rebuild.py` lines 137-160 and beyond.

### Cost

Small to medium.

Likely changes:

- Replace `fetchall()` + dict grouping with cursor iteration.
- Maintain a current `position_id` and list of rows for that one group.
- Flush group through `_accumulate_position()` when `position_id` changes.
- Preserve same insert logic.

### Benefit

- Avoids loading every `position_events` row and a whole-table grouping dict during rebuild.
- Makes the code match the documented replay algorithm more directly: “walk grouped by `position_id`, ordered by created_at/id.”
- Reduces accidental complexity in the rebuild kernel without changing projection math.

### Refactor shape

Behavior-preserving streaming rewrite:

```python
cur = conn.execute("SELECT ... ORDER BY position_id, created_at, id")
current_id = None
events = []

for row in cur:
    event = PositionEventRow(*row)
    if current_id is not None and event.position_id != current_id:
        rebuild_one(current_id, events)
        events = []
    current_id = event.position_id
    events.append(event)

if current_id is not None:
    rebuild_one(current_id, events)
```

Could extract the repeated insert body into a local helper if desired, but avoid broad abstraction.

### Non-goals

- Do not change position P&L logic.
- Do not change invalid reversal handling.
- Do not change projection schema.
- Do not introduce event-sourcing framework abstractions.
- Do not change memory-node stats rebuild.

### Behavior-preservation plan

Run:

```bash
pytest tests/integration/test_projection_rebuild.py
```

Optional targeted addition:

- Add a test with multiple `position_id`s whose events interleave by timestamp to prove grouping remains by `position_id` and stable per-position event order is preserved.

### Size / risk / priority / confidence

- Size: M
- Risk: Low to medium, because projection math is important.
- Priority: Medium
- Confidence: High

### Why not style-only

The current implementation has avoidable memory growth and two-phase grouping despite SQL already producing the needed order. This is structural simplification of a rebuild path, not naming/formatting.

### Intentional complexity check

Projection rebuild determinism and append-only source replay are intentional complexity. This candidate preserves the ordered replay contract and only simplifies the in-memory grouping mechanism.

### Duplicate / overlap notes

Does not appear covered by the listed prior simplification items. It is within projection rebuild behavior, not migration split/schema diagnostics/append-only hardening.

### Proposed bead title

Stream positions projection rebuild by ordered position_events groups

### Proposed bead body

`rebuild_positions()` currently fetches all `position_events`, materializes a `dict[position_id, list[event]]`, then replays each group. Since the query already orders by `position_id, created_at, id`, refactor the rebuild to stream one position group at a time. Preserve deterministic ordering, P&L math, invariant violations, transaction behavior, and projection output.

### Proposed acceptance

- `rebuild_positions()` no longer materializes all position events into a whole-table grouping dict.
- Existing projection rebuild tests pass.
- Multi-position rebuild output remains byte-identical before/after.
- No schema or public envelope changes.

### Coordinator disposition recommendation

Accept as additive simplification candidate.

---

## CAND-STORAGE-EVENTS-003

### Title

Collapse overlapping event-type → tool registries where safely derivable.

### Complexity class

Registry duplication / contract drift risk.

### Evidence

There are two manually maintained maps with overlapping knowledge:

1. Exporter map:

- `src/trade_trace/exporter.py` lines 87-139.
- `_STATIC_EVENT_TOOL_MAP` maps event types to user-callable tools for replayable JSONL events.
- Example entries:
  - `"venue.created": "venue.add"` lines 112.
  - `"decision.created": "decision.add"` line 117.
  - `"memory_node.retained": "memory.retain"` line 126.
  - `"strategy.created": "strategy.create"` line 127.

2. Semantic/idempotency map:

- `src/trade_trace/events/semantic_keys.py` lines 324-367.
- `TOOL_PRIMARY_EVENT_TYPE` maps user-callable tools to primary event types for auto-derived idempotency.
- Example inverse entries:
  - `"venue.add": "venue.created"` line 338.
  - `"decision.add": "decision.created"` line 345.
  - `"memory.retain": "memory_node.retained"` line 363.
  - `"strategy.create": "strategy.created"` line 351.

Existing contract tests acknowledge two event-type registries:

- `tests/contracts/test_event_type_registry_alignment.py` lines 1-16.
- It currently only asserts exporter map keys are a subset of `SEMANTIC_KEYS` and values are registered tools, lines 24-58.

### Current behavior contract

- `SEMANTIC_KEYS` remains canonical for event types that may be written.
- `_STATIC_EVENT_TOOL_MAP` is intentionally a subset: only replayable bucket-A events need explicit tool mapping.
- System/audit-only events may default to event type string.
- `source.attached` remains payload-disambiguated via `resolve_tool_for_event()` lines 101-105.
- JSONL importer must keep receiving valid `tool` names for replayable events.

### Cost

Medium.

Because the subset/default behavior and aliases need care.

### Benefit

- Reduces manual inverse duplication.
- Prevents a replayable event from gaining auto-idempotency mapping but missing JSONL replay mapping, or vice versa.
- Makes registry-alignment tests stronger and less dependent on human synchronization.

### Refactor shape

Conservative additive shape:

- Define one canonical mapping for replayable events, possibly tool → event.
- Derive event → tool for one-to-one replayable events.
- Keep explicit overrides for:
  - aliases such as `outcome.add`, `resolution.add`, `resolve.record`;
  - `source.attached` payload-based handling;
  - audit-only/system events that intentionally default.
- Update alignment tests to assert derived/inverse consistency for the one-to-one subset.

### Non-goals

- Do not make every semantic event replayable.
- Do not remove bucket taxonomy.
- Do not change JSONL line shape.
- Do not alter idempotency key derivation.

### Behavior-preservation plan

Run:

```bash
pytest tests/contracts/test_event_type_registry_alignment.py \
       tests/integration/test_outbox_export.py \
       tests/integration/test_jsonl_contract.py \
       tests/integration/test_import_jsonl_replay.py \
       tests/integration/test_jsonl_replay_readiness.py
```

### Size / risk / priority / confidence

- Size: M
- Risk: Medium, because importer/exporter replay contracts are sensitive.
- Priority: Low to medium.
- Confidence: Medium.

### Why not style-only

This is not cosmetic duplication. The two maps encode overlapping event-contract knowledge and a mismatch could produce non-replayable JSONL or divergent idempotency behavior.

### Intentional complexity check

The bucketed replay taxonomy and defaulting audit/system events to event type strings are intentional. This candidate should preserve that by deriving only the safe one-to-one replayable subset and leaving explicit exceptions.

### Duplicate / overlap notes

Potential overlap with prior “timestamp/enum registry investigation” and “JSONL serialization decision.” Existing `test_event_type_registry_alignment.py` references `SIMP-004`, indicating some prior registry alignment work. This candidate should be treated as **conditional**: only proceed if the coordinator confirms prior closed work did not already reject centralization of these two specific maps.

### Proposed bead title

Derive JSONL replay event-tool map from canonical replayable tool-event registry

### Proposed bead body

`exporter._STATIC_EVENT_TOOL_MAP` and `events.semantic_keys.TOOL_PRIMARY_EVENT_TYPE` manually encode many inverse event/tool relationships. Introduce a conservative shared replayable mapping or derivation for one-to-one replayable events, while preserving explicit aliases, `source.attached` payload-based resolution, and audit-only defaults. Strengthen alignment tests so future event additions cannot drift between idempotency and JSONL replay surfaces.

### Proposed acceptance

- One-to-one replayable event/tool relationships are not manually duplicated in opposite directions.
- Existing JSONL export/import tests pass.
- Audit-only/system event behavior remains unchanged.
- `source.attached` payload-dependent resolution remains unchanged.
- Alignment tests document and enforce intentional exceptions.

### Coordinator disposition recommendation

Conditional / needs duplicate check against SIMP-004 and prior JSONL registry decisions before accepting.

---

# Non-candidates / intentional complexity observed

## Append-only guards and migration triggers

Observed many append-only and invariant triggers across migrations:

- `m003_m1_ledger.py` trigger creation search hits at lines 417 and 426.
- `m009_events_append_only.py` lines 43 and 52.
- `m006_memory_layer.py` FTS/append-only trigger hits.
- `m010_strategy_id_new_row_triggers.py` line 39.

Disposition: **do not simplify away**. These are intentional audit/idempotency/security constraints and are explicitly in prior coverage: append-only hardening, strategy_id references, FTS5 optionality/policy.

## Migration split / schema-meta diagnostics

Observed split registry and fingerprints:

- `storage/migrations/__init__.py` lines 1-10 document split and schema hash test.
- `MIGRATIONS` list lines 56-72.
- `_MIGRATION_TABLES_CREATED` lines 75-105.
- `_MIGRATION_COLUMNS_ADDED` lines 108-156.
- `_runner.py` schema/meta mismatch checks lines 82-184.

Disposition: **no new candidate**. This area is explicitly covered by prior closed work: migration split investigation, schema/meta diagnostics, migration policy.

## Timestamp governed columns

Observed `TIMESTAMP_API_GOVERNED_COLUMNS` in `timestamps.py` lines 23-94 and normalization logic lines 107-143.

Disposition: **no new candidate**. The governance list is intentionally explicit and prior coverage mentions timestamp/enum registry investigation.

## Security and JSONL atomicity

Observed exporter path/file safety and permissions:

- Safe filename handling: `exporter.py` lines 39-64.
- Atomic tmp write/replace and chmod: lines 185-233.
- Tmp cleanup: lines 254-273.
- Secret scanning warnings: lines 276-315 and 487-522.

Disposition: **no simplification candidate**. This is intentional complexity for local-first security, atomic export, replay, and secret-boundary behavior. Prior coverage includes path/POSIX permission helpers, export secret boundary, public JSONL outbox, and JSONL serialization decision.

## Legacy sqlite-vec no-op helpers

Observed:

- `load_sqlite_vec_extension()` in `storage/database.py` lines 39-48.
- `has_sqlite_vec()` lines 254-258.
- Current caller in `tools/journal.py` search hits lines 92-99.

Disposition: **not in assigned scope enough / likely compatibility surface**. Could be future cleanup if public journal status no longer reports sqlite-vec, but this lane should avoid adapter/tool-reporting contracts.

---

# Coverage accounting

### In-scope areas covered

- Storage connection/read-only/open policy: sampled.
- Migrations runner and registry: sampled.
- Events writer/idempotency/outbox: inspected.
- Unit of work transaction/dry-run: inspected.
- Semantic keys/idempotency derivation: inspected.
- Projection rebuilds: inspected.
- JSONL exporter/outbox drain/security scanning: inspected.
- Timestamp policy: inspected.
- Relevant tests for outbox, projections, event registry alignment: inspected.

### Areas intentionally not deeply pursued

- CLI parser details: out of scope.
- Report display/report-specific logic: out of scope.
- Adapter fetch logic: out of scope.
- Broad docs style: out of scope.
- Full migration body line-by-line review: avoided because prior migration split/schema/meta work exists and current runner/registry showed intentional complexity.

### Files created or modified

None.

### Issues encountered

None. Read-only inspection completed successfully.