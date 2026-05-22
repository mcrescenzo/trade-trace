# Agent Continuity Entity Contracts

> Status: **shipped** foundation contract for the agent-continuity roadmap. This document is deliberately JSON/CLI/MCP-first and agent-only; it is not a human dashboard spec.

## Purpose

Trade Trace is evolving from a passive local journal into a continuity substrate for stateless LLM trading agents. A cron-triggered agent needs to reconstruct what it previously believed, why it acted or did not act, which strategy or playbook governed the choice, what outcomes followed, and which memories/reports it relied on.

This contract defines the canonical source of truth and invariants for the entities future roadmap work may extend. It consolidates the research decisions in:

- `docs/research/agentic-trade-trace/decisions/ranked-product-direction.md` §§4-5
- `docs/research/agentic-trade-trace/synthesis/foundational-continuity.md`
- `docs/research/agentic-trade-trace/synthesis/agent-decision-control-surface.md`
- `docs/research/agentic-trade-trace/synthesis/evaluation-learning-architecture.md`
- `docs/research/agentic-trade-trace/concepts/agent-run-session-identity.md`
- `docs/research/agentic-trade-trace/concepts/recall-receipts.md`
- `docs/research/agentic-trade-trace/concepts/decision-non-action-lifecycle.md`
- `docs/research/agentic-trade-trace/concepts/strategy-state-lifecycle.md`
- `docs/research/agentic-trade-trace/concepts/replay-regression-evaluation-substrate.md`
- [`replay-case-bundles.md`](replay-case-bundles.md)

## Non-negotiable product boundaries

All future entities and tools must preserve these boundaries:

- **Agent-only**: optimized for CLI, MCP, deterministic JSON envelopes, schemas, and receipts. No human dashboard dependency.
- **Local-first**: one local SQLite journal remains the source of truth. No required hosted service.
- **Caller-supplied data only**: Trade Trace stores and evaluates data supplied by the caller; it does not fetch market prices, broker state, outcomes, or research by default.
- **No execution or custody**: no broker, wallet, order placement, signing, or execution paths.
- **No financial advice**: reports and bootstrap packets may summarize local journal evidence and caveats; they must not recommend buys/sells, rank live trades as advice, or claim profit proof.
- **No generic scheduler/rule engine/backtester drift**: scheduling belongs to the calling agent/orchestrator; rules are local playbook memory; replay is for deterministic regression/evaluation, not predictive backtesting.
- **Append-only by default**: source-of-truth facts are corrected by new rows and `supersedes`/related edges, not in-place mutation. Rebuildable projections may be mutable.

## Common provenance fields

The canonical run/session fields are:

| Field | Meaning | Semantics |
|---|---|---|
| `actor_id` | Transport/user identity that initiated the call | Required on writes; derived from CLI/MCP context. |
| `agent_id` | Logical trading-agent identity | Optional reporting/filter dimension. Does not imply credentials or authority. |
| `model_id` | LLM/model family/version used by the logical agent | Optional reporting/filter dimension. |
| `environment` | Local operating context (`paper`, `actual_recorded`, `simulation`, `backtest_import`, `manual_review`) | Optional reporting/filter dimension. `backtest_import` means imported historical records, not a built-in backtester. |
| `run_id` | Caller-supplied run/session identifier | Optional reporting/filter dimension for cron/session continuity. No runtime manager is implied. |
| `request_id` | Per-call envelope/event trace identifier | Transport/request tracing, not a durable strategy/session identity. |
| `idempotency_key` | Caller-supplied replay key for write calls | Prevents duplicate local writes where supported; scoped by tool/event and actor. |

Nullable provenance fields are explicit: missing means the caller did not provide the dimension, not that Trade Trace inferred it.

## Entity/invariant matrix

| Entity | Source of truth | Mutable status | Lifecycle states | Provenance | Idempotency | Direct write vs derived-only | Downstream consumers |
|---|---|---|---|---|---|---|---|
| `AgentRun` / run metadata | No standalone table in Epic A; fields on records/events and report filters | Not an entity row; values are caller-supplied labels | `run_id` appears on writes/recall events; absence is valid | `actor_id`, `agent_id`, `model_id`, `environment`, `run_id`, `request_id` where applicable | Write tools use existing per-tool idempotency where supported | Direct metadata on rows only; no scheduler/process manager | `report.calibration`, `report.compare`, future `agent.bootstrap`, replay case selection, audit/debug receipts |
| `Decision` | `decisions` table + `decision_tags` + position projection side effects | Append-only row; corrections via new decision or superseding edge/related row | `type` enum: watch, skip, paper/actual enter/exit, add/reduce/hold, invalidate/update/review/resolved | Full common segmentation fields plus `actor_id`; linked `snapshot_id`, `thesis_id`, `forecast_id`, `strategy_id`, `playbook_version_id` | `idempotency_key` supported by `decision.add` | Direct write by `decision.add`; position rows are projections derived from decisions | Reports, strategy performance, playbook adherence, bootstrap packets, replay cases, reflection prompts |
| `NonAction` | A `decisions` row with `type='skip'`, `watch`, or other non-executing decision types | Append-only | Same decision lifecycle; important non-actions should carry reason/tags/strategy/forecast context | Same as Decision | Same as Decision | Direct write through `decision.add`; no separate table in Epic A | Calibration of skipped ideas, opportunity/mistake reports, bootstrap unresolved work, strategy diagnostics |
| `Forecast` | `forecasts` + `forecast_outcomes` + `forecast_scores` | Forecast row append-only; score rows append-only; logical state derived when needed | `kind` may be binary/categorical/scalar; MVP scoring support is binary-first. `scoring_state` is derived/persisted as current schema allows (`pending`, `scored`, `failed`, `superseded`) | Full common segmentation fields plus `actor_id`; usually inherited from thesis/decision only if caller supplies matching metadata | `forecast.add` / supersede paths use write idempotency where supported | Direct write for forecast/outcome probabilities; scores are derived from outcomes | Calibration, compare, strategy diagnostics, bootstrap unresolved/resolved ideas, replay evaluation |
| `Outcome` | `outcomes` + scoring side effects | Append-only; correction by superseding outcome edge/new row | `status`: `resolved_final`, `resolved_provisional`, `ambiguous`, `disputed`, `void`, `cancelled` | Full common segmentation fields plus `actor_id`; source/evidence fields are caller-supplied | `outcome.add` idempotency where supplied | Direct write by caller; Trade Trace never fetches outcomes | Scoring, calibration, outcome hygiene, review bundles, replay labels |
| `Strategy` | `strategies` table; row references from theses/decisions/memory edges | Soft-mutable for description/hypothesis/status; no delete; archived strategies remain FK targets | `active`, `archived`; list accepts active/archived/both/all | `actor_id` on row; downstream records carry run/session fields | Create/update support idempotency where supplied | Direct strategy row writes; performance diagnostics are derived reports | `strategy.list/show/update`, strategy performance reports, bootstrap strategy context, memory scoping |
| `MemoryNode` | `memory_nodes` + `edges` + optional `memory_node_embeddings` | Append-only node; supersession by new node/edge; projections rebuildable | `node_type`: `observation`, `reflection`, `playbook_rule`; validity via `valid_from`, `valid_to`, `invalidated_at`, `invalidated_by` | Full common segmentation fields plus `actor_id` | `memory.retain`/reflection paths use write idempotency where supplied | Direct write for authored memory/reflection/rules; embeddings/stats are derived or opt-in | `memory.recall`, bootstrap memory section, playbook/rule evolution, replay context |
| `RecallReceipt` | `memory_recall_events` today; roadmap may expose richer receipt objects | Append-only | One event per recall call with query, strategies, node IDs, context, as_of | Full common segmentation fields plus `actor_id`; `recall_id` is receipt identity | Recall is read-oriented but logs a receipt event for audit | Derived from `memory.recall`; callers do not edit receipts | Bootstrap provenance, replay/regression, audit of why an agent saw specific memories |
| `DerivedWorkItem` | Future local table/packet section; no generic task manager in Epic A | Append-only or status-transitioned only when implemented | Proposed states: open/claimed/done/stale/quarantined; exact states deferred to work-queue epic | Must carry common provenance and source record references | Must require idempotent creation/update keys when implemented | Derived from local journal signals/reports; direct writes only for local acceptance/claiming if scoped | `agent.bootstrap`, follow-up queues, unresolved outcome/forecast/review prompts |
| `PlaybookRule` | `memory_nodes.node_type='playbook_rule'` plus `playbooks`/`playbook_versions` | Append-only/superseded by versioned rule nodes | Active through playbook version; superseded by new version/rule | MemoryNode provenance plus playbook/version IDs in metadata/edges | Rule/version proposal writes use idempotency where supplied | Direct rule/version proposal writes; adherence diagnostics derived | Playbook adherence, decision constraints, bootstrap rules, strategy refinement |
| `PlaybookAdherence` | `decision_playbook_rules` / adherence write surface | Append-only evidence row linking decision to rule/version | `followed`, `violated`, `not_applicable`, `unknown` as implemented by adherence contract | `actor_id`; decision/rule/version rows carry their own run metadata | `decision.record_adherence` uses idempotency | Direct record of a decision-rule relationship; aggregate reports are derived | Playbook adherence reports, strategy diagnostics, bootstrap caveats |
| `ReplayCase` | Future local replay-case artifact/table; not present in Epic A | Append-only case definitions; results append-only | Proposed states: captured, runnable, run_complete, quarantined; exact states deferred to replay epic | Must cite source record IDs, recall receipts, agent/model/run metadata | Must be idempotent by source selection/case ID | Derived from local records and receipts; no market fetch/backtest engine | Regression evaluation, bootstrap packet validation, reflection quarantine |

Current shipped continuity projections for the work-queue precursor are
`report.lifecycle`, `report.work_queue`, and `agent.next_actions`. They
are derived/read-only over local rows and cite `source_refs`,
`allowed_actions`, `forbidden_actions`, `closure_condition`, and caveats
where applicable. They do not implement `DerivedWorkItem` persistence,
claiming, assignment, notification, scheduling, human dashboard workflow,
fetching, execution, broker/wallet state, or financial advice.

## Implementation rules for future roadmap work

1. New write paths must accept `agent_id`, `model_id`, `environment`, and `run_id` only when they persist or explicitly reject them. Silent discard is not allowed.
2. Read/report tools must reject unsupported non-empty filters instead of echoing filters they did not apply.
3. Bootstrap/replay outputs must cite record IDs and recall IDs; summaries without receipts are not enough for agent-continuity claims.
4. Reflection-derived behavior changes must pass through quarantine/review states before becoming active playbook rules.
5. Any new network-capable path must be explicit opt-in, documented, and covered by no-network/default-off tests. No roadmap feature may require it.

## Bootstrap packet v0 contract (`agent.bootstrap` / `report.bootstrap`)

> Status: **contract precursor** for Epic B. This section defines the deterministic JSON shape that future `agent.bootstrap` and any alias/transport surface named `report.bootstrap` must implement. It does not authorize runtime composition, scheduling, persistence, fetching, execution, or advice generation.

### Intent and boundaries

The bootstrap packet is a read-oriented session-start packet for a fresh/stateless agent. It assembles local journal state, memory context, provenance, caveats, and process obligations so the agent can decide what to inspect before writing new theses, decisions, outcomes, or reflections.

Non-negotiable constraints for the packet and its tool handlers:

- **Read-only synthesis**: generating the packet must not create trades, orders, tasks, alerts, playbook rules, outcomes, decisions, forecasts, sources, or scheduler state. If the implementation uses `memory.recall` in a mode that appends recall telemetry, that local recall side effect must be explicitly reported in `metadata.side_effects` and `memory_context.recall_receipts`.
- **Caller-supplied data only**: the packet may summarize rows and reports already stored in the local journal. It must not fetch market prices, broker state, web pages, research, filings, news, or outcome truth.
- **No execution or custody**: process suggestions must never place, route, sign, or prepare orders.
- **No financial advice**: sections may rank by process urgency, due time, staleness, or retrieval relevance. They must not recommend buying, selling, holding, sizing, or entering/exiting an instrument as advice.
- **No scheduler drift**: due work and suggested calls are obligations for the caller/orchestrator to consider; Trade Trace does not launch cron jobs, reserve work, page humans, or retry tasks.
- **Deterministic for fixed inputs**: for a fixed database, `as_of`, filters, and budgets, packet content and ordering must be stable except for documented recall telemetry IDs/timestamps if recall persistence is enabled.

### Request contract

Future CLI/MCP schemas must use one canonical request shape for `agent.bootstrap` and `report.bootstrap`:

```json
{
  "as_of": "2026-05-22T00:00:00Z",
  "filter": {
    "actor_id": "local-agent",
    "agent_id": "cron-agent-a",
    "model_id": "model-family-or-version",
    "environment": "paper",
    "run_id": "run-2026-05-22-0001",
    "strategy_ids": ["strat_123"],
    "symbols": ["BTC-USD"],
    "tags": ["breakout"],
    "since": "2026-04-22T00:00:00Z",
    "until": "2026-05-22T00:00:00Z"
  },
  "sections": [
    "current_scope",
    "obligations",
    "active_ideas",
    "strategy_context",
    "memory_context",
    "caveats",
    "suggested_process_calls"
  ],
  "budgets": {
    "max_chars_total": 24000,
    "default_max_items_per_section": 10,
    "default_max_chars_per_section": 4000,
    "sections": {
      "obligations": {"max_items": 20, "max_chars": 6000},
      "memory_context": {"max_items": 12, "max_chars": 5000}
    },
    "include_memory_body": false,
    "include_sensitive_sources": false
  }
}
```

Request semantics:

- `as_of` is the deterministic read boundary. If omitted, the implementation may use current time but must echo the resolved value in `metadata.as_of`.
- `filter` mirrors report-filter provenance dimensions plus bootstrap-specific local selectors. Unsupported non-empty filters must be rejected with a validation error, not silently ignored.
- Missing nullable provenance fields mean “caller did not scope by this field.” The response must surface the broadening in `current_scope.missing_scope_fields` and `caveats.scope_caveats`.
- `sections` is optional. If supplied, omitted optional sections must appear in `omitted_counts` with reason `section_not_requested` so consumers can distinguish “not requested” from “empty.” Required metadata, filters, budgets/truncation, caveats, and hard constraints are always returned.
- Budget values are hard upper bounds on returned summaries. Implementations may enforce lower internal safety caps but must report effective limits.
- `include_memory_body=false` means memory rows should expose IDs, node types, validity/confidence/importance fields, and compact summaries/snippets, not full unbounded bodies.
- `include_sensitive_sources=false` means sensitive or redacted source content stays excluded; IDs and redaction caveats may still be reported when safe.

### Response envelope and stable top-level fields

`agent.bootstrap` / `report.bootstrap` must return the normal success envelope. The `data` object has stable top-level fields in this order:

```json
{
  "kind": "agent.bootstrap",
  "contract_version": "bootstrap.v0",
  "metadata": {},
  "filter": {},
  "budgets": {},
  "truncation": {},
  "omitted_counts": {},
  "current_scope": {},
  "obligations": [],
  "active_ideas": {},
  "strategy_context": {},
  "memory_context": {},
  "caveats": {},
  "suggested_process_calls": [],
  "hard_constraints": {}
}
```

Aliases must not fork the contract: `report.bootstrap` may set `kind` to `report.bootstrap` only if an explicit alias policy is documented in tool metadata; otherwise both surfaces should return `kind="agent.bootstrap"` with identical `data` semantics.

### Field contracts

#### `metadata`

Required fields:

- `packet_id`: deterministic content identifier when practical, or a locally unique request identifier if recall side effects make a content hash impractical. It is not a source-of-truth row ID unless future work adds a receipt table.
- `generated_at`: timestamp when the packet was assembled.
- `as_of`: read boundary used by all sections.
- `contract_version`: duplicate of the top-level version for clients that persist sub-objects.
- `source_tools`: ordered list of local tools/reports/queries used to compose the packet, for example `strategy.list`, `report.current_exposure`, `report.watchlist`, `resolve.pending`, `memory.recall`, and source-quality reports.
- `side_effects`: array of local side effects, normally empty. If recall telemetry was written, include `{ "kind": "memory_recall_event", "recall_id": "..." }` entries.
- `determinism`: object with `stable_ordering=true`, the ranking keys used, and any documented nondeterministic component.

#### `filter`

Echo the resolved, actually applied filter:

- `requested`: the caller-supplied filter after schema normalization.
- `applied`: filters that were actually pushed into local reads/reports.
- `unsupported_rejected`: filters rejected before execution; successful responses normally use an empty array.
- `broadening`: fields omitted by the caller that caused a wider local read, with caveat codes such as `missing_agent_id`, `missing_run_id`, or `missing_strategy_id`.

#### `budgets` and `truncation`

`budgets` echoes effective limits:

- `max_chars_total`
- `default_max_items_per_section`
- `default_max_chars_per_section`
- `sections`: per-section `max_items` and `max_chars`
- `include_memory_body`
- `include_sensitive_sources`

`truncation` reports whether absence can be trusted:

```json
{
  "is_partial": true,
  "policy": "stable_priority_then_time_then_id",
  "total_chars_returned": 18320,
  "sections": {
    "obligations": {
      "is_partial": true,
      "returned_count": 20,
      "available_count": 37,
      "omitted_count": 17,
      "reason": "max_items",
      "next_cursor": null
    }
  }
}
```

Truncation rules:

- Each section orders candidates by documented stable keys, then applies `max_items`, then `max_chars`. Ties must break by stable source kind and source ID.
- Obligations are ordered by process urgency: overdue/due forecasts, overdue reviews, source/evidence hygiene blockers, projection anomalies, missing adherence/reflection, then lower-urgency stale items; never by trade attractiveness.
- Active ideas are grouped by lifecycle bucket before recency: open/current exposure, watches, unresolved forecasts, skips/holds/reviews with open follow-up, and recently resolved items needing reflection.
- Memory context is ordered by retrieval rank/importance, validity, and source ID. Invalidated/superseded memories may appear only when directly relevant and must carry caveats.
- When either a section or the whole packet hits a budget, set `is_partial=true`; absence of an item is not evidence that no such item exists.
- `available_count` is preferred. If exact counts are too expensive or unavailable for a section, return `available_count=null`, `omitted_count=null`, and a caveat code `count_unavailable`; do not invent counts.

#### `omitted_counts`

This object summarizes non-returned material by section and reason:

```json
{
  "obligations": {"max_items": 17, "max_chars": 0, "section_not_requested": 0, "redacted_or_sensitive": 0},
  "memory_context": {"max_items": 4, "max_chars": 2, "invalidated": 0, "section_not_requested": 0},
  "caveats": {"redacted_or_sensitive": 3}
}
```

Reasons are stable strings: `max_items`, `max_chars`, `max_total_chars`, `section_not_requested`, `redacted_or_sensitive`, `unsupported_source_type`, `count_unavailable`, `not_applicable`, and implementation-specific extensions prefixed by `x_`.

#### `current_scope`

Required fields:

- `identity`: echoed `actor_id`, `agent_id`, `model_id`, `environment`, and `run_id` values or `null` when missing.
- `time_window`: `as_of`, `since`, `until`, and any derived staleness thresholds.
- `selectors`: strategy IDs, symbols/instruments, tags, and other local selectors.
- `missing_scope_fields`: nullable provenance fields the caller did not provide.
- `scope_caveat_codes`: machine-readable caveats for broad reads or mixed contexts.

#### `obligations`

Array of process work items synthesized from local state. Each item uses:

```json
{
  "obligation_id": "derived:forecast:fc_123:due_resolution",
  "kind": "due_forecast_resolution",
  "urgency": "overdue",
  "due_at": "2026-05-21T00:00:00Z",
  "summary": "Forecast is past resolution_at and lacks a final outcome.",
  "source_refs": [{"kind": "forecast", "id": "fc_123"}],
  "evidence_refs": [{"kind": "source", "id": "src_456"}],
  "caveat_codes": ["requires_caller_supplied_outcome", "no_fetch_performed"],
  "suggested_process_call_ids": ["call_001"]
}
```

Allowed obligation kinds include due/overdue forecast resolution, stale watch review, missing or stale source evidence, source redaction/sensitivity review, current-exposure projection anomaly review, missing playbook adherence, missing post-outcome reflection, memory supersession/invalidation review, and strategy hygiene review. Obligations are not durable tasks unless a future work-queue contract says otherwise.

#### `active_ideas`

Object with stable buckets:

- `current_exposure`: open/partial position projection summaries using the current-exposure contract's bucket and caveat names. Watch ideas and record-only actual decisions must not appear here.
- `watches`: active watch decisions with `review_by`, stale/overdue flags, thesis/forecast/source/strategy refs, and compact reason snippets.
- `unresolved_forecasts`: pending forecasts, especially past `resolution_at`, with resolution rule text snippets, scoring support/state, and related source/outcome caveats.
- `non_actions_and_reviews`: skips, holds, reviews, invalidations, or updates that still have follow-up obligations.
- `recently_resolved_needing_learning`: resolved outcomes/forecasts that have missing reflection, adherence, or source-quality follow-up.

Every row-level item must carry `source_refs` with `{kind, id}` pairs and may include `summary`, `timestamps`, `strategy_refs`, `forecast_refs`, `decision_refs`, `source_refs`, `caveat_codes`, and `drilldown_tool`.

#### `strategy_context`

Required object with:

- `active_strategies`: active strategy IDs/slugs/status/hypothesis snippets in scope.
- `relevant_archived_strategies`: archived strategies only when referenced by unresolved work, memories, or active ideas.
- `playbook_state`: active playbook/version IDs, relevant playbook-rule memory node refs, and recent adherence/override diagnostics.
- `strategy_caveats`: low sample warnings, mixed-scope warnings, stale strategy descriptions, missing adherence, and recently changed rule caveats.

#### `memory_context`

Required object even when memory is disabled or not requested:

- `included`: boolean.
- `recall_queries`: fixed or caller-supplied query descriptors actually used.
- `memory_nodes`: bounded returned nodes with `node_id`, `node_type`, `summary`/`body` according to budget flags, validity window, confidence, importance, supersession/invalidated status, target refs, and source refs.
- `recall_receipts`: recall IDs/events with query/context, returned node IDs, ranking/truncation metadata, and whether telemetry was persisted.
- `omitted_memory`: counts/reasons for nodes omitted by budget, invalidation, sensitivity, or section selection.
- `memory_caveats`: caveat codes such as `recall_not_run`, `recall_telemetry_persisted`, `memory_body_omitted`, `superseded_memory_included`, or `low_confidence_memory`.

#### `caveats`

Required object with machine-readable caveat arrays:

- `hard_boundary_caveats`: always include `no_market_data_fetch`, `no_broker_verification`, `no_trade_execution`, `no_financial_advice`, and `caller_supplied_data_only`.
- `scope_caveats`: missing or broad scope dimensions.
- `evidence_caveats`: missing/stale/contradictory/redacted/sensitive source indicators and `no_fetch_performed`.
- `data_quality_caveats`: projection anomalies, unsupported forecast scoring, low samples, ambiguous/disputed/void outcomes, count-unavailable warnings.
- `memory_caveats`: recall and memory validity warnings.
- `truncation_caveats`: packet/section partial-output warnings.

Each caveat may be a string code or object. Object form must include `code`, `severity` (`info`, `warn`, `blocker`), `message`, and optional `source_refs`.

#### `suggested_process_calls`

Array of possible next local tool calls for the caller/orchestrator to choose from. They are process suggestions, not scheduled actions or trading recommendations:

```json
{
  "call_id": "call_001",
  "tool": "outcome.add",
  "reason": "Record a caller-supplied final/provisional outcome for an overdue forecast.",
  "preconditions": ["caller_has_external_outcome_evidence", "caller_accepts_source_caveats"],
  "args_template": {"forecast_id": "fc_123", "status": "resolved_final"},
  "source_refs": [{"kind": "forecast", "id": "fc_123"}],
  "caveat_codes": ["requires_caller_supplied_data", "not_trade_advice", "not_executed"]
}
```

Allowed suggestions include read/drilldown calls (`strategy.show`, reports, `memory.recall`) and local write calls that require caller-supplied evidence (`outcome.add`, `decision.add(type=review)`, `source.add`/attach, `memory.reflect`, adherence recording). Suggestions must not include market-data fetches, broker calls, order placement, or automatic scheduling.

#### `hard_constraints`

Required object for machine clients:

```json
{
  "no_financial_advice": true,
  "no_market_data_fetch": true,
  "no_broker_or_exchange_fetch": true,
  "no_trade_execution": true,
  "no_order_preparation": true,
  "no_scheduler_or_alert_creation": true,
  "caller_supplied_data_only": true,
  "local_read_synthesis_only": true
}
```

### Source/reference conventions

- Use `source_refs` for local Trade Trace records: `{ "kind": "decision|forecast|outcome|strategy|memory_node|recall_event|source|position|playbook_version|playbook_rule|report", "id": "..." }`.
- Use `evidence_refs` for caller-supplied sources/evidence rows.
- Use `drilldown_tool` when a client can fetch a richer local view by ID.
- Do not embed external source content beyond budgeted snippets and redaction policy. Stored URLs/paths are metadata, not proof that the external content is current or verified.

### Empty, omitted, and partial output semantics

- Empty arrays/objects mean the implementation looked within the applied scope and found no matching local rows, subject to caveats.
- Missing optional sections are not allowed in successful responses; return an empty section plus `omitted_counts.<section>.section_not_requested` or a section-level caveat.
- `truncation.is_partial=false` and a section `available_count=returned_count` are required before a caller may treat absence as meaningful within that section.
- Redacted/sensitive omissions must be counted where safe, without leaking secret values.
