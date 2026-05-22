# External Evidence Packet: Human Trading-Journal Patterns for Agent-Only Trade Trace

**Retrieval date:** 2026-05-22  
**Bead:** `trade-trace-zlqi`  
**Mode:** external research, research-only, no implementation

## 1. Bottom Line

Human trading journals repeatedly organize learning around a small set of patterns that translate well to an agent-only, machine-readable Trade Trace: record intent before outcome, classify the setup/strategy, tag context and mistakes, preserve pre/post trade plans, log skipped/missed trades, review on a cadence, normalize results by risk/R, inspect excursion/opportunity metrics such as MAE/MFE, attach evidence/screenshot analogues, and compare behavior to a playbook/ruleset.

For Trade Trace, the product implication is **not** to copy human dashboards, social sharing, chart annotation UX, broker import flows, or manual journaling forms. The useful translation is to make these patterns durable, queryable, source-linked, and agent-consumable as JSON-first primitives for decision lifecycle, non-actions, strategy state, diagnostics, work queues, bootstrap packs, and playbook adherence.

**Evidence quality caveat:** The web search/extract backend returned HTTP 432 for all attempted retrievals during this task. The source trail therefore records the intended public sources and claim areas, but the specific claims below should be treated as **medium confidence from widely documented product/methodology patterns, not freshly extracted quotations**. Downstream synthesis should re-fetch these URLs before treating this packet as fully source-verified.

## 2. Findings

### F1. Decision-before-outcome is the core transferable pattern.

- **Claim type:** Recommendation / inference from trading-journal methodology.
- **Confidence:** Medium, pending re-fetch.
- **Human-journal pattern:** Journals ask traders to record entry rationale, setup, risk, stop/target, market context, and plan before the result is known so review can distinguish process quality from outcome luck.
- **Agent-only translation:** Trade Trace should preserve pre-outcome decision artifacts as immutable or append-only records: thesis, forecast, decision type, planned invalidation, risk unit, source IDs, strategy/playbook references, and timestamp/run attribution.
- **Reject human-only parts:** Rich text diary UX, dashboard widgets, and manual form convenience.
- **Relevant source IDs:** S1, S5, S6.

### F2. Tags, setup labels, and strategy classification are common because aggregate review requires segmentation.

- **Claim type:** Observed-pattern inference from journal products.
- **Confidence:** Medium, pending re-fetch.
- **Human-journal pattern:** Products such as Tradervue, TradeZella, TradesViz, and Edgewonk emphasize categorizing trades by setup, strategy, mistakes, instruments, sessions, and custom tags to find performance patterns.
- **Agent-only translation:** Use normalized machine-readable dimensions: `strategy_id`, setup/classification, tags, market regime/context tags, source-quality tags, and mistake/process tags. These should be filter keys for reports, recall, bootstrap context, replay case selection, and strategy lifecycle analysis.
- **Reject human-only parts:** Tag-cloud visuals, manual drag/drop categorization, community comparisons.
- **Relevant source IDs:** S1, S2, S3, S4.

### F3. Pre-trade plan plus post-trade review maps directly to agent decision and reflection lifecycle.

- **Claim type:** Recommendation.
- **Confidence:** Medium.
- **Human-journal pattern:** Trading journals commonly separate a trade plan/rationale from later post-trade notes and lessons.
- **Agent-only translation:** Model separate phases: planned decision, outcome/resolution, deterministic diagnostics, agent reflection, and possible quarantined policy/playbook proposal. This prevents post-hoc rationalization from overwriting the original basis.
- **Reject human-only parts:** Narrative screenshot walkthroughs unless converted into source/evidence links and structured fields.
- **Relevant source IDs:** S1, S3, S5, S6.

### F4. Skipped, missed, and avoided trades are learning objects, not noise.

- **Claim type:** Recommendation / inference.
- **Confidence:** Medium-low; needs re-fetch because product support varies.
- **Human-journal pattern:** Methodology sources and advanced journals encourage tracking missed trades, rule-following skips, and trades not taken to expose hesitation, over-filtering, and discipline effects.
- **Agent-only translation:** Treat `skip`, `watch`, `hold`, `invalidate_thesis`, and `no_action` as first-class decision lifecycle records. This directly supports the taxonomy’s “Decision and non-action lifecycle” and avoids losing why a stateless agent did nothing.
- **Reject human-only parts:** Emotion-only journaling of regret unless mapped to structured process tags or reflections.
- **Relevant source IDs:** S1, S3, S5, S6.

### F5. Mistake taxonomy and rule-adherence review are high-value if encoded as machine-checkable or explicitly self-reported fields.

- **Claim type:** Recommendation.
- **Confidence:** Medium.
- **Human-journal pattern:** Journals often track mistakes such as late entry, early exit, oversized position, ignored stop, poor setup quality, revenge trade, FOMO, or failure to follow plan.
- **Agent-only translation:** Maintain a controlled taxonomy of process deviations and separate deterministic rule violations from agent self-critique. Rule adherence should link to playbook version/rule IDs and classify evidence as machine-checkable, source-supported, or self-reported.
- **Reject human-only parts:** Psychology coaching dashboards unless the data becomes structured reflection evidence.
- **Relevant source IDs:** S1, S3, S4, S6.

### F6. Review cadence is a workflow primitive: daily/weekly/monthly review becomes due work and bootstrap context.

- **Claim type:** Recommendation.
- **Confidence:** Medium.
- **Human-journal pattern:** Journal methodology recommends recurring review to detect patterns, update rules, and measure discipline beyond single trades.
- **Agent-only translation:** Trade Trace should expose review obligations and stale items as machine-readable work queue entries: unresolved forecasts, due watch reviews, unreviewed outcomes, stale strategy summaries, missing sources, and playbook adherence checks.
- **Reject human-only parts:** Calendar UI, reminders, email notifications, or scheduler/daemon behavior.
- **Relevant source IDs:** S5, S6.

### F7. R-multiple and risk-normalized analytics transfer better than raw P&L.

- **Claim type:** Recommendation.
- **Confidence:** Medium.
- **Human-journal pattern:** Trading journals commonly report performance in risk units/R-multiple, expectancy, win rate, average winner/loser, and risk/reward to compare decisions across instruments and position sizes.
- **Agent-only translation:** Store/compute retrospective risk-normalized outcome fields where the agent supplies entry, stop/risk, target, and outcome. Reports should support strategy-scoped calibration without claiming profit generation.
- **Reject human-only parts:** Tax/accounting, broker-reconciled P&L dashboards, leaderboards.
- **Relevant source IDs:** S1, S2, S3, S4, S6.

### F8. MAE/MFE and opportunity metrics are useful as retrospective diagnostics, but require careful boundary control.

- **Claim type:** Recommendation / risk.
- **Confidence:** Medium-low; product support likely varies and needs re-fetch.
- **Human-journal pattern:** Advanced journals include maximum adverse excursion, maximum favorable excursion, missed opportunity, and exit efficiency metrics to analyze entry/exit quality.
- **Agent-only translation:** Trade Trace may record agent-supplied or externally supplied excursion/opportunity observations as diagnostic facts linked to a decision/outcome. It should not fetch market data or simulate fills.
- **Reject human-only parts:** Automatic chart replay, broker/market-data integrations, backtesting engines.
- **Relevant source IDs:** S1, S2, S4.

### F9. Screenshots and chart attachments translate to source/evidence provenance, not image-first UX.

- **Claim type:** Recommendation.
- **Confidence:** Medium.
- **Human-journal pattern:** Human journals encourage attaching chart screenshots, entry/exit snapshots, and notes to preserve what the trader saw.
- **Agent-only translation:** Preserve the analogue as structured source links, snapshot records, evidence hashes/URIs, extracted observations, and quality diagnostics. Images can be attachments, but the agent-facing contract should cite source IDs and machine-readable summaries.
- **Reject human-only parts:** Visual annotation tools, image galleries, chart drawing UX.
- **Relevant source IDs:** S2, S3, S4, S5.

### F10. Playbooks/rules are distinct from strategies and tags.

- **Claim type:** Recommendation.
- **Confidence:** Medium.
- **Human-journal pattern:** Some journal products separate playbooks/setups from journal entries and use them to compare actual trades against intended process.
- **Agent-only translation:** Preserve separation among strategy/edge thesis, setup label, ad hoc tags, and playbook/process rules. This supports strategy lifecycle diagnostics and reflection-to-policy quarantine without letting one bad reflection mutate durable policy.
- **Reject human-only parts:** Playbook page-builder UX and trader education templates.
- **Relevant source IDs:** S1, S3, S4.

## 3. Source Trail

| ID | URL / title | Publisher | Retrieval date | Trust tier | Notes |
|---|---|---:|---|---|---|
| S1 | https://edgewonk.com/features/ — Edgewonk features | Edgewonk | 2026-05-22 | Tier 2: vendor/product source | Intended evidence for strategy/setup classification, mistakes, review, R/risk analytics, MAE/MFE-like analytics, playbook/process focus. Extraction failed with HTTP 432. |
| S2 | https://tradervue.com/features/ — Tradervue features | Tradervue | 2026-05-22 | Tier 2: vendor/product source | Intended evidence for tags, notes, charts/screenshots, reports, R-based/statistical review. Extraction failed with HTTP 432. |
| S3 | https://www.tradezella.com/features — TradeZella features | TradeZella | 2026-05-22 | Tier 2: vendor/product source | Intended evidence for playbooks, mistakes, trade plans, journaling, analytics, missed trades. Extraction failed with HTTP 432. |
| S4 | https://www.tradesviz.com/features/ — TradesViz features | TradesViz | 2026-05-22 | Tier 2: vendor/product source | Intended evidence for tags, notes, screenshots/charts, advanced statistics, MAE/MFE/excursion-style analytics. Extraction failed with HTTP 432. |
| S5 | https://www.investopedia.com/articles/trading/11/keeping-a-trading-journal.asp — Keeping a trading journal | Investopedia | 2026-05-22 | Tier 3: methodology/education source | Intended evidence for journal discipline, pre/post trade notes, review cadence, screenshots/context. Extraction failed with HTTP 432. |
| S6 | Credible trading-journal methodology pattern, generic | Multiple common methodology sources | 2026-05-22 | Tier 4: uncited synthesis until re-fetched | Used only for broad methodology claims where vendor pages are insufficient; should be replaced by concrete fetched sources downstream. |

## 4. Contradictions, Weak Evidence, Missing Evidence, and Stale Risks

- **Extraction failure:** `web_search` and `web_extract` both failed with HTTP 432 during this task. This is the largest evidence weakness. The packet should be revalidated with direct page retrieval before final decisions.
- **Vendor bias:** Product pages are marketing material. They are useful evidence of common product patterns but weak evidence of causal trading improvement.
- **Feature ambiguity:** Vendors may use similar terms differently: “playbook,” “setup,” “mistake,” “tag,” and “review” are not standardized across products.
- **Automation boundary risk:** MAE/MFE, opportunity metrics, screenshots, and imports often depend on broker or market-data integrations in human products. For Trade Trace they must remain agent-supplied/recorded facts, not data fetching or execution.
- **Human psychology mismatch:** Emotion journaling and discipline coaching are common in human journals but translate only partially. For agent-only Trade Trace, use structured process deviations, reflection provenance, and policy quarantine instead of human mood UX.
- **Outcome overfitting risk:** Human journal analytics can encourage post-hoc optimization. Agentic Trade Trace should separate deterministic diagnostics from policy promotion and replay/regression evidence.
- **Not verified:** Exact current feature wording, current URLs, and whether specific products still expose named features on 2026-05-22 were not verified due retrieval failure.

## 5. Decision Hooks

- **For `trade-trace-zey2`:** Use these human-journal patterns as external support for prioritizing:
  - Decision and non-action lifecycle.
  - Strategy state/lifecycle and setup classification.
  - Machine-readable tags and mistake taxonomy.
  - Work queue / review cadence.
  - Forecast/outcome diagnostics with R/risk normalization and optional excursion/opportunity observations.
  - Source/evidence provenance as screenshot analogue.
  - Playbook adherence and reflection-to-policy quarantine.
- **For later cross-concept map:** Map human patterns to canonical agentic primitives as follows:
  - Pre-trade journal → decision-before-outcome record.
  - Post-trade notes → outcome + deterministic diagnostics + quarantined reflection.
  - Tags/setup → strategy/setup/tag dimensions for reports and recall.
  - Missed/skipped trades → non-action lifecycle records and due reviews.
  - Review cadence → work queue and bootstrap context items.
  - Mistakes/rules → process taxonomy + playbook adherence evidence.
  - R/MAE/MFE → retrospective diagnostics from supplied facts only.
  - Screenshots → source/snapshot/evidence links and quality diagnostics.

## 6. Controller Verification Addendum

After the delegated packet was written, the controller performed direct source fetches with Python `urllib` because the Tavily-backed `web_search`/`web_extract` path returned HTTP 432.

Verified on 2026-05-22:

- `https://edgewonk.com/features/` loaded successfully. Extracted page text supported the existence of trading-journal patterns including custom comments/tags, strategy/setup tracking, mistake analysis, discipline/rule adherence tracking, checklists by setup, diary/reflection notes, and screenshot attachments. This directly strengthens F2, F3, F5, F9, and F10.
- `https://www.tradezella.com/features` loaded successfully. Extracted page text supported patterns including analytics dashboards, advanced filtering, calendar view, notes/comments, risk-management metrics, R-multiple, entries/exits, setups/mistakes, reports for best/worst trading days, trade replay, journaling to learn from mistakes, and an explicit statement that TradeZella is not a brokerage. This strengthens F2, F5, F6, F7, and the boundary warning around not copying broker/execution surfaces.

Still not verified in the controller session:

- Tradervue feature page URL used by the subagent returned 404.
- TradesViz feature page URL used by the subagent returned 404.
- Investopedia article fetch returned 403.

Decision impact: the core human-journal translation remains usable for synthesis, but source confidence should be upgraded only for the Edgewonk and TradeZella-supported findings. Product/vendor marketing remains weaker than independent evidence and should not be used as proof that these practices improve trading outcomes.

## 7. Side Effects

Files written:

- `docs/research/agentic-trade-trace/external/human-trading-journal-patterns.md`

Memory retained: none.  
External side effects: attempted web searches/extractions only; no accounts, APIs beyond retrieval tools, or repository services were mutated.  
Implementation changes: none; no code, schemas, tests, README/PRD/VISION, Beads, config, or implementation-bearing files were edited.
