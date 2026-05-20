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
| `--port` | `8765` | TCP bind port. Choose an explicit free port; `--port=0` is rejected because the Console must print and open the actual URL. |
| `--no-browser` | (off) | Skip the auto-open on startup. |
| `--allow-non-loopback` | (off) | Explicit acknowledgement that `--host` exposes the dashboard beyond localhost. |

The CLI prints a banner on startup naming the URL, the DB path,
the read-only mode, and the no-trade notice. It then opens your
default browser (unless `--no-browser`).

If the port is occupied, the CLI exits with code **73** and a
helpful message naming the port and suggesting `--port=<n+1>`
or another explicit free port. There is no traceback; operators
can script around the documented exit code.

`Ctrl+C` triggers a graceful shutdown without traceback.

## Pages

Every page shows the read-only badge and a staleness indicator
("Data as of HH:MM:SS UTC"). A manual refresh button is in the
filter bar; a "Refresh on R" keyboard shortcut works on every
page. Optional `Off / 10s / 30s / 60s` polling persists in
`localStorage`. The UTC↔Local time-zone toggle also persists
client-side; the server always returns UTC ISO 8601.

Per the reporting product overhaul ([trade-trace-3o4a]), the
navigation now splits three lanes (reporting / strategies+playbooks /
developer-audit). The reporting lane covers the Tradervue-like reading
experience; the developer-audit lane preserves the inspection surface.

### Reporting lane

| Page | What it shows |
|------|---------------|
| Overview (`/`) | P&L + risk + performance roll-up dashboard: realized/unrealized P&L tiles, open-position count, open-mark coverage, mean R, expectancy. Evidence affordance deep-links into `report.pnl` and `report.risk` record IDs. |
| Trades (`/trades`) | Every trade-typed decision (`actual_enter`, `actual_exit`, `paper_enter`, `paper_exit`, `add`, `reduce`) with side / qty / price / declared risk / strategy / per-row caveat chips. Filterable by strategy, instrument, decision type; cursor pagination. |
| Reports (`/reports`) | Index of read-only `report.*` tools the Console exposes. Side-effect-risky handlers (`signal.scan`, `report.coach`) are not invocable. |
| P&L (`/reports/pnl`) | `report.pnl` dashboard with realized / unrealized / MTM tiles, open-mark coverage caveat, per-instrument bar chart. |
| Risk (`/reports/risk`) | `report.risk` R-multiple panel: mean / median R, expectancy, win rate, payoff ratio, pending-with-risk caveat. |
| Performance (`/reports/performance`) | Decision velocity bucketed by day; placeholder for the dedicated equity-curve / drawdown view. |
| Strategy (`/reports/strategy`) | `report.strategy_performance` — wraps `report.compare(base_report='pnl', group_by='strategy_id')`. |
| Decision intelligence (`/reports/decisions`) | Watch + overdue watch + stale watch surface from `report.watchlist`. |
| Compare (`/reports/compare`) | Comparison builder. `base_report` × `group_by` form bound to the closed enums (calibration/pnl × strategy_id/agent_id/model_id/playbook_version_id/decision_type). |
| Calibration (`/calibration`) | Brier / log score / ECE / sharpness / baseline panel + reliability bins from `report.calibration`. Integrity diagnostics embedded. |
| Evidence (`/evidence`) | Provenance hygiene from `report.source_quality`: missing / stale / contradictory / duplicated / sensitive sources. |
| Audit · Integrity (`/integrity`) | Legacy developer-lane integrity snapshot (source totals, attachment counts, outbox pending). Kept alongside the new Evidence dashboard. |

### Strategies / Playbooks

| Page | What it shows |
|------|---------------|
| Strategies (`/strategies`) | Paginated strategies table. |
| Playbooks (`/playbooks`) | Paginated playbooks table. |

### Developer / Audit lane

| Page | What it shows |
|------|---------------|
| Journal (`/journal`) | Paginated event stream with event-type / actor / subject-kind filters and per-row Raw JSON drilldown. |
| Decisions (`/decisions`) | Paginated decisions table with detail page (`/decisions/<id>`) showing decision row plus related events. |
| Position detail (`/positions/<id>`) | Per-position lifecycle audit: realized/unrealized P&L tiles, full `position_events` lineage chronologically, opening decision strategy/playbook, missing-mark / no-strategy caveats. |
| Logs (`/logs`) | Last N lines of `<home>/logs/trade-trace.log` (configurable via `TRADE_TRACE_LOG_DIR`). Optional level filter, malformed-line tolerance, and the same secret redaction the logging module applies on write. |
| Raw JSON (`/raw`) | Index of latest events plus per-event payload viewer (`/raw?event_id=<n>`). |
| Legacy Overview (`/overview-legacy`) | DB-meta snapshot kept for operators auditing schema_version / row counts; the reporting-lane Overview at `/` is the canonical reader view. |

### Read-only data flow

Every dashboard renders server-computed metrics — there is no
frontend financial math. The `report.*` tools produce a
`ReportResult` envelope; the
`trade_trace.console.reporting.adapter.run_report` helper enforces
the closed safe-report allowlist (`SAFE_REPORT_TOOLS`) and projects
the envelope into a typed `DashboardContext` Jinja consumes. Every
aggregate metric exposes an Evidence affordance with the originating
tool name, CLI invocation, request_id, and per-record drilldown IDs
(per the §6 evidence contract in
[`architecture/reporting-product.md`](./architecture/reporting-product.md)).

### Filter URL state

The reporting dashboards share a single `f=<base64url-json>` URL
parameter carrying the canonical `ReportFilter`. Bookmarking or
sharing a dashboard URL preserves the filter; the encoder /
decoder lives at
`trade_trace.console.reporting.filter_state` (trade-trace-hayy).
Empty filter encodes to `e30` (base64url of `{}`); unknown axes are
rejected via `ReportFilter.model_validate` (`extra="forbid"`) so a
crafted URL can never silently broaden the filter.

### Read-only export packets

Every reporting dashboard exposes `/reports/<tool>/export.json`
(e.g. `/reports/report.pnl/export.json`) which bundles the full
ReportResult envelope, originating filter, request_id, as_of, and
record_ids in one JSON packet for cross-tool audit. No credentials
are ever embedded; the packet is the same envelope the CLI / MCP
client would receive. Per-bead trade-trace-sqtq.

### Charting

Dashboards render charts via the vendored Chart.js asset under
`static/vendor/chartjs/`. The bootstrap script
(`static/js/chart-bootstrap.js`) reads `<script
type="application/json" data-chart="<canvas-id>">` blocks via
`JSON.parse` (no `eval`, no `new Function` — CSP-clean). The asset
is downloaded once via the curl in
`static/vendor/chartjs/README.md`; when the binary is missing every
chart canvas degrades to a visible "asset not loaded" caveat
(numeric evidence below is unaffected). See trade-trace-ycag for
the bootstrap and trade-trace-nfn4 for the binary install.

The operational logging contract lives in
[`docs/architecture/logging.md`](./architecture/logging.md)
(trade-trace-3zvl); the Logs page consumes those JSONL files.

## Troubleshooting

| Symptom | Resolution |
|---------|------------|
| `Console requires the [console] extra` | `pip install 'trade-trace[console]'` |
| `port <n> on 127.0.0.1 is already in use` | Re-run with `--port <n+1>` or another explicit free port. The CLI exits with code 73 — operators can script around it. |
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
