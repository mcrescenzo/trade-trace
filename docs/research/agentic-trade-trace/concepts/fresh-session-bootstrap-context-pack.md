# Concept Dossier: Fresh-session bootstrap context pack

## 1. Question

Should Trade Trace make a bounded, deterministic, machine-readable startup context pack a first-class product primitive for cron-triggered or otherwise stateless LLM trading agents, and what should that pack contain without turning Trade Trace into a dashboard, scheduler, market-data fetcher, or trading advisor?

## 2. Bottom Line

- Recommendation: adopt core
- Confidence: high
- Why: The central research contract explicitly prioritizes fresh-session continuity for stateless trading agents, and the current repo already contains most of the underlying read/write primitives a context pack would assemble: active strategies, watch/skip/paper/actual-recorded decisions, unresolved forecasts, due resolution reads, watchlist/unscored reports, current exposure/open-position reports, memory recall and recall telemetry, playbook versions/adherence, sources, report filters, and JSON-first CLI/MCP parity. The missing product primitive is not more raw state; it is a deterministic session-start assembly contract that selects, bounds, cites, caveats, and orders that state for an agent with no implicit memory.

## 3. Agent-Specific Problem

A human trader can rely on habit, visual dashboards, broker screens, handwritten notes, and latent memory to reconstruct “what am I doing today?” A fresh LLM trading agent cannot. In a cron-triggered workflow, each run may start with no conversation history and must not infer continuity from unstated memory. If startup context is retrieved ad hoc, the agent can:

- miss unresolved forecasts whose `resolution_at` has passed;
- confuse watch ideas with open positions;
- ignore strategy boundaries and smear lessons across unrelated edge theses;
- apply stale playbook rules or forget which rules were current at prior decisions;
- repeat work because next actions were only in prose from a prior session;
- over-trust a memory without knowing its source, validity window, or recall provenance;
- fabricate continuity because it remembers a prior conversation rather than reading the local journal.

The agent-specific need is therefore a compact “session boot packet” that is deterministic, token-budgeted, ID-rich, caveated, and safe to consume before the agent forms new theses or decisions. It should answer: what is active, what is unresolved or due, what context must be recalled, what caveats limit confidence, and what actions are next for this run?

## 4. Current Trade Trace Baseline

Observed implementation/planning baseline from inspected repo docs and source:

- Product boundary: Trade Trace is a local, open-source, AI-only journal, memory, and calibration substrate with MCP/CLI/JSON-first surfaces and no trade execution (`README.md:3-11`, `README.md:92-117`; `docs/VISION.md:8-29`, `38-49`, `149-170`).
- Fresh-session continuity is in scope for this research program; dashboards, execution, market-data fetching, and generic memory are out of scope (`docs/research/agentic-trade-trace/00-research-contract.md:20-38`).
- The Phase 0 taxonomy identifies “Fresh-session bootstrap context pack” as a core concept and describes it as a bounded startup packet containing active strategies, unresolved forecasts, stale watches, open/paper positions, queued next actions, memories, playbook state, and caveats (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:37-49`, `92-119`, `140-151`).
- Current system already has many candidate inputs:
  - strategies are first-class active/archived entities with `strategy.create/list/show/update` and strategy-scoped report/recall intent (`docs/PRD.md:117-131`, `422-433`; baseline notes source implementation in `src/trade_trace/tools/strategy.py`);
  - decisions include `watch`, `skip`, `hold`, `paper_enter`, `paper_exit`, `actual_*`, `review`, thesis update/invalidation, and `watch.review_by` for deferred review (`docs/PRD.md:194-228`);
  - paper position projections and current-exposure semantics distinguish open positions from watch ideas and record-only actual decisions (`docs/PRD.md:203-206`, `240-250`; `docs/architecture/current-exposure-agent-contract.md:5-16`, `18-31`, `53-75`);
  - forecasts carry `resolution_at`, `resolution_rule_text`, scoring lifecycle, and segmentation fields (`docs/PRD.md:175-184`);
  - `resolve.pending` returns due unresolved forecasts deterministically because outcome resolution often happens in a different session from forecast creation (`docs/PRD.md:408-413`);
  - reports include watchlist, unscored forecasts, playbook adherence, calibration/integrity/source/audit diagnostics, compare, current exposure/open positions, and strategy performance in the observed registry baseline (`docs/research/agentic-trade-trace/01-current-system-baseline.md:51-59`; `docs/architecture/reports.md:1-14`);
  - memory nodes, recall events, and recall stats can expose recent/important reflections, observations, and playbook rules with validity, confidence, importance, and returned-node telemetry (`docs/PRD.md:302-325`, `357-363`);
  - sources attach to theses, decisions, forecasts, and memory nodes, with redaction/freshness/stance fields and no automatic fetching (`docs/PRD.md:260-268`, `415-420`).
- Current gap: no inspected source or docs define a single canonical startup pack that assembles these primitives with stable sections, token budgets, source caveats, recall receipts, and next-action ordering. The baseline explicitly names “agent-session protocols for cron/fresh sessions” as a Phase 1 need (`docs/research/agentic-trade-trace/01-current-system-baseline.md:87-97`).

## 5. Candidate Product Shape

Conceptually, a fresh-session bootstrap context pack should be a read-only, deterministic assembly object, not a new market signal and not a scheduler. It would be generated at session start for a caller-supplied scope such as agent/model/environment/run, strategy, time window, or asset universe.

Candidate sections:

1. **Pack metadata**
   - generated_at, as_of, actor/agent/model/environment/run filters, contract version, truncation policy, source tools/reports used, and caveat summary.
2. **Identity and scope**
   - current logical agent/session attribution keys and any filter assumptions. If fields are missing, the pack should say so rather than silently widening scope.
3. **Active strategies**
   - active strategy IDs/slugs, hypotheses, status, last update, recent decision counts, and strategy-specific caveats. Archived strategies should appear only if directly relevant to unresolved work or recall.
4. **Open/current exposure**
   - canonical open/partial `positions` projection rows where present, with `kind` (`paper`, `actual`, `simulation`) and caveat codes. Watch ideas and record-only actual decisions must be separate buckets, never counted as exposure.
5. **Watchlist and stale watches**
   - active `watch` decisions, `review_by`, overdue/stale flags, thesis/forecast/source pointers, and reason snippets.
6. **Unresolved/due forecasts**
   - forecasts pending resolution, especially past `resolution_at`, with resolution rules, related thesis/instrument, scoring support/state, and source/outcome caveats.
7. **Due reviews / next actions**
   - deterministic obligations synthesized from due forecasts, overdue watches, missing sources, stale sources, projection anomalies, playbook-adherence gaps, and review prompts. This section should list work for the external cron-triggered agent; Trade Trace should not schedule or execute it.
8. **Current playbook state**
   - active playbook/version IDs, relevant playbook rule memory nodes, recent adherence/override diagnostics, and provenance caveats for recently changed rules.
9. **Recent and important memories**
   - bounded recall output for current scope: high-importance observations/reflections/playbook rules, valid time windows, confidence/decay hints, supersession/invalidated status, and target links. The pack should prefer IDs and compact summaries over unbounded prose.
10. **Recall receipts / retrieval trace**
    - query/context/strategies used for memory recall, returned node IDs, ranking/truncation metadata, and whether recall persistence occurred. This lets later decisions prove what internal memory was surfaced at startup.
11. **Source and data caveats**
    - sensitive/redacted sources excluded, missing/stale/contradictory source diagnostics, projection anomalies, unsupported forecast scoring, low sample warnings, and “no fetch performed” boundary.
12. **Recommended next tool calls, not trade advice**
    - machine-actionable read/write candidates such as `resolve.pending`, `outcome.add` for a user-supplied outcome, `memory.reflect` after a resolved outcome, or `decision.add(type=review)` for an overdue watch. These should be framed as process obligations, not market recommendations.

Lifecycle:

- Generated at the beginning of an agent run.
- Consumed before the agent forms new theses or decisions.
- Optionally linked by the agent to later decisions through recall receipts or metadata, but the pack itself should remain a read artifact.
- Regenerated each run rather than persisted as the canonical source of truth; durable state remains in ledger, memory, reports, events, and projections.

## 6. Required Data / State

The concept depends mostly on existing or already-planned state:

- Agent/run attribution fields: `actor_id`, `agent_id`, `model_id`, `environment`, `run_id` as filters and caveats (`docs/PRD.md:133-145`).
- Strategies: `strategies.status`, description/hypothesis, strategy IDs on decisions/theses/reviews, and strategy-scoped reports/recall (`docs/PRD.md:117-131`, `281-287`, `422-433`).
- Decisions and non-actions: decision type, reason, `review_by`, tags, thesis/forecast/snapshot/playbook/strategy links (`docs/PRD.md:194-238`).
- Positions/exposure: `position_events`, `positions`, and current-exposure caveat codes/buckets (`docs/PRD.md:240-250`; `docs/architecture/current-exposure-agent-contract.md:18-51`).
- Forecasts/outcomes/scores: `resolution_at`, `resolution_rule_text`, scoring state/support, due unresolved forecasts, scores, outcomes (`docs/PRD.md:175-192`, `252-258`, `408-413`).
- Memory: memory nodes, edges, valid time windows, importance/confidence/decay, recall events/stats, recall filters, playbook-rule nodes (`docs/PRD.md:302-325`, `335-340`, `357-363`).
- Playbooks/adherence: playbook versions, rule nodes, adherence rows and overrides (`docs/PRD.md:289-292`, `398-406`).
- Sources and source diagnostics: source rows, stance/freshness/redaction fields, attachments, `report.source_quality` and audit readiness diagnostics (`docs/PRD.md:260-268`, `379-381`, `415-420`).
- Report infrastructure: `ReportFilter`, record IDs, sample warnings, truncation/cursoring, and `report.filter_schema` (`docs/architecture/reports.md:26-31`, `33-122`, `124-220`).

State that may need future product definition, without implementation authorization:

- A stable pack section schema and ordering.
- Token/character budgets per section and global truncation semantics.
- How next actions are represented if no first-class work queue exists yet.
- Whether recall events from startup should be enough as receipts, or whether a higher-level pack receipt is needed to tie all included artifacts to the run.

## 7. Machine Interface Implications

The interface should be JSON/MCP/CLI-first and read-oriented. Agents should be able to request a pack with explicit scope and budget, receive stable keys, and then drill down through existing tools using IDs.

Implications:

- Inputs should likely mirror `ReportFilter` plus bootstrap-specific controls: `as_of`, `strategy_id`, `agent_id/model_id/environment/run_id`, `max_chars`, `max_items_per_section`, `include_memory_body`, `include_sensitive=false`, and section toggles.
- Output should be a single structured envelope with stable section names, not a prose briefing.
- Every included row should carry `{kind, id}` references and enough summary to decide whether to fetch details.
- The pack should echo filters and list omitted/truncated sections so an agent knows when not to over-trust absence.
- It should use current-exposure bucket and caveat names exactly where exposure is included; `watchlist` is not `open_positions`.
- It should call out “no market data fetched, no broker truth verified, no trade advice generated” as machine-readable caveats.
- It should be deterministic for a fixed database/as-of/filter/budget, except for durable side effects already inherent to recall telemetry if memory recall is invoked.
- It should integrate recall receipts: the agent needs to know which memory queries were run, which node IDs were returned, and what was truncated.
- It should point to next process actions but not execute them. For example, a due forecast can say “requires externally supplied outcome before `outcome.add`,” not “fetch outcome.”

No UI/dashboard assumptions are needed. The pack is a session-start context contract for machine clients, not a visual home screen.

## 8. Evidence

- Repo evidence:
  - Research contract scopes fresh-session continuity, machine-readable MCP/CLI/JSON-first abstractions, local-first operation, and excludes dashboards/execution/fetching/implementation (`docs/research/agentic-trade-trace/00-research-contract.md:20-38`, `89-138`).
  - Current-system baseline observes implemented ledger, memory, strategies, reports, current exposure, recall telemetry, playbooks, source provenance, and CLI/MCP parity; it identifies agent-session protocols as a Phase 1 need (`docs/research/agentic-trade-trace/01-current-system-baseline.md:21-39`, `51-67`, `87-97`).
  - Taxonomy classifies the fresh-session bootstrap context pack as a core concept and names its overlap/dependencies with work queue, recall receipts, strategy state, playbook, and reports (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:37-49`, `92-119`, `140-151`).
  - README and Vision establish Trade Trace as local, AI-only, no-execution/no-fetch, JSON-first, agent-native substrate (`README.md:3-11`, `92-146`; `docs/VISION.md:8-29`, `38-62`, `163-170`).
  - PRD documents strategies, common metadata, forecasts/resolution, decisions/watch/review deadlines, positions, memory recall events, reports, playbooks, resolution, and sources (`docs/PRD.md:117-145`, `175-238`, `240-268`, `302-325`, `357-420`, `422-433`).
  - Reports architecture documents `ReportFilter`, record-ID drilldowns, sample warnings/truncation, and shipped/deferred report surfaces (`docs/architecture/reports.md:1-14`, `26-31`, `33-122`, `124-220`).
  - Current-exposure contract provides stable machine-readable exposure buckets and caveat codes required to avoid confusing watches or record-only actual decisions with open exposure (`docs/architecture/current-exposure-agent-contract.md:5-16`, `18-75`).
- External evidence, if used: none. No network fetches were run.
- User-stated intent: The delegated task states that cron-triggered/stateless LLM trading agents need deterministic, bounded, machine-readable startup context and specifically asks to consider active strategies, unresolved forecasts, watchlist, open/paper positions, stale watches, due reviews, current playbook, recent/important memories, recall receipts, source caveats, and next actions.
- Inferences:
  - Because most underlying data primitives already exist, the highest-value primitive is an assembly/contract layer rather than a new ledger category.
  - Because absence can be ambiguous in a truncated/token-budgeted pack, caveats and truncation metadata are part of the core concept, not polish.
  - Because Trade Trace must not fetch data or execute trades, next actions must be process-oriented and require caller-supplied market/outcome information.
  - Because `memory.recall` can persist recall events, a startup pack that invokes recall has a small local side effect unless designed to avoid or explicitly report it.

## 9. Risks and Failure Modes

- Context poisoning: stale, low-confidence, superseded, or overfit reflections could be surfaced as authoritative unless confidence, validity, source, and supersession caveats are explicit.
- False completeness: a bounded pack can omit important rows. Without truncation and filter metadata, an agent may treat absence as evidence.
- Watch/exposure confusion: watch ideas or record-only actual decisions could be mistaken for open positions unless current-exposure semantics are reused exactly.
- Dashboard creep: if framed as a “morning screen,” the concept could drift toward human UI. It should remain JSON-first and token-budgeted.
- Scheduler creep: due reviews and next actions could become alerts/cron/daemon behavior. Trade Trace should expose obligations; external orchestrators trigger runs.
- Advice creep: startup sections like opportunity/risk/watchlist could be misconstrued as trade recommendations. The pack should present recorded state and process obligations only.
- Source over-trust: attached URLs/paths are stored metadata; Trade Trace does not fetch or verify external content. Packs must distinguish caller-supplied source metadata from verified current facts.
- Scope leakage across agents/models: if `agent_id`, `model_id`, `environment`, or `run_id` are omitted, the pack may merge contexts from incompatible agents or experiments.
- Recall side effects ambiguity: if pack generation records recall telemetry, callers must understand that a read-like startup action may append local recall events.
- Token-budget distortion: ranking and truncation can bias what the agent sees; important low-recentness items may be hidden without drilldown cues.

## 10. Dependencies and Conflicts

Dependencies:

- Agent/run attribution and continuity keys for scoping and caveating mixed records.
- Decision and non-action lifecycle for watch/skip/hold/review/open-position context.
- Work queue / next actions for durable pending obligations; in the interim, next actions can be synthesized from reports and due fields.
- Recall receipts for startup memory provenance and later audits of what context was available.
- Strategy lifecycle because active strategies are a first-class organizing axis for startup context.
- Playbook state and reflection-to-policy quarantine because current rules and recent rule changes shape how the new agent should operate.
- Source/evidence provenance and current-exposure caveats to avoid hallucinated market truth or broker truth.

Conflicts to manage:

- A bootstrap pack is close to a dashboard in purpose, but can stay within product principles if it is a machine-readable JSON packet with stable IDs, budgets, filters, and caveats.
- It can look like a scheduler if it includes due work, but it should not trigger jobs, fetch outcomes, page humans, or run cron.
- It can look like advice if it ranks opportunities; avoid ranking markets by attractiveness. Ranking should be by process urgency, due time, stale risk, or retrieval relevance.
- It can duplicate `review.bundle`; distinguish them: `review.bundle` packages historical cases for review, while bootstrap packs assemble live session-start continuity and obligations.

## 11. Open Questions / Falsifiers

- Is a single pack primitive necessary, or can disciplined agents compose existing tools (`strategy.list`, `report.current_exposure`, `report.watchlist`, `resolve.pending`, `memory.recall`, `playbook.show`) reliably enough? Falsifier: dogfood agents consistently bootstrap safely with an existing-tool recipe and no missed obligations.
- What is the minimum viable section set? Falsifier: packs with all proposed sections exceed token budgets and agents ignore most of them.
- Should pack generation persist a durable receipt distinct from `memory_recall_events`, or is returned JSON plus recall telemetry enough?
- How should next actions be represented before a first-class work queue exists?
- How should missing segmentation fields be handled: include all with caveat, require explicit opt-in broadening, or fail closed?
- What budget policy best avoids hiding critical obligations: per-section quotas, priority tiers, or cursor-based continuation?
- Should startup recall query templates be fixed by Trade Trace, caller-supplied, or hybrid? A fixed template is more deterministic; caller-supplied queries may be more relevant but less comparable.
- Not verified: full SQL correctness of all report tools, end-to-end CLI/MCP responses, current status of `review.bundle` implementation beyond docs/source search, and exact snapshot segmentation drift noted in the baseline.

## 12. Decision Hook

This dossier should feed decision bead `trade-trace-53tq` for Phase 1 synthesis/ranking. It recommends adopting the fresh-session bootstrap context pack as a core product primitive for future product direction only. No implementation is authorized.

Side effects for this artifact: wrote exactly this research file; retained no memory; performed no network fetches; made no code, schema, test, README/PRD/VISION, Beads, config, or implementation changes.
