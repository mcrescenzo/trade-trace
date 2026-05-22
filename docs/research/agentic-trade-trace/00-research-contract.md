# Agentic Trade Trace Research Contract

**Date:** 2026-05-22  
**Program bead:** `trade-trace-4epz`  
**Phase bead:** `trade-trace-tka6`  
**Status:** Research-only operating contract

## 1. Purpose

This research program investigates how Trade Trace should evolve from a capable AI-only trading journal into a more complete substrate for agentic trading continuity, memory, calibration, and process control.

The central product question is:

> What would make Trade Trace genuinely useful to a fresh-session LLM trading agent that needs to resume prior market reasoning, track its ideas and decisions over time, evaluate strategy performance, and refine its own process without relying on human-facing journal UX?

The program exists to produce decision-grade research artifacts. It does **not** authorize implementation.

## 2. Product boundary

Trade Trace is being evaluated as an **agent-only** tool.

In scope:

- Fresh-session continuity for cron-triggered or otherwise stateless trading agents.
- Durable tracking of theses, forecasts, decisions, non-actions, strategies, reflections, playbook rules, and recall behavior.
- Machine-readable MCP/CLI/JSON-first product abstractions.
- Local-first operation with no required remote service.
- Evidence-backed product decisions about which concepts should become first-class primitives later.
- Research artifacts, concept dossiers, synthesis memos, advisor critiques, and final ranked recommendations.

Out of scope:

- Human trading dashboards or human-first UX.
- Trade execution, order routing, broker integrations, wallet/key handling, or signing.
- Market-data fetching, venue connectors, price polling, webhooks, or outcome fetching.
- Claims of profitability, financial advice, or autonomous edge generation.
- Generic agent memory functionality that is not trading-shaped.
- Code, schema, migration, test, API, CLI, MCP, packaging, runtime, config, or release implementation during this research program.

## 3. Anti-implementation rule

This program may create, update, or close Beads and may write research artifacts under:

```text
docs/research/agentic-trade-trace/
```

It must not modify implementation-bearing files, including but not limited to:

- `src/`
- `tests/`
- migrations or schema definitions
- `pyproject.toml`
- public README/PRD/VISION/product docs outside this research artifact tree
- MCP/CLI registry or tool contracts
- release/checklist artifacts

Implementation ideas discovered during research must be recorded only as **candidate future recommendations** in research artifacts or future backlog suggestions. They must not be implemented, specced as executable build tasks, or treated as approved scope.

## 4. Artifact taxonomy

Use these artifact classes consistently.

### 4.1 Research contract

Defines program scope, evidence standards, artifact templates, close rules, and no-implementation guardrails.

### 4.2 Current-system baseline

Maps current repo/docs/source capabilities against proposed agentic concepts. Must distinguish:

- implemented behavior observed in source/tests/tool registry;
- planned or aspirational behavior documented in PRD/VISION/architecture docs;
- partial support;
- current gaps;
- doc/status drift.

### 4.3 Concept taxonomy

Normalizes proposed concepts before deep research. Must identify:

- canonical names;
- duplicates/overlaps;
- dependencies;
- investigation order;
- concepts to defer or exclude;
- any child beads whose framing should be updated later.

### 4.4 Concept dossier

A focused artifact for one proposed product concept.

Required shape:

```markdown
# Concept Dossier: <canonical concept name>

## 1. Question
<The specific product question this dossier answers.>

## 2. Bottom Line
- Recommendation: <adopt core | adopt supporting | defer | reject | needs more evidence>
- Confidence: <high | medium | low>
- Why: <brief evidence-tied explanation>

## 3. Agent-Specific Problem
<Why this matters for LLM/agent traders specifically, not human traders.>

## 4. Current Trade Trace Baseline
<What already exists, with file/doc references. Separate implementation from planning docs.>

## 5. Candidate Product Shape
<The conceptual object/interface/lifecycle, without implementation details.>

## 6. Required Data / State
<What durable state the concept needs and which existing primitives it may depend on.>

## 7. Machine Interface Implications
<How an agent would inspect/use this through CLI/MCP/JSON surfaces. No UI assumptions.>

## 8. Evidence
- Repo evidence:
- External evidence, if used:
- User-stated intent:
- Inferences:

## 9. Risks and Failure Modes
<Context poisoning, stale ideas, false calibration, overfitting, scope creep, etc.>

## 10. Dependencies and Conflicts
<Upstream/downstream concept dependencies and any conflict with product principles.>

## 11. Open Questions / Falsifiers
<What would change this recommendation.>

## 12. Decision Hook
<Which synthesis/decision bead consumes this artifact.>
```

### 4.5 Synthesis memo

Combines several dossiers into a higher-level product model. Must include:

- upstream artifacts consumed;
- concepts strengthened/weakened;
- dependency map;
- conflicts/tradeoffs;
- recommended primitive set;
- explicit rejects/deferments;
- decision questions enabled for the next phase.

### 4.6 External evidence packet

For source-heavy research, follow the evidence-packet standard:

- bottom line;
- key findings with claim type and confidence;
- source trail with URL/title/publisher/retrieval date/trust tier;
- contradictions, weak evidence, missing evidence, and stale risks;
- decision hooks.

### 4.7 Decision record

A decision artifact classifies each candidate concept as:

- **Adopt as core primitive** — central to Trade Trace's agentic identity.
- **Adopt as supporting primitive** — useful, but downstream or secondary.
- **Defer** — promising but not needed for the next product direction.
- **Reject / out of scope** — conflicts with product boundary.
- **Needs more evidence** — plausible but not decision-safe yet.

Each decision must trace to prior artifacts and state the product consequence without authorizing implementation.

## 5. Evidence standards

Material claims must be labeled as one of:

- **Observed fact** — directly seen in repo files, command output, bead text, or cited source.
- **User-stated intent** — explicitly stated by Michael in the conversation or durable memory.
- **Inference** — reasoned conclusion from observed facts and/or user intent.
- **Recommendation** — judgment about what to do later.
- **Open question** — unresolved but material.

Confidence labels:

- **High** — direct repo evidence or multiple strong sources with limited contradiction.
- **Medium** — credible but incomplete evidence, or a reasonable inference from current artifacts.
- **Low** — weak, stale, single-source, speculative, or contradicted evidence.

Rules:

1. Do not present planning docs as implemented truth.
2. Do not treat subagent summaries as proof; verify artifacts or source references in the controller session.
3. Do not hide contradictions or status drift.
4. Do not call a concept “core” merely because it sounds useful; tie it to agent-only necessity and Trade Trace boundaries.
5. Every artifact must state whether it wrote files, retained memory, or caused external side effects.

## 6. Bead close rules

A `Research:` bead may close only when:

1. An artifact exists, or the bead note contains an equivalent complete artifact.
2. The artifact distinguishes observed facts, user intent, inferences, recommendations, and open questions.
3. Repo evidence and/or external source evidence is named.
4. The artifact states adopt/defer/reject/needs-more-evidence where applicable.
5. The artifact identifies which downstream synthesis or decision bead consumes it.
6. The bead close note includes artifact path and no-implementation confirmation.

A `Synthesize:` bead may close only when:

1. It consumes all required upstream artifacts.
2. It names dependencies and conflicts between concepts.
3. It identifies candidate product primitives.
4. It rejects or deprioritizes some ideas, rather than summarizing everything positively.
5. It emits decision questions for the next stage.

A `Decide:` bead may close only when:

1. The decision traces to prior artifacts.
2. Adopted, deferred, rejected, and evidence-insufficient concepts are explicitly classified.
3. The consequence is framed as future product direction only.
4. No implementation is authorized.

The final closeout bead may close only when it verifies:

- all required artifacts exist;
- all research/synthesis/decision beads are closed, deferred, or superseded with notes;
- advisor critique was incorporated or explicitly rejected with rationale;
- `git diff` confirms no implementation-bearing files changed;
- implementation candidates remain recommendations only.

## 7. Advisor and research-agent use

Use advisor review at major gates:

- after Phase 0 taxonomy/baseline/contract if the taxonomy changes materially;
- after major synthesis artifacts;
- before the final ranked product direction packet closes.

Use research agents/subagents for:

- repo baseline inspection;
- source-heavy external research;
- independent concept dossier drafting;
- critical review of synthesis artifacts.

The controller session remains responsible for:

- Beads mutation;
- artifact verification;
- synthesis;
- final decisions;
- no-implementation proof.

## 8. Adding new scope

If research discovers a missing concept:

1. Record it in the current artifact as a candidate.
2. Decide whether it is a duplicate, subcase, or genuinely new concept.
3. If it needs research in this program, create a new `Research:` bead labeled `agentic-research`, `no-implementation`, `product-investigation`, `research-only`, and `trade-trace`.
4. Relate it to the root epic and wire it to the appropriate synthesis or gate bead.
5. Do not create implementation beads in this program.

## 9. First-phase decision gate

The taxonomy gate (`trade-trace-vcfx`) may close only when these Phase 0 artifacts exist and agree:

- this research contract;
- current-system baseline;
- concept taxonomy.

The gate should confirm:

- which canonical concept names downstream beads will use;
- whether any planned child beads need rename/note updates;
- whether any concepts should be deferred before dossier work begins;
- that the research-only boundary remains intact.

## 10. Side effects

Files written:

- `docs/research/agentic-trade-trace/00-research-contract.md`

Memory retained: none.  
External side effects: none.  
Implementation changes: none.
