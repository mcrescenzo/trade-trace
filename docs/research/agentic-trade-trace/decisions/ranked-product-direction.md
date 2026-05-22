# Ranked Product Direction Packet — Agentic Trade Trace

**Date:** 2026-05-22  
**Decision bead:** `trade-trace-gwv4`  
**Program:** `trade-trace-4epz` — Agentic Trade Trace product investigation, no implementation  
**Status:** Final research decision packet; **does not authorize implementation**

## 1. Decision Scope

This packet approves only:

- product-direction priorities;
- concept classifications;
- non-goals and negative-scope boundaries;
- future candidate backlog themes that require separate approval.

This packet does **not** approve:

- code changes;
- database/schema/migration changes;
- API/CLI/MCP contracts;
- UI/dashboard work;
- runtime/scheduler/orchestration work;
- market-data fetching;
- broker/execution integration;
- public claims about trading performance;
- deployment or packaging changes.

All implementation candidates below are research-derived backlog seeds only.

## 2. Product Thesis

Trade Trace should evolve from a logging tool into a **local, agent-only continuity and evaluation substrate for stateless LLM trading agents**.

The product should let a fresh agent run answer:

1. What prior ideas, strategies, forecasts, decisions, watches, skips, and obligations exist?
2. What source evidence and internal memory were available, retrieved, used, ignored, or stale?
3. What forecasts resolved, how calibrated was the agent, and what caveats limit interpretation?
4. What process work is due before new decisions are made?
5. What reflections are merely subjective versus safe candidates for policy/playbook changes?
6. How should future prompts/models/playbooks be evaluated against prior recorded cases without hindsight leakage?

## 3. Ranked Product Direction

### 3.1 Pursue as foundational product pillars

| Rank | Concept | Classification | Confidence | Rationale | Caveat / counterevidence | Creep boundary |
|---:|---|---|---:|---|---|---|
| 1 | Fresh-session bootstrap context pack | Pursue now as flagship concept | High | Directly solves cron/fresh-session continuity; composes existing reports, strategies, lifecycle, memory, playbook, source caveats, and due work. | Needs careful token budgets, truncation metadata, and absence caveats; can start as contract/spec before implementation. | Not dashboard, scheduler, signal, or advisor. |
| 2 | Decision and non-action lifecycle | Pursue now | High | Preserves unresolved intent across decisions, watches, skips, holds, thesis updates, invalidations, reviews, forecasts, outcomes, sources, adherence, and reflection obligations. | Need materiality/closure semantics to prevent overlogging; `skip`/`defer` semantics still open. | Not separate non-action source-of-truth table by default. |
| 3 | Recall receipts | Pursue now | High for need; medium for scoring model | Existing recall telemetry proves what was returned, not what was used; receipts are required for memory usefulness, replay, and context-poisoning control. | Need decide computed view vs materialized object; usefulness scoring must be multi-signal, not one reward. | Not full transcript storage or generic memory analytics. |
| 4 | Strategy state and lifecycle | Pursue now as scoping axis | High for strategy scope; medium for richer states | Strategy is the edge-thesis boundary for recall, diagnostics, bootstrap, replay, and policy scope; avoids smearing lessons across unrelated setups. | Current implementation only has active/archived; richer proposed/dormant/superseded states need dogfood evidence. | Not tag substitute, not playbook, not live strategy-ranking engine. |
| 5 | Forecast/calibration diagnostics | Pursue now | High for retrospective diagnostics; medium for market-reference details | Brier/log/reliability/base-rate/source/outcome caveats form the clearest process-feedback spine. | External primary-source verification is partial; market-implied comparisons only when caller-supplied. | Not profitability, alpha, live signal, or market-data fetch. |

### 3.2 Pursue as core next layer

| Rank | Concept | Classification | Confidence | Rationale | Caveat / counterevidence | Creep boundary |
|---:|---|---|---:|---|---|---|
| 6 | Derived work queue / next actions | Pursue after lifecycle/bootstrap framing | Medium-high | Stateless agents need due process obligations: due forecasts, stale watches, missing sources/reflections/adherence, strategy reviews, exposure/projection checks. | Start derived-first; durable ack/snooze/owner state only if dogfood proves necessary. | Not scheduler, daemon, generic task manager, or alert system. |
| 7 | Reflection-to-policy quarantine | Pursue after diagnostics foundation | High need; medium thresholds | Lets agents reflect while preventing one subjective lesson from becoming unvetted playbook/process policy. | Promotion thresholds, repeated-pattern requirements, and low-N exceptions need spec. | Not automatic policy mutation or human approval workflow. |
| 8 | Replay/regression substrate | Pursue as core to evaluation architecture, not initial MVP/API/storage | Medium-high | Needed to test prompt/model/playbook/recall changes against frozen recorded cases without live risk. | Promote only after bootstrap, receipts, strategy/playbook point-in-time context, and expected-output schemas are stable. | Not backtester, model runner, market simulator, or performance proof. |

### 3.3 Keep supporting / narrow

| Concept | Classification | Confidence | Rationale | Promotion trigger | Creep boundary |
|---|---|---:|---|---|---|
| Agent/run/session identity | Supporting via existing metadata for now | Medium | `agent_id`, `model_id`, `environment`, `run_id`, actor/request/idempotency metadata support grouping and basic continuity. | Promote to first-class AgentRun only if replay/handoff cannot reconstruct run intent/status/completion from row metadata/events. | Not agent runtime/process manager. |
| Machine-checkable playbook predicates | Supporting, narrow audit concept | Medium | Useful to separate agent self-report from deterministic checks over explicit fields. | Pursue only after closed predicate families are defined and playbook/quarantine reports are stable. | Not general rule engine, execution blocker, or LLM rule interpreter. |
| Non-actions as first-class learning objects | Supporting under lifecycle | High need; medium object boundary | Watches/skips/holds/defers/reviews matter for agent learning and obligations. | Separate object only if lifecycle interpretation fails; otherwise keep as material lifecycle cases. | Not log-every-no-op noise. |

### 3.4 Defer

| Concept | Classification | Confidence | Rationale | Promotion trigger | Boundary |
|---|---|---:|---|---|---|
| Multi-agent handoff protocol | Defer standalone; keep as future packet shape | Medium-high | Handoff should consume bootstrap/work queue/receipts/lifecycle/strategy/playbook caveats. | Only if dogfood shows multiple agents/models need explicit packet/ack beyond row metadata + derived queue + idempotency. | No coordination service, locks, leases, scheduler, assignment system, or collaboration UI. |

### 3.5 Reject for this product direction

| Rejected direction | Reason |
|---|---|
| Human dashboard / manual journal UI | Trade Trace is agent-only; human products provide translation patterns, not UX target. |
| Broker execution / order routing | Violates product boundary and safety. |
| Market-data/outcome/source fetching | Trade Trace stores caller-supplied records; no fetching. |
| Trading advice or signal generation | The system reports state, evidence, diagnostics, and due process; it does not tell agents what to trade. |
| Generic memory store | Memory must remain trading-artifact-shaped and auditable. |
| Generic task manager/scheduler/daemon | Work queue is data; external orchestrators run agents. |
| General rule engine | Playbook checks must be narrow/audit-only over explicit fields. |
| Backtester/simulated fills | Replay evaluates process over recorded artifacts; no simulated market paths. |

## 4. Dependency / Falsifier Graph

| Concept | Depends on | Blocked-until / prerequisite | Falsifier or redesign trigger |
|---|---|---|---|
| Bootstrap pack | lifecycle, strategy scope, reports, memory recall, source caveats, work queue/receipt sections | Stable section contract and caveat/truncation policy | If existing tool recipe reliably bootstraps agents without missed obligations, pack may be a recipe/report bundle rather than first-class primitive. |
| Decision/non-action lifecycle | decision matrix, forecasts/outcomes, sources, reflections, playbook adherence | Materiality and closure semantics | If non-actions flood context or remain unused, tighten or reduce scope. |
| Recall receipts | recall events, typed use edges, consumer artifacts, attribution | Decide computed vs materialized receipt | If raw recall events + existing edges prove enough, keep receipt as report abstraction. |
| Strategy lifecycle | strategy rows, strategy IDs on artifacts, reports/recall, events | Decide whether active/archived is enough | If strategy scope is rarely used or noisy, avoid richer states. |
| Forecast diagnostics | forecasts, outcomes/scores, snapshots, source/provenance, reports | Resolve docs/source drift before claims beyond binary core | If samples are too sparse or reference classes too arbitrary, keep diagnostics caveated/limited. |
| Work queue | lifecycle, reports, due dates, source/adherence/reflection gaps | Derived item categories and closure conditions | If derived items need ack/snooze/assignment/stable IDs, consider durable work item later. |
| Reflection quarantine | reflections, outcomes, diagnostics, recall receipts, strategies/playbooks | Promotion criteria/evidence bundle semantics | If quarantine blocks useful learning, simplify thresholds; if poisoned rules emerge, strengthen criteria. |
| Replay/regression | point-in-time bundles, receipts, strategies, playbooks, hidden labels, expected output schema | Bootstrap/receipt/strategy/predicate contracts stable | If replay cannot be token-bounded without hiding key context, redesign around smaller case types. |
| AgentRun | existing metadata/events | Need observed replay/handoff reconstruction failure | If run status/intent/completion cannot be reconstructed, promote to first-class object. |
| Playbook predicates | playbook rules/adherence, explicit recorded fields | Closed predicate family list | If useful rules depend on semantic source interpretation, keep self-reported/hygiene-only. |
| Handoff packet | bootstrap, work queue, receipts, attribution, idempotency | Single-agent continuity primitives stable | If duplicate/conflicting writes occur despite idempotency/derived packets, consider durable handoff/ack state. |

## 5. Negative-Scope Matrix

| Boundary | Applies to | Hard rule |
|---|---|---|
| No dashboard | All concepts | Machine-readable CLI/MCP/JSON-first; no human workflow dependency. |
| No generic memory | Recall, bootstrap, quarantine | Memory must link to trading artifacts, strategies, forecasts, decisions, outcomes, sources, or playbooks. |
| No scheduler/task manager | Work queue, handoff, bootstrap | Expose obligations; external systems trigger runs. |
| No general rule engine | Playbook predicates, quarantine | Only explicit closed predicate families; no arbitrary code or LLM-prose execution. |
| No backtesting/simulation | Replay, forecast diagnostics | Use recorded artifacts only; no simulated fills or market paths. |
| No market fetch | Forecast diagnostics, sources, work queue | Caller supplies snapshots/outcomes/sources; Trade Trace does not fetch. |
| No broker execution | Decisions, exposure, queue | Actual decisions are journal records; no order placement. |
| No advice/signal | All concepts | Outputs are process obligations, evidence, caveats, diagnostics, not market actions. |
| No automatic policy mutation | Quarantine, playbooks | Reflections become candidate evidence, not durable policy without explicit promotion. |

## 6. Drift Appendix

Known repo documentation/source drift found during research:

| Drift | Evidence from research | Decision impact |
|---|---|---|
| `strategy.list` status name | Implementation uses `status='both'`; PRD text says `status='all'`. | Track as future docs/API cleanup; not blocker for strategy concept. |
| `strategy.show` summary counts | Implementation returns row-only; PRD describes future summary counts. | Strategy health surface should not assume counts exist today. |
| Forecast scoring breadth | Scoring docs/source indicate categorical/scalar support beyond some PRD binary-only MVP wording. | Binary forecast diagnostics are the safe core; verify non-binary before future claims/specs. |
| External source verification | Some human-journal and literature sources remain blocked/unverified. | External evidence supports direction only; do not use for public claims or implementation justifications without refresh. |

## 7. Candidate Backlog Seeds — Separate Approval Required

If Michael later approves implementation planning, candidate epics/tasks could be:

1. Specify bootstrap context pack JSON contract and caveats.
2. Specify derived work-queue categories, closure conditions, and report shape.
3. Specify recall receipt view/report correlating recall events to downstream use links.
4. Specify strategy health/read surface using current active/archived status first.
5. Specify forecast-vs-market diagnostic report around binary core and caller-supplied market references.
6. Specify reflection quarantine evidence-bundle report and policy-candidate lifecycle.
7. Specify replay case-bundle format and point-in-time context rules.
8. Specify narrow playbook predicate eligibility model.
9. Evaluate AgentRun and durable work/handoff state only after dogfood falsifies metadata/derived-first approach.

None of these are authorized by this decision packet.

## 8. Research Close Criteria

This decision packet is closeable as research because:

- all research artifacts are saved under `docs/research/agentic-trade-trace/`;
- concept classifications include confidence and scope limits;
- advisor blockers were addressed in this packet;
- external evidence weaknesses are named;
- repo doc/source drift is named;
- candidate implementation work is explicitly not approved;
- boundaries against dashboard/execution/fetching/advice/generic-memory/scheduler/rule-engine/backtester creep are explicit;
- no code, schema, test, README/PRD/VISION, config, or runtime files were changed.

## 9. Artifact Index

Key artifacts:

- `docs/research/agentic-trade-trace/00-research-contract.md`
- `docs/research/agentic-trade-trace/01-current-system-baseline.md`
- `docs/research/agentic-trade-trace/02-concept-taxonomy.md`
- `docs/research/agentic-trade-trace/synthesis/foundational-continuity.md`
- `docs/research/agentic-trade-trace/synthesis/external-evidence.md`
- `docs/research/agentic-trade-trace/synthesis/agent-decision-control-surface.md`
- `docs/research/agentic-trade-trace/synthesis/evaluation-learning-architecture.md`
- `docs/research/agentic-trade-trace/synthesis/cross-concept-map.md`
- `docs/research/agentic-trade-trace/reviews/advisor-critique.md`

Full artifact inventory should be verified in closeout bead `trade-trace-4jxm`.

## 10. Final Decision

For future product direction, **pursue Trade Trace as an agentic trading continuity substrate**, centered on:

1. fresh-session bootstrap;
2. decision/non-action lifecycle;
3. recall receipts;
4. strategy-scoped evaluation;
5. forecast/calibration diagnostics;
6. derived process obligations;
7. reflection-to-policy quarantine;
8. replay/regression later, after foundation is stable.

Defer multi-agent handoff to a packet-shaped downstream concept. Reject dashboard, execution, market fetch, advice, generic memory, generic scheduler, general rule engine, and backtester drift.

## 11. Side Effects

Files written:

- `docs/research/agentic-trade-trace/decisions/ranked-product-direction.md`

Memory retained: none.  
External side effects: none.  
Implementation changes: none; no code, schema, tests, README/PRD/VISION, config, or runtime files were edited.
