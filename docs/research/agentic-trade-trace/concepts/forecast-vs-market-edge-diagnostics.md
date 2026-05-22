# Concept Dossier: Forecast-vs-Market Edge Diagnostics

## 1. Question

Should Trade Trace adopt forecast-vs-market edge diagnostics as a core retrospective evaluation concept that compares agent forecasts, caller-supplied market context, base-rate/reference-class baselines, and resolved outcomes across decisions, non-actions, and strategies without fetching market data or claiming profitability?

## 2. Bottom Line

- Recommendation: **adopt core**.
- Confidence: **high** for retrospective forecast/calibration diagnostics; **medium** for market-implied comparison details.
- Why: Trade Trace already records forecasts, snapshots with `implied_probability`/spread/liquidity fields, decisions including non-actions, outcomes, strategy scope, source provenance, and calibration reports with Brier/log score, ECE, reliability bins, sharpness, baseline, skill, sample-size warnings, and late-recorded exclusion. The concept should be elevated as a product shape because fresh-session agents need a bounded way to ask, “Was my probability better calibrated than simple references, and did any claimed edge survive outcome review?” It must remain retrospective process evidence, not a live market data service, trading signal, or profitability proof.

## 3. Agent-Specific Problem

A human trader may remember whether a “70%” conviction was really distinct from the market, whether the venue was thin, or whether a skip was smart after the fact. A fresh-session LLM trading agent does not preserve those distinctions unless the system records and reports them. The agent-specific failure modes are:

- **Probability drift across sessions:** one run records a forecast; another resolves it; a later run may only see a score, not the base-rate or market context that made the forecast meaningful.
- **False edge claims:** an agent may say “edge” because its forecast differs from price, but the gap may be spread/fee/liquidity/contract-wording noise, a bad reference class, or low-N luck.
- **Calibration theater:** a single Brier score can look precise even when there are only a few resolved forecasts, ambiguous outcomes, or late-recorded probabilities.
- **Non-action invisibility:** watches/skips/holds may contain useful edge judgments, but if only entered trades are reviewed the agent learns from a biased subset.
- **Strategy smearing:** a model may be calibrated in one strategy and overconfident in another; aggregate reports can hide that.
- **Reflection poisoning:** if diagnostics are weakly caveated, the agent may promote “I have edge in thin markets” into a playbook rule from one case.

Forecast-vs-market diagnostics matter because they make probabilistic reasoning inspectable for stateless agents: not “should I trade now?” but “what did I forecast, against which reference, with what market context, and how did it resolve?”

## 4. Current Baseline

### Implemented / observed substrate

- Forecasts are first-class ledger rows with forecast outcomes/probabilities, resolution times, yes labels, resolution rules, scoring support/state, segmentation metadata, and append-only score events (`docs/PRD.md:175-192`; `docs/architecture/scoring.md:32-49`, `151-220`).
- `outcome.add` / `resolve.record` appends outcomes and triggers auto-scoring only for `resolved_final` outcomes; ambiguous, disputed, void, cancelled, or superseded outcomes are not auto-scored as final truth (`docs/architecture/scoring.md:242-281`, `331-345`; `src/trade_trace/tools/ledger.py:1120-1173`).
- Live scoring computes at least binary Brier and, according to current scoring docs/source, also supports categorical/multiclass and scalar score rows (`docs/architecture/scoring.md:6-14`, `106-149`; `src/trade_trace/tools/ledger.py:1227-1247`). The PRD’s earlier MVP text still emphasizes binary-only scope, so non-binary breadth is an area of doc/status drift to verify before depending on it (`docs/PRD.md:68-78`, `175-184`).
- `report.calibration` loads scored binary forecasts and computes Brier, log score, ECE, sharpness, sample-prevalence baseline, Brier/log baselines, skill, 10 equal-width reliability bins, sample size, low-N warning, examples, and late-recorded exclusions (`src/trade_trace/reports/calibration.py:51-136`, `303-400`; `docs/architecture/scoring.md:352-426`).
- `report.compare` can group calibration by `agent_id`, `model_id`, `strategy_id`, decision type, venue, asset class, environment, instrument, or outcome status; unsupported future groupings such as liquidity bucket and confidence bucket are explicitly not live in the current mapping (`src/trade_trace/reports/compare.py:35-69`, `122-166`; `docs/PRD.md:390-394`).
- Snapshots record caller-supplied price, bid, ask, mid, spread, volume, open interest, `implied_probability`, and `liquidity_depth_json` (`docs/PRD.md:158-162`, `342-355`; `src/trade_trace/tools/ledger.py:306-323`, `346-357`). Trade Trace does not fetch those values.
- Decisions reference instruments, theses, forecasts, snapshots, strategies, playbook versions, tags, and decision types including `watch`, `skip`, `hold`, `review`, thesis updates/invalidations, paper actions, and record-only actual actions (`docs/PRD.md:194-229`, `342-355`; `docs/research/agentic-trade-trace/concepts/decision-non-action-lifecycle.md`).
- Sources attach to theses, decisions, forecasts, and memory nodes, giving diagnostics an evidence-provenance path without fetching URLs or local paths automatically (`docs/PRD.md:260-268`, `415-420`).
- Existing reports already include calibration integrity, source quality, audit readiness, watchlist, unscored forecasts, coach, compare, and review bundle surfaces that can supply related hygiene data (`docs/PRD.md:364-388`; `docs/research/agentic-trade-trace/01-current-system-baseline.md:51-59`).

### Planning / deferred baseline

- PRD explicitly names forecast-vs-market edge, calibration-by-liquidity-bucket, and skipped-positive-edge review as deferred trading-native reports; it says the data is already captured in snapshots and the reports are additive (`docs/PRD.md:386-388`).
- The concept taxonomy classifies forecast-vs-market diagnostics as a core evaluation concept, bounded to retrospective reporting and no market fetching/advice (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:35-49`, `140-145`).
- External synthesis strongly supports forecast diagnostics as product direction while warning that calibration quality is not profitability or alpha (`docs/research/agentic-trade-trace/synthesis/external-evidence.md:20-24`, `47`, `74-76`).

### Current gap

The current system has strong forecast scoring and calibration reports, but no named “forecast-vs-market edge diagnostics” surface that joins:

- agent probability vs snapshot-implied probability;
- base-rate/reference-class baseline vs agent probability;
- spread/liquidity/cost caveats;
- entered decisions and non-actions;
- strategy/playbook/agent/model slices;
- source/outcome/late-recorded/low-N integrity caveats;
- reflection/quarantine hooks.

Today, an agent can inspect these ingredients through separate reports and records. The product concept is the retrospective diagnostic bundle that makes the edge question explicit without crossing into advice.

## 5. Candidate Product Shape

The candidate shape is a **retrospective diagnostic bundle** over recorded artifacts. It should answer: “For this slice of historical forecasts/decisions/non-actions, what was the agent’s probability quality, how did it compare to recorded references, and what caveats limit interpretation?”

Conceptual components:

1. **Forecast scoring panel**
   - Brier score, log score, reliability bins, ECE, sharpness, sample size, scored/unscored counts, failed/ambiguous counts, late-recorded exclusions, and representative worst/high-gap cases.
   - Binary-first for product claims; non-binary diagnostics should be treated as current-capability verification rather than assumed core until source/docs drift is resolved.

2. **Base-rate / reference-class comparison**
   - Sample prevalence baseline already exists in `report.calibration`.
   - Future conceptual diagnostics should name the reference class used: global, strategy, venue, asset class, instrument, decision type, tag/setup, playbook version, or agent-supplied custom baseline.
   - If no defensible baseline exists, the report should say `baseline_unavailable` rather than imply skill.

3. **Market-implied comparison, only when supplied**
   - Compare agent `p_yes` to caller-supplied `snapshot.implied_probability`, or derive only if the caller explicitly supplied the derived field.
   - Report direction and magnitude of `agent_probability - market_implied_probability`, but label it as **recorded market reference gap**, not edge proof.
   - Include bid/ask/spread/liquidity/depth/source caveats when present; if missing, emit `market_reference_caveat` rather than fabricating context.

4. **Decision / non-action coverage**
   - Include forecasts tied to `paper_enter`, record-only actual decisions, watches, skips, holds, reviews, thesis updates, and strategy reviews.
   - Separate coverage slices: forecasts attached to decisions; decisions without forecasts; forecasts without decisions; non-actions with forecasts; unresolved forecasts past due.
   - Avoid evaluating only filled/entered positions, which would bias learning away from missed or rejected opportunities.

5. **Strategy and actor segmentation**
   - Slice by strategy, agent, model, environment, run, decision type, venue, asset class, and instrument where sample size allows.
   - If a strategy slice is below threshold, show low-N warnings and avoid ranking strategies by edge.

6. **Evidence and integrity overlay**
   - Join or cite source-quality/audit-readiness/calibration-integrity diagnostics: missing sources, stale/contradictory sources, resolution-rule gaps, late-recorded forecasts, disputed outcomes, unsupported kinds, suspicious late rates.
   - Diagnostics should return drill-down IDs for forecasts, decisions, snapshots, outcomes, sources, strategies, and reflections.

7. **Reflection/quarantine hook**
   - Repeated overconfidence, poor reference-class choice, or market-implied-gap failure can become evidence for a quarantined reflection or playbook candidate.
   - The bundle should not auto-promote a playbook rule and should not say which market action to take.

## 6. Required Data / State

Required existing state:

- **Forecast state:** forecast id, thesis id, kind, outcomes/probabilities, yes label, resolution rule, resolution_at, scoring support/state, valid time, supersession state, late-recorded metadata.
- **Score/outcome state:** forecast score rows, metric, score, outcome id, outcome status, outcome label/value, outcome source/confidence, outcome supersession edges.
- **Snapshot / market-reference state:** snapshot id, captured_at, price, bid, ask, mid, spread, volume, open interest, `implied_probability`, liquidity depth, source/source_url/metadata, and any caller-supplied caveats.
- **Decision/non-action state:** decision id/type, forecast/thesis/snapshot ids, reason, review_by, tags, strategy id, playbook version id, side/quantity/price where relevant.
- **Source/evidence state:** source rows and edges to thesis/forecast/decision/memory; stance, freshness, redaction, content hash, provenance metadata.
- **Strategy / playbook / reflection state:** strategy ids/status/hypothesis, playbook adherence, reflections linked to outcomes/decisions/strategies, candidate playbook provenance where applicable.
- **Attribution/filter state:** actor id, `agent_id`, `model_id`, `environment`, `run_id`, timestamps, idempotency/event records.
- **Derived/report state:** reliability bins, base-rate baseline, low-N warnings, integrity diagnostics, source-quality diagnostics, unscored forecast lists, watchlist/stale non-actions.

Potential future conceptual state, not implementation-approved:

- Named reference-class definitions or report parameters for baseline selection.
- Market-reference caveat codes such as missing implied probability, stale snapshot, wide spread, thin liquidity, missing depth, contract wording mismatch, or source missing.
- Diagnostic case bundles keyed by forecast/decision/snapshot/outcome IDs for replay and reflection.
- Optional agent-supplied market-implied probability provenance when it differs from snapshot fields.

## 7. Machine Interface Implications

Future agent-facing surfaces should remain CLI/MCP/JSON-first and report-like. Conceptually, an agent should be able to request a diagnostic bundle with filters and receive structured outputs such as:

- `summary`: sample size, low-N warning, scored/unscored/failed/late/ambiguous counts, date range, filters applied, and caveats.
- `forecast_metrics`: Brier, log score, ECE, sharpness, reliability bins, prevalence baseline, skill, and worst/example forecast IDs.
- `reference_class`: baseline type, definition, count, prevalence, baseline scores, and “unavailable/low-N” status.
- `market_reference`: counts with supplied implied probability, average forecast-vs-implied gap, gap bins, spread/liquidity coverage, and caveat codes.
- `decision_coverage`: counts by decision type, including watches/skips/holds and decisions without forecasts.
- `groups`: strategy/agent/model/venue/asset/instrument/decision-type slices, each with independent sample warnings.
- `case_refs`: bounded lists of forecast/decision/snapshot/outcome/source/strategy IDs for drill-down or `review.bundle` handoff.
- `process_hooks`: suggested process follow-ups such as “resolve overdue forecasts,” “inspect low-N slice,” “write reflection for repeated overconfidence,” or “attach missing source”; never “buy/sell/enter/exit.”

Interface guardrails:

- No market fetching, price polling, URL fetching, broker access, or outcome fetching.
- No current trade recommendation or opportunity ranking by expected profit.
- No claim that beating a base rate or market-implied reference proves profitability, alpha, or good execution.
- No hidden derivation of implied probability from live prices unless the caller supplied the values and the derivation basis.
- Low-N and missing-reference caveats must be first-class fields, not buried prose.

## 8. Evidence

- Repo evidence:
  - Research contract places forecasts, decisions, non-actions, strategies, reflections, calibration, and machine-readable abstractions in scope while excluding market-data fetching, execution, profitability claims, and implementation (`docs/research/agentic-trade-trace/00-research-contract.md:18-39`).
  - Current baseline says Trade Trace implements ledger/source/snapshot/forecast/decision/outcome primitives, binary auto-scoring, reports, strategies, playbooks, sources, and segmentation fields; it identifies calibration usefulness as dependent on disciplined forecast creation and enough scored forecasts (`docs/research/agentic-trade-trace/01-current-system-baseline.md:21-49`).
  - PRD states Trade Trace never fetches market data, supports manual ingestion of snapshots/forecasts/decisions/outcomes, records snapshots with `implied_probability`/spread/liquidity fields, includes calibration reports, and defers forecast-vs-market reports as additive trading-native reports (`docs/PRD.md:7-28`, `49-78`, `158-184`, `342-388`).
  - Scoring docs and `report.calibration` source define Brier/log score, reliability bins, ECE, sharpness, prevalence baseline, skill, sample-size warnings, late-recorded exclusion, and resolved-final-only scoring (`docs/architecture/scoring.md`; `src/trade_trace/reports/calibration.py`).
  - `report.compare` source supports calibration slices by several actor/strategy/market dimensions but not liquidity/confidence buckets yet (`src/trade_trace/reports/compare.py:35-69`).
  - `snapshot.add` source records caller-supplied market context including implied probability and liquidity fields (`src/trade_trace/tools/ledger.py:306-323`, `346-357`).
- External evidence:
  - Forecasting/calibration packet supports proper scoring rules, Brier/log score, reliability/calibration bins, ECE caveats, sharpness/resolution, base-rate/reference-class baselines, resolution discipline, low-N warnings, and market-implied comparisons only as caveated references (`docs/research/agentic-trade-trace/external/forecasting-calibration-references.md:8-18`, `23-90`, `121-143`).
  - External evidence synthesis classifies forecast-vs-market diagnostics as strongly supported for scoring direction and medium-supported for market-implied comparisons, while warning that calibration is not profitability (`docs/research/agentic-trade-trace/synthesis/external-evidence.md:20-24`, `47`, `60-62`, `74-76`).
- User-stated intent:
  - The delegated task explicitly asks for retrospective forecast scoring/calibration, base-rate/reference-class comparisons, market-implied probabilities if agent-supplied, Brier/log/reliability/sharpness, low-N warnings, forecasts tied to decisions/non-actions/strategies, no profitability/advice claims, and no market fetch.
- Inferences:
  - Because core data already exists, the concept is less about new capture and more about joining/caveating existing forecasts, snapshots, decisions, outcomes, strategies, and reports into an explicit edge-diagnostic product shape.
  - Market-implied comparison is valuable only when caveated and caller-supplied; otherwise it conflicts directly with the no-fetch boundary and risks becoming advice.
  - Low-N warnings and reference-class disclosure are not optional safety polish; they are necessary to prevent agents from overfitting their future reflections/playbook rules.

## 9. Risks/Failure Modes

- **Advice boundary drift:** “forecast beat market” can be misread as “trade this setup.” Outputs must be retrospective diagnostics only.
- **Profitability overclaim:** Better Brier/skill vs prevalence does not prove positive expected value after fees, spreads, slippage, sizing, liquidity, or execution quality.
- **Market-implied misuse:** Prediction-market or snapshot-implied probabilities may be distorted by contract wording, fees, thin liquidity, spread, stale prices, or participant constraints.
- **Low-N false certainty:** Strategy/instrument slices may have too few resolved cases for meaningful reliability bins or skill estimates.
- **Reference-class gaming:** Choosing a favorable baseline can manufacture apparent skill. Baseline definitions must be explicit and counts shown.
- **Outcome ambiguity:** Disputed/void/ambiguous outcomes poison calibration if scored as final; resolved-final-only handling must remain visible.
- **Late-recorded/rationalized forecasts:** Probabilities created after outcome or after resolution time can make the agent look falsely calibrated unless excluded/caveated.
- **Selection bias:** Reviewing only entered trades omits skipped/watched/held forecasts and can misrepresent agent decision quality.
- **Strategy smearing:** Aggregates can hide one strategy’s overconfidence behind another’s calibration.
- **Metric theater:** ECE/log score/reliability numbers may be copied into playbook policy without enough cases or source/outcome integrity.
- **Scope creep into data connector:** Requests for market-implied probabilities may tempt live price fetching; this concept must rely on caller-supplied snapshots only.

## 10. Dependencies/Conflicts

Dependencies:

- **Decision and non-action lifecycle:** supplies the forecast/decision/non-action cases that diagnostics should evaluate, including watches/skips/holds and review transitions.
- **Agent work queue / next actions:** consumes unresolved forecasts, unscored forecasts, stale watches, missing market-reference fields, and missing reflections as process obligations.
- **Reflection-to-policy quarantine:** consumes repeated calibration failures, base-rate errors, market-reference caveats, and low-N warnings before any rule promotion.
- **Strategy state and lifecycle:** scopes diagnostics by edge thesis so calibration and market-reference gaps do not smear across unrelated strategies.
- **Recall receipts:** can help determine whether prior calibration lessons or playbook rules were retrieved before a later forecast/decision.
- **Replay/regression substrate:** can package diagnostic cases to test whether a new agent/model/playbook would handle the same recorded context differently.
- **Source/evidence provenance and audit readiness:** supply resolution-rule, source freshness, contradiction, and snapshot-quality caveats.

Conflicts / boundaries:

- Conflicts with product boundary if it requires market-data fetching, live outcome fetching, broker data, execution, alerting, or best-trade ranking.
- Conflicts with safety posture if it frames outputs as financial advice or autonomous edge generation.
- Conflicts with append-only/audit discipline if it mutates old forecasts/outcomes to repair scores rather than using supersession/caveats.
- Potential doc/status conflict: PRD says broader trading-native reports are deferred and earlier forecast model text is binary-only, while current scoring docs/source indicate broader scoring support. Future decisions should verify live implementation before committing product claims around non-binary diagnostics.

## 11. Open Questions/Falsifiers

- What reference-class hierarchy is useful without becoming gameable: global, strategy, venue, asset class, instrument, decision type, tag/setup, or explicit agent-supplied class?
- Should market-implied probability live only in snapshots, or should diagnostics allow a separate caller-supplied market-reference object with provenance/caveats?
- What minimum sample thresholds should apply to reliability bins, strategy slices, market-implied-gap slices, and base-rate skill claims?
- How should diagnostics treat non-actions with no explicit forecast but a reason implying edge/no-edge?
- Should skipped-positive-edge review be part of this concept or remain a downstream/non-action review concept?
- Can liquidity/spread buckets be derived safely from existing snapshot fields, or would bucket semantics require an implementation-spec phase and tests?
- How should categorical/scalar forecast diagnostics be represented given PRD/source/doc drift around scoring breadth?
- What caveat vocabulary is sufficient for prediction-market vs equity/crypto/futures contexts without becoming venue-specific market microstructure modeling?
- Falsifier: if dogfood agents can reliably answer forecast-vs-market/base-rate questions using existing `report.calibration`, `report.compare`, `review.bundle`, and raw snapshot queries without missed caveats or context loss, this concept may remain a report recipe rather than a core primitive.
- Falsifier: if useful market-implied comparison cannot be done without fetching live/historical market data, the market-comparison portion should be rejected or limited to stored snapshot fields.
- Falsifier: if outputs are repeatedly interpreted by agents as trade recommendations despite caveats, the surface should be narrowed to internal review bundles and quarantine inputs.

## 12. Decision Hook

This dossier should be consumed by `trade-trace-4d5e` and downstream evaluation/calibration synthesis, plus `trade-trace-34c2` for replay/regression and `trade-trace-9lgd` for cross-concept dependency/conflict mapping. Recommended decision framing: adopt **forecast-vs-market edge diagnostics** as a core retrospective evaluation primitive over existing forecasts, snapshots, decisions/non-actions, outcomes, strategies, sources, and calibration reports; keep implementation, live market fetching, and advice/profitability claims out of scope.

## 13. Side Effects

Files written:

- `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/concepts/forecast-vs-market-edge-diagnostics.md`

Files modified besides this artifact: none.

Memory retained: none.

External/network side effects: none; no web or market-data fetches were run.

Implementation changes: none; no Beads, code, schemas, tests, README, PRD, VISION, config, or runtime files were edited.
