# Trade Trace — Vision

**Date:** 2026-05-18
**Status:** Refined draft
**Audience:** Project maintainers and contributors
**Companion doc:** [`PRD.md`](./PRD.md)

## What this is

Trade Trace is a **local, open-source, AI-only journal, memory, and calibration substrate for LLM trading agents.** It is a Python package distributed as both a Model Context Protocol (MCP) server and a CLI, with a JSON-only output contract. It records — and helps an LLM agent *reason about* — every decision the agent makes across markets, holds those decisions to their evidence, scores their forecasts when outcomes resolve, and surfaces structured signals the agent can use to identify and refine the shortcomings in its own trading process.

The wedge is the intersection of three gaps in the 2026 landscape:

1. **Human trading journals** (Tradervue, TradesViz, Edgewonk, TradeZella) are optimized for discretionary human traders and web UX. None are agent-native.
2. **LLM trading agents** (TradingAgents, Polymarket Agents, the various open-source bots) execute trades but do not journal them in a way that supports calibration over time or process review.
3. **AI agent memory systems** (Hindsight, Mem0, Letta, Zep) generalize over arbitrary domains and do not understand the trading-specific concepts of outcome resolution, forecast scoring, position provenance, or playbook adherence.

Trade Trace lives at that intersection. It is a *grader* and a *memory*, not a *trader*.

## What this is not

- **Not an executor.** Trade Trace never places, signs, cancels, or routes a trade. It never handles wallet keys, broker credentials, or seed phrases. Execution is a separate concern with separate safety design.
- **Not a data fetcher.** Trade Trace never queries external venues or market data APIs. The agent calling Trade Trace already has its own data connections — it is the one currently analyzing the market — and supplies all snapshots, outcomes, and metadata through the structured ingestion APIs.
- **Not a human dashboard.** There is no web UI. There is no chart-painting workflow. Outputs are JSON-by-default; a `--human` flag exists only as a courtesy for the project maintainer who is dogfooding the tool.
- **Not a generic agent memory framework.** Trade Trace's memory layer is trading-specific: nodes carry outcome links, calibration confidence, and position provenance. If you want a general memory store, use Mem0, Letta, or Hindsight directly.
- **Not a backtesting or simulation engine.** Trade Trace records and grades real and paper trades. It does not synthesize market data or replay historical fills.
- **Not a portfolio accounting system.** It computes P&L and basic exposure metrics, but it is not broker-grade and is not a tax tool.
- **Not a benchmark.** Trade Trace may export ForecastBench-inspired data once the external schema is verified, but it is the tooling, not a leaderboard.

## Why now

Three shifts make 2026 the right moment:

- **LLMs are becoming useful forecasting actors, but calibration remains fragile.** Recent forecasting work shows rapid improvement, while still leaving a gap to strong human forecasting and large variance across tasks. Trade Trace exists because agents need auditable calibration feedback, not because parity is guaranteed.
- **Agent memory is now a real engineering discipline.** Mem0, Hindsight, Letta, Zep, SYNAPSE, and others have converged on a recognizable shape: episodic + semantic + reflective memory with multi-strategy retrieval. The patterns are stable enough to specialize.
- **MCP has won as the agent-tool interface.** A journal exposed as an MCP server plugs into Claude Code, Cursor, and every other MCP-aware host without integration work. Combined with a token-efficient CLI for tight write loops, the surface is solved.

## Product principles

1. **Decision before outcome.** Capture reasoning, forecast, and evidence before the result is known. A thesis written after the fact is a rationalization, not a thesis.
2. **Every decision is reviewable.** Trades, skips, watches, paper trades, and thesis updates all create reviewable artifacts. A skipped trade is as important as an entered one.
3. **Separate process from P&L.** Good process can produce bad outcomes and vice versa. The system grades both axes independently.
4. **Market-agnostic core.** Prediction markets, equities, options, futures, crypto, and event markets share a generic decision/position/outcome spine. Venue-specific details live in `metadata_json`; there are no per-venue plugins or connectors to maintain.
5. **Local-first by default.** Storage is a single SQLite database. JSONL can be exported from committed DB events/outbox records for audit and portability; it is not a second source of truth. No remote services required. External sync is opt-in and explicit.
6. **MCP-first, CLI-equivalent, JSON-first contract.** Every operation is exposed as an MCP tool and as an equivalent CLI command. Schemas and semantics are equivalent after transport normalization. CLI output is JSON to stdout; prose is suppressed by default and only emitted to stderr when `--human` is requested. Errors carry stable codes.
7. **Structured input, graceful prose.** Prefer explicit fields with schema validation, but allow attached freeform notes for the LLM to reason about.
8. **Auditability over convenience.** Snapshots, theses, decisions, and memory nodes are append-only and versioned. Corrections create new events; nothing is silently overwritten.
9. **Memory and ledger are linked but distinct.** The trade ledger is strict, typed, and auditable — the agent's actions and what the market did. The memory layer is a flexible graph — the agent's beliefs, observations, and reflections. Both worlds cross-link through a single edges table. Beliefs are versioned and falsifiable; ledger facts are immutable.
10. **The agent is the one with judgment.** The system surfaces objective signals (calibration drift, mistake-tag frequency, advisory/manual playbook overrides, stale watches) but does not decide what counts as a mistake. The agent reflects; the system stores and links the reflection.

## Primary persona

**The LLM trading agent.** Trade Trace is built for an agent that:

- Forms theses with structured forecasts and evidence
- Records what was known at each decision point
- Decides whether to watch, skip, paper, enter, exit, hold, add, reduce, invalidate, or update
- Has its forecasts auto-graded when outcomes resolve
- Reads back its own past observations, reflections, and playbook rules when forming new theses
- Periodically reviews its own decisions and writes reflections that update its playbooks

Trade Trace is **not** built for a human discretionary trader. Humans are welcome as project maintainers, contributors, and dogfooders — but the product's surfaces are designed for token-efficient, schema-driven, machine-readable interaction.

## The four-layer self-improvement loop

Trade Trace's central feature is a closed loop that turns trading experience into refined process. The system supplies the primitives; the agent supplies the judgment.

```
                       ┌──────────────────────────────────────┐
                       │                                      │
                       ▼                                      │
              ┌─────────────────┐                             │
              │  1. Primitive   │  Calibration curves, tag    │
              │     reports     │  counts, override outcomes, │
              │   (objective)   │  stale watches, drift...    │
              └────────┬────────┘                             │
                       │                                      │
                       ▼                                      │
              ┌─────────────────┐                             │
              │   2. `coach`    │  Synthesized "things to     │
              │   command       │  think about" packet —      │
              │   (synthesis)   │  pure aggregation, no       │
              │                 │  opinions.                  │
              └────────┬────────┘                             │
                       │                                      │
                       ▼                                      │
              ┌─────────────────┐                             │
              │  3. Agent       │  Agent writes reflection    │
              │     reflection  │  nodes linked to ledger     │
              │   (subjective)  │  rows and memory nodes.     │
              └────────┬────────┘                             │
                       │                                      │
                       ▼                                      │
              ┌─────────────────┐                             │
              │  4. Playbook    │  Agent proposes versioned   │
              │   evolution     │  rule updates with          │
              │  (codification) │  provenance pointing back   │
              │                 │  to the reflection.         │
              └────────┬────────┘                             │
                       │                                      │
                       └──────────────────────────────────────┘
                              (next cycle, with new rules)
```

Layers 1 and 2 are deterministic and live in the system. Layers 3 and 4 are agent-driven and stored as graph memory. The loop closes because every new decision records the current playbook version, advisory/manual overrides are tracked, and override outcomes feed the next cycle's reports. Future machine-checkable rules may add automatic violation detection for explicitly modeled predicates.

This loop is the product. The MVP proves the complete loop with narrow breadth: structured manual ingestion, binary scoring, deterministic reports, reflection, playbook versioning, and recall. Broad asset coverage, richer scoring, sync, and viewers can follow only after that slice works.

## Differentiation

| System | What it is | Where it overlaps | Where Trade Trace differs |
|--------|-----------|-------------------|---------------------------|
| **Tradervue / Edgewonk / TradeZella** | Web journals for human traders | Decision logging, P&L analytics | Agent-native, MCP/CLI-first, no human UI, calibration as core |
| **TradingAgents (TauricResearch)** | Multi-agent LLM trading framework | Decision logging + reflection memory | No execution; journaling and grading only; memory is a typed graph not raw markdown |
| **Hindsight (Vectorize.io)** | General agent memory: Retain/Recall/Reflect | Memory abstraction shape | Trading-specific schema: outcome-linked, calibration-aware, position-provenanced |
| **Mem0 / Letta / Zep** | General agent memory frameworks | Multi-strategy retrieval | Domain-specific; would not be a good fit if generalized |
| **ForecastBench** | Forecasting benchmark | Calibration scoring | Tooling, not benchmark — export shape remains TBD until schema verification |
| **TradeNote / Deltalytix** | Open-source self-hosted journals | Local-first, open-source | Agent-native; no web UI; memory + reflection loop |

## Non-goals

- Trade execution of any kind in any version of the product, unless explicitly re-scoped with separate safety design.
- Broker / wallet credential handling.
- External data fetching of any kind — the agent supplies all market data through structured ingestion APIs.
- Real-time alerting, paging, or scheduling (deferred to external orchestrators).
- Generic agent memory framework — Trade Trace's memory is trading-shaped.
- Backtesting or market simulation engines.
- Full tax accounting or broker-grade portfolio accounting.
- Product web dashboard for human users. Optional static/read-only inspection exports may be considered later.
- Social / community / leaderboard features.
- Any claim of profitability, edge, or financial advice.
- Venue-specific product semantics — fields like Polymarket condition IDs, options Greeks, or futures contract specs live in `metadata_json`, not in the core schema.

## Safety posture

- The MVP cannot execute trades. There is no surface that signs, routes, or transmits an order.
- The MVP makes no outbound network calls. There are no external data connectors, no third-party API clients, no webhooks, and no telemetry. The product is air-gappable.
- The core never reads, stores, logs, or asks for private keys, seed phrases, broker credentials, wallet signatures, or API keys. The credential ban is unconditional.
- Local journal data contains sensitive trading information. Default file permissions are user-only (`0600`) where the platform supports it. Exports that include actual trade details emit a stderr warning.
- All analytics are framed as retrospective decision support, not as recommendations. The system does not generate trade ideas or signals.

## Definition of done — vision level

Trade Trace's vision is satisfied when:

1. An LLM agent can run a complete trading research session — forming theses, recording decisions, taking paper or actual positions, reviewing outcomes, and writing reflections — entirely through MCP tools or the CLI, with zero human-facing UI required.
2. After 30 days of continuous dogfooding, the agent has identified at least one miscalibrated confidence bucket it didn't already know about (via the calibration report), and updated at least one playbook rule with provenance traceable back to a stored reflection.
3. Memory recall reliably surfaces relevant past observations and reflections when a new thesis is being formed on a similar instrument, market type, or scenario.
4. The system has graded binary forecasts across at least two forecast patterns where possible: direct binary prediction markets and derived directional binary equity/crypto forecasts at a defined horizon.
5. No trade has ever been placed by the system.

The success question is not *"does this look like a trading journal?"* but:

> **Does this make the LLM trader auditable, calibratable, and improvable over time?**

If yes, the vision is met.
