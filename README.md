# Trade Trace

**A local, open-source, AI-only journal, memory, and calibration substrate for LLM trading agents.**

Trade Trace records trading decisions an LLM agent makes and helps the agent improve through a closed learning loop: journal a decision, resolve the outcome, score calibration, review deterministic reports, write reflections, update a versioned playbook, and recall that learning next time. It runs locally, exposes both an MCP server and a CLI with JSON-first contracts, and never executes trades.

## What this is

- A **decision journal** with instruments, snapshots, theses, forecasts, outcomes, and process tags.
- A **trading-native memory layer** modeled on Retain / Recall / Reflect, with outcome-linked and calibration-aware recall.
- A **binary MVP calibration grader** that scores supported binary forecasts with Brier score when outcomes resolve.
- A **playbook loop** that versions rules, records manual/advisory overrides, and keeps provenance from reflections.
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
- [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md) — memory layer spec
- [`docs/architecture/scoring.md`](./docs/architecture/scoring.md) — forecast scoring (Brier formula, resolution status, lifecycle)
- [`docs/architecture/persistence.md`](./docs/architecture/persistence.md) — events, outbox, idempotency
- [`docs/architecture/contracts.md`](./docs/architecture/contracts.md) — CLI/MCP envelope and error codes

## Install (planned)

```bash
pip install trade-trace
```

Planned requirements: Python 3.11+, SQLite with FTS5. `sqlite-vec` and a local embedding model can be enabled when available; MVP recall can run with FTS5 + graph + temporal retrieval. The default local embedding model is downloaded and cache-managed when enabled, not bundled into the wheel.

Trade Trace makes no outbound network calls and has no external data connectors. The agent calling it supplies all market data through the structured ingestion APIs.

## MVP vertical slice

The MVP proves a complete learning-loop slice with narrow breadth:

1. `journal.init`
2. manual `instrument.add` / `snapshot.add` / `thesis.add` / binary `forecast.add` / `decision.add`
3. `outcome.add`
4. binary Brier scoring
5. deterministic reports and `report.coach`
6. agent-written `memory.reflect`
7. `playbook.propose_version` with advisory/manual override tracking
8. `memory.recall` during the next thesis

Deferred or optional after the manual loop: CSV import, sqlite-vec embeddings, multi-class/scalar scoring, trading-native edge/market reports (forecast-vs-market, calibration-by-liquidity-bucket), exact ForecastBench compatibility, sync, HTTP/SSE, websockets, and a web viewer.

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

{"tool": "snapshot.add", "args": {"instrument_id": "...", "price": 0.37, "bid": 0.36, "ask": 0.39, "actor_id": "agent:default"}}
{"tool": "thesis.add", "args": {"instrument_id": "...", "side": "yes", "body": "...", "falsification_criteria": "...", "actor_id": "agent:default"}}
{"tool": "forecast.add", "args": {"thesis_id": "...", "kind": "binary", "outcomes": [{"label": "YES", "probability": 0.48}, {"label": "NO", "probability": 0.52}], "actor_id": "agent:default"}}
{"tool": "decision.add", "args": {"instrument_id": "...", "thesis_id": "...", "type": "skip", "reason": "Estimated edge < spread + resolution risk", "tags": ["liquidity-ignored", "good-skip"], "actor_id": "agent:default"}}

{"tool": "outcome.add", "args": {"instrument_id": "...", "outcome_label": "NO", "outcome_value": 0.0, "resolved_at": "2026-06-30T00:00:00Z", "actor_id": "agent:default"}}

{"tool": "report.coach", "args": {"horizon_days": 30}}

{"tool": "memory.reflect", "args": {
  "target": {"kind": "decision", "id": "..."},
  "insight": "Skip was correct here; spread compression never materialized.",
  "strength_tags": ["good-skip", "good-liquidity-discipline"],
  "actor_id": "agent:default"
}}

{"tool": "memory.recall", "args": {"context": {"kind": "instrument", "id": "..."}, "node_types": ["observation", "reflection", "playbook_rule"], "k": 10}}
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
