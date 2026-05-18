# Persistence: Events, Outbox, and Idempotency

Status: clean planning draft. Date: 2026-05-18.

Companion docs: [PRD.md](../../PRD.md), [VISION.md](../../VISION.md),
[memory-layer.md](memory-layer.md), [scoring.md](scoring.md),
[contracts.md](contracts.md).

## 1. Purpose

PRD §2.2 and §5 reference an event log, an outbox for JSONL export, and
idempotency keys on write APIs, but never specify their schema or contract.
This doc fills that gap. It defines:

- The `events` table that records every committed write.
- The `outbox` table that drives JSONL export without dual-writing.
- The idempotency contract for safe agent retries.
- Transaction boundaries between ledger writes, event log writes, and
  projection updates.
- Replay semantics for rebuilding projections.

The contract is designed for one specific failure mode: an LLM agent's
network or tool call drops mid-write and the agent retries with the same
inputs. Trade Trace must not double-write under retry, and must not lose
writes under crash.

## 2. SQLite as Source of Truth

SQLite at `$TRADE_TRACE_HOME/trade-trace.sqlite` is the single source of
truth. The database runs in WAL mode with a single-writer assumption for
MVP. Multi-writer concurrency is a P1+ concern (see open questions).

Two classes of table:

- **Source/event tables** (`events`, `outcomes`, `snapshots`, `theses`,
  `decisions`, `position_events`, `forecast_scores`, `memory_nodes`,
  `edges`, `outbox`) are append-only. Corrections create new rows; older
  rows stay readable for audit.
- **Projection tables** (`positions`, `memory_node_stats`) are rebuildable
  from source data via `journal.rebuild_projections`. They exist for query
  performance, not authority.

## 3. The `events` Table

Every committed ledger write produces exactly one `events` row in the same
transaction as the write itself.

| Column | Type | Purpose |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Monotonic event ID. |
| `event_type` | `TEXT NOT NULL` | E.g. `decision.created`, `outcome.recorded`, `memory_node.retained`, `forecast.scored`, `playbook.proposed_version`. |
| `subject_kind` | `TEXT NOT NULL` | Kind of the primary subject (`decision`, `outcome`, `memory_node`, ...). |
| `subject_id` | `TEXT NOT NULL` | ID of the primary subject. |
| `payload_json` | `TEXT NOT NULL` | The full input payload as accepted by the tool, after validation. |
| `actor_id` | `TEXT NOT NULL` | `agent:default`, `cli:user`, `import:<name>`, etc. |
| `idempotency_key` | `TEXT NULL` | Caller-supplied retry key (see §5). |
| `created_at` | `TEXT NOT NULL` | UTC ISO 8601 timestamp. |
| `request_id` | `TEXT NULL` | Per-call request ID echoed in the response envelope. |

Indexes:

- `(subject_kind, subject_id)` for lookups like "all events about this
  decision".
- `(event_type, actor_id, idempotency_key)` UNIQUE WHERE `idempotency_key
  IS NOT NULL` — the deduplication index.
- `(created_at)` for time-window queries.

### 3.1 `event_type` taxonomy

The full taxonomy is owned by the implementation, not this doc. Conventions:

- `<subject>.<verb_past_tense>`: `decision.created`, `outcome.recorded`,
  `forecast.scored`, `playbook.proposed_version`, `memory_node.retained`,
  `edge.created`, `source.attached`, `playbook_rule.followed`,
  `playbook_rule.overridden`.
- One event per logical write. A `decision.created` event may cascade to a
  `position_event.appended` in the same transaction, producing two events.

## 4. The `outbox` Table

The outbox drives optional JSONL export to a directory the user has
configured. It is a queue, not a second source of truth: every outbox row
references an `events` row by ID.

| Column | Type | Purpose |
|---|---|---|
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Outbox row ID. |
| `event_id` | `INTEGER NOT NULL` | FK to `events.id`. |
| `export_kind` | `TEXT NOT NULL` | E.g. `jsonl`, future `parquet`, `webhook`. |
| `state` | `TEXT NOT NULL` | `pending`, `exported`, `failed`. |
| `exported_at` | `TEXT NULL` | When the row was successfully exported. |
| `error_text` | `TEXT NULL` | Last failure reason for `state = 'failed'`. |
| `attempt_count` | `INTEGER NOT NULL DEFAULT 0` | Number of export attempts so far. |

Indexes:

- `(state, export_kind, id)` for the exporter's "next batch" query.

### 4.1 Export semantics

- Outbox rows are inserted in the same transaction as their `events` row,
  only when the user has enabled JSONL export (`config.toml` flag).
- The exporter is invoked by an explicit CLI/MCP call
  (`export.drain --kind=jsonl`); there is no background daemon (see PRD
  §2.7).
- Successful export sets `state = 'exported'` and `exported_at`. Failed
  export increments `attempt_count` and records `error_text`.
- The exporter is idempotent: replaying an already-exported event re-writes
  the same JSONL row (file path includes `event_id`).

## 5. Idempotency Contract

### 5.1 Scope of the key

An `idempotency_key` is unique within `(event_type, actor_id)`. Two actors
may use the same key without collision; one actor may not.

The choice of scope is deliberate. Scoping by `event_type` alone risks
cross-actor collision when two agents pick the same UUID. Scoping by
`actor_id` alone risks an actor using the same key for two different event
types (e.g. creating both a decision and a forecast with key `"abc"`).
Scoping by the tuple is the smallest scope that prevents both.

### 5.2 Conflict behavior

On a write with `(event_type, actor_id, idempotency_key)` that already
exists in `events`:

- The server returns the **original event's result** with
  `meta.idempotent_replay: true` and `meta.event_id` set to the original
  event's ID.
- **No error.** Pure replay is success.

The only case that produces an error is when an existing
`(event_type, actor_id, idempotency_key)` row's `payload_json` is
semantically incompatible with the new payload. "Semantic equivalence" is
defined per `event_type`:

- For most types, byte-equal JSON after canonical key ordering is
  sufficient.
- For event types where the payload contains agent-generated free text
  (e.g. `memory_node.retained` with a `body` field), only structurally
  significant fields are compared; minor whitespace or LLM-generated
  rephrasing should not produce a conflict. The list of compared fields
  per event type is owned by the implementation.

When payloads are incompatible, the server returns `IDEMPOTENCY_CONFLICT`
(see [contracts.md](contracts.md)) with `details.original_event_id` and
`details.diff_summary`.

### 5.3 Absent idempotency keys

If a call omits `idempotency_key`, the server does not deduplicate. Each
call produces a new event row. This is documented as at-least-once
semantics for callers who explicitly want it (e.g. an importer that wants
every CSV row to land even if duplicates exist).

The MCP and CLI surfaces both default to **requiring** `idempotency_key`
for retryable writes; the absence path is opt-in via a documented flag.

## 6. Transaction Boundaries

A single tool call runs a single SQLite transaction containing all of:

1. The primary ledger write (e.g. `decisions` row).
2. Cascaded writes derived from the primary write (e.g. a
   `position_events` row for an `actual_enter` decision).
3. The `events` row.
4. The `outbox` row, if export is enabled.
5. Any projection updates that the implementation chooses to maintain
   eagerly (e.g. `positions`).

If any step fails, the entire transaction rolls back. The agent sees a
single error envelope; no partial state is committed.

Memory layer writes (`memory_nodes`, `edges`) get their own transactions.
They reference ledger IDs by value but never block on or coordinate with
ledger writes — a memory node about a decision can be written
seconds, minutes, or weeks after the decision itself.

## 7. Projections and Rebuild

The two projection tables in MVP are:

- `positions`: rebuildable from `position_events` and `snapshots`.
- `memory_node_stats`: rebuildable from recall event history (whose own
  event log table is `memory_recall_events`, defined alongside `events`
  but with a narrower schema; out of scope for this doc).

Admin command `journal.rebuild_projections`:

- Drops and rebuilds the chosen projection from its source tables.
- Runs inside one transaction so the rebuild is atomic.
- Reports `rebuilt_rows`, `dropped_rows`, and `duration_ms` in the success
  envelope.
- Is intended for recovery after corruption, schema upgrade, or projection
  bug; not part of normal operation.

## 8. Append-Only Invariants

Tests enforce:

- No `UPDATE` or `DELETE` statement runs against `events`, `outcomes`,
  `snapshots`, `decisions`, `position_events`, `forecast_scores`,
  `memory_nodes`, `edges`, or `outbox` (except `outbox.state` and
  `outbox.exported_at` updates by the exporter).
- Corrections to ledger rows create new rows with a `supersedes` edge or a
  table-specific `parent_*_id` reference.
- Replay of the event log against an empty database produces the same
  projection state as the original sequence.

## 9. Open Questions

1. **Per-actor sequence numbers.** Some downstream consumers (replay,
   stream sync) may want a per-`actor_id` monotonic sequence in addition
   to the global `events.id`. Likely P1; cheap to add later via a
   computed column or a side table.
2. **Outbox compaction.** Once an event is exported, do we keep the
   outbox row forever or compact it? Keep forever for MVP (cheap; useful
   for audit). Revisit if disk pressure shows up in dogfooding.
3. **Multi-writer concurrency.** SQLite WAL handles concurrent readers
   fine, but multi-writer is serialized. If multiple agents start writing
   to the same journal, do we want a connection-pool with retry/backoff,
   or do we move to a different engine? Out of scope for MVP.
4. **Cross-process event-stream subscribe.** An obvious P1 feature is a
   subscribe API (`events.subscribe`) that streams new events as they
   commit. Out of MVP.
