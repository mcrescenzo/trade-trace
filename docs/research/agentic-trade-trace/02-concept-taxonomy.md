# Agentic Concept Taxonomy and Deduplication

## 1. Bottom Line

**Recommendation:** normalize the Phase 0 concept set into eight core investigation clusters plus four supporting/deferred clusters before dossier work begins.

The most agent-specific product question is not “what would a better trading journal show a human?” but “what persistent, machine-readable state lets a fresh LLM trading agent resume work, prove what it recalled, evaluate its past reasoning, and safely turn reflection into process changes?” The canonical concepts should therefore be organized around the agent continuity loop:

1. identify the acting session/run;
2. reconstruct active context at startup;
3. record decisions, non-decisions, forecasts, sources, recalls, and next actions as auditable artifacts;
4. evaluate forecasts/outcomes and strategy/process state;
5. quarantine subjective reflections before they become playbook policy;
6. replay/regress behavior over old cases;
7. hand off between agents only after the single-agent continuity model is coherent.

**Initial taxonomy decisions:**

- **Adopt as core investigation clusters:** Fresh-session continuity pack; Decision and non-action lifecycle; Recall receipts; Work queue / next actions; Forecast-vs-market diagnostics; Strategy lifecycle; Reflection-to-policy quarantine; Replay/regression substrate.
- **Adopt as supporting/cross-cutting:** Agent run/session identity; Machine-checkable playbook predicates.
- **Defer pending core evidence:** Multi-agent handoff protocol.
- **Exclude from this program:** execution, order routing, market-data fetching, autonomous scheduling/daemons, human dashboards, generic agent memory, and profitability/financial-advice claims.

## 2. Taxonomy Principles — agent-only, local-first, no execution/data fetching, machine-readable, fresh-session continuity

1. **Agent-only:** every concept must solve a problem caused by LLM/agent operation: stateless runs, tool-mediated memory, limited context windows, idempotent retries, machine-readable provenance, and auditable self-improvement. Human journal conveniences are not enough.
2. **Local-first:** concepts should fit a local SQLite / CLI / MCP / JSON-first tool boundary with no required remote service.
3. **No execution or data fetching:** concepts may record agent-supplied market data, outcomes, decisions, and sources, but must not imply broker integration, order placement, price polling, venue connectors, webhooks, or outcome fetching.
4. **Machine-readable over human-readable:** every recommended primitive should be inspectable through schemas, stable IDs, filters, events, and JSON bundles; prose can be attached but must not be the only contract.
5. **Fresh-session continuity:** prioritize primitives that let a new cron-triggered or stateless session recover the prior session’s unresolved theses, active decisions, relevant memories, strategy state, playbook version, and queued work.
6. **Auditability before automation:** prefer recording and deterministic reporting over agentic action. Subjective judgment remains with the calling agent; Trade Trace stores, links, scores, and reports.
7. **Separate ledger facts, beliefs, and policy:** immutable decisions/outcomes, falsifiable memory/reflection, and playbook rules have different lifecycles and should not be collapsed.
8. **Scope by trading-shaped concepts:** generic memory, generic task management, and generic multi-agent protocols should be accepted only when tied to forecasts, decisions, strategies, playbooks, or source/outcome provenance.

## 3. Canonical Concept Table

| Canonical name | Purpose | Human-trader analogue if any | Agent-only difference | Dependencies | Downstream synthesis bead | Initial stance |
|---|---|---|---|---|---|---|
| Agent run/session identity | Track which logical agent/model/environment/run created or consumed records so later reports, recalls, and handoffs can be filtered by actor/session. | Journal account/user, trading desk, notebook date. | LLMs restart without implicit memory; `run_id`, `agent_id`, `model_id`, and actor identity become continuity and attribution keys, not mere metadata. | Existing common metadata in PRD §2.12; event/idempotency model. | Continuity/memory synthesis; evaluation synthesis. | **Adopt supporting primitive.** Keep as cross-cutting metadata unless dossiers show it needs first-class run objects. |
| Fresh-session bootstrap context pack | Provide a bounded machine-readable startup packet: active strategies, unresolved forecasts, stale watches, open/paper positions if present, queued next actions, recent/important memories, current playbook version, and caveats. | Morning prep sheet / trading plan review. | A fresh LLM session has no latent personal memory; bootstrap must be deterministic, token-budgeted, and cite IDs so the agent can resume safely. | Run identity; decision lifecycle; work queue; recall receipts; strategy state; reports; playbook state. | Core product-direction synthesis. | **Adopt core.** Likely the highest-value agent-only primitive. |
| Decision and non-action lifecycle | Normalize trades, skips, watches, holds, thesis updates, invalidations, and reviews into one auditable lifecycle. | Trade blotter plus decision journal. | Non-actions and deferred choices must be retrievable and reviewable because an agent otherwise loses why it did nothing between stateless runs. | Current decisions/theses/forecasts/snapshots/outcomes; playbook adherence; sources. | Decision/process synthesis. | **Adopt core.** Merge canonical “decision lifecycle” and “non-actions as first-class learning objects.” |
| Recall receipts | Persist evidence of what memories were returned and used for a decision/review, including query/context/strategies and returned node IDs. | A human’s remembered precedent, usually implicit. | Agents need auditable proof of retrieved context; otherwise self-improvement cannot distinguish “memory absent” from “memory ignored.” | Memory graph; memory_recall_events; decision/source edges; run identity. | Memory/continuity synthesis. | **Adopt core.** Treat as required evidence for calibration of the memory layer. |
| Agent work queue / next actions | Represent pending agent obligations: resolve due forecasts, revisit watches, collect missing sources, review stale strategies, perform reflection after outcomes, or re-run diagnostics. | To-do list, watchlist, calendar reminders. | Cron-triggered agents need durable task state because there is no human habit loop; tasks must be machine-filterable and not require internal scheduling. | Decision lifecycle; reports for stale/unscored items; bootstrap pack; run identity. | Continuity/process-control synthesis. | **Adopt core, but local/deterministic only.** No daemon or external scheduler. |
| Forecast-vs-market diagnostics | Compare prior forecast probabilities, decision prices/snapshots, market-implied probabilities, liquidity/spread, and resolved outcomes to diagnose calibration and edge claims. | Post-trade review, forecast calibration, entry-quality review. | Agents can systematically over/underweight signals; diagnostics must be structured enough to feed reflection and playbook changes without claiming alpha. | Forecasts, snapshots, outcomes, scoring reports, source quality, strategy filters. | Evaluation/calibration synthesis. | **Adopt core.** Keep as retrospective reporting, not market data fetching or advice. |
| Strategy state and lifecycle | Track named edge theses from active to archived, with associated decisions, theses, reviews, reflections, diagnostics, and hypothesis evolution. | Strategy notebook / playbook by setup. | Agents need durable strategy/process state across sessions and must avoid smearing performance across unrelated ideas. | Existing first-class strategies in PRD §2.12; reports; recall context; playbooks. | Strategy/process synthesis. | **Adopt core.** Investigate whether current mutable strategy row is enough for agentic continuity or whether point-in-time strategy hypothesis state matters. |
| Machine-checkable playbook predicates | Identify rule types whose adherence can be evaluated deterministically rather than only self-reported. | Checklist compliance rules. | Agents may self-report adherence inconsistently; machine-checkable predicates allow safer regression and violation reports where fields are explicit. | Playbook versions/rules; decision_playbook_rules; snapshots/forecasts/decisions; reflection quarantine. | Policy/playbook synthesis. | **Adopt supporting; split from playbook lifecycle.** Start narrow; avoid general rule engine. |
| Reflection-to-policy quarantine | Separate agent-written reflections from durable playbook/policy updates until evidence, provenance, and review criteria are satisfied. | Trader reviews notes before changing rules. | LLMs can overfit, rationalize, or poison their own future context; quarantine prevents one bad reflection from immediately becoming policy. | Reflections; playbook versions; source/outcome/provenance edges; forecast diagnostics; replay/regression. | Policy/playbook synthesis. | **Adopt core.** Important safety primitive for agentic self-improvement. |
| Replay/regression evaluation substrate | Package historical cases and prior context so an agent/model/playbook can be re-evaluated against old decisions without rewriting history. | Replay old trades / backtesting lessons, but not market simulation. | Agents and models change; old cases should test whether new prompts/playbooks would recall better evidence or avoid old errors. | Recall receipts; decision lifecycle; forecast outcomes; bootstrap context; strategy state; playbook versions. | Evaluation/calibration synthesis. | **Adopt core as research concept.** Must remain replay of recorded artifacts, not synthetic backtesting or market simulation. |
| Multi-agent handoff protocol | Define how one agent session hands context, obligations, and caveats to another agent/model/reviewer. | Shift handoff between analysts/traders. | Multiple LLMs lack shared implicit memory; handoff needs explicit IDs, assumptions, unresolved work, and authority boundaries. | Bootstrap pack; run identity; work queue; recall receipts; strategy state. | Later collaboration synthesis. | **Defer.** Valuable but should consume the single-agent continuity primitives rather than drive them. |
| Source/evidence provenance for agent decisions | Ensure claims, snapshots, outcomes, and reflections carry local, inspectable source links and quality diagnostics. | Research binder / citations. | Agents need machine-checkable provenance to avoid hallucinated continuity and to enable later reflection on evidence quality. | Sources table/edges; source-quality reports; decisions/theses/forecasts; bootstrap pack. | Cross-cutting input to all dossiers. | **Do not split into a new dossier unless baseline shows a gap.** Treat as dependency already present in docs. |

## 4. Merges / Renames / Splits

### Merges

1. **Decision lifecycle + non-actions as first-class learning objects → “Decision and non-action lifecycle.”**
   - Reason: PRD decision types already include `watch`, `skip`, `hold`, `invalidate_thesis`, `update_thesis`, and `review`; separating non-actions would duplicate lifecycle analysis.
2. **Fresh-session bootstrap context pack + agent work queue overlap:** keep separate but tightly linked.
   - Bootstrap is a read/packaging concept for session start.
   - Work queue is the durable set of pending obligations that bootstrap should include.
3. **Forecast-vs-market diagnostics + replay/regression overlap:** keep separate.
   - Diagnostics explain what happened in recorded market/forecast terms.
   - Replay/regression tests whether a new agent/model/playbook would behave differently on recorded cases.
4. **Strategy lifecycle + playbook lifecycle overlap:** keep separate.
   - Strategies describe edge theses / setup families.
   - Playbooks codify process rules. PRD explicitly treats them as orthogonal.
5. **Recall receipts + source provenance overlap:** keep separate.
   - Recall receipts prove what internal memory was surfaced.
   - Source provenance proves external/evidentiary basis supplied by the agent.

### Renames

- “Agent run/session identity” should be investigated as **Agent/run attribution and continuity keys** if a dossier is opened, to avoid implying a new runtime session manager.
- “Fresh-session bootstrap context pack” should remain exactly named because it captures the key agent-only pain point.
- “Machine-checkable playbook predicates” should be framed as **narrow predicate eligibility**, not as a general rule engine.
- “Multi-agent handoff protocol” should be reframed as **handoff packet over existing continuity primitives** if revisited later.

### Splits

1. **Playbook concepts split into two questions:**
   - Machine-checkable predicates: which rules can be deterministically evaluated?
   - Reflection-to-policy quarantine: when may subjective reflection promote into playbook policy?
2. **Continuity concepts split into three questions:**
   - Identity/attribution keys.
   - Bootstrap pack.
   - Work queue / next actions.
3. **Evaluation concepts split into three questions:**
   - Forecast-vs-market diagnostics.
   - Strategy lifecycle diagnostics.
   - Replay/regression over recorded cases.

## 5. Dependency Graph Narrative

The dependency graph starts with **agent/run identity** and the existing append-only event/ledger model. Identity does not by itself solve continuity, but it tags who wrote, recalled, reviewed, and resolved each artifact. From there, **decision and non-action lifecycle** provides the core stream of reviewable trading intent: theses, forecasts, snapshots, decisions, outcomes, reviews, and non-actions.

**Recall receipts** depend on the memory layer and the decision lifecycle because a receipt is useful only when it can be tied to later decisions, reviews, strategies, or playbook changes. **Source provenance** is a parallel evidence dependency: it records why a thesis/decision/reflection believed something, while recall receipts record which internal memories were surfaced.

**Work queue / next actions** depends on decisions and forecasts becoming due, watches becoming stale, sources being missing/stale/contradictory, and strategies/playbooks needing review. It should feed the **fresh-session bootstrap context pack**, which is the main continuity artifact consumed at session start. The bootstrap pack in turn should include pointers to queued work, active strategies, unresolved forecasts, relevant recall results, playbook state, and caveats.

**Forecast-vs-market diagnostics** consume forecasts, snapshots, outcomes, scoring, source quality, and strategy filters. Those diagnostics feed **reflection-to-policy quarantine**, because policy changes should be supported by more than one subjective reflection when possible. Quarantine then gates changes to playbook rules and informs **machine-checkable predicate** selection.

**Strategy lifecycle** cuts across the graph: it scopes decisions, recall, reports, reflections, and playbook adherence. Strategy state is also a major component of bootstrap and replay. **Replay/regression evaluation** sits downstream of almost everything: it requires recorded decisions/non-actions, original forecasts/outcomes, recall receipts, playbook versions, and strategy state to test whether changed models/prompts/rules would have produced better context use or process decisions.

**Multi-agent handoff** should be downstream of bootstrap/work-queue/identity. A handoff protocol without these primitives risks becoming a generic agent collaboration feature rather than a trading-shaped Trade Trace primitive.

## 6. Recommended Investigation Order

1. **Current-system baseline alignment** — confirm which parts are implemented versus planned before dossiers rely on them. The research contract requires not treating planning docs as implemented truth.
2. **Agent/run attribution and continuity keys** — quick supporting dossier or baseline section: determine whether current common metadata is enough.
3. **Decision and non-action lifecycle** — establish the canonical lifecycle all other concepts reference.
4. **Work queue / next actions** — define pending obligations generated from the lifecycle without introducing a scheduler.
5. **Fresh-session bootstrap context pack** — synthesize identity, lifecycle, queue, recall, playbook, and strategy state into the session-start problem.
6. **Recall receipts** — evaluate whether recall telemetry is sufficient and how receipts should be used in decisions/reviews.
7. **Forecast-vs-market diagnostics** — investigate retrospective diagnostics from supplied snapshots/outcomes only.
8. **Strategy state and lifecycle** — assess whether first-class strategies need richer point-in-time/hypothesis lifecycle for agentic continuity.
9. **Reflection-to-policy quarantine** — define safe promotion boundaries from subjective reflection to playbook/policy.
10. **Machine-checkable playbook predicates** — only after quarantine and available decision fields are understood.
11. **Replay/regression evaluation substrate** — downstream synthesis over recorded cases, recall receipts, strategies, playbooks, and diagnostics.
12. **Multi-agent handoff protocol** — defer until single-agent continuity artifacts are stable.

## 7. Deferred or Excluded Concepts

### Deferred

- **Multi-agent handoff protocol:** useful but not first-order; it should reuse bootstrap packs, work queues, recall receipts, and run identity rather than define new primitives prematurely.
- **General strategy versioning:** PRD currently documents mutable strategy rows with update events and defers a separate `strategy_versions` table until point-in-time hypothesis queries become load-bearing. Research should test whether this is load-bearing, not assume it.
- **Generic automatic rule engine:** only narrow, explicitly modeled predicates should be investigated now.
- **Background scheduling / daemonized reminders:** external orchestrators should trigger agents; Trade Trace can expose due work but should not become a scheduler.
- **Richer forecast types / multiclass/scalar scoring:** PRD defers non-binary scoring; agentic diagnostics should not depend on it for Phase 0.

### Excluded

- Trade execution, order routing, broker APIs, wallet/key handling, signing, or order cancellation.
- Market-data fetching, price polling, venue connectors, webhooks, or automatic outcome fetching.
- Human dashboards, social/community features, leaderboard features, or human-first journal UX.
- Generic agent memory unrelated to trading-shaped objects.
- Claims that diagnostics produce profit, alpha, recommendations, or financial advice.
- Backtesting or market simulation engines; replay/regression may use recorded artifacts only.

## 8. Risks of Overlap / Scope Creep

1. **Bootstrap pack becoming a dashboard:** keep it JSON-first, bounded, token-budgeted, and citation/ID-oriented rather than visual or human UX oriented.
2. **Work queue becoming a scheduler:** record and expose obligations; do not run cron, alert, page, or fetch data.
3. **Forecast-vs-market diagnostics becoming advice:** retrospective diagnostics can report calibration, edge claims, spread/liquidity context, and outcomes; they must not recommend trades.
4. **Replay/regression becoming backtesting:** replay recorded context and agent decisions; do not synthesize missing market data or simulate fills.
5. **Playbook predicates becoming a general rules engine:** only rules with explicit data fields and deterministic predicates should be considered.
6. **Reflection quarantine becoming human approval workflow:** the product is agent-only; quarantine should be machine-readable provenance/status, not a human UI gate.
7. **Multi-agent handoff becoming generic collaboration:** handoff must be trading-shaped and downstream of continuity primitives.
8. **Run/session identity becoming execution orchestration:** identity tags records and retrieval behavior; it should not imply process launching or lifecycle management.
9. **Strategy state duplicating tags or playbooks:** preserve PRD’s separation: strategies group edge theses, tags subclassify, playbooks codify process rules.
10. **Memory receipts over-logging sensitive context:** receipts should capture IDs/query/provenance and respect local/security boundaries; avoid turning them into unbounded transcript storage.

## 9. Downstream Bead Update Recommendations, if any

Observed from this subagent prompt only; no Beads were inspected or mutated.

Recommended controller-side updates before dossier work:

1. Ensure downstream dossier beads use the canonical names in this artifact.
2. Rename/merge any separate “non-actions” dossier into **Decision and non-action lifecycle** unless the parent plan requires a narrow sub-dossier.
3. Make **Fresh-session bootstrap context pack** a primary synthesis consumer, because it ties together the central user intent.
4. Mark **Agent run/session identity** as supporting/cross-cutting unless baseline work shows a first-class run entity is needed.
5. Defer **Multi-agent handoff protocol** until after continuity, queue, recall receipts, and bootstrap dossiers complete.
6. Split playbook research into **Reflection-to-policy quarantine** and **Machine-checkable playbook predicates** to avoid conflating safety gates with predicate mechanics.
7. Add a downstream synthesis checkpoint that explicitly rejects any concept requiring execution, data fetching, scheduler, or human dashboard surfaces.

## 10. Evidence / Basis — cite user intent from prompt and repo docs inspected

### User-stated intent from prompt

- Trade Trace is a local, open-source, AI-only journal, memory, and calibration substrate for LLM trading agents.
- The program is research-only and no-implementation.
- The investigation should reason from the difference between human traders and LLM/agents: fresh sessions, cron-triggered runs, no implicit personal memory, machine-readable retrieval needs, persistent strategy/process state, and auditable self-improvement.
- Canonical starting concepts to normalize include: agent run/session identity; decision lifecycle; recall receipts; fresh-session bootstrap context pack; agent work queue / next actions; non-actions as first-class learning objects; forecast-vs-market diagnostics; strategy state and lifecycle; machine-checkable playbook predicates; reflection-to-policy quarantine; replay/regression evaluation substrate; multi-agent handoff protocol.

### Repo docs inspected

- `docs/research/agentic-trade-trace/00-research-contract.md`
  - Observed: program purpose is to evaluate evolution from AI-only journal into agentic continuity, memory, calibration, and process-control substrate.
  - Observed: in scope includes fresh-session continuity, durable tracking of theses/forecasts/decisions/non-actions/strategies/reflections/playbook rules/recall behavior, machine-readable MCP/CLI/JSON-first abstractions, local-first operation, and evidence-backed product decisions.
  - Observed: out of scope includes human dashboards, execution, market-data fetching, profitability claims, generic memory, and implementation.
  - Observed: concept taxonomy must normalize names, duplicates/overlaps, dependencies, investigation order, defer/exclude concepts, and child bead framing.
- `README.md`
  - Observed: product describes itself as local, open-source, AI-only journal, memory, and calibration substrate for LLM trading agents; exposes MCP and CLI with JSON-first contracts; never executes trades.
  - Observed: current status text claims storage, event log/idempotency, reports/integrity diagnostics, typed memory graph, first-class strategies, versioned playbooks, MCP schema discovery, optional embeddings, and backup/restore have landed. This artifact treats README status as documentation evidence, not independently verified implementation.
  - Observed: “What this is not” excludes execution, remote service/human UI, generic memory, backtesting, tax accounting, social platform, or financial advice.
- `docs/VISION.md`
  - Observed: Trade Trace is a grader and memory, not a trader; no data fetching; no human dashboard; JSON/MCP/CLI surfaces; agent is primary persona.
  - Observed: product principles include decision-before-outcome, every decision reviewable including skips/watches, process separated from P&L, local-first, MCP/CLI JSON-first, auditability, memory/ledger separation, and agent judgment retained outside the system.
  - Observed: four-layer self-improvement loop: deterministic reports, coach packet, agent reflection, playbook evolution; strategy-scoped recall/reports/reflection are part of the vision.
- `docs/PRD.md`
  - Observed: MVP scope includes manual ingestion, strategies, outcome entry, binary scoring, deterministic reports/coach, reflection, playbook versioning, token-budgeted recall, and source/evidence capture.
  - Observed: no trading-data fetching and no execution are locked decisions.
  - Observed: common metadata includes `agent_id`, `model_id`, `environment`, and `run_id` as optional segmentation fields on major records.
  - Observed: decisions include watch/skip/hold/review/invalidate/update types; watches can carry review deadlines.
  - Observed: memory graph includes memory nodes, memory recall events, signals, and edges; reports include calibration, watchlist, unscored forecasts, playbook adherence, audit/source diagnostics, and deferred trading-native reports such as forecast-vs-market edge.
  - Observed: strategies are first-class, orthogonal to playbooks and tags, with active/archived state and report/recall filters.

### Inferences and recommendations

- Inference: bootstrap context and work queue are central because the product question emphasizes fresh stateless agents and cron-triggered runs.
- Inference: recall receipts are necessary for auditable memory usefulness, not just retrieval quality.
- Inference: non-actions should be merged into the decision lifecycle because repo docs already model skips/watches/holds as decisions.
- Recommendation: multi-agent handoff should be deferred until the single-agent continuity model is stable.

## 11. Side Effects — files written, memory retained, external side effects, implementation changes

Files written:

- `docs/research/agentic-trade-trace/02-concept-taxonomy.md`

Memory retained: none.

External side effects: none; no network fetches were run.

Implementation changes: none; no code, schemas, tests, README/PRD/VISION, Beads, config, or implementation-bearing files were edited.
