# Console Architecture

> Status: **shipped** — clean-break implementation contract for the
> package-shipped React Console.

## Decisions

1. **Launch command stays `tt console serve`.** The existing CLI grammar,
   default host/port, browser-open default, non-loopback opt-in, and port
   conflict behavior remain stable.
2. **Backend stays FastAPI + Uvicorn.** FastAPI serves the JSON API,
   static app assets, security headers, and SPA fallback. The Python
   dependency extra is only `fastapi` and `uvicorn[standard]`.
3. **Frontend is React + TypeScript + Vite.** Source lives in
   `frontend/console/`; release builds emit package data under
   `src/trade_trace/console/static/app/`.
4. **Users never need Node.js.** Node is development/release-time only.
   Wheels ship the prebuilt app.
5. **The Console remains read-only.** It reads the local journal only,
   never mutates the DB, never executes trades, never calls broker APIs,
   never fetches market data, and never opens outbound network paths.
6. **No frontend report math.** JavaScript renders backend-provided
   metrics. P&L, risk, calibration, score, and report aggregates stay in
   Python report tools.
7. **No remote assets.** CSP is `'self'` only for scripts, styles,
   images, fonts, and connects. The app uses package-shipped assets and
   local API calls only.

## Runtime Shape

`trade_trace.console.serve._build_app(home)` creates a FastAPI app with:

- middleware applying the stable security header set;
- `/assets/*` mounted to the Vite build output;
- `/static/*` mounted for package static files such as the favicon;
- `/api/console/*` read-only JSON endpoints;
- an SPA fallback that returns `static/app/index.html` for non-API routes.

The app opens a read-only SQLite handle per request using the same
storage helper pinned by the read-only database tests. Missing or
unsupported journals return typed JSON details from API routes.

## API Surface

The Console API is intentionally local and narrow:

- status/catalog: `/api/console/status`, `/api/console/catalog`
- paginated tables: events, decisions, trades, strategies, playbooks,
  memory nodes, instruments, forecasts, outcomes
- detail views: raw event and position detail
- reports: `POST /api/console/reports/{tool}/run`
- export packets: `GET /api/console/reports/{tool}/export`

The report adapter is the only dispatch path for report tools. It keeps
the closed safe-report allowlist and blocks lazy-write handlers.

## Product Boundaries

The Console is not a trading terminal, broker connector, live-market
dashboard, SaaS collaboration product, or financial-advice surface. It
does not support broker/exchange sync, execution/order management,
credential entry, live quotes/news, cloud sharing, social/mentor review
threads, telemetry, server-side comments/annotations/preferences, or
saved filters. Competitor-inspired features that depend on fills,
commissions, slippage, tax lots, intraday execution streams, account
sync, or remote collaboration require explicit future local backend data
contracts before any UI can claim them.

Current React navigation intentionally excludes Logs and Raw JSON as
primary pages. Auditability is still available through Journal event
detail, related-record drilldowns, raw payload rendering, and the local
JSON endpoints (`/api/console/logs`, `/api/console/raw/{event_id}`).
Richer process analytics and period-review packets are deferred to their
backend-contract beads (`trade-trace-4exy`, `trade-trace-2vq5`); until
then sparse data is rendered as caveats/empty states.

## Frontend Stack

The SPA uses:

- TanStack Router for route definitions and route state;
- TanStack Query for server-state cache, refresh, loading, and error
  states;
- TanStack Table and Virtual for dense tables;
- ECharts for interactive charts;
- Radix primitives, Tailwind, source-owned shadcn-style components, and
  Lucide icons for the UI system.

## Packaging

`pyproject.toml` package data includes `trade_trace.console = ["static/**/*"]`.
The release build command is:

```bash
npm --prefix frontend/console ci
npm --prefix frontend/console run test
npm --prefix frontend/console run build
python -m build
```

The Vite output path is fixed to
`src/trade_trace/console/static/app/`.

## Testing Contract

Required gates:

- Python contracts for CLI registration, app serving, API route shape,
  static asset serving, malformed cursor/filter errors, and report export.
- Security tests for CSP, no external app resources, no outbound network
  posture, and read-only DB behavior.
- Frontend Vitest tests and TypeScript build.
- Playwright browser smoke tests against `tt console serve`.
- Agentic visual review using the rubric in
  `docs/architecture/console-visual-review.md`.
