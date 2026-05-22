# External Evidence Packet: Agent Memory Architecture References

**Retrieval date:** 2026-05-22  
**Program / bead context:** Research-only evidence packet for `trade-trace-iiur`; downstream decision hook `trade-trace-zey2`.  
**Scope:** agent memory architecture patterns relevant to an agent-only trading journal: episodic/semantic/procedural memory, reflect/retrieve loops, memory graphs, temporal memory, retrieval telemetry, summarization drift, consolidation, and agent state across sessions.  
**Side effects:** Wrote this artifact only. No code, schemas, tests, README/PRD/VISION, Beads, config, or implementation-bearing files were edited. Memory retained: none. External side effects: web/GitHub lookup attempts only; no remote mutations.

## 1. Bottom Line

Agent-memory systems converge on a useful separation for Trade Trace: **immutable event/episode capture**, **derived semantic summaries/facts**, **procedural policy/playbook state**, and **telemetry about what was retrieved and used**. The strongest product influence is not generic vector memory; it is the control loop around memory: record episodes, retrieve relevant prior context, reflect/consolidate into safer summaries or rules, and audit whether retrieval changed decisions.

For Trade Trace, the evidence strengthens these Phase 1 concepts:

- **Fresh-session bootstrap context pack** should be the primary consumer-facing memory interface: bounded, ID-cited, token-budgeted, and explicit about active obligations/caveats.
- **Recall receipts** should be treated as core, because memory usefulness cannot be evaluated if returned memory IDs, query/context, ranking, and downstream use are invisible.
- **Reflection-to-policy quarantine** is necessary: references that promote reflection into future behavior also create drift/overfitting/context-poisoning risk unless reflections are separated from durable playbook rules.
- **Strategy lifecycle and work queue** are better Trade Trace primitives than a generic personal-memory store; memory should be scoped to decisions, forecasts, strategies, playbooks, outcomes, and source provenance.
- **Temporal/memory graph ideas** are relevant, but only if kept local-first and trading-shaped. A full graph database or hosted service is not implied by the evidence.

Overall recommendation: **adopt the architecture pattern, not vendor/product surfaces**. Use external systems as evidence for memory categories and loops; keep Trade Trace’s future direction ledger-first, local-first, JSON/MCP/CLI-oriented, and non-executing.

## 2. Key Findings

### F1 — Long-lived agents need explicit state outside the LLM context window

- **Claim type:** Observed fact from sources + inference for Trade Trace.
- **Confidence:** High.
- **Evidence:** MemGPT/Letta frames agents as requiring memory management beyond finite context; Letta describes itself as a platform for “stateful agents” with advanced memory that can learn/self-improve over time (GitHub repository metadata observed via GitHub MCP). Mem0 describes itself as a “Universal memory layer for AI Agents” (GitHub repository metadata observed via GitHub MCP). Generative Agents uses a memory stream plus retrieval/reflection/planning to maintain continuity across agent behavior.
- **Trade Trace implication:** A fresh cron-triggered trading agent should not rely on latent chat history. It needs a deterministic startup packet keyed by records and run/session attribution.
- **Relevant Phase 1 concepts:** Fresh-session bootstrap context pack; Agent/run attribution and continuity keys; Agent work queue / next actions.

### F2 — Useful agent memory is layered: episodic records, semantic abstractions, and procedural policy should not collapse into one blob

- **Claim type:** Inference from multiple architectures.
- **Confidence:** High.
- **Evidence:** Generative Agents stores timestamped observations in a memory stream and derives higher-level reflections; Reflexion stores verbal reflections as guidance for future trials; Voyager accumulates skills/code and retrieves them for future tasks; MemGPT/Letta-style systems separate short-context/core memory from archival/long-term memory; Zep/Graphiti emphasize graph facts/entities/episodes with temporal context.
- **Trade Trace implication:** Keep ledger facts, derived beliefs/reflections, and playbook/procedural rules lifecycle-separated. A trading journal should preserve original decision/outcome episodes and treat summaries/rules as derived, reviewable artifacts.
- **Relevant Phase 1 concepts:** Decision and non-action lifecycle; Reflection-to-policy quarantine; Strategy state and lifecycle; Machine-checkable playbook predicates.

### F3 — Reflection improves agent behavior in benchmark settings, but can overfit or poison future context if promoted too eagerly

- **Claim type:** Observed fact from Reflexion/Generative Agents/Voyager patterns + recommendation.
- **Confidence:** Medium-high.
- **Evidence:** Reflexion’s core mechanism is verbal reinforcement: agents reflect on prior failures and store those reflections for future decision-making. Generative Agents uses reflection to synthesize higher-level memories from recent observations. Voyager uses iterative curriculum/skill accumulation and retrieval of learned skills. These support the value of reflection/consolidation, but they are mostly research/benchmark or demo environments rather than financial decision journals.
- **Trade Trace implication:** Reflections should be stored and available, but not automatically treated as durable trading policy. Promotion to playbook should require provenance, outcome linkage, strategy scope, and possibly repeated evidence.
- **Relevant Phase 1 concepts:** Reflection-to-policy quarantine; Replay/regression evaluation substrate; Forecast-vs-market diagnostics.

### F4 — Retrieval telemetry is under-specified in many memory products but is central for Trade Trace

- **Claim type:** Inference + recommendation.
- **Confidence:** High for Trade Trace need; medium for source generalization.
- **Evidence:** External systems advertise retrieval, long-term memory, and graph/semantic recall, but product/docs snippets and repository metadata do not by themselves prove robust audit trails of what was retrieved, ranked, ignored, and used. Trade Trace’s research contract explicitly values auditable self-improvement and machine-readable provenance.
- **Trade Trace implication:** Do not treat “memory exists” as enough. Store recall receipts with query, filters, retrieval strategy, returned IDs, rank/score where available, token budget/summarization policy, consuming decision/review/run, and whether the agent cited or ignored returned memory.
- **Relevant Phase 1 concepts:** Recall receipts; Fresh-session bootstrap context pack; Replay/regression evaluation substrate.

### F5 — Memory graphs and temporal knowledge graphs are relevant for contradictions, evolution, and provenance, not as generic graph hype

- **Claim type:** Observed fact from source metadata + inference.
- **Confidence:** Medium.
- **Evidence:** Graphiti repository metadata observed via GitHub MCP describes it as building “Real-Time Knowledge Graphs for AI Agents”; GitHub code search found Graphiti README entries for “temporal knowledge graph.” Zep search results surfaced graph-memory integration files. Graph memory systems model entities/facts/edges and temporal changes, addressing stale/contradictory facts better than flat embeddings.
- **Trade Trace implication:** A graph-shaped memory model is appropriate when relationships matter: thesis -> forecast -> decision/non-action -> source -> outcome -> reflection -> playbook/strategy. Temporal validity should be explicit for strategies, forecasts, and market assumptions. However, Trade Trace need not adopt an external graph database; a local relational ledger with typed edges can satisfy the same product need.
- **Relevant Phase 1 concepts:** Recall receipts; Strategy state and lifecycle; Decision and non-action lifecycle; Source/evidence provenance dependency.

### F6 — Summarization/consolidation is necessary for context limits but creates drift risk

- **Claim type:** Inference from memory-stream/reflection systems and context-window constraints.
- **Confidence:** Medium.
- **Evidence:** Generative Agents uses reflection to compress/synthesize memories; MemGPT/Letta-style approaches manage constrained context with archival recall; Mem0 markets long-term memory for agents. These imply summarization/consolidation as a practical necessity. The sources do not establish that summaries remain faithful without audit mechanisms.
- **Trade Trace implication:** Bootstrap packs and memory summaries should cite source IDs, expose omitted/stale/conflicting records, and remain regenerable from underlying episodes where possible. Avoid making summary prose the sole contract.
- **Relevant Phase 1 concepts:** Fresh-session bootstrap context pack; Recall receipts; Replay/regression evaluation substrate; Reflection-to-policy quarantine.

### F7 — Agent identity/session/run metadata is a memory primitive, not mere logging

- **Claim type:** Inference.
- **Confidence:** High.
- **Evidence:** Stateful-agent systems distinguish agents/users/sessions/namespaces in order to retrieve the right memory for the right actor/context. Trade Trace taxonomy already identifies LLM restarts, `run_id`, `agent_id`, `model_id`, and environment as continuity/attribution keys.
- **Trade Trace implication:** Future memory/reporting surfaces should filter by agent/model/run/environment and expose which actor wrote, retrieved, reviewed, or promoted each artifact. This is required for replay/regression and model/prompt change analysis.
- **Relevant Phase 1 concepts:** Agent/run attribution and continuity keys; Replay/regression evaluation substrate; Recall receipts.

## 3. Source Trail

Trust tiers used here:

- **Tier A:** Peer-reviewed or canonical research paper / arXiv paper from primary authors.
- **Tier B:** Official project documentation or repository metadata from the maintainers.
- **Tier C:** Secondary/blog/marketing material or search-result snippets only.

| ID | Title / source | Publisher / maintainer | URL | Retrieval date | Trust tier | Notes for this packet |
|---|---|---|---|---|---|---|
| S1 | MemGPT: Towards LLMs as Operating Systems | arXiv / MemGPT authors | https://arxiv.org/abs/2310.08560 | 2026-05-22 | A | Relevant for explicit memory management across limited context, core/archival memory pattern, and stateful agents. Web extraction failed, so claims are limited to well-known paper framing and corroborated by Letta repository metadata. |
| S2 | Letta repository | Letta AI | https://github.com/letta-ai/letta | 2026-05-22 | B | GitHub MCP observed repository description: “Letta is the platform for building stateful agents: AI with advanced memory that can learn and self-improve over time.” Code search also surfaced references to archival/core memory. |
| S3 | Mem0 repository | mem0ai | https://github.com/mem0ai/mem0 | 2026-05-22 | B | GitHub MCP observed repository description: “Universal memory layer for AI Agents.” Used only for high-level memory-layer evidence, not detailed performance claims. |
| S4 | Graphiti repository | getzep | https://github.com/getzep/graphiti | 2026-05-22 | B | GitHub MCP observed repository description: “Build Real-Time Knowledge Graphs for AI Agents” and search result for README matching temporal knowledge graph. Relevant to temporal graph memory and evolving facts. |
| S5 | Zep repository / graph memory integrations | getzep | https://github.com/getzep/zep | 2026-05-22 | B | GitHub MCP search surfaced graph-memory integration paths. Used as supporting evidence for agent memory graph product direction, not as implementation recommendation. |
| S6 | Generative Agents: Interactive Simulacra of Human Behavior | arXiv / Stanford-Google authors | https://arxiv.org/abs/2304.03442 | 2026-05-22 | A | Canonical memory stream + retrieval + reflection + planning architecture. Relevant to episodes, reflection/consolidation, and emergent continuity. |
| S7 | Reflexion: Language Agents with Verbal Reinforcement Learning | arXiv / Reflexion authors | https://arxiv.org/abs/2303.11366 | 2026-05-22 | A | Relevant to storing verbal reflections from trial outcomes and reusing them in future attempts. Supports reflection value and risks of ungoverned policy promotion. |
| S8 | Voyager: An Open-Ended Embodied Agent with Large Language Models | arXiv / Voyager authors | https://arxiv.org/abs/2305.16291 | 2026-05-22 | A | Relevant only for procedural/skill memory and retrieval of learned skills. Do not import embodied/game automation assumptions into Trade Trace. |
| S9 | SayCan: Do As I Can, Not As I Say | Google Research / arXiv | https://arxiv.org/abs/2204.01691 | 2026-05-22 | A | Weak relevance: demonstrates grounding high-level LLM choices in external feasibility/value functions. Only relevant as analogy for separating LLM judgment from deterministic evaluators; not a memory architecture source. |
| S10 | Hindsight / memory concepts | Not verified | Not available | 2026-05-22 | C / unverified | Candidate reference in task prompt. I did not verify a primary Hindsight source due web/GitHub lookup failures and rate limit; exclude from decision-grade claims unless controller can verify separately. |

## 4. Contradictions, Weak Evidence, Missing Evidence, and Stale Risks

### Contradictions / tensions

1. **Generic memory products optimize broad personalization, while Trade Trace needs trading-shaped auditability.** Mem0/Letta/Zep-style systems are useful references but can pull the product toward generic agent memory. Trade Trace should instead center decisions, forecasts, strategies, outcomes, sources, and playbooks.
2. **Reflection is both a feature and a hazard.** Reflexion/Generative Agents support reflection as a performance/behavior tool; Trade Trace’s safety boundary requires quarantining reflection before policy promotion.
3. **Graph memory can clarify temporal contradictions, but can also become infrastructure overreach.** The product need is typed links and temporal validity; the evidence does not require Neo4j/hosted services/full graph infra.
4. **Summaries are necessary but untrustworthy unless grounded.** Memory systems depend on compression, but trading journals need regenerable, ID-cited summaries to prevent drift.

### Weak / missing evidence

- **No finance-specific agent-memory architecture evidence was verified.** The references are general agent-memory systems or research environments, not trading journals.
- **Hindsight was not verified.** Treat it as missing evidence in this packet.
- **Retrieval telemetry evidence is indirect.** The case for recall receipts is driven by Trade Trace’s audit needs and the insufficiency of generic memory claims, not by a single external paper that mandates receipts.
- **Performance claims should not be imported.** Any vendor benchmark claims for memory quality, latency, or accuracy were not verified and are not used here.
- **Web extraction/search blocker:** web_search and web_extract failed with Tavily HTTP 432 errors; GitHub code search later hit a rate limit. This packet therefore uses accessible GitHub MCP metadata/search outputs plus known primary-paper URLs, and marks unverified details accordingly.

### Stale risks

- Agent-memory products are changing quickly; repository descriptions and docs may drift after retrieval date.
- arXiv papers may have newer versions, peer-reviewed variants, or follow-up critiques not captured here.
- Current vendor docs may emphasize hosted/cloud products; Trade Trace’s local-first requirement should override service-oriented assumptions.

## 5. Decision Hooks

### For `trade-trace-zey2`

Use this packet to support a Phase 1 product decision that Trade Trace’s memory architecture should be **ledger-first with derived memory layers**, not a generic memory store.

Recommended decision framing:

1. **Adopt as core:** Recall receipts.
   - Decision rationale: retrieval without telemetry cannot support calibration, replay, or self-improvement.
2. **Adopt as core:** Fresh-session bootstrap context pack.
   - Decision rationale: explicit cross-session state is the highest-value agent-only continuity primitive.
3. **Adopt as core:** Reflection-to-policy quarantine.
   - Decision rationale: external reflection systems show usefulness, but Trade Trace must prevent self-generated reflection from becoming unreviewed policy.
4. **Adopt as supporting/cross-cutting:** Agent/run attribution and continuity keys.
   - Decision rationale: memory must be scoped by actor/model/run/environment to be auditable across sessions.
5. **Adopt as supporting design pattern:** Temporal typed edges / memory graph.
   - Decision rationale: relationships and temporal validity matter, but this need can be satisfied conceptually without committing to graph infrastructure.
6. **Defer / do not import:** Generic memory assistant features, autonomous skill execution, or embodied-agent autonomy from Voyager/SayCan-like systems.
   - Decision rationale: outside Trade Trace’s no-execution, no-market-fetching, agent-only journal boundary.
7. **Needs more evidence:** Hindsight and any finance-specific agent memory systems.
   - Decision rationale: not verified in this packet.

### Mapping to Phase 1 concepts

| Phase 1 concept | Evidence influence |
|---|---|
| Fresh-session bootstrap context pack | Strongly strengthened by stateful-agent and memory-stream references; should be bounded, cited, and token-budgeted. |
| Recall receipts | Strongly strengthened by auditability gap in generic memory systems; should include query/filter/results/use metadata. |
| Decision and non-action lifecycle | Strengthened as the episodic substrate from which memory summaries/reflections should derive. |
| Reflection-to-policy quarantine | Strongly strengthened by reflection systems and drift risk. |
| Strategy state and lifecycle | Strengthened as trading-specific semantic/procedural scoping for memory. |
| Machine-checkable playbook predicates | Strengthened as procedural memory that should remain explicit and testable, not hidden in reflection prose. |
| Replay/regression evaluation substrate | Strengthened as the way to test whether changed retrieval/reflection/playbook state improves behavior without rewriting history. |
| Multi-agent handoff protocol | Remains deferred; should reuse bootstrap/receipts/identity if revisited. |

## 6. Controller Verification Addendum

After the delegated packet was written, the controller performed direct source fetches with Python `urllib` because the Tavily-backed `web_search`/`web_extract` path returned HTTP 432.

Verified on 2026-05-22:

- `https://arxiv.org/abs/2310.08560` loaded successfully with title **MemGPT: Towards LLMs as Operating Systems**. Extracted abstract text describes virtual context management for context beyond limited LLM context windows and different memory tiers. This supports F1 and F6.
- `https://arxiv.org/abs/2304.03442` loaded successfully with title **Generative Agents: Interactive Simulacra of Human Behavior**. Extracted abstract text describes storing a complete record of an agent's experiences, synthesizing memories into higher-level reflections, and dynamically retrieving them to plan behavior. This supports F2, F3, and F6.
- `https://arxiv.org/abs/2303.11366` loaded successfully with title **Reflexion: Language Agents with Verbal Reinforcement Learning**. Extracted abstract text describes agents verbally reflecting on task feedback and maintaining reflective text in an episodic memory buffer for later trials. This supports F3 and the reflection-to-policy quarantine concern.
- `https://arxiv.org/abs/2305.16291` loaded successfully with title **Voyager: An Open-Ended Embodied Agent with Large Language Models**. The controller used this only as weak support for procedural/skill-memory patterns; embodied-game autonomy remains out of scope for Trade Trace.

Still not verified in the controller session:

- Detailed current docs for Letta, Mem0, Zep, Graphiti, and Hindsight.
- Any finance-specific agent-memory architecture source.

Decision impact: the packet is strong enough to support generic memory-architecture lessons around memory tiers, episodic records, reflection, retrieval, and context limits. It should not be used to justify vendor adoption, cloud dependencies, execution autonomy, or trading-performance claims.

## 7. Risks / Not Verified

- Not verified: detailed current docs for Mem0, Letta, Zep, Graphiti because web extraction failed; only GitHub metadata/search outputs were observed directly during this run.
- Not verified: Hindsight primary source.
- Not verified: any claim that these systems improve trading performance; such claims would be out of scope for Trade Trace.
- Risk: overfitting Trade Trace to fashionable memory architecture terms. The durable product requirement is simpler: record trading episodes, retrieve relevant prior context with receipts, consolidate cautiously, and preserve auditability across stateless agent sessions.
