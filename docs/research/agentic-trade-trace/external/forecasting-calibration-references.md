# External Evidence Packet: Forecasting and Calibration References

**Retrieval date:** 2026-05-22  
**Program bead:** `trade-trace-r03m`  
**Decision hooks:** `trade-trace-zey2` and later evaluation/calibration synthesis  
**Scope:** External research references for evaluating agentic Trade Trace forecasts, decisions, non-actions, and process. This packet is about grading and retrospective diagnostics, not proving LLM trading profitability.

## 1. Bottom Line

Trade Trace should evaluate agent decisions with a small, conservative forecasting diagnostics stack:

1. **Proper scoring rules for resolved binary forecasts**: Brier score as the primary interpretable score; log score as a stricter optional diagnostic for overconfident misses.
2. **Calibration and reliability diagnostics**: reliability bins/diagrams, expected calibration error (ECE) or similar bin-gap summaries, plus counts per bin so sparse samples are visible.
3. **Sharpness/resolution diagnostics**: do not reward calibration alone; compare whether the agent made forecasts that meaningfully departed from base rates and separated events that happened from events that did not.
4. **Baselines and reference classes**: every forecast report should compare against simple prevalence/base-rate forecasts and, where an agent supplies an external market price, prediction-market or market-implied probabilities.
5. **Resolution discipline**: outcomes need explicit, auditable resolution criteria and source provenance; otherwise scores are not meaningful.
6. **Process evaluation over profitability claims**: scores should grade forecast quality, overconfidence, evidence use, recall use, and decision process, while staying inside Trade Trace's no-execution/no-data-fetching/no-financial-advice boundary.

**Confidence:** Medium. The scoring/calibration practices are well-established in forecasting and ML calibration literature, but this subagent's web search/extract tools returned HTTP 432 errors during retrieval. URLs below are stable source trails to verify in the controller session; the artifact labels this retrieval weakness explicitly.

## 2. Findings

### F1 — Use proper scoring rules so truthful probabilities are incentivized.

- **Claim type:** Observed fact from external literature standard; recommendation for Trade Trace.
- **Confidence:** High for the general scoring-rule principle; medium for this packet because direct extraction failed.
- **Evidence/source IDs:** S1, S2, S3.
- **Finding:** Brier score and logarithmic score are canonical proper scoring rules for probabilistic forecasts. Proper scoring rules are designed so the forecaster optimizes expected score by reporting true beliefs, unlike ad hoc hit-rate metrics that can reward uncalibrated thresholding.
- **Trade Trace implication:** For each resolvable binary forecast attached to a decision/watch/skip/thesis, store/report probability, outcome, score, and aggregation scope. Prefer Brier for default reports because it is bounded and interpretable; add log score as an optional overconfidence alarm because it penalizes near-certain wrong forecasts sharply.

### F2 — Brier score is useful but should be decomposed/interpreted with calibration and resolution.

- **Claim type:** Observed fact from forecasting literature; recommendation.
- **Confidence:** High generally; medium for direct retrieval.
- **Evidence/source IDs:** S1, S4.
- **Finding:** The Brier score for binary events is the squared error between forecast probability and outcome. Classic forecast verification decomposes mean Brier score into components associated with reliability/calibration, resolution, and uncertainty/base rate.
- **Trade Trace implication:** A single average Brier score is not enough. Reports should show:
  - aggregate Brier score;
  - sample size and event prevalence;
  - reliability/calibration by probability bin;
  - resolution/sharpness indicators, e.g. whether forecasts away from the base rate separated outcomes;
  - comparison to a base-rate forecast.

### F3 — Calibration/reliability diagrams expose whether “70%” events happen about 70% of the time.

- **Claim type:** Observed fact from ML calibration practice; recommendation.
- **Confidence:** High generally; medium for direct retrieval.
- **Evidence/source IDs:** S5, S6.
- **Finding:** Reliability diagrams/calibration curves group predictions by predicted probability and compare predicted probability to observed frequency. They are standard for diagnosing probabilistic classifier calibration.
- **Trade Trace implication:** Agent calibration reports should bin forecasts, show mean predicted probability vs. observed frequency, include bin counts, and avoid over-interpreting bins with very few resolved cases. This directly supports agentic questions such as “was this model/strategy/playbook overconfident on 60–80% forecasts?”

### F4 — Expected Calibration Error is compact but can hide binning and sample-size artifacts.

- **Claim type:** Observed fact/inference from ML calibration literature; recommendation.
- **Confidence:** Medium.
- **Evidence/source IDs:** S6, S7.
- **Finding:** ECE summarizes the weighted average gap between confidence and empirical accuracy across bins. It is common in ML calibration, but depends on binning choices and can obscure sparse or uneven bins.
- **Trade Trace implication:** ECE-like summaries can be useful as a dashboard/report field, but should never appear without bin definitions, counts, and the underlying reliability table. For trading agents with small sample sizes, qualitative “insufficient resolved cases” flags may be more honest than a precise ECE.

### F5 — Sharpness/resolution matters: a perfectly calibrated agent can still be useless if it only predicts base rates.

- **Claim type:** Observed fact from probabilistic forecasting theory; inference for product design.
- **Confidence:** High generally; medium for direct retrieval.
- **Evidence/source IDs:** S2, S4.
- **Finding:** Good probabilistic forecasting seeks calibration/reliability and sharpness/resolution. A forecast stream can be calibrated by always predicting the base rate, but it has little decision value if it does not discriminate cases.
- **Trade Trace implication:** Reports should compare against prevalence/base-rate baselines and record whether forecasts are meaningfully different from baseline. The product should avoid congratulating an agent for low-risk but uninformative probabilities.

### F6 — Base rates/reference classes are essential baselines for agent forecasts.

- **Claim type:** Recommendation grounded in forecasting practice.
- **Confidence:** Medium.
- **Evidence/source IDs:** S8, S9.
- **Finding:** Forecasting practice emphasizes reference classes/base rates before case-specific adjustments. In prediction tasks, a simple prevalence forecast is often the minimum baseline.
- **Trade Trace implication:** Every evaluation slice should show an available baseline: global event prevalence, strategy-specific prevalence, instrument/setup prevalence, or a user/agent-supplied reference class. Where no defensible baseline exists, reports should say so rather than imply edge.

### F7 — Prediction-market implied probabilities can be comparison references, not truth.

- **Claim type:** Observed fact/inference; recommendation.
- **Confidence:** Medium.
- **Evidence/source IDs:** S10, S11.
- **Finding:** Prediction-market prices are often interpreted as implied probabilities after accounting for contract design, fees, liquidity, bid/ask spread, and market microstructure. They can be useful crowd/market baselines but are not clean ground truth.
- **Trade Trace implication:** If an agent records a prediction-market price or market-implied probability at decision time, Trade Trace can compare the agent forecast to that reference. It should store spread/liquidity/caveats when supplied and label the comparison as retrospective context, not as execution advice or an automatically fetched market signal.

### F8 — Good forecasting practice requires clear resolution criteria and timestamped commitments.

- **Claim type:** Observed fact from forecasting tournament/open forecasting practice; recommendation.
- **Confidence:** High generally; medium for direct retrieval.
- **Evidence/source IDs:** S8, S9, S12.
- **Finding:** Forecasting platforms and tournaments rely on clearly specified questions, time horizons, resolution criteria, and resolved outcomes. Ambiguous resolution undermines score validity.
- **Trade Trace implication:** A forecast primitive should carry due/resolution date, event definition, resolution source/provenance, and outcome status. Unresolved or ambiguously resolved forecasts should be excluded or separately flagged in calibration reports.

### F9 — LLM forecasting benchmarks are emerging but should not be treated as proof of trading profitability.

- **Claim type:** Observed fact from emerging benchmark literature; caution/recommendation.
- **Confidence:** Low-to-medium; web retrieval failed and the field is moving quickly.
- **Evidence/source IDs:** S13, S14.
- **Finding:** Recent work evaluates LLMs on forecasting questions using benchmark/tournament-style tasks and probabilistic scoring. This is relevant to how to grade agent forecasts, but not enough to claim market edge.
- **Trade Trace implication:** Use benchmark-inspired patterns—question specification, probability commitments, scoring, calibration by bins, resolution source trails—but keep product claims limited to process diagnostics and retrospective evaluation.

## 3. Source Trail

> Retrieval note: `web_search` and `web_extract` calls attempted on 2026-05-22 failed with Tavily HTTP 432 errors. The following source trail is therefore a verification queue with stable URLs and expected relevance, not a claim that full page text was successfully extracted in this subagent session.

| ID | Title / source | Publisher / type | URL | Trust tier | Relevance | Retrieval date |
|---|---|---|---|---|---|---|
| S1 | “Verification of forecasts expressed in terms of probability” | Glenn W. Brier, Monthly Weather Review, 1950 | https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2 | Primary academic | Introduces Brier score for probability forecasts. | 2026-05-22 |
| S2 | “Strictly Proper Scoring Rules, Prediction, and Estimation” | Gneiting & Raftery, Journal of the American Statistical Association, 2007 | https://doi.org/10.1198/016214506000001437 | Primary academic/review | Proper scoring rules; calibration/sharpness framing. | 2026-05-22 |
| S3 | Proper scoring rule | Wikipedia overview | https://en.wikipedia.org/wiki/Proper_scoring_rule | Secondary | Quick reference for Brier/log score as proper scoring rules; should be verified against primary sources. | 2026-05-22 |
| S4 | “Decomposition of the Brier score” / forecast verification references | Forecast verification literature; Murphy decomposition commonly cited | https://doi.org/10.1175/1520-0450(1973)012%3C0595:ANVFOT%3E2.0.CO;2 | Primary academic | Reliability, resolution, uncertainty decomposition. | 2026-05-22 |
| S5 | Probability calibration | scikit-learn user guide | https://scikit-learn.org/stable/modules/calibration.html | Technical documentation | Reliability diagrams/calibration curves and probability calibration practice. | 2026-05-22 |
| S6 | “On Calibration of Modern Neural Networks” | Guo et al., ICML 2017 | https://proceedings.mlr.press/v70/guo17a.html | Primary ML paper | ECE and neural-network calibration discussion. | 2026-05-22 |
| S7 | “Verified Uncertainty Calibration” / ECE limitations literature | Kumar, Liang & Ma, NeurIPS 2019 | https://proceedings.neurips.cc/paper/2019/hash/f8c0c968632845cd133308b1a494967f-Abstract.html | Primary ML paper | Limitations/verification of calibration error estimates. | 2026-05-22 |
| S8 | Good Judgment Open — About / forecasting platform | Good Judgment Open | https://www.gjopen.com/about | Practitioner platform | Open forecasting/tournament-style probabilistic questions. | 2026-05-22 |
| S9 | “Superforecasting: The Art and Science of Prediction” | Tetlock & Gardner, 2015 | Book / practitioner-scientific | ISBN: 9780804136693; publisher page: https://www.penguinrandomhouse.com/books/227815/superforecasting-by-philip-e-tetlock-and-dan-gardner/ | High-quality secondary | Base rates, updating, probabilistic forecasting practice. | 2026-05-22 |
| S10 | Prediction market | Wikipedia overview | https://en.wikipedia.org/wiki/Prediction_market | Secondary | Implied probabilities from market prices and caveats. | 2026-05-22 |
| S11 | Polymarket / prediction-market docs or help pages | Platform documentation | https://docs.polymarket.com/ | Practitioner docs | Contract/market mechanics if Trade Trace stores market-implied reference probabilities. | 2026-05-22 |
| S12 | Metaculus scoring / question resolution documentation | Metaculus | https://www.metaculus.com/help/ | Practitioner platform docs | Resolution criteria, scoring, tournament practice. | 2026-05-22 |
| S13 | ForecastBench | LLM forecasting benchmark, arXiv/GitHub depending final venue | https://arxiv.org/search/?query=ForecastBench+LLM+forecasting&searchtype=all | Emerging academic | Candidate benchmark for LLM forecasting evaluation patterns; requires controller verification. | 2026-05-22 |
| S14 | “Approaching Human-Level Forecasting with Language Models” | Halawi et al., arXiv/benchmark literature | https://arxiv.org/abs/2402.18563 | Emerging academic | LLM forecasting methodology; not trading-profitability evidence. | 2026-05-22 |

## 4. Contradictions, Weak Evidence, Missing Evidence, and Stale Risks

- **Direct retrieval failure:** Web tools failed with HTTP 432, so the controller should verify URLs/text before treating this as fully source-extracted evidence.
- **Small-sample calibration risk:** Trading-agent forecasts may be sparse by strategy/instrument/timeframe. Reliability bins, Brier averages, and ECE can be unstable with low counts.
- **Outcome ambiguity risk:** Market/trading theses often resolve partially or across multiple horizons. Binary scoring is clean only when the event definition and resolution source are explicit.
- **Base-rate selection risk:** Choosing the wrong reference class can make the agent look better or worse arbitrarily. Reports should expose the baseline definition.
- **Prediction-market comparison caveat:** Implied probabilities can be distorted by fees, thin liquidity, bid/ask spreads, contract wording, and participant constraints. They are useful comparison references, not ground truth.
- **Log score brittleness:** Log score is highly sensitive to probabilities near 0 or 1. This is useful for overconfidence diagnostics but can dominate small samples.
- **LLM benchmark staleness:** LLM forecasting benchmark results will age quickly as models and prompting systems change. Product decisions should copy evaluation structure, not model-performance claims.
- **Profitability boundary:** Calibration quality is not alpha. A calibrated agent can still make unprofitable decisions after costs, slippage, or bad opportunity selection; Trade Trace should not claim otherwise.

## 5. Decision Hooks for Trade Trace

For `trade-trace-zey2` and later evaluation synthesis, this packet supports the following product-direction questions:

1. **Forecast diagnostics primitive:** Adopt retrospective forecast scoring as a core evaluation capability, centered on Brier score plus calibration/resolution tables.
2. **Baseline fields:** Require or encourage evaluation slices to name a base-rate/reference-class baseline; show “baseline unavailable” when absent.
3. **Resolution provenance:** Treat explicit resolution criteria/source/outcome status as mandatory for scored forecasts.
4. **Agent process reports:** Use forecast scores to evaluate decisions, non-actions, strategies, playbook adherence, and recall usage, not to recommend trades.
5. **Market-implied comparison:** Allow agent-supplied market-implied probability snapshots as comparison references with provenance/caveats; do not fetch them or treat them as truth.
6. **Calibration report guardrails:** Always include sample counts, bin definitions, unresolved counts, and low-N warnings; avoid single-number calibration theater.
7. **Reflection quarantine input:** Use repeated calibration failures, overconfidence, or poor resolution against base rates as evidence that can inform quarantined reflections or proposed playbook changes.

## 6. Controller Verification Addendum

After the delegated packet was written, the controller performed direct source fetches with Python `urllib` because the Tavily-backed `web_search`/`web_extract` path returned HTTP 432.

Verified on 2026-05-22:

- `https://proceedings.mlr.press/v70/guo17a.html` loaded successfully with title **On Calibration of Modern Neural Networks**. Extracted text describes confidence calibration as predicting probability estimates representative of true correctness likelihood. This supports F3/F4 and ECE-related calibration caution.
- `https://scikit-learn.org/stable/modules/calibration.html` loaded successfully with title **Probability calibration — scikit-learn documentation**. Extracted metadata describes obtaining class probabilities and confidence. This supports use of calibration curves/reliability-style diagnostics as standard ML practice.
- `https://arxiv.org/abs/2402.18563` loaded successfully with title **Approaching Human-Level Forecasting with Language Models**. This verifies the LLM-forecasting reference exists; it remains benchmark/evaluation-structure evidence only, not profitability evidence.
- `https://www.gjopen.com/about` loaded successfully with title **Good Judgment Open**. This verifies the open-forecasting platform reference exists, but the controller did not extract detailed methodology from the page.

Still not verified in the controller session:

- Brier 1950 and Gneiting/Raftery DOI full text.
- Metaculus help page, which returned 403.
- Polymarket docs details.
- ForecastBench-specific source beyond the arXiv search trail.

Decision impact: the packet is decision-useful for general scoring/calibration direction, especially Brier/log-score/proper-scoring/calibration concepts, but any final evidence packet should verify primary scoring-rule sources before using exact literature claims as authoritative citations.

## 7. Side Effects

Files written:

- `docs/research/agentic-trade-trace/external/forecasting-calibration-references.md`

Memory retained: none.  
External side effects: attempted web search/extract calls; all returned HTTP 432 errors.  
Implementation changes: none; no code, schemas, tests, README/PRD/VISION, Beads, config, or implementation-bearing files were edited.
