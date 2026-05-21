# Trade Trace Console - User Guide

> Status: clean-break React Console. The Console remains optional under
> `trade-trace[console]`, local-first, read-only, and package-shipped.

## What It Is

The Console is a local analytics dashboard for a Trade Trace journal.
It runs at `http://127.0.0.1:8765` by default, reads the journal SQLite
file through a read-only handle, serves a prebuilt React/Vite app, and
exposes read-only JSON APIs under `/api/console/*`.

It does not execute trades, call broker APIs, fetch market data, mutate
the journal DB, load CDN assets, send telemetry, or make outbound
network connections during normal Console use.

## Install And Launch

```bash
pip install 'trade-trace[console]'
tt console serve
```

The base wheel ships the compiled frontend assets. The `[console]`
extra adds the Python server runtime:

- `fastapi`
- `uvicorn[standard]`

Node.js is only needed by maintainers rebuilding the frontend.

Launch flags:

| Flag | Default | Meaning |
|---|---:|---|
| `--host` | `127.0.0.1` | TCP bind host. Non-loopback values require explicit opt-in. |
| `--port` | `8765` | TCP bind port. `--port=0` is rejected so the banner can name the URL. |
| `--home` | resolved Trade Trace home | Journal home to read. |
| `--no-browser` | off | Skip auto-opening the browser. |
| `--allow-non-loopback` | off | Acknowledge that the dashboard is reachable beyond localhost. |

## Frontend Stack

The shipped app is built from `frontend/console/`:

- React + TypeScript + Vite
- TanStack Router for SPA routes
- TanStack Query for server state and refresh
- TanStack Table / Virtual for dense tables
- Apache ECharts for charts
- Radix primitives, Tailwind, source-owned shadcn-style components
- Lucide React icons

Release builds emit `src/trade_trace/console/static/app/index.html`
and `src/trade_trace/console/static/app/assets/*`. FastAPI serves
`/assets/*` directly and returns the app shell for SPA routes.

## Pages And Navigation

The SPA route catalog is shared between the Python package and
`frontend/console/src/routeCatalog.json`. The primary navigation shows
top-level routes only; nested `/reports/*` pages are reached from the
Reports page or direct URLs. Logs and Raw JSON are intentionally not
primary-nav items. Raw auditability is still available through journal
event drilldowns, raw payload views, and the local JSON endpoints.

The shipped React Console owns these routes:

| Route | Purpose |
|---|---|
| `/` | Overview rollup for journal counts, P&L, and risk. |
| `/trades` | Position lifecycle rows by default, backed by `/api/console/positions`; `/trades?view=events` preserves the flat trade-decision event audit view backed by `/api/console/trades`. |
| `/reports` | Safe report catalog and links into report pages. |
| `/review` | Local period / edge review summary over existing aggregates. |
| `/reports/pnl` | P&L analytics. |
| `/reports/risk` | Risk analytics. |
| `/reports/performance` | Decision velocity and performance timeline. |
| `/reports/strategy` | Strategy performance. |
| `/reports/decisions` | Watchlist and decision intelligence. |
| `/process` | Process analytics where backend-local data exists. Sparse journals show caveats/empty states rather than invented metrics. |
| `/reports/compare` | Comparison report surface. |
| `/calibration` | Calibration metrics and integrity. |
| `/evidence` | Source quality and provenance analytics. |
| `/strategies`, `/playbooks` | Strategy and playbook tables. |
| `/journal` | Journal timeline, replay, event detail, related records, and raw payload access. |
| `/decisions` | Paginated decision inspection. |

## Filters, Drilldowns, And Caveats

The currently implemented global filter bar is URL-backed via
`f=<base64url-json>` and exposes only fields the Console can pass to
current backend contracts: decision type, exact instrument ID, strategy
ID, and `/trades` date/view controls where the page supports them. Empty
filters mean "all local rows". For table endpoints, repeated array
params are preserved instead of truncated (for example repeated
`decision_type` in event view and repeated `instrument_id` where
supported), and date ranges map to explicit `opened_from` / `opened_to`
query params. The frontend does not add hidden filter axes; broader
filter facets require backend `ReportFilter` contracts before they can be
truthfully exposed.

Report pages re-run backend `report.*` tools when filters change. The
frontend renders returned metrics, caveats, evidence, examples, and raw
envelopes; it does not recompute finance, calibration, or risk metrics
in JavaScript. Pages surface low sample size, missing marks, missing
risk, missing prices/quantities, unsupported scoring, sparse data, and
empty-state conditions as caveats instead of silently zero-filling.

Record drilldowns stay local and read-only: journal event detail,
related decisions/forecasts/outcomes/sources, raw event payloads,
trade decision-event rows, position lifecycle rows, and position detail
all render existing database contents.
`trade_trace.console.reporting.trade_detail(conn, decision_id)` is a
supported external Python read-model helper for single trade rows, but
the shipped Console intentionally does not expose a per-trade HTTP
endpoint or React route.
There is no server-side comment, annotation, preference, or saved-filter
write path in the Console.

## Read-Only API

The frontend calls these local JSON endpoints:

- `GET /api/console/status`
- `GET /api/console/catalog`
- `GET /api/console/events`
- `GET /api/console/events/{event_id}`
- `GET /api/console/events/{event_id}/related`
- `GET /api/console/record-events`
- `GET /api/console/decisions`
- `GET /api/console/trades`
- `GET /api/console/positions`
- `GET /api/console/positions/{id}`
- `GET /api/console/strategies`
- `GET /api/console/playbooks`
- `GET /api/console/memory-nodes`
- `GET /api/console/instruments`
- `GET /api/console/forecasts`
- `GET /api/console/outcomes`
- `GET /api/console/logs`
- `GET /api/console/raw/{event_id}`
- `POST /api/console/reports/{report_name}/run`
- `GET /api/console/reports/{report_name}/export`

All financial and calibration aggregates come from backend report tools.
The frontend renders server-provided metrics and never computes P&L,
R-multiples, win rate, ECE, scoring, or other report math in JavaScript.

## Product Boundaries And Unsupported Features

The Console is a local reader for one Trade Trace journal. These features
are unsupported by design in the shipped React Console:

- broker/exchange/wallet sync, order entry, order management, execution,
  signing, cancellations, and credential storage;
- live market data, news feeds, quote refresh, alerts, or external price
  backfill;
- cloud hosting, multi-user sharing, social/mentor SaaS workflows, remote
  dashboards, or cross-device sync;
- telemetry, analytics beacons, CDN bundles, Google Fonts, webhooks, or
  any normal-use outbound network path from the Console;
- financial advice or generated recommendations to enter/exit/size a
  trade;
- server-side comments, annotations, saved preferences, saved filters, or
  journal edits from dashboard interactions;
- competitor-inspired advanced analytics that require absent backend data
  contracts, such as broker-grade fills/commissions/slippage, tax lots,
  tick/intraday execution replay, account-level sync, mentor review
  threads, social sharing, or authoritative import adapters.

Future work may add report pages only after the local database schema,
ingestion tools, read models, and `report.*` contracts exist. Until then,
the Console must show sparse/unsupported caveats rather than imply data it
does not have. Known deferred backend-contract areas include richer
process analytics (`trade-trace-4exy`) and period review packets
(`trade-trace-2vq5`).

## Glossary

- **Decision**: any recorded agent action (`watch`, `skip`, entries,
  exits, thesis updates, reviews, etc.). Decisions are not necessarily
  trades.
- **Trade**: a decision type that changes exposure (`actual_enter`,
  `paper_enter`, `add`, `reduce`, `actual_exit`, `paper_exit`) and has
  quantity/price data when available.
- **Position**: rebuildable local exposure projection from trade events;
  open positions may lack current marks.
- **Forecast / Outcome / Calibration**: forecast probabilities, realized
  outcomes, and backend scoring/integrity diagnostics for supported
  forecast shapes. Unsupported or unresolved forecasts remain visible but
  are caveated.
- **Evidence**: source/provenance records and report examples/record IDs
  already stored in the journal.
- **Process analytics**: local process signals such as adherence,
  mistakes/strengths/watchlists, and opportunity/review aggregates when
  the corresponding backend data exists; not a behavioral surveillance or
  mentor SaaS feature.

## Maintainer Build

```bash
npm --prefix frontend/console ci
npm --prefix frontend/console run test
npm --prefix frontend/console run build
./.venv/bin/python -m pytest tests/contracts/test_console_shell.py
python -m build
```

The built app is intentionally committed into package data so users do
not need Node.js to run the Console from a wheel or source checkout.

## Quality Gates

Before release, run:

```bash
npm --prefix frontend/console run test
npm --prefix frontend/console run build
pytest tests/contracts/test_console_serve.py tests/contracts/test_console_http_routes.py
pytest tests/contracts/test_console_shell.py tests/contracts/test_console_dashboard_a11y.py
pytest tests/contracts/test_console_charting.py
pytest tests/security/test_console_security_headers.py
pytest tests/console_browser/
```

`npm --prefix frontend/console run build` writes
`src/trade_trace/console/static/app/provenance.json` with SHA-256 hashes
for the route catalog/source inputs and emitted static assets. The shell
contract test recomputes those hashes so a release gate fails when source
changes are not rebuilt into packaged assets, or when packaged assets are
edited without regenerating provenance. The Python and frontend route
catalog JSON files are also compared byte-for-byte as data so the backend
catalog endpoint and visible SPA routes stay aligned.

Agentic visual QA is tracked in
`docs/architecture/console-visual-review.md`. A release review should
exercise both rich and sparse local journals:

```bash
TRADE_TRACE_HOME=/tmp/tt-console-rich tt journal init
TRADE_TRACE_HOME=/tmp/tt-console-rich tt journal fixture_seed \
  --target mvp-eval-rich \
  --idempotency-key console-rich-fixture
tt console serve --home /tmp/tt-console-rich --no-browser

TRADE_TRACE_HOME=/tmp/tt-console-sparse tt journal init
TRADE_TRACE_HOME=/tmp/tt-console-sparse tt journal fixture_seed \
  --target mvp-eval \
  --idempotency-key console-sparse-fixture
tt console serve --home /tmp/tt-console-sparse --no-browser
```

For the rich fixture, capture desktop/tablet/mobile screenshots and
inspect hierarchy, density, overlap, table ergonomics, chart readability,
drilldowns, caveat chips, and route consistency. For the sparse fixture,
verify empty and low-coverage states: missing marks/risk data should be
explicit, pages should not invent P&L/risk/process metrics, and report
errors should remain typed and local.

## Troubleshooting

| Symptom | Resolution |
|---|---|
| `Console requires the [console] extra` | Install with `pip install 'trade-trace[console]'`. |
| Browser shows only an asset-missing error | Rebuild with `npm --prefix frontend/console run build`. |
| `/api/console/status` says `missing` | Run `tt journal init` or pass the correct `--home`. |
| Port conflict exits with code 73 | Re-run with another explicit `--port`. |
| Non-loopback bind refused | Add `--allow-non-loopback` only if LAN exposure is intentional. |

## Read-Only Contract

The Console enforces read-only behavior at the SQLite handle, endpoint,
tool-dispatch, and browser layers:

1. SQLite opens with URI read-only mode and `PRAGMA query_only`.
2. Console API routes use `open_database_readonly()`.
3. The report adapter allows only `SAFE_REPORT_TOOLS` and blocks
   `signal.scan` and `report.coach`.
4. CSP allows only `'self'`, forbids inline script/style and eval, and
   no built app asset may reference a CDN or remote bundle.
