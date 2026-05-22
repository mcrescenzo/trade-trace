# Concept Dossier: Machine-Checkable Playbook Predicates

## 1. Question

Which agent-only playbook rules should Trade Trace treat as eligible for deterministic, machine-checkable adherence evaluation from recorded ledger/source/forecast/decision fields, and where should the product boundary remain agent self-report rather than a general rule engine, execution guard, or trading-advice system?

## 2. Bottom Line

- Recommendation: adopt supporting
- Confidence: medium
- Why: Current Trade Trace already has advisory playbooks, playbook-rule memory nodes, normalized `decision_playbook_rules` adherence rows, strategy-scoped adherence reporting, source-quality reporting, forecast/outcome/scoring state, and rich decision fields. That substrate is sufficient to define a narrow future predicate-eligibility model. The recommendation is not to add a general rule engine; it is to classify a small subset of playbook rules as deterministically auditable only when their required inputs are explicit recorded fields. Rules depending on agent judgment, source interpretation, market data not recorded in Trade Trace, or latent reasoning should remain self-reported adherence with reasons.

## 3. Agent-Specific Problem

A fresh-session LLM trading agent can inconsistently report whether it followed its own playbook. It may:

- remember the rule text differently across sessions;
- rationalize an override after outcome resolution;
- say a rule was “not applicable” because the triggering evidence was not in context;
- forget that a playbook version existed for a prior decision;
- confuse strategy-scoped rules with global process rules;
- conflate source quality, calibration, and expected edge with unrecorded market intuition.

Human traders often tolerate checklist ambiguity because they carry implicit memory and can review screenshots manually. An agent-only substrate needs stronger audit separation: “the agent says it followed this rule” is different from “the recorded decision/forecast/source fields satisfy this predicate.” Machine-checkable predicates are valuable because they let later reports, replay/regression, and policy quarantine identify concrete process drift without trusting a regenerated rationale.

The problem is also safety-boundary-sensitive. Trade Trace must not become an execution blocker, broker pre-trade risk system, alpha engine, or autonomous advisor. The product value is retrospective auditability and continuity: recorded facts can prove that a process rule was satisfiable, violated, overridden, or not computable from the journal.

## 4. Current Baseline

### Implemented behavior observed in source/research artifacts

- Playbooks are advisory. The playbook tool module states that adherence is recorded per `(decision, playbook_version, rule_node)` with statuses `considered`, `followed`, `overridden`, and `not_applicable`, and that “nothing auto-rejects a decision because it violates a playbook rule” (`src/trade_trace/tools/playbook.py:1-13`, `50`).
- `decision.record_adherence` validates that `decision_id`, `playbook_version_id`, and a `rule_node_id` pointing to a `memory_node` with `node_type='playbook_rule'` all exist, then writes one normalized `decision_playbook_rules` row with status, reason, metadata, event, actor, and idempotency fields (`src/trade_trace/tools/playbook.py:561-693`).
- Playbook version proposals require a provenance reflection node and reject rule payloads in `playbook.propose_version`; rule content is stored separately as `playbook_rule` memory nodes (`src/trade_trace/tools/playbook.py:76-92`, `407-462`).
- `playbook.show` and `playbook.list_versions` expose playbook-version lineage and discover linked rule summaries from prior adherence rows, with guidance to create `playbook_rule` nodes via `memory.retain` (`src/trade_trace/tools/playbook.py:242-290`, `301-364`).
- `report.playbook_adherence` aggregates from `decision_playbook_rules`, not JSON blobs; it returns counts for considered/followed/overridden/not-applicable, distinct decision counts, rule-node ids, adherence-row ids, sample warnings, and supports top-level `playbook_id` and `strategy_id` scoping (`src/trade_trace/reports/playbook_adherence.py:1-11`, `29-142`).
- The baseline identifies playbooks/adherence as implemented but advisory: agents create `playbook_rule` memory nodes, propose versions, and record adherence/overrides; no automatic rule engine exists (`docs/research/agentic-trade-trace/01-current-system-baseline.md:31-32`, `47`).
- The PRD explicitly states that MVP playbook rules are advisory, normalized adherence is in `decision_playbook_rules`, and automatic violation detection is only for future rules whose predicates are explicitly machine-checkable; MVP must not promise a general automatic rule engine (`docs/PRD.md:81-83`, `234-238`).
- The memory-layer architecture defines `playbook_rule` as procedural memory with required playbook metadata and states that automatic violation detection requires explicit predicate fields added later (`docs/architecture/memory-layer.md:66-76`). It also defines `follows` and `violates` edge semantics as potential decision-to-rule links (`docs/architecture/memory-layer.md:99-112`).
- The decision lifecycle dossier shows that decisions already include type, side, quantity, price, review deadline, strategy/playbook references, tags, risk/edge estimates, source attachments, forecasts, outcomes, and reflections as lifecycle components (`docs/research/agentic-trade-trace/concepts/decision-non-action-lifecycle.md:27-60`, `101-115`).

### Planning/doc evidence and constraints

- Product docs classify playbooks as process rules and strategies as edge-thesis groupings. They are orthogonal: a decision may have any combination of `strategy_id`, `playbook_version_id`, and tags (`docs/PRD.md:81-83`, `117-125`, `289-292`).
- Human trading-journal evidence supports rule-adherence review and mistake taxonomies, but recommends separating deterministic rule violations from agent self-critique (`docs/research/agentic-trade-trace/external/human-trading-journal-patterns.md:53-60`, `98-105`).
- The taxonomy positions machine-checkable playbook predicates as supporting and warns to start narrow and avoid a general rule engine (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:46`, `75`, `127`, `146`).
- Foundational continuity synthesis frames this concept downstream of decision lifecycle, recall receipts, forecast diagnostics, and reflection-to-policy quarantine; it asks which rule types can be evaluated from recorded fields without a general rule engine (`docs/research/agentic-trade-trace/synthesis/foundational-continuity.md:201-208`).

### Baseline gap

The current system records self-reported adherence rows, but it has no standard vocabulary for predicate eligibility, required inputs, computability state, confidence of evaluation, or how an automatic check should coexist with an agent’s self-reported `followed`/`overridden`/`not_applicable` row. Rule text lives in memory-node prose, so future automatic checks would need a separate narrow predicate representation rather than parsing natural language.

## 5. Candidate Product Shape

The product shape should be a narrow predicate-eligibility layer over advisory playbooks, not an execution-time rule engine.

### 5.1 Conceptual rule classes

1. **Self-reported procedural rule**
   - Current default.
   - The agent records adherence status and reason.
   - Examples: “Only trade when thesis quality feels high,” “avoid narrative overconfidence,” “prefer markets where sources agree.”
   - Machine status: not checkable unless converted into explicit fields and thresholds.

2. **Source-supported but judgmental rule**
   - Some evidence is recorded, but interpretation remains agent judgment.
   - Examples: “Require at least two independent credible sources,” “do not rely on weak rumors,” “avoid stale source evidence.”
   - Machine status: partially checkable for counts/freshness/source-quality fields; not checkable for semantic credibility unless that credibility is separately recorded as structured source metadata.

3. **Ledger-field predicate rule**
   - Deterministically computable from existing recorded fields.
   - Examples:
     - decision type must not be `actual_enter` for a paper-only playbook;
     - `forecast_id` must be present for entry decisions;
     - forecast must have `resolution_rule_text`;
     - decision must have `playbook_version_id` when a playbook-scoped strategy is used;
     - watch decisions must include `review_by`;
     - entry decisions must carry non-null price/quantity where matrix permits/requires them;
     - decisions under a strategy must use the strategy’s active scope.
   - Machine status: eligible for deterministic pass/fail/not-computable if fields exist.

4. **Recorded numeric-threshold predicate rule**
   - Computable only when the relevant numeric quantities are explicitly recorded.
   - Examples:
     - predicted edge estimate exceeds configured minimum;
     - spread does not exceed a recorded threshold if spread is captured in snapshot/metadata;
     - position size/risk unit stays below a recorded cap;
     - forecast probability is within a permitted band for a strategy.
   - Machine status: eligible if fields and units are pinned; otherwise not-computable.

5. **Calibration/outcome-conditioned audit rule**
   - Checkable only after outcome/scoring exists; not a pre-decision constraint.
   - Examples:
     - overridden rules should be reviewed after negative outcomes;
     - late-recorded forecasts must not count toward prospective calibration;
     - repeated overrides with worse Brier/outcome metrics should trigger reflection review.
   - Machine status: retrospective diagnostic only; must not advise future trades.

### 5.2 Predicate evaluation states

A future predicate surface should distinguish at least:

- `pass`: recorded fields satisfy the predicate.
- `fail`: recorded fields contradict the predicate.
- `not_applicable`: predicate trigger does not apply to the decision/scope.
- `not_computable`: required field/source/outcome is missing or not represented.
- `ambiguous`: conflicting records, stale/superseded rule context, or unit/threshold mismatch prevents deterministic classification.

This is separate from existing self-reported adherence statuses. A decision could have `agent_status='followed'` and `machine_status='not_computable'`, or `agent_status='followed'` and `machine_status='fail'`. The product value is the discrepancy.

### 5.3 Predicate eligibility criteria

A playbook rule is machine-checkable only if all of the following are true:

1. **Explicit trigger scope:** applicable decision types, strategies, instruments/asset classes, or playbook version are explicit.
2. **Recorded inputs:** every field needed for evaluation is stored in Trade Trace at or before the relevant decision/outcome boundary.
3. **Pinned comparator:** the operator is deterministic (`exists`, `equals`, `in`, `<=`, `>=`, date-before/date-after, count-at-least, link-exists).
4. **Pinned units and timestamps:** numeric and temporal comparisons specify units and whether they use decision time, forecast creation time, outcome time, or report time.
5. **No semantic parsing dependency:** the predicate does not require interpreting natural-language rationale/source prose unless a separate structured field already encodes the interpretation.
6. **No external fetch dependency:** the predicate cannot require live market data, source retrieval, broker state, or outcome fetching.
7. **Audit-only consequence:** failure produces a reportable audit row/signal/review input, not an order block or recommendation.

## 6. Required Data / State

Machine-checkable predicates can be narrow because much of the required state already exists conceptually in the ledger/memory model:

- **Rule identity:** `rule_node_id`, `node_type='playbook_rule'`, `playbook_version_id`, playbook/version lineage, provenance reflection node, rule validity/supersession from memory-node semantics.
- **Decision fields:** `decision_id`, type, side, quantity, price, reason, `review_by`, `forecast_id`, `thesis_id`, `snapshot_id`, `instrument_id`, `playbook_version_id`, `strategy_id`, tags, risk/edge estimates, metadata, created timestamp, actor/run/model/environment fields.
- **Forecast fields:** kind, outcome probabilities, `yes_label`, `resolution_at`, `resolution_rule_text`, scoring support/state, late-recorded metadata, supersession/invalidated state, binary Brier score after resolution.
- **Outcome fields:** resolution status, final/provisional/disputed state, resolution timestamp, linked forecast/outcome score rows.
- **Source/evidence fields:** source attachments to thesis/forecast/decision/memory, stance, freshness/retrieval metadata, source-quality/audit readiness report outputs where available.
- **Strategy scope:** `strategy_id`, active/archived state, strategy-scoped reports/recall, and decision/thesis/review grouping.
- **Adherence rows:** existing `decision_playbook_rules` self-reported status/reason/metadata plus report aggregation.
- **Recall/reflection context:** recall receipts and reflections are not required to evaluate narrow predicates, but they are needed to explain whether the agent had rule context available and to quarantine later policy changes.

The most important required state not currently standardized is a predicate declaration attached to or linked from a rule: a machine-readable expression of input fields, scope, comparator, threshold, units, and evaluation boundary. This dossier does not authorize a schema; it identifies the conceptual need.

## 7. Machine Interface Implications

Agent-facing interfaces should expose predicate information as machine-readable audit data while keeping existing advisory playbook behavior intact.

- **Rule inspection:** When an agent calls playbook/rule read surfaces, rules should be clearly labeled as `self_reported_only`, `partially_checkable`, or `machine_checkable` if such metadata exists later. Prose body remains for agent reasoning, but predicate metadata must be the only automatic-check contract.
- **Decision-time recording:** `decision.record_adherence` remains the agent’s self-report. It should not be silently replaced by machine evaluation. Agent statuses and machine statuses answer different questions.
- **Adherence reports:** `report.playbook_adherence` is the natural consumer. It already aggregates normalized rows and supports strategy scoping; future predicate diagnostics could add discrepancy groups such as “self-reported followed but machine failed,” “overridden with negative outcome,” or “rule not computable due missing source/forecast fields.”
- **Override semantics:** Overrides remain allowed and explicitly recorded. A machine failure should not mean “bad trade”; it means “recorded process rule not satisfied.” An override reason plus later outcome/calibration context is evidence for reflection, not execution advice.
- **Strategy scope:** Predicate applicability should respect strategy boundaries. A rule can be global, playbook-version scoped, strategy-scoped, or decision-type scoped, but strategies and playbooks must remain orthogonal objects.
- **Source quality:** Predicate checks may assert presence/freshness/count/stance of source attachments, but must not infer truth or credibility from source prose. Source-quality report outputs can be referenced as diagnostics, not treated as fetched facts.
- **Calibration:** Outcome-conditioned predicate reporting should join to forecast scores and outcomes only after resolution. It can surface whether overrides correlate with poor calibration or outcomes, but not claim profitability or future edge.
- **Replay/regression:** Predicate checks can become valuable replay inputs because they are deterministic over recorded cases. Replay should use the historical rule version and fields available at that decision time, not current rule text or post-outcome data.
- **No general rule engine:** Interfaces should avoid arbitrary code, dynamic expressions, plugin predicates, SQL fragments, LLM-evaluated rule text, or action hooks. Allowed predicate families should be closed and audited.

## 8. Evidence

- Repo evidence:
  - Research contract scopes the program to fresh-session continuity, durable playbook rules, recall behavior, machine-readable abstractions, and explicitly prohibits implementation, execution, data fetching, and generic memory scope (`docs/research/agentic-trade-trace/00-research-contract.md:18-39`, `40-58`).
  - Baseline confirms implemented advisory playbooks, normalized adherence rows, decision.record_adherence, playbook adherence reports, memory graph, strategies, sources, reports, and the absence of automatic rule detection (`docs/research/agentic-trade-trace/01-current-system-baseline.md:21-39`, `47`).
  - Taxonomy classifies machine-checkable playbook predicates as supporting and warns against a general rule engine (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:46`, `75`, `127`, `146`).
  - PRD states MVP rules are advisory and automatic violation detection is only for future explicitly machine-checkable predicates (`docs/PRD.md:81-83`, `234-238`).
  - Source confirms `decision.record_adherence` writes one normalized adherence row after validating endpoints and rule node type (`src/trade_trace/tools/playbook.py:561-693`).
  - Source confirms `report.playbook_adherence` aggregates from `decision_playbook_rules` and supports playbook/strategy scoping (`src/trade_trace/reports/playbook_adherence.py:29-142`).
  - Memory-layer doc defines `playbook_rule` as procedural memory and says automatic violation detection requires explicit predicate fields added later (`docs/architecture/memory-layer.md:66-76`).
- External evidence, if used:
  - Human trading-journal patterns support rule-adherence review and mistake taxonomies, but specifically imply separating deterministic rule violations from self-critique (`docs/research/agentic-trade-trace/external/human-trading-journal-patterns.md:53-60`, `98-105`).
  - External synthesis maps this concept as moderately supported: human checklists/rule adherence and procedural memory support explicit process rules, with confidence medium and a narrow-predicate warning (`docs/research/agentic-trade-trace/synthesis/external-evidence.md:44-47`, `95-99`).
- User-stated intent:
  - The task asks to focus on how agent-only playbook rules can be represented as narrow, auditable predicates over recorded ledger/source/forecast/decision fields; distinguish machine-checkable from agent self-reported; avoid general rule-engine/execution/advice; and address adherence rows, overrides, strategy scope, source quality, and calibration.
- Inferences:
  - Current adherence rows are the correct spine for self-report and report aggregation, but cannot by themselves prove deterministic compliance.
  - A future predicate model should not parse `playbook_rule.body`; it should use explicit narrow metadata, otherwise it will become LLM judgment disguised as automation.
  - The highest-value first predicate families are field-presence, linkage, timestamp/order, enum/type, threshold-over-recorded-fields, and source/link-count checks.

## 9. Risks/Failure Modes

- **False determinism:** Treating prose rules as machine-checkable via LLM interpretation would recreate self-report under a different name.
- **General rule-engine creep:** Arbitrary predicates, SQL snippets, plugin functions, or action hooks would expand the product into an unsafe automation platform.
- **Advice/execution confusion:** A failed predicate could be misread as “do not trade” or “bad trade.” It must remain an audit diagnostic.
- **Market-data fetch creep:** Rules about spread, liquidity, price, or market-implied probability are checkable only if those values were recorded by the caller. Trade Trace must not fetch them.
- **Missing-field bias:** `not_computable` can become noisy if agents omit optional fields; reports must distinguish “violated rule” from “insufficient recorded data.”
- **Overfitting policy:** Outcome-conditioned predicates can encourage rules that fit a small sample. Sample warnings and reflection-to-policy quarantine remain necessary.
- **Strategy scope mistakes:** Global rules applied to a narrow strategy, or strategy rules applied globally, can produce misleading violation rates.
- **Source-quality overclaim:** Source presence/count/freshness can be checked, but truthfulness or independence may remain subjective unless explicitly structured.
- **Late/hindsight leakage:** Post-outcome fields must not be used to evaluate whether a pre-decision rule was followed, except in clearly retrospective audit reports.
- **Override stigma:** Overrides are legitimate process data. Treating every machine failure as an error would discourage agents from recording honest exceptions.
- **Adherence row duplication/mismatch:** The existing normalized rows track self-report per decision/rule; future predicate results need clear identity and timestamps to avoid contradictory report counts.

## 10. Dependencies/Conflicts

Dependencies:

- **Decision and non-action lifecycle:** Provides the recorded fields, closure state, outcome linkage, and non-action semantics that predicates inspect.
- **Reflection-to-policy quarantine:** Should decide when a subjective reflection can become a durable rule and whether a rule is eligible for predicate metadata. The companion dossier now exists at `docs/research/agentic-trade-trace/concepts/reflection-to-policy-quarantine.md` and should be consumed before any final policy/playbook decision.
- **Recall receipts:** Needed to audit whether an agent had the relevant rule/memory in context before self-reporting adherence or overriding a rule.
- **Forecast-vs-market/calibration diagnostics:** Provide retrospective outcome/scoring context for evaluating overrides and rule usefulness, not for pre-trade advice.
- **Strategy lifecycle:** Needed to scope rules and reports by edge thesis without conflating strategies with playbooks or tags.
- **Source/evidence provenance and source-quality reports:** Needed for source-count/freshness/evidence-presence predicates.
- **Replay/regression substrate:** Downstream consumer for deterministic predicate results over historical cases.

Conflicts / boundaries:

- Conflicts with product principles if it requires execution, market-data fetching, broker state, external scheduling, arbitrary code evaluation, or human dashboard approval.
- Conflicts with memory-layer semantics if it treats playbook-rule prose as executable truth instead of agent-authored procedural memory.
- Conflicts with calibration integrity if post-outcome knowledge is used to judge pre-decision adherence without temporal boundaries.
- Conflicts with strategy/playbook separation if strategy membership implicitly determines a rule instead of explicit playbook/version/rule scope.

## 11. Open Questions/Falsifiers

- What closed set of predicate families is sufficient: field existence, enum equality, timestamp ordering, numeric threshold, link/source count, source freshness, scoring state, outcome status?
- Should predicate metadata live on playbook-rule memory-node metadata, playbook-version metadata, adherence-row metadata, or a separate future object? This dossier does not decide implementation shape.
- How should historical rule evaluation handle superseded playbook versions and memory-node validity windows?
- Should machine evaluation run only in reports/replay, or also at `decision.record_adherence` time as a warning-like diagnostic? Either way it must not block writes.
- Which source-quality attributes are objective enough to check without semantic interpretation?
- How should disagreement between agent self-report and machine status be reported so it prompts reflection rather than hides or punishes overrides?
- What minimum sample size is required before override-outcome/calibration patterns influence policy quarantine?
- Falsifier: if dogfood agents reliably self-report adherence with low contradiction and high usefulness, machine predicates may remain a small report enhancement rather than a supporting primitive.
- Falsifier: if useful rules mostly depend on unstructured reasoning/source interpretation, this concept should be narrowed to hygiene predicates only.
- Falsifier: if predicate checks require arbitrary expressions or external facts, reject that scope as a general rule engine/data-fetching creep.

## 12. Decision Hook

This dossier should feed the policy/playbook synthesis and the later cross-concept decision map for `trade-trace-n958` / Phase 2 playbook safety work. It should be consumed alongside reflection-to-policy quarantine, decision lifecycle, forecast/calibration diagnostics, strategy lifecycle, recall receipts, and replay/regression research before any future implementation is proposed.

## Side Effects

Files written:

- `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/concepts/machine-checkable-playbook-predicates.md`

Memory retained: none.

External side effects: none; no network fetches were run.

Implementation changes: none; no Beads, code, schemas, tests, README, PRD, VISION, config, or memory files were edited.
