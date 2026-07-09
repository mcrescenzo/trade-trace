# Trade Trace — v0.0.2 product scope and principles

> Status: **shipped** — scope, principles, and non-goals governing the
> current journal-phase product. Formerly `docs/VISION.md` (the product
> vision until 2026-06-12); superseded as the north star by the root
> [`VISION.md`](../../VISION.md). The "not a trader" boundaries below
> remain binding for the current phase; the root vision frames them as
> the first stage of an earned-autonomy arc, not the end-state.

**Date:** 2026-05-18 (demoted from vision 2026-06-12)
**Audience:** Project maintainers and contributors
**Companion doc:** [`PRD.md`](../PRD.md)

## What this is

Trade Trace is a **local, open-source, AI-only journal, memory, and calibration substrate for LLM prediction-market agents.** It is a Python package distributed as both a Model Context Protocol (MCP) server and a CLI, with a JSON-first output contract. It records — and helps an LLM agent reason about — prediction markets, snapshots, binary probability forecasts, optional decisions, resolutions, reflections, and playbook rules. It scores forecasts when outcomes resolve and surfaces structured signals the agent can use to refine its own forecasting process.

The wedge is the intersection of three gaps in the 2026 landscape:

1. **Human trading journals** (Tradervue, TradesViz, Edgewonk, TradeZella) are optimized for discretionary human traders, broad asset classes, fills, and web UX. None are agent-native PM calibration ledgers.
2. **Prediction-market LLM agents** can produce forecasts or trades, but they rarely keep a durable, local, schema-checked record of market baselines, forecast timing, resolution rules, and calibration feedback.
3. **AI agent memory systems** (Hindsight, Mem0, Letta, Zep) generalize over arbitrary domains and do not understand prediction-market concepts such as condition IDs, resolution status, anchored market probabilities, forecast scoring, or playbook adherence.

Trade Trace lives at that intersection. It is a *grader* and a *memory*, not a *trader*.

## What this is not

- **Not an executor.** Trade Trace never places, signs, cancels, or routes a trade. It never handles wallet keys, broker credentials, or seed phrases. Execution is a separate concern with separate safety design.
- **Not a default data fetcher.** Trade Trace makes no outbound calls by default and has no scheduler, daemon, webhook, or default RPC endpoint. The v0.0.2 Polymarket adapter is explicit opt-in, agent-triggered, and requires caller-supplied configuration; the agent can also supply all snapshots, outcomes, and metadata manually through structured APIs.
- **Not a remote dashboard or trading UI.** Trade Trace has no shipped human-facing dashboard; the former Console UI was hard-removed. Outputs are JSON-by-default for agents through MCP, CLI, and library/reporting surfaces.
- **Not a generic agent memory framework.** Trade Trace's memory layer is prediction-market-specific: nodes carry market/resolution links, calibration confidence, and process provenance. If you want a general memory store, use Mem0, Letta, Zep, or Hindsight directly.
- **Not a backtesting or simulation engine.** Trade Trace records and grades forecasts against supplied or explicitly fetched resolutions. It does not synthesize market data, replay historical fills, or simulate execution.
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
4. **Prediction-market-first core.** v0.0.2 intentionally narrows to binary prediction markets. Core tables model markets, snapshots, forecasts, and resolutions directly; venue-specific addenda live in `metadata_json`. Continuous assets such as equities, options, futures, FX, crypto spot/perps, and Greeks are out of scope.
5. **Local-first by default.** Storage is a single SQLite database. JSONL can be exported from committed DB events/outbox records for audit and portability; it is not a second source of truth. No remote services are required. Venue clients preserve local-first by staying opt-in, explicit, and disabled by default.
6. **MCP-first, CLI-equivalent, JSON-first contract.** Every operation is exposed as an MCP tool and as an equivalent CLI command. Schemas and semantics are equivalent after transport normalization. CLI output is JSON to stdout; prose is suppressed by default and only emitted to stderr when `--human` is requested. Errors carry stable codes.
7. **Structured input, graceful prose.** Prefer explicit fields with schema validation, but allow attached freeform notes for the LLM to reason about.
8. **Auditability over convenience.** Snapshots, theses, decisions, and memory nodes are append-only and versioned. Corrections create new events; nothing is silently overwritten.
9. **Memory and ledger are linked but distinct.** The trade ledger is strict, typed, and auditable — the agent's actions and what the market did. The memory layer is a flexible graph — the agent's beliefs, observations, and reflections. Both worlds cross-link through a single edges table. Beliefs are versioned and falsifiable; ledger facts are immutable.
10. **The agent is the one with judgment.** The system surfaces objective process diagnostics (calibration drift, mistake-tag frequency, advisory/manual playbook overrides, stale watches) but does not decide what counts as a mistake, generate trading signals, rank opportunities, or recommend trades.

## Primary persona

**The LLM trading agent.** Trade Trace is built for an agent that:

- Binds or records prediction markets and their resolution context
- Records what market probability and evidence were known at each forecast/decision point
- Produces binary probability forecasts, with optional watch/skip/paper/enter/exit/hold/add/reduce-style decisions outside Trade Trace's execution boundary
- Has its forecasts graded when outcomes resolve
- Reads back past observations, reflections, and playbook rules when forming a new market thesis
- Periodically reviews calibration and writes reflections that update its playbooks

Trade Trace is **not** built for a human discretionary trader. Humans are welcome as project maintainers, contributors, and dogfooders — but the product's surfaces are designed for token-efficient, schema-driven, machine-readable interaction.

## The four-layer self-improvement loop

Trade Trace's central feature is a closed loop that turns prediction-market forecasting experience into refined process. The system supplies the primitives; the agent supplies the judgment.

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

Reflections, reports, and recall can be scoped by **strategy** — a named strategy thesis (e.g., `earnings-momentum`, `pairs-trade-XYZ`) that groups decisions, theses, and reviews into one logical grain. This is retrospective grouping/process context only; it is not an edge detector, opportunity ranking, or recommendation surface. The loop then runs not just per-decision but per-strategy: the agent can ask "is this strategy coherent, sourced, reviewed, and calibrated?" without smearing those diagnostics across unrelated trades. Strategies are orthogonal to playbooks (rules) and tags (free-form sub-classifiers); see PRD §2.12.

This loop is the product. v0.0.2 proves the complete loop with narrow breadth: PM market binding, snapshot capture, binary scoring, deterministic reports, reflection, playbook versioning, and recall. Broad asset coverage, richer scoring, sync, and viewers are out of scope until this slice works.

## Differentiation

| System | What it is | Where it overlaps | Where Trade Trace differs |
|--------|-----------|-------------------|---------------------------|
| **Tradervue / Edgewonk / TradeZella** | Web journals for human traders | Decision logging, P&L analytics | Agent-native, MCP/CLI-first, no human UI, calibration as core |
| **TradingAgents (TauricResearch)** | Multi-agent LLM trading framework | Decision logging + reflection memory | No execution; journaling and grading only; memory is a typed graph not raw markdown |
| **Hindsight (Vectorize.io)** | General agent memory: Retain/Recall/Reflect | Memory abstraction shape | Trading-specific schema: outcome-linked, calibration-aware, position-provenanced |
| **Mem0 / Letta / Zep** | General agent memory frameworks | Multi-strategy retrieval | Domain-specific; would not be a good fit if generalized |
| **ForecastBench** | Forecasting benchmark | Calibration scoring | Tooling, not benchmark — export shape remains TBD until schema verification |
| **TradeNote / Deltalytix** | Open-source self-hosted journals | Local-first, open-source | Agent-native; no human UI; memory + reflection loop |

## Borrowed patterns (and what they translate to)

Trade Trace borrows analytical and architectural patterns from existing systems without copying their product surface. The rule is: borrow what helps an AI agent reason, reject what only serves a human UI.

From **Tradervue / Edgewonk** (human trading journals):

- **Report drill-down** — aggregates carry the filter spec and contributing record IDs so an agent can pull the exact underlying decisions. Translated as the `ReportFilter` / `ReportResult` / `ReportGroup` contracts in `reports.md`, not as clickable charts.
- **Tags + tag-combination reports** — free-form sub-classifiers with a tag-co-occurrence query model. Already in MVP through `decision_tags`, the public mistakes report, and coach's internal tag-strength view.
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
- Default/background external data fetching. The only v0.0.2 venue client is the opt-in, agent-triggered Polymarket adapter with no default RPC URL.
- Real-time alerting, paging, or scheduling (deferred to external orchestrators).
- Generic agent memory framework — Trade Trace's memory is trading-shaped.
- Backtesting or market simulation engines.
- Full tax accounting or broker-grade portfolio accounting.
- Cloud-hosted or local product dashboard for human users. The former local read-only Console UI has been hard-removed; current surfaces remain MCP, CLI, and library/reporting APIs.
- Social / community / leaderboard features.
- Any claim of profitability, edge, or financial advice.
- Continuous-asset trading journal scope: equities, options, futures, FX, crypto spot/perps, Greeks, and broker/fill accounting are outside v0.0.2. Polymarket condition/market concepts are first-class; venue-specific addenda still live in `metadata_json`.

## Safety posture

- The MVP cannot execute trades. There is no surface that signs, routes, or transmits an order.
- **Offline by default:** Trade Trace never fetches broker data, places orders, runs webhooks, sends telemetry, or auto-updates. No network socket opens on first run or ordinary local journal operations. The Polymarket adapter is the explicit exception: disabled by default, caller-configured, agent-triggered, HTTPS-only, and scrubbed in logs/errors.
- **One opt-in local embeddings path:** the optional SEMANTIC recall strategy uses pre-staged local ONNX/tokenizers model assets (see PRD §2.4.1 and `memory-layer.md` §8). Off by default in MVP; opt-in via explicit config; no model weights are downloaded by configuration; no memory or trading data leaves the machine. Remote/API embedding providers are unsupported in v0.0.2.
- The core never reads, stores, logs, or asks for private keys, seed phrases, broker credentials, wallet signatures, trading-API keys, or embedding-provider API keys. The credential ban is unconditional for v0.0.2.
- Local journal data contains sensitive trading information. Default file permissions are user-only (`0600`) where the platform supports it. Exports that include actual trade details emit a stderr warning. Sources flagged `redaction_status = sensitive` are never included in review bundles.
- All analytics are framed as retrospective decision support, not as recommendations. The system does not generate trade ideas or signals.

## Definition of done — vision level

Trade Trace's vision is satisfied when:

1. An LLM agent can run a complete prediction-market research session — binding a market, recording snapshots, writing binary forecasts, optionally recording decisions, reviewing resolutions, and writing reflections — entirely through MCP tools or the CLI, with zero human-facing UI required.
2. After 30 days of continuous dogfooding, the agent has identified at least one miscalibrated confidence bucket it didn't already know about (via the calibration report), and updated at least one playbook rule with provenance traceable back to a stored reflection.
3. Memory recall reliably surfaces relevant past observations and reflections when a new thesis is being formed on a similar market, event type, or scenario.
4. The system has graded binary forecasts across direct prediction-market patterns, including forecast-only research loops and decision-attached market loops.
5. No trade has ever been placed by the system.

The success question is not *"does this look like a trading journal?"* but:

> **Does this make the LLM prediction-market agent auditable, calibratable, and improvable over time?**

If yes, the vision is met.
