# Trade Trace Console — User Guide

> Status: **shipped**. The Console is the optional `[console]`
> extra; the base install does not require it (trade-trace-1kkv).

## What it is

A **local, read-only** review dashboard for the Trade Trace
journal. It runs `http://127.0.0.1:8765` by default, reads the
journal SQLite file via a SQLite URI `mode=ro` handle, and
renders the same data the CLI and MCP surface — without
mutating any state.

What it does **not** do:

- Does **not** execute trades, route orders, or sign anything.
- Does **not** call broker APIs.
- Does **not** fetch market data.
- Does **not** make outbound network connections (the
  network-isolation guard in
  [`docs/architecture/console.md`](./architecture/console.md)
  §read-only-threat-model pins this).
- Does **not** alter the journal DB.

## Install

```bash
pip install 'trade-trace[console]'
```

The base wheel ships without FastAPI / Uvicorn / Jinja2; the
extra adds them. If you skip the extra and run
`tt console serve` anyway, the CLI prints:

```
Console requires the [console] extra:
    pip install 'trade-trace[console]'
```

## Launch

```bash
tt console serve
```

The default flags:

| Flag | Default | What it does |
|------|---------|---------------|
| `--host` | `127.0.0.1` | TCP bind host. Non-loopback values require `--allow-non-loopback`. |
| `--port` | `8765` | TCP bind port. Use `0` to let the OS pick a free port. |
| `--no-browser` | (off) | Skip the auto-open on startup. |
| `--allow-non-loopback` | (off) | Explicit acknowledgement that `--host` exposes the dashboard beyond localhost. |

The CLI prints a banner on startup naming the URL, the DB path,
the read-only mode, and the no-trade notice. It then opens your
default browser (unless `--no-browser`).

If the port is occupied, the CLI exits with code **73** and a
helpful message naming the port and suggesting `--port=<n+1>`
or `--port=0`. There is no traceback; operators can script
around the documented exit code.

`Ctrl+C` triggers a graceful shutdown without traceback.

## Pages

Every page shows the read-only badge and a staleness indicator
("Data as of HH:MM:SS UTC"). A manual refresh button is in the
filter bar; a "Refresh on R" keyboard shortcut works on every
page. Optional `Off / 10s / 30s / 60s` polling persists in
`localStorage`. The UTC↔Local time-zone toggle also persists
client-side; the server always returns UTC ISO 8601.

| Page | What it shows |
|------|---------------|
| Overview (`/`) | DB path, schema version, last-event timestamp, projection row counts, and the lazy-write deny set. Empty home → concrete CLI-hint affordances (`tt journal init`, `tt journal fixture-seed`). |
| Journal (`/journal`) | Paginated event stream with event-type / actor / subject-kind filters and per-row Raw JSON drilldown. |
| Decisions (`/decisions`) | Paginated decisions table with detail page (`/decisions/<id>`) showing decision row plus related events. |
| Reports (`/reports`) | The list of read-only `report.*` tools the Console exposes. Side-effect-risky handlers (`signal.scan`, `report.coach`) are **not** invocable from this page. |
| Calibration (`/calibration`) | Forecast totals and scored counts. Run `tt report calibration` for the full reliability diagram. |
| Strategies (`/strategies`) | Paginated strategies table. |
| Playbooks (`/playbooks`) | Paginated playbooks table. |
| Evidence & Integrity (`/integrity`) | Source totals, decision-source attachment counts, event-log totals, outbox-pending count. |
| Logs (`/logs`) | Last N lines of `<home>/logs/trade-trace.log` (configurable via `TRADE_TRACE_LOG_DIR`). Optional level filter, malformed-line tolerance, and the same secret redaction the logging module applies on write. |
| Raw JSON (`/raw`) | Index of latest events plus per-event payload viewer (`/raw?event_id=<n>`). |

The operational logging contract lives in
[`docs/architecture/logging.md`](./architecture/logging.md)
(trade-trace-3zvl); the Logs page consumes those JSONL files.

## Troubleshooting

| Symptom | Resolution |
|---------|------------|
| `Console requires the [console] extra` | `pip install 'trade-trace[console]'` |
| `port <n> on 127.0.0.1 is already in use` | Re-run with `--port <n+1>` or `--port=0`. The CLI exits with code 73 — operators can script around it. |
| Status page reports `reason: 'missing'` | The DB path does not exist. Run `tt journal init` first or pass `--home` to the right path. |
| Status page reports `reason: 'unsupported_schema'` | The file at the DB path is not a Trade Trace journal (missing M0 tables). The Console will not auto-migrate. Check `$TRADE_TRACE_HOME`. |
| Browser fails to render anything | The vendored htmx / CSS / JS path may not have shipped. Verify the `[console]` extra is installed and the wheel contains `src/trade_trace/console/static/`. |
| Non-loopback bind warning | Pass `--allow-non-loopback` only if you intentionally want LAN-reachable Console. The default 127.0.0.1 bind is correct for almost every use. |

## Read-only contract

The Console enforces read-only at four layers:

1. **OS file descriptor** — every SQLite handle opens with the
   URI `mode=ro` flag, so the kernel refuses writes.
2. **SQLite layer** — `PRAGMA query_only = 1` re-asserts the
   intent. Any `INSERT/UPDATE/DELETE/DDL` raises
   `sqlite3.OperationalError("attempt to write a readonly
   database")`.
3. **Tool dispatch** — the Console code path never calls a
   write tool. The lazy-write deny set
   (`signal.scan`, `report.coach`) is enforced by an AST test
   that pins endpoints/pages source.
4. **Security headers** — every HTTP response carries CSP
   (no `unsafe-inline`, no `unsafe-eval`, `'self'` only),
   `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
   `Referrer-Policy: no-referrer`, a locked-down
   `Permissions-Policy`, and `Cache-Control: no-store`.

See [`docs/architecture/console.md`](./architecture/console.md)
for the complete contract and threat model.
