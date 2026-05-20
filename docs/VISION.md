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
- **Not a remote dashboard or trading UI.** The optional `trade-trace[console]` extra ships a **local, read-only** React analytics dashboard at `http://127.0.0.1:8765` (see [`docs/CONSOLE.md`](./CONSOLE.md)). Outputs are JSON-by-default for agents; the Console is a read-only renderer over the same JSON, not a trading workflow.
- **Not a generic agent memory framework.** Trade Trace's memory layer is trading-specific: nodes carry outcome links, calibration confidence, and position provenance. If you want a general memory store, use Mem0, Letta, or Hindsight directly.
- **Not a backtesting or simulation engine.** Trade Trace records and grades real and paper trades. It does not synthesize market data or replay historical fills.
- **Not a portfolio accounting system.** It computes P&L and basic exposure metrics, but it is not broker-grade and is not a tax tool.
- **Not a benchmark.** Trade Trace may export ForecastBench-inspired data once the external schema is verified, but it is the tooling, not a leaderboard.

## Why now

Three shifts make 2026 the right moment:

- **LLMs are becoming useful forecasting actors, but calibration remains fragile.** Recent forecasting work shows rapid improvement, while still leaving a gap to strong human forecasting and large variance across tasks. Trade Trace exists because agents need auditable calibration feedback, not because parity is guaranteed.
- **Agent memory is now a real engineering discipline.** Mem0, Hindsight, Letta, Zep, SYNAPSE, and others have converged on a recognizable shape: episodic + semantic + reflective memory with multi-strategy retrieval (BM25 + temporal + vector + graph, distinct from trading strategies). The patterns are stable enough to specialize.
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

Reflections, reports, and recall can be scoped by **strategy** — a named edge thesis (e.g., `earnings-momentum`, `pairs-trade-XYZ`) that groups decisions, theses, and reviews into one logical grain. The loop then runs not just per-decision but per-strategy: the agent can ask "how is this strategy performing, what mistakes recur in it, what rule changes does it suggest?" without smearing those signals across unrelated trades. Strategies are orthogonal to playbooks (rules) and tags (free-form sub-classifiers); see PRD §2.12.

This loop is the product. The MVP proves the complete loop with narrow breadth: structured manual ingestion, binary scoring, deterministic reports, reflection, playbook versioning, and recall. Broad asset coverage, richer scoring, sync, and viewers can follow only after that slice works.

## Differentiation

| System | What it is | Where it overlaps | Where Trade Trace differs |
|--------|-----------|-------------------|---------------------------|
| **Tradervue / Edgewonk / TradeZella** | Web journals for human traders | Decision logging, P&L analytics | Agent-native, MCP/CLI-first, no human UI, calibration as core |
| **TradingAgents (TauricResearch)** | Multi-agent LLM trading framework | Decision logging + reflection memory | No execution; journaling and grading only; memory is a typed graph not raw markdown |
| **Hindsight (Vectorize.io)** | General agent memory: Retain/Recall/Reflect | Memory abstraction shape | Trading-specific schema: outcome-linked, calibration-aware, position-provenanced |
| **Mem0 / Letta / Zep** | General agent memory frameworks | Multi-strategy retrieval | Domain-specific; would not be a good fit if generalized |
| **ForecastBench** | Forecasting benchmark | Calibration scoring | Tooling, not benchmark — export shape remains TBD until schema verification |
| **TradeNote / Deltalytix** | Open-source self-hosted journals | Local-first, open-source | Agent-native; optional local read-only Console; memory + reflection loop |

## Borrowed patterns (and what they translate to)

Trade Trace borrows analytical and architectural patterns from existing systems without copying their product surface. The rule is: borrow what helps an AI agent reason, reject what only serves a human UI.

From **Tradervue / Edgewonk** (human trading journals):

- **Report drill-down** — aggregates carry the filter spec and contributing record IDs so an agent can pull the exact underlying decisions. Translated as the `ReportFilter` / `ReportResult` / `ReportGroup` contracts in `reports.md`, not as clickable charts.
- **Tags + tag-combination reports** — free-form sub-classifiers with a tag-co-occurrence query model. Already in MVP (`decision_tags`, `report.mistakes`, `report.strengths`).
- **R-multiple / risk-normalized analytics** — every trade carries declared risk so P&L can be unit-normalized. P1 per `risk-units.md`.
- **MFE/MAE / exit efficiency** — path-dependent process diagnostics over snapshot series the agent supplied. P1 per `opportunity-analysis.md`. Never fetches market data.
- **Mentor read-only + private comments** — adapted as `review.bundle`: a deterministic packet a separate reviewer (LLM or human) consumes. No SaaS sharing.
- **Account tags as a tag, not a separate entity** — account/portfolio bucket is a `metadata_json` key, not a first-class field. Avoids broker-account semantics.
- **Generic CSV import schema (execution-level fills)** — captured as the import-ready write schema in MVP; JSONL/CSV importers ship as P1 implementations.

From **Hindsight / Mem0 / Letta / Zep** (AI memory systems):

- **Retain / Recall / Reflect surface naming** — agent-developer familiarity.
- **Multi-strategy retrieval (BM25 + vector + temporal + graph) with RRF fusion** — standard, adopted directly.
- **Bi-temporal records (Zep / Graphiti)** — every belief-shaped row records both transaction time (`created_at`, `invalidated_at`) and world time (`valid_from`, `valid_to`) so "what did the agent believe on day X" is a primitive query. Load-bearing for honest calibration replay.
- **Importance scoring at write time (Generative Agents)** — every memory node carries `importance ∈ [1, 10]`, fed into recall ranking. Lets writer-set salience drive surfacing rather than letting "loudest" win.
- **Episodic / semantic / procedural memory types (Mem0)** — Trade Trace's three node types (`observation`, `reflection`, `playbook_rule`) map onto this distinction.

From **ForecastBench / Manifold / Brier.fyi** (LLM forecasting):

- **Full calibration panel** — not just Brier. The MVP `report.calibration` emits Brier + log score + reliability bins + ECE + sharpness + sample-prevalence baseline so "agent improved" and "agent got more confident" are distinguishable signals.
- **Resolution rule recorded at prediction time** — `forecasts.resolution_rule_text` is captured at create time, not derived later, to keep resolution decisions auditable.

## Non-goals

- Trade execution of any kind in any version of the product, unless explicitly re-scoped with separate safety design.
- Broker / wallet credential handling.
- External data fetching of any kind — the agent supplies all market data through structured ingestion APIs.
- Real-time alerting, paging, or scheduling (deferred to external orchestrators).
- Generic agent memory framework — Trade Trace's memory is trading-shaped.
- Backtesting or market simulation engines.
- Full tax accounting or broker-grade portfolio accounting.
- Cloud-hosted product dashboard for human users. The local read-only Console (`trade-trace[console]`) supersedes the prior "static exports may be considered later" framing — see [`docs/CONSOLE.md`](./CONSOLE.md) and [`docs/architecture/console.md`](./architecture/console.md).
- Social / community / leaderboard features.
- Any claim of profitability, edge, or financial advice.
- Venue-specific product semantics — fields like Polymarket condition IDs, options Greeks, or futures contract specs live in `metadata_json`, not in the core schema.

## Safety posture

- The MVP cannot execute trades. There is no surface that signs, routes, or transmits an order.
- **Forbidden network surface:** Trade Trace never fetches trading data, broker data, market prices, order books, or outcomes. There are no broker integrations, no market-data clients, no webhooks, no telemetry, and no auto-update. The product is air-gappable on first run.
- **One opt-in outbound path:** the optional local embedding model download for the SEMANTIC recall strategy (see PRD §2.4.1). Off by default in MVP; opt-in via explicit config; carries only model weights, never trading data. API embedding providers (memory-layer.md §8.3) are a separate also-opt-in path that DOES send memory text outward and carries an explicit configure-time warning. Neither path activates by default.
- The core never reads, stores, logs, or asks for private keys, seed phrases, broker credentials, wallet signatures, or trading-API keys. The credential ban is unconditional. Embedding-provider API keys (when an API provider is opt-in) are stored in the OS keyring, never in the database or plaintext config, never logged.
- Local journal data contains sensitive trading information. Default file permissions are user-only (`0600`) where the platform supports it. Exports that include actual trade details emit a stderr warning. Sources flagged `redaction_status = sensitive` are never included in review bundles.
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
