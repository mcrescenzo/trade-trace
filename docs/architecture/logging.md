---
status: active
owners: trade-trace
last_reviewed: 2026-05-19
bead: trade-trace-3zvl
---

# Operational Logging Contract

> Status: **partial — see §Module shape for the shipped subset**.
> The `trade_trace.logging` module is implemented and `drain_outbox`
> emits operational logs through it. Backfill into remaining tool
> call sites is opportunistic, not required for the MVP.

## Why this exists

Trade Trace today has **no centralized operational logging**. The
package ships an MCP server (stdout reserved for JSON-RPC; stderr is
the protocol error channel) and a CLI. There is no rotation, no
format convention, no file path layout, no redaction rule, and no
single place a console or oncall reader can grep.

This document fixes that. It is also a prerequisite for the
Console Logs page (`trade-trace-jtec`); the Console is a *reader*
of the contract — it does not extend it.

## Scope

In:

- File format and field set for operational log lines.
- Level conventions.
- Path layout, rotation, and retention defaults.
- stderr-vs-file rules for MCP server and CLI processes.
- Redaction posture.
- The thin `trade_trace.logging` module that emits log lines.

Out:

- Cloud log shipping or external aggregators.
- The Console Logs page UX.
- Backfilling every existing tool call site (opportunistic).

## Format

JSONL, one record per line. Each line is a flat JSON object with
these reserved keys:

| Key          | Type    | Notes |
|--------------|---------|-------|
| `ts`         | string  | UTC ISO 8601 with millisecond precision (`2026-05-19T21:30:00.000Z`). |
| `level`      | string  | One of `DEBUG`, `INFO`, `WARN`, `ERROR`. |
| `actor`      | string  | Mirror of the dispatch `actor_id` if known (`cli:default`, `agent:mcp-default`); else module name. |
| `subject`    | string  | Optional; the entity kind being acted on (`event`, `outbox`, `tool`, `migration`). |
| `verb`       | string  | Optional; short identifier for what's happening (`dispatch`, `commit`, `drain`, `error`). |
| `record_id`  | string  | Optional; the primary id being operated on (`event_id`, `outbox_id`, `request_id`). |
| `message`    | string  | Human-readable summary; safe to ship in alerts. |
| `tool`       | string  | Optional; canonical tool name (`memory.retain`) when the line is inside a dispatch. |
| `request_id` | string  | Optional; copy of `meta.request_id` so cross-line correlation works. |

Producers MAY add arbitrary additional keys. Readers MUST NOT
assume any field beyond the table above is present. Field-level
redaction (see below) applies to all keys, not just `message`.

## Levels

| Level | When to use |
|-------|-------------|
| DEBUG | Verbose detail useful in local dev. Off by default in production. |
| INFO  | Normal operations: dispatch boundary, outbox drain, migration run. |
| WARN  | Recoverable anomalies: failed export attempt, retry, degraded subsystem. |
| ERROR | Operation failed and surfaced to caller; pre-existing fault that needs operator attention. |

The package itself emits at INFO or higher. Tests and tooling MAY
emit DEBUG.

## Path layout

```
<home>/logs/
    trade-trace.log          # current file (newest writes here)
    trade-trace.log.1
    trade-trace.log.2
    ...
```

`<home>` resolves via the existing `resolve_home()` helper. The
operator can override the directory by setting
`TRADE_TRACE_LOG_DIR`. If the directory does not exist on first
write, the module creates it with mode `0o700` to match the rest
of the home tree (`security.md` §3.1).

## Rotation and retention

- Size-based via `logging.handlers.RotatingFileHandler`.
- Default rotation size: 5 MiB per file.
- Default backup count: 5 (so the operator keeps ~25 MiB of recent
  history before the oldest file is overwritten).
- Both knobs are environment-overridable:
  `TRADE_TRACE_LOG_MAX_BYTES`, `TRADE_TRACE_LOG_BACKUP_COUNT`.
- Files are written with mode `0o600`.

## stderr vs. file

| Process mode | File handler | stderr handler |
|--------------|--------------|----------------|
| MCP server (`trade-trace mcp serve`) | yes | **never** — stderr is reserved for the MCP SDK's protocol error channel. |
| CLI (everything else) | yes | yes, at WARN+ by default. |

The module detects MCP mode by checking the environment variable
`TRADE_TRACE_TRANSPORT` (set to `mcp` by `mcp_server.run()` before
the first log line is emitted). The detection is explicit so the
test harness can flip it on demand.

If the file handler can't be opened (e.g. read-only home), the
module degrades silently in MCP mode and prints a single startup
warning to stderr in CLI mode. Operational logging must never raise
into the request path.

## Redaction

The operational log is a security boundary the same way the JSONL
exporter is (`security.md` §6, `exporter.scan_for_secrets`). Each
emitted record runs through the existing
`security.patterns.scan_for_secrets` adapter; matched substrings
are redacted in-place with `***` before the record is written.

The redactor runs over every string value in the record, including
nested values in `extra` fields the caller passes through. A
redacted line still goes to disk — the operator wants to see *that*
something matched, not the match itself.

## Module shape

`trade_trace.logging` exposes one public function:

```python
def get_logger(name: str) -> logging.Logger:
    """Return a configured stdlib logger with the project's
    JSONL formatter + rotation handlers attached. Idempotent —
    repeat calls return the same logger."""
```

Internally it:

1. Resolves `<home>/logs/trade-trace.log` (or `TRADE_TRACE_LOG_DIR`).
2. Attaches a single `RotatingFileHandler` per process.
3. Attaches a stderr `StreamHandler` only when not in MCP mode.
4. Installs a `JSONLFormatter` that maps `LogRecord.__dict__` into
   the JSONL schema in §Format and runs redaction.
5. Caches the returned `Logger` so reconfiguration is a no-op.

Tools call it the same way every Python module calls stdlib
logging:

```python
from trade_trace.logging import get_logger

log = get_logger(__name__)
log.info("draining outbox", extra={"subject": "outbox", "verb": "drain", "record_id": str(outbox_id)})
```

## Test coverage

The module ships with unit tests pinning:

- JSONL line shape (every required key, no extras leak).
- Redaction strips ethereum addresses, API keys, etc.
- MCP mode does not attach a stderr handler.
- Rotation is triggered by size; backup count is honored.
- Repeat `get_logger` calls do not double-attach handlers.
- Tools that emit through `get_logger` write to the expected path.

End-to-end coverage: at least one existing tool path (the JSONL
exporter `drain_outbox`) emits an INFO line on success and a WARN
on a per-row failure.

## Open questions

- Time-based rotation (daily) may be more useful for human readers
  than size-based; revisit after the Console Logs page lands and
  we see how operators actually grep these files.
- Should the module register a JSON Schema for the line shape?
  Deferred — the contract above is the source of truth until a
  schema-driven consumer demands one.
