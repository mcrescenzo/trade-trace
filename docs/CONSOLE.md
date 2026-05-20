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

## Pages

The SPA owns these routes:

| Route | Purpose |
|---|---|
| `/` | Overview rollup for journal counts, P&L, and risk. |
| `/trades` | Trade-typed decisions with caveats. |
| `/reports` | Safe report catalog. |
| `/reports/pnl` | P&L analytics. |
| `/reports/risk` | Risk analytics. |
| `/reports/performance` | Decision velocity and performance timeline. |
| `/reports/strategy` | Strategy performance. |
| `/reports/decisions` | Watchlist and decision intelligence. |
| `/reports/compare` | Comparison report surface. |
| `/calibration` | Calibration metrics and integrity. |
| `/evidence` | Source quality and provenance analytics. |
| `/strategies`, `/playbooks` | Strategy and playbook tables. |
| `/journal`, `/decisions`, `/logs`, `/raw` | Developer/audit inspection surfaces. |

## Read-Only API

The frontend calls these local JSON endpoints:

- `GET /api/console/status`
- `GET /api/console/catalog`
- `GET /api/console/events`
- `GET /api/console/decisions`
- `GET /api/console/trades`
- `GET /api/console/positions/{id}`
- `GET /api/console/logs`
- `GET /api/console/raw/{event_id}`
- `POST /api/console/reports/{report_name}/run`
- `GET /api/console/reports/{report_name}/export`

All financial and calibration aggregates come from backend report tools.
The frontend renders server-provided metrics and never computes P&L,
R-multiples, win rate, ECE, scoring, or other report math in JavaScript.

## Maintainer Build

```bash
npm --prefix frontend/console ci
npm --prefix frontend/console run test
npm --prefix frontend/console run build
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

Agentic visual QA is tracked in
`docs/architecture/console-visual-review.md`. A release review should
capture screenshots of the rich fixture at desktop, tablet, and mobile
widths, then inspect hierarchy, density, overlap, table ergonomics,
chart readability, loading/error/empty states, and route consistency.

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
