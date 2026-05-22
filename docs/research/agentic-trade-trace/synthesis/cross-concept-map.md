# Cross-Concept Dependency and Conflict Map

**Date:** 2026-05-22  
**Synthesis bead:** `trade-trace-9lgd`  
**Inputs:** foundational continuity, external evidence, decision-control surface, evaluation/learning architecture  
**Status:** Research synthesis only — implementation candidates are not approved for implementation

## 1. Executive Conclusion

Trade Trace becomes genuinely useful for agentic trading when it stops being “a log” and becomes a **local continuity, decision-control, and evaluation substrate for stateless LLM traders**.

The strongest product thesis:

> A fresh trading agent should start each run from bounded, cited, caveated state; know what prior ideas and obligations exist; prove what memory it retrieved and used; evaluate forecasts and strategy process over time; and quarantine subjective lessons before they become durable policy — all without fetching market data, executing trades, or producing advice.

## 2. Concept Classification

### Must-have / foundational

| Concept | Classification | Confidence | Why |
|---|---|---:|---|
| Fresh-session bootstrap context pack | Must-have | High | Directly solves cron/fresh-session continuity. Product flagship. |
| Decision and non-action lifecycle | Must-have | High | Preserves unresolved intent, due work, watches/skips/holds/reviews, and learning cases. |
| Recall receipts | Must-have | High for need; medium for scoring | Proves memory was retrieved/used/ignored; necessary for memory usefulness and replay. |
| Strategy state and lifecycle | Must-have | High for scoping; medium for richer states | Strategy is the edge-thesis boundary for memory, reports, calibration, replay, and policy scope. |
| Forecast/calibration diagnostics | Must-have | High | Main objective-ish process feedback; Brier/reliability/base-rate/source caveats. |

### Core next layer

| Concept | Classification | Confidence | Why |
|---|---|---:|---|
| Agent work queue / next actions | Core, derived-first | Medium-high | Converts due forecasts, stale watches, missing reflections/sources/adherence, and strategy reviews into process obligations. |
| Reflection-to-policy quarantine | Core | High need; medium thresholds | Prevents subjective reflections from becoming poisoned playbook rules. |
| Replay/regression substrate | Core but later-stage | Medium-high | Evaluates prompt/model/playbook/recall changes against frozen recorded cases. |

### Supporting / narrow

| Concept | Classification | Confidence | Why |
|---|---|---:|---|
| Agent/run/session identity | Supporting now; possible first-class later | Medium | Existing metadata is enough for current continuity; replay/handoff may prove need for durable AgentRun. |
| Machine-checkable playbook predicates | Supporting/narrow | Medium | Useful as audit-only deterministic checks over explicit fields; avoid rule-engine creep. |
| Non-actions as first-class learning objects | Supporting under lifecycle | High need; medium boundary | Treat as material lifecycle cases, not a separate source-of-truth object yet. |

### Defer / packet-shaped

| Concept | Classification | Confidence | Why |
|---|---|---:|---|
| Multi-agent handoff protocol | Defer standalone; packet-shaped if needed | Medium-high | Should consume bootstrap/work queue/receipts/lifecycle/strategy state; no coordination service. |

### Reject / out of product boundary

| Idea | Why rejected |
|---|---|
| Human dashboard / manual trading journal UI | Product is agent-only; human UX patterns are source material, not target surface. |
| Broker execution / order routing | Violates no-execution boundary. |
| Live/historical market-data fetching | Trade Trace stores caller-supplied snapshots/outcomes/sources only. |
| Trading advice / signal generation | Product reports process state, not what to trade. |
| Generic memory store | Memory must be trading-shaped and tied to decisions, forecasts, sources, strategies, playbooks, outcomes. |
| General task manager / scheduler / daemon | Work queue is process-obligation data; external orchestrator runs cron. |
| General rule engine / arbitrary predicates | Playbook predicates must be narrow, explicit, audit-only. |
| Backtester / simulated fills | Replay is frozen-case process evaluation, not market simulation. |

## 3. Dependency Graph

```text
Agent/run attribution
  ├─ scopes writes, recalls, reports, replay, handoff
  └─ may become first-class only if replay/handoff needs run lifecycle

Decision + non-action lifecycle
  ├─ consumes: theses, forecasts, snapshots, sources, strategies, playbooks, outcomes
  ├─ produces: active/due/resolved/unreviewed/reflected/unreflected state
  ├─ feeds: bootstrap, work queue, replay, strategy reviews, non-action learning
  └─ depends on: materiality and closure semantics

Recall receipts
  ├─ consumes: memory_recall_events, returned node IDs, typed edges, consumer artifacts
  ├─ produces: retrieved/cited/ignored/usefulness evidence
  ├─ feeds: bootstrap, decisions/reviews, replay, quarantine, memory diagnostics
  └─ depends on: attribution and typed use links

Fresh-session bootstrap pack
  ├─ consumes: strategies, lifecycle state, work queue, exposure, forecasts, playbooks, recall receipts, source caveats
  ├─ produces: bounded startup state for stateless agent
  └─ feeds: every new agent run and future handoff packet

Strategy lifecycle
  ├─ consumes: decisions, theses, forecasts, outcomes, reflections, playbooks, reports
  ├─ produces: strategy-scoped health/review/context boundary
  ├─ feeds: bootstrap, calibration, replay, quarantine, handoff
  └─ depends on: null-strategy and lifecycle-state caveats

Work queue / next actions
  ├─ consumes: lifecycle state, forecasts, watchlist, source/audit reports, adherence/reflection gaps, strategy state
  ├─ produces: process obligations and closure conditions
  ├─ feeds: bootstrap, handoff, reviews
  └─ derived-first; durable work items only if dogfood falsifies

Forecast/calibration diagnostics
  ├─ consumes: forecasts, outcomes, scores, snapshots, strategy/decision context, source caveats
  ├─ produces: Brier/log/reliability/base-rate/market-reference diagnostics
  ├─ feeds: strategy reviews, reflection quarantine, replay, bootstrap caveats
  └─ bounded to retrospective, caller-supplied data

Reflection-to-policy quarantine
  ├─ consumes: reflections, outcomes, calibration, sources, recall receipts, adherence, strategy scope
  ├─ produces: policy candidates, evidence bundles, promotion/rejection diagnostics
  ├─ feeds: playbook evolution, bootstrap caveats, replay
  └─ prevents automatic policy mutation

Machine-checkable predicates
  ├─ consumes: playbook rules, explicit predicate metadata, recorded ledger/source/forecast fields
  ├─ produces: pass/fail/not-computable/ambiguous audit state
  ├─ feeds: adherence reports, quarantine, replay
  └─ audit-only, not an execution guard

Replay/regression
  ├─ consumes: point-in-time bundles, lifecycle state, receipts, strategies, playbooks, sources, hidden outcomes
  ├─ produces: process regression diagnostics for model/prompt/playbook/recall changes
  ├─ feeds: future policy/strategy/prompt decisions
  └─ not backtesting or market simulation

Multi-agent handoff
  ├─ consumes: bootstrap, work queue, receipts, attribution, strategy/playbook caveats
  ├─ produces: handoff packet if needed
  └─ deferred; no coordination service
```

## 4. Overlap and Conflict Matrix

| Pair | Overlap | Conflict risk | Resolution |
|---|---|---|---|
| Bootstrap vs work queue | Both surface due work. | Bootstrap becomes scheduler/task manager. | Bootstrap includes queue section; queue is process data only. |
| Work queue vs scheduler | Due dates and obligations resemble cron. | Product becomes daemon/alerting infra. | External orchestrator triggers runs; Trade Trace only reports obligations. |
| Decision lifecycle vs non-actions | Non-actions are lifecycle cases. | Separate object creates duplicate source of truth. | Keep non-actions as material lifecycle interpretation for now. |
| Recall receipts vs source provenance | Both prove context. | Conflate external evidence with internal memory retrieval. | Source provenance = caller-supplied evidence; recall receipt = internal memory exposure/use. |
| Reflection quarantine vs playbooks | Both influence future process. | Reflections become policy too fast. | Reflection is candidate evidence; playbook rule requires promotion bundle. |
| Playbook predicates vs rule engine | Predicates check rules. | Arbitrary code/LLM interpretation becomes hidden automation. | Closed predicate families over explicit fields only. |
| Strategy lifecycle vs tags | Both classify records. | Tags substitute for edge-thesis scope. | Strategy is durable thesis scope; tags are free-form sub-classifiers. |
| Strategy lifecycle vs playbooks | Both shape process. | Edge thesis and process rules blur. | Strategies group opportunities; playbooks codify process. Orthogonal. |
| Forecast diagnostics vs advice | Probability/edge language resembles signal. | Product says what to trade. | Retrospective diagnostics only; no live ranking. |
| Replay vs backtesting | Both evaluate historical cases. | Replay becomes simulated trading engine. | Replay only reuses recorded artifacts, hides labels, no fills/data fetch. |
| Handoff vs coordination | Both transfer work between agents. | Locks/leases/scheduler/assignment service. | Handoff packet only; durable ownership deferred. |
| AgentRun vs metadata | Both identify runs. | First-class runtime sprawl. | Keep metadata until replay/handoff proves lifecycle need. |

## 5. Hidden Implementation Prerequisites / Candidate Backlog Seeds

These are **candidate backlog themes only**. They are not approved implementation work.

| Candidate | Why it may be needed | Dependency / trigger |
|---|---|---|
| Bootstrap context pack contract | Flagship agent startup primitive. | After final decision memo adopts core foundation. |
| Derived work-queue report | Needed to unify process obligations. | Requires lifecycle/materiality semantics and report categorization. |
| Recall receipt report/view | Needed to correlate recall events with downstream use. | Requires edge/use-link conventions. |
| Strategy health/read surface | Needed for bootstrap and strategy reviews. | Existing strategy object plus report summaries; note current strategy.show drift. |
| Forecast-vs-market diagnostic report | Needed for calibration/reference/market-context bundle. | Existing calibration/snapshot/source data; source/docs drift on scoring breadth must be resolved. |
| Reflection policy-candidate report | Needed for quarantine. | Requires evidence bundle criteria and scope/caveat taxonomy. |
| Narrow playbook predicate metadata | Useful for audit-only checks. | Only after predicate family list is decided; no general engine. |
| Replay case-bundle format | Needed for regression testing prompts/models/playbooks. | Requires bootstrap/receipt/strategy/playbook point-in-time contracts. |
| Optional AgentRun object | Could help replay/handoff. | Only if row metadata fails to reconstruct run/session boundaries. |
| Optional durable work item / handoff ack | Could support multi-agent/durable ownership. | Only if derived queue/packet dogfood fails. |

## 6. Product Boundary Risk Register

| Risk | Severity | Evidence / trigger | Mitigation |
|---|---:|---|---|
| Advice creep | High | “next action” or “edge” surfaces recommend trades. | Process wording only; no enter/exit/rank-by-profit outputs. |
| Execution creep | High | Actual-enter records mistaken for broker orders. | Keep record-only semantics explicit in every surface. |
| Market-data creep | High | Diagnostics require current prices/outcomes. | Caller-supplied data only; no fetch requirement. |
| Context poisoning | High | Reflections/rules become uncaveated context. | Recall receipts, quarantine, validity/supersession, source caveats. |
| Hindsight leakage | High | Replay/policy uses future outcomes in candidate context. | Strict `as_of`, hidden labels, late-recorded flags. |
| Overlogging | Medium-high | Non-actions/work items flood bootstrap. | Materiality thresholds and truncation/cursors. |
| False completeness | Medium-high | Bootstrap omits due work but agent treats absence as proof. | Omitted counts, filters, truncation metadata, drilldown IDs. |
| Calibration theater | Medium-high | Single scores over low-N/ambiguous data drive policy. | Bins/counts/low-N/source/outcome caveats. |
| Generic memory drift | Medium | Memory becomes personal assistant store. | Tie memory to trading artifacts and scoped recall. |
| Generic task/coordinator drift | Medium | Work queue/handoff becomes assignment system. | Derived-first queue, packet-only handoff. |
| Rule-engine drift | Medium | Playbook predicates become arbitrary logic. | Closed predicate families, audit-only state. |
| Strategy status sprawl | Medium | Proposed/dormant/superseded overcomplicate MVP. | Keep active/archived until dogfood proves richer states. |

## 7. Sequencing Recommendation

### Phase A — Product definition / final decision, no code

1. Adopt/reject/defer concept classifications.
2. Decide flagship narrative: “fresh-session continuity substrate for agentic trading.”
3. Define implementation candidate backlog only after research final review.

### Phase B — If future implementation is authorized

Recommended build-order hypothesis:

1. **Bootstrap pack contract** — because it is the agent-facing wedge.
2. **Derived work queue and lifecycle materiality** — because bootstrap needs due obligations.
3. **Recall receipts/report** — because bootstrap and replay need memory proof.
4. **Strategy health/scoping read surface** — because evaluation and bootstrap need strategy boundaries.
5. **Forecast-vs-market diagnostics** — because learning needs objective-ish process feedback.
6. **Reflection quarantine reports** — because process learning must not mutate policy unsafely.
7. **Replay case bundles** — after point-in-time context and receipts are stable.
8. **Machine predicates** — narrow audit layer, only after playbook/report semantics are stable.
9. **Multi-agent handoff packet** — only if single-agent continuity primitives prove reusable and dogfood demands handoff.

Do **not** start with multi-agent handoff, predicates, or replay. They depend on the continuity foundation.

## 8. Redundancy / Consolidation Decisions

- Merge “decision lifecycle” and “non-actions” conceptually; keep non-actions as a dedicated research lens but not a separate source-of-truth primitive.
- Treat “agent work queue” as derived process obligations, not durable task table by default.
- Treat “recall receipts” as product-level abstraction over recall events + use links; not just raw telemetry.
- Treat “strategy” as first-class scope, not tag/playbook substitute.
- Treat “multi-agent handoff” as downstream packet, not coordination layer.
- Treat “playbook predicates” as audit-only subset, not the whole playbook system.

## 9. Open Decisions for Final Decision Memo

The next decision bead should answer:

1. Which concepts are officially adopted as future product pillars?
2. Which remain supporting research-only concepts?
3. Which are deferred until dogfood falsifies current assumptions?
4. Which implementation candidates should become future backlog, if any?
5. What is explicitly rejected as out of scope?
6. What evidence remains too weak for implementation planning?

Recommended provisional answers:

- Adopt: bootstrap, lifecycle/non-actions, recall receipts, strategy scope, forecast diagnostics, reflection quarantine, work queue.
- Adopt later-stage: replay/regression.
- Adopt supporting/narrow: AgentRun if needed, playbook predicates.
- Defer: multi-agent handoff as packet.
- Reject: execution/fetching/advice/dashboard/generic memory/generic task manager/backtester.

## 10. Side Effects

Files written:

- `docs/research/agentic-trade-trace/synthesis/cross-concept-map.md`

Memory retained: none.  
External side effects: none.  
Implementation changes: none; no code, schema, tests, README/PRD/VISION, config, or runtime files were edited.
