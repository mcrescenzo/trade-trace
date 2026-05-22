# Concept Dossier: Reflection-to-Policy Quarantine

## 1. Question

Should Trade Trace treat agent-written reflections as quarantined, subjective evidence that can inform future playbook/process policy only after provenance, outcome/calibration evidence, repeated-pattern checks, and strategy/agent scope are explicit?

## 2. Bottom Line

- Recommendation: **adopt core**.
- Confidence: **high** for the need; **medium** for exact promotion thresholds.
- Why: Trade Trace already separates `reflection` memory nodes from `playbook_rule` nodes, requires playbook version proposals to cite a reflection, tracks outcomes/forecast scores/playbook adherence, and records recall/source provenance. That substrate makes quarantine feasible and necessary. A fresh-session LLM can overfit a single outcome, rationalize after the fact, or poison its own future context if one subjective reflection is immediately elevated into durable policy. Quarantine should therefore become a future product primitive: reflections can be recalled and reviewed, but durable process policy must carry an evidence bundle, scope, and promotion rationale.

## 3. Agent-Specific Problem

A human trader may distinguish a diary note, a hunch, a lesson, a setup rule, and a hard process rule using tacit judgment. A fresh-session LLM trading agent does not reliably preserve that distinction unless the system encodes it. If the agent stores “never trade this setup again” as a high-importance memory after one bad outcome, future sessions may retrieve it as authoritative policy even when it is:

- a post-hoc rationalization rather than pre-outcome evidence;
- based on one trade, one market regime, or one instrument;
- contradicted by other decisions, skipped opportunities, or calibration results;
- written by a different agent/model/run than the current one;
- scoped to a strategy but recalled globally;
- stale, superseded, or invalid outside its original conditions.

For agent-only Trade Trace, reflection-to-policy quarantine is the safety boundary between **subjective learning** and **procedural memory**. It lets an LLM write honest reflections immediately after outcomes while preventing those reflections from silently becoming durable playbook rules that steer later sessions.

## 4. Current Baseline

### Implemented / observed substrate from research artifacts and docs

- The memory taxonomy already separates `observation`, `reflection`, and `playbook_rule` nodes. `reflection` is defined as subjective retrospective synthesis; `playbook_rule` is codified procedural policy belonging to a playbook version (`docs/architecture/memory-layer.md:30-77`).
- `memory.reflect` writes a reflection node and an `about` edge to a target such as decision, outcome, forecast, strategy, playbook version, signal, or instrument. The system packages evidence but does not generate the reflection itself (`docs/architecture/memory-layer.md:285-299`, `337-355`).
- `reflection.prompt_for_outcome` is deterministic and no-LLM: it bundles resolved outcome, original thesis/forecast, prior reflections, and calibration delta; an external LLM decides what to write back (`docs/architecture/memory-layer.md:291-293`; `docs/PRD.md:361-362`).
- `playbook.propose_version` exists in the tool family, and the current baseline notes that playbook version updates require reflection-node provenance (`docs/research/agentic-trade-trace/01-current-system-baseline.md:29-33`, `45-47`).
- Playbooks are advisory, not automatic rule engines; adherence is recorded through playbook/report surfaces and decision adherence rows (`docs/PRD.md:398-406`; baseline §3). Machine-checkable predicates are deferred/narrow, not assumed.
- The ledger already records decisions/non-actions, forecasts, outcomes, sources, strategy IDs, playbook versions, adherence, and segmentation fields such as `agent_id`, `model_id`, `environment`, and `run_id` on major rows (`docs/research/agentic-trade-trace/01-current-system-baseline.md:21-39`).
- Memory recall includes temporal validity, confidence decay, supersession discounting, strategy context, and recall telemetry (`docs/architecture/memory-layer.md:115-216`, `220-229`; `docs/research/agentic-trade-trace/concepts/recall-receipts.md`).
- External synthesis strengthens this concept: reflection systems are useful, but in trading they raise overfitting/context-poisoning risk; reflection should not auto-promote to policy (`docs/research/agentic-trade-trace/synthesis/external-evidence.md:45`, `78-80`).

### Current gap

Trade Trace has the building blocks but no named quarantine lifecycle. Today, a reflection can be retained and a playbook version can be proposed from reflection provenance, but product research has not yet defined what evidence makes promotion legitimate, how scope is constrained, how contradictions are surfaced, or how agents should distinguish “candidate lesson” from “durable process rule.”

## 5. Candidate Product Shape

The candidate product shape is a **policy candidate quarantine** lifecycle, not an implementation mandate.

Conceptual states:

1. **Raw reflection**
   - Agent writes subjective synthesis after a decision, outcome, review bundle, period, signal, or strategy review.
   - Reflection is linked with `about` and, where available, `supports`/`contradicts`/`derived_from` edges.
   - It remains memory, not policy.

2. **Policy candidate**
   - Agent or report identifies a reflection as a possible rule change.
   - Candidate records intended playbook/process implication in prose, but is clearly marked as not durable policy.
   - Candidate must name intended scope: strategy, instrument class, venue, asset class, decision type, timeframe/regime, agent/model, and playbook/version if applicable.

3. **Evidence bundle assembly**
   - Candidate gathers linked decisions/non-actions, forecasts, outcomes, sources, recall receipts, calibration diagnostics, playbook adherence/override data, and strategy context.
   - Bundle should include both supporting and contradicting evidence and sample-size warnings.

4. **Promotion eligibility review**
   - Candidate is checked against promotion criteria: repeated pattern, pre-outcome evidence quality, outcome/calibration support, source provenance, recall/use evidence, scope clarity, no unresolved contradiction, and sufficient sample size or explicit low-N caveat.

5. **Promoted playbook/process policy**
   - Only after eligibility is satisfied should the reflection support a new or superseding `playbook_rule` / playbook version.
   - The promoted rule should keep `derived_from` provenance to the reflection(s) and evidence bundle, plus `supersedes` links to old rules where applicable.

6. **Post-promotion monitoring**
   - Future adherence, overrides, outcomes, recall receipts, and calibration reports test whether the rule is followed, ignored, helpful, harmful, overbroad, or stale.
   - Contradictory evidence should send the rule back to review/supersession rather than silently accumulating poisoned context.

Recommended promotion criteria:

- **Minimum provenance:** at least one linked reflection, target decision/outcome/review/strategy, and source/forecast/outcome evidence where applicable.
- **Repeated-pattern requirement:** default expectation of multiple related cases or a clearly labeled exception for severe one-off risk-control lessons. A single outcome can create a candidate, not a durable general rule by default.
- **Outcome/calibration support:** resolved outcomes, forecast scores, Brier/calibration deltas, base-rate comparison, or non-action review where available.
- **Pre-outcome discipline:** forecasts/sources/theses used for evidence should have been recorded before outcome or explicitly late-recorded/ambiguous.
- **Recall evidence:** recall receipts should show whether relevant prior reflections/rules were retrieved, cited, ignored, or contradicted.
- **Strategy/scope boundary:** rule must name the strategy/process scope it applies to and should not become global by accident.
- **Agent/model boundary:** promotion should identify the agent/model/environment/run that authored and proposed the rule; cross-agent/global policy needs stronger evidence.
- **Contradiction check:** known contradictory cases/sources/reflections must be included or caveated.
- **Reversibility:** durable rules should be supersedable, not overwritten; old rules remain auditable.

## 6. Required Data / State

Required existing state:

- `memory_nodes` for `reflection` and `playbook_rule`, including `confidence_base`, `importance`, decay, bi-temporal validity, author/segmentation fields, and invalidation/supersession metadata.
- `edges` between reflections, decisions, forecasts, outcomes, sources, strategies, playbook versions, signals, and rules.
- Decision/non-action lifecycle records: decisions, watches, skips, holds, reviews, thesis updates/invalidations, forecasts, outcomes, review deadlines, tags, reasons, and strategy/playbook references.
- Forecast scoring and calibration state: resolution rules, outcome status, score state, Brier/calibration reports, low-N warnings, and late/ambiguous resolution flags.
- Source/evidence provenance: caller-supplied sources and stance/freshness/quality diagnostics.
- Recall telemetry/receipts: raw recall events plus later use/citation evidence.
- Playbook versions and adherence rows: followed/overridden/not-applicable statuses and reasons.
- Agent/run identity: actor, `agent_id`, `model_id`, `environment`, `run_id`, idempotency, and timestamps.
- Strategy scope: active/archived strategies and strategy-linked decisions/reflections/reports.

Potential future conceptual state:

- A computed or materialized **policy candidate** status over reflection(s).
- Evidence bundle IDs or deterministic bundle keys that group promotion evidence.
- Promotion decision metadata: eligible/ineligible/promoted/rejected/superseded, criteria satisfied, missing evidence, scope, caveats, and reviewer actor.
- Post-promotion monitoring metrics: adherence trend, override outcomes, repeated violation patterns, contradiction counts, and low-N caveats.

## 7. Machine Interface Implications

Future CLI/MCP/JSON surfaces should let an agent inspect quarantine state without a human approval dashboard. Conceptual machine-facing needs:

- Query reflections that are **candidate lessons**, grouped by strategy, playbook, decision type, instrument, tag, period, or outcome pattern.
- Produce an evidence bundle for a candidate: linked decisions/non-actions, forecasts, outcomes, sources, recall receipts, playbook adherence, calibration report slices, and contradictions.
- Return promotion eligibility as structured diagnostics: criteria satisfied, criteria missing, sample size, scope, contradiction/caveat list, and source/recall IDs.
- Distinguish `reflection` from `playbook_rule` in recall/bootstrap output. Startup packs should label quarantined reflections as “candidate/subjective” rather than “policy.”
- Allow agents to filter recall by node type and strategy context so subjective reflections do not outrank active playbook rules accidentally.
- Expose promoted rules with provenance: which reflection(s), outcome(s), calibration diagnostics, and prior rule(s) they derive from or supersede.
- Support replay/regression later: evaluate whether a proposed rule would have changed decisions on recorded cases without rewriting history.

Interface guardrail: promotion diagnostics should not say “enter/exit/buy/sell.” They should report process evidence and policy-readiness only, preserving Trade Trace’s no-advice/no-execution boundary.

## 8. Evidence

- Repo evidence:
  - Research contract places reflections, playbook rules, recall behavior, forecasts, decisions, non-actions, strategies, and machine-readable abstractions in scope, while prohibiting implementation and execution/data-fetching scope (`docs/research/agentic-trade-trace/00-research-contract.md`).
  - Baseline reports implemented memory graph, reflections, playbooks, strategy context, forecast scoring, reports, source evidence, and segmentation fields; it identifies the gap as taxonomy/usage around when reflections become rules (`docs/research/agentic-trade-trace/01-current-system-baseline.md`).
  - Taxonomy classifies reflection-to-policy quarantine as a core investigation cluster and explicitly separates it from machine-checkable predicates (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:35-49`, `80-83`).
  - Foundational synthesis says policy changes should be quarantined after diagnostics and should consume lifecycle outcomes, forecast diagnostics, recall receipts, and strategy context (`docs/research/agentic-trade-trace/synthesis/foundational-continuity.md:147-149`, `201-205`).
  - Memory architecture defines `reflection` as subjective, `playbook_rule` as procedural, specifies `derived_from`/`supersedes` edges for rules, and supports confidence decay, supersession, strategy context, and recall telemetry (`docs/architecture/memory-layer.md`).
  - PRD defines memory nodes, recall telemetry, playbook tools/adherence, deterministic `reflection.prompt_for_outcome`, forecast scoring, reports, and safety boundaries (`docs/PRD.md:302-420`, `463-469`).
- External evidence:
  - External evidence synthesis states reflection systems support reflection value but also create drift/context-poisoning risk; this strengthens quarantine (`docs/research/agentic-trade-trace/synthesis/external-evidence.md:45`, `78-80`).
  - Agent memory packet finds layered episodic/semantic/procedural memory and recommends separating reflections from durable playbook policy (`docs/research/agentic-trade-trace/external/agent-memory-architecture-references.md:32-47`).
  - Forecasting/calibration packet supports proper scoring, calibration/reliability, base-rate comparisons, resolution discipline, and low-N caveats as evidence inputs to reflection quarantine (`docs/research/agentic-trade-trace/external/forecasting-calibration-references.md:8-18`, `132-143`).
- User-stated intent:
  - The delegated task explicitly requests focus on separating subjective reflections/lessons from durable playbook/process policy; promotion criteria; evidence bundles; outcome/calibration evidence; repeated-pattern requirements; agent identity and strategy scope; and preventing context poisoning/overfitting.
- Inferences:
  - Existing node-type separation is necessary but not sufficient; agents need a lifecycle/status and evidence standard for promotion.
  - A single reflection should normally be allowed to influence recall as subjective memory but should not become general policy without repeated evidence or a narrow risk-control exception.
  - Recall receipts and source provenance are both required because policy promotion should know what external evidence supported the decision and what internal memory was retrieved/used.

## 9. Risks / Failure Modes

- **Context poisoning:** A false or stale lesson is repeatedly recalled and treated as process truth.
- **Overfitting to one outcome:** A single win/loss becomes a broad rule despite low sample size or regime dependence.
- **Retrospective rationalization:** Reflections written after outcomes rewrite the agent’s apparent pre-outcome reasoning.
- **Scope leakage:** A strategy-specific lesson becomes a global playbook rule.
- **Agent/model leakage:** A rule learned by one model/prompt/environment is assumed valid for another without evidence.
- **Evidence cherry-picking:** Promotion bundle includes only supporting cases and omits skips, holds, contradicted sources, or failed recalls.
- **Metric theater:** Calibration/Brier numbers are used despite sparse samples, ambiguous outcomes, or invalid reference classes.
- **Rule accretion:** Too many promoted rules make future context longer, noisier, and more contradictory.
- **Automation creep:** Quarantine could become an automatic policy-mutating system or human approval workflow; both exceed current product direction.
- **Advice boundary drift:** Policy diagnostics could be phrased as trade recommendations rather than process/readiness evidence.
- **Excessive friction:** If promotion criteria are too heavy, useful lessons may never become playbook rules.

## 10. Dependencies / Conflicts

Dependencies:

- **Decision and non-action lifecycle:** supplies the reviewable cases, outcomes, non-actions, adherence gaps, and reflection targets.
- **Recall receipts:** prove what internal memories/rules/reflections were retrieved or ignored before decisions and promotions.
- **Forecast-vs-market diagnostics / calibration reports:** provide objective outcome and probability-quality evidence.
- **Source/evidence provenance:** shows whether decisions/reflections relied on strong, stale, missing, or contradictory sources.
- **Strategy lifecycle:** prevents policy from smearing across unrelated edge theses.
- **Agent/run attribution:** scopes learning by agent/model/environment/run.
- **Machine-checkable playbook predicates:** downstream consumer; only some promoted rules may become deterministic predicates.
- **Replay/regression substrate:** downstream verifier for whether candidate rules would have improved recorded cases.
- **Fresh-session bootstrap pack:** consumer; must label quarantined reflections distinctly from durable policy.

Conflicts / boundaries:

- Must preserve ledger/memory/policy separation; reflections are beliefs, decisions/outcomes are facts, playbook rules are procedural policy.
- Must not become trade execution, market-data fetching, financial advice, human dashboard approval, or a generic RL reward loop.
- A strict repeated-pattern standard conflicts with rare but severe risk-control lessons; the product may need explicit “single-case critical risk” exceptions with narrow scope and strong caveats.
- A materialized quarantine object improves clarity but may duplicate evidence already expressible through memory nodes, edges, and playbook versions; initial product direction should decide computed/reportable vs durable state later.

## 11. Open Questions / Falsifiers

- What minimum number of repeated cases is enough by default, and when should a single severe case be eligible as a narrow risk-control rule?
- Should promotion require at least one resolved forecast or scored outcome, or can source/adherence/process evidence suffice for rules not tied to binary forecasts?
- How should skipped/watched/held non-actions contribute to repeated-pattern evidence?
- Should promotion be scoped to strategy by default, with global playbook rules requiring extra evidence?
- How should contradictions be weighted: does one strong contradicting case block promotion or merely force a caveat?
- Can existing `reflection` nodes plus `playbook.propose_version` provenance express quarantine well enough, or is a distinct policy-candidate abstraction needed?
- Should agent-authored helpfulness labels be allowed in evidence bundles, and how are they kept separate from objective outcome/calibration evidence?
- How should recall ranking treat quarantined reflections so useful lessons surface without overpowering durable playbook rules?
- Falsifier: if dogfood shows agents safely evolve playbooks from single reflections using existing playbook provenance, with no observed overfitting/context poisoning and no confusion between reflection and rule, this concept may be downgraded from core to supporting.
- Falsifier: if promotion criteria require human approval, external market fetching, execution integration, or generic memory infrastructure, the concept should be narrowed or rejected.

## 12. Decision Hook

This dossier should feed the policy/playbook synthesis and downstream decision work for `trade-trace-sdym`, plus later synthesis on machine-checkable playbook predicates and replay/regression. Recommended decision framing: adopt **reflection-to-policy quarantine** as a core future product primitive, initially as a machine-readable lifecycle/evidence standard over existing reflections, playbook rules, edges, outcomes, recall receipts, and reports; do not authorize implementation or automatic policy mutation.

## 13. Side Effects

Files written:

- `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/concepts/reflection-to-policy-quarantine.md`

Files modified besides this artifact: none.

Memory retained: none.

External/network side effects: none; no network fetches were run.

Implementation changes: none; no code, schemas, tests, README, PRD, VISION, Beads, config, or implementation-bearing files were edited.
