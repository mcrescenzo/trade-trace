# Concept Dossier: Multi-agent handoff protocol

## 1. Question

If Trade Trace eventually needs multi-agent or multi-model collaboration, what is the minimal handoff protocol that preserves agentic trading continuity without turning Trade Trace into a coordination service, scheduler, runtime, broker, or generic collaboration framework?

## 2. Bottom Line

- Recommendation: defer; define as a downstream handoff packet over existing continuity primitives, not as a standalone coordination primitive.
- Confidence: medium-high.
- Why: Phase 0 taxonomy explicitly deferred multi-agent handoff until single-agent continuity is coherent. Subsequent continuity and decision-control synthesis confirm that handoff should consume bootstrap packs, work queues, recall receipts, run attribution, lifecycle state, strategies, playbooks, and caveats. A minimal future shape is useful: a bounded, ID-rich, caveated packet that lets one agent/model/reviewer resume another agent's trading-process obligations safely. But anything resembling assignment queues, locking, agent scheduling, live coordination, or conflict resolution service is outside the current product boundary and should be rejected unless future dogfood proves row-level attribution plus append-only/idempotent writes are insufficient.

## 3. Agent-Specific Problem

A human trading desk can hand off verbally, point to screens, rely on shared institutional memory, or know who owns a book. Multiple LLM trading agents do not share implicit memory. A fresh agent/model taking over another run can easily:

- miss unresolved forecasts, stale watches, missing reflections, or source caveats left by a prior agent;
- confuse another agent's watch idea with its own active obligation;
- overwrite or duplicate writes when retrying work already attempted by a prior run;
- apply a playbook or strategy hypothesis outside the originating agent/model/environment scope;
- assume retrieved memories were considered by the prior agent when only raw recall events exist;
- treat a handoff note as authority to trade, execute, fetch data, or mutate policy;
- blur responsibility for a decision, reflection, outcome resolution, or playbook update.

The agent-specific problem is not team chat. It is machine-readable continuity transfer under stateless sessions, model changes, optional attribution fields, append-only correction semantics, and no execution/data-fetching boundary. If handoff exists, it should answer: who produced this state, what is being transferred, what remains unresolved, what evidence/context was used, what caveats constrain the next agent, and what the recipient is allowed to do.

## 4. Current Baseline

Observed facts from repo research artifacts and planning docs:

- The research contract scopes Trade Trace as an agent-only, local-first, machine-readable continuity/memory/calibration/process-control substrate and excludes human dashboards, execution, market-data fetching, generic memory, and implementation during this research program (`00-research-contract.md:20-39`).
- The taxonomy explicitly classifies “Multi-agent handoff protocol” as deferred: useful, but downstream of bootstrap packs, work queues, recall receipts, strategy state, and run identity; it warns against generic collaboration (`02-concept-taxonomy.md:15-22`, `49`, `104-119`, `121-129`, `148-151`).
- Foundational continuity synthesis states the minimum coherent foundation is agent/run attribution → decision/non-action lifecycle → recall receipts → bootstrap pack, and recommends defining bootstrap before multi-agent handoff (`synthesis/foundational-continuity.md:10-29`, `82-93`, `131-146`).
- Agent decision-control synthesis says multi-agent handoff should reuse queue/bootstrap/quarantine state rather than invent collaboration primitives (`synthesis/agent-decision-control-surface.md:191-195`, `224-232`).
- Agent/run attribution research finds current `actor_id`, `agent_id`, `model_id`, `environment`, `run_id`, request IDs, events, and idempotency are sufficient for basic attribution/grouping/retry safety, but not full run lifecycle or handoff notes (`concepts/agent-run-session-identity.md:7-12`, `25-50`, `52-63`).
- Bootstrap research defines the strongest candidate input: a deterministic, bounded startup context pack with identity/scope, active strategies, exposure, watches, due forecasts, due reviews/next actions, playbook state, important memories, recall trace, source caveats, and process tool-call hints (`concepts/fresh-session-bootstrap-context-pack.md:45-82`).
- Work queue research recommends a derived process-obligation surface first and defers durable work items unless acknowledgement/snooze/assignment/stable identity/partial-progress needs arise (`concepts/agent-work-queue-next-actions.md:48-123`, `153-185`).
- Recall receipt research distinguishes raw recall telemetry from proof of recall consumption and usefulness; receipts should show what was retrieved, cited/used, ignored, and later evaluated (`concepts/recall-receipts.md:44-72`, `93-104`).
- The PRD documents core product boundaries: local SQLite source of truth, append-only event/source tables, correction by new rows/events, CLI/MCP parity, no default outbound network, no execution, no scheduler/daemon, advisory playbooks, optional segmentation fields, and idempotency keys (`docs/PRD.md:7`, `36-47`, `49-87`, `133-145`, `194-238`, `294-300`).

Current gap: no current artifact defines what happens when one logical agent/model hands active trading-process context to another. Existing metadata can attribute records; bootstrap can assemble state; work queue can expose obligations; recall receipts can prove memory context. But there is no explicit conceptual contract for handoff scope, recipient authority, ownership caveats, conflicting-write avoidance, or when to reject handoff as out of scope.

## 5. Candidate Product Shape

The safest candidate shape is a **handoff packet**, not a coordination protocol.

A handoff packet is a bounded, deterministic, machine-readable bundle created for a recipient agent/model/reviewer that summarizes active trading-process state, unresolved obligations, evidence, recalled context, and caveats. It should be generated from existing continuity surfaces and optionally cited by later recipient actions. It should not assign work through a central service, lock rows, schedule agents, route messages, execute trades, fetch data, or arbitrate live conflicts.

Candidate packet sections:

1. **Packet metadata**
   - `handoff_id` or deterministic packet key if later needed, generated/as-of timestamp, source tool/version, truncation policy, filters, omitted counts, no-fetch/no-execution/no-advice caveats.

2. **Originator and recipient attribution**
   - originator `actor_id`, `agent_id`, `model_id`, `environment`, `run_id`; intended recipient role/agent/model/environment; whether recipient is same logical agent, replacement model, reviewer, resolver, or replay/evaluation agent.
   - Preserve `actor_id` vs `agent_id`: originator of the packet is not necessarily owner of all underlying artifacts.

3. **Purpose and authority boundary**
   - Handoff purpose such as `resume_process`, `resolve_outcomes`, `review_strategy`, `reflect_after_outcome`, `audit_sources`, `replay_case`, or `manual_review`.
   - Explicit allowed process actions and forbidden actions. Allowed examples: inspect IDs, record externally supplied outcome, write reflection, record review, attach caller-supplied source, record playbook adherence. Forbidden: place orders, fetch prices/outcomes, mutate policy automatically, assume broker truth.

4. **Transferred context from bootstrap pack**
   - Active strategies, current exposure buckets/caveats, watches, unresolved forecasts, current playbook version/rules, important memories, source caveats, and suggested process tool calls.
   - This should reuse the bootstrap pack shape where possible; handoff is a scoped bootstrap for another agent.

5. **Work queue / obligations**
   - Due process items with category, source refs, due/stale status, blocked reasons, required external input, closure conditions, and suggested process tool calls.
   - Items should be process obligations, not trade recommendations.

6. **Recall receipt and context-use trace**
   - Recall IDs, returned memory node IDs, cited/used memory node IDs where known, query/context/strategy filters, truncation and usefulness caveats.
   - If the prior agent did not establish receipt/use links, the packet should say `recall_use_unproven` rather than imply consumption.

7. **Ownership and caveats**
   - Who last touched each obligation or artifact; whether ownership is explicit, inferred, broad, missing, or conflicting.
   - Caveat codes for missing attribution, mixed agents/models/environments, stale packet, filtered-out rows, source sensitivity/redaction, unsupported scoring, missing snapshots, and unresolved external evidence.

8. **Conflict/idempotency guidance**
   - Existing IDs and recommended idempotency-key prefixes/derivation hints for recipient writes if later specs need them.
   - Prior attempted writes/events, if visible, so recipient can avoid duplicate outcome/reflection/adherence/source attachments.
   - Append-only correction rule: recipients correct by new rows/events/supersession, not by overwriting prior agent records.

9. **Recipient acknowledgement or follow-up links, if ever needed**
   - Defer durable acknowledgement, assignment, snooze, or accept-risk state unless work-queue dogfood proves derived state insufficient.
   - If later adopted, acknowledgements should be append-only process evidence over trading artifacts, not a live coordination bus.

Minimal lifecycle:

- Originator or orchestrator requests a packet for a scope and recipient.
- Packet is generated from bootstrap/work-queue/receipt/lifecycle/report state at `as_of`.
- Recipient consumes packet before acting.
- Recipient writes normal Trade Trace artifacts with its own `actor_id`, `agent_id`, `model_id`, `environment`, `run_id`, and idempotency keys.
- Later reports can compare what the handoff packet exposed versus what the recipient acted on.

## 6. Required Data / State

Required existing or already-researched state:

- Attribution: `actor_id`, `agent_id`, `model_id`, `environment`, `run_id`, request IDs, idempotency keys, events.
- Bootstrap inputs: active strategies, exposure/open positions, watches/stale watches, unresolved forecasts, playbook state, memories, source caveats.
- Work queue inputs: due forecasts, overdue/stale watches, missing reflections/adherence/sources, strategy/playbook review candidates, exposure/projection checks, recall gaps.
- Recall evidence: `memory_recall_events`, returned node IDs, context JSON, typed edges from later artifacts to memory nodes, receipt abstractions.
- Lifecycle/ledger records: theses, forecasts, decisions, outcomes, sources, reviews, strategies, playbooks, memory nodes, edges, projection caveats.
- Append-only/event state: events and idempotency records to support retry safety and duplicate-write detection.

State to defer unless falsified:

- Durable `handoff_id` records.
- Explicit assignment/owner tables.
- Locks or leases for artifacts/work items.
- Recipient acknowledgement/snooze/accept-risk state.
- Parent/child run links or first-class AgentRun handoff state.

Potential durable state becomes reasonable only if future dogfood shows that derived packets cannot support stable ownership, acknowledgement, partial progress, or conflict avoidance across multiple agents.

## 7. Machine Interface Implications

A future handoff interface should be JSON/MCP/CLI-first, read-heavy, and explicitly scoped. No UI/dashboard assumption is required.

Interface implications:

- Inputs should mirror bootstrap/report filters plus handoff-specific fields: originator scope, recipient role/agent/model/environment, purpose, `as_of`, strategies/instruments, categories, max items/chars, include/exclude sensitive content, and strictness for missing attribution.
- Output should be a structured packet with stable section names, source refs, caveats, filters echoed, counts/truncation, and drilldown IDs.
- The packet should include process-action hints only. Examples: “inspect due forecast,” “record outcome if caller supplies final evidence,” “write reflection after reviewing outcome,” “record playbook adherence,” or “attach caller-supplied source.” It must not recommend entering/exiting trades.
- Recipient actions should remain ordinary existing/future Trade Trace writes, with recipient attribution and idempotency. Handoff should not create a privileged write path.
- If durable handoff acknowledgement is ever added, it should be append-only and idempotent, scoped to packet/artifact IDs, and limited to process states like received, declined, partially handled, blocked, or accepted-risk.
- Absence must be caveated: a packet filtered to one agent/model/run cannot claim global cleanliness; mixed or missing attribution should be machine-visible.
- Conflict handling should be conservative: show existing events and source refs, warn on stale `as_of`, prefer “refresh packet before writing” over live locks.

## 8. Evidence

- Repo evidence:
  - Research contract establishes local-first, agent-only, no-execution/no-fetch/no-dashboard/no-implementation scope (`00-research-contract.md:20-39`).
  - Taxonomy defers multi-agent handoff until single-agent continuity artifacts are stable and says it should consume bootstrap packs, work queues, recall receipts, and run identity (`02-concept-taxonomy.md:49`, `104-119`, `121-129`, `148-151`).
  - Foundational continuity synthesis recommends defining bootstrap before multi-agent handoff and describes continuity derived surfaces (`synthesis/foundational-continuity.md:73-93`, `131-146`).
  - Decision-control synthesis says multi-agent handoff should reuse queue/bootstrap/quarantine state rather than invent collaboration primitives (`synthesis/agent-decision-control-surface.md:191-195`, `224-232`).
  - Agent/run identity dossier observes current attribution and idempotency are useful but not a full run lifecycle object (`concepts/agent-run-session-identity.md:25-63`).
  - Bootstrap, work queue, and recall receipt dossiers define the upstream packet components and caveats (`concepts/fresh-session-bootstrap-context-pack.md:45-82`; `concepts/agent-work-queue-next-actions.md:48-123`; `concepts/recall-receipts.md:44-72`).
  - PRD documents no scheduler, no execution, no fetch, local SQLite source of truth, append-only events, common attribution fields, and idempotency (`docs/PRD.md:36-47`, `49-87`, `133-145`, `294-300`).
- External evidence, if used: none. No network fetches were run.
- User-stated intent:
  - The delegated task asks to evaluate minimal handoff if needed; build it from bootstrap/work queue/receipts/lifecycle; include role/agent/model attribution; avoid coordination service/scheduler and conflicting writes; address idempotency, ownership/caveats, and defer/reject criteria.
- Inferences:
  - Handoff is valuable only as continuity transfer; it is not yet justified as durable coordination state.
  - Existing attribution and idempotency reduce duplicate/conflicting-write risk, but they do not by themselves provide ownership or stale-packet warnings.
  - A handoff packet can be a scoped bootstrap pack for a recipient, with work queue and recall receipts as first-class sections.

## 9. Risks/Failure Modes

- **Coordination-service creep:** Assignment, locks, leases, status dashboards, or message routing could turn Trade Trace into an agent framework. Mitigation: packet/report first; defer durable coordination.
- **Scheduler creep:** Handoffs between runs may imply dispatching agents. Mitigation: external orchestrator triggers agents; Trade Trace only exposes state.
- **Conflicting writes:** Two agents may resolve the same forecast, attach contradictory sources, or both reflect/review. Mitigation: append-only events, idempotency keys, source refs, stale-packet caveats, and supersession/correction semantics.
- **False authority:** Recipient may treat originator notes as approved strategy or trade instruction. Mitigation: explicit purpose/authority boundary and no-advice caveats.
- **Ownership ambiguity:** Optional metadata may not identify who owns an obligation. Mitigation: ownership should be explicit/inferred/missing/conflicting, never assumed silently.
- **Scope leakage:** Mixed `agent_id`, `model_id`, `environment`, or run scopes can merge experiments. Mitigation: strict filters, broadening warnings, and caveats for missing attribution.
- **Stale packets:** A generated packet can become outdated after another agent writes. Mitigation: `as_of`, event watermark, refresh-before-write warnings for stale packets.
- **Overlogging/transcript bloat:** Handoff could become full conversation transfer. Mitigation: use IDs, summaries, receipt refs, and optional snippets; avoid transcript storage.
- **Policy poisoning:** Handoff notes may smuggle unreviewed reflections into playbook-like authority. Mitigation: reflection-to-policy quarantine and rule provenance caveats.
- **Generic collaboration drift:** If packet content is arbitrary tasks/comments, product focus erodes. Mitigation: include only trading-shaped artifacts and process obligations.

## 10. Dependencies/Conflicts

Dependencies:

- Fresh-session bootstrap context pack: primary object to reuse; handoff is a recipient-scoped bootstrap plus originator caveats.
- Agent work queue / next actions: supplies unresolved process obligations and closure conditions.
- Recall receipts: prove what internal memory was surfaced and used by the originator/recipient.
- Agent/run attribution and continuity keys: identify originator, recipient, model, environment, run, actor, and idempotency scope.
- Decision and non-action lifecycle: defines active, due, resolved, reviewed, reflected, stale, and terminal work.
- Strategy lifecycle and playbook/quarantine concepts: scope obligations and prevent policy drift.
- Append-only event/idempotency model: supports duplicate-write avoidance and audit.

Conflicts/boundaries:

- Handoff vs bootstrap: do not create a parallel context format unless recipient-specific authority/ownership/caveats require it.
- Handoff vs work queue: queue items may need assignment later, but initial handoff should not assume durable task ownership.
- Handoff vs AgentRun: first-class runs may simplify handoff, but should not be introduced only to model generic sessions.
- Handoff vs scheduler/coordinator: any requirement for live locking, dispatch, webhooks, broker state, or agent assignment service is a reject/defer signal.
- Handoff vs advice: process obligations are allowed; market-action recommendations are not.

## 11. Open Questions/Falsifiers

- Can a recipient agent safely resume work using only a normal bootstrap pack filtered to its scope plus existing attribution, without a distinct handoff packet?
- Do multi-agent dogfood workflows actually occur, or is the main need model-version comparison/replay rather than live handoff?
- Is a durable handoff record needed for audit, or is generated JSON plus later recipient writes/receipts enough?
- What ownership model is acceptable: no ownership, inferred owner from source rows, explicit owner in durable work items, or packet-level intended recipient?
- How should stale-packet detection work without locks: event watermark, latest `created_at`, or report refresh?
- Do conflicting writes create real harm under append-only correction semantics, or only extra review noise?
- Does handoff need first-class AgentRun lifecycle state, or can row-level `run_id` and packet metadata suffice?
- What should happen when attribution is missing: fail closed, include with caveat, or require explicit broadening?

Falsifiers for adoption beyond defer:

- Single-agent bootstrap/work-queue/receipt flows solve continuity well enough and multi-agent use remains rare.
- Handoff requires scheduler/daemon/assignment service/locks to be useful.
- Handoff packets are mostly generic tasks or prose notes rather than trading-shaped artifacts and IDs.

Falsifiers for rejection/deep deferral:

- Agents consistently duplicate writes or lose obligations when one model/run hands off to another despite using bootstrap and queue.
- Replay/evaluation requires reconstructing originator-recipient boundaries with more fidelity than current attribution supports.
- Dogfood shows durable acknowledgement/ownership is necessary to avoid unsafe repeated outcome/reflection/source writes.

## 12. Decision Hook

This dossier should feed `trade-trace-9lgd` cross-concept dependency/conflict mapping and later final ranking/decision work for the agentic Trade Trace research program. It should also be available to `trade-trace-d8kr` closeout as a downstream/deferred collaboration concept.

Recommended decision framing: **defer multi-agent handoff as a standalone primitive**. If future evidence requires it, adopt only a minimal handoff packet built from bootstrap, work queue, recall receipts, attribution, lifecycle, strategy/playbook state, and caveats. Reject any version that requires coordination service, scheduler, broker/execution integration, market-data fetching, live locking, human dashboard, or generic task management.

## 13. Side Effects

Files written:

- `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/concepts/multi-agent-handoff-protocol.md`

Files modified besides this artifact: none.

Memory retained: none.

External/network side effects: none; no network fetches were run.

Implementation changes: none; no code, schemas, tests, README, PRD, VISION, config, Beads, memory, or implementation-bearing files were edited.
