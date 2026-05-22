# Synthesis: Agent Decision-Control Surface

**Date:** 2026-05-22  
**Synthesis bead:** `trade-trace-9o5h`  
**Inputs:** `trade-trace-m364`, `trade-trace-t4sr`, `trade-trace-sdym`, `trade-trace-n958`  
**Status:** Research synthesis only — no implementation approval

## 1. Bottom Line

Trade Trace’s “decision-control surface” should not control trading. It should control **agent process continuity**.

The coherent model is:

```text
Non-action/lifecycle cases define unresolved intent
  → work queue exposes process obligations
  → playbook predicates audit narrow recorded-rule compliance
  → reflection-to-policy quarantine prevents subjective lessons becoming unvetted rules
  → bootstrap/replay consume these surfaces without execution/advice
```

Recommended classification:

| Concept | Decision | Confidence | Role in decision-control surface |
|---|---|---:|---|
| Agent work queue / next actions | Adopt core as derived surface first | Medium-high | The process-obligation layer: what the next stateless run must inspect or resolve. |
| Non-actions as learning objects | Adopt supporting under lifecycle | High need / medium object boundary | Converts watches/skips/holds/defers/updates/reviews into material reviewable cases without a separate source-of-truth table yet. |
| Reflection-to-policy quarantine | Adopt core | High need / medium thresholds | Stops one subjective reflection from becoming durable playbook/process policy without evidence. |
| Machine-checkable playbook predicates | Adopt supporting | Medium | Adds deterministic audit for narrow rule classes while preserving self-report and advisory boundaries. |

The minimum viable research conclusion: **Trade Trace should expose due process, evidence gaps, rule-adherence gaps, and policy-candidate status as machine-readable audit surfaces; it should not schedule, fetch, execute, block trades, or recommend trades.**

## 2. Inputs Consumed

- `docs/research/agentic-trade-trace/concepts/agent-work-queue-next-actions.md`
- `docs/research/agentic-trade-trace/concepts/non-actions-first-class-learning-objects.md`
- `docs/research/agentic-trade-trace/concepts/reflection-to-policy-quarantine.md`
- `docs/research/agentic-trade-trace/concepts/machine-checkable-playbook-predicates.md`
- Supporting upstream synthesis: `docs/research/agentic-trade-trace/synthesis/foundational-continuity.md`
- Supporting external synthesis: `docs/research/agentic-trade-trace/synthesis/external-evidence.md`

## 3. Proposed Decision-Control Architecture

### 3.1 Control target

The system does **not** control orders, exposures, market actions, or recommendations. It controls whether an agent has a reliable machine-readable view of:

- what prior ideas/actions/non-actions exist;
- what process obligations are due;
- what evidence/source/memory/playbook gaps exist;
- which rules were self-reported vs machine-auditable;
- which reflections are merely subjective vs policy candidates vs promoted playbook rules;
- what must be reviewed before future sessions change behavior.

### 3.2 Architecture layers

```text
Source-of-truth records
  - decisions and non-actions
  - theses, forecasts, outcomes
  - sources and source edges
  - strategies and playbooks
  - playbook adherence rows
  - memory/reflection/playbook_rule nodes
  - recall events/receipts
  - positions/projections where relevant

Derived decision-control surfaces
  - lifecycle/non-action materiality and status
  - work queue / next actions
  - playbook predicate audit states
  - reflection quarantine and policy candidate status
  - bootstrap sections and replay bundles
```

### 3.3 Core flow

1. **Agent records a meaningful decision or non-action.**  
   Non-actions are material if they encode intent, rejection, deferment, thesis state change, playbook evidence, due review, or scanner-selected opportunity.

2. **Reports derive process obligations.**  
   The work queue surfaces due forecasts, stale watches, missing sources, missing reflections, missing adherence, strategy/playbook review candidates, exposure/projection checks, and recall-use gaps.

3. **Playbook adherence remains honest self-report.**  
   The agent can say followed/overridden/not-applicable/considered, with reasons. Machine checks may later disagree or say not-computable.

4. **Narrow predicates audit only recorded facts.**  
   Examples: forecast present, watch has review deadline, source count/freshness fields exist, required decision field exists, timestamp ordering, numeric thresholds over caller-recorded values. Anything needing source prose interpretation or live market data remains self-reported.

5. **Reflection enters quarantine, not policy.**  
   Reflections can be recalled and reviewed, but playbook/policy promotion requires evidence bundle, scope, repeated pattern or explicit one-off exception, outcome/calibration support, recall/source provenance, contradiction check, and supersession semantics.

6. **Bootstrap and replay consume decision-control surfaces.**  
   A fresh session reads obligations/caveats before acting. Future replay can evaluate whether different prompts/models/rules would handle the same recorded cases differently.

## 4. Dependency / Overlap Map

| Surface | Depends on | Feeds | Overlap / resolution |
|---|---|---|---|
| Non-action learning cases | Decision lifecycle, forecasts, sources, playbook adherence, recall, reflection | Work queue, bootstrap, missed-opportunity review, strategy lifecycle | Keep as lifecycle interpretation, not separate table until dogfood proves need. |
| Work queue / next actions | Lifecycle state, reports, source quality, forecasts, positions, adherence, reflection gaps, recall gaps | Bootstrap, strategy review, replay, external orchestrator | Derived queue first; durable work items only if ack/snooze/assignment/stable identity needed. |
| Machine-checkable predicates | Playbook rules, decision fields, forecasts, sources, outcomes, adherence rows, strategy scope | Playbook adherence reports, reflection quarantine, replay | Machine status is audit signal separate from agent self-report. |
| Reflection quarantine | Reflections, outcomes, calibration, sources, recall receipts, adherence, strategy/playbook scope | Playbook version proposals, bootstrap caveats, replay cases | Reflection can influence context, but not become durable policy without evidence. |
| Bootstrap pack | All decision-control surfaces plus foundational continuity | Next agent run | Bootstrap reports process obligations/caveats, not advice. |
| Replay/regression | Historical lifecycle, receipts, predicates, outcomes, policy versions | Evaluation and future policy safety | Replay is retrospective over recorded facts, not backtest/market simulation. |

## 5. Anti-Advice / Anti-Execution Boundary Analysis

The decision-control surface is valuable precisely because it keeps the agent disciplined without taking over trading.

| Temptation | Why it is dangerous | Boundary-safe formulation |
|---|---|---|
| “Next action: buy/short/exit” | Becomes trade advice/execution direction. | “Process obligation: inspect due forecast / review stale watch / record outcome if caller has evidence.” |
| Queue as scheduler/daemon | Turns Trade Trace into orchestration infrastructure. | Queue is read-only process data; external cron/orchestrator decides when to run agents. |
| Predicate fail blocks trade | Becomes risk engine or broker pre-trade control. | Predicate fail is audit diagnostic; agent may still record override with reason. |
| Source quality fetches URLs | Violates no-fetch/local-first boundary. | Source diagnostics only inspect caller-recorded metadata and attachments. |
| Reflection auto-promotes rule | Context poisoning and overfitting risk. | Reflection becomes candidate; promotion requires evidence and scope. |
| Missed opportunity ranks trades | Could become recommendation/alpha surface. | Missed-opportunity review is retrospective using caller-supplied outcomes/opportunity facts. |
| Work queue stores arbitrary tasks | Becomes generic task manager. | Items must derive from trading artifacts and close through trading-journal state. |
| Machine-checking natural-language rules | Hides LLM judgment as deterministic truth. | Only closed predicate families over explicit fields are checkable. |

Hard rule for future specs: decision-control outputs should be framed as **process readiness, audit gaps, due reviews, and evidence requirements**. They must not say what trade to place.

### 5.1 Machine-Auditable Boundary Invariants

Any future decision-control surface should be rejectable by review if it violates one of these invariants:

- **No trade sizing:** output must not compute or recommend position size, quantity, leverage, or risk allocation except by reporting caller-recorded historical fields.
- **No enter/exit recommendation:** output must not say buy, sell, short, cover, enter, exit, add, reduce, or hold as a recommended market action. It may cite an existing recorded decision of that type.
- **No broker/execution call:** output must not call or imply access to broker/order-routing APIs.
- **No market-data fetch requirement:** output must not require Trade Trace to fetch live or historical market data, URLs, broker positions, or outcomes. It may request caller-supplied evidence.
- **No “best trade” ranking:** output must not rank instruments/opportunities by attractiveness or expected profit. Ranking may use process urgency, due time, missing evidence severity, or audit risk only.
- **No automatic policy mutation:** output must not promote a reflection into playbook policy without an explicit quarantine/promotion decision and evidence bundle.
- **No hidden LLM rule evaluation:** output must not present natural-language rule interpretation as deterministic predicate status.
- **No human-dashboard dependency:** output must remain machine-readable and consumable by CLI/MCP/JSON clients.

### 5.2 Surface Contract Table

| Surface | Allowed consumer | Allowed output | Forbidden output | Falsifier / escalation |
|---|---|---|---|---|
| Work queue / next actions | Fresh-session agent, bootstrap pack, external orchestrator | Due process obligations, source refs, closure conditions, required external input, suggested process tool calls | Trade recommendations, scheduler state, arbitrary tasks, live-data fetch requests | If agents need ack/snooze/assignment/stable identity, research durable work items separately. |
| Non-action lifecycle cases | Bootstrap, work queue, review/replay agents | Material watches/skips/holds/defers/reviews with reasons, deadlines, evidence links, review status | Logging every no-op, ranking skipped trades by future profit, treating absence as a decision | If overlogging dominates context, tighten materiality thresholds; if missed cases vanish, add review-selection semantics. |
| Playbook predicate audit | Adherence reports, quarantine, replay | `pass`/`fail`/`not_applicable`/`not_computable`/`ambiguous` over explicit recorded fields | Natural-language rule execution, order blocking, external fact checks, “bad trade” judgments | If useful rules require semantic/source interpretation, keep them self-reported and narrow predicate scope. |
| Reflection quarantine | Playbook/version review agents, bootstrap caveat sections | Candidate lessons, evidence bundles, promotion eligibility diagnostics, contradiction and low-N caveats | Auto-promoted rules, globalized one-off lessons, unscoped policy, advice phrasing | If policy candidates pile up unused, simplify promotion thresholds; if poisoned rules emerge, strengthen quarantine. |
| Bootstrap pack | Fresh cron/stateless agent | Bounded startup state, due work, caveats, recall receipts, IDs for drilldown | Dashboard prose, opportunity rankings, execution instructions, uncaveated omissions | If token budget hides obligations, add per-section counts/cursors and stricter truncation policy. |
| Replay/regression | Evaluation agent, future review agent | Historical case bundles, original context, predicate/receipt/outcome evidence, comparison diagnostics | Backtest claims, simulated fills, profitability promises, rewritten history | If replay needs first-class run/session boundaries, revisit AgentRun as durable object. |

Closure status for this memo: **complete for research synthesis and downstream validation planning**. It is not an implementation architecture-ready spec; sample JSON fixtures, exact schemas, and tool contracts would require a separately authorized implementation/spec phase.

## 6. Minimum Viable Research Conclusion

The smallest coherent future product direction is:

1. **Derived work queue in bootstrap.**  
   Start as report-style derived obligations, not durable tasks.

2. **Material non-action semantics.**  
   Define when watches/skips/holds/defers/reviews are material, due, closed, terminal, or review-selected.

3. **Adherence honesty split.**  
   Keep agent self-report. Add conceptual machine-status only for narrow recorded predicates.

4. **Policy quarantine.**  
   Reflections may inform future agents, but policy promotion must cite evidence and remain auditable/reversible.

5. **No advice/execution.**  
   Every surface returns IDs, due states, gaps, caveats, closure conditions, and suggested process tool calls — never market actions.

## 7. Recommendations

### R1. Adopt the decision-control surface as a product frame.

Confidence: high.  
It clarifies how Phase 2 concepts fit: not “more logs,” but process-control primitives for stateless agents.

### R2. Start derived-first for work queue and non-action status.

Confidence: medium-high.  
Existing ledger/report surfaces already supply many obligations. Durable queue/task state should be justified by dogfood failures such as inability to snooze, acknowledge, assign, preserve stable item IDs, or track partial progress.

### R3. Treat machine-checkable predicates as audit-only.

Confidence: high.  
They are useful for catching mismatch between self-report and recorded facts, but must not block writes or imply trade quality.

### R4. Make policy quarantine core before expanding playbook automation.

Confidence: high.  
If the product lets agents learn, it must also prevent subjective lessons from becoming unbounded policy.

### R5. Feed these findings directly into strategy/replay/multi-agent research.

Confidence: high.  
Strategy lifecycle needs queue/review/policy context; replay needs predicates and receipts; multi-agent handoff should reuse queue/bootstrap/quarantine state rather than invent collaboration primitives.

## 8. Open Questions / Falsifiers

### Work queue

- Are derived obligations stable enough across runs for idempotent handling?
- Is there a need for durable ack/snooze/accepted-risk state?
- What queue categories are core vs noise?

### Non-actions

- Should `skip` ever support explicit review deadlines, or should aggregate/missed-opportunity sampling handle it?
- Does `defer` need a first-class decision type?
- What materiality vocabulary prevents both under-logging and over-logging?

### Predicates

- What closed predicate families cover enough useful rules without becoming a rule engine?
- Where should future predicate declarations live if ever implemented?
- How should machine status disagreement with self-report be reported?

### Quarantine

- What repeated-pattern threshold is enough for policy promotion?
- Which severe one-off risk-control reflections can bypass repeated evidence, and how should they be labeled?
- How should contradiction checks and low-N warnings be represented?

Falsifier for the whole decision-control framing: if dogfood agents using only existing low-level reports/records can reliably recover due work, non-actions, adherence gaps, and policy state without missed obligations or context poisoning, then the decision-control surface may remain a documentation/usage recipe rather than a future product primitive.

## 9. Downstream Hooks

This synthesis should feed:

- `trade-trace-nm7a` — strategy state and lifecycle: strategy reviews and scoped rules need decision-control context.
- `trade-trace-4d5e` — forecast-vs-market diagnostics: calibration/outcomes are inputs to queue and quarantine.
- `trade-trace-34c2` — replay/regression: replay should consume lifecycle, receipts, predicate status, and quarantine state.
- `trade-trace-d8kr` — multi-agent handoff: defer until bootstrap/work queue/receipts/quarantine form the handoff packet.
- `trade-trace-9lgd` — cross-concept dependency/conflict map: decision-control should be a major cluster under foundational continuity.

## 10. Side Effects

Files written:

- `docs/research/agentic-trade-trace/synthesis/agent-decision-control-surface.md`

Memory retained: none.  
External side effects: none.  
Implementation changes: none; no code, schema, tests, README/PRD/VISION, config, or runtime files were edited.
