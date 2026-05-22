# Concept Dossier: Replay and Regression Evaluation Substrate

## 1. Question

Should Trade Trace adopt a replay/regression evaluation substrate that lets agents re-run old recorded decision cases against newer prompts, models, playbooks, and recall policies while preserving the original `as_of` context boundary, avoiding market simulation, avoiding data fetching, and preventing hindsight leakage?

## 2. Bottom Line

- Recommendation: **adopt core**.
- Confidence: **medium-high**.
- Why: Replay/regression is downstream of the core agentic loop. Current Trade Trace already records most source material needed for historical cases: decisions/non-actions, theses, forecasts, snapshots, outcomes/scores, sources, strategies, playbooks, memory nodes, recall events, segmentation fields, and report outputs. The missing concept is not a backtester; it is a bounded, point-in-time case-bundle and evaluator that can ask: “Given only what was recorded and knowable then, would the new model/prompt/playbook/recall recipe produce a better process output?” This is core for agentic self-improvement because agents and prompts change over time, but it must be tightly scoped to recorded artifacts and retrospective process diagnostics.

## 3. Agent-Specific Problem

Fresh-session LLM trading agents change in ways human traders usually do not: model versions move, prompts are rewritten, tool-use policies change, recall ranking changes, and playbook rules are promoted or superseded. Without replay/regression, Trade Trace can score historical forecasts but cannot evaluate whether a new agent configuration would have:

- recalled relevant prior memories that the original run missed;
- avoided a known repeated process error;
- followed a newer playbook rule on a past case where required fields were available;
- resisted a poisoned or stale reflection;
- preserved valid skips/watches instead of overtrading in hindsight;
- complied with the no-fetch/no-execution/no-advice boundary during evaluation.

This matters specifically for LLM agents because future behavior is often prompt/model dependent. A regression substrate gives the system a way to test changes against frozen historical cases before those changes shape future live decision records. The target is **process regression**, not simulated profitability.

## 4. Current Baseline

### Implemented / observed substrate from existing research artifacts and product docs

- Trade Trace’s product boundary is local-first, agent-only, JSON/MCP/CLI oriented, with no trade execution, no broker credentials, no market-data fetching, and caller-supplied snapshots/outcomes only (`docs/PRD.md:7`, `49-67`; research contract §2).
- The current baseline reports implemented ledger/source primitives for venues, instruments, snapshots, theses, forecasts, decisions, outcomes, source attachments, append-only events, idempotency, binary Brier scoring, reports, memory graph, recall telemetry, strategies, playbooks, and segmentation metadata (`01-current-system-baseline.md:21-39`, `51-67`).
- The taxonomy classifies replay/regression as a core evaluation concept but warns that it must remain replay of recorded artifacts, not backtesting or market simulation (`02-concept-taxonomy.md:48`, `138`, `145`).
- Foundational continuity synthesis says replay depends on lifecycle state and recall receipts, and asks whether row-level metadata is enough or replay needs first-class AgentRun/session boundaries (`synthesis/foundational-continuity.md:91`, `210-213`).
- Decision-control synthesis frames replay as a downstream consumer of lifecycle, work queue, playbook predicates, reflection quarantine, outcomes, and policy versions, and explicitly forbids backtest claims, simulated fills, and rewritten history (`synthesis/agent-decision-control-surface.md:93-105`, `137-147`).
- Agent/run identity dossier finds broad row-level metadata (`actor_id`, `agent_id`, `model_id`, `environment`, `run_id`) but no first-class run/session object; it identifies replay/regression as a possible falsifier for keeping only metadata (`concepts/agent-run-session-identity.md:52-62`, `153-172`).
- Recall receipts dossier distinguishes raw recall events from product-level evidence of memory consumption and names replay/regression as a consumer that needs original `as_of`, returned nodes, and later outcome labels (`concepts/recall-receipts.md:93-103`, `134-144`).
- Fresh-session bootstrap context pack dossier defines a bounded startup context contract with `as_of`, section budgets, active strategies, unresolved forecasts, watchlist, exposure, memory recall trace, caveats, and next process actions; replay cases should reuse the same bounded/context-caveated discipline (`concepts/fresh-session-bootstrap-context-pack.md:45-82`, `104-120`).
- Machine-checkable playbook predicates dossier states replay should use historical rule version and fields available at decision time, not current rule text or post-outcome data (`concepts/machine-checkable-playbook-predicates.md:138-150`).
- Reflection-to-policy quarantine dossier names replay/regression as a verifier for whether proposed rules would have changed recorded cases without rewriting history (`concepts/reflection-to-policy-quarantine.md:107-118`, `155-167`).
- Forecasting/calibration evidence supports proper scoring, calibration/reliability, low-N warnings, resolution criteria, and explicit source provenance; these are evaluation inputs, but not profitability proof (`external/forecasting-calibration-references.md:8-18`, `84-90`, `121-143`).

### Baseline gap

The existing system can record and score historical decisions, but the inspected research/docs do not define a canonical **replay case bundle**, **point-in-time context boundary**, **expected-output contract**, or **regression comparison method** for evaluating a changed model/prompt/playbook over old recorded cases. Existing reports answer “what happened?”; replay/regression should answer “would the changed agent process behave acceptably on the same recorded case without using future information?”

## 5. Candidate Product Shape

The candidate product is a **recorded-case replay and regression substrate**. It packages historical cases and evaluates process outputs under controlled conditions. It should not fetch data, simulate market paths, synthesize missing snapshots, route orders, or claim realized alpha.

### 5.1 Replay case types

1. **Decision replay case**
   - Original decision or non-action: `watch`, `skip`, `hold`, `paper_enter`, `paper_exit`, `actual_*` record-only entries, thesis updates, invalidations, reviews.
   - Goal: test whether a candidate agent configuration would produce an acceptable process output from the same pre-decision context.

2. **Forecast replay case**
   - Original forecast with probability, resolution rule, timestamp, linked thesis/snapshot/sources, and later outcome hidden from the replay agent but used by evaluator.
   - Goal: compare forecast probability, resolution discipline, and calibration outcomes.

3. **Recall replay case**
   - Original recall query/context/strategy/`as_of`, returned nodes, and later use evidence.
   - Goal: test whether new prompts or recall policies retrieve/cite/use better memory without exposing post-decision memories.

4. **Playbook/predicate replay case**
   - Historical decision with playbook version/rules as of the decision time and recorded fields.
   - Goal: check adherence/predicate behavior using historical policy state, plus evaluate candidate new rules in “shadow mode” as a separate what-if diagnostic.

5. **Policy-candidate replay case**
   - A quarantined reflection or proposed rule evaluated against prior cases to see whether it would have flagged relevant patterns, overfit a narrow sample, or contradicted good historical decisions.

### 5.2 Case bundle lifecycle

1. **Select historical cases.** Use filters over strategy, instrument, decision type, playbook version, forecast status, outcome status, agent/model/environment/run, date range, and source/adherence caveats.
2. **Freeze `as_of`.** The case has an evaluation timestamp: normally just before the original decision/forecast/review. All context sections must be derived as if queried at that time.
3. **Assemble context bundle.** Include only recorded artifacts that existed and were valid as of the boundary: snapshots, thesis versions, forecasts created so far, sources attached so far, strategy state then-known, playbook version then-active, memory nodes valid then, recall events/receipts up to then, and relevant prior outcomes/scores already known then.
4. **Hide future labels.** Outcomes, forecast scores, later reflections, later source updates, later playbook rules, and post-decision market facts are withheld from the candidate agent unless explicitly evaluating a post-outcome review task.
5. **Run candidate agent externally.** Trade Trace should provide the bundle and accept the candidate output; it should not host arbitrary model execution or become an agent runtime.
6. **Normalize expected output.** Candidate outputs are evaluated against a task-specific schema: forecast probability, decision/non-action type, required reasoning fields, cited memories/sources, playbook adherence status, predicate statuses, caveats, and process next steps.
7. **Compare to original and outcomes.** Evaluation reports compare candidate vs original on process criteria and, where legitimate, later labels such as Brier score, outcome status, and post-hoc rule/adherence diagnostics.
8. **Emit regression diagnostics.** Results are scoped, low-N caveated, and tied to model/prompt/playbook/recall-policy identifiers.

### 5.3 What replay is not

- Not market simulation or backtesting.
- Not synthetic fills, slippage, or order execution.
- Not automatic data/outcome fetching.
- Not a claim that a candidate decision would have been executable or profitable.
- Not rewriting original decisions, forecasts, memories, outcomes, or scores.
- Not a generic LLM benchmark detached from trading-shaped Trade Trace artifacts.

## 6. Required Data / State

A replay/regression substrate needs a case bundle that is richer than a single decision row. Required state includes:

### 6.1 Point-in-time boundary

- `case_id` or deterministic case key.
- `as_of` timestamp used for context inclusion.
- Original artifact identity: decision, forecast, thesis, review, strategy, reflection, playbook version, or recall event.
- Original created timestamps and validity windows (`valid_from`, `valid_to`, invalidation/supersession where available).
- Timezone/UTC discipline and ordering caveats.

### 6.2 Original recorded context

- Instrument and venue metadata as recorded then.
- Snapshot(s) captured at or before `as_of`, including price/bid/ask/mid/spread/liquidity fields if caller supplied them.
- Thesis version and falsification/exit/risk notes valid then.
- Forecast probability, outcome labels, resolution rule text, resolution horizon, and scoring state as of the boundary.
- Decision or non-action reason, type, side, quantity/price if recorded, tags, review deadline, strategy/playbook references.
- Source snapshot: source IDs, attachments, stance, freshness/redaction/caveats recorded by then. Source content should be by ID/summary unless explicitly allowed; no URL fetching.
- Strategy state/hypothesis/status as known then. If mutable strategy rows are reconstructed from events rather than versions, the bundle should caveat reconstruction quality.
- Playbook version/rule nodes active then and any adherence rows already recorded before `as_of`.
- Memory nodes valid then, with confidence/importance/decay, source refs, supersession status as of then.
- Recall events/receipts before the decision, including returned node IDs, query, context, strategies, `as_of`, budgets, and cited/used nodes where available.
- Bootstrap/work-queue context if the replay task is “start of run” rather than “single decision.”

### 6.3 Hidden evaluation labels

These are withheld from the candidate agent during replay but available to evaluator/reporting:

- Later outcomes and outcome status (`resolved_final`, provisional/disputed/ambiguous where applicable).
- Forecast scores and calibration bins.
- Later reflections/reviews and policy-candidate evidence.
- Later source updates or contradictory evidence.
- Later playbook versions/rules unless the replay task explicitly tests a new rule in shadow mode.
- Original final decision if evaluating blind generation; or original decision visible if evaluating review/critique behavior.

### 6.4 Candidate configuration metadata

- Candidate `agent_id`, `model_id`, prompt identifier/hash or label, playbook version/rule-set identifier, recall policy/ranking label, environment, and `run_id` if used.
- Whether candidate had access to original recall receipts or had to call a recall-like retrieval over the frozen memory set.
- Task mode: blind decision, forecast-only, review original, policy shadow-check, bootstrap replay, or recall regression.
- Output schema/version and evaluation rubric version.

### 6.5 Expected outputs

Expected outputs should be machine-readable and task-specific. Examples:

- Forecast probability and resolution rule restatement.
- Decision/non-action classification from allowed decision types.
- Required citations to source IDs and memory node IDs.
- Recall-use declaration: returned/cited/ignored memory nodes.
- Playbook adherence self-report and predicate audit state.
- Process next actions: due outcome entry, reflection needed, source gap, review needed — not trade advice.
- Caveats and “insufficient context” declaration.

## 7. Machine Interface Implications

Replay/regression should be exposed as JSON-first machine surfaces if adopted later, but this dossier does not authorize implementation. The conceptual interface implications are:

- **Case discovery:** list eligible historical cases with filters and caveats: resolved/unresolved, has snapshot, has forecast, has recall receipt, has source attachments, has playbook version, has outcome, has low-N warning.
- **Case bundle export:** return a frozen, bounded bundle with `as_of`, included sections, excluded/future sections, truncation metadata, source IDs, memory IDs, recall IDs, and no-fetch/no-simulation caveats.
- **Redaction and budget controls:** let agents request IDs-only, summaries, or limited bodies; never require full transcripts.
- **Candidate output ingestion:** accept structured outputs from external model/prompt runs for comparison. Trade Trace should not need to execute the model.
- **Regression report:** compare original vs candidate by task schema: calibration/Brier where legitimate, source/recall citation quality, predicate adherence, missing-field rate, hindsight-leakage violations, output validity, and process-obligation correctness.
- **Run identity relationship:** candidate runs should carry `agent_id`, `model_id`, `environment`, `run_id`, prompt/playbook/recall-policy labels, and possibly a first-class run/session ID if row-level metadata proves insufficient.
- **Determinism:** bundle generation should be deterministic for the same DB state, filters, `as_of`, and budget. If recall ranking is re-run under a new policy, the report should distinguish “original recalled context” from “candidate recall result.”

Evaluation outputs should use IDs, counts, statuses, and caveats. Free-form model reasoning may be stored or attached only as bounded evidence if needed; it should not become the replay source of truth.

## 8. Evidence

- Repo evidence:
  - `docs/research/agentic-trade-trace/00-research-contract.md`: in scope includes agentic continuity, forecasts, decisions, playbooks, recall behavior, and research-only artifacts; out of scope includes execution, market-data fetching, implementation, and generic memory.
  - `docs/research/agentic-trade-trace/01-current-system-baseline.md`: current baseline confirms ledger, scoring, reports, memory graph, recall telemetry, strategies, playbooks, sources, and metadata fields, while flagging drift around snapshot segmentation and report completeness.
  - `docs/research/agentic-trade-trace/02-concept-taxonomy.md`: replay/regression is core but must remain replay of recorded artifacts, not synthetic backtesting or market simulation.
  - `docs/research/agentic-trade-trace/synthesis/foundational-continuity.md`: replay depends on lifecycle and recall receipts and may test whether first-class AgentRun boundaries are needed.
  - `docs/research/agentic-trade-trace/synthesis/agent-decision-control-surface.md`: replay consumes lifecycle, work queue, predicates, outcomes, receipts, and policy versions; forbidden outputs include backtest claims and simulated fills.
  - `docs/research/agentic-trade-trace/concepts/agent-run-session-identity.md`: current metadata is useful but may be insufficient for run-scoped replay intent/scope/status.
  - `docs/research/agentic-trade-trace/concepts/recall-receipts.md`: replay should use original `as_of`, returned nodes, and later outcome labels to test memory use.
  - `docs/research/agentic-trade-trace/concepts/fresh-session-bootstrap-context-pack.md`: bounded, cited, caveated packs provide a model for replay context bundles.
  - `docs/research/agentic-trade-trace/concepts/machine-checkable-playbook-predicates.md`: replay should use historical rule versions and fields available at decision time.
  - `docs/research/agentic-trade-trace/concepts/reflection-to-policy-quarantine.md`: replay can verify proposed rules against recorded cases without rewriting history.
  - `docs/PRD.md`: product records manual snapshots/outcomes, binary forecasts, decisions, sources, memory recall events, strategies, playbooks, reports, and segmentation fields, and explicitly excludes trading-data fetching/execution.
- External evidence:
  - `docs/research/agentic-trade-trace/external/forecasting-calibration-references.md`: proper scoring, calibration/reliability, base-rate/reference-class comparisons, explicit resolution criteria, and low-N caveats support retrospective evaluation, not profitability claims.
- User-stated intent:
  - The delegated task asks for replay old recorded cases against new prompts/models/playbooks without fetching data or simulating markets; it explicitly names context bundle, `as_of` boundaries, recall receipts, source snapshots, predictions, outcomes, expected outputs, regression metrics, hindsight leakage prevention, and relation to agent run identity.
- Inferences:
  - Replay/regression is only decision-safe if the bundle records both included context and withheld future labels.
  - Current row-level metadata may support simple replay, but robust regression across candidate model/prompt/playbook runs may require stronger run/session boundaries or at least disciplined candidate configuration metadata.
  - Replay should evaluate process validity and calibration improvements, not assert counterfactual P&L.

## 9. Risks/Failure Modes

- **Hindsight leakage:** Later outcomes, scores, reflections, source updates, strategy edits, or playbook rules accidentally enter the candidate context.
- **Backtesting creep:** Replay starts producing simulated P&L, fills, missed profits, or “would have bought/sold” claims beyond recorded facts.
- **Market-data fetch creep:** Case bundles try to fill gaps by querying historical prices, source URLs, broker records, or outcome services.
- **False counterfactuals:** A candidate output is treated as proof that the agent would have acted profitably, even though execution, liquidity, costs, and market reaction are not modeled.
- **Mutable-state reconstruction error:** Strategies or playbook state reconstructed from mutable rows/events may not reflect exactly what the original agent saw.
- **Run identity ambiguity:** Optional `run_id` strings may not prove which records were generated/consumed together in the original session.
- **Receipt ambiguity:** Multiple recalls before a decision can make it unclear which memory context the original decision used.
- **Overfitting prompts/playbooks:** Candidate prompts are tuned to historical cases and appear better in replay while degrading future behavior.
- **Metric theater:** Single aggregate win/loss or Brier deltas over sparse cases hide low sample size, outcome ambiguity, or reference-class selection.
- **Regression target drift:** Expected outputs change over time, making comparisons between old and new prompt/model runs invalid unless schema/rubric versions are pinned.
- **Context bloat:** Replay bundles become large transcripts rather than bounded ID-rich case packs.
- **Advice phrasing:** Regression reports could imply recommended future trades unless framed as process diagnostics.

## 10. Dependencies/Conflicts

### Dependencies

- **Decision and non-action lifecycle:** supplies cases and original intent.
- **Agent/run attribution and continuity keys:** scopes original and candidate runs; may need first-class run/session boundaries if row metadata is insufficient.
- **Recall receipts:** prove original/candidate memory exposure and use.
- **Fresh-session bootstrap context pack:** provides section/budget/caveat pattern for bundle construction.
- **Work queue / next actions:** replay can test whether old cases would have generated correct process obligations.
- **Machine-checkable playbook predicates:** provide deterministic process checks over recorded fields.
- **Reflection-to-policy quarantine:** supplies policy candidates to test in shadow over historical cases.
- **Forecast diagnostics/calibration:** provides scoring, reliability, sample-size, and resolution discipline.
- **Strategy lifecycle:** scopes cases by edge thesis and prevents cross-strategy leakage.
- **Source/evidence provenance:** determines what evidence was available then and prevents fabricated context.

### Conflicts / boundaries

- Replay conflicts with Trade Trace’s product boundary if it requires market-data fetching, broker state, order simulation, price-path reconstruction, or profitability claims.
- Replay conflicts with append-only/audit principles if it rewrites original records rather than producing separate candidate/evaluation artifacts.
- Replay can conflict with local-first/token-budget discipline if it stores full prompts/transcripts or unbounded source/memory bodies.
- Replay can conflict with agent-only product direction if it becomes a human benchmark dashboard instead of machine-readable evaluation substrate.

## 11. Open Questions/Falsifiers

- Is a replay substrate necessary, or can agents compare prompts/models using existing reports, exports, and ad hoc scripts? Falsifier: dogfood agents perform reliable prompt/playbook regression with existing exports and no repeated leakage or case-selection errors.
- Is row-level `run_id` enough, or does replay need first-class AgentRun/session records with start/end/status/scope/consumed-context summaries?
- What is the minimum case bundle: decision + snapshot + thesis + forecast + sources + memories, or full bootstrap-style pack?
- Should original decision be hidden in blind replay, visible in critique replay, or selectable by task mode?
- How should strategy state be reconstructed at `as_of` if strategies are mutable and separate strategy versions are deferred?
- Do replay bundles need materialized snapshots for determinism, or can they be generated from append-only events and reports on demand?
- What metrics are legitimate for non-actions like `skip` and `watch`, where good behavior may be “did not enter” or “requested more evidence” rather than forecast score?
- How can expected outputs be normalized without forcing all agents into one decision schema too early?
- How should candidate prompt/model identifiers be captured without storing proprietary prompts or excessive transcripts?
- What threshold distinguishes useful regression from overfitting to a small historical suite?
- Falsifier for “adopt core”: if replay requires external market data, simulated fills, broker truth, or strong counterfactual profitability assumptions, it should be narrowed to export-only evidence bundles or deferred.

## 12. Decision Hook

This dossier should feed `trade-trace-34c2` and downstream evaluation/calibration synthesis. Recommended decision framing: adopt replay/regression as a **core future product primitive** only as a recorded-artifact, point-in-time, no-fetch/no-simulation evaluation substrate. It should initially be conceptualized as case-bundle generation plus regression diagnostics over external candidate outputs, not as a model runner, backtester, scheduler, or trading advisor.

## 13. Side Effects

Files written:

- `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/concepts/replay-regression-evaluation-substrate.md`

Files modified besides this artifact: none.

Memory retained: none.

External/network side effects: none; no network fetches were run.

Implementation changes: none; no code, schemas, tests, README, PRD, VISION, Beads, config, memory, or implementation-bearing files were edited.
