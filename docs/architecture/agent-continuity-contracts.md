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

## Implementation rules for future roadmap work

1. New write paths must accept `agent_id`, `model_id`, `environment`, and `run_id` only when they persist or explicitly reject them. Silent discard is not allowed.
2. Read/report tools must reject unsupported non-empty filters instead of echoing filters they did not apply.
3. Bootstrap/replay outputs must cite record IDs and recall IDs; summaries without receipts are not enough for agent-continuity claims.
4. Reflection-derived behavior changes must pass through quarantine/review states before becoming active playbook rules.
5. Any new network-capable path must be explicit opt-in, documented, and covered by no-network/default-off tests. No roadmap feature may require it.
