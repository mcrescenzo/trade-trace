# Synthesis: Foundational Continuity Architecture

**Date:** 2026-05-22  
**Synthesis bead:** `trade-trace-53tq`  
**Inputs:** `trade-trace-4v7b`, `trade-trace-0frg`, `trade-trace-8iet`, `trade-trace-onja`  
**Status:** Research synthesis only — no implementation approval

## 1. Bottom Line

The minimum coherent agentic foundation for Trade Trace is a **continuity loop**, not a collection of unrelated journal tables:

```text
Agent/run attribution
  → decision + non-action lifecycle
  → recall receipts
  → fresh-session bootstrap context pack
  → next run starts with bounded, cited, caveated state
```

Recommended classification:

| Concept | Decision | Confidence | Why |
|---|---|---:|---|
| Fresh-session bootstrap context pack | Adopt core | High | It directly solves the user's core cron/fresh-session problem and assembles already-existing primitives into a startup contract. |
| Decision and non-action lifecycle | Adopt core | High | Trade Trace already models many actions/non-actions; fresh agents need one auditable lifecycle so intent and pending obligations do not vanish. |
| Recall receipts | Adopt core | High for need; medium for scoring model | Existing recall telemetry is necessary but insufficient; agents need proof of retrieved/used memory to evaluate memory usefulness. |
| Agent/run attribution and continuity keys | Adopt supporting now; possible first-class later | Medium | Current `agent_id`/`model_id`/`environment`/`run_id` metadata is enough for grouping but may not capture run lifecycle/completion if downstream work needs it. |

The immediate product direction should be: **define the foundation around read-time continuity and auditability before adding more behavior.** Do not start with multi-agent handoff, automatic policy mutation, or advanced replay. Those depend on the foundation being coherent.

## 2. Upstream Artifacts Consumed

- `docs/research/agentic-trade-trace/00-research-contract.md`
- `docs/research/agentic-trade-trace/01-current-system-baseline.md`
- `docs/research/agentic-trade-trace/02-concept-taxonomy.md`
- `docs/research/agentic-trade-trace/concepts/agent-run-session-identity.md`
- `docs/research/agentic-trade-trace/concepts/decision-non-action-lifecycle.md`
- `docs/research/agentic-trade-trace/concepts/recall-receipts.md`
- `docs/research/agentic-trade-trace/concepts/fresh-session-bootstrap-context-pack.md`

## 3. Core Product Model

### 3.1 The agent continuity problem

Observed fact / user-stated intent: the program is about trading agents that may run from cron or fresh sessions, with no reliable access to prior chat context. The system must preserve prior ideas, strategy state, decisions, non-actions, recall behavior, performance signals, and process learning in machine-readable form.

The foundation therefore has to answer four questions for each new agent run:

1. **Who/what context am I operating as?**  
   Agent/run attribution keys.
2. **What unresolved trading intent exists?**  
   Decision and non-action lifecycle.
3. **What memory did the system surface, and was it used?**  
   Recall receipts.
4. **What should I read first before forming new theses?**  
   Fresh-session bootstrap context pack.

### 3.2 Proposed conceptual architecture

```text
Recorded facts and intent
  - theses
  - forecasts
  - decisions
  - watches/skips/holds/reviews
  - outcomes
  - sources
  - strategies
  - playbook versions/adherence
  - memory nodes/reflections
  - recall events

Derived continuity surfaces
  - lifecycle state: active/due/resolved/unreviewed/reflected/unreflected
  - recall receipts: retrieved/cited/ignored/helpful/harmful candidates
  - work obligations: due forecasts, stale watches, missing reflection/adherence/source caveats
  - bootstrap packet: bounded startup state with IDs and caveats
```

The important distinction: the **ledger and memory graph remain source of truth**; continuity objects are read/synthesis/reporting surfaces unless later evidence proves new durable state is necessary.

## 4. Dependency Map

| Dependency | Meaning | Evidence basis |
|---|---|---|
| Identity → everything | `agent_id`, `model_id`, `environment`, `run_id`, `actor_id`, request/idempotency metadata scope records and recalls. | `agent-run-session-identity.md`; baseline §3/§5. |
| Decision lifecycle → bootstrap | Startup context must know active watches, due forecasts, open/paper exposure, skipped/held/review items, thesis updates, and unresolved intent. | `decision-non-action-lifecycle.md`; `fresh-session-bootstrap-context-pack.md`. |
| Recall receipts → decision lifecycle | Decisions/reviews need proof of what prior memory was surfaced and later used/cited. | `recall-receipts.md`; PRD recall telemetry references summarized in dossier. |
| Recall receipts → bootstrap | Startup packs should include memory retrieval trace/truncation/caveats so later decisions can prove context exposure. | `fresh-session-bootstrap-context-pack.md` §5/§7. |
| Bootstrap → work queue | Bootstrap should expose due work, but should not itself become scheduler/daemon. | `fresh-session-bootstrap-context-pack.md`; taxonomy §8. |
| Lifecycle + receipts → replay | Future replay/regression needs original decision state plus what memory was available/used. | `recall-receipts.md`; `agent-run-session-identity.md`. |
| Lifecycle + receipts + bootstrap → multi-agent handoff | Handoff should be deferred until these single-agent surfaces are stable. | taxonomy addendum and downstream bead note. |

## 5. Overlap and Conflict Matrix

| Pair | Overlap | Recommended resolution |
|---|---|---|
| Bootstrap pack vs dashboard | Both answer “what should I look at now?” | Keep bootstrap JSON-first, ID-rich, token-budgeted, scoped, and caveated. No human UI. |
| Bootstrap pack vs scheduler | Both include due work. | Bootstrap reports obligations; external orchestrators trigger agents. No daemon/alerting. |
| Work queue vs decision lifecycle | Due work derives from watches, forecasts, source gaps, reflections, adherence, etc. | Phase 2 should define work queue as derived/pending obligations, not generic task management. |
| Recall receipts vs source provenance | Both prove context. | Source provenance = external/caller-supplied evidence; recall receipt = internal memory retrieval/use. Keep both. |
| Run identity vs orchestration | Run lifecycle can sound like process management. | Keep identity descriptive/audit-oriented. No launching, scheduling, or execution. |
| Decision lifecycle vs non-actions | Non-actions are one part of lifecycle. | Keep non-actions as a focused sub-dossier under the lifecycle, not separate source-of-truth primitive. |
| Reflection/playbook vs recall receipts | Reflections can be retrieved and later become policy. | Require receipts/provenance and quarantine before playbook promotion. |

## 6. Minimum Coherent Foundation

The smallest product foundation worth pursuing later is not “add more reports.” It is a bounded startup-and-audit contract:

1. **Stable attribution discipline**
   - Every agent write/recall should be attributable by actor/logical agent/model/environment/run where available.
   - Missing scope should be caveated, not silently broadened.

2. **Unified lifecycle state for decisions and non-actions**
   - Trades, watches, skips, holds, review decisions, thesis updates, invalidations, unresolved forecasts, missing sources, missing adherence, and missing reflections are all part of the same continuity problem.

3. **Recall receipt abstraction**
   - Raw recall events prove what was returned.
   - Receipts should prove what was consumed/cited/ignored by later artifacts.
   - Usefulness scoring should start as multi-signal diagnostics, not one scalar reward.

4. **Fresh-session bootstrap context pack**
   - A deterministic, bounded, machine-readable pack for session start.
   - It should assemble IDs and summaries from strategies, lifecycle state, due work, exposure/watch/forecast reports, playbooks, memory recall, receipt trace, and caveats.
   - It should not fetch market data, execute trades, or recommend trades.

This foundation can be expressed as a future product thesis:

> Trade Trace should make a fresh LLM trading session start from a cited, bounded, auditable state packet rather than from memory vibes or ad hoc queries.

## 7. Sequencing Hypothesis

Recommended investigation/build-order implication:

1. **Confirm attribution discipline before new objects.**  
   Current metadata is probably sufficient for research and first product iteration; do not invent AgentRun until bootstrap/queue/receipt research proves the need.

2. **Canonicalize lifecycle before queue.**  
   Work queue depends on what counts as active, due, stale, unresolved, reflected, unreflected, source-missing, adherence-missing, etc.

3. **Define recall receipts before bootstrap finalization.**  
   Bootstrap that includes memory without retrieval/use trace risks context poisoning and later audit ambiguity.

4. **Define bootstrap before multi-agent handoff.**  
   Handoff should be a bootstrap/work-queue/receipt packet passed between agents, not a generic collaboration protocol.

5. **Quarantine policy changes after diagnostics.**  
   Reflection-to-policy quarantine should consume lifecycle outcomes, forecast diagnostics, recall receipts, and strategy context.

## 8. Risks

| Risk | Why it matters | Mitigation direction |
|---|---|---|
| Context poisoning | Bad/stale reflections can dominate future runs. | Receipts, validity windows, supersession/caveats, source quality, quarantine. |
| False completeness | A token-budgeted pack may omit important state. | Truncation metadata, filter echoes, per-section counts, drilldown IDs. |
| Metadata fragmentation | Optional `run_id`/`agent_id` can be inconsistent. | Attribution discipline and missing-scope caveats; defer first-class run object until justified. |
| Non-action noise | Logging every micro-hesitation can flood recall/reports. | Materiality thresholds and lifecycle categories. |
| Scheduler creep | Due work might become daemon/alerting. | Expose obligations only; external orchestrator runs cron. |
| Advice creep | Startup “next actions” could sound like trades to enter. | Process obligations only; never trade recommendations. |
| Implementation overreach | The foundation can tempt schema/API design immediately. | Keep this program decision-only; future implementation needs separate approval. |

## 9. Clear Recommendations

### R1. Adopt the fresh-session bootstrap pack as the flagship concept.

Confidence: high.  
Rationale: it is the clearest answer to the user’s stated fresh-session/cron problem and composes existing primitives instead of expanding scope.

### R2. Treat decision/non-action lifecycle as the source of unresolved intent.

Confidence: high.  
Rationale: the system already records many decision types; the product need is lifecycle interpretation and visibility to future sessions.

### R3. Treat recall receipts as required for auditable memory usefulness.

Confidence: high for receipt need; medium for exact scoring.  
Rationale: without receipts, bad outcomes cannot distinguish “memory not retrieved,” “retrieved but ignored,” “retrieved and harmful,” or “agent reasoning failure.”

### R4. Keep run/session identity supporting until downstream evidence proves first-class need.

Confidence: medium.  
Rationale: current metadata is useful, but first-class AgentRun risks generic agent-runtime creep unless tied to bootstrap/replay/work-queue needs.

### R5. Phase 2 should focus on durable obligations and policy safety.

Confidence: high.  
Rationale: the next ready research should clarify work queue/next actions, non-action materiality, playbook predicates, and reflection-to-policy quarantine.

## 10. Open Questions for Downstream Beads

For `trade-trace-m364` work queue:

- Are next actions derived from reports/lifecycle state enough, or does the product need first-class durable work items?
- What is the boundary between due process work and scheduler behavior?

For `trade-trace-t4sr` non-actions:

- What materiality threshold prevents over-logging while preserving missed/avoided/held ideas?
- Should `skip` ever produce later review obligations?

For `trade-trace-sdym` reflection-to-policy quarantine:

- What evidence is sufficient to promote a reflection into playbook policy?
- How should recall receipts and forecast diagnostics participate?

For `trade-trace-n958` machine-checkable predicates:

- Which rule types can be evaluated from recorded fields without a general rule engine?

For later `trade-trace-34c2` replay/regression:

- Is row-level metadata enough, or does replay need a first-class AgentRun/session boundary?

## 11. Side Effects

Files written:

- `docs/research/agentic-trade-trace/synthesis/foundational-continuity.md`

Memory retained: none.  
External side effects: none.  
Implementation changes: none; no code, schema, tests, README/PRD/VISION, config, or runtime files were edited.
