# Concept Dossier: Recall Receipts and Memory Usefulness Scoring

## 1. Question

Should Trade Trace promote raw memory recall telemetry into a first-class product primitive that lets a fresh-session trading agent prove which memories were retrieved, which were actually used in later reasoning, and whether the memory layer is useful enough to trust for continuity and self-improvement?

## 2. Bottom Line

- Recommendation: **adopt core**.
- Confidence: **high** for the need to track recall/use; **medium** for the exact scoring model.
- Why: Fresh-session agents cannot rely on latent personal memory. Current Trade Trace already logs append-only `memory_recall_events` for every `memory.recall` call and exposes returned node IDs, query, context, retrieval strategies, actor/run metadata, and recall IDs. That is necessary raw telemetry, but it is not yet the full product primitive implied by “recall receipt”: a durable, decision-linked proof object that distinguishes “memory was retrieved” from “memory was cited/used” and supports usefulness scoring without overfitting the agent’s future context.

## 3. Agent-Specific Problem

Human traders often remember why they acted, whether a prior lesson influenced them, and when a note was merely skimmed. A fresh LLM trading agent has none of that implicit continuity. Between cron-triggered runs it loses conversational context, prior retrieved snippets, and the distinction between:

1. a relevant memory not existing;
2. a relevant memory existing but not being retrieved;
3. a relevant memory being retrieved but ignored;
4. a retrieved memory being cited but not actually useful;
5. a stale or poisoned memory being retrieved and harmful.

For an agent-only journal, this distinction is load-bearing. Without auditable recall proof, later calibration cannot tell whether a bad decision was a forecasting error, a retrieval failure, an agent-judgment failure, a bad-memory-write failure, or a playbook/process failure. Recall receipts are therefore not human UX; they are an accountability layer for stateless agents that use Trade Trace as durable memory.

## 4. Current Trade Trace Baseline

### Implemented behavior observed in source/migrations

- `memory.recall` exists in `src/trade_trace/tools/memory.py` and ranks memory nodes using BM25, temporal, graph, and optional semantic retrieval, then returns `recall_id`, query, strategies used, `k`, `as_of`, `mode`, `items`, and `total_in_scope` (`memory.py:682-722`, `842-846`).
- Each returned item includes the memory node ID, node type, title, importance, recall score, source references, optional body, and optional per-strategy provenance (`memory.py:793-817`).
- Every recall writes an append-only row to `memory_recall_events` containing `recall_id`, query, strategies used, returned node IDs in top-k order, `context_json`, `limit_k`, `as_of`, `created_at`, actor identity, and optional `agent_id`, `model_id`, `environment`, and `run_id` (`memory.py:820-839`; `m006_memory_layer.py:115-153`).
- `memory_node_stats` stores recall count and last recalled time as a rebuildable projection from recall events (`m006_memory_layer.py:155-165`).
- Recall writes are side effects of a read tool from the agent’s perspective, but the telemetry table itself is append-only (`m006_memory_layer.py:115-153`).
- Recall response metadata includes retrieval parameters such as RRF constant, importance boost slope, supersession discount, strategies used, `k`, and `max_chars` (`memory.py:849-853`).
- Segmentation fields support later actor/model/run comparisons for recall behavior (`memory.py:690`, `827-828`; `m006_memory_layer.py:127-132`).

### Planning/product docs observed

- The PRD describes `memory_recall_events` as an append-only recall telemetry log that drives `memory_node_stats` and loop-usefulness traceability checks (`docs/PRD.md:319-325`).
- PRD loop-usefulness criteria require at least one `memory.recall` result to be explicitly cited in a later thesis and traceable via a `derived_from` or `supports` edge (`docs/PRD.md:574-583`).
- The dogfood protocol operationalizes “the agent did not already know this” as a combination of edges from a later thesis/decision/forecast plus a preceding `memory_recall_events` row whose `node_ids_returned` includes the memory (`docs/architecture/dogfood-protocol.md:325-345`).
- The memory-layer architecture frames recall as surfacing relevant observations, reflections, and playbook rules when forming new theses, and states recall telemetry lives in `memory_node_stats` populated from `memory_recall_events` (`docs/architecture/memory-layer.md:11-19`, `141-145`).

### Gap / product distinction

Current `memory_recall_events` are **raw recall events**: they prove what the system returned for a query at a time. A future **recall receipt** should be a product-level proof object or reportable abstraction over those events plus later usage evidence. The receipt should answer: “For this decision/thesis/review/playbook change, what memories were available, what did the agent retrieve, which returned nodes did it cite/use, and what later evidence suggests they helped or hurt?”

## 5. Candidate Product Shape

A recall receipt should be defined conceptually as a bounded, machine-readable proof packet anchored to a trading action or review artifact. It should not be an unbounded transcript.

Candidate lifecycle:

1. **Recall event emitted:** Agent calls `memory.recall` with a query, optional context such as instrument/strategy, retrieval strategies, `as_of`, and budget parameters. The system records raw telemetry.
2. **Decision/reasoning artifact written:** Agent creates or updates a thesis, forecast, decision, review, reflection, or playbook proposal.
3. **Use linkage established:** The later artifact cites returned memory nodes through typed edges such as `derived_from`, `supports`, `about`, `follows`, or `violates`, depending on artifact type.
4. **Receipt materialized or computed:** A receipt view/report correlates the recent recall event(s), returned node IDs, later edge citations, actor/run metadata, and relevant context.
5. **Usefulness evaluated later:** Outcome/scoring/reporting can compute whether cited recall preceded better calibration, avoided repeated mistakes, changed playbook adherence, surfaced uncited prior knowledge, or merely added noise.

Recommended conceptual fields:

- `receipt_id` or computable receipt key.
- `recall_id` and raw recall-event pointer.
- `consumer_kind` / `consumer_id` for the thesis, decision, forecast, review, reflection, or playbook proposal that consumed the recall.
- `actor_id`, `agent_id`, `model_id`, `environment`, `run_id`.
- `query`, `context_json`, `as_of`, retrieval strategies, budget parameters.
- `node_ids_returned` in order, with scores/provenance available from response or derived audit bundle.
- `node_ids_cited` / `node_ids_used`, computed from typed edges to the consumer artifact.
- `not_used_returned_nodes`, because ignored recall can be as informative as cited recall.
- optional later evaluation fields or report outputs: `usefulness_label`, `usefulness_score`, `harm_flag`, `not_actionable_reason`, and outcome-linked diagnostics. These should be future/report-level concepts, not automatic truth.

The key product distinction: `memory_recall_events` are **telemetry**; recall receipts are **auditable product evidence of recall consumption and usefulness**.

## 6. Required Data / State

Required existing state:

- Memory nodes with node type, body/title, confidence, importance, validity, provenance, and actor/run metadata.
- `memory_recall_events` with query/context/returned nodes/time/actor/run metadata.
- Typed edges connecting later artifacts to memory nodes.
- Consumer artifacts: theses, forecasts, decisions, reviews, reflections, playbook versions/rules.
- Outcomes and forecast scores when usefulness is evaluated against later results.
- Strategy IDs and playbook/version IDs for scoped usefulness analysis.

Additional conceptual state that may be needed later:

- A normalized “consumed recall” relation or report view mapping `recall_id` to `consumer_kind`/`consumer_id`. This can initially be computed from temporal adjacency plus edges, but explicit linkage may become necessary if agents perform multiple recalls before one decision.
- A usefulness taxonomy separating objective evidence from subjective agent labels:
  - objective: cited/uncited, retrieved/not retrieved, subsequent edge use, forecast score delta, repeated-error reduction, playbook adherence changed, stale/superseded memory retrieved;
  - subjective: agent-reported helpfulness, misleading, redundant, ignored, too broad, too stale, too verbose.
- Guardrail metadata for sensitive or redacted recall payloads if receipts include snippets rather than IDs.

## 7. Machine Interface Implications

A future machine interface should let agents inspect recall receipts through CLI/MCP/JSON without human dashboard assumptions. Candidate operations/reports, expressed conceptually rather than as implementation scope:

- Retrieve receipt(s) for a decision/thesis/review: “show which recall events and memory nodes influenced this artifact.”
- Retrieve consumers for a memory node: “show where this memory was returned, cited, ignored, or later contradicted.”
- Compare recall usefulness by strategy, agent, model, environment, run, instrument, or playbook version.
- Produce a bounded bootstrap section: “recent high-value recalled-and-used memories” and “high-recall/low-use memories that may be noise.”
- Support replay/regression: re-run old context with original `as_of`, original returned nodes, and later outcome labels to test whether a new prompt/model would use memory better.

Machine-facing response shape should prefer IDs, ranks, retrieval strategies, edge evidence, and score components over prose. Bodies/snippets should be optional and token-budgeted to avoid receipt payloads becoming transcript storage.

## 8. Evidence

- Repo evidence:
  - `docs/research/agentic-trade-trace/00-research-contract.md`: the program is research-only; in scope includes fresh-session continuity, durable tracking of recall behavior, and machine-readable abstractions.
  - `docs/research/agentic-trade-trace/01-current-system-baseline.md`: baseline identifies memory graph, recall telemetry, segmentation metadata, and strategy-scoped recall as implemented, while warning that usefulness depends on write/retrieval discipline.
  - `docs/research/agentic-trade-trace/02-concept-taxonomy.md`: recall receipts are classified as a core investigation cluster because agents need auditable proof of retrieved context and memory usefulness.
  - `src/trade_trace/tools/memory.py`: observed raw recall behavior, ranking, response shape, recall-event logging, and stats projection updates (`memory.py:682-853`).
  - `src/trade_trace/storage/migrations/m006_memory_layer.py`: observed `memory_recall_events` schema and append-only triggers; observed `memory_node_stats` projection (`m006_memory_layer.py:115-165`).
  - `docs/PRD.md`: observed recall telemetry, `memory.recall` contract, and loop-usefulness criteria requiring cited recall (`docs/PRD.md:319-325`, `359-362`, `574-583`, `590-593`).
  - `docs/architecture/memory-layer.md`: observed recall goals, memory taxonomy, confidence/decay model, and telemetry description (`memory-layer.md:11-19`, `115-145`, `285-293`).
  - `docs/architecture/dogfood-protocol.md`: observed operational definition for “agent did not already know this” using recall events plus edges (`dogfood-protocol.md:244-255`, `290-307`, `325-345`).
- External evidence, if used: none. No network fetches were run.
- User-stated intent: The delegated task explicitly asks to focus on why fresh-session agents need auditable proof of what memory was retrieved and used; to distinguish raw recall events from a future product primitive “recall receipt”; and to include memory usefulness scoring possibilities and risks of context poisoning/overlogging.
- Inferences:
  - Raw recall events are necessary but insufficient because they show returned memory, not consumption.
  - Edges from later artifacts to returned memory nodes are the current best evidence of use.
  - Usefulness scoring must remain probabilistic/report-level, because a cited memory may be performative, redundant, or harmful, while an uncited memory may still have influenced reasoning.

## 9. Risks and Failure Modes

1. **Context poisoning:** Bad reflections or stale playbook rules can be repeatedly retrieved, cited, and reinforced. Receipt/usefulness scoring should flag stale, superseded, contradicted, or high-recall/negative-outcome memories rather than blindly boosting recalled nodes.
2. **Overlogging:** Capturing full prompts, transcripts, or all recall bodies in receipts would bloat the journal and potentially expose sensitive reasoning. Prefer IDs, ranks, timestamps, strategies, and optional snippets.
3. **False usefulness:** Citation is not causation. A memory can be cited after the agent already knew it, cited for ritual compliance, or cited while being ignored substantively.
4. **Optimization gaming:** If agents optimize for usefulness metrics, they may over-cite memories or avoid exploratory recall. Metrics should report multiple signals rather than one reward-like score.
5. **Temporal ambiguity:** Multiple recalls before a decision can make it hard to know which recall informed which artifact. Explicit consumer linkage may eventually be needed.
6. **Privacy/security drift:** If semantic/API embedding paths or receipts include memory text, sensitive journal data could leave local boundaries or be over-retained. Keep local/offline defaults and receipt payloads minimal.
7. **Metric overfitting:** A memory that helped avoid one mistake may become harmful in a different market regime. Usefulness scoring should respect `as_of`, validity windows, supersession, strategy scope, and sample-size warnings.
8. **Conflating retrieval quality with reasoning quality:** A poor outcome after relevant recall may be an agent reasoning failure, not a memory failure.

## 10. Dependencies and Conflicts

Dependencies:

- Memory graph and `memory_recall_events` telemetry.
- Agent/run attribution and continuity keys.
- Decision and non-action lifecycle, because receipts need consumer artifacts.
- Source/evidence provenance and typed edges, because use must be traceable.
- Strategy state and playbook versions for scoped recall usefulness.
- Replay/regression substrate for later evaluation of whether changed prompts/models/playbooks use memory better.
- Reflection-to-policy quarantine to prevent one recalled reflection from immediately becoming policy without evidence.

Conflicts/tradeoffs:

- Stronger receipts improve auditability but risk overlogging and token bloat.
- A single scalar usefulness score is attractive for automation but conflicts with Trade Trace’s product principle that the system reports and the agent judges.
- Explicit receipt state may simplify audit but could duplicate append-only event/edge evidence if introduced too early. The first product decision should decide whether receipts are materialized records, computed reports, or both.

## 11. Open Questions / Falsifiers

- Can existing `memory_recall_events` plus typed edges reliably infer use, or do multi-recall sessions require explicit `recall_id` linkage on later artifacts?
- What is the minimum useful receipt shape for bootstrap/replay without storing full memory text?
- Which usefulness labels are objective enough for deterministic reports, and which must remain agent-authored annotations?
- Should high-recall/low-use memories be demoted, flagged for review, or merely reported?
- How should usefulness scoring handle non-actions such as skips and watches, where “helpful” may mean avoiding a bad trade rather than improving forecast score?
- What would falsify “adopt core”: if dogfood shows agents can achieve reliable continuity and self-improvement using raw recall events plus existing edges, with no need for a product-level receipt abstraction.
- What remains not verified: no end-to-end tool calls or tests were run; exact report implementations for recall/usefulness were not inspected beyond docs/source references; no Beads were inspected or mutated; no external research was used.

## 12. Decision Hook

This dossier should feed decision bead `trade-trace-53tq`. Recommended decision framing: adopt recall receipts as a **core future product primitive**, but initially define them as a computed/reportable abstraction over `memory_recall_events` plus typed use edges before committing to new durable schema. Usefulness scoring should start as multi-signal diagnostics, not a single authoritative reward score.

## 13. Side Effects

Files written:

- `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/concepts/recall-receipts.md`

Files modified besides this artifact: none.

Memory retained: none.

External/network side effects: none; no network fetches were run.

Implementation changes: none; no code, schemas, tests, README/PRD/VISION, Beads, config, or implementation-bearing files were edited.
