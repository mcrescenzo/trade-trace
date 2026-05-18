# Trade Trace

**A local, open-source, AI-only journal, memory, and calibration substrate for LLM trading agents.**

Trade Trace records trading decisions an LLM agent makes and helps the agent improve through a closed learning loop: journal a decision, resolve the outcome, score calibration, review deterministic reports, write reflections, update a versioned playbook, and recall that learning next time. It runs locally, exposes both an MCP server and a CLI with JSON-first contracts, and never executes trades.

## What this is

- A **decision journal** with instruments, snapshots, theses, forecasts, outcomes, and process tags.
- A **trading-native memory layer** modeled on Retain / Recall / Reflect, with outcome-linked and calibration-aware recall.
- A **binary MVP calibration grader** that scores supported binary forecasts with Brier score when outcomes resolve.
- A **playbook loop** that versions rules, records manual/advisory overrides, and keeps provenance from reflections.
- **Strategies** that group decisions, theses, and reviews under a named edge thesis (e.g., `earnings-momentum`) so reports, recall, and reflection can be scoped to one logical grain without depending on free-form tags.
- An **MCP server** and **CLI** whose schemas and semantics are equivalent after transport normalization.

## What this is not

- Not a trade executor. No order signing, wallet handling, broker credentials, seed phrases, or trade routing.
- Not a human dashboard. There is no product web UI; P2 may add optional static/read-only inspection exports.
- Not a generic agent memory framework. The schema is trading-shaped.
- Not a backtesting engine, tax accountant, social platform, or source of financial advice.

For the full vision, see [`VISION.md`](./VISION.md). For the working PRD, see [`PRD.md`](./PRD.md).

## Status

Pre-implementation. The current artifacts are design docs:

- [`VISION.md`](./VISION.md) — north star
- [`PRD.md`](./PRD.md) — working PRD and MVP scope
- [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md) — memory layer spec (node taxonomy, retrieval, bi-temporal validity, embeddings posture)
- [`docs/architecture/scoring.md`](./docs/architecture/scoring.md) — forecast scoring (Brier, log score, ECE, sharpness, reliability bins, lifecycle)
- [`docs/architecture/persistence.md`](./docs/architecture/persistence.md) — events, outbox, idempotency
- [`docs/architecture/contracts.md`](./docs/architecture/contracts.md) — CLI/MCP envelope and error codes
- [`docs/architecture/operability.md`](./docs/architecture/operability.md) — timezone, multi-process, migrations, logging, blob caps, JSONL on-disk format
- [`docs/architecture/reports.md`](./docs/architecture/reports.md) — `ReportFilter` / `ReportResult` / drill-down / `review.bundle`
- [`docs/architecture/imports.md`](./docs/architecture/imports.md) — JSONL/CSV local-import contract
- [`docs/architecture/risk-units.md`](./docs/architecture/risk-units.md) — P1 risk-unit / R-multiple analytics design
- [`docs/architecture/opportunity-analysis.md`](./docs/architecture/opportunity-analysis.md) — P1 path-dependent process diagnostics

## Install (planned)

```bash
pip install trade-trace
```

Planned requirements: Python 3.11+, SQLite with FTS5. The base wheel ships `sqlite-vec` and `sentence-transformers` as runtime dependencies. **Vectors are off by default in MVP**: a fresh `journal.init` makes zero outbound network calls. MVP recall runs with FTS5 + graph + temporal retrieval. Opt in to semantic recall via `tt config set embeddings.provider local` (one-time model-weight download, ~130 MB) or `tt model import <path>` for air-gapped installs. See [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md) §8.

Trade Trace never fetches trading data, broker data, market prices, order books, or outcomes. The agent calling it supplies all market data through the structured ingestion APIs. The single opt-in outbound path (embedding model download) carries no trading data; the optional API-embeddings path is separately opt-in and warned about at configure time. See [`PRD.md`](./PRD.md) §2.4.1.

## MVP vertical slice

The MVP proves a complete learning-loop slice with narrow breadth:

1. `journal.init`
2. manual `instrument.add` / `snapshot.add` / `thesis.add` / binary `forecast.add` / `decision.add` — with optional `strategy_id` linkage to a named strategy
3. optional `strategy.create` to group decisions/theses/reviews under a named edge thesis (M3; nullable FK column is reserved in M1)
4. `outcome.add`
5. binary Brier scoring
6. deterministic reports and `report.coach` — all accept an optional `strategy_id` filter
7. agent-written `memory.reflect`, including reflections targeted at a strategy
8. `playbook.propose_version` with advisory/manual override tracking
9. `memory.recall` during the next thesis, optionally scoped to a strategy

Deferred or optional after the manual loop: JSONL/CSV import implementations (the write schemas are import-ready in MVP), `sqlite-vec` semantic recall, multi-class/scalar scoring, trading-native edge/market reports (forecast-vs-market, calibration-by-liquidity-bucket), `report.compare`, `report.strategy_performance`, `report.risk` (see [`docs/architecture/risk-units.md`](./docs/architecture/risk-units.md)), `report.opportunity` (see [`docs/architecture/opportunity-analysis.md`](./docs/architecture/opportunity-analysis.md)), `review.bundle` implementation, exact ForecastBench compatibility, sync, HTTP/SSE, websockets, and a web viewer.

## Quickstart for an agent (MCP, planned)

```jsonc
{"tool": "journal.init"}

{"tool": "instrument.add", "args": {
  "venue": "manual",
  "asset_class": "prediction_market",
  "title": "Will X happen by 2026-06-30?",
  "currency_or_collateral": "USDC",
  "actor_id": "agent:default"
}}

{"tool": "strategy.create", "args": {"name": "Thin-liquidity prediction markets", "slug": "thin-liquidity-prediction-markets", "hypothesis": "Markets with < $5K ADV near resolution are systematically mispriced; favor skips when spread > expected edge.", "actor_id": "agent:default"}}

{"tool": "snapshot.add", "args": {"instrument_id": "...", "price": 0.37, "bid": 0.36, "ask": 0.39, "actor_id": "agent:default"}}
{"tool": "thesis.add", "args": {"instrument_id": "...", "side": "yes", "body": "...", "falsification_criteria": "...", "strategy_id": "...", "actor_id": "agent:default"}}
{"tool": "forecast.add", "args": {"thesis_id": "...", "kind": "binary", "outcomes": [{"label": "YES", "probability": 0.48}, {"label": "NO", "probability": 0.52}], "actor_id": "agent:default"}}
{"tool": "decision.add", "args": {"instrument_id": "...", "thesis_id": "...", "type": "skip", "reason": "Estimated edge < spread + resolution risk", "strategy_id": "...", "tags": ["liquidity-ignored", "good-skip"], "actor_id": "agent:default"}}

{"tool": "outcome.add", "args": {"instrument_id": "...", "outcome_label": "NO", "outcome_value": 0.0, "status": "resolved_final", "resolved_at": "2026-06-30T00:00:00Z", "actor_id": "agent:default"}}

{"tool": "report.coach", "args": {"horizon_days": 30, "strategy_id": "..."}}

{"tool": "memory.reflect", "args": {
  "target": {"kind": "decision", "id": "..."},
  "insight": "Skip was correct here; spread compression never materialized.",
  "strength_tags": ["good-skip", "good-liquidity-discipline"],
  "actor_id": "agent:default"
}}

{"tool": "memory.recall", "args": {"context": {"kind": "strategy", "id": "..."}, "node_types": ["observation", "reflection", "playbook_rule"], "k": 10}}
```

## CLI dogfood surface (planned)

The CLI mirrors the MCP tool catalog. Stdout is JSON only by default; `--human` may add prose to stderr without changing stdout semantics.

```bash
trade-trace journal init --human
trade-trace instrument add --venue manual --asset-class prediction_market --title "Will X happen by 2026-06-30?" --currency USDC --actor-id agent:default --human
trade-trace report coach --horizon-days 30 --human
trade-trace journal schema --tool decision.add
```

## License

MIT. See `LICENSE` once implementation begins.
