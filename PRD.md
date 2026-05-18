# Trade Trace — Product Requirements Document

**Date:** 2026-05-18
**Status:** Clean planning draft
**Companion docs:** [`VISION.md`](./VISION.md), [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md), [`docs/architecture/scoring.md`](./docs/architecture/scoring.md), [`docs/architecture/persistence.md`](./docs/architecture/persistence.md), [`docs/architecture/contracts.md`](./docs/architecture/contracts.md)

Trade Trace is a local, open-source, AI-only journal, memory, and calibration substrate for LLM trading agents. It records decisions, resolves outcomes, scores supported forecasts, stores reflections, evolves playbooks, and recalls prior learning. It never executes trades, never queries external venues for market data, never handles execution credentials, and is not a human dashboard.

## 1. MVP scope

The MVP proves the full four-layer learning loop with narrow breadth: a complete learning-loop slice, not the entire broad product. Breadth is deferred.

MVP vertical slice:

1. `journal.init`
2. Structured manual ingestion of instruments, snapshots, theses, binary forecasts, and decisions
3. Structured manual outcome entry with a typed resolution status
4. Binary Brier scoring (see [`scoring.md`](./docs/architecture/scoring.md))
5. Deterministic reports and `report.coach`
6. Agent-written reflection
7. Playbook version update with normalized adherence tracking (considered, followed, overridden, not_applicable)
8. Token-budgeted recall of prior observations, reflections, and playbook rules in the next decision
9. Source/evidence capture attached to theses, decisions, and forecasts

Deferred or optional after the manual loop: `sqlite-vec` embeddings, CSV import, multi-class/scalar scoring, trading-native edge/market reports (forecast-vs-market, calibration-by-liquidity-bucket, skipped-positive-edge review), exact ForecastBench submission compatibility, web viewer, sync, HTTP/SSE transport, and websockets.

There are no external data connectors. The agent supplies all market data through the structured ingestion APIs.

## 2. Locked product decisions

### 2.1 Memory layer

The memory layer is built in-house, modeled on Retain / Recall / Reflect but trading-specific. Memory nodes link to ledger rows, carry confidence/decay metadata, and can participate in typed graph recall. No external memory framework is a runtime dependency. See [`memory-layer.md`](./docs/architecture/memory-layer.md).

### 2.2 State model

The SQLite database is the source of truth. It separates immutable event/source tables from mutable or rebuildable projections. See [`persistence.md`](./docs/architecture/persistence.md) for the full event/outbox/idempotency contract.

- `position_events` are source of truth; `positions` is a projection derived from them.
- `memory_nodes` are immutable; recall telemetry belongs in `memory_node_stats` or recall events/projections, not on the node row.
- Corrections create new rows/events, not silent mutation.
- JSONL export/audit is derived from committed DB events via the outbox table. It is not a second source of truth and must not require fragile dual writes.

### 2.3 CLI and MCP parity

One internal core API backs both MCP and CLI. Tool schemas, validation semantics, result meaning, and error codes must be equivalent after transport normalization. JSON byte identity is not required because MCP framing, streaming, and transport metadata differ from CLI stdout/NDJSON. See [`contracts.md`](./docs/architecture/contracts.md) for the envelope and error code list.

### 2.4 No data fetching

Trade Trace never queries external venues, broker APIs, or market data providers. The agent calling Trade Trace already has the data — it is the one currently analyzing the market — and supplies it through structured ingestion APIs. This boundary keeps the product small, market-agnostic, secure by construction, and free of third-party rate limits, version drift, and trust assumptions.

The `snapshots.source` and `outcomes.source` columns are free-form strings. MVP only writes `'manual'`. The columns exist so future imports (CSV, JSONL, dogfooded research scripts) have a place to land without migration; no connector type taxonomy is implied or reserved.

### 2.5 Forecast model

MVP scoring is binary only. See [`scoring.md`](./docs/architecture/scoring.md) for invariants, the exact Brier formula (single-probability form), the resolution status enum, and the lifecycle of a forecast row.

- Binary prediction markets: score directly against resolved YES/NO outcome.
- Equity/crypto directional forecasts: may be expressed as binary derived events, e.g. `AAPL closes above 200 at horizon` or `BTC return > 0 by horizon`.
- Scalar, options, futures, numeric, and multi-outcome forecasts may be stored as record-only data with `scoring_support = 'unsupported'` until P1.
- P1 may add `forecasts.distribution_json` and multi-class/scalar scoring; it is not an MVP schema field.

The `forecasts` table splits status into two columns: `scoring_support` (capability) and `scoring_state` (lifecycle). Auto-scoring only fires when the linked `outcomes` row has `status = 'resolved_final'`.

### 2.6 Playbooks

MVP playbook rules are advisory. The agent records which rules it considered, followed, overrode, or judged not_applicable in a normalized `decision_playbook_rules` table (§3.1), not in a JSON blob. Automatic violation detection is only implemented for future rules whose predicates are explicitly machine-checkable. MVP must not promise a general automatic rule engine.

### 2.7 Coach signals

No background scheduler or daemon exists in MVP. Write-triggered signals may be persisted during ordinary writes. Time-passing signals, such as stale watches and unscored forecasts, are generated lazily by `report.coach`, `watch.stale`, `report.unscored_forecasts`, or an explicit maintenance scan. External scheduling is out of scope.

### 2.8 Credentials and security

The core never accepts, stores, logs, or prompts for credentials. Wallet, broker, order-signing, and seed credentials are never supported, never read from any source, and never appear in any API surface. Because there is no external data fetching (§2.4), there is no execution path, network surface, or third-party trust model in MVP.

### 2.9 Tags

Tags are stored relationally, e.g. `decision_tags(decision_id, tag)` and `review_tags(review_id, tag, tag_kind)`, because SQLite has no native array column type. APIs may expose arrays for convenience.

### 2.10 Edges

Generic edges require endpoint validation against allowed endpoint kinds and existing IDs. Edge endpoint kinds include memory nodes and ledger rows including instruments and venues. Do not use `contradicts` for administrative edge deletion. Edge removal/admin history is either deferred or represented with retract/tombstone edge events.

Period- or tag-scoped reflections are valid, but periods and tags are not MVP edge endpoints. Their scope is stored in reflection `meta_json` unless later versions add first-class period/tag entities.

### 2.11 External claims

- yfinance, Polymarket Gamma, and similar external APIs are explicitly out of scope; see §2.4.
- `sqlite-vec` is optional/verified at init; MVP recall can use FTS5 + graph + temporal retrieval.
- Local embedding models are downloaded/cache-managed when enabled.
- ForecastBench export is ForecastBench-inspired/TBD until the current external schema is verified.
- No claim is made that LLMs have reached forecasting parity with human superforecasters.

## 3. Data model

All write APIs include common metadata from MVP:

- `id`
- `created_at`
- `actor_id` or `actor` (`agent:default`, `cli:user`, `import:<name>`, etc.)
- `idempotency_key` where retries are expected (uniqueness scope and conflict behavior in [`persistence.md`](./docs/architecture/persistence.md))
- `metadata_json` where venue/tool-specific extension is needed

### 3.1 Core ledger/source tables

#### `venues`
- `id`, `name`, `kind`, `metadata_json`, `created_at`, `actor_id`

#### `instruments`
- `id`, `venue_id`, `external_id`, `symbol`, `title`, `asset_class`, `currency_or_collateral`
- `expiration_or_resolution_at`, `resolution_criteria_text`, `contract_multiplier`, `metadata_json`, `created_at`, `actor_id`

#### `snapshots`
- `id`, `instrument_id`, `captured_at`, `source`, `source_url`
- `price`, `bid`, `ask`, `mid`, `spread`, `volume`, `open_interest`, `implied_probability`, `liquidity_depth_json`
- `metadata_json`, `created_at`, `actor_id`
- Immutable; corrections create new snapshots.
- `source` is a free-form string; MVP only writes `'manual'`.

#### `theses`
- `id`, `instrument_id`, `version`, `parent_thesis_id`, `side`, `time_horizon_at`, `confidence_label`
- `body`, `falsification_criteria`, `exit_triggers`, `risk_notes`, `created_at`, `actor_id`
- Versioned; updates create new rows.

#### `forecasts`
- `id`, `thesis_id`, `kind` (`binary`, `categorical`, `scalar`), `resolution_at`, `yes_label`
- `scoring_support` (`supported`, `unsupported`) — capability: can this `kind` be scored by the installed scorer?
- `scoring_state` (`pending`, `scored`, `failed`, `superseded`) — lifecycle: what has happened to this forecast?
- `created_at`, `actor_id`
- MVP supports binary scoring only; non-binary rows are recorded with `scoring_support = 'unsupported'` and remain `pending` forever unless a future scorer ships. See [`scoring.md`](./docs/architecture/scoring.md).

#### `forecast_outcomes`
- `id`, `forecast_id`, `outcome_label`, `probability`, `lower_bound`, `upper_bound`
- One row per forecast outcome. Binary forecasts have exactly two rows whose `probability` values sum to 1.0 within `1e-6` tolerance.

#### `forecast_scores`
- `id`, `forecast_id`, `outcome_id`, `metric` (`brier_binary` in MVP), `score`, `scored_at`, `actor_id`, `metadata_json`
- Immutable score event table. `score = NULL` with `metadata_json.failure_reason` on `scoring_state = 'failed'`.

#### `decisions`
- `id`, `instrument_id`, `thesis_id`, `forecast_id`, `snapshot_id`
- `type` (`watch`, `skip`, `paper_enter`, `paper_exit`, `actual_enter`, `actual_exit`, `add`, `reduce`, `hold`, `invalidate_thesis`, `update_thesis`, `resolved`, `review`)
- `side`, `quantity`, `price`, `fees`, `slippage`, `reason`
- `playbook_version_id`, `review_by`, `created_at`, `actor_id`
- Tags live in `decision_tags`; playbook rule adherence lives in `decision_playbook_rules`.
- The `actual_enter`, `actual_exit`, `add`, and `reduce` decision types are **journal records only**. They record trades the agent placed elsewhere; they never trigger orders, writes to external systems, or any execution path inside Trade Trace.

#### `decision_tags`
- `decision_id`, `tag`

#### `decision_playbook_rules`
- `id`, `decision_id`, `playbook_version_id`, `rule_node_id`
- `status` (`considered`, `followed`, `overridden`, `not_applicable`)
- `reason`, `created_at`, `actor_id`
- Normalized adherence tracking. One row per (decision, rule) pair the agent evaluated. Supports `report.playbook_adherence` directly without JSON parsing.

#### `position_events`
- `id`, `position_id`, `instrument_id`, `decision_id`, `event_type`, `quantity_delta`, `price`, `fees`, `slippage`, `created_at`, `actor_id`
- Source of truth for position history.

#### `positions`
- `id`, `instrument_id`, `kind`, `side`, `status`, `opened_at`, `closed_at`, `resolved_at`, `realized_pnl`, `unrealized_pnl`, `avg_entry_price`, `updated_at`
- Rebuildable projection from `position_events` and marks.

#### `outcomes`
- `id`, `instrument_id`, `resolved_at`, `outcome_label`, `outcome_value`
- `status` (`resolved_final`, `resolved_provisional`, `ambiguous`, `disputed`, `void`, `cancelled`) — see [`scoring.md`](./docs/architecture/scoring.md) §5.
- `source`, `confidence`, `metadata_json`, `created_at`, `actor_id`
- Append-only. Corrections produce new rows; older rows stay readable. Auto-scoring fires only when `status = 'resolved_final'`.

#### `sources`
- `id`, `kind`, `ref`, `title`, `note`, `stance` (`supports`, `contradicts`, `neutral`), `freshness_at`, `content_hash`, `captured_at`, `created_at`, `actor_id`
- Attached to theses, decisions, forecasts, and memory nodes through edges.

#### `reviews`
- `id`, `target_kind`, `target_id`, `classification`, `body`, `next_rule_suggestion`, `created_at`, `actor_id`
- Tags live in `review_tags`.

#### `review_tags`
- `review_id`, `tag`, `tag_kind` (`mistake`, `strength`, `neutral`)

#### `playbooks` / `playbook_versions`
- `playbooks`: `id`, `name`, `description`, `created_at`, `actor_id`
- `playbook_versions`: `id`, `playbook_id`, `version`, `parent_version_id`, `created_at`, `actor_id`, `provenance_reflection_node_id`

#### `events`
- `id`, `event_type`, `subject_kind`, `subject_id`, `payload_json`, `actor_id`, `idempotency_key`, `request_id`, `created_at`
- Append-only event log. One row per committed write. Unique on `(event_type, actor_id, idempotency_key)` when the key is present. Full schema and idempotency semantics in [`persistence.md`](./docs/architecture/persistence.md).

#### `outbox`
- `id`, `event_id`, `export_kind`, `state` (`pending`, `exported`, `failed`), `exported_at`, `error_text`, `attempt_count`
- Drives optional JSONL export from the event log without dual writes.

### 3.2 Memory graph

#### `memory_nodes`
- `id`, `node_type` (`observation`, `reflection`, `semantic_claim`, `playbook_rule`, `coach_signal`)
- `version`, `parent_node_id`, `title`, `body`, `meta_json`, `confidence_base`, `decay_rate_per_day`, `embedding_ref`, `created_at`, `actor_id`
- Immutable. Updates create new nodes.

#### `memory_node_stats`
- `memory_node_id`, `recall_count`, `last_recalled_at`, `updated_at`
- Rebuildable/projection-style recall telemetry.

#### `edges`
- `id`, `source_kind`, `source_id`, `target_kind`, `target_id`, `edge_type`, `weight`, `created_at`, `actor_id`
- Allowed endpoint kinds: `memory_node`, `decision`, `thesis`, `position`, `forecast`, `outcome`, `snapshot`, `review`, `playbook_version`, `source`, `instrument`, `venue`.
- Edge types: `supports`, `contradicts`, `supersedes`, `links`, `derived_from`, `about`, `violates`, `follows`, `retracts`, `tombstones`.
- Endpoint IDs are validated before insertion.

## 4. APIs and tools

### 4.1 Memory

- `memory.retain` writes observation, semantic claim, reflection, playbook rule, or coach signal nodes.
- `memory.recall` retrieves by FTS5, graph, temporal, and optionally vector similarity when `sqlite-vec` and embeddings are configured. Accepts `max_chars`, `compact`, `include_body`, and `include_provenance` parameters to fit results within the caller's context budget. Full contract in [`memory-layer.md`](./docs/architecture/memory-layer.md) §4.
- `memory.reflect` is sugar over `retain(node_type=reflection)` and creates `about`/provenance edges.

### 4.2 Reports and coach

Deterministic reports:

- `report.calibration` — MVP binary Brier and reliability buckets for scored binary forecasts
- `report.mistakes` / `report.strengths` — tag counts and co-occurrence
- `report.pnl` — basic paper/actual projections where enough data exists
- `report.watchlist` and `watch.stale` — lazy stale-watch detection
- `report.unscored_forecasts` — lazy time-passed unscored detection
- `report.playbook_adherence` — driven by `decision_playbook_rules`; surfaces considered/followed/overridden/not_applicable counts and override outcomes
- `report.decision_velocity`

`report.coach` aggregates objective signals into a structured packet. It does not call an LLM and does not provide trading advice.

Trading-native reports (forecast-vs-market edge, calibration-by-liquidity-bucket, skipped-positive-edge review) are deferred to P1. The data is already captured in `snapshots`; the reports are additive.

### 4.3 Playbooks

- `playbook.create`, `playbook.list`, `playbook.show`
- `playbook.propose_version`, `playbook.list_versions`
- `playbook.adherence` — convenience wrapper around `report.playbook_adherence` scoped to a single playbook

MVP captures the active playbook version and normalized adherence records on every decision. Machine-checkable predicates may be added for specific rule types later.

### 4.4 Resolution

- `resolve.pending` — returns forecasts past their `resolution_at` without an `outcomes` row, or with an outcome row whose `status != 'resolved_final'`. Idempotent read; supports filters by instrument/venue/asset_class/time-window.
- `resolve.record` — writes an `outcomes` row with the required `status`, optionally attaches evidence via `source.attach_to_*`, and triggers auto-scoring when `status = 'resolved_final'` and the forecast is scoring-supported.

These tools exist because outcomes lag decisions: the agent session that resolves a forecast is usually not the same session that made the decision.

### 4.5 Sources

- `source.add` — creates a `sources` row.
- `source.attach_to_thesis`, `source.attach_to_decision`, `source.attach_to_forecast`, `source.attach_to_memory_node` — create `about`/`supports`/`contradicts` edges from a source to the target, depending on the source's `stance`.

Evidence capture is first-class in MVP because reflection quality depends on it: "did I overweight a weak source", "did I miss the resolution criteria", "did I rely on stale news" are answerable only if sources were captured at decision time.

## 5. Storage

- Primary store: SQLite at `$TRADE_TRACE_HOME/trade-trace.sqlite`, WAL mode, single-writer assumption for MVP.
- Required recall: SQLite FTS5 + graph + temporal queries.
- Optional vector recall: `sqlite-vec` if installed and verified at `journal.init`/`journal.status`.
- Event/outbox tables record committed writes for audit/export. JSONL export is generated from the outbox; see [`persistence.md`](./docs/architecture/persistence.md).
- Migrations are versioned and preserve data.
- File permissions default to user-only where supported.

## 6. Output contract

- CLI stdout is JSON only by default; list streams use NDJSON.
- `--human` may add prose to stderr only.
- MCP uses normal MCP framing and may stream according to transport capabilities.
- CLI and MCP must be schema/semantic equivalents after transport normalization, not byte-level twins.
- Success and error envelopes have the shapes defined in [`contracts.md`](./docs/architecture/contracts.md). Stable error codes: `VALIDATION_ERROR`, `NOT_FOUND`, `IDEMPOTENCY_CONFLICT`, `UNSUPPORTED_CAPABILITY`, `STORAGE_ERROR`, `SCORING_UNSUPPORTED`, `SCORING_NOT_READY`, `INVARIANT_VIOLATION`, `MARKET_NOT_RESOLVED`, `MARKET_AMBIGUOUS`, `RATE_LIMITED`.

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
- SQLite + FTS5 baseline; optional `sqlite-vec` detection
- Initial docs

### M1 — Manual ledger core + CLI/MCP frames
- Tables for venues, instruments, snapshots, theses, forecasts, decisions, outcomes, sources, tags, events, outbox, and write metadata
- `journal.init`, `journal.status`, `journal.schema`, JSONL export drain
- Manual end-to-end write path: instrument → snapshot → thesis → binary forecast → decision → outcome
- Idempotency contract and result/error envelope per [`contracts.md`](./docs/architecture/contracts.md) and [`persistence.md`](./docs/architecture/persistence.md)
- `source.add`, `source.attach_to_*`
- `resolve.pending`, `resolve.record`

### M2 — Binary scoring and deterministic reports
- `forecast_scores` binary Brier on supported outcome writes (single-probability form per [`scoring.md`](./docs/architecture/scoring.md))
- Calibration, watchlist, unscored forecast, tag, decision velocity, and basic P&L reports
- Lazy coach-signal generation in reports/explicit scans

### M3 — Memory layer and recall
- `memory_nodes`, `memory_node_stats`, `edges`
- `memory.retain`, `memory.reflect`, `memory.recall` with budget params (`max_chars`, `compact`, `include_body`, `include_provenance`)
- FTS5 + graph + temporal recall; optional vector recall if configured

### M4 — Playbook loop
- Playbooks, versions, playbook rule nodes
- Normalized `decision_playbook_rules` adherence tracking
- `report.coach` and `report.playbook_adherence`
- Playbook version update with reflection provenance

### P1
- CSV import
- Multi-class/categorical scoring and ranked probability score
- Scalar/distribution schema including `distribution_json`
- Trading-native reports: forecast-vs-market edge, calibration-by-liquidity-bucket, skipped-positive-edge review
- ForecastBench schema verification and compatible export if feasible
- HTTP/SSE transport, re-embedding tools
- Subscribe API on the event log

### P2
- Optional sync/backup
- Optional static/read-only inspection export/viewer, not a product dashboard
- Historical/replay hooks
- Multi-agent concurrency improvements

## 9. Testing and verification

- `journal.init` is idempotent.
- Every tool has a JSON schema.
- Every write carries `actor_id`/actor metadata; retryable writes accept `idempotency_key` and replay-safely.
- CLI and MCP outputs are semantically equivalent after transport normalization (verified by the golden-test suite in [`contracts.md`](./docs/architecture/contracts.md) §7).
- Append-only invariants hold for source/event tables.
- `positions` and `memory_node_stats` can be rebuilt from source data via `journal.rebuild_projections`.
- Binary Brier scores match reference calculations using the single-probability form.
- Binary forecast invariants hold: exactly two outcomes, probabilities in `[0,1]`, sum to `1.0` within `1e-6`, distinct labels.
- Auto-scoring is blocked when the linked `outcomes.status != 'resolved_final'`.
- An `IDEMPOTENCY_CONFLICT` is raised only on semantically incompatible payload reuse; pure replay succeeds and reports `meta.idempotent_replay: true`.
- Time-passing signals are generated lazily by reports or explicit scan, not by a hidden daemon.
- Security tests ensure credentials are not accepted through CLI/MCP args and are not logged.

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

10. At least one report identifies a recurring error or strength pattern that the agent did not call out in advance.
11. At least one `memory.recall` result is explicitly cited in a later thesis, traceable via a `derived_from` or `supports` edge.
12. At least one playbook rule changes a later decision: either followed (`decision_playbook_rules.status = 'followed'`) or overridden (`status = 'overridden'`) with the outcome captured.
13. At least one ambiguous-resolution case is handled correctly: the outcome row carries `status ∈ ('ambiguous', 'disputed', 'resolved_provisional')` and the forecast remains in `scoring_state = 'pending'` until a `resolved_final` outcome supersedes it.
14. The calibration report explicitly states sample size; 5 resolved forecasts is enough for plumbing but not enough for serious calibration, and reports must say so when the sample is small.

Validation question: does Trade Trace make the LLM trader auditable, calibratable, and improvable over time?

## 11. Remaining open questions

1. Re-embedding policy when an embedding model changes: likely P1 lazy re-embed, see [`memory-layer.md`](./docs/architecture/memory-layer.md) §8.
2. Concurrency: SQLite WAL with single-writer assumption for MVP; stronger multi-agent concurrency later. See [`persistence.md`](./docs/architecture/persistence.md) §9.
3. Exact ForecastBench export shape: verify against the current schema before promising compatibility.
4. Surfacing "the agent did not already know this" for the §10.2 usefulness criterion: requires the agent to explicitly flag pre-existing knowledge on thesis write, or the report to compare against the agent's prior memory recall results. Likely a small extension to `report.coach` in P1.
