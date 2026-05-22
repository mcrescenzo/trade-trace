# Concept Dossier: Agent Work Queue / Next Actions

## 1. Question

Should Trade Trace define an agent work queue / next-action surface for stateless trading agents, and should that surface be only a derived report over existing ledger/memory/report state or eventually include first-class durable work items?

## 2. Bottom Line

- Recommendation: adopt core as a **process-obligation surface**; defer first-class durable work items until dogfood proves derived obligations are insufficient.
- Confidence: medium-high.
- Why: The current system already exposes many obligation sources as deterministic reports or fields: forecasts past `resolution_at`, stale/overdue watches, source/audit-readiness gaps, missing reflections, missing playbook adherence, current exposure/open positions, strategies, playbooks, and recall/receipt inputs. Fresh-session agents need a single bounded “what work is due?” surface because obligations otherwise vanish between cron runs. However, Trade Trace should not become a scheduler, daemon, alerting system, generic task manager, or market-data/outcome fetcher. The safest product shape is a read-oriented next-action queue derived from recorded trading artifacts, with a later falsifier-driven option for durable acknowledgements/snoozes/owner state if derived reports cannot preserve agent continuity.

## 3. Agent-Specific Problem

Human traders have habits, calendars, broker screens, watchlists, and implicit memory. A stateless LLM trading agent has none of those unless the local substrate exposes them as data. Between runs, the agent can miss obligations such as:

- forecasts whose `resolution_at` has passed and require externally supplied outcomes;
- watches whose `review_by` deadline passed or whose age makes them stale;
- decisions or outcomes that need reflection before playbook/process learning is safe;
- playbook-scoped decisions with no adherence rows;
- thesis/decision/forecast/memory artifacts with missing, stale, contradictory, duplicated, or sensitive sources;
- strategy reviews after enough decisions/outcomes accumulate or after a strategy has gone dormant;
- playbook review after repeated overrides or negative/positive override outcomes;
- open/paper exposure or projection anomalies that should be inspected before new decisions;
- recall/use gaps where prior memories were retrieved but not linked or cited.

The problem is agent-specific because a fresh session cannot infer “what I promised to do next” from yesterday’s conversation. If due work is only implicit in scattered reports, the agent may form new theses before resolving old forecasts, reviewing stale watches, checking exposure, or reflecting on outcomes. Conversely, if Trade Trace stores arbitrary tasks, the product risks becoming a generic task manager rather than an agentic trading journal.

## 4. Current Baseline

Observed current capabilities and planning docs relevant to work queues:

- Research scope explicitly includes fresh-session continuity, durable tracking of theses/forecasts/decisions/non-actions/strategies/reflections/playbook rules/recall behavior, and machine-readable MCP/CLI/JSON-first abstractions; it excludes execution, market-data fetching, human dashboards, and implementation during this program (`docs/research/agentic-trade-trace/00-research-contract.md:20-38`).
- Phase 0 taxonomy classifies “Agent work queue / next actions” as core, but with a local/deterministic boundary: pending obligations are exposed as data; no daemon or external scheduler (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:37-49`, `121-129`, `140-151`).
- Foundational continuity synthesis names downstream open questions: whether next actions derived from reports/lifecycle state are enough, and where the boundary lies between due process work and scheduler behavior (`docs/research/agentic-trade-trace/synthesis/foundational-continuity.md:73-80`, `189-195`).
- The fresh-session bootstrap dossier expects a next-action section containing due forecasts, overdue watches, missing sources, stale sources, projection anomalies, playbook-adherence gaps, and review prompts; it explicitly says this should list work for an external cron-triggered agent, not schedule or execute it (`concepts/fresh-session-bootstrap-context-pack.md:61-75`, `153-170`).
- The decision/non-action lifecycle dossier identifies pending obligation state as derived from watches with `review_by`, unresolved forecasts, open/paper positions, stale watches, missing sources, missing adherence, and decisions without reflections (`concepts/decision-non-action-lifecycle.md:86-100`, `159-177`).
- `docs/PRD.md` defines forecasts with `resolution_at` and resolution rules, decisions with `review_by` for watch/review types, normalized `decision_playbook_rules`, positions/projections, sources, memory nodes/recall events, strategies, playbooks, and reports (`docs/PRD.md:175-238`, `240-268`, `302-340`, `364-420`, `422-433`).
- `resolve.pending` is documented as a deterministic read that returns forecasts past `resolution_at` without final outcomes; outcomes often lag decisions and are resolved in later sessions (`docs/PRD.md:408-413`).
- Implemented `report.watchlist` lists `watch` decisions and independently surfaces age-based `stale` status and deadline-based `overdue` flags from `review_by`; it returns record IDs and per-row examples (`src/trade_trace/reports/watchlist.py:1-13`, `50-101`).
- Implemented `report.unscored_forecasts` lists supported pending forecasts past `resolution_at` without a non-superseded `resolved_final` outcome (`src/trade_trace/reports/unscored.py:1-7`, `31-96`).
- Implemented coach hygiene samples watches without `review_by`, decisions without attached reflections, and playbook-scoped decisions missing adherence rows (`src/trade_trace/reports/coach.py:340-394`).
- Implemented source/audit reports surface missing sources, stale sources, contradictory sources, duplicated sources, sensitive sources, missing resolution-rule provenance, missing snapshots/microstructure, weak decision provenance, missing retrieval metadata, and missing agent metadata (`src/trade_trace/reports/source_quality.py:1-24`, `44-81`; `src/trade_trace/reports/audit_readiness.py:1-4`, `22-64`).
- `docs/architecture/reports.md` establishes a JSON `ReportFilter`, report envelopes with record IDs, sample warnings, truncation/cursor semantics, and deterministic no-advice report behavior (`docs/architecture/reports.md:26-31`, `33-122`, `124-229`).

Current gap: there is no single canonical “agent work queue” surface that merges these obligation signals, deduplicates them, ranks by process urgency, gives machine-actionable next tool-call hints, and reports whether each obligation is derived/transient versus durable/acknowledged. Existing reports are strong inputs, but an agent must know which reports to call and how to merge them.

## 5. Candidate Product Shape

The candidate concept is a **local, deterministic process-obligation queue** for agent use. It is not a scheduler, not a daemon, not an alert service, not a broker/order manager, and not a generic task manager.

### 5.1 Queue item classes

Candidate queue categories should be trading-shaped and derived from existing primitives:

1. **Resolve due forecast**
   - Trigger: supported forecast has `resolution_at <= as_of`, `scoring_state='pending'`, and no usable final outcome.
   - Agent obligation: obtain caller-side/outside outcome evidence and write `outcome.add` / `resolve.record` if available.
   - Boundary: Trade Trace does not fetch the outcome.

2. **Review stale or overdue watch**
   - Trigger: `decision.type='watch'` with `review_by <= as_of` or age above stale threshold.
   - Agent obligation: record a `review`, update/invalidate thesis, keep watching with new reason/deadline, or close the loop with reflection.
   - Boundary: urgency is process-based, not a trade recommendation.

3. **Reflect after outcome/review**
   - Trigger: decision/forecast/outcome/review has no linked reflection, especially after a resolved outcome or scheduled review.
   - Agent obligation: call `reflection.prompt_for_outcome` or review bundle/report inputs, then write `memory.reflect` if useful.
   - Boundary: system prompts reflection; it does not auto-generate subjective lessons.

4. **Record playbook adherence**
   - Trigger: decision references a playbook version but lacks `decision_playbook_rules` rows.
   - Agent obligation: record considered/followed/overridden/not-applicable rows.
   - Boundary: system reports missing audit trail; it does not judge compliance quality as advice.

5. **Investigate source/provenance gap**
   - Trigger: missing sources, stale sources, contradictory sources, duplicated sources, sensitive-source caveats, missing resolution-rule provenance, weak decision provenance, missing retrieval metadata.
   - Agent obligation: attach caller-supplied sources, mark caveats, or avoid using the artifact as high-confidence context.
   - Boundary: no URL/path fetch, no credibility scoring beyond deterministic hygiene diagnostics.

6. **Check current exposure / projection anomalies**
   - Trigger: open/partial positions, stale marks, projection anomalies, or current-exposure caveats.
   - Agent obligation: inspect exposure before adding/holding/reducing or before assuming flat state.
   - Boundary: no broker truth verification, no execution.

7. **Strategy review due**
   - Trigger: strategy active with enough new decisions/outcomes since last review, prolonged inactivity, adverse diagnostics, repeated stale watches, or sample-size thresholds crossed.
   - Agent obligation: inspect strategy-scoped reports, record review/reflection, maybe archive/update hypothesis later through existing strategy/playbook/reflection workflows.
   - Boundary: no automatic strategy mutation; exact review cadence may need later policy.

8. **Playbook review due**
   - Trigger: repeated overrides, missing adherence clusters, override outcome panels, new high-confidence reflections, or rule conflicts.
   - Agent obligation: review evidence and, if warranted, propose a playbook version with provenance reflection.
   - Boundary: reflection-to-policy quarantine applies; no automatic rule promotion.

9. **Recall receipt / memory hygiene gap**
   - Trigger: important decision/review lacks recall evidence; recalled memories are high-recall/low-use; startup/decision memory was not linked to consumer artifacts.
   - Agent obligation: establish receipt/use links or inspect memory usefulness diagnostics.
   - Boundary: do not overlog full transcripts; prefer IDs and typed edges.

### 5.2 Derived queue vs first-class durable work item

Recommended initial conceptual model: **derived queue surface first**.

A derived queue item is computed from ledger/memory/report state at `as_of`. This preserves append-only facts as source of truth, avoids generic task tables, and fits the existing report architecture. It is enough for obligations that have canonical source rows and deterministic closure:

- due forecast closes when a final/superseding outcome exists or forecast is superseded;
- overdue watch closes when a later review/update/invalidate/watch replacement exists, subject to lifecycle rules;
- missing reflection closes when a linked reflection exists;
- missing adherence closes when adherence rows exist;
- source gap closes when sources/edges/caveats exist or the issue becomes explicitly accepted.

First-class durable work items may become necessary only for state that cannot be reconstructed from source records, such as:

- explicit snooze/defer of a queue item without changing the underlying decision/forecast;
- assignment to a specific agent/model/role in multi-agent workflows;
- acknowledgement/dismissal with reason where the underlying gap remains but is intentionally accepted;
- recurring review cadence that is not tied to existing row timestamps or thresholds;
- queue item identity stability across runs for idempotent agent handling;
- partial progress on multi-step obligations, e.g., source collected but not attached, reflection drafted but not promoted.

The dossier recommendation is to keep “durable work item” as a later option, not a starting primitive. If introduced later, it should be constrained to **work state about trading artifacts**, not arbitrary to-dos.

### 5.3 Queue item lifecycle

Conceptual lifecycle for a queue item:

- `open`: obligation currently due or missing.
- `blocked`: requires caller-supplied external data/evidence/outcome before Trade Trace can be updated.
- `snoozed` / `deferred`: only if durable item state is later adopted; otherwise represented by updating the underlying artifact, e.g., new watch/review deadline.
- `satisfied`: derived closure condition met.
- `stale`: item has remained open beyond a policy threshold.
- `invalidated`: source row superseded/archived/voided such that the obligation no longer applies.
- `accepted_risk`: possible future durable state for intentional non-remediation of a hygiene issue.

For the derived-first model, most lifecycle state should be computed. Durable states like `snoozed` and `accepted_risk` are open questions.

## 6. Required Data / State

Required existing or planned state:

- Forecasts: `forecast_id`, `thesis_id`, `resolution_at`, `resolution_rule_text`, `scoring_support`, `scoring_state`, supersession/invalidated state, related outcomes.
- Decisions/non-actions: `decision_id`, `type`, `reason`, `review_by`, `created_at`, links to instrument/thesis/forecast/snapshot/strategy/playbook, tags, common attribution fields.
- Outcomes/scores: outcome status, final/provisional/disputed/ambiguous states, score events, late-recording caveats.
- Sources/edges: attachments to theses/decisions/forecasts/memory nodes, stance, freshness, redaction/sensitivity, contradiction/supersession edges.
- Memory/reflections: reflection nodes, `about` edges, validity/supersession, recall events, recall receipts/use links where available.
- Playbooks/adherence: active playbook versions, playbook-rule memory nodes, `decision_playbook_rules`, override reasons/outcome panels.
- Strategies: active/archived status, strategy IDs on theses/decisions/reviews/reflections, strategy-scoped report outputs.
- Exposure/projections: `positions`, `position_events`, current-exposure/open-position caveats, projection rebuild/anomaly reports.
- Report infrastructure: `ReportFilter`, record IDs, sample warnings, truncation, `as_of`, deterministic ordering, severity/caveat codes.
- Attribution: actor ID, `agent_id`, `model_id`, `environment`, `run_id`, request/idempotency metadata for scoping and audit.

Potential future durable state, only if derived surfaces fail:

- stable `work_item_id` or deterministic item key;
- `source_kind/source_id` plus `category` and `trigger_reason`;
- `status` such as open/snoozed/acknowledged/satisfied/accepted_risk;
- `due_at`, `priority`, `severity`, `blocked_reason`, and `requires_external_input`;
- owner/scope fields (`agent_id`, `model_id`, `environment`, `run_id`, strategy/playbook scope);
- `created_from_report` / trigger provenance;
- idempotency key for action completion/acknowledgement;
- audit trail for dismiss/snooze/acceptance reasons.

## 7. Machine Interface Implications

A work queue should be exposed as CLI/MCP/JSON-first data, likely as a read/report-style surface or a section in the bootstrap pack. No human UI assumptions are needed.

Expected interface implications:

- Inputs should mirror `ReportFilter` plus queue controls: `as_of`, `categories`, `severity_min`, `due_before`, `include_blocked`, `include_satisfied=false`, `strategy_id`, actor/run filters, `limit`, `cursor`, and per-category thresholds.
- Output should be stable JSON with an array of items. Each item should include:
  - deterministic key or item ID;
  - `category` and short `summary`;
  - `status`, `severity`, `due_at`, `stale_since`, and `as_of`;
  - `source_refs` such as forecast/decision/source/memory/strategy/playbook/position IDs;
  - `trigger_evidence` naming the report/check that generated the item;
  - `required_external_input` boolean and reason;
  - `suggested_tool_calls` framed as process actions, e.g. `resolve.record` after caller supplies outcome, `memory.reflect`, `decision.record_adherence`, `source.attach_to_forecast`, `decision.add(type=review)`;
  - `closure_condition` so the next agent knows how the item disappears;
  - caveats: no fetch, no execution, no advice, truncation, low sample, missing metadata.
- The queue should support deterministic pagination and deduplication. A due forecast that also appears in audit-readiness issues should not create conflicting obligations; it may have one primary queue item plus secondary caveats.
- Absence must be caveated. If filters exclude agents/strategies or metadata is missing, the response should not imply global cleanliness.
- Suggested actions must not be imperative trading recommendations. “Resolve forecast with externally supplied outcome” is acceptable; “enter this trade” is not.
- For MCP, the shape should be schema-discoverable and safe for fresh agents to call at session start. For CLI, JSON output should be the default or easily selectable.
- If future durable work items exist, write operations should be limited to process-state changes such as acknowledge/snooze/accept-risk/mark-blocked, with idempotency and append-only event audit. They should never launch jobs, fetch data, or execute trades.

## 8. Evidence

- Repo evidence:
  - Research contract establishes the agent-only, local-first, no-execution/no-fetching/no-dashboard boundary and requires concept dossiers to distinguish facts, inferences, and recommendations (`docs/research/agentic-trade-trace/00-research-contract.md:20-39`, `89-138`).
  - Current-system baseline observes implemented ledger, decisions, outcomes, reports, memory graph, strategies, playbooks, source provenance, current exposure, MCP/CLI parity, and identifies agent-session protocols as a Phase 1 need (`docs/research/agentic-trade-trace/01-current-system-baseline.md:21-39`, `51-67`, `87-97`).
  - Taxonomy adopts work queue / next actions as core but explicitly excludes background scheduling/daemonized reminders (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:37-49`, `121-129`, `140-151`).
  - Foundational synthesis frames work obligations as derived continuity surfaces and asks whether reports/lifecycle are enough or durable items are needed (`docs/research/agentic-trade-trace/synthesis/foundational-continuity.md:73-80`, `189-195`).
  - Bootstrap, lifecycle, and recall receipt dossiers define upstream dependencies and the need to surface due work at session start (`concepts/fresh-session-bootstrap-context-pack.md`, `concepts/decision-non-action-lifecycle.md`, `concepts/recall-receipts.md`).
  - PRD documents forecasts, decisions with watch deadlines, playbook adherence rows, sources, memory/recall events, reports, resolution tools, and strategies (`docs/PRD.md:175-238`, `260-340`, `364-420`, `422-433`).
  - `report.watchlist`, `report.unscored_forecasts`, `report.coach`, `report.source_quality`, and `report.audit_readiness` provide concrete existing obligation signals (`src/trade_trace/reports/watchlist.py`, `unscored.py`, `coach.py`, `source_quality.py`, `audit_readiness.py`).
  - Reports architecture provides filter, record-ID drilldown, truncation, and sample-warning patterns suitable for a derived queue (`docs/architecture/reports.md:26-31`, `33-229`).
- External evidence, if used:
  - The external synthesis says human trading journals and agent memory architecture strengthen work queue / next actions moderately: review cadence and explicit state translate into due work, but obligations should be exposed rather than scheduled/executed (`docs/research/agentic-trade-trace/synthesis/external-evidence.md:38-49`, `105-117`). No new network fetches were run for this dossier.
- User-stated intent:
  - The delegated task asks this dossier to focus on durable obligations for stateless agents: due forecasts, stale watches, missing outcomes/sources/reflections/adherence, strategy reviews, playbook review, current exposure checks; to distinguish work queue from scheduler/daemon/task manager; to design JSON/MCP implications; and to determine whether a derived report surface is enough or first-class durable work items may be needed.
- Inferences:
  - Current reports are strong enough to support a derived-first work queue concept, but they are scattered and do not provide one deduplicated obligation list.
  - First-class durable work items are plausible only for acknowledgement, snooze, assignment, stable identity, and partial-progress state that cannot be derived from ledger/memory facts.
  - Work queue priority should be by process urgency, audit risk, due time, and continuity risk, not by expected profit/opportunity attractiveness.

## 9. Risks / Failure Modes

- **Scheduler creep:** A due-work surface may be mistaken for cron, daemon, alerting, webhook, or job execution. Mitigation: expose obligations only; external orchestrators trigger agents.
- **Generic task-manager creep:** Arbitrary tasks would dilute the trading-shaped substrate. Queue items should derive from forecasts, decisions, outcomes, sources, strategies, playbooks, memory, exposure, and reports.
- **Advice creep:** “Next action” can sound like “trade recommendation.” Suggested actions must be process actions, not market-direction actions.
- **False completeness:** If queue generation is filtered, truncated, or misses metadata, an agent may assume no obligations exist. Responses need filter echoes, omitted counts, and caveats.
- **Overwhelming backlog:** Missing reflections/sources/adherence on every historical row can flood the queue. Need severity thresholds, age windows, category filters, and sample caps.
- **Duplicated obligations:** A single root issue may appear in watchlist, coach, audit, and source reports. Deduplication by source refs and category is necessary.
- **Stale queue identity:** Purely derived items may shift IDs or disappear/reappear when thresholds change, making idempotent agent handling harder.
- **Unclosable items:** Some gaps may require external data not available to Trade Trace. Items need `blocked` / `requires_external_input` semantics.
- **Overfitting process work:** Agents may optimize to clear hygiene queues rather than make better-calibrated decisions. Queue metrics should not become a reward score.
- **Append-only conflict:** Acknowledging/dismissing derived gaps could require mutable task state unless modeled carefully as append-only process events.
- **Scope leakage:** Missing or inconsistent `agent_id`, `model_id`, `environment`, or `run_id` can blend obligations from incompatible agents or experiments.
- **Policy poisoning:** Playbook/strategy review due items could pressure premature rule changes; reflection-to-policy quarantine must gate promotions.

## 10. Dependencies / Conflicts

Dependencies:

- Decision and non-action lifecycle: defines which records create obligations and how closure is inferred.
- Fresh-session bootstrap context pack: primary consumer; the queue should feed the startup “what must I handle?” section.
- Recall receipts: memory/retrieval use gaps may become queue items, and queue-driven decisions should cite recalled context.
- Strategy lifecycle: strategy review obligations require strategy-scoped reports, status, and update/review semantics.
- Reflection-to-policy quarantine and playbook predicates: playbook review and adherence gaps must not auto-promote policy.
- Forecast-vs-market diagnostics: due outcomes and post-resolution review obligations feed diagnostics/reflection.
- Current exposure contract: queue must distinguish actual/paper exposure from watches and record-only actual decisions.
- Report infrastructure: filters, record IDs, sample warnings, truncation, and deterministic report envelopes.

Conflicts / boundaries:

- Work queue vs scheduler: Trade Trace can report due work but must not run jobs, poll markets, alert humans, or call tools on a timer.
- Work queue vs task manager: only trading-journal/process obligations should be in scope.
- Work queue vs bootstrap pack: bootstrap is the bounded startup packet; work queue is one input/section and possible standalone report.
- Derived queue vs durable items: derived avoids schema/scope creep; durable items solve acknowledgement/snooze/identity. This tension should be decided after dogfood evidence.
- Work queue vs advice: ranking by urgency/severity is acceptable; ranking by “best opportunity” risks advice/product-scope drift.

## 11. Open Questions / Falsifiers

- Can disciplined agents reliably compose `resolve.pending`, `report.watchlist`, `report.unscored_forecasts`, `report.coach`, `report.source_quality`, `report.audit_readiness`, `report.current_exposure`, `report.strategy_performance`, and playbook reports without a unified queue? Falsifier: dogfood agents miss few/no obligations using an existing-tool recipe.
- What queue categories are minimum viable for a bootstrap pack: due forecasts, overdue watches, missing reflections/adherence, source gaps, exposure checks, strategy/playbook reviews, or fewer?
- Are strategy review and playbook review due rules deterministic enough, or do they require agent-authored policy/cadence state?
- Should `skip` ever create a later review item, or only when tagged/linked to a forecast/outcome/replay case?
- How should pure derived queues support snooze/acknowledge/accept-risk without durable state?
- What closure conditions are canonical for a watch, stale source, missing reflection, and strategy review?
- Should queue item severity be fixed by Trade Trace or caller-configurable per agent/playbook?
- Does queue state need a first-class `work_item_id` for idempotent MCP agents, or is deterministic `{category, source_refs, as_of/threshold}` enough?
- Would first-class durable work items conflict with append-only invariants, or can they be append-only process events over derived obligations?
- Falsifier for adoption: if the queue requires execution, data fetching, broker truth, human approval UI, or generic task assignment to be useful, it should be narrowed or rejected.
- Falsifier for derived-first stance: if repeated dogfood runs show agents need stable acknowledgement/snooze/assignment/partial-progress state that cannot be represented by existing ledger/memory updates, durable work items should be promoted from deferred option to product primitive.

## 12. Decision Hook

This dossier should feed continuity/process-control synthesis after `trade-trace-53tq`, especially the downstream cross-concept ranking/decision work for agentic Trade Trace. Recommended decision framing: adopt a work queue / next-action surface as a core future product concept, initially as a derived report/bootstrap section over existing ledger, memory, projection, and report state; keep first-class durable work items as a conditional later primitive if dogfood falsifies derived sufficiency.

## 13. Side Effects

Files written:

- `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/concepts/agent-work-queue-next-actions.md`

Files modified besides this artifact: none.

Memory retained: none.

External/network side effects: none; no network fetches were run.

Implementation changes: none; no code, schemas, tests, README, PRD, VISION, config, Beads, or implementation-bearing files were edited.
