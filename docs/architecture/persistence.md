# Persistence: Events, Outbox, and Idempotency

> Status: **shipped**. Events / outbox / idempotency contracts as implemented today.

Status: clean planning draft. Date: 2026-05-18.

**Implementation status (M0-M4 MVP):** every contract here ships — events
table + outbox + closed event-type enum (per bead trade-trace-0r1),
idempotency-key replay, JSONL atomic write, append-only triggers across
M1+M3+M4 tables, projection rebuild (positions + memory_node_stats).

Companion docs: [PRD.md](../PRD.md), [VISION.md](../VISION.md),
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
MVP; multi-writer behavior is specified in [`operability.md`](operability.md)
§3.

### 2.1 SQLite build dependencies

Two SQLite-build features are **required** (not optional) for the
journal to migrate cleanly:

- **WAL mode** — set on every connection via `PRAGMA journal_mode = WAL`.
  All modern SQLite builds support it.
- **FTS5** — virtual-table extension powering the BM25 backbone of
  `memory.recall`. Migration 006 preflights FTS5 availability and
  aborts with a typed `FTS5UnavailableError` carrying remediation
  text if the build lacks it (bead trade-trace-qis). Most CPython
  distributions on Linux/macOS/Windows ship FTS5 by default; the
  failure path generally only hits minimal Alpine/musl builds. The
  remediation is to install a SQLite (or Python distribution)
  compiled with `-DSQLITE_ENABLE_FTS5`.

`sqlite-vec` (the vector backend used by the embeddings opt-in path) is
**optional**: when missing the embeddings strategy is silently
unavailable, but the rest of the recall pipeline keeps working.

Three classes of table:

- **Source/event tables** (`events`, `outcomes`, `snapshots`, `theses`,
  `forecasts`, `forecast_outcomes`, `decisions`, `decision_tags`,
  `decision_playbook_rules`, `position_events`, `forecast_scores`,
  `memory_nodes`, `memory_recall_events`, `signals`, `edges`, `outbox`)
  are append-only. Corrections create new rows; older rows stay
  readable for audit. The append-only invariant is tested per §8.
- **Mutable metadata tables** (`venues`, `instruments`, `playbooks`,
  `strategies`) hold low-volume reference data whose `description`,
  `hypothesis`, or `status` fields may change over the life of the row.
  Every change writes a corresponding `<subject>.updated` event in the
  `events` log, so the audit trail is preserved even though the row
  itself is mutated in place. There is no separate version table for
  these entities at MVP (see PRD §11 for the deferred decisions).
- **Projection tables** (`positions`, `memory_node_stats`) are rebuildable
  from source data via `journal.rebuild_projections`. They exist for query
  performance, not authority.

`memory_node_embeddings` is a special case: it is logically append-only but
the embedding `BLOB` for a given `(memory_node_id, provider)` may be
replaced via DELETE+INSERT inside one transaction during a re-embed pass
(see [`memory-layer.md`](memory-layer.md) §8.4). This is the only DELETE
permitted on a memory-side table and is gated behind explicit user action.

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
| `actor_id` | `TEXT NOT NULL` | `agent:default`, `cli:user`, `import:<name>`, etc. Per PRD §2 grammar. |
| `idempotency_key` | `TEXT NULL` | Caller-supplied retry key (see §5). Required by default for retryable writes per PRD §2. |
| `created_at` | `TEXT NOT NULL` | UTC ISO 8601 timestamp. Mandatory UTC per [`operability.md`](operability.md) §2.1. |
| `request_id` | `TEXT NULL` | Per-call request ID echoed in the response envelope. |
| `agent_id` | `TEXT NULL` | Optional segmentation; logical trading-agent identifier. PRD §2. |
| `model_id` | `TEXT NULL` | Optional segmentation; model/family identifier. PRD §2. |
| `environment` | `TEXT NULL` | Optional segmentation; `paper`/`actual_recorded`/`simulation`/`backtest_import`/`manual_review`. PRD §2. |
| `run_id` | `TEXT NULL` | Optional segmentation; agent run/session identifier. PRD §2. |

Indexes:

- `(subject_kind, subject_id)` for lookups like "all events about this
  decision".
- `(event_type, actor_id, idempotency_key)` UNIQUE WHERE `idempotency_key
  IS NOT NULL` — the deduplication index.
- `(created_at)` for time-window queries.

### 3.1 `event_type` taxonomy

Conventions:

- `<subject>.<verb_past_tense>`: `decision.created`, `outcome.recorded`,
  `forecast.scored`, `forecast.superseded`, `playbook.proposed_version`,
  `memory_node.retained`, `memory_node.invalidated`, `edge.created`,
  `source.attached`, `playbook_rule.followed`, `playbook_rule.overridden`,
  `strategy.created`, `strategy.updated`, `signal.emitted`,
  `import.row_committed`.
- One event per logical write. A `decision.created` event may cascade to a
  `position_event.appended` in the same transaction, producing two events.
- Adding a new `event_type` is a non-breaking schema extension. Removing or
  renaming one is a breaking change requiring a contract version bump. Per
  [`operability.md`](operability.md) §4 (migration policy), the migration
  framework treats `event_type` as an open enum.

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
  only when the user has enabled JSONL export via the
  `outbox.jsonl_enabled` key (set with `tt journal config_set`).
- The drain is invoked programmatically via `drain_outbox()` in
  `src/trade_trace/exporter.py`; there is no background daemon (see
  PRD §2.7). An explicit `export.drain` CLI/MCP tool surface is
  deferred to a future export-tool bead — today the drain runs
  inside the test/dogfood suites and is reachable from a Python
  shell.
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
defined per `event_type`. The MVP comparison policy is:

| Class | Comparison |
|---|---|
| Structured writes with no free text (e.g. `decision.created`, `forecast.created`, `forecast_outcome.created`, `outcome.recorded`, `position_event.appended`, `playbook_rule.followed/overridden`, `edge.created`, `source.attached`) | Byte-equal JSON after canonical key ordering and after stripping the `actor_id`, `created_at`, `request_id` fields (which the server fills). |
| Free-text writes (`memory_node.retained`, `memory_node.invalidated`, `thesis.created`, `signal.emitted`, `source.added` for free-text sources, `strategy.created`, `strategy.updated`) | Compare a fixed structural-field set per event type, ignoring free-text fields (see §5.2.1). Minor whitespace and LLM rephrasing on the free-text fields are tolerated. The per-event-type structural-field set is enumerated in the `events_semantic_keys.py` registry in code (trade-trace-kvn). Adding to the list is a non-breaking change; removing or changing a key requires a contract version bump. |
| Importer writes (`import.row_committed`) | Compare on `(import_run_id, source_row_number)` only; the row payload is treated as the entire row identity. |

### 5.2.1 Per-event-type structural-field minimum set

The registry implementation (trade-trace-kvn) MUST encode at least the
fields below per event type. Free-text fields are explicitly excluded
from comparison (LLM-rephrasing tolerance). This list is the MVP
contract; additions are non-breaking.

| `event_type` | Structural fields (compared) | Free-text fields (ignored) |
|---|---|---|
| `decision.created` | `instrument_id`, `type`, `thesis_id`, `forecast_id`, `snapshot_id`, `side`, `quantity`, `price`, `fees`, `slippage`, `playbook_version_id`, `review_by`, `strategy_id`, sorted `tags[]` | `reason` |
| `outcome.recorded` | `instrument_id`, `resolved_at`, `outcome_label` (lower-cased), `outcome_value`, `status`, `source`, `confidence` | `metadata_json.note` if present |
| `forecast.created` | `thesis_id`, `kind`, `resolution_at`, `yes_label`, sorted `outcomes[*].outcome_label` (lower-cased), `outcomes[*].probability`, `outcomes[*].lower_bound`, `outcomes[*].upper_bound` | `resolution_rule_text` |
| `forecast.scored` | `forecast_id`, `outcome_id`, `metric`, `score`, `scored_at`, `metadata_json.failure_reason` | (none — no free text) |
| `forecast.superseded` | `prior_forecast_id`, `new_forecast_id` | (none) |
| `playbook.proposed_version` | `playbook_id`, `version`, `parent_version_id`, `provenance_reflection_node_id` | (none) |
| `playbook_rule.followed` | `decision_id`, `playbook_version_id`, `rule_node_id`, `status="followed"` | `reason` |
| `playbook_rule.overridden` | `decision_id`, `playbook_version_id`, `rule_node_id`, `status="overridden"` | `reason` |
| `memory_node.retained` | `node_type`, `parent_node_id`, `version`, `confidence_base`, `decay_rate_per_day`, `importance`, `valid_from`, `valid_to`, sorted `tags[]`, structural `meta_json` keys (scoping fields like `instrument_id`/`venue_id`/`asset_class`/`pattern_kind`/`playbook_version_id`/`rule_meta`; free-text `meta_json` values excluded) | `title`, `body`, `meta_json.note` |
| `memory_node.invalidated` | `memory_node_id`, `invalidated_by`, `invalidated_at` (truncated to millisecond) | (none) |
| `edge.created` | `source_kind`, `source_id`, `target_kind`, `target_id`, `edge_type`, `weight` | (none) |
| `source.attached` | `source_id`, `target_kind`, `target_id`, `edge_type` (derived from `sources.stance`) | (none) |
| `strategy.created` | `slug` (lower-cased), `name`, `status="active"` (server-set) | `description`, `hypothesis` |
| `strategy.updated` | `strategy_id`, `status` (when changed) | `description`, `hypothesis` |
| `signal.emitted` | `kind`, `severity`, `actor_id`, sorted `related_refs_json[]` (deterministic-ordered by `{kind, id}`), `expires_at` | `body`, `meta_json.note` |
| `import.row_committed` | `import_run_id`, `source_row_number` (entire payload identity per §5.2 row 3) | the whole row payload (treated as identity by the import_run_id pair) |

Comparison rules common to every event type:
- Server-filled fields (`actor_id`, `created_at`, `request_id`,
  `event_id`) are excluded from comparison.
- Timestamp fields included in the structural set are compared after
  truncation to millisecond precision per
  [`operability.md`](operability.md) §2.1.
- Array fields are compared after deterministic sorting on the
  documented key(s); the registry encodes the sort key.
- Optional fields that are absent vs. set to `null` compare equal.
- An unregistered `event_type` is a startup error (default-deny): a
  writer cannot land a new event class without an explicit registry
  entry. This guards against silent contract drift.

When payloads are incompatible, the server returns `IDEMPOTENCY_CONFLICT`
(see [contracts.md](contracts.md)) with `details.original_event_id`,
`details.diff_summary` (a structural diff, never raw payload bodies, to
avoid leaking sensitive content), and `details.compared_keys` (the
structural-key set used for the comparison, so the caller can audit which
fields were considered).

### 5.3 Absent idempotency keys

If a call omits `idempotency_key`, the server does not deduplicate. Each
call produces a new event row. This is documented as at-least-once
semantics for callers who explicitly want it (e.g. an importer that wants
every row to land even if duplicates exist).

The MCP and CLI surfaces both **require `idempotency_key` for retryable
writes by default.** The absence path is opt-in via an explicit flag:

- CLI: `--allow-no-idempotency` (long-form only; no short form to discourage
  accidental use).
- MCP: `_allow_no_idempotency: true` in the tool's args object (underscore
  prefix marks it as a transport-level argument, not a domain field).

When the flag is absent and `idempotency_key` is omitted on a retryable
write, the server returns `VALIDATION_ERROR` with
`details.field = "idempotency_key"` and `details.hint = "missing required
idempotency_key; pass --allow-no-idempotency to opt into at-least-once
semantics"`. Read tools, list tools, and admin tools do not require a key
and never raise this error.

The full list of "retryable writes" is exactly the §4.0 core write tools
(PRD): `venue.add`, `instrument.add`, `snapshot.add`, `thesis.add`,
`forecast.add`, `forecast.supersede`, `decision.add`, `outcome.add` /
`resolve.record`, plus `memory.retain`, `memory.reflect`, `memory.link`,
`source.add`, `source.attach_to_*`, `playbook.create`,
`playbook.propose_version`, `strategy.create`, `strategy.update`,
`import.commit`.

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
- `memory_node_stats`: rebuildable from `memory_recall_events`. The
  `memory_recall_events` table is defined in PRD §3.2; it is append-only
  and shares the persistence semantics of `events` (committed in the same
  transaction as the recall response).

A recall call (`memory.recall`) is a read tool from the agent's perspective
but appends to `memory_recall_events` as a side effect to drive the
projection. The recall transaction includes the read query and the
`memory_recall_events` row. This makes recall a writer at the SQLite level
and is the one case where a nominally-read tool participates in the
single-writer assumption ([`operability.md`](operability.md) §3). The
write is small (one row per recall call) and bounded.

Admin command `journal.rebuild_projections`:

- Accepts `projection: "positions" | "memory_node_stats" | "all"`
  (required; default would be ambiguous).
- Drops and rebuilds the chosen projection from its source tables.
- Runs inside one transaction so the rebuild is atomic.
- Reports `rebuilt_rows`, `dropped_rows`, and `duration_ms` in the success
  envelope.
- Is intended for recovery after corruption, schema upgrade, or projection
  bug; not part of normal operation. Concurrent writes during a rebuild
  are serialized behind the single-writer transaction per
  [`operability.md`](operability.md) §3.

## 8. Append-Only Invariants

Tests enforce:

- No `UPDATE` or `DELETE` statement runs against `events`, `outcomes`,
  `snapshots`, `theses`, `forecasts`, `forecast_outcomes`, `decisions`,
  `decision_tags`, `decision_playbook_rules`, `position_events`,
  `forecast_scores`, `memory_nodes`, `memory_recall_events`, `signals`,
  `edges`, or `outbox`. Specific exemptions:
  - `outbox.state`, `outbox.exported_at`, `outbox.error_text`,
    `outbox.attempt_count` updates by the exporter.
  - `memory_node_stats` (a projection) is freely mutable; the projection
    rebuild path drops and re-inserts the whole table.
  - `memory_node_embeddings` allows DELETE+INSERT inside one re-embed
    transaction per [`memory-layer.md`](memory-layer.md) §8.4 (the only
    permitted memory-side DELETE).
- Corrections to ledger rows create new rows with a `supersedes` edge.
  This is the **single canonical correction mechanism** for all
  append-only tables — there is no `parent_*_id` correction column on
  ledger tables. (`theses.parent_thesis_id` is a *versioning* column that
  threads thesis revisions; it is not a correction mechanism. Versioning
  and correction are distinct: a new version may emit a `supersedes` edge
  to the prior version; a correction MUST emit one.)
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
3. **Cross-process event-stream subscribe.** An obvious P1 feature is a
   subscribe API (`events.subscribe`) that streams new events as they
   commit. Out of MVP.

Closed in this pass (no longer open): multi-writer behavior is specified
in [`operability.md`](operability.md) §3 (second writer receives
`STORAGE_ERROR` with `details.reason = "single_writer_lock"` and an
exponential backoff hint); the implementation-owned semantic-equivalence
list for `IDEMPOTENCY_CONFLICT` is enumerated in §5.2 above.
