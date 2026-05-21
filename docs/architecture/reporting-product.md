# Reporting product architecture

> Status: **partial — obsolete Console UI architecture; current reporting surfaces are CLI, MCP, and library read models**

This document used to lock architecture for a human-facing Console reporting
product. That Console UI has been hard-removed: there is no supported
`tt console serve` command, `trade_trace.console.*` Python package,
`frontend/console` application, packaged React/Vite assets, FastAPI/Uvicorn
Console server, browser/Playwright gate, or `[console]` / `[console-test]`
install extra.

The current product surface for reporting is:

- MCP tools and the equivalent `tt` CLI commands.
- Python/library report implementations under `src/trade_trace/reports/` and
  related contracts under `src/trade_trace/contracts/`.
- Architecture contracts in [`reports.md`](./reports.md),
  [`current-exposure-agent-contract.md`](./current-exposure-agent-contract.md),
  [`risk-units.md`](./risk-units.md), and
  [`opportunity-analysis.md`](./opportunity-analysis.md).

Keep this file only as an explicit tombstone so stale references do not look
like active product promises. Do not add new Console UI work here. Future
reporting documentation should describe agent-readable report envelopes,
filters, drill-down IDs, export packets, and library/MCP/CLI contracts rather
than a frontend dashboard.

## Current reporting boundary

The current reporting stack remains local-first and read-only with respect to
analytics reads:

1. **Local data only.** Reports read the local journal database and derived
   projections. They do not query external venues, price feeds, news sources,
   brokers, telemetry services, or remote assets.
2. **No broker or execution path.** Trade Trace never sends orders, webhooks,
   broker API requests, or outbound credentialed requests.
3. **No trade advice.** Reports may summarize recorded facts and deterministic
   diagnostics, but must not recommend trades, rank what the agent should do
   next, or imply financial advice.
4. **Backend/library math is canonical.** Aggregate metrics belong in
   `trade_trace.reports` and documented contracts, not in a removed frontend.
5. **Evidence remains agent-readable.** `ReportResult` envelopes carry filters,
   drill-down IDs, examples, caveats, and export/review-bundle material for
   MCP/CLI/library consumers.

## Historical Console material

The removed Console docs and plans were intentionally deleted rather than kept
as active architecture:

- `docs/CONSOLE.md`
- `docs/architecture/console.md`
- `docs/architecture/console-release-gate.md`
- `docs/architecture/console-visual-review.md`
- `docs/architecture/console-review.md`
- `docs/architecture/console-ia-support-contract.md`
- `docs/architecture/console-final-product-qa.md`
- `docs/plans/2026-05-21-trades-page-overhaul.md`

If historical proof is needed, use git history or bead records; do not recreate
public docs that instruct users or agents to install, run, test, build, or
maintain the removed UI.
