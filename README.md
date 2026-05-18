# Trade Trace

**A local, open-source, AI-only journal, memory, and calibration substrate for LLM trading agents.**

Trade Trace records every trading decision an LLM agent makes — across prediction markets, equities, options, crypto, and event markets — and helps the agent identify and refine its own process over time through a closed self-improvement loop. It runs locally, exposes both an MCP server and a CLI with a JSON-only output contract, and never executes trades or handles credentials.

## What this is

- A **decision journal** with forecasts, theses, evidence, and process tags.
- A **memory layer** modeled on Hindsight's Retain / Recall / Reflect surface but trading-specific (outcome-linked, calibration-aware, position-provenanced).
- A **calibration grader** that auto-scores forecasts when outcomes resolve and surfaces drift.
- A **playbook engine** that versions trading rules, tracks adherence and override outcomes, and evolves with reflection-derived provenance.
- An **MCP server** and an **equivalent CLI** with identical JSON contracts.

## What this is not

- Not a trade executor. No order signing, no wallet handling, no credentials.
- Not a human dashboard. There is no web UI. Outputs are JSON-only.
- Not a generic agent memory framework. The schema is trading-shaped.
- Not a backtesting engine, tax accountant, or social platform.

For the full vision, see [`VISION.md`](./VISION.md). For the working PRD, see [`PRD.md`](./PRD.md).

## Status

Pre-implementation. The current artifacts are design docs:

- [`VISION.md`](./VISION.md) — north star
- [`PRD.md`](./PRD.md) — working PRD
- [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md) — memory layer spec
- [`docs/architecture/connector-interface.md`](./docs/architecture/connector-interface.md) — connector plugin spec

Implementation begins after these are reviewed and an implementation plan is written.

## Install (planned)

```bash
pip install trade-trace                                    # core
pip install "trade-trace[polymarket,manifold,yfinance]"    # with marquee venue connectors
```

Requirements (planned): Python 3.11+, SQLite with the `sqlite-vec` extension (auto-installed), ~150MB for the default local embedding model (`BAAI/bge-small-en-v1.5`).

## Quickstart for an agent (MCP)

Add to your MCP host config (e.g., Claude Code's `mcp.json`):

```json
{
  "mcpServers": {
    "trade-trace": {
      "command": "trade-trace",
      "args": ["mcp"]
    }
  }
}
```

Then from the agent:

```jsonc
// 1. Initialize the local journal
{"tool": "journal.init"}

// 2. Add an instrument
{"tool": "instrument.add", "args": {
  "venue": "polymarket",
  "asset_class": "prediction_market",
  "title": "Will X happen by 2026-06-30?",
  "currency_or_collateral": "USDC"
}}

// 3. Record a snapshot + thesis + forecast + decision
{"tool": "snapshot.add", "args": {"instrument_id": "...", "price": 0.37, "bid": 0.36, "ask": 0.39}}
{"tool": "thesis.add", "args": {"instrument_id": "...", "side": "yes", "body": "...", "falsification_criteria": "..."}}
{"tool": "forecast.add", "args": {"thesis_id": "...", "kind": "binary", "outcomes": [{"label": "YES", "probability": 0.48}, {"label": "NO", "probability": 0.52}]}}
{"tool": "decision.add", "args": {"instrument_id": "...", "thesis_id": "...", "type": "skip", "reason": "Estimated edge < spread + resolution risk", "tags": ["liquidity-ignored", "good-skip"]}}

// 4. When the market resolves, record the outcome and the system auto-scores
{"tool": "outcome.add", "args": {"instrument_id": "...", "outcome_label": "NO", "outcome_value": 0.0, "resolved_at": "2026-06-30T00:00:00Z"}}

// 5. Run the self-improvement loop
{"tool": "report.coach", "args": {"horizon_days": 30}}
// → structured JSON with calibration drift, top mistake tags, overdue reviews, ...

{"tool": "memory.reflect", "args": {
  "target": {"kind": "decision", "id": "..."},
  "insight": "Skip was correct here; spread compression never materialized. Pattern: thin-liquidity resolution-week markets.",
  "strength_tags": ["good-skip", "good-liquidity-discipline"]
}}

// 6. Recall relevant past memory when forming a new thesis on a similar market
{"tool": "memory.recall", "args": {
  "context": {"kind": "instrument", "id": "..."},
  "node_types": ["observation", "reflection", "playbook_rule"],
  "k": 10
}}
```

## Quickstart for a human dogfooder (CLI)

The CLI is a 1:1 mirror of the MCP tools, with a `--human` flag that adds prose to stderr for readability.

```bash
# Initialize
trade-trace journal init --human

# Add an instrument, snapshot, thesis, decision
trade-trace instrument add --venue polymarket --asset-class prediction_market --title "Will X happen by 2026-06-30?" --currency USDC --human

# Run a report
trade-trace report coach --horizon-days 30 --human

# See the full tool schema for any command
trade-trace journal schema --tool decision.add
```

All commands also accept the equivalent flags without `--human`; output is then JSON-only to stdout.

## License

MIT. See `LICENSE` (added at implementation start).

## Contributing

The project is pre-implementation. The most useful contributions right now are review of the design docs:

- Does the data model serve a real LLM trading workflow you've built or tried to build?
- Are the four layers of the self-improvement loop the right primitives?
- Are there venues / connectors that should be marquee priority that aren't listed?

Open an issue with feedback; implementation work will track a milestone-by-milestone plan once design is settled.
