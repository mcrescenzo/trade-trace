# Trade Trace — Product Requirements Document

**Date:** 2026-05-18
**Status:** Refined draft
**Companion docs:** [`VISION.md`](./VISION.md), [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md), [`docs/architecture/connector-interface.md`](./docs/architecture/connector-interface.md)

This document is the working PRD that drives implementation. It captures the locked decisions from the 2026-05-18 refinement session, sketches data models and APIs, enumerates milestones, and tracks remaining open questions.

## 1. Executive summary

Trade Trace is a local, open-source, AI-only journal/memory/calibration substrate for LLM trading agents, distributed as a Python package exposing both an MCP server and a CLI with a JSON-only output contract. It records every decision the agent makes across markets, grades forecasts when outcomes resolve, stores agent reflections as a typed knowledge graph, and runs a four-layer self-improvement loop (primitive reports → coach synthesis → reflection → playbook evolution). It does not execute trades. It does not handle credentials. It is not a human dashboard.

The product is **market-agnostic at the core** (prediction markets, equities, options, futures, crypto, event markets share a generic decision/position/outcome spine), with **plugin connectors** for first-party venues (Polymarket, Manifold, yfinance in MVP). The full product is planned from day one; there is no MVP shortcut.

## 2. Decisions log

The following decisions were locked in the 2026-05-18 refinement session and are non-negotiable assumptions for the rest of this document.

### 2.1 Memory layer — custom, trading-native

The memory layer is built in-house, modeled on Hindsight's **Retain / Recall / Reflect** API surface (so other tooling can swap in or out) but backed by a trading-specific schema: every memory node can link to ledger rows (decisions, positions, outcomes), carries calibration-aware confidence and decay, and supports typed edges to other memory nodes. No external memory framework as a runtime dependency.

**Rationale:** The trading semantics (outcome-linked recall, position provenance, calibration-decayed confidence) do not fit a generic memory store without significant retrofitting. Owning the schema is cheaper than wrapping Hindsight and fighting its assumptions.

### 2.2 Data model — hybrid ledger + memory graph

The trade ledger (decision, position, position_event, snapshot, outcome, forecast, thesis, source, instrument, venue, playbook, playbook_version) lives in strictly-typed SQL tables with foreign-key relationships, append-only semantics, and an event log. The memory layer (observation, reflection, semantic_claim, playbook_rule, coach_signal) lives in a unified `memory_nodes` table with a node-type discriminator and embedding columns. A single `edges` table connects any node to any other node *or* to any ledger row, with typed edges (supports, contradicts, supersedes, links, derived_from, about, violates, follows).

**Rationale:** P&L roll-ups, position math, and calibration scoring need clean SQL; agent recall needs flexible graph traversal. Both worlds cross-link cleanly via the edges table.

### 2.3 Self-improvement loop — full four-layer loop in MVP

All four layers ship in MVP: (1) primitive reports, (2) `coach` synthesis, (3) agent-written reflections, (4) versioned playbook rules with provenance and override tracking. This is the product wedge; anything less makes Trade Trace a generic journal.

**Rationale:** Without playbook evolution, the journal is just a logger. Without reflection, the agent has no synthesis loop. Without `coach`, the agent burns tokens computing primitives. Without primitive reports, `coach` has nothing to synthesize.

### 2.4 Surface — CLI + MCP, MCP-primary, JSON-only

One Python package, single internal `trade_trace.core` API, two thin parallel front-ends: an MCP server (primary) and a CLI (equivalent). All output is JSON to stdout. No human prose is emitted unless `--human` is explicitly passed, in which case prose goes to stderr only. Errors are structured JSON with stable `code` fields. Streams are NDJSON (one JSON object per line, newline-delimited).

**Rationale:** Schema introspection and host integration (Claude Code, Cursor) demand MCP; token-efficient batch writes and scriptability demand CLI; identical contracts let agents treat them interchangeably.

### 2.5 Connectors — plugin architecture + first-party for marquee venues

The core package defines a `Connector` ABC with three required methods (`snapshot`, `resolve`, `search`) and a small capability-flag interface. First-party connectors for Polymarket (Gamma read-only), Manifold, and yfinance ship in MVP. Third-party connectors are separate pip packages registered via the `trade_trace.connectors` entry point group. Manual snapshot and outcome entry is always supported; no connector is ever required to use the journal.

**Rationale:** Out-of-box experience for marquee venues without committing to maintain the universe of connectors. Plugin model encourages community contribution without growing core.

### 2.6 Forecast model — multi-outcome from day one, calibration first-class

Forecasts are modeled to support binary, multi-outcome categorical, and scalar/continuous distributions from the data layer onward. **Long form**: one row per outcome in `forecast_outcomes` with `probability` and `lower_bound` / `upper_bound` columns where applicable, linked to a `forecasts` parent. MVP ships binary Brier scoring; multi-class Brier and ranked probability score land in P1. **Calibration is a first-class feature, not a report** — every decision with a forecast is auto-scored the moment an outcome resolves, calibration drift is a top-level metric in `coach` output, and exports are ForecastBench-compatible.

**Rationale:** Manifold has MULTIPLE_CHOICE / NUMERIC / PSEUDO_NUMERIC natively. A binary-only data model would force a repaint within months. Auto-scoring at resolution time means the agent never has a stale picture of its own performance.

### 2.7 Storage — SQLite + sqlite-vec + FTS5 + JSONL log

Single SQLite file as the source of truth. The `sqlite-vec` extension provides vector similarity for memory recall. SQLite FTS5 provides BM25 keyword recall. Both back the multi-strategy retrieval (semantic + keyword + temporal + graph). A JSONL append-only event log is written alongside SQLite for audit, portability, and recovery. Pydantic v2 schemas are the single source of truth, generating MCP tool definitions, CLI argument validators, and DB serializers.

**Rationale:** One file, no extra services, queryable, durable, supports all retrieval strategies natively. JSONL log gives a portable durable record independent of SQLite if the schema ever needs aggressive migration.

### 2.8 Embeddings — configurable, default local

Bundle `BAAI/bge-small-en-v1.5` (133MB, top-tier small open model in 2026) as the default embedding model via `sentence-transformers`. Override via config to use Claude, OpenAI, or Voyage embedding APIs for higher-quality recall. Local default preserves the local-first promise; API override gives a quality lever.

**Rationale:** Local-first is a stated principle. Embedding API calls would route every memory write/recall through a network. Small local models are good enough for in-domain similarity; the API path exists for users who want it.

### 2.9 Open questions resolved during PRD authoring

The following were marked open in the refinement plan and are resolved here:

| # | Question | Decision |
|---|----------|----------|
| 1 | Command/tool naming | CLI: `trade-trace`. Python module: `trade_trace`. PyPI package: `trade-trace`. |
| 2 | License | **MIT** (most permissive open-source license; matches ecosystem norms for AI/finance tooling) |
| 3 | Python floor | **3.11** (Pydantic v2, fastmcp, sqlite-vec all support; broad compatibility) |
| 4 | Embedding default | `BAAI/bge-small-en-v1.5` |
| 5 | MCP framework | `fastmcp` (decorator-based, ergonomic, widely adopted) |
| 6 | Multi-outcome forecast shape | Long form: rows in `forecast_outcomes` linked to a `forecasts` parent |
| 7 | Memory decay model | Both: per-node `decay_rate_per_day` (default by node type) + edge-density modulation at recall time |
| 8 | Playbook rule format | Both: structured `rule_meta` for override detection + free-text `rule_body` for agent reasoning |
| 9 | Coach trigger | On-demand primary (`report.coach`). System auto-emits `coach_signal` memory nodes on notable events (calibration drift, large outcome surprise, stale watch). External scheduling is deferred. |
| 10 | Repository layout | **Monorepo, single package with optional extras**. `pip install trade-trace` for core; `pip install trade-trace[polymarket,manifold,yfinance]` for connectors. First-party connectors live under `trade_trace/connectors/`. Third-party connectors are separate packages. |

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│                       LLM Trading Agent                         │
│                  (Claude / GPT / local / etc.)                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
   ┌─────────────────────┐         ┌─────────────────────┐
   │   MCP server        │         │       CLI           │
   │   (fastmcp,         │         │  (typer, JSON-only) │
   │   primary surface)  │         │                     │
   └──────────┬──────────┘         └──────────┬──────────┘
              │                                │
              └────────────────┬───────────────┘
                               │
                               ▼
                  ┌──────────────────────────┐
                  │   trade_trace.core       │
                  │  (single internal API,   │
                  │   pydantic schemas)      │
                  └────────────┬─────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
        ▼                      ▼                      ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│  Ledger       │      │  Memory       │      │  Connectors   │
│  (strict SQL) │      │  (graph)      │      │  (plugins)    │
│  ─────────    │      │  ─────────    │      │  ─────────    │
│ decisions     │      │ memory_nodes  │      │ Polymarket    │
│ positions     │──┬──▶│ edges         │      │ Manifold      │
│ snapshots     │  │   │ (sqlite-vec,  │      │ yfinance      │
│ forecasts     │  │   │  FTS5)        │      │ (third-party  │
│ outcomes      │  │   └───────────────┘      │  via entry    │
│ instruments   │  │           ▲              │  points)      │
│ ...           │  │           │              └───────┬───────┘
└───────────────┘  │           │                      │
                   └───────────┴──────────────────────┘
                          edges link ledger ↔ memory
                          and connector data → snapshots/outcomes
                               │
                               ▼
                  ┌──────────────────────────┐
                  │  trade-trace.sqlite      │
                  │  + events.jsonl (audit)  │
                  └──────────────────────────┘
```

Pydantic schemas in `trade_trace.schemas` define every entity. The MCP server uses fastmcp to generate JSON schemas from pydantic models automatically. The CLI uses typer with the same schemas. The core API exposes a single set of methods, both front-ends call into it.

## 4. Data model

### 4.1 Ledger tables

All ledger tables are append-only or versioned. Corrections create new rows; nothing is silently overwritten.

#### `venues`
- `id` (text, primary key, e.g., `polymarket`, `manifold`, `yfinance`, `manual`)
- `name`, `kind` (prediction_market, equity, options, futures, crypto, event_market, other)
- `connector_name` (nullable; references an installed connector)
- `metadata_json`
- `created_at`

#### `instruments`
- `id` (uuid)
- `venue_id` (FK)
- `external_id` (venue-specific ID), `symbol`, `title`
- `asset_class` (text)
- `currency_or_collateral`
- `multi_outcome` (bool)
- `expiration_or_resolution_at` (nullable)
- `resolution_criteria_text` (nullable)
- `contract_multiplier` (nullable, for options/futures)
- `metadata_json`
- `created_at`

#### `snapshots`
- `id` (uuid)
- `instrument_id` (FK)
- `captured_at` (timestamp)
- `source` (text: `connector:polymarket`, `manual`, `import:csv`, …)
- `source_url` (nullable)
- `price`, `bid`, `ask`, `mid`, `spread`
- `volume`, `open_interest`, `liquidity_depth_json`
- `implied_probability` (nullable, for prediction markets)
- `metadata_json`
- Immutable; corrections create new rows.

#### `theses`
- `id` (uuid)
- `instrument_id` (FK)
- `version` (int, starts at 1)
- `parent_thesis_id` (FK, nullable — points to previous version)
- `side` (text: yes/no/long/short/call/put/multi/…)
- `time_horizon_at` (timestamp, nullable)
- `confidence_label` (text: low/medium/high/extreme — agent-defined; the *forecast* row carries the numeric probability)
- `body` (text)
- `falsification_criteria` (text)
- `exit_triggers` (text)
- `risk_notes` (text)
- `created_at`
- Versioned: thesis updates create new rows linked via `parent_thesis_id`.

#### `forecasts`
- `id` (uuid)
- `thesis_id` (FK)
- `kind` (text: binary, categorical, scalar)
- `resolution_at` (timestamp, nullable)
- `created_at`

#### `forecast_outcomes`
- `id` (uuid)
- `forecast_id` (FK)
- `outcome_label` (text, e.g., "YES", "NO", "AAPL>200@2026-06-30")
- `probability` (float, 0-1)
- `lower_bound`, `upper_bound` (float, nullable — for scalar/continuous)
- One row per outcome; for binary forecasts there are typically two rows.

#### `decisions`
- `id` (uuid)
- `instrument_id` (FK)
- `thesis_id` (FK, nullable)
- `forecast_id` (FK, nullable)
- `snapshot_id` (FK, nullable — what was the market state at decision time)
- `type` (text: watch, skip, paper_enter, paper_exit, actual_enter, actual_exit, add, reduce, hold, invalidate_thesis, update_thesis, resolved, review)
- `side`, `quantity`, `price`, `fees`, `slippage` (nullable — only relevant for enter/exit/add/reduce)
- `reason` (text)
- `playbook_version_id` (FK, nullable — which playbook was in force)
- `playbook_overrides_json` (list of rule IDs the agent intentionally overrode)
- `review_by` (timestamp, nullable — used for watch entries)
- `tags` (text[])
- `created_at`
- Append-only.

#### `positions`
- `id` (uuid)
- `instrument_id` (FK)
- `kind` (paper, actual)
- `side`
- `status` (open, closed, resolved)
- `opened_at`, `closed_at`, `resolved_at`
- `realized_pnl`, `unrealized_pnl`, `avg_entry_price`
- Derived from `position_events`.

#### `position_events`
- `id` (uuid)
- `position_id` (FK)
- `decision_id` (FK)
- `event_type` (open, add, reduce, close, partial_close, resolve, mark)
- `quantity_delta`, `price`, `fees`, `slippage`
- `created_at`

#### `outcomes`
- `id` (uuid)
- `instrument_id` (FK)
- `resolved_at`
- `outcome_label` (text — matches one or more `forecast_outcomes.outcome_label` if a forecast exists)
- `outcome_value` (float — final settle value, e.g., 1.0 for YES at $1, or the actual return)
- `source` (text)
- `confidence` (float — 1.0 for unambiguous resolutions; <1 for disputed/delayed prediction markets)
- `metadata_json`

#### `sources`
- `id` (uuid)
- `kind` (text: url, file, ref, note)
- `ref` (text — URL, path, or identifier)
- `title`, `note`
- `stance` (text: supporting, opposing, neutral, background)
- `captured_at`
- Attached to theses, decisions, reviews, or memory nodes via the `edges` table.

#### `reviews`
- `id` (uuid)
- `target_kind` (text: decision, position, instrument, period, playbook)
- `target_id` (uuid)
- `classification` (text: good_process_good_outcome, good_process_bad_outcome, bad_process_good_outcome, bad_process_bad_outcome, unreviewable_missing_data)
- `mistake_tags`, `strength_tags` (text[])
- `body` (text)
- `next_rule_suggestion` (text — optional; may spawn a playbook_rule node)
- `created_at`
- Reviews are reusable but each review row is immutable.

#### `playbooks`
- `id` (uuid)
- `name` (text, unique)
- `description` (text)
- `created_at`

#### `playbook_versions`
- `id` (uuid)
- `playbook_id` (FK)
- `version` (int, starts at 1)
- `parent_version_id` (FK, nullable)
- `created_at`
- `provenance_reflection_node_id` (uuid, nullable — points to the memory node that motivated this version)
- Each `playbook_rule` memory node belongs to a `playbook_version`; new versions are created when rules change.

### 4.2 Memory graph

#### `memory_nodes`
- `id` (uuid)
- `node_type` (text: observation, reflection, semantic_claim, playbook_rule, coach_signal)
- `version` (int, defaults 1; bumps for typed nodes that version like `playbook_rule`)
- `parent_node_id` (uuid, nullable)
- `title` (text, short)
- `body` (text, the actual content)
- `meta_json` (typed metadata per node_type)
- `confidence_base` (float 0-1)
- `decay_rate_per_day` (float; default by node type; see [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md))
- `embedding` (blob — sqlite-vec column; computed at write time)
- `embedding_text_fts` (text — FTS5 virtual column)
- `created_at`, `last_recalled_at`, `recall_count`
- Append-only. Updates create new nodes with `parent_node_id` set.

**Per-`node_type` `meta_json` fields:**

- **observation**: `{ instrument_id?, venue_id?, asset_class?, pattern_kind? }`
- **reflection**: `{ target_kind, target_id, mistake_tags?, strength_tags? }`
- **semantic_claim**: `{ scope: "market_type" | "venue" | "asset_class" | "general", scope_value? }`
- **playbook_rule**: `{ playbook_version_id, rule_meta: { trigger_kind, applicable_decision_types, applicable_asset_classes? } }`
- **coach_signal**: `{ signal_kind, severity, related_ledger_refs[] }`

#### `edges`
- `id` (uuid)
- `source_kind` (text: memory_node, decision, thesis, position, forecast, outcome, snapshot, review, playbook_version, source)
- `source_id` (uuid)
- `target_kind` (same enum)
- `target_id` (uuid)
- `edge_type` (text: supports, contradicts, supersedes, links, derived_from, about, violates, follows)
- `weight` (float, optional)
- `created_at`
- Append-only. To "remove" an edge, add a superseding `contradicts` edge — never delete.

Edges let any memory node link to any ledger row, and vice versa. A reflection "about" a decision is an edge with `(memory_node, reflection_id) -[about]-> (decision, decision_id)`. A playbook rule "violates" tag on a decision is an edge `(decision, decision_id) -[violates]-> (memory_node, rule_id)`.

## 5. Memory layer API

All three operations live in `trade_trace.core.memory`. MCP tools and CLI commands are thin wrappers.

### 5.1 `retain(node)`

Write an episodic observation, semantic claim, reflection, playbook rule, or coach signal.

```python
def retain(
    node_type: NodeType,
    title: str,
    body: str,
    *,
    meta: dict | None = None,
    links: list[EdgeSpec] | None = None,
    confidence_base: float = 1.0,
    decay_rate_per_day: float | None = None,  # default by node type
) -> MemoryNode
```

`links` accepts `EdgeSpec(target_kind, target_id, edge_type, weight?)`. Embeddings are computed automatically at write time using the configured provider.

### 5.2 `recall(...)`

Multi-strategy retrieval — semantic similarity, BM25, temporal proximity, graph traversal.

```python
def recall(
    *,
    query: str | None = None,                     # natural-language query
    context: ContextRef | None = None,            # ledger row to retrieve memories about
    node_types: list[NodeType] | None = None,
    strategies: list[Strategy] = [SEMANTIC, BM25, TEMPORAL, GRAPH],
    k: int = 10,
    min_confidence: float = 0.0,
    as_of: datetime | None = None,
) -> list[ScoredMemoryNode]
```

Each returned node carries its current effective confidence (base × decay × edge-density boost), match score per strategy, and the reasoning trail (which edges or embeddings surfaced it).

### 5.3 `reflect(target, insight, ...)`

Sugar over `retain(node_type=reflection, ...)` with structured target binding and automatic edge creation.

```python
def reflect(
    target: TargetRef,       # decision_id, position_id, period, tag, playbook_version_id
    insight: str,
    *,
    mistake_tags: list[str] | None = None,
    strength_tags: list[str] | None = None,
    supersedes: list[uuid] | None = None,    # reflection IDs this one supersedes
    derived_from: list[NodeRef] | None = None,  # observations / claims this reflection synthesizes
) -> MemoryNode
```

Reflect always creates `about` edges to the target and optionally `supersedes` / `derived_from` edges.

## 6. Self-improvement loop spec

### 6.1 Layer 1 — Primitive reports (deterministic)

All exposed as MCP tools and CLI commands under `report.*`:

- `report.calibration` — calibration curve by bucket, optionally filtered by venue / asset_class / tag / playbook_version / time_window. Outputs reliability table + Brier / ECE / log loss.
- `report.mistakes` — frequency and co-occurrence matrix of mistake tags (e.g., the top-20 pairs and how often they appear together).
- `report.strengths` — same but for strength tags.
- `report.pnl` — paper vs actual, optionally grouped by venue / asset_class / tag / playbook_version.
- `report.watchlist` — open watches with stale flag (review_by passed without action).
- `report.unscored_forecasts` — forecasts with passed resolution_at and no linked outcome row.
- `report.playbook_adherence` — for a given playbook_version, decisions in scope, overrides used, override outcomes (good/bad), rule-by-rule grade.
- `report.decision_velocity` — decisions per week broken down by type.

These never call the LLM. Pure SQL aggregation, NDJSON-streamable.

### 6.2 Layer 2 — `report.coach` (synthesis)

A synthesizing primitive that aggregates the above into a structured "things to think about" packet:

```json
{
  "as_of": "2026-05-18T12:00:00Z",
  "horizon_days": 30,
  "calibration_drift": [
    {
      "bucket": "high",
      "expected_resolution_rate": 0.85,
      "realized_resolution_rate": 0.62,
      "n": 14,
      "drift_zscore": -2.1
    }
  ],
  "top_mistake_tags": [
    {"tag": "liquidity-ignored", "count": 8, "trend": "up", "co_occurs_with": ["spread-too-wide"]}
  ],
  "playbook_warnings": [
    {"rule_id": "uuid", "rule_name": "no-trade-in-thin-markets", "overridden_count": 3, "override_pnl": -120.0}
  ],
  "overdue_reviews": [...],
  "stale_watches": [...],
  "unscored_forecasts": [...],
  "recent_coach_signals": [
    {"id": "uuid", "kind": "calibration_drift_high_bucket", "severity": "warn", "created_at": "...", "related": [...]}
  ]
}
```

`coach` has no opinions — it surfaces objective signals. The agent decides what to reflect on.

### 6.3 Layer 3 — Reflections (agent-driven)

Agents call `memory.reflect(target, insight, ...)` after running `coach`, reviewing a position, or reading a resolved outcome. Reflections are typed memory nodes, linked to ledger rows and other memory nodes via the edges table. They never disappear; they decay in confidence and can be superseded by newer reflections via a `supersedes` edge.

Recommended reflection cadence (a soft guideline, not enforced):
- After every paper / actual exit
- After every prediction-market resolution where a forecast existed
- After every `coach` invocation that surfaces a non-empty signal set
- Weekly summary reflection on a recent period

### 6.4 Layer 4 — Playbook evolution

Playbooks are versioned. Each playbook_version contains a set of playbook_rule memory nodes (with structured `rule_meta` for machine-checking and free-text `rule_body` for agent reasoning).

When an agent proposes a rule change:
1. The agent calls `playbook.propose_version(playbook_id, new_rules, provenance_reflection_id)`.
2. A new `playbook_versions` row is created.
3. New `playbook_rule` memory nodes are created with `parent_node_id` pointing to the prior version's rules where applicable.
4. An edge `(playbook_versions, new) -[derived_from]-> (memory_nodes, reflection)` captures provenance.

When a decision is recorded:
1. The current playbook_version_id is captured.
2. For each rule whose `trigger_kind` applies, the system checks whether the decision violates it.
3. Violations are recorded in `decisions.playbook_overrides_json` and an edge `(decision) -[violates]-> (rule)` is created.
4. When the outcome lands, override outcomes are aggregated in `report.playbook_adherence`.

This closes the loop: rule outcomes inform the next reflection, which informs the next rule version.

### 6.5 Coach signal events

The system auto-emits `coach_signal` memory nodes on notable events to surface them without requiring the agent to run `coach`:

- Outcome resolution where realized probability diverges from forecast by > 30%
- Calibration drift z-score < -2 in any bucket
- Playbook rule overridden 3+ times in 14 days
- Watchlist item passes `review_by` without action
- Forecast resolution_at passes without linked outcome (after a grace period)

These signals appear in the `recent_coach_signals` field of `report.coach`. They are real memory nodes with edges to the originating ledger rows, so they can be reflected upon directly.

## 7. Forecast & calibration spec

### 7.1 Forecast shape

A `forecasts` row anchors a forecast to a thesis. `forecast_outcomes` rows enumerate outcomes:

- **Binary**: 2 rows (e.g., YES p=0.62, NO p=0.38).
- **Categorical**: N rows, probabilities sum to 1.0 within tolerance.
- **Scalar / continuous**: one or more rows with `lower_bound`, `upper_bound`, and `probability` (interval probabilities), or a parametric distribution stored in `forecasts.distribution_json` (P1).

### 7.2 Auto-scoring on resolution

When an `outcomes` row is written with a `outcome_label` matching a forecast's outcome rows, the system:

1. Computes binary Brier in MVP for binary forecasts: `(forecast_probability_of_realized_outcome - 1.0)²`.
2. Writes a `forecast_score` event (an internal ledger event, not a node) with metric values.
3. Emits a `coach_signal` memory node if the score is a strong surprise (large Brier).

Multi-class Brier and ranked probability score land in P1.

### 7.3 Drift detection

Calibration drift is computed by:

1. Bucketing forecasts by `confidence_label` (low / medium / high) or numeric probability bucket (0.0-0.1, 0.1-0.2, …).
2. Computing realized resolution rate within each bucket over a rolling window.
3. Comparing to the bucket's expected rate (either the midpoint or the average forecast probability).
4. Flagging buckets where the z-score of the deviation exceeds threshold (configurable, default 2.0).

### 7.4 ForecastBench export

`journal.export --format forecastbench` emits forecasts + outcomes in ForecastBench-compatible JSON for benchmark submission or external scoring tools. Sensitive trade details (P&L, actual position sizes) are stripped.

## 8. Connector interface spec

See [`docs/architecture/connector-interface.md`](./docs/architecture/connector-interface.md) for the full spec. Summary:

```python
class Connector(Protocol):
    name: str
    venue_kind: str
    capabilities: ConnectorCapabilities

    def snapshot(self, instrument_ref: InstrumentRef) -> Snapshot: ...
    def resolve(self, instrument_ref: InstrumentRef) -> Outcome | None: ...
    def search(self, query: str, *, limit: int = 20) -> list[InstrumentRef]: ...
```

`ConnectorCapabilities` flags: `supports_resolution`, `supports_multi_outcome`, `supports_websocket`, `requires_api_key`, `read_only` (always true for MVP — no connector may execute trades).

Connectors are registered via the `trade_trace.connectors` entry point group in `pyproject.toml`. The core resolves connectors at startup by name; the venue table's `connector_name` column joins to the registry.

Manual snapshot / outcome entry via `snapshot.add` / `outcome.add` is always available and bypasses connectors entirely.

## 9. MCP tool catalog

Tools are grouped by namespace. All emit JSON, accept `--dry-run` (validation without write), and use `--idempotency-key` where writes may be retried.

### `journal.*`
- `journal.init` — initialize storage in the current directory or a configured path
- `journal.status` — schema version, storage location, counts of major entities
- `journal.schema` — return the JSON schema for a specified entity or tool
- `journal.export` — export as `jsonl`, `markdown`, or `forecastbench`
- `journal.import` — import CSV trades (P1)

### `venue.*`, `instrument.*`, `snapshot.*`, `source.*`
Standard CRUD-ish operations: `add`, `list`, `show`, with filtering by tag / venue / asset_class / date_range.

### `thesis.*`, `forecast.*`, `decision.*`
- `thesis.add`, `thesis.update` (creates new version)
- `forecast.add` (linked to a thesis)
- `decision.add`, `decision.list`, `decision.show`

### `position.*`
- `position.list`, `position.show`, `position.close` (records a final mark-and-close decision)

### `watch.*`
- `watch.list`, `watch.stale`, `watch.archive`, `watch.convert` (to skip / paper_enter / actual_enter)

### `review.*`
- `review.add`, `review.due`, `review.list`, `review.show`

### `memory.*`
- `memory.retain`, `memory.recall`, `memory.reflect`
- `memory.list_edges`, `memory.add_edge` (manual edge creation)

### `playbook.*`
- `playbook.create`, `playbook.list`, `playbook.show`
- `playbook.propose_version`, `playbook.list_versions`
- `playbook.adherence` (sugar over `report.playbook_adherence`)

### `report.*`
- `report.calibration`, `report.mistakes`, `report.strengths`
- `report.pnl`, `report.watchlist`, `report.decision_velocity`
- `report.unscored_forecasts`, `report.playbook_adherence`
- `report.coach` — synthesis primitive
- `report.weekly` — convenience preset that calls coach + a fixed set of reports

### `connector.*`
- `connector.list` — installed connectors and their capabilities
- `connector.snapshot` — pull a snapshot for a given instrument
- `connector.resolve` — pull outcome data
- `connector.search` — search a venue for instruments matching a query

Every MCP tool has a corresponding CLI command at `trade-trace <namespace> <verb>`. See `journal.schema` for the full machine-readable tool registry at runtime.

## 10. CLI surface

The CLI is a 1:1 mirror of the MCP tool catalog. Conventions:

```bash
trade-trace <namespace> <verb> [--positional <id>] [--flag value ...]
```

Common flags:
- `--json` — (default, kept for explicitness; identical to no flag)
- `--human` — emit human-readable prose to stderr; stdout remains JSON
- `--idempotency-key <key>` — natural-key dedup for write retries
- `--dry-run` — validate without writing
- `--note-file <path>` — supply long notes from a file
- `--tags <a,b,c>` — comma-separated tags
- `--metadata-json <json>` — structured metadata for venue-specific fields
- `--fields <a,b,c>` — limit returned JSON to specified fields (context-budget aware)
- `--page-all` — NDJSON stream of all results, one per line

Output contract:
- **stdout**: JSON only. Pretty-printed with `--human`, compact otherwise. Streams are NDJSON.
- **stderr**: empty by default. Used for `--human` prose and structured error logs.
- **exit codes**: 0 success, 1 generic error, 2 validation error, 3 not-found, 4 idempotency conflict, 5 connector error, 6 storage error.

Errors are always structured JSON to stdout (even in CLI), e.g.:

```json
{"error": {"code": "VALIDATION_ERROR", "message": "...", "field": "side", "expected": ["yes","no","long","short"]}}
```

## 11. Storage spec

- **Primary store**: SQLite database at `$TRADE_TRACE_HOME/trade-trace.sqlite` (default `~/.trade-trace/`).
- **Vector index**: `sqlite-vec` extension loaded at connection time; `embedding` columns on `memory_nodes`.
- **Full-text index**: SQLite FTS5 virtual table over `memory_nodes.title`, `memory_nodes.body`, and selected ledger text fields.
- **Audit log**: `$TRADE_TRACE_HOME/events.jsonl` — append-only, one JSON record per write. Format: `{"ts": "...", "op": "decision.add", "actor": "agent" | "cli" | "import", "payload": {...}}`.
- **Schema migrations**: versioned migration scripts under `trade_trace/migrations/`. `journal.status` reports schema version. Migrations preserve all data.
- **File permissions**: created with mode `0600` where the platform allows.
- **Configuration**: `$TRADE_TRACE_HOME/config.toml` controls embedding provider, default decay rates, drift z-score thresholds, log verbosity.

## 12. Output contract

Reiterating the principle: **JSON-only by default.** Every command, success or error, success or empty, returns valid JSON to stdout. No human prose is mixed in. The `--human` flag adds prose to stderr only, never to stdout.

Streams (`--page-all`, list operations on large result sets) use NDJSON — one JSON object per line, terminated by `\n`. Agents can stream-parse with `for line in stdout: obj = json.loads(line)`.

Schema introspection: `journal.schema` returns the full JSON schema of any entity, command argument set, or tool definition. The MCP server also exposes this through the standard MCP `tools/list` and `tools/get` calls; agents using MCP do not need to call `journal.schema` separately.

## 13. Safety, privacy, compliance

- **No execution.** No code path in MVP produces an order or signs anything. Connector code is firewalled from any execution capability at the protocol level.
- **No credentials.** Connectors that need API keys read them only from environment variables. Keys are never written to disk, never logged, never echoed.
- **Local-first.** No remote sync in MVP. Optional sync is a P2 feature gated behind explicit consent.
- **Export warnings.** Exports that include actual trade details emit a stderr warning and require `--confirm-actual-trades` to proceed.
- **Framing.** All analytics output is labeled as retrospective decision support, not as recommendation. Documentation never claims edge, profitability, or financial advice.
- **License**: MIT. Project ships with `NOTICE` listing third-party dependencies and their licenses.

## 14. Milestones

### M0 — Repo and package foundation
- `pyproject.toml`, MIT license, Python 3.11+
- Package skeleton: `trade_trace/{core,schemas,storage,connectors,cli,mcp,migrations}/`
- Pydantic v2 schemas for all ledger entities and memory nodes
- SQLite + sqlite-vec + FTS5 wired; migration framework
- README, VISION, PRD published

### M1 — Ledger core + CLI/MCP frames
- All ledger tables created via migration v1
- Core API methods: instrument, snapshot, thesis, decision, position, outcome, source, review
- CLI + MCP front-ends wired (fastmcp + typer), JSON-only output
- `journal.init`, `journal.status`, `journal.schema`, `journal.export jsonl`
- Manual workflow end-to-end: add instrument → add snapshot → add thesis → add forecast → add decision → add outcome → run a basic report

### M2 — Memory layer
- `memory_nodes` and `edges` tables
- Embedding provider abstraction; bundled bge-small default
- `memory.retain / recall / reflect` API and tool/command pairs
- Multi-strategy retrieval (semantic + BM25 + temporal + graph)
- Confidence/decay computation at recall time
- `memory.list_edges`, `memory.add_edge`

### M3 — Self-improvement loop
- Layer 1: primitive reports (`report.calibration`, `report.mistakes`, `report.strengths`, `report.pnl`, `report.watchlist`, `report.decision_velocity`, `report.playbook_adherence`, `report.unscored_forecasts`)
- Layer 2: `report.coach` synthesis
- Layer 3: reflection ergonomics + linked-memory traversal
- Layer 4: playbook + playbook_version + playbook_rule machinery; override detection; provenance

### M4 — Connectors
- Connector ABC + entry-point registry
- First-party: Polymarket (Gamma read-only), Manifold, yfinance
- `connector.snapshot / resolve / search` tools
- Manual fallback always available

### M5 — Calibration and reports polish
- Binary Brier scoring with `forecast_score` events
- Calibration drift detection + `coach_signal` emission
- ForecastBench-compatible export
- Tag taxonomy seed (~30 mistake tags, ~10 strength tags from VISION.md §16)

### P1 (post-MVP)
- CSV import (`journal.import csv`)
- Multi-class and ranked probability scoring
- Strategy/playbook reports that grade rules by outcome
- Performance metrics: win rate, expectancy, R-multiple, max favorable/adverse excursion, profit factor
- Read-only Polymarket WebSocket connector
- Additional connectors via plugins (Kalshi, Polygon, IBKR)

### P2 (later)
- Optional sync / backup
- Local web read-only viewer (still JSON-source-of-truth, generated HTML view)
- Replay / backtest hooks for connectors that support historical data
- Multi-agent collaboration patterns (multiple agents writing to the same journal with attribution)

## 15. Testing & verification

### CLI / MCP front-end tests
- `journal.init` is idempotent
- Every tool has a JSON schema retrievable via `journal.schema`
- Every write tool supports `--dry-run` and `--idempotency-key`
- Error responses use stable codes from the documented enum
- CLI and MCP emit byte-identical JSON for equivalent inputs

### Storage tests
- Schema migrations preserve all data on upgrade and downgrade where reversible
- Append-only invariants hold for snapshots, theses, decisions, position_events, outcomes, reviews, memory_nodes, edges
- sqlite-vec and FTS5 are operational after fresh init

### Memory layer tests
- Embeddings are computed and stored for every memory_node write
- Recall returns nodes ordered by combined score across enabled strategies
- Confidence decay matches the documented formula for synthetic age inputs
- Edge traversal honors depth limits and edge-type filters

### Self-improvement loop tests
- Auto-scoring fires on outcome resolution and produces correct Brier values for binary forecasts
- Calibration drift z-scores match a reference numpy implementation
- Playbook override detection correctly flags decisions that violate active rules
- `report.coach` synthesizes from a fixture without calling any LLM

### Connector tests
- Polymarket Gamma read-only snapshot for a known market
- Manifold public snapshot for a known market
- yfinance snapshot for a known equity
- Manual entry path produces identical ledger state to connector-provided entry

### End-to-end dogfood test
- LLM agent (Claude/GPT) is given MCP access to the journal
- It records 20 decisions across at least two asset classes
- It runs `report.coach`, writes reflections, proposes a playbook rule update
- The next session of decisions shows the updated playbook is in force and overrides are tracked

## 16. Definition of done (MVP, learning-gated)

The MVP is done when, after 30 days of continuous dogfooding by an LLM agent:

1. The agent has recorded **at least 30 decisions** across **at least two asset classes** (one of which is binary prediction markets, for calibration testing).
2. At least **5 forecasts have resolved** and been auto-scored with binary Brier; calibration buckets have non-trivial sample size.
3. `report.coach` surfaces **at least one miscalibrated bucket** the agent did not already know about (verified by asking the agent before and after).
4. The agent has written **at least 10 reflections** linked to ledger rows and other memory nodes; `memory.recall` reliably surfaces relevant past reflections when forming a new thesis.
5. **At least one playbook rule has been updated** via `playbook.propose_version`, with provenance traceable to a stored reflection; override tracking is active and reports show at least one rule whose override outcomes are negative.
6. The system has executed **zero trades**.
7. Exports (`journal.export jsonl` and `journal.export forecastbench`) produce valid output that round-trips through import (where supported) without data loss.

The validation question, restated:

> Does Trade Trace make the LLM trader auditable, calibratable, and improvable over time?

## 17. Remaining open questions

These are deferred to implementation planning or future iterations:

1. **MCP server transport**: stdio (default for local Claude Code / Cursor integration) only, or also HTTP/SSE for remote hosts? Stdio in MVP; HTTP in P1.
2. **Embedding migration**: if the user changes the embedding model in config, do we re-embed all existing memory nodes lazily, eagerly, or never? Probably lazily with a `memory.reembed` command in P1.
3. **Tag governance**: tags are free-form for now but a system playbook of "canonical mistake tags" is shipped. Should we lint or normalize agent-provided tags? Probably not — let usage data inform later.
4. **Reflection LLM model**: agents bring their own LLM; the system never calls an LLM directly. But should `report.coach` optionally call an LLM to summarize the structured packet in prose? Probably no — the prose belongs to the agent, not the system.
5. **Multi-agent attribution**: when multiple agents write to the same journal, do we track `actor_id` on every row? Probably yes, even in MVP — a simple `actor` column on writes is cheap insurance.
6. **Connector authentication boundary**: how do we prevent a third-party connector from doing unintended things? Sandboxing is hard in Python. Best we can do for MVP: connector capability flags + connectors live in known plugin packages + we document the security model and refuse to load unknown connectors without explicit config opt-in.
7. **Concurrency**: SQLite WAL mode + a single writer assumption is fine for MVP. Multi-process concurrency from multiple agents on the same machine is a P1 concern.
