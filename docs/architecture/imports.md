# Imports: Local JSONL and CSV

Status: implementation-era semantics. Date: 2026-05-19.

**Implementation status:** `import.validate` and `import.commit` are real
JSONL replay tools. Validation parses files or directories, checks line
shape, import-ready tool names, ID strategy, forward references, and the
underlying tool schemas by replaying into an isolated staged home. Commit
replays through the same core dispatcher used by MCP/CLI. The shipped JSONL
export path (outbox drain) is the replay-input format; underscore-prefixed
export transport metadata is ignored on input.

Companion docs: [PRD.md](../../PRD.md), [persistence.md](persistence.md),
[contracts.md](contracts.md), [operability.md](operability.md).

## 1. Purpose

PRD §4.7 specifies the canonical local-ingestion path: replay
tool-shaped JSONL through the same handlers that back MCP and CLI
calls. This doc nails down the file format, dry-run semantics,
idempotency behavior, error reporting, and the boundary that keeps
imports from becoming a broker-sync surface.

The implementation now includes the JSONL importer described here:
every import-ready write tool from PRD §4.0 is callable by the importer
with the same validation, idempotency, and event emission as MCP/CLI.

## 2. JSONL Format

### 2.1 Line shape

Each line is a single JSON object:

```json
{"tool": "decision.add", "args": {"instrument_id": "i_...", "type": "skip", "reason": "spread too wide", "actor_id": "import:run-2026-05", "idempotency_key": "csv-row-42"}}
```

Required fields:

- `tool`: the canonical MCP tool name for an import-ready writer. Current
  allowlist: `venue.add`, `instrument.add`, `snapshot.add`, `thesis.add`,
  `forecast.add`, `forecast.supersede`, `decision.add`, `outcome.add`,
  `resolve.record`, `source.add`, `source.attach_to_thesis`,
  `source.attach_to_decision`, `source.attach_to_forecast`,
  `playbook.create`, `playbook.propose_version`, `strategy.create`,
  `strategy.update`. Recursive import tools, read/report/admin/journal
  tools, and other non-allowlisted tools are rejected with
  `VALIDATION_ERROR`.
- `args`: the tool's args object, identical to the in-process call.

`args.actor_id` is required. `args.idempotency_key` is required unless
the importer is invoked with `--allow-no-idempotency` (per
[persistence.md](persistence.md) §5.3).

The exporter (JSONL outbox per [operability.md](operability.md) §9)
emits a superset shape: each line additionally carries
`_event_id`, `_event_type`, `_actor_id`, `_created_at`,
`_contract_version`. The importer **ignores** underscore-prefixed keys
on input; the exporter's output is therefore directly replayable by
the importer without preprocessing.

### 2.2 Line ordering

Order matters when one row references another (an `instrument.add`
event before a `snapshot.add` that references its `id`). The importer
processes lines in file order within a single file, and files in
sorted-by-path order across a directory. Forward references are
**rejected** at validate time (`VALIDATION_ERROR` with
`details.referenced_id_not_yet_defined`) rather than buffered, so an
exporter-produced sequence (which is `created_at`-ordered) is always
importable.

### 2.3 ID handling

Two paths:

- **Server-assigned IDs (recommended for fresh imports)**: omit `args.id`.
  The importer generates new IDs server-side. The line's
  `idempotency_key` is the stable handle for retries.
- **Caller-assigned IDs (recommended for replaying an existing journal,
  e.g. exporter output)**: include `args.id`. The importer uses the
  provided ID. If the ID already exists with a semantically different
  payload, the importer returns `IDEMPOTENCY_CONFLICT` for that row.

The two paths cannot be mixed within one file; the importer detects
mixing and emits `VALIDATION_ERROR` at validate time.

## 3. CLI and MCP Surface

### 3.1 Tools

- **`import.validate(path, *, max_errors?, mode?)`** — dry-run. Parses
  the file or directory, validates every line against the tool's
  schema, checks intra-file ID references, and reports what would
  happen without writing. Returns:

  ```jsonc
  {
    "ok": true,
    "data": {
      "validated": 120,
      "would_create": 118,
      "would_replay": 2,                // duplicate idempotency_keys
      "errors": [
        {"line": 47, "tool": "decision.add", "code": "VALIDATION_ERROR",
         "details": {"field": "quantity", "reason": "forbidden for type=skip"}}
      ],
      "warnings": [
        {"line": 31, "warning": "missing optional source attachment"}
      ],
      "id_strategy": "server_assigned"   // or "caller_assigned"
    }
  }
  ```

  `max_errors` (default 100) caps the error list; over-cap, the tool
  emits `meta.truncated: true`.

- **`import.commit(path, *, halt_on_error?, transaction_mode?,
  max_errors?)`** — write path.
  - `halt_on_error` (default `true`): stop at first error; partial
    progress (committed rows so far) is reported.
  - `transaction_mode` (default `single`): `single` stages the import in a
    temporary copy of the Trade Trace SQLite database and atomically replaces
    the real DB files only after every row succeeds; on validation or runtime
    row failure, the staged home is discarded and the real DB is left
    unchanged. `per_row` dispatches each row directly to the target home,
    allowing partial progress according to `halt_on_error`.

  Returns the same envelope as `validate` plus `committed_event_ids`
  and `committed_count`. Re-running the same file is safe: rows whose
  `idempotency_key` matches an existing event are replayed (`replay`
  count incremented).

### 3.2 CLI mapping

```bash
trade-trace import validate --file path/to/events.jsonl
trade-trace import validate --dir path/to/jsonl_tree
trade-trace import commit --file path/to/events.jsonl
trade-trace import commit --dir path/to/jsonl_tree --transaction-mode per_row
```

## 4. CSV Fills Import (P1)

For execution-level (per-fill) CSV input, the importer accepts an
explicit column-mapping file. There is **no auto-inference** of
broker-specific schemas; if the user wants broker compatibility, they
either author a mapping file or run a separate adapter that emits
Trade Trace JSONL.

### 4.1 Required columns

After applying the mapping, every row must produce:

- `instrument_external_id` OR `instrument_id`
- `executed_at` (UTC ISO 8601)
- `side` (one of `decisions.side` enum values, plus `buy`/`sell` aliases
  for buy = `long` direction increase, sell = `long` direction decrease
  or `short` increase per signed-quantity convention)
- `quantity`
- `price`

Optional: `fees`, `slippage`, `account_label` (goes to
`metadata_json.account_label`), `strategy_slug`, `tags`.

### 4.2 Mapping file format

```json
{
  "instrument_external_id": "Symbol",
  "executed_at": {"column": "DateTime", "format": "%m/%d/%Y %H:%M:%S", "timezone": "America/New_York"},
  "side": {"column": "Action", "values": {"BTO": "long", "STC": "long", "STO": "short", "BTC": "short"}},
  "quantity": "Quantity",
  "price": "Price",
  "fees": {"column": "Commission", "default": 0},
  "tags": {"static": ["import:broker-x-2026-q2"]}
}
```

Mapping rules:

- Plain string ⇒ source column name.
- Object with `column` + optional `format`/`timezone` ⇒ explicit parsing
  (used for timestamps).
- Object with `column` + `values` ⇒ enum value mapping.
- Object with `column` + `default` ⇒ source column with fallback if
  missing/empty.
- Object with `static` ⇒ constant value applied to every row.

### 4.3 Round-tripping to JSONL

The CSV importer's first step is to emit a JSONL file (one
`decision.add` line per fill, joined with a `position_event` line where
needed) and then invoke `import.commit` against it. The JSONL artifact
is preserved on disk under `$TRADE_TRACE_HOME/import/csv/<timestamp>/`
as the audit trail for the CSV ingestion. This keeps the CSV path
thin: all schema enforcement lives in JSONL import.

### 4.4 Idempotency for CSV

CSV rows lack natural idempotency keys. The importer derives:

`idempotency_key = sha1("{import_run_id}:{source_row_number}")` truncated
to 32 hex chars. The `import_run_id` is set by the importer at
invocation time (default: ISO timestamp; override via
`--run-id`). Re-running the same CSV file with the same `import_run_id`
is a clean replay.

## 5. Error Reporting

All importer errors use existing error codes from
[contracts.md](contracts.md). Per-row context is attached via
`details`:

```jsonc
{
  "code": "VALIDATION_ERROR",
  "message": "decisions.type=skip cannot carry a quantity",
  "details": {
    "line": 47,
    "file": "events.jsonl",
    "tool": "decision.add",
    "field": "quantity",
    "value": 100
  }
}
```

No import-specific error codes are introduced. Reusing
`VALIDATION_ERROR`, `INVARIANT_VIOLATION`, `IDEMPOTENCY_CONFLICT`,
`NOT_FOUND`, and `STORAGE_ERROR` covers every observed failure mode.

## 6. Boundaries (What Imports Are NOT)

- **Not broker sync.** Trade Trace never reaches out to a broker. CSV
  files come from the user; JSONL files come from the user or a prior
  Trade Trace export. The importer never makes outbound calls
  (per PRD §2.4 / §2.4.1).
- **Not credential ingestion.** API keys, broker tokens, wallet
  signatures, and seed phrases are rejected by every write schema. A
  CSV column mapping that targets a credential-shaped field is
  rejected at mapping-load time.
- **Not a generic ETL.** The importer assumes lines are Trade Trace
  tool calls. CSV with non-execution shapes (positions, P&L summaries,
  account statements) is not supported; the agent computes those from
  the imported fills.

## 7. Open Questions

1. **Parallel commit.** §3.1 wraps a file in one transaction by default;
   large files may benefit from chunked parallel commits. SQLite's
   single-writer model bounds the gain; defer until dogfood shows it
   matters.
2. **Streaming validate.** Very large files (>1 GB) won't fit in memory
   if `import.validate` collects all errors. Behavior today: stream
   validate, emit up to `max_errors`, then truncate. Configurable
   chunked-buffer mode is a P1 candidate.
3. **Cross-file dedup.** Identical idempotency keys across files in a
   directory tree replay safely. If two different files contain the
   same key with different payloads, the second triggers
   `IDEMPOTENCY_CONFLICT` mid-commit; the recovery path is to fix the
   source file. No silent "first writer wins" behavior.
