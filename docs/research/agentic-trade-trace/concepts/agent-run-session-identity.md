# Concept Dossier: Agent/run attribution and continuity keys

## 1. Question

Are Trade Trace's current `actor_id`, `agent_id`, `model_id`, `environment`, `run_id`, idempotency, and event metadata sufficient for stateless cron-triggered trading agents, or should Trade Trace later introduce a first-class AgentRun/session object?

## 2. Bottom Line

- Recommendation: adopt supporting
- Confidence: medium
- Why: Current repo evidence shows broad cross-cutting attribution fields on events, major ledger rows, memory nodes, and recall events, plus dispatcher-level actor validation and idempotency. That is enough for basic attribution, grouping, retries, and report filtering. However, it is not enough to answer session-lifecycle questions such as “what did this run intend to do?”, “did it bootstrap/review/resolve/reflect?”, “what completed or failed?”, or “what state should the next cron run inherit?” A first-class AgentRun/session object should be treated as a likely supporting primitive later, but only if downstream dossiers show that bootstrap packs, work queues, recall receipts, replay, or audit reports need a durable run boundary rather than optional `run_id` strings.

## 3. Agent-Specific Problem

Stateless LLM trading agents do not carry reliable implicit continuity between cron invocations. Each run may:

- start with no memory of prior unresolved watches, forecasts, decisions, or reflections;
- retry writes after tool failures or transport interruption;
- use a different model version or prompt while representing the same logical trading agent;
- consume prior memory and sources without leaving a clear record of what context shaped the decision;
- partially complete a cycle, leaving the next run unsure whether to resume, repeat, or skip work.

For a human trader, a day, notebook, or personal memory often supplies a session boundary. For an LLM agent, the boundary must be machine-readable. Attribution fields identify who wrote records; session identity should only become first-class if Trade Trace needs to model the lifecycle of a run as a product object, not merely label records.

## 4. Current Trade Trace Baseline

### Implemented behavior observed in source

- **Dispatcher actor identity.** `dispatch` builds response metadata with `tool`, `actor_id`, and `request_id`, validates `actor_id`, and rejects malformed actors before invoking tools (`src/trade_trace/core.py:123-132`, `148`).
- **Retry safety.** Retryable write tools require `idempotency_key` unless the caller explicitly opts out with `_allow_no_idempotency`; idempotency conflicts return typed envelope details including `event_type`, `actor_id`, `idempotency_key`, and original event id (`src/trade_trace/core.py:150-180`, `218-230`).
- **MCP identity default.** The stdio MCP adapter does not infer identity from network/session state; it uses `MCP_ACTOR_ID` or a deterministic default and still relies on shared dispatcher validation (`src/trade_trace/mcp_server.py:32-42`, `92-118`).
- **Event metadata.** The events table stores `actor_id`, `idempotency_key`, `request_id`, `agent_id`, `model_id`, `environment`, and `run_id`, with idempotency uniqueness scoped to `(event_type, actor_id, idempotency_key)` (`src/trade_trace/storage/migrations/m002_events_outbox.py:20-49`).
- **Common segmentation extraction.** `common_metadata` extracts optional `agent_id`, `model_id`, `environment`, and `run_id` from tool args (`src/trade_trace/tools/_helpers.py:181-189`).
- **Ledger row coverage.** The M1 migration includes `agent_id`, `model_id`, `environment`, and `run_id` on theses, forecasts, decisions, and outcomes (`src/trade_trace/storage/migrations/m003_m1_ledger.py:97-123`, `132-154`, `195-221`, `244-262`). Corresponding handlers pass these fields into inserts for theses, forecasts, decisions, and outcomes (`src/trade_trace/tools/ledger.py:439-450`, `598-607`, `978-993`, `1080-1089`).
- **Memory and recall coverage.** Memory nodes include the same segmentation columns (`src/trade_trace/storage/migrations/m006_memory_layer.py:46-70`). Memory recall events store `query`, `strategies_used`, `node_ids_returned`, `context_json`, `limit_k`, `as_of`, `actor_id`, and segmentation fields (`src/trade_trace/storage/migrations/m006_memory_layer.py:115-133`), and `memory.recall` writes those fields (`src/trade_trace/tools/memory.py:683-712`, `820-828`).
- **No AgentRun/session table found.** Static inspection found no first-class `agent_runs`, `sessions`, or equivalent lifecycle object in the inspected migrations/source. `run_id` is currently metadata, not an entity with status, start/end, purpose, or links.

### Planning/documentation evidence

- The PRD defines `actor_id` as the initiator used in idempotency scope and explicitly distinguishes it from `agent_id`, the logical trading-agent identifier (`docs/PRD.md:133-142`).
- The PRD says `agent_id`, `model_id`, `environment`, and `run_id` are optional reporting dimensions and never imply credentials, broker accounts, or execution (`docs/PRD.md:139-145`).
- The research taxonomy initially classifies Agent run/session identity as a supporting/cross-cutting concept and warns that it should not become runtime orchestration (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:37-40`, `140-151`).
- The current-system baseline notes segmentation fields are implemented on major rows and useful for multi-agent/model comparison, but also flags possible doc/status drift around snapshot segmentation (`docs/research/agentic-trade-trace/01-current-system-baseline.md:35-37`, `76-85`).

### Gaps and drift relevant to this concept

- `run_id` is optional and unconstrained; no observed source defines uniqueness, lifecycle, parent/child relationships, or completion state.
- Current metadata can answer “which records say they belong to run X?” but not “what was run X?”, “what was it supposed to accomplish?”, “did it finish?”, or “what should the next run inherit?”
- Snapshot segmentation is documented in PRD but was not observed in the M003 snapshot table or snapshot handler according to the baseline, so session-level reconstruction from market context may be incomplete unless later code not inspected here resolves it.
- `actor_id` and `agent_id` are separate by design. This is useful, but creates room for inconsistent caller discipline if agents do not pass the same logical metadata on all related writes and recalls.

## 5. Candidate Product Shape

Keep identity as cross-cutting metadata in the near term, and frame a possible future AgentRun/session object as a product concept with a narrow purpose:

- **AgentRun as a durable run boundary:** a record of one invocation or logical work cycle by a trading agent, model, environment, and actor.
- **Lifecycle, not orchestration:** the object would describe a run; it would not launch cron jobs, schedule agents, fetch market data, execute trades, or manage credentials.
- **Run intent and scope:** a run could conceptually carry purpose such as scan, review, resolve, reflect, replay, or maintenance; scoped strategies/instruments/watch items; and start/end timestamps.
- **Run outcome:** a run could conceptually record completed/failed/partial status, error/caveat summaries, and generated/consumed artifact IDs.
- **Continuity anchor:** downstream bootstrap packs, work queues, recall receipts, decisions, outcomes, and reflections could cite a durable run identity when the product needs to reconstruct what happened in a session.

This shape should not be promoted to core unless later research shows that optional metadata cannot support bootstrap, queue, recall, replay, or evaluation flows safely.

## 6. Required Data / State

Current fields that already exist or are documented:

- `actor_id`: initiator and idempotency scope.
- `request_id`: dispatch/envelope correlation.
- `idempotency_key`: retry-deduplication key for writes.
- `agent_id`: logical trading agent attribution.
- `model_id`: model/model-family attribution.
- `environment`: paper, actual-recorded, simulation, backtest import, or manual-review context per PRD.
- `run_id`: caller-supplied session/run identifier.
- Event rows and append-only ledger/memory/recall rows that carry some or all of these fields.

State a first-class AgentRun would likely need if adopted later:

- stable run identifier and optional parent/superseded run relationship;
- logical `agent_id`, `model_id`, `environment`, `actor_id`, and optional prompt/tooling version labels;
- start/end timestamps and status such as started, completed, partial, failed, aborted;
- declared purpose/scope, e.g. scan, review, resolve, reflect, replay;
- links or summaries of consumed context and produced records, preferably by IDs rather than transcripts;
- caveats/errors/handoff notes for the next run;
- no credentials, no external session tokens, no scheduler state, and no broker/account authority.

## 7. Machine Interface Implications

With the current baseline, agents should be able to:

- pass consistent `agent_id`, `model_id`, `environment`, and `run_id` to writes and recalls;
- use `actor_id` at the MCP/CLI boundary for initiator identity;
- rely on idempotency keys for safe retries;
- filter/group reports and recall events by attribution fields where tools expose those filters.

If AgentRun becomes first-class later, the machine interface implication should be read/JSON-oriented and bounded:

- create or declare a run boundary at the beginning of a work cycle;
- attach generated ledger/memory/recall/work-queue artifacts to that run by ID;
- close or summarize the run with status and caveats;
- query recent/incomplete runs for bootstrap and audit;
- export run-scoped bundles for replay/regression or handoff.

The interface should not become a process supervisor, cron daemon, streaming transcript store, or generic agent framework.

## 8. Evidence

- Repo evidence:
  - `docs/research/agentic-trade-trace/00-research-contract.md`: program scope includes fresh-session continuity for stateless agents and machine-readable MCP/CLI/JSON-first abstractions; implementation is out of scope.
  - `docs/research/agentic-trade-trace/01-current-system-baseline.md`: current system has event/idempotency envelopes and segmentation metadata, with drift around snapshots.
  - `docs/research/agentic-trade-trace/02-concept-taxonomy.md`: Agent run/session identity is a supporting/cross-cutting concept and must not become execution orchestration.
  - `docs/PRD.md:133-145`: common metadata defines `actor_id`, idempotency, `agent_id`, `model_id`, `environment`, and `run_id` as reporting dimensions.
  - `src/trade_trace/core.py:123-180`, `218-230`: actor validation and write idempotency enforcement.
  - `src/trade_trace/mcp_server.py:32-42`, `92-118`: MCP actor behavior and shared dispatch path.
  - `src/trade_trace/storage/migrations/m002_events_outbox.py:20-49`: events metadata and idempotency uniqueness.
  - `src/trade_trace/storage/migrations/m003_m1_ledger.py:97-154`, `195-262`: segmentation on core ledger rows.
  - `src/trade_trace/storage/migrations/m006_memory_layer.py:46-70`, `115-133`: segmentation on memory nodes and recall events.
  - `src/trade_trace/tools/_helpers.py:181-189`: common metadata extraction.
- External evidence, if used: none. No network fetches were run.
- User-stated intent: The delegated task asks specifically whether current metadata is enough for stateless cron-triggered agents or whether Trade Trace needs a first-class AgentRun/session object later; it also requires research-only/no implementation.
- Inferences:
  - Current attribution metadata is sufficient for record-level grouping and retry safety.
  - A first-class run object becomes valuable only when session lifecycle, completeness, failure recovery, or run-scoped replay becomes product-critical.

## 9. Risks and Failure Modes

- **Metadata discipline risk:** Optional `run_id` and `agent_id` can be omitted or inconsistently applied, fragmenting later reports and recall audits.
- **False continuity risk:** Grouping by `run_id` may imply a coherent session even if only some writes used that run id.
- **Over-modeling risk:** A first-class run object could become a generic agent runtime/session manager, violating the no-scheduler/no-execution/no-framework boundary.
- **Transcript bloat risk:** If run identity evolves into transcript capture, it could store excessive context, secrets, or irrelevant prompt chatter instead of trading-shaped IDs and summaries.
- **Idempotency confusion:** `idempotency_key` is for retry deduplication, not session identity. Agents may misuse one as the other unless docs/interfaces remain clear.
- **Actor/agent ambiguity:** `actor_id` initiates tool calls; `agent_id` identifies the logical trading agent. Collapsing them would damage import/admin/reviewer attribution and idempotency semantics.
- **Snapshot reconstruction gap:** If snapshots truly lack segmentation, run-scoped reconstruction of market context is weaker than PRD wording implies.

## 10. Dependencies and Conflicts

Dependencies:

- Fresh-session bootstrap context pack: may need a durable run boundary to say which prior run left which caveats and pending work.
- Agent work queue / next actions: may need run linkage for created-by, completed-by, failed-by, and carried-over obligations.
- Recall receipts: already log `run_id`; downstream research should decide whether receipts must attach to a first-class run or only to decisions/reviews.
- Decision and non-action lifecycle: decisions/non-actions already carry attribution fields and can be grouped by run.
- Replay/regression substrate: may need run-scoped bundles to reproduce what an agent knew and did in a historical invocation.
- Multi-agent handoff protocol: should remain deferred and consume stable single-agent identity/continuity primitives.

Conflicts or constraints:

- Must not conflict with local-first operation.
- Must not introduce execution, broker authority, market data fetching, webhooks, or autonomous scheduling.
- Must preserve the distinction between `actor_id` and `agent_id`.
- Must not treat planning docs as implemented truth; snapshot segmentation and report-filter coverage need verification before relying on them.

## 11. Open Questions / Falsifiers

- Do downstream bootstrap/work-queue/recall dossiers require answering “what happened in the previous run?” beyond filtering rows by `run_id`?
- Can agents reliably provide consistent `run_id` values across all writes and recalls without a first-class run declaration?
- Do current reports and filters expose enough run/agent/model/environment segmentation for practical audit and calibration, or are fields present but not usable?
- Is snapshot segmentation actually absent in live schema after all migrations, and does that matter for run-scoped reconstruction?
- Would a run object materially improve error recovery for partial cron executions, or would idempotency plus work-queue state be enough?
- Would first-class runs encourage transcript/log hoarding or generic agent-framework creep?

Falsifiers for adopting a first-class AgentRun later:

- Bootstrap, queue, recall, and replay can all be made reliable using existing row-level metadata and deterministic reports.
- Agents rarely need run-completion semantics; they only need unresolved trading artifacts and due work.
- Report/filter surfaces can expose all needed attribution without introducing a new object.

Falsifiers for keeping only metadata:

- Repeated cron failures create ambiguous partial sessions that cannot be safely resumed from row metadata.
- Recall receipt evaluation needs a run-scoped “context consumed” boundary independent of any one decision.
- Replay/regression needs original run intent/scope/status, not just artifact timestamps and `run_id` strings.

## 12. Decision Hook

This dossier should be consumed by `trade-trace-53tq`.

## 13. Side Effects

Files written:

- `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/concepts/agent-run-session-identity.md`

Files modified besides this artifact: none.

Memory retained: none.

External/network side effects: none; no network fetches were run.

Implementation changes: none; no code, schemas, tests, README/PRD/VISION, Beads, config, or other implementation-bearing files were edited.
