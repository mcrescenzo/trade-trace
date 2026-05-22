# Concept Dossier: Non-actions as First-Class Learning Objects

## 1. Question

Should Trade Trace treat watches, skips, holds, defers, invalidations, thesis updates, reviews, and explicit no-action decisions as first-class learning objects for stateless LLM trading agents, or are they adequately represented as lifecycle interpretations over existing decisions, forecasts, sources, recalls, adherence, and reflections?

## 2. Bottom Line

- Recommendation: adopt supporting under the core decision/non-action lifecycle; do not split into an independent source-of-truth primitive yet.
- Confidence: high for the need; medium for exact object boundary.
- Why: Trade Trace’s product principles already say every decision is reviewable and that skipped trades matter (`docs/VISION.md:40-49`). The PRD and source-backed baseline already include non-trade decision types (`watch`, `skip`, `hold`, `invalidate_thesis`, `update_thesis`, `review`), `watch.review_by`, watchlist and unscored-forecast reports, source attachments, playbook adherence, recall telemetry, reflections, and review bundles. The missing product shape is not “add a second non-action table”; it is a machine-readable interpretation layer that turns material non-actions into durable learning cases, pending obligations, missed-opportunity review candidates, and reflection inputs without logging every moment of inaction.

## 3. Agent-Specific Problem

Human traders carry much of their non-action context implicitly. A discretionary trader may remember that an instrument was skipped because liquidity was poor, watched until earnings, held because a thesis remained intact, or deferred because a source was stale. They can also use visual dashboards, broker screens, calendar habits, and embodied routines to reconstruct “why I did nothing.”

A fresh-session LLM trading agent has none of that implicit continuity. If the agent runs from cron or a new chat, any unrecorded non-action becomes indistinguishable from absence of work. That creates several agent-specific failures:

- **Lost negative evidence:** A skipped idea may have been a correct avoidance, a missed opportunity, or an over-filtering error. Without a record, later calibration cannot distinguish them.
- **Dropped obligations:** Watches, holds, defers, unresolved forecasts, and stale sources require later review. If not represented as durable state, the next session may never revisit them.
- **False memory continuity:** The agent may infer that no prior stance existed simply because no executed trade exists.
- **Unreviewable discipline:** A no-trade decision can be the best evidence of playbook adherence, but only if the rule considered, reason, source context, and later outcome/opportunity are joinable.
- **Reflection gaps:** Outcome review cannot know whether the agent correctly avoided a trade, missed a positive-edge setup, or followed a rule that later proved too conservative.
- **Recall ambiguity:** Without recall receipts/source links, review cannot tell whether the agent saw prior warnings and ignored them or never retrieved them.

For an agent-only product, non-actions are therefore learning objects when they encode material intent, rejection, deferment, thesis state change, or review obligation. They are not learning objects merely because the agent did not act.

## 4. Current Baseline

### Observed and documented support

- The research contract explicitly includes durable tracking of “decisions, non-actions, strategies, reflections, playbook rules, and recall behavior” for fresh-session/stateless agents and prohibits implementation in this research phase (`docs/research/agentic-trade-trace/00-research-contract.md:20-39`).
- The taxonomy merges “Decision lifecycle” and “non-actions as first-class learning objects” into **Decision and non-action lifecycle**, with an initial core stance (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:35-58`).
- The foundational continuity synthesis recommends treating decision/non-action lifecycle as core, but specifically flags “non-action noise” and asks what materiality threshold prevents over-logging and whether `skip` should produce later review obligations (`docs/research/agentic-trade-trace/synthesis/foundational-continuity.md:20-29`, `150-160`, `196-200`).
- The dedicated decision/non-action lifecycle dossier establishes that current Trade Trace already models non-trade decision types, source attachments, watchlist reporting, unscored forecasts, reflection handoff, and playbook adherence; it identifies gaps around closure/revisit semantics for `skip`, `hold`, `update_thesis`, `invalidate_thesis`, and `review` (`docs/research/agentic-trade-trace/concepts/decision-non-action-lifecycle.md:27-60`, `147-188`).
- Vision principle: “Every decision is reviewable. Trades, skips, watches, paper trades, and thesis updates all create reviewable artifacts. A skipped trade is as important as an entered one” (`docs/VISION.md:40-42`).
- PRD decision enum includes `watch`, `skip`, `hold`, `invalidate_thesis`, `update_thesis`, `resolved`, and `review`, not only trade-entry/exit decisions (`docs/PRD.md:194-228`).
- PRD states `watch` may carry `review_by`, while `report.watchlist` surfaces overdue status (`docs/PRD.md:208-228`, `368-386`).
- PRD and baseline describe forecasts with `resolution_at` and resolution rules, source attachment, playbook adherence rows, memory recall events, and deterministic reports (`docs/PRD.md:175-238`, `260-268`, `323-325`, `368-420`; baseline §3-§5).
- External human-journal research identifies skipped/missed/avoided trades, pre/post review, tags, strategy classification, review cadence, and playbook adherence as common transferable patterns, with the caveat that source confidence is medium and vendor-marketing-heavy (`docs/research/agentic-trade-trace/external/human-trading-journal-patterns.md:7-14`, `44-69`, `118-126`, `148-163`).

### Baseline gaps

- There is no single “non-action learning object” abstraction that says when a non-action is material, what minimum state it must carry, how it becomes due for review, or how it closes.
- `watch` has explicit deferred-review support; `skip` is terminal in the matrix (`review_by` forbidden), and `hold`/`invalidate_thesis`/`update_thesis` have weaker revisit semantics.
- “Defer” is not a current decision type; it must be represented as `watch.review_by`, `hold`, or `review`, which may blur meaning.
- Missed-opportunity review is deferred in PRD as a trading-native report area (“skipped-positive-edge review”), not an established implemented primitive (`docs/PRD.md:26`, `386-388`).
- Human traders’ emotion/regret journaling does not translate cleanly. For agents, the useful analogue is structured process tags, adherence evidence, source/forecast context, and reflection provenance.

## 5. Candidate Product Shape

Non-actions should be treated as **material lifecycle cases** over the existing ledger/memory graph, not as a totally separate object family. Conceptually, a non-action learning object is a durable, reviewable case with these dimensions:

1. **Kind of non-action**
   - `watch`: active interest without exposure; usually requires a trigger or review deadline.
   - `skip`: explicit rejection; may be terminal or marked reviewable if material.
   - `hold`: no exposure change despite possible action; should capture why the thesis/playbook still held.
   - `defer`: cannot decide yet because timing, evidence, liquidity, or source freshness is insufficient; currently encoded as watch/hold/review-like behavior.
   - `invalidate_thesis`: active negative update to belief state.
   - `update_thesis`: belief revision without necessarily changing exposure.
   - `review`: deliberate retrospective or checkpoint action.
   - `no_action`: optional explicit “nothing material to do” marker only when needed to close a due obligation, not for every run.

2. **Materiality gate**
   A non-action deserves first-class treatment only if at least one is true:
   - it references an existing thesis, forecast, strategy, playbook rule, watch, or open/paper position;
   - it was considered as a candidate trade or exposure change but rejected;
   - it changes or invalidates a thesis;
   - it carries a deadline/trigger/source gap/outcome-resolution obligation;
   - it records playbook adherence or override evidence;
   - it is intended for later missed-opportunity, avoided-loss, or process review;
   - it is selected by a scanner bundle such as `market.scan` and would otherwise vanish.

3. **Minimum useful state**
   - instrument/thesis/forecast/snapshot/strategy IDs where available;
   - decision type and reason;
   - source IDs or source-quality caveats;
   - playbook version/rule adherence if relevant;
   - review trigger (`review_by`, horizon, price/condition trigger in metadata, or “after outcome”);
   - materiality reason/tag such as `liquidity`, `source_stale`, `insufficient_edge`, `risk_limit`, `playbook_block`, `already_exposed`, `forecast_ambiguous`, `waiting_for_resolution`;
   - links to prior recall where applicable;
   - later outcome/opportunity/review/reflection links.

4. **Lifecycle interpretation**
   - **Open:** watch/defer/hold with unresolved trigger, due date, forecast, source gap, or open thesis.
   - **Terminal closed:** skip that is intentionally not reviewable except by aggregate sampling.
   - **Review due:** `review_by` elapsed, forecast resolved, source became stale, strategy review cadence reached, or missed-opportunity diagnostic selected the case.
   - **Reviewed/reflected:** review bundle consumed and reflection written.
   - **Promoted/quarantined:** repeated lesson supports a strategy update or playbook proposal through reflection-to-policy quarantine.

5. **Outcome and missed-opportunity review**
   Non-actions should be reviewable along two axes:
   - **Avoided-loss / good discipline:** the skipped or held-back action would have violated playbook, lacked source support, or resolved poorly.
   - **Missed opportunity / over-filtering:** the skipped or deferred setup later met the original thesis, had favorable externally supplied outcome/opportunity facts, or revealed overly conservative rules.

   Trade Trace should not fetch prices or infer opportunity automatically. It can only join non-actions to caller-supplied outcomes, snapshots, opportunity observations, forecasts, and later reflections.

## 6. Required Data/State

The concept can mostly reuse current primitives:

- **Decision rows:** type, reason, `review_by`, tags, instrument/thesis/forecast/snapshot/strategy/playbook references, common metadata.
- **Forecast state:** resolution horizon, resolution rule, scoring state, late/superseded caveats, outcome links.
- **Thesis state:** parent/superseding thesis, invalidation/update rows, valid windows, strategy linkage.
- **Source state:** source rows, stance, freshness, redaction, and attachments to thesis/forecast/decision/memory node.
- **Playbook adherence:** considered/followed/overridden/not-applicable rows and reasons.
- **Recall state:** memory recall events and future recall receipts showing what prior warnings/reflections/rules were surfaced when the non-action was made or reviewed.
- **Review/reflection state:** review decision rows, review bundles, reflection memory nodes with `about` edges, possible `supports`/`contradicts`/`supersedes` links.
- **Strategy state:** strategy ID/status/hypothesis so non-action lessons are scoped by edge thesis and not smeared across unrelated setups.
- **Derived report state:** watchlist, unscored forecasts, source quality, audit readiness, coach hygiene, opportunity diagnostics, playbook adherence, strategy performance.

Potential future product definition, without implementation authorization:

- a controlled materiality vocabulary for non-actions;
- explicit non-action closure/read statuses derived from rows and edges;
- policy for when `skip` is terminal vs reviewable;
- whether `defer` should remain encoded via existing types or become an explicit decision enum later;
- how to represent “no material action this run” without turning every run into log noise.

## 7. Machine Interface Implications

Agent-facing interfaces should expose non-actions as structured, filterable lifecycle cases through CLI/MCP/JSON surfaces. Implications:

- Writes should remain tied to existing decision/forecast/thesis/source/playbook/memory primitives unless a later decision authorizes a new primitive.
- Non-action reads should be ID-rich: decision IDs, thesis IDs, forecast IDs, strategy IDs, source IDs, playbook rule IDs, recall event/receipt IDs, due timestamps, caveats, and closure/review status.
- Bootstrap packs should include only material active/due non-actions: overdue watches, unresolved defer/hold cases, skips selected for review, thesis invalidations needing follow-up, and reviews/reflections missing after outcomes.
- Work queue / next-action surfaces should distinguish process obligations from trade advice: “review this skipped case because outcome was supplied,” not “enter now.”
- Reports should support sampling and aggregate diagnostics for terminal skips to avoid requiring every skip to have a review deadline.
- Interfaces should make absence caveated. “No due non-actions returned” may mean no records in scope, omitted due to filters, or truncated by budget.
- `market.scan`-style bundles are good intake for scanner-produced `watch`/`skip` cases because they can require sources, reason, forecast/resolution fields, and child idempotency keys.
- Recall receipts matter: a non-action review should know whether the agent previously retrieved relevant memories/rules/similar cases before skipping/holding/deferring.
- Machine schemas should not imply execution, data fetching, broker truth, or market recommendations. Any missed-opportunity fact must be supplied by the caller or already recorded in the journal.

## 8. Evidence

- Repo evidence:
  - Research contract: non-actions are in scope for durable tracking; implementation is out of scope (`00-research-contract.md:20-39`, `89-138`).
  - Taxonomy: non-actions are merged into the decision/non-action lifecycle, initially core, rather than split as independent concept (`02-concept-taxonomy.md:35-58`).
  - Foundational continuity synthesis: lifecycle is part of the minimum foundation; non-action noise and materiality thresholds are explicit downstream questions (`foundational-continuity.md:20-29`, `150-160`, `196-200`).
  - Decision/non-action lifecycle dossier: existing primitives cover many lifecycle states; gaps remain in materiality, skip review, defer semantics, and closure (`decision-non-action-lifecycle.md:27-60`, `147-188`).
  - Vision: every decision is reviewable; skipped trades are as important as entered trades; memory and ledger are distinct; agent supplies judgment (`docs/VISION.md:40-49`).
  - PRD: decision enum and required-field matrix include non-trade decisions, watch deadlines, source attachments, playbook adherence, memory recall events, reports, and no execution/fetching boundaries (`docs/PRD.md:49-87`, `194-238`, `260-268`, `323-325`, `368-420`, `463-469`).
- External evidence, if used:
  - Human trading-journal packet supports recording pre-outcome intent, skipped/missed/avoided trades, review cadence, process/mistake tags, playbook adherence, and opportunity diagnostics, but warns source confidence is medium and vendor-biased (`external/human-trading-journal-patterns.md:7-14`, `44-69`, `80-87`, `118-126`, `148-163`).
- User-stated intent:
  - The delegated task asks specifically to focus on watches, skips, holds, defers, invalidations, thesis updates, reviews, and no-action decisions as learning objects for stateless LLM agents; materiality thresholds; missed-opportunity review; relation to forecasts/source/adherence/reflection; and whether a first-class object is needed or lifecycle interpretation is enough.
- Inferences:
  - First-class learning status is warranted at the product/concept level because stateless agents lose implicit non-action context.
  - A separate durable non-action table is not yet warranted because existing decision rows plus forecasts, sources, adherence, recall, and reflection already provide the likely source of truth.
  - The strongest future product move is to define materiality, closure, due-review, and review-selection semantics over current primitives.

## 9. Risks/Failure Modes

- **Over-logging:** If every absent trade or minor hesitation becomes a non-action record, bootstrap packs, recall, and reports become noisy.
- **Under-logging:** If only executed trades are recorded, agents lose avoided-loss and missed-opportunity evidence.
- **False calibration:** A skipped idea reviewed only after a favorable outcome can create hindsight bias unless original thesis/forecast/source context was captured before outcome.
- **Regret overfitting:** Missed-opportunity review can push agents toward chasing every skipped winner unless balanced against avoided losses and process adherence.
- **Terminal skip ambiguity:** A `skip` may mean “never revisit,” “not now,” “rejected by rule,” or “insufficient data.” Without materiality tags or review semantics, later agents may misread it.
- **Defer semantic loss:** Encoding defer as watch/hold/review may hide the reason for delay unless the reason and trigger are structured enough.
- **Context poisoning:** Low-quality skip/hold reasons or emotional regret reflections may be over-retrieved and treated as policy.
- **Advice creep:** Missed-opportunity and watchlist reports may look like trade recommendations unless framed as retrospective/process obligations.
- **Source over-trust:** A non-action reason based on stale or contradictory evidence can persist unless source freshness/stance is visible.
- **Playbook overfitting:** One skipped winner might cause premature rule relaxation unless reflection-to-policy quarantine requires provenance and repeated evidence.
- **Scope creep into scheduler:** Due watches/defers should be exposed as obligations, not alerts, daemon behavior, or market polling.

## 10. Dependencies/Conflicts

Dependencies:

- **Decision and non-action lifecycle:** parent/core concept; non-actions should be interpreted through this lifecycle.
- **Fresh-session bootstrap context pack:** primary read consumer for due and material non-actions.
- **Work queue / next actions:** should derive due review/closure obligations from watches, defers, holds, unresolved forecasts, missing reflections, and selected skips.
- **Forecast-vs-market diagnostics / opportunity diagnostics:** needed for missed-opportunity and avoided-loss review, limited to caller-supplied facts.
- **Source/evidence provenance:** needed to know whether a non-action rested on missing, stale, contradictory, or strong evidence.
- **Playbook adherence and machine-checkable predicates:** needed to decide whether a skip/hold was rule-following, override, or process deviation.
- **Recall receipts:** needed to distinguish memory unavailable, memory retrieved-but-ignored, and memory used.
- **Reflection-to-policy quarantine:** needed before non-action lessons become durable playbook changes.
- **Strategy lifecycle:** needed to scope non-action lessons by edge thesis.

Conflicts / boundaries:

- Non-actions must not become a human dashboard, scheduler, broker/execution path, market-data fetcher, or trade recommender.
- Non-action learning must preserve the ledger/memory distinction: decisions/forecasts/outcomes/sources are auditable facts; reflections and policy proposals are agent-authored beliefs.
- Making every `skip` reviewable conflicts with materiality and token-budget discipline.
- Treating non-actions as a wholly separate primitive conflicts with the taxonomy/synthesis conclusion that they belong under the unified lifecycle unless dogfood proves otherwise.

## 11. Open Questions/Falsifiers

- What exact materiality thresholds should agents use before writing a non-action?
- Should `skip` remain terminal by default, or support optional review triggers for high-materiality skips?
- Does “defer” deserve its own decision type, or is `watch.review_by` / `hold` / `review` enough with better tags and metadata?
- What minimum fields make each non-action kind useful without increasing write friction too much?
- How should missed-opportunity review be selected: all tagged material skips, sampled skips, skips linked to supplied outcomes, or forecast-backed skips only?
- Should an explicit `no_action` marker exist only to close due work, or should agents be discouraged from writing it at all?
- How should avoided-loss and missed-opportunity outcomes be normalized when no position existed and no execution price/fill exists?
- What non-action lessons are safe to promote into playbook changes, and how many examples are enough?
- Falsifier: if dogfood agents can reliably recover material non-actions, due obligations, and missed-opportunity cases from existing `decision.add`, reports, and review bundles with only prompt/process discipline, then no new product abstraction is needed beyond documentation/taxonomy.
- Falsifier: if first-class non-action treatment causes agents to log large volumes of low-value “nothing happened” rows, the concept should be narrowed to watches/defers/forecast-backed skips and due-work closures.
- Falsifier: if missed-opportunity analysis requires automatic market-data fetching or simulated fills, that part should be rejected under Trade Trace’s boundaries.

## 12. Decision Hook

This dossier should feed the downstream decision/process synthesis and future decision matrix for `trade-trace-t4sr`, plus later work on work queue / next actions, forecast-vs-market diagnostics, reflection-to-policy quarantine, machine-checkable playbook predicates, replay/regression, and bootstrap context packs.

Recommended decision wording: **adopt non-actions as first-class learning cases within the decision/non-action lifecycle; defer any separate durable non-action object until dogfood proves lifecycle interpretation is insufficient.**

## 13. Side Effects

Files written:

- `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/concepts/non-actions-first-class-learning-objects.md`

Memory retained: none.

External side effects: none; no network fetches were run.

Implementation changes: none; no code, schemas, tests, README, PRD, VISION, Beads, config, or memory files were edited.
