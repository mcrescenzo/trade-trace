# Trade Trace — Product Requirements Document

**Date:** 2026-05-18
**Status:** Clean planning draft
**Companion docs:** [`VISION.md`](../VISION.md), [`product-scope-v002.md`](./architecture/product-scope-v002.md), [`docs/architecture/memory-layer.md`](./architecture/memory-layer.md), [`docs/architecture/scoring.md`](./architecture/scoring.md), [`docs/architecture/persistence.md`](./architecture/persistence.md), [`docs/architecture/contracts.md`](./architecture/contracts.md), [`docs/architecture/current-exposure-agent-contract.md`](./architecture/current-exposure-agent-contract.md), [`docs/architecture/market-scan-contract.md`](./architecture/market-scan-contract.md), [`docs/architecture/operability.md`](./architecture/operability.md), [`docs/architecture/reports.md`](./architecture/reports.md), [`docs/architecture/imports.md`](./architecture/imports.md), [`docs/architecture/risk-units.md`](./architecture/risk-units.md), [`docs/architecture/opportunity-analysis.md`](./architecture/opportunity-analysis.md), [`docs/architecture/dogfood-protocol.md`](./architecture/dogfood-protocol.md)

Trade Trace is a local, open-source, AI-only journal, memory, and calibration substrate for LLM trading agents. It records decisions, resolves outcomes, scores supported forecasts, stores reflections, evolves playbooks, and recalls prior learning. It never executes trades, never queries external venues for market data, and never handles execution credentials. The former human-facing Console UI has been hard-removed; supported product surfaces are the MCP server, CLI, and Python/library reporting APIs.

## 1. MVP scope

The MVP proves the full four-layer learning loop with narrow breadth: a complete learning-loop slice, not the entire broad product. Breadth is deferred.

MVP vertical slice:

1. `journal.init`
2. Structured manual ingestion of instruments, snapshots, theses, binary forecasts, and decisions
3. Optional grouping of decisions, theses, and reviews under named strategies for scoped reports, recall, and reflection (see §2.12 and §4.6)
4. Structured manual outcome entry with a typed resolution status
5. Binary Brier scoring (see [`scoring.md`](./architecture/scoring.md))
6. Deterministic reports and `report.coach`
7. Agent-written reflection
8. Playbook version update with normalized adherence tracking (considered, followed, overridden, not_applicable)
9. Token-budgeted recall of prior observations, reflections, and playbook rules in the next decision
10. Source/evidence capture attached to theses, decisions, and forecasts

The post-MVP pre-release track has since landed stdio MCP, tool-schema introspection, optional local ONNX embeddings/model import/reindex surfaces, JSONL/CSV import implementations, comparison/review-bundle/risk/opportunity reports, and — in the P1 scoring upgrade — categorical and normalized scalar auto-scoring (see [`scoring.md`](./architecture/scoring.md)). Still deferred or unsupported in v0.0.2: remote/API embeddings, keyring-backed embedding credentials, the `forecasts.distribution_json` scalar/distribution schema, exact ForecastBench submission compatibility, sync, HTTP/SSE transport, and websockets.

Trade Trace does not fetch trading data, broker data, market prices, or outcomes from external services by default. The agent supplies market data through structured ingestion APIs, except for the explicitly opt-in Polymarket adapter path documented for v0.0.2. Semantic embeddings use pre-staged local model assets and never send journal text outward.

## 2. Locked product decisions

### 2.1 Memory layer

The memory layer is built in-house, modeled on Retain / Recall / Reflect but trading-specific. Memory nodes link to ledger rows, carry confidence/decay metadata, and can participate in typed graph recall. No external memory framework is a runtime dependency. See [`memory-layer.md`](./architecture/memory-layer.md).

### 2.2 State model

The SQLite database is the source of truth. It separates immutable event/source tables from mutable or rebuildable projections. See [`persistence.md`](./architecture/persistence.md) for the full event/outbox/idempotency contract.

- `position_events` are source of truth; `positions` is a projection derived from them.
- `memory_nodes` are immutable; recall telemetry belongs in `memory_node_stats` or recall events/projections, not on the node row.
- Corrections create new rows/events, not silent mutation.
- JSONL export/audit is derived from committed DB events via the outbox table. It is not a second source of truth and must not require fragile dual writes.

### 2.3 CLI and MCP parity

One internal core API backs both MCP and CLI. Tool schemas, validation semantics, result meaning, and error codes must be equivalent after transport normalization. JSON byte identity is not required because MCP framing, streaming, and transport metadata differ from CLI stdout/NDJSON. See [`contracts.md`](./architecture/contracts.md) for the envelope and error code list.

### 2.4 No trading-data fetching

Trade Trace never queries external venues, broker APIs, or market data providers, and never fetches trading data, broker data, market prices, order books, or outcomes on the agent's behalf. The agent calling Trade Trace already has the data — it is the one currently analyzing the market — and supplies it through structured ingestion APIs. This boundary keeps the product small, market-agnostic, secure by construction, and free of third-party rate limits, version drift, and trust assumptions.

The `snapshots.source` and `outcomes.source` columns are free-form strings. MVP only writes `'manual'`. The columns exist so future imports (CSV, JSONL, dogfooded research scripts) have a place to land without migration; no connector type taxonomy is implied or reserved.

#### 2.4.1 Explicit opt-in outbound-network paths

Trade Trace makes no outbound network calls by default. The v0.0.2 outbound surface is intentionally narrow:

- **Polymarket adapter** — disabled by default and configured explicitly. Adapter calls are agent-triggered; there is no background fetch daemon, scheduler, default RPC URL, or committed credential. Security policy requires endpoint allowlisting, TLS verification, scrubbed error/log output, and no request/response body logging.
- **Local semantic embeddings** — no outbound network path. Operators may install `[embeddings]`, pre-stage the pinned BGE-small assets, import them with `tt model import --path <dir> --confirm`, and set `embeddings.provider=local`. `journal.config_set` does not download model files.

Remote/API embedding providers are unsupported in v0.0.2. There is no telemetry, usage analytics, auto-update, webhook, broker integration, or trade execution.

### 2.5 Forecast model

The initial MVP shipped binary scoring; categorical and normalized scalar auto-scoring were added in the P1 scoring upgrade (see [`scoring.md`](./architecture/scoring.md) for the full shipped scorer matrix). See [`scoring.md`](./architecture/scoring.md) for invariants, the exact Brier formula (single-probability form), the resolution status enum, and the lifecycle of a forecast row.

- Binary prediction markets: score directly against resolved YES/NO outcome.
- Equity/crypto directional forecasts: may be expressed as binary derived events, e.g. `AAPL closes above 200 at horizon` or `BTC return > 0 by horizon`.
- Scalar, options, futures, numeric, and multi-outcome forecasts may be stored as record-only data with `scoring_support = 'unsupported'` until P1.
- Multi-class/categorical and normalized scalar scoring shipped in the P1 scoring upgrade (see [`scoring.md`](./architecture/scoring.md)). The `forecasts.distribution_json` scalar/distribution schema field remains a deferred follow-up; it is not an MVP schema field.

The `forecasts` table splits status into two columns: `scoring_support` (capability) and `scoring_state` (lifecycle). Auto-scoring only fires when the linked `outcomes` row has `status = 'resolved_final'`.

### 2.6 Playbooks

MVP playbook rules are advisory. The agent records which rules it considered, followed, overrode, or judged not_applicable in a normalized `decision_playbook_rules` table (§3.1), not in a JSON blob. Automatic violation detection is only implemented for future rules whose predicates are explicitly machine-checkable. MVP must not promise a general automatic rule engine.

Playbooks codify rules; strategies (§2.12) group decisions by edge thesis. The two are orthogonal: a decision independently references a playbook version and (optionally) a strategy. A reflection can promote into either — a new rule (playbook version) or a refined strategy hypothesis. Adherence reports may be sliced by `(strategy × playbook)` once both filters are wired up (M4).

### 2.7 Coach signals

Here `signals` means local process notifications written by deterministic
tools (for example stale watches or unscored forecasts), not trading signals.
They are retrospective/process context only and must not be interpreted as
advice, alpha, profitability evidence, or instructions to trade.

No background scheduler or daemon exists in MVP. Write-triggered signals may be persisted during ordinary writes. Time-passing signals, such as stale watches and unscored forecasts, are generated lazily by `report.coach`, `report.watchlist`, `report.unscored_forecasts`, or an explicit maintenance scan. External scheduling is out of scope.

### 2.8 Credentials and security

The core never accepts, stores, logs, or prompts for trading credentials. Wallet, broker, order-signing, and seed credentials are never supported, never read from any source, and never appear in any API surface. Because the only v0.0.2 network path is the explicitly configured Polymarket adapter (§2.4), there is no execution path, no broker trust model, and no default market-data network surface in MVP.

The optional local embeddings path (§2.4.1) is off by default, local-only, and carries no trading data. v0.0.2 does not support remote/API embedding providers or keyring-backed embedding credentials; `embeddings.provider` is limited to `none|local`.

### 2.9 Tags

Tags are stored relationally, e.g. `decision_tags(decision_id, tag)` and `review_tags(review_id, tag, tag_kind)`, because SQLite has no native array column type. APIs may expose arrays for convenience.

Tags are free-form sub-classifiers and coexist with a row's optional `strategy_id`. Tags never substitute for a strategy: strategies are first-class entities (§2.12) with their own table, tools, edges, and report filters, while tags remain unstructured string labels that may further partition rows within a strategy (e.g., a decision in the `earnings-momentum` strategy may also carry tags `liquidity-ignored`, `good-skip`).

### 2.10 Edges

Generic edges require endpoint validation against allowed endpoint kinds and existing IDs. Edge endpoint kinds include memory nodes and ledger rows including instruments and venues. Do not use `contradicts` for administrative edge deletion. Edges are append-only; correction is by `supersedes`. Administrative deletion (`retracts`/`tombstones`) is deferred until a concrete need arises — see [`memory-layer.md`](./architecture/memory-layer.md) §5.

Strategies are first-class edge endpoints (added to the kind enum in §3.2). Reflections can target a strategy directly via an `about` edge, and `memory.recall` accepts a strategy as context.

Period- or tag-scoped reflections remain valid, but periods and tags are not MVP edge endpoints. Their scope is stored in reflection `meta_json` unless later versions add first-class period/tag entities.

### 2.11 External claims

- yfinance, Polymarket Gamma, and similar external APIs are explicitly out of scope; see §2.4.
- Local semantic embeddings are optional and use a pre-staged local ONNX/tokenizers path. The base install uses FTS5 + graph + temporal retrieval; vector recall is off by default and fail-soft (§2.4.1).
- No embedding model is downloaded by configuration. Operators who want local embeddings install the `[embeddings]` extra and use `tt model import` against a verified, pre-staged model directory. Remote/API embedding providers, `sqlite-vec` indexes, and keyring-backed embedding credentials are not supported in v0.0.2.
- ForecastBench export is ForecastBench-inspired/TBD until the current external schema is verified; see [`forecastbench-compatibility.md`](./architecture/forecastbench-compatibility.md).
- No claim is made that LLMs have reached forecasting parity with human superforecasters.

### 2.12 Strategies

Strategies are named, persistent entities that group decisions, theses, and reviews under one edge thesis (e.g., `earnings-momentum`, `pairs-trade-XYZ`, `thin-liquidity-prediction-markets`). They let the loop run not just per-decision but per-strategy: scoped reports, scoped recall, and reflections that target a strategy as a whole.

**Locked decisions:**

- **First-class entity.** A `strategies` table (§3.1) holds the row; `decisions`, `theses`, and `reviews` carry an optional `strategy_id` FK. A `strategy` edge endpoint kind (§3.2) lets reflections and memory nodes link to a strategy directly.
- **Orthogonal to playbooks and tags.** Playbooks (§2.6) codify rules; tags (§2.9) sub-classify within a row. Strategies group rows by edge thesis. Each axis is independent. A decision can have any combination of `strategy_id`, `playbook_version_id`, and tags.
- **Single-strategy at MVP.** One `strategy_id` per decision, thesis, or review (nullable). Pairs trades and basket strategies use one composite strategy row at MVP; a many-to-many `decision_strategies` join table is deferred (§11).
- **Mutable rows, append-only audit.** Strategy `description`, `hypothesis`, and `status` are mutable. Every change emits a `strategy.updated` event in the `events` log so historical state is recoverable. Versioning into a `strategy_versions` table is deferred until point-in-time hypothesis queries become load-bearing (§11).
- **Soft-archive only.** `status` is one of `active` or `archived`. There is no delete and no `draft`; strategies are created `active`, archived once retired, and remain valid FK targets for historical rows forever.
- **Tools take `strategy_id`.** The canonical reference in tool schemas is the opaque `id`. Tools that accept a strategy MAY also accept a `strategy_slug` input alias resolved server-side; the result envelope always echoes `strategy_id`.
- **Filter semantics for reports** (referenced from §4.2, §4.3, §4.6): a tool's `strategy_id` parameter, when omitted or `null`, applies **no filter** — rows with and without a strategy are both included. To select only rows with no strategy, callers pass the sentinel string `"__none__"`. This convention is canonical here; report tools do not redefine it.

Strategies are not introduced as a runtime requirement: the column is nullable at every stage, pre-strategy data is silently included by every report, and an agent that never calls `strategy.create` sees the same MVP it would have seen without this section.

All write APIs include common metadata from MVP:

- `id` — server-generated unless the tool documents an explicit override.
- `created_at` — UTC ISO 8601 timestamp; mandatory UTC (see [`operability.md`](./architecture/operability.md) §2.1).
- `actor_id` or `actor` — string with grammar `<role>:<name>` where `<role>` is one of `agent`, `cli`, `import`, `system` and `<name>` is `[a-z0-9][a-z0-9._-]{0,63}`. Examples: `agent:default`, `cli:user`, `import:polymarket-csv-2026-05`. Used in idempotency scope.
- `idempotency_key` — **required by default** for retryable writes (creation tools). The MCP and CLI surfaces both refuse retryable writes without a key unless the caller passes the explicit `--allow-no-idempotency` flag (CLI) or `_allow_no_idempotency: true` argument (MCP). Uniqueness scope and conflict behavior in [`persistence.md`](./architecture/persistence.md) §5. Read tools, list tools, and admin tools do not require a key. Grammar: `[A-Za-z0-9._:-]{1,128}`; server compares post-trim, case-sensitive.
- `agent_id` — optional logical trading-agent identifier (e.g. `agent:polymarket-scout`). Distinct from `actor_id`: `actor_id` is who initiated the write; `agent_id` is which logical agent the work belongs to. Reporting dimension only.
- `model_id` — optional model/model-family identifier (e.g. `claude-opus-4-7`). Reporting dimension only.
- `environment` — optional enum: `paper`, `actual_recorded`, `simulation`, `backtest_import`, `manual_review`. Reporting dimension only; defaults unset.
- `run_id` — optional agent run/session identifier. Reporting dimension only.
- `metadata_json` — venue/tool-specific extension. The escape hatch for everything not modeled as a first-class column. Account/portfolio bucket labels (if used) belong here until dogfood proves a need to promote them to a first-class column.

The four segmentation fields (`agent_id`, `model_id`, `environment`, `run_id`) ship as optional columns on `theses`, `forecasts`, `decisions`, `snapshots`, `sources`, `outcomes`, `events`, `memory_nodes`, and `memory_recall_events`. None are required at the schema level; any unset value defaults to `NULL`. Reports may group or filter by them where the report documents support. They never imply credentials, broker accounts, or execution.

### 3.1 Core ledger/source tables

#### `venues`
- `id`, `name`, `kind`, `metadata_json`, `created_at`, `actor_id`
- `kind` enum: `exchange`, `broker`, `prediction_market`, `dex`, `otc`, `manual`. `manual` is the default for agent-supplied rows that have no real venue (paper trading, hypotheticals).

#### `instruments`
- `id`, `venue_id`, `external_id`, `symbol`, `title`, `asset_class`, `currency_or_collateral`
- `expiration_or_resolution_at`, `resolution_criteria_text`, `contract_multiplier`, `metadata_json`, `created_at`, `actor_id`
- `asset_class` enum: `equity`, `option`, `future`, `crypto_spot`, `crypto_perp`, `prediction_market`, `event_market`, `fx`, `commodity`, `other`. `other` exists as the explicit fallback so the schema never forces an inaccurate classification; venue/contract specifics live in `metadata_json`.

#### `snapshots`
- `id`, `instrument_id`, `captured_at`, `source`, `source_url`
- `price`, `bid`, `ask`, `mid`, `spread`, `volume`, `open_interest`, `implied_probability`, `liquidity_depth_json`
- `metadata_json`, `created_at`, `actor_id`
- Segmentation: `agent_id`, `model_id`, `environment`, `run_id` (all nullable).
- Immutable; corrections create new snapshots.
- `source` is a free-form string; MVP only writes `'manual'`.

#### `theses`
- `id`, `instrument_id`, `version`, `parent_thesis_id`, `side`, `time_horizon_at`, `confidence_label`
- `body`, `falsification_criteria`, `exit_triggers`, `risk_notes`, `created_at`, `actor_id`
- `valid_from` (default `created_at`), `valid_to` (nullable; default `time_horizon_at` if set, else `NULL`), `invalidated_at` (nullable), `invalidated_by` (nullable FK to a superseding `theses.id` or `outcomes.id`) — bi-temporal fields per [`operability.md`](./architecture/operability.md) §2.
- `strategy_id` (nullable FK to `strategies.id`; optional grouping per §2.12). Column reserved in M1; the `strategies` table itself ships in M3.
- Segmentation: `agent_id`, `model_id`, `environment`, `run_id` (all nullable; see §2 common metadata).
- `side` enum: `long`, `short`, `yes`, `no`, `flat_neutral`, `pairs_long_short`. `yes`/`no` are the standard prediction-market direction; `long`/`short` are directional positions in any non-prediction market; `flat_neutral` is the explicit "no directional view" stance (relevant for theses that say "spread compression" or "volatility expansion" without picking a side); `pairs_long_short` covers composite strategies.
- `confidence_label` enum: `very_low`, `low`, `medium`, `high`, `very_high`. Coarse human-readable label; the underlying probability lives on the linked `forecasts` row, not here.
- Versioned; updates create new rows. New rows reference the prior version via `parent_thesis_id` and may emit a `supersedes` edge for explicit invalidation.

#### `forecasts`
- `id`, `thesis_id`, `kind` (`binary`, `categorical`, `scalar`), `resolution_at`, `yes_label`, `resolution_rule_text`
- Transitional PM-native columns added in the v0.0.2 schema phase: `market_id`, `probability`, `rationale_body`, `falsification_criteria`, `updated_rationale_at`, `updated_rationale_by`. These are nullable during the additive transition so old journals remain readable.
- `scoring_support` (`supported`, `unsupported`) — capability: can this `kind` be scored by the installed scorer?
- `scoring_state` (`pending`, `scored`, `failed`, `superseded`) — lifecycle: what has happened to this forecast?
- `created_at`, `actor_id`
- `valid_from` (default `created_at`), `valid_to` (default `resolution_at`), `invalidated_at` (nullable), `invalidated_by` (nullable; FK to a superseding forecast or to the outcome that resolved it). Bi-temporal fields per [`operability.md`](./architecture/operability.md) §2.
- Segmentation: `agent_id`, `model_id`, `environment`, `run_id` (all nullable).
- `yes_label` is set at create time only and is **immutable**. If omitted at create time, scoring applies the heuristic in [`scoring.md`](./architecture/scoring.md) §3.2 on resolution. If the heuristic fails, the forecast is scored as `failed` with `details.reason = "yes_label_ambiguous"`; the caller's recovery path is to issue `forecast.supersede` writing a new forecast row with an explicit `yes_label`. There is no `forecast.set_yes_label` tool; the append-only invariant on `forecasts` is strict.
- `resolution_rule_text` is a free-text statement of the rule that determines YES/NO at resolution, recorded at forecast creation. Reduces hindsight ambiguity in calibration replay; explicitly carrying the rule lets later analysis distinguish "forecast was wrong" from "resolution rule was ambiguous."
- Binary PM readers should prefer canonical `forecasts.probability` and `forecasts.market_id` when present, with guarded fallback to `forecast_outcomes` and thesis/instrument joins for legacy rows. Non-binary scoring remains on the legacy outcome-row representation until a later cleanup.

#### `forecast_outcomes`
- `id`, `forecast_id`, `outcome_label`, `probability`, `lower_bound`, `upper_bound`
- Transitional compatibility table. One row per forecast outcome remains written/read for legacy journals and non-binary forecasts. **Unique on `(forecast_id, outcome_label)`** with case-insensitive label comparison (server lower-cases on write). Binary forecasts have exactly two rows whose `probability` values sum to 1.0 within `1e-6` tolerance. Row ordering is not semantically significant; consumers must identify YES via `forecasts.yes_label` or the heuristic in `scoring.md` §3.2, not via row position. PM-native binary reports/scorers prefer `forecasts.probability` when present.

#### `forecast_scores`
- `id`, `forecast_id`, `outcome_id`, `metric` (`brier_binary` in MVP), `score`, `scored_at`, `actor_id`, `metadata_json`
- Immutable score event table. `score = NULL` with `metadata_json.failure_reason` on `scoring_state = 'failed'`.

#### `decisions`
- `id`, `instrument_id`, `thesis_id`, `forecast_id`, `snapshot_id`
- `type` enum (13 values): `watch`, `skip`, `paper_enter`, `paper_exit`, `actual_enter`, `actual_exit`, `add`, `reduce`, `hold`, `invalidate_thesis`, `update_thesis`, `resolved`, `review`
- `side`, `quantity`, `price`, `fees`, `slippage`, `reason`
- `playbook_version_id`, `review_by`, `created_at`, `actor_id`
- `strategy_id` (nullable FK to `strategies.id`; optional grouping per §2.12). Column reserved in M1; the `strategies` table itself ships in M3. Independent of `playbook_version_id`: a decision may carry any combination of strategy, playbook, and tags.
- Segmentation: `agent_id`, `model_id`, `environment`, `run_id` (all nullable).
- `side` enum (same set as `theses.side`): `long`, `short`, `yes`, `no`, `flat_neutral`, `pairs_long_short`.
- Tags live in `decision_tags`; playbook rule adherence lives in `decision_playbook_rules`.
- `paper_enter` automatically creates and links one `position_events` row (`event_type = 'open'`) and refreshes the `positions` projection in the same successful write, so `report.pnl` and open-position views can see the paper position immediately. The signed `quantity_delta` is positive for `yes`/`long` and negative for `no`/`short`.
- `paper_exit` is validated and stored as a decision, but close/reduce projection semantics are not inferred automatically yet.
- The `actual_enter`, `actual_exit`, `add`, and `reduce` decision types are **journal records only**. They record trades the agent placed elsewhere; they never trigger orders, writes to external systems, automatic `position_events`, or any execution path inside Trade Trace.
- Agent-facing current-exposure semantics are pinned in [`current-exposure-agent-contract.md`](./architecture/current-exposure-agent-contract.md): `positions`/`position_events` are canonical for current exposure, decisions are activity/audit trail, `watch` decisions are not positions, and actual-recorded decisions are record-only unless a linked position projection/event exists.

**Required-field matrix by decision `type`** (R = required, O = optional, X = forbidden):

| `type` | `instrument_id` | `thesis_id` | `side` | `quantity` | `price` | `fees` | `slippage` | `reason` | `review_by` |
|---|---|---|---|---|---|---|---|---|---|
| `watch` | R | O | O | X | X | X | X | O | O |
| `skip` | R | O | O | X | X | X | X | R | X |
| `paper_enter` | R | R | R | R | R | O | O | O | X |
| `paper_exit` | R | O | R | R | R | O | O | O | X |
| `actual_enter` | R | R | R | R | R | O | O | O | X |
| `actual_exit` | R | O | R | R | R | O | O | O | X |
| `add` | R | O | R | R | R | O | O | O | X |
| `reduce` | R | O | R | R | R | O | O | O | X |
| `hold` | R | O | O | X | X | X | X | O | O |
| `invalidate_thesis` | R | R | X | X | X | X | X | R | X |
| `update_thesis` | R | R | X | X | X | X | X | O | X |
| `resolved` | R | O | X | X | X | X | X | O | X |
| `review` | R | O | X | X | X | X | X | O | R |

Forbidden-but-supplied fields raise `VALIDATION_ERROR` with `details.field` set. The matrix is enforced at write time, not at projection time.

Per bead trade-trace-gbtj, `watch` accepts an optional `review_by` (matrix `O`) so a watch can carry a first-class deferred-review deadline. `hold` also accepts optional `review_by` so material defer-like hold records can carry a first-class checkpoint without changing decision type. `report.watchlist` surfaces the deadline plus a per-row `overdue` flag (`review_by <= as_of`) and a summary `overdue_count`. Age-based `mode='stale'` filtering remains independent so age-only callers are unchanged.

Material non-actions are explicit learning cases over existing `decisions`, not a new table or enum. Callers mark one by setting `metadata_json.material_non_action = {"category": <category>, "materiality_reason": <reason>}` and still choosing an existing `decision.type`. Categories are `watch`, `skip`, `hold`, `defer`, `review`, `thesis_update`, and `thesis_invalidated`; `defer` is encoded as `type=watch|hold|review` plus `category=defer` and requires `review_by`. Allowed materiality reasons are exposed in `tool.schema` as `x-material-non-action-taxonomy` and include `candidate_rejected`, `liquidity`, `source_stale`, `insufficient_edge`, `risk_limit`, `playbook_block`, `already_exposed`, `forecast_ambiguous`, `waiting_for_resolution`, `thesis_changed`, `thesis_invalidated`, `review_obligation`, `scanner_selected`, and `source_gap`. When material metadata is present, `reason` is required and the category must be compatible with the decision type. Ordinary absence of action remains no row/no marker; reports must not infer material learning cases from silence. `report.watchlist` includes `material_non_action_count` plus per-row material category/reason so material watches/defers can be distinguished from ordinary watch records.

#### `decision_tags`
- `decision_id`, `tag`
- Primary key: `(decision_id, tag)`. Tags are server-normalized to lowercase, leading/trailing whitespace stripped, max length 64.

#### `decision_playbook_rules`
- `id`, `decision_id`, `playbook_version_id`, `rule_node_id`
- `status` (`considered`, `followed`, `overridden`, `not_applicable`)
- `reason`, `created_at`, `actor_id`
- Normalized adherence tracking. One row per (decision, rule) pair the agent evaluated. Supports `report.playbook_adherence` directly without JSON parsing. `rule_node_id` is an FK into `memory_nodes` where `node_type = 'playbook_rule'`.

#### `position_events`
- `id`, `position_id`, `instrument_id`, `decision_id`, `event_type`, `quantity_delta`, `price`, `fees`, `slippage`, `created_at`, `actor_id`
- Source of truth for position history.
- `event_type` enum: `open`, `add`, `reduce`, `close`, `mark`, `expire`, `assigned`, `corrected`. `open` initializes a position; `add`/`reduce` change size; `close` zeros the position; `mark` records a mark-to-market revaluation without a trade; `expire`/`assigned` cover option-style terminations; `corrected` is a post-hoc adjustment that must reference a prior `position_events.id` in `metadata_json.corrects`.

#### `positions`
- `id`, `instrument_id`, `kind`, `side`, `status`, `opened_at`, `closed_at`, `resolved_at`, `realized_pnl`, `unrealized_pnl`, `avg_entry_price`, `updated_at`
- Rebuildable projection from `position_events` and marks.
- `kind` enum: `paper`, `actual`, `simulation`. Mirrors the source `decisions.type` family.
- `side` enum: `long`, `short`, `yes`, `no`, `pairs_long_short`. (Excludes `flat_neutral` — a flat position is not a position.)
- `status` enum: `open`, `partial`, `closed`, `resolved`, `expired`, `assigned`, `voided`. Lifecycle is `open` → `partial` (after a `reduce` that does not zero size) → `closed` (final reduce to zero) or `resolved`/`expired`/`assigned`/`voided` (terminal states driven by the linked instrument's resolution).

#### `outcomes`
- `id`, `instrument_id`, `resolved_at`, `outcome_label`, `outcome_value`
- `status` (`resolved_final`, `resolved_provisional`, `ambiguous`, `disputed`, `void`, `cancelled`) — see [`scoring.md`](./architecture/scoring.md) §5.
- `source`, `confidence`, `metadata_json`, `created_at`, `actor_id`
- Segmentation: `agent_id`, `model_id`, `environment`, `run_id` (all nullable).
- `outcome_value` is a `REAL` column. For binary outcomes, it carries `0.0` or `1.0` matching the realized indicator. For scalar outcomes it carries the realized scalar. For categorical outcomes it is `NULL` and the categorical winner is identified by `outcome_label` only.
- Append-only. **Corrections produce a new `outcomes` row connected to the prior row via a `supersedes` edge** (`source_kind = 'outcome'`, `source_id = <new>`, `target_kind = 'outcome'`, `target_id = <old>`, `edge_type = 'supersedes'`). There is no `parent_outcome_id` column; the supersedes edge is the canonical mechanism. Older rows remain readable for audit. Auto-scoring fires only on `status = 'resolved_final'` rows that are not themselves superseded.

#### `sources`
- `id`, `kind`, `ref`, `title`, `note`, `stance` (`supports`, `contradicts`, `neutral`), `freshness_at`, `content_hash`, `captured_at`, `created_at`, `actor_id`
- Provenance fields: `uri`, `media_type`, `storage_kind`, `retrieved_at`, `source_author`, `publisher`, `excerpt`, `extracted_text`, `summary`, `hash_algorithm`, `redaction_status`, `license_or_terms_note`.
- Segmentation: `agent_id`, `model_id`, `environment`, `run_id` (all nullable).
- `kind` enum: `url`, `pdf`, `image`, `tweet`, `news_article`, `research_doc`, `transcript`, `chart_image`, `note`, `other`.
- `stance` enum: `supports`, `contradicts`, `neutral`. The stance produces the corresponding edge type (`supports`, `contradicts`, or `about`) when the source is attached via §4.5.
- `storage_kind` enum: `url`, `local_path`, `inline_text`, `external_ref`. Note: Trade Trace **never fetches a `url` or reads a `local_path` automatically**. URLs and paths are stored as metadata only. Inline text is the canonical local-content path. `external_ref` covers opaque references the agent will resolve elsewhere. Content-addressed blob storage is explicitly deferred (P2+).
- `hash_algorithm` enum: `sha256`, `sha512`, `blake3`, `none`. Required when `content_hash` is populated.
- `redaction_status` enum: `none`, `redacted`, `sensitive`. `sensitive` flags content that should never appear in shared review bundles (see [`reports.md`](./architecture/reports.md) §5).
- Attached to theses, decisions, forecasts, and memory nodes through edges. During the additive PM-source transition, attaching a source to forecasts, decisions, or memory nodes also projects a compact copy into the target row's `metadata_json.sources` array with shape `{kind, title, url, stance, captured_at, hash}` when available; source-quality readers understand both direct/edge-backed and inline provenance. There is no `source_attachments` table.

#### `reviews`
- `id`, `target_kind`, `target_id`, `classification`, `body`, `next_rule_suggestion`, `created_at`, `actor_id`
- `strategy_id` (nullable FK to `strategies.id`; optional grouping per §2.12). Column reserved in M1; the `strategies` table itself ships in M3.
- `target_kind` enum: `decision`, `position`, `thesis`, `forecast`, `instrument`, `strategy`, `period`, `tag`. `period` and `tag` are non-row-backed scopes; their identifying detail lives in `metadata_json` (e.g. `metadata_json.period = {start, end}` or `metadata_json.tag = "liquidity-ignored"`).
- `classification` enum: `mistake`, `strength`, `neutral`, `process_error`, `process_success`, `mixed`. The four-axis breakdown (`process_error`, `process_success`, `mistake`, `strength`) makes process-vs-outcome scoring (product-scope-v002.md principle 3) explicit. `mixed` covers reviews where good and bad coexist; `neutral` is for observations with no value judgement.
- Tags live in `review_tags`.

#### `review_tags`
- `review_id`, `tag`, `tag_kind` (`mistake`, `strength`, `neutral`)
- Primary key: `(review_id, tag, tag_kind)`.

#### `strategies`
- `id`, `name`, `slug` (unique, lowercase-kebab), `description`, `hypothesis`
- `status` (`active`, `archived`), `created_at`, `updated_at`, `actor_id`
- Mutable rows on `description`, `hypothesis`, and `status`. Every change writes a `strategy.updated` event in the `events` log so historical state is recoverable without a separate version table.
- Soft-archive only; rows are never deleted. Archived strategies remain valid FK targets for historical decisions, theses, and reviews.
- Slug uniqueness is enforced at the storage layer per Trade Trace database instance (one `$TRADE_TRACE_HOME/trade-trace.sqlite` = one slug namespace; cross-database slug collisions are not detected or relevant). Duplicate slugs on `strategy.create` surface as `VALIDATION_ERROR` (§6).
- Ships in M3 alongside the memory layer (§8); the nullable `strategy_id` FK columns on `decisions`, `theses`, and `reviews` are reserved in M1.

#### `playbooks` / `playbook_versions`
- `playbooks`: `id`, `name`, `description`, `created_at`, `actor_id`
- `playbook_versions`: `id`, `playbook_id`, `version`, `parent_version_id`, `created_at`, `actor_id`, `provenance_reflection_node_id`
- Playbooks are independent of strategies (§2.6 and §2.12): a decision references a playbook version and a strategy independently. No FK between the two tables.

#### `events`
- `id`, `event_type`, `subject_kind`, `subject_id`, `payload_json`, `actor_id`, `idempotency_key`, `request_id`, `created_at`
- Append-only event log. One row per committed write. Unique on `(event_type, actor_id, idempotency_key)` when the key is present. Full schema and idempotency semantics in [`persistence.md`](./architecture/persistence.md).

#### `outbox`
- `id`, `event_id`, `export_kind`, `state` (`pending`, `exported`, `failed`), `exported_at`, `error_text`, `attempt_count`
- Drives optional JSONL export from the event log without dual writes.

### 3.2 Memory graph

#### `memory_nodes`
- `id`, `node_type` (`observation`, `reflection`, `playbook_rule`)
- `version`, `parent_node_id`, `title`, `body`, `metadata_json`, legacy `meta_json`, `confidence_base`, `decay_rate_per_day`, `importance`, `created_at`, `actor_id`
- During the additive v0.0.2 schema transition, writers dual-write `metadata_json` and `meta_json`; readers prefer `metadata_json` when present and fall back to `meta_json` for legacy rows. Destructive removal of `meta_json` is deferred to the final cleanup wave.
- `valid_from` (default `created_at`), `valid_to` (nullable), `invalidated_at` (nullable), `invalidated_by` (nullable FK to a superseding `memory_nodes.id`). Bi-temporal fields per [`operability.md`](./architecture/operability.md) §2.
- Segmentation: `agent_id`, `model_id`, `environment`, `run_id` (all nullable).
- `node_type` enum is exactly three values. `semantic_claim` from earlier drafts has collapsed into `reflection`-with-slow-decay (writer sets `decay_rate_per_day = 0.0005` or similar); `coach_signal` has moved to the separate `signals` table because its author (the system) and lifecycle (short-lived notification) differ. See [`memory-layer.md`](./architecture/memory-layer.md) §3 for the per-type defaults and required metadata fields.
- `importance` is an integer in `[1, 10]` set by the writer at create time; defaults to `5` if omitted. Feeds reflection-threshold logic and recall ranking. Importance does not decay — it is a fixed signal of the writer's judgement at write time. The retrieval-time confidence model still applies separately (decay + supersession; see [`memory-layer.md`](./architecture/memory-layer.md) §6).
- Embeddings live in the separate `memory_node_embeddings` table (below), not on this row, so a node can have zero or multiple embeddings (one per provider/dim).
- Immutable. Updates create new nodes; older rows stay readable.

#### `memory_node_embeddings`
- `memory_node_id` (FK to `memory_nodes.id`), `provider` (`none` configuration produces no rows; `local` rows use the pinned BGE-small local ONNX model id), `dim` (integer), `embedding` (BLOB), `model_id`, `created_at`
- Primary key: `(memory_node_id, provider)`. A node may have at most one embedding per provider; switching providers either re-embeds (eager via `tt memory reindex --confirm`) or leaves old vectors stale until reindex completes. See [`memory-layer.md`](./architecture/memory-layer.md) §8.4.
- Append-only; replaced rows on reindex use `DELETE` + `INSERT` within a single transaction (the one place a memory-side `DELETE` is allowed; see [`persistence.md`](./architecture/persistence.md) §8).

#### `memory_node_stats`
- `memory_node_id`, `recall_count`, `last_recalled_at`, `updated_at`
- Rebuildable/projection-style recall telemetry. Rebuilt from `memory_recall_events`.

#### `memory_recall_events`
- `id`, `request_id`, `actor_id`, `query_text`, `context_kind`, `context_id`, `strategies_used` (JSON array of `"bm25"`/`"semantic"`/`"temporal"`/`"graph"`), `node_ids_returned` (JSON array, top-k order), `created_at`
- Append-only event log for recall telemetry. Drives `memory_node_stats` projection (per [`persistence.md`](./architecture/persistence.md) §7) and supports the `report.calibration` and DoD §10.2 #11/#15 traceability checks. Recall is a read tool from the agent's perspective; persistence of recall events is an append-only side effect (see [`persistence.md`](./architecture/persistence.md) §7 for transaction handling).

#### `signals`
- `id`, `kind`, `severity`, `body`, `meta_json`, `related_refs_json`, `created_at`, `expires_at`, `actor_id`
- `kind` enum (open enum, extensible without contract bump because it's system-emitted): `calibration_drift`, `override_outcome_negative`, `override_outcome_positive`, `stale_watch`, `unscored_forecast`, `sample_size_warning`, `risk_data_missing`. Implementations may add more; readers must tolerate unknown kinds.
- `severity` enum: `info`, `warn`, `critical`.
- `related_refs_json` is an array of `{kind, id}` pointers to ledger rows the signal references.
- `actor_id` is the system actor (`system:report.coach`, `system:resolve.pending_scan`, etc.) since signals are emitted by the system, not the agent.
- Append-only; stale signals are filtered by `created_at` or `expires_at`, never deleted. See [`memory-layer.md`](./architecture/memory-layer.md) §4 for the rationale of keeping signals out of `memory_nodes`.

#### `edges`
- `id`, `source_kind`, `source_id`, `target_kind`, `target_id`, `edge_type`, `weight`, `created_at`, `actor_id`
- Allowed endpoint kinds: `memory_node`, `decision`, `thesis`, `position`, `forecast`, `outcome`, `snapshot`, `review`, `playbook_version`, `source`, `instrument`, `venue`, `signal`, `strategy`.
- Edge types (7, matching [`memory-layer.md`](./architecture/memory-layer.md) §5): `about`, `derived_from`, `supports`, `contradicts`, `supersedes`, `violates`, `follows`.
- Deferred edge types until a concrete need arises: `links`, `retracts`, `tombstones`. Append-only; correction is via `supersedes`. `contradicts` is semantic evidence and is never used for administrative deletion.
- Endpoint IDs are validated before insertion. **M1 endpoint enum** (minimum sufficient for source attachments and outcome corrections): `decision`, `thesis`, `forecast`, `outcome`, `snapshot`, `instrument`, `venue`, `source`, `review`, `playbook_version`. **M1 edge type enum**: `about`, `supports`, `contradicts`, `supersedes`. The `memory_node`, `signal`, and `strategy` endpoint kinds and the `derived_from`, `violates`, `follows` edge types are added with the memory layer and strategies in M3; pre-M3 writes that pass these kinds or types are rejected with `VALIDATION_ERROR`.

## 4. APIs and tools

### 4.0 Core ledger write tools

The MVP slice's manual ingestion path is exposed as one tool per write table. Every tool below follows the common-metadata contract from §2 (mandatory `actor_id`, mandatory `idempotency_key` for retryable writes unless `_allow_no_idempotency: true`, optional segmentation fields), the success/error envelope from [`contracts.md`](./architecture/contracts.md), and the transaction model from [`persistence.md`](./architecture/persistence.md) §6.

- **`venue.add(name, kind, *, metadata_json?)`** — creates a `venues` row. `kind` ∈ §3.1 venues enum.
- **`instrument.add(venue_id, asset_class, title, *, external_id?, symbol?, currency_or_collateral?, expiration_or_resolution_at?, resolution_criteria_text?, contract_multiplier?, metadata_json?)`** — creates an `instruments` row. `asset_class` ∈ §3.1 instruments enum.
- **`snapshot.add(instrument_id, captured_at, *, source?, source_url?, price?, bid?, ask?, mid?, spread?, volume?, open_interest?, implied_probability?, liquidity_depth_json?, agent_id?, model_id?, environment?, run_id?, metadata_json?)`** — appends a `snapshots` row. Immutable; corrections create new snapshots.
- **`thesis.add(instrument_id, side, body, *, time_horizon_at?, confidence_label?, falsification_criteria?, exit_triggers?, risk_notes?, strategy_id?, parent_thesis_id?, valid_from?, valid_to?)`** — creates a `theses` row. If `parent_thesis_id` is supplied, the new row is the next `version`; a `supersedes` edge is emitted from new → old.
- **`forecast.add(thesis_id, kind, outcomes, *, resolution_at?, yes_label?, resolution_rule_text?, rationale_body?, falsification_criteria?)`** — creates a `forecasts` row plus exactly N `forecast_outcomes` compatibility rows. Binary forecasts must satisfy the §3.1 invariants on outcomes. During the v0.0.2 additive PM transition, binary forecasts also populate canonical `forecasts.probability` from the YES-side outcome and derive/preserve `market_id` where possible; reports and scorers prefer those canonical fields with guarded legacy fallback. `yes_label` is set here and only here; once written it is immutable.
- **`forecast.supersede(prior_forecast_id, *, ...same args as forecast.add except thesis_id)`** — appends a new `forecasts` row, sets the prior row's `scoring_state = 'superseded'` (via supersedes-edge invalidation, not in-place mutation; see [`scoring.md`](./architecture/scoring.md) §4.2), and emits a `supersedes` edge new → prior. The recovery path when an earlier forecast's `yes_label` was ambiguous or wrong.
- **`decision.add(instrument_id, type, *, thesis_id?, forecast_id?, snapshot_id?, side?, quantity?, price?, fees?, slippage?, reason?, playbook_version_id?, review_by?, strategy_id?, tags?)`** — creates a `decisions` row, validated against the §3.1 required-field matrix for `type`. Tags are written to `decision_tags` in the same transaction. For `type = paper_enter`, the tool also appends one linked `position_events.open` row and rebuilds the `positions` projection before returning; response data includes `position_id` and `position_event_id`. `paper_exit` close semantics are not auto-invented. `actual_*`-type decisions are journal records only — no execution side effect or automatic position event, ever.
- **`outcome.add(instrument_id, resolved_at, outcome_label, status, *, outcome_value?, source?, confidence?, metadata_json?)`** — appends an `outcomes` row. Equivalent to `resolve.record` (§4.4); both names resolve to the same internal handler. `outcome.add` is the canonical name; `resolve.record` is retained as an alias for callers that already use it. Triggers auto-scoring per [`scoring.md`](./architecture/scoring.md) §6 when `status = 'resolved_final'`.

### 4.1 Memory

- `memory.retain(node_type, body, *, title?, tags?, metadata_json?, meta_json?, importance?, confidence_base?, decay_rate_per_day?, valid_from?, valid_to?, edges?)` writes a node. `node_type` ∈ {`observation`, `reflection`, `playbook_rule`}. During the additive schema transition, `metadata_json` is the preferred row field and `meta_json` is a legacy alias/fallback. The `edges` parameter lets the caller specify outgoing edges in the same call so reflection-without-edges never happens.
- `memory.recall(query, context?, strategies?, k?, max_chars?, compact?, include_body?, include_provenance?, min_confidence?, node_types?, mode?)` retrieves by FTS5, graph, temporal, and optionally vector similarity. `query` is required; optional `context` narrows graph/provenance ranking metadata such as strategy or instrument context, but does not replace `query`. Default `k = 10`; default `max_chars = 8000`; default `min_confidence = 0.0`. Accepts a `node_types` array (subset of the three node types) to scope recall by type. Accepts a `mode` parameter (`fused` (default) or `per_strategy`): `fused` returns one ranked list via RRF; `per_strategy` returns a `{bm25: [...], temporal: [...], semantic: [...], graph: [...]}` shape so the agent can triangulate without seeing only the combined ranking. Also accepts a `context: {kind, id}` parameter; valid kinds include row-backed targets (instrument, decision, thesis, playbook version, signal) and `strategy` once §2.12 ships in M3. Full contract in [`memory-layer.md`](./architecture/memory-layer.md) §4 and §7.
- `memory.reflect(target, body, *, importance?, ...)` is sugar over `retain(node_type=reflection)` and creates the required `about` edge. The live helper accepts canonical `target_kind`/`target_id` plus `body` (or README sugar `target`/`insight`); provenance/supporting edges are created with `memory.link` or `memory.retain(edges=...)` rather than a `derived_from` argument on `memory.reflect`.
- `reflection.prompt_for_outcome(outcome_id, *, include_forecast?, include_thesis?, include_prior_reflections?)` — deterministic, no-LLM tool that emits a structured prompt packet bundling the resolved outcome, the original thesis and forecast, the agent's prior reflections on this instrument/strategy, and the calibration delta. The caller (a separate LLM) decides what to write back via `memory.reflect`. The system never auto-generates reflections.

### 4.2 Reports and coach

All deterministic reports accept a `filter` argument conforming to the `ReportFilter` schema in [`reports.md`](./architecture/reports.md) §2, return `ReportResult` envelopes with drill-down IDs and sample-size warnings (see `reports.md` §3), and support truncation/cursor semantics. The `filter` argument honors the canonical strategy-id sentinel from §2.12 (omitted/`null` = no filter; `"__none__"` = rows with no strategy). Filter wiring lands in M2; pre-strategy data simply has `strategy_id = NULL` and is included by an unfiltered call.

Deterministic reports:

- `report.calibration` — binary Brier, log score, reliability buckets, ECE, sharpness, and a sample-prevalence baseline, computed over scored binary forecasts matching the filter. Supports actor/run filters for `actor_id`, `agent_id`, `model_id`, `environment`, and `run_id` plus the documented venue/strategy/outcome filters. Full output shape and formulas in [`scoring.md`](./architecture/scoring.md) §3 and §7 and `reports.md` §4. Returns `sample_warning` when the filtered set is below the configurable minimum (default 20 scored forecasts).
- `report.forecast_diagnostics` — binary-first retrospective diagnostics over local forecasts, scored outcomes, decisions/non-actions, and caller-supplied snapshots. It compares agent `p_yes` only to stored `snapshots.implied_probability` as a caveated caller-supplied `recorded_market_reference_gap`, reports Brier/reliability/base-rate caveats and low-N/source/spread/liquidity coverage, excludes unsupported/non-binary forecasts with reasons, and never fetches data or provides advice, a trading signal, alpha, or profit/performance ranking.
- `report.mistakes` / `report.strengths` — current compatibility implementation ranks decision tags by mean Brier on scored forecasts and rejects non-empty filters; broader tag counts/co-occurrence over decisions plus reviews remain target/follow-up work, not shipped behavior.
- `report.pnl` — paper/actual P&L aggregates where position projections have enough fills to compute realized/unrealized P&L. Returns a `data_coverage` field reporting how many positions could and could not be computed.
- Current-exposure/open-position report surfaces must follow [`current-exposure-agent-contract.md`](./architecture/current-exposure-agent-contract.md) for bucket names, caveat codes, and source precedence. This PRD link is a contract seam only; it does not imply a shipped `report.current_exposure` tool.
- `report.watchlist` — lazy stale-watch detection (the `watch.stale` historical name was rolled into `report.watchlist`; see trade-trace-ftnu).
- `report.unscored_forecasts` — lazy time-passed unscored detection.
- `report.playbook_adherence` — driven by `decision_playbook_rules`; surfaces considered/followed/overridden/not_applicable counts and override outcomes.
- `report.decision_velocity`.
- `report.filter_schema` — returns the canonical `ReportFilter` Pydantic schema as JSON, so an agent can introspect valid fields without hitting the docs.
- `report.calibration_integrity` — six anti-goodhart hygiene diagnostics (forecast_coverage, unsupported_rate, ambiguous_rate, disputed_rate, void_cancelled_rate, suspicious_late_rate). Embedded in `report.calibration.data.integrity_diagnostics` and surfaced as a standalone tool. See [`reports.md`](./architecture/reports.md) §4.8. (Bead trade-trace-jzn.)
- `report.source_quality` — five provenance hygiene diagnostics (missing_sources_on_actual_enter, stale_sources, contradictory_sources, duplicated_sources, sensitive_sources) over the source-attachment graph. See [`reports.md`](./architecture/reports.md) §4.9. (Bead trade-trace-l9q.)
- `report.audit_readiness` — read-only prediction/event-market audit-readiness diagnostics with `blocking` / `warning` / `info` severities for resolution-rule provenance, snapshot freshness, bid/ask/spread/depth coverage, source freshness/contradictions, and decision provenance. It is local-only, deterministic, and never fetches market data or gives trading advice. See [`reports.md`](./architecture/reports.md) §4.10. (Bead trade-trace-r566.)
- `tool.schema` — per-tool introspection: returns description, CLI invocation, example_minimal/example_rich payloads (for write tools), and required_metadata notes (actor_id pattern, idempotency_key pattern, dry-run support flags). Omit `tool` to enumerate the full tool catalog. (Bead trade-trace-268.)

Every write tool accepts `--dry-run` (CLI) / `_dry_run: true` (MCP): the dispatcher rolls back the wrapping transaction so the call returns the would-be IDs and payload without persisting any rows. `meta.dry_run=true` echoes back on the envelope (success or error). (Bead trade-trace-268.)

`report.coach` aggregates objective signals into a structured packet. It does not call an LLM and does not provide trading advice. Allowed outputs: surfacing recurring tags, calibration drift buckets, override outcomes, stale watches, sample-size warnings, integrity / source-quality diagnostics. Forbidden outputs: trade recommendations, profitability claims, directional advice.

Trading-native liquidity-bucket and skipped-positive-edge review reports are deferred to P1; that legacy label refers only to caller-recorded thesis/review terminology, not an engine for discovering profitable edge. A cautious binary-first `report.forecast_diagnostics` now covers local forecast-vs-recorded-market-reference diagnostics using caller-supplied `snapshots.implied_probability` only; no data is fetched or treated as advice, a trading signal, alpha, or profitability evidence. The data is already captured in `snapshots`; broader reports are additive.

Comparison and per-strategy reporting:

- `report.compare(group_by, filter)` — runs the same metric set across groups and returns a per-group `ReportGroup` for side-by-side comparison. Live `group_by` values (per `trade_trace.reports.compare.SUPPORTED_GROUP_BY_BY_BASE_REPORT`): for `base_report="calibration"` — `actor_id`, `agent_id`, `model_id`, `run_id`, `strategy_id`, `decision_type`, `venue_id`, `asset_class`, `environment`, `instrument_id`, `outcome_status`, `status`; for `base_report="pnl"` — `instrument_id`, `status`, `venue_id`, `asset_class`. Deferred to P1+ until SQL mapping lands: `playbook_version_id`, `liquidity_bucket`, `confidence_bucket`. See trade-trace-cs0r.
- `report.strategy_performance` — shipped convenience wrapper over `report.compare(base_report="pnl", group_by="strategy_id")`; broader per-strategy calibration trend, mistake-tag frequency, and playbook-adherence summary remain additive target behavior, not part of the current wrapper contract.
- `report.strategy_health` — deterministic read-only local process-health report across active strategies by default. It surfaces review-due decisions, low-N caveats, open/unresolved forecasts, thesis source-reference gaps, repeated overrides, and the current unsupported-local-surface caveat for policy candidates. It uses administrative ordering, not profit/performance ranking, and does not fetch data, detect edge/signals, or provide advice.
- `report.risk` and `report.opportunity` — shipped local journal/projection analysis reports; see [`risk-units.md`](./architecture/risk-units.md) and [`opportunity-analysis.md`](./architecture/opportunity-analysis.md). They do not fetch market data, execute trades, or assert broker truth.

`review.bundle(filter, *, max_records?, include_sources?, include_reflections?, include_playbook?)` packages a bounded case set as deterministic JSON for an external review loop (a separate LLM or a human reviewer). It selects records by filter, includes their theses/forecasts/outcomes/reflections, and includes attached sources subject to `sources.redaction_status`. Sources marked `sensitive` are never included; sources marked `redacted` have `body`/`extracted_text` omitted. The bundle does not call an LLM and does not provide advice. Full spec in [`reports.md`](./architecture/reports.md) §5.

### 4.3 Playbooks

- `playbook.create`, `playbook.list`, `playbook.show`
- `playbook.propose_version`, `playbook.list_versions`
- `playbook.adherence` — convenience wrapper around `report.playbook_adherence` scoped to a single playbook

MVP captures the active playbook version and normalized adherence records on every decision. Machine-checkable predicates may be added for specific rule types later.

`playbook.adherence` and `report.playbook_adherence` accept an optional `strategy_id` parameter (filter semantics per §2.12) so adherence can be sliced by strategy — e.g., "how well does the `earnings-momentum` strategy follow the `risk-management` playbook." This filter lands in M4.

### 4.4 Resolution

- `resolve.pending` — returns forecasts past their `resolution_at` without an `outcomes` row, or with an outcome row whose `status != 'resolved_final'`. Idempotent read. Accepts `filter` (the `ReportFilter` schema from [`reports.md`](./architecture/reports.md) §2), optional `cursor`, and `limit` (default 100, max 1000). Returns deterministic ordering by `resolution_at ASC, forecast_id ASC` so cursor pagination is stable.
- `resolve.record` — alias of `outcome.add` (§4.0). Writes an `outcomes` row with the required `status`, optionally attaches evidence via `source.attach_to_*` in the same logical operation (separate edge writes; see [`persistence.md`](./architecture/persistence.md) §6), and triggers auto-scoring when `status = 'resolved_final'` and the forecast is scoring-supported. Either name resolves to the same handler; success envelopes echo `meta.tool` with the name the caller used.

These tools exist because outcomes lag decisions: the agent session that resolves a forecast is usually not the same session that made the decision.

### 4.5 Sources

- `source.add` — creates a `sources` row.
- `source.attach_to_thesis`, `source.attach_to_decision`, `source.attach_to_forecast`, `source.attach_to_memory_node` — create `about`/`supports`/`contradicts` edges from a source to the target, depending on the source's `stance`.

Evidence capture is first-class in MVP because reflection quality depends on it: "did I overweight a weak source", "did I miss the resolution criteria", "did I rely on stale news" are answerable only if sources were captured at decision time.

### 4.6 Strategies

Strategies (§2.12) are managed through a small CRUD-style tool family:

- `strategy.create(name, slug?, description?, hypothesis?)` — creates a new `active` strategy. The `slug` defaults to a kebab-case slugification of `name`; duplicate slugs raise `VALIDATION_ERROR` (§6).
- `strategy.list(status?, q?)` — lists strategies. `status` defaults to `active` and accepts `active`, `archived`, `both`, or `all` (`both` and `all` are aliases for all statuses). `q` is a substring search over `name`, `slug`, `description`, and `hypothesis`.
- `strategy.show(strategy_id? | slug?, as_of?, stale_threshold_days?)` — returns the strategy row plus a read-only `health_summary` derived from local recorded data. `as_of`, when supplied, must be a UTC ISO-8601 timestamp ending in `Z` (for example, `2026-01-20T00:00:00Z`) so text-ordered due/stale checks match stored project timestamps. The summary exposes deterministic counts and drilldown IDs for scoped decisions, theses, unresolved/scored forecasts, due/stale watches when `as_of` is supplied, source/reflection/adherence caveats, and low-sample warnings. Cross-strategy and forecast-specific diagnostics remain report surfaces such as `report.strategy_performance` and later strategy/forecast diagnostics reports.
- `strategy.update(id, *, description?, hypothesis?, status?)` — partial update. `name` and `slug` are immutable in MVP; rename support is deferred. Setting `status='archived'` is the archive operation; there is no separate `strategy.archive` tool.

Tools that reference a strategy (`decision.add`, `thesis.add`, write paths into `reviews`, `memory.recall` context, `memory.reflect` target, and every `report.*` filter) accept the canonical `strategy_id`. They MAY also accept a `strategy_slug` input alias that the server resolves to `strategy_id` before validation; the success envelope always echoes `strategy_id` regardless of which form was passed.

The strategy tool family ships in M3 alongside the memory layer (§8); the nullable `strategy_id` column is reserved on `decisions`, `theses`, and `reviews` in M1 to keep the schema forward-compatible.

### 4.7 Imports

JSONL import is the canonical local-ingestion path. Each line is a `{tool, args}` envelope identical to the in-process tool calls in §4.0–§4.6; the importer replays them through the same handlers with the same validation and idempotency contract. There is no broker-specific logic in the core; venue-specific adapters that produce Trade Trace JSONL live outside the package.

- `import.validate(file, *, max_errors?)` — dry-run path. Parses, validates, and reports `validated`, `would_create`, `would_replay`, `errors[]`, and `warnings[]` without writing.
- `import.commit(file, *, halt_on_error?)` — write path. Wraps the JSONL stream in a single transaction by default (atomic import); per-row transactions opt-in via `transaction_mode='per_row'` for very large files where atomicity is impractical.

CSV-fills import is implemented and documented in [`imports.md`](./architecture/imports.md) §3. It shares the validation/dry-run/idempotency contract.

The current pre-release implementation includes the import-ready write schema plus `import.validate`, `import.commit`, and `import.csv_fills`. See [`imports.md`](./architecture/imports.md) for the full contract and current shipped status.

## 5. Storage

- Primary store: SQLite at `$TRADE_TRACE_HOME/trade-trace.sqlite`, WAL mode, single-writer assumption for MVP (see [`operability.md`](./architecture/operability.md) §3 for second-writer behavior).
- Required recall: SQLite FTS5 + graph + temporal queries.
- Optional local vector recall via pre-staged ONNX assets if `[embeddings]` is installed and `embeddings.provider=local`; missing assets/dependencies degrade to required recall.
- Event/outbox tables record committed writes for audit/export. JSONL export is generated from the outbox; see [`persistence.md`](./architecture/persistence.md).
- Migrations are versioned and preserve data. Migration policy (forward-only with documented schema-version field; enum extensions are non-breaking; column removals are major) detailed in [`operability.md`](./architecture/operability.md) §4.
- File permissions default to user-only where supported. Logging policy, crash-recovery contract, blob-size caps, and outbox JSONL file format detailed in [`operability.md`](./architecture/operability.md).

## 6. Output contract

- CLI stdout is JSON only by default; list streams use NDJSON.
- `--human` may add prose to stderr only.
- MCP uses normal MCP framing and may stream according to transport capabilities.
- CLI and MCP must be schema/semantic equivalents after transport normalization, not byte-level twins.
- Success and error envelopes have the shapes defined in [`contracts.md`](./architecture/contracts.md). Stable error codes: `VALIDATION_ERROR`, `NOT_FOUND`, `IDEMPOTENCY_CONFLICT`, `UNSUPPORTED_CAPABILITY`, `STORAGE_ERROR`, `SCORING_UNSUPPORTED`, `SCORING_NOT_READY`, `INVARIANT_VIOLATION`, `MARKET_NOT_RESOLVED`, `MARKET_AMBIGUOUS`.

## 7. Safety and privacy

- No execution path places, signs, cancels, or routes trades.
- No external data fetching (§2.4): no network surface, no third-party API surface, no rate limits to negotiate.
- Core never accepts or persists credentials of any kind.
- Wallet/broker/order-signing credentials are never supported.
- Analytics are retrospective decision support, not recommendations or financial advice.

## 8. Milestones

### M0 — Repo and package foundation
- Python 3.11+, MIT license, package skeleton
- Pydantic schemas and migration framework
- SQLite + FTS5 baseline; optional local ONNX/tokenizers embeddings path with graceful fallback
- Initial docs including `operability.md`, `reports.md`, `imports.md`

### M1 — Manual ledger core + CLI/MCP frames
- Tables for venues, instruments, snapshots, theses, forecasts, decisions, outcomes, sources, tags, events, outbox, and write metadata (with segmentation fields `agent_id`/`model_id`/`environment`/`run_id` and bi-temporal fields `valid_from`/`valid_to`/`invalidated_at`/`invalidated_by` on belief-shaped tables)
- `edges` table ships in M1 with a **minimal endpoint enum** sufficient for source attachments and outcome corrections: `decision`, `thesis`, `forecast`, `outcome`, `snapshot`, `instrument`, `venue`, `source`, `review`, `playbook_version`. Edge types in M1: `about`, `supports`, `contradicts`, `supersedes`. The `memory_node`, `signal`, and `strategy` endpoint kinds and the `derived_from`/`violates`/`follows` edge types are deferred to M3 alongside the memory layer and strategies (§3.2); pre-M3 writes that pass deferred kinds or types are rejected with `VALIDATION_ERROR`. `signals` table is M3 (no system-emitted signals before reports exist).
- Reserve nullable `strategy_id` columns on `decisions`, `theses`, and `reviews` for forward compatibility; the `strategies` table itself, the `strategy.*` tools, and the `strategy` edge endpoint kind ship in M3
- Core write tools per §4.0: `venue.add`, `instrument.add`, `snapshot.add`, `thesis.add`, `forecast.add`, `forecast.supersede`, `decision.add`, `outcome.add` / `resolve.record`
- `journal.init`, `journal.status`, `journal.schema`, JSONL export drain
- Manual end-to-end write path: instrument → snapshot → thesis → binary forecast → decision → outcome
- Idempotency contract and result/error envelope per [`contracts.md`](./architecture/contracts.md) and [`persistence.md`](./architecture/persistence.md)
- `source.add`, `source.attach_to_*` with provenance fields per §3.1 sources (writes `about`/`supports`/`contradicts` rows into the M1 `edges` table)
- Outcome correction path per §3.1 outcomes (new `outcomes` row + `supersedes` edge in the M1 `edges` table)
- `resolve.pending`, `resolve.record`

### M2 — Binary scoring and deterministic reports
- `forecast_scores` binary Brier on supported outcome writes (single-probability form per [`scoring.md`](./architecture/scoring.md))
- `ReportFilter` schema and `report.filter_schema` per [`reports.md`](./architecture/reports.md)
- Calibration (Brier + log score + reliability bins + ECE + sharpness + baseline per `scoring.md` §7), watchlist, unscored forecast, tag, decision velocity, and basic P&L reports
- Drill-down envelope on all reports per [`reports.md`](./architecture/reports.md) §3 (aggregate → filter → contributing record IDs → examples)
- Optional `filter` parameter on every report per §2.12 strategy-id sentinel semantics; the filter operates on the still-nullable column reserved in M1, so calls without an active strategy match all rows
- Lazy coach-signal generation in reports/explicit scans (writes to the `signals` table)

### M3 — Memory layer and recall
- `memory_nodes` (3 node types, bi-temporal columns, importance), `memory_node_embeddings`, `memory_node_stats`, `memory_recall_events`, `signals`, `edges`
- `memory.retain`, `memory.reflect`, `memory.recall` with budget params (`max_chars`, `compact`, `include_body`, `include_provenance`) and `mode` (`fused` | `per_strategy`)
- `reflection.prompt_for_outcome` deterministic prompt-packet tool
- FTS5 + graph + temporal recall; optional vector recall when SEMANTIC strategy is enabled per §2.4.1
- `strategies` table and `strategy.{create,list,show,update}` tools per §4.6
- `strategy` (and `signal`) added to the edge endpoint kind enum (§3.2)
- `memory.recall(query, context: {kind: "strategy", id})` and `memory.reflect(target: strategy)` per [`memory-layer.md`](./architecture/memory-layer.md) §7 and §9

### M4 — Playbook loop
- Playbooks, versions, playbook rule nodes
- Normalized `decision_playbook_rules` adherence tracking
- `report.coach` and `report.playbook_adherence`
- Optional `strategy_id` filter on `report.playbook_adherence` and `playbook.adherence` per §4.3
- Playbook version update with reflection provenance

### Shipped in the post-MVP pre-release track
- JSONL import implementation (`import.validate`, `import.commit`) per [`imports.md`](./architecture/imports.md)
- CSV-fills import (including optional `strategy_id` column) per [`imports.md`](./architecture/imports.md) §3
- Risk-unit fields and the shipped subset of `report.risk` per [`risk-units.md`](./architecture/risk-units.md)
- Path-dependent analysis and the shipped subset of `report.opportunity` per [`opportunity-analysis.md`](./architecture/opportunity-analysis.md)
- `report.compare` implementation (segmentation data is captured from M1)
- `review.bundle` implementation
- `report.strategy_performance` — per-strategy P&L, calibration trend, mistake-tag frequency, playbook adherence summary
- The former local read-only Console UI was removed before release; current reporting/review surfaces are MCP/CLI tools, `review.bundle`, and Python/library report APIs.
- Guided market-scan journal bundle flow (originally `market.scan.dry_run` / `market.scan.promote`, now consolidated into `market.bind` per trade-trace-4kec; see [`market-scan-contract.md`](./architecture/market-scan-contract.md))

### P1
- Multi-class/categorical scoring and ranked probability score — **shipped** in the P1 scoring upgrade (see [`scoring.md`](./architecture/scoring.md)); normalized scalar auto-scoring shipped alongside it
- Scalar/distribution schema including `distribution_json` (still deferred follow-up)
- Broader trading-native reports: calibration-by-liquidity-bucket, skipped-positive-edge review
- ForecastBench schema verification and compatible export if feasible
- HTTP/SSE transport, re-embedding tools
- Subscribe API on the event log

### P2
- Optional cross-device sync
- Historical/replay hooks
- Multi-agent concurrency improvements

## 9. Testing and verification

- `journal.init` is idempotent.
- Every tool has a JSON schema; `report.filter_schema` and `journal.schema` surface them at runtime.
- Every write carries `actor_id`/actor metadata; retryable writes require `idempotency_key` by default and replay-safely. The `--allow-no-idempotency` opt-out is exercised by tests of at-least-once import paths only.
- CLI and MCP outputs are semantically equivalent after transport normalization (verified by the golden-test suite in [`contracts.md`](./architecture/contracts.md) §7).
- Append-only invariants hold for source/event tables.
- `positions`, `memory_node_stats` can be rebuilt from source data via `journal.rebuild_projections`.
- Binary Brier scores match reference calculations using the single-probability form. Log score, ECE, sharpness, and the sample-prevalence baseline match reference formulas in [`scoring.md`](./architecture/scoring.md) §3 and §7.
- Reliability-diagram bin boundaries are deterministic given the bin policy in [`scoring.md`](./architecture/scoring.md) §7.2.
- Binary forecast invariants hold: exactly two outcomes, probabilities in `[0,1]`, sum to `1.0` within `1e-6`, distinct labels.
- Auto-scoring is blocked when the linked `outcomes.status != 'resolved_final'`.
- An `IDEMPOTENCY_CONFLICT` is raised only on semantically incompatible payload reuse; pure replay succeeds and reports `meta.idempotent_replay: true`.
- Time-passing signals are generated lazily by reports or explicit scan, not by a hidden daemon.
- Security tests ensure credentials are not accepted through CLI/MCP args and are not logged. The embedding-download path is exercised only when explicitly enabled; default-disabled behavior is verified to make zero outbound calls during `journal.init`.
- Bi-temporal queries: `as_of=<timestamp>` predicates return the rows whose `[valid_from, valid_to)` interval contained the timestamp and were not `invalidated_at <= <timestamp>`. Tests cover (a) a thesis whose `valid_to` is hit by `time_horizon_at` arrival, (b) a forecast invalidated by `forecast.supersede`, (c) a memory node invalidated by an explicit supersedes edge.
- Decision required-field matrix per §3.1 decisions is enforced at write time: forbidden field with value raises `VALIDATION_ERROR` with `details.field` set; missing required field same.
- Outcome corrections create new rows and emit a `supersedes` edge; auto-scoring never fires against a superseded outcome.

## 10. Definition of done — MVP

The MVP is done when **both** the plumbing criteria and the loop-useful criteria below are met.

### 10.1 Plumbing criteria (the loop runs)

1. Initialize a journal.
2. Record at least 30 decisions, including binary forecasts.
3. Resolve at least 5 supported binary forecasts with `outcomes.status = 'resolved_final'` and score them with binary Brier.
4. Run deterministic reports and `report.coach`.
5. Write at least 10 reflections linked to ledger rows.
6. Propose at least one playbook version update with provenance from a reflection.
7. Record `decision_playbook_rules` adherence entries on later decisions and surface them in `report.playbook_adherence`.
8. Recall relevant prior memories/playbook rules during a later thesis.
9. Execute zero trades and handle zero execution credentials.

### 10.2 Loop-useful criteria (the loop helps)

Each criterion has a deterministic protocol and measurable assertion in [`dogfood-protocol.md`](./architecture/dogfood-protocol.md) §5; `c1r` (Final Verification) runs the protocol against the trade-trace-8dv fixture.

10. At least one report identifies a recurring error or strength pattern that the agent did not call out in advance. (Protocol: §5.1.)
11. At least one `memory.recall` result is explicitly cited in a later thesis, traceable via a `derived_from` or `supports` edge. (Protocol: §5.2; "agent did not already know this" construction in §6.)
12. At least one playbook rule changes a later decision: either followed (`decision_playbook_rules.status = 'followed'`) or overridden (`status = 'overridden'`) with the outcome captured. (Protocol: §5.3.)
13. At least one ambiguous-resolution case is handled correctly: the outcome row carries `status ∈ ('ambiguous', 'disputed', 'resolved_provisional')` and the forecast remains in `scoring_state = 'pending'` until a `resolved_final` outcome supersedes it. (Protocol: §3 / §5.4 covers `void`, `disputed`, and `resolved_provisional` scenarios.)
14. The calibration report explicitly states sample size and emits a `sample_warning` when the filtered set is below the configurable minimum (default 20 scored forecasts); 5 resolved forecasts is enough for plumbing but not enough for serious calibration, and reports must say so. (Protocol: §5.5.)
15. At least one strategy-scoped recall (`memory.recall(query, context: {kind: 'strategy', id})`) surfaces a memory the agent did not cite in the originating thesis, traceable via a `derived_from` or `supports` edge — demonstrating that strategies actually narrow recall to a useful subset rather than acting as decorative metadata. (Protocol: §5.6.)
16. The calibration report surfaces a sharpness signal that distinguishes "always 50%" from a confident-and-calibrated forecaster (the former has near-zero sharpness; the latter has non-trivial sharpness with low ECE). (Protocol: §5.7.)

The validation question for the MVP is whether the loop **made the LLM trader auditable, calibratable, and improvable over time**: every decision traces to a thesis with bi-temporal validity, every supported forecast has a calibration score with a documented baseline, and every reflection traces to the ledger rows that motivated it.

## 11. Remaining open questions

1. Exact ForecastBench export shape: verify against the current schema before promising compatibility.
2. ~~Surfacing "the agent did not already know this" for the §10.2 usefulness criterion~~ Resolved by [`dogfood-protocol.md`](./architecture/dogfood-protocol.md) §6: the construction relies on the union of `derived_from`/`supports`/`about` edges from the new thesis (and its same-transaction decision/forecast rows) plus the immediately-preceding `memory_recall_events` row's `node_ids_returned`. No `prior_knowledge` boolean column is needed; the property is computable from existing data and surfaces in `report.coach`.
3. **Strategy ↔ playbook coupling.** A future `playbook_strategy_link(playbook_version_id, strategy_id, role)` join table is considered and explicitly deferred. Orthogonality (§2.6, §2.12) is the MVP stance. Promote when dogfood shows that playbooks consistently follow strategy boundaries (e.g., one strategy "owns" a rule set used nowhere else) and `(strategy × playbook)` filtering on `report.playbook_adherence` becomes insufficient.
4. **Strategy versioning.** Hypotheses evolve. MVP captures evolution as `strategy.updated` events in the `events` log (per §3.1 and [`persistence.md`](./architecture/persistence.md)). Promote to a `strategy_versions` table when point-in-time queries like "what was this strategy's hypothesis on the date I made decision X" become load-bearing for reflection or reporting.
5. **Many-to-many decision↔strategy.** Pairs trades and basket strategies arguably belong to multiple strategies at once. MVP uses a single nullable `strategy_id` FK; the workaround is a composite strategy row (e.g., `pairs-trade-AAPL-MSFT`). Promote to a `decision_strategies` join table when dogfood produces concrete cases where the composite-row workaround loses information that reports actually consume.
6. **`strategy_id` filter sentinel.** §2.12 defines `"__none__"` as the "no strategy" selector. The sentinel string is chosen rather than a separate boolean (`strategy_present: false`) to keep the report-tool surface consistent across filters. Revisit if a second non-null sentinel becomes necessary (e.g., "strategies in any of \{...\}").
7. **`account_label` promotion from `metadata_json`.** Segmentation by portfolio/account bucket is currently a `metadata_json` key, not a first-class column, to avoid implying broker-account semantics. Promote to a first-class column on `decisions`/`positions`/`outcomes` when dogfood produces reports that actually need to filter or group by it. Demoting a first-class column is more expensive than promoting from JSON.
8. **Two-tier reflection.** Current `memory.reflect` produces one node per call. Generative-agents-style two-tier reflection (shallow per-session, deep per-cluster) is appealing once importance accumulation across sessions is dogfooded. P1+ candidate.
9. **Letta-style core memory block.** A small pinned "session_context" rewritable scratchpad surfaced on every relevant call is interesting; deferred because the MVP loop runs without it and the cost of adding it later is small.
10. **Source-typed decay profiles.** FinMem-style shallow/intermediate/deep decay buckets per `sources.kind` could feed temporal weighting in recall. Currently each `memory_node.decay_rate_per_day` is writer-set per node; layered decay-by-source is a P1+ refinement.

Closed in this pass (no longer open): the embedding-default-on/off ambiguity (resolved off-default per §2.4.1), the re-embedding policy (resolved eager per [`memory-layer.md`](./architecture/memory-layer.md) §8.4), multi-writer behavior (specified in [`operability.md`](./architecture/operability.md) §3), memory taxonomy drift (resolved to 3 node types), edge-taxonomy drift (resolved to 7 types), and outcome-correction mechanism (resolved to supersedes-edge per §3.1 outcomes).
