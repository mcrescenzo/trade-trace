# Operability: Time, Concurrency, Migrations, Logging, Limits

Status: clean planning draft. Date: 2026-05-18.

Companion docs: [PRD.md](../../PRD.md), [VISION.md](../../VISION.md),
[memory-layer.md](memory-layer.md), [persistence.md](persistence.md),
[scoring.md](scoring.md), [contracts.md](contracts.md),
[reports.md](reports.md), [imports.md](imports.md).

## 1. Purpose

PRD §5 references time-handling, multi-process behavior, migrations,
logging, blob caps, and on-disk format conventions, but never specifies
them in one place. This doc fills that gap.

The audience is implementers of Trade Trace and dogfooders deciding
whether to trust the system on their machine. Every section names a
specific behavior; "TBD" / "later" answers are not acceptable here.

## 2. Time and Bi-Temporal Semantics

### 2.1 Timezone

**All `*_at` columns are UTC ISO 8601 timestamps.** This is mandatory and
enforced at the schema/Pydantic-validator layer:

- Inputs without an offset are rejected with `VALIDATION_ERROR` and
  `details.field` set to the offending column.
- Inputs with a non-UTC offset are normalized to UTC at write time and
  stored as `Z`-suffixed strings (`2026-05-18T14:32:11Z`). The original
  offset is dropped; if the caller wanted to preserve "agent's local
  time" it should record it in `metadata_json`.
- Sub-second precision is preserved up to milliseconds; sub-millisecond
  digits are truncated. SQLite text-comparison ordering is stable on the
  canonical form.

### 2.2 "Now" resolution

The system clock is the source of "now." For test determinism, an
injectable `clock` is available to the implementation: tests fake `now`
to verify time-passing signals (`watch.stale`, `report.unscored_forecasts`)
and bi-temporal validity filters.

`now` is read at most once per tool call and cached for the duration of
the transaction; this ensures that a single call's reads of
`time_horizon_at <= now` and `valid_to > now` see the same `now`.

### 2.3 Bi-temporal model

PRD adds bi-temporal columns to belief-shaped tables (`theses`,
`forecasts`, `memory_nodes`). The semantics:

- `created_at` — when the system received the write. Transaction time.
  Append-only and immutable.
- `valid_from` — when the agent claims the belief began holding in the
  world. World time. Defaults to `created_at` if omitted.
- `valid_to` — when the agent claims the belief stopped holding. `NULL`
  means "ongoing until invalidated or superseded." Defaults: for
  `forecasts`, `resolution_at`; for `theses`, `time_horizon_at` if set,
  else `NULL`; for `memory_nodes`, `NULL`.
- `invalidated_at` — transaction time of invalidation. Set when a newer
  row explicitly invalidates this one, typically in the same transaction
  as a `supersedes` edge write.
- `invalidated_by` — FK to the superseding row (same table or, for
  forecasts, optionally to the resolving `outcomes` row).

The **as-of query primitive** is:

```sql
WHERE valid_from <= :as_of
  AND (valid_to IS NULL OR valid_to > :as_of)
  AND (invalidated_at IS NULL OR invalidated_at > :as_of)
```

`memory.recall` accepts `as_of` to apply this filter to the candidate set
before ranking ([memory-layer.md](memory-layer.md) §7). Other reports
(calibration, P&L) currently use transaction time only; as-of variants
are P1+ enhancements that compose cleanly because the underlying columns
are populated from M1.

### 2.4 Versioning vs invalidation

`parent_thesis_id` (theses) and `parent_node_id` (memory_nodes) thread
*versioning* relationships — a new version may continue, refine, or
contradict the prior. Versioning is non-destructive: prior versions
remain readable and queryable.

Invalidation (`invalidated_at`/`invalidated_by` + a `supersedes` edge)
is the **explicit** declaration that the prior row is no longer believed
to be true. A new version without an invalidation marker is read as "I
revised my view but the prior view was reasonable at the time."

## 3. Multi-Process Concurrency

### 3.1 Single-writer assumption

SQLite WAL mode handles concurrent readers but serializes writers. MVP
assumes one writer process at a time. The "single writer" granularity is
per-database-file, not per-table.

### 3.2 Second-writer behavior

When a second process attempts to acquire the write lock while the first
holds it:

- The default `busy_timeout` is **5 seconds**. SQLite retries internally
  during this window.
- If the lock is not acquired within the timeout, the failing write
  returns `STORAGE_ERROR` with `details.reason = "single_writer_lock"`,
  `details.held_by_pid` (if discoverable from filesystem locks), and
  `details.retry_after_seconds = <exponential-backoff hint, starting at 2>`.
- The agent is expected to back off and retry — the error envelope's
  `details.retry_after_seconds` is the recommended next-attempt wait.
- The contract surface treats `single_writer_lock` as a transient
  failure; the calling agent or CLI can simply retry after the hint.

Reads are never blocked by writers and never fail with
`single_writer_lock`.

### 3.3 Recall is a writer at the SQLite level

`memory.recall` appends to `memory_recall_events`, so it participates in
the single-writer assumption. The recall transaction is short (one row,
no cascades). In practice this only matters when a long-running write
holds the lock; in that case recall returns the same
`single_writer_lock` error with a short retry hint.

### 3.4 Multi-writer concurrency (deferred)

Connection-pool with retry/backoff, write-fan-out via a coordinator
process, or migration to a different engine are P1+ considerations. The
MVP commitment is that the single-writer contract is honest and
recoverable: a second writer never silently loses a write.

## 4. Migration Policy

### 4.1 Schema versioning

`schema_version` is an integer stored in a `meta` key-value table.
`journal.init` writes the current schema version; `journal.status`
reports it. Every migration script bumps the version by exactly one.

### 4.2 Forward-only

Migrations are forward-only. There is no automatic downgrade path.
Backups (§5) are the recovery story for "I want to roll back."

This is a deliberate constraint, not a missing feature. Reverse
migrations on append-only event/source tables are mostly impossible
without data loss; making the policy explicit avoids the trap of
"downgrade exists but is unsafe."

### 4.3 Enum extensions

Adding a value to an open enum (anywhere the schema documents the enum
as "open" — currently `signals.kind`, `event_type`, `import.source_kind`)
is a non-breaking schema change and does NOT require a migration script.
Adding a value to a closed enum (anywhere the docs say "closed enum" —
the error code list, `node_type`, the 7 edge types, `decisions.type`,
`outcomes.status`) IS a breaking contract change and requires:

1. A migration script (the value is added to the CHECK constraint).
2. A contract version bump.
3. A deprecation note in the changelog if any prior value is being
   removed in the same migration.

### 4.4 Column lifecycle

- **Adding a nullable column**: non-breaking. Single migration step.
- **Adding a non-nullable column with a default**: non-breaking. Two-step
  migration: add as nullable, backfill, switch to NOT NULL.
- **Removing a column**: breaking. Requires contract version bump and a
  one-version-window deprecation: the column is marked deprecated, kept
  populated for one schema version, then removed.
- **Renaming a column**: breaking. Implemented as add-new + dual-write +
  remove-old over two schema versions.

## 5. Backup and Restore

### 5.1 The `cp` story

The "complete backup is `cp trade-trace.sqlite`" promise in
[memory-layer.md](memory-layer.md) §2 has caveats. The honest version:

- **Safe** when no writer is active. The agent's tool calls are
  transactional; between calls, `cp` of the main file + WAL produces a
  consistent snapshot.
- **Safer**: `sqlite3 trade-trace.sqlite ".backup backup.sqlite"` works
  while writers are active. The WAL is reconciled into the backup at
  copy time. This is the documented backup path.
- **Unsafe**: a plain `cp` of just the `.sqlite` file while writers are
  active misses WAL contents. The product CLI surfaces `tt backup
  --to <path>` which wraps `.backup` correctly.

### 5.2 Outbox-mid-drain edge case

If the JSONL exporter is mid-drain when a backup is taken, the backup
captures committed outbox rows up to the snapshot boundary. The exporter
is idempotent (per [persistence.md](persistence.md) §4.1), so re-running
the drain after restore re-exports any rows the original drain hadn't
finished. JSONL output paths include `event_id`, so duplicate writes
overwrite the same file.

### 5.3 Restore

Restore is `tt restore --from <path>`. The command:

1. Validates the source DB's schema version is compatible (equal to or
   one less than the installed version; in the latter case, runs
   migrations after restore).
2. Atomically replaces the main DB file. The WAL is reset.
3. Re-runs `tt journal status` to verify the restored DB is reachable
   and consistent.

## 6. Logging

### 6.1 Log surface

Trade Trace uses Python's standard `logging` module. The package's
loggers are namespaced under `trade_trace.<module>`. By default:

- Console handler at `WARNING` level on stderr.
- Optional file handler at `INFO` level when
  `TRADE_TRACE_LOG_FILE=$path` is set. File path created with `0600`
  permissions where the platform supports it.
- `TRADE_TRACE_LOG_LEVEL` env var overrides the default level globally.

### 6.2 Structured log records

Every log record includes (where applicable):

- `request_id` (from the contract envelope)
- `actor_id`, `agent_id`, `model_id`, `environment`, `run_id`
- `tool` name
- `event_type` (when the log relates to a committed event)

These are attached via `logging.LoggerAdapter`; the log format is
JSON-line by default to make ingestion into local log tools trivial.

### 6.3 What MUST NOT be logged

- Embedding-provider API keys. Reads from keyring are never logged.
- `body`, `note`, `excerpt`, `extracted_text`, `summary` fields from
  sources, memory nodes, or theses at `INFO` or higher. (The DEBUG level
  may include them under explicit user opt-in via
  `TRADE_TRACE_LOG_INCLUDE_BODIES=1`.)
- `idempotency_key` values. They're useful for debugging, but they may
  be tied to the agent's own session identity.
- Anything matching common secret patterns (regex-scanned at log-write
  time): `sk-[A-Za-z0-9]{16,}`, `xoxb-[A-Za-z0-9-]+`,
  `0x[0-9a-fA-F]{40}` (Ethereum addresses), JWT-shaped tokens. Matches
  are redacted to `[REDACTED:<pattern>]` and the redaction is itself
  logged at `WARNING` (so dogfooders know their journal had a secret in
  it). See §7 for the secrets-in-notes risk.

## 7. Secrets in Notes (User-Facing Risk)

Agents can — and will — paste API keys, signed transactions, broker
URLs with credentials, or wallet addresses into `body`, `note`,
`reflection`, `source.note`, `memory_node.body`. The system cannot
prevent this without making the writes useless.

Mitigations:

- **Log-time scanning** (§6.3): pattern-redact before any secret-shaped
  string reaches a log.
- **Export-time warning**: `export.drain` and `review.bundle` scan
  outgoing payloads for the same patterns and emit a stderr warning
  with the matching event IDs. The export still proceeds; the warning
  is a "did you mean to ship these out?" check, not a block.
- **`sources.redaction_status = sensitive`**: writer-declared. Excluded
  from `review.bundle` unconditionally.
- **No remote-by-default surface**: there is no auto-sync, no
  telemetry, no remote backup. A secret stays on the local disk unless
  the user explicitly exports it.

Documented in the README and in `--human` startup hint on `tt journal
init` so dogfooders know the risk before pasting their first reflection.

## 8. Blob and Payload Caps

To avoid pathological writes that destabilize the DB or downstream
exports:

| Field | Cap | Behavior on overflow |
|---|---|---|
| `body` (memory_nodes, theses) | 64 KB | `VALIDATION_ERROR` with `details.field` and `details.actual_size` |
| `note`, `excerpt`, `summary` (sources) | 16 KB | same |
| `extracted_text` (sources) | 1 MB | same |
| `metadata_json`, `meta_json`, `payload_json` | 256 KB | same |
| `liquidity_depth_json` (snapshots) | 64 KB | same |
| `related_refs_json` (signals) | 16 KB | same |
| One JSONL outbox line | 1 MB | exporter emits a `signal.emitted` with `kind = "export_oversized"` and skips the line; the event row remains committed in the DB |
| `query_text` on `memory.recall` | 8 KB | `VALIDATION_ERROR` |
| `max_chars` on `memory.recall` | 64 KB cap (response envelope) | server caps at 64 KB and sets `meta.budget_applied` |

Caps are constants, not configurable. Future relaxation is a
non-breaking change.

## 9. JSONL Outbox File Format

### 9.1 File naming and rotation

- File path: `$TRADE_TRACE_HOME/export/jsonl/<YYYY>/<MM>/<DD>/<event_type>-<event_id>.jsonl`
- One line per event. Files are NOT rotated by size; each event has its
  own file. This is intentional: the importer (`import.commit`) can
  process a directory tree without parsing file boundaries.
- Atomic write: each file is written as `<name>.jsonl.tmp` then renamed
  to `<name>.jsonl` on success. Readers ignore `.tmp` files.

### 9.2 Line format

Each line is a single JSON object identical to the corresponding
`events` row's `payload_json` field, with these additional keys:

- `_event_id` (integer) — the source `events.id`.
- `_event_type` (string) — copy of the row's `event_type` for
  self-description.
- `_actor_id` (string).
- `_created_at` (UTC ISO 8601).
- `_contract_version` (string, e.g. `"1.0"`).

Underscore-prefixed keys are reserved for transport metadata; domain
fields never start with underscore. This makes JSONL files
self-describing and replayable through `import.commit` without external
schema. See [imports.md](imports.md) §2.

### 9.3 Encoding

UTF-8, no BOM, LF line endings (`\n`). On Windows the writer still emits
LF to keep cross-platform replay deterministic. JSON inside a line uses
RFC 8259-conformant escaping.

### 9.4 Disk-full behavior

The exporter writes lock-free per-file. On `ENOSPC`:

- The `outbox` row's `state` flips to `failed`, `error_text` records
  `"disk_full"`, `attempt_count` increments.
- The exporter emits a `signal.emitted` with `kind = "export_disk_full"`
  and `severity = "critical"`.
- Subsequent `export.drain` invocations resume from the failed row once
  disk pressure clears.

## 10. Crash Recovery

### 10.1 WAL recovery

SQLite WAL is robust to crashes mid-transaction; the partial transaction
is rolled back automatically on the next open. No special handling
required at the Trade Trace layer.

### 10.2 WAL corruption

If `journal.init` or any tool call detects a corrupted WAL:

- Return `STORAGE_ERROR` with `details.reason = "wal_corruption"` and
  `details.hint = "run 'tt journal repair' or restore from backup"`.
- `tt journal repair` attempts SQLite's `.recover` against the main
  database file. Successful repair recovers committed transactions and
  drops any in-flight transaction. Failed repair surfaces the recovery
  error and recommends restore.

### 10.3 Exporter resume

The exporter is idempotent (§9, [persistence.md](persistence.md) §4.1).
If the process is killed mid-drain, the next `export.drain` invocation
re-tries rows in `state = 'pending'` or `state = 'failed'` (with
`attempt_count` capped at 10 before the row is left in `failed` state
and surfaced via signal).

### 10.4 Rebuild after schema upgrade

`journal.rebuild_projections` (per
[persistence.md](persistence.md) §7) is the recovery path after a
schema upgrade that changes a projection's shape. It is safe to run
while writers are active (the rebuild is serialized behind the
single-writer transaction) but slower; the recommended workflow is to
take the writer offline for the rebuild.

## 11. Open Questions

1. **Configurable busy_timeout.** §3.2 fixes a 5-second `busy_timeout`.
   If multi-agent dogfooding shows the contention rate matters, expose
   it as a config knob.
2. **Compression of `extracted_text`.** §8 caps `extracted_text` at 1
   MB. If dogfood shows research-doc ingestion bumps the cap regularly,
   compress at the storage layer (zstd) transparently. Additive,
   non-breaking.
3. **Secret scanning regex set.** §6.3 lists four patterns. The set
   should grow as we see leaks in dogfood. Adding patterns is
   non-breaking; tightening them risks false positives. Track regressions
   via signal-emitted events.
