# Synthesis: Evaluation and Learning Architecture

**Date:** 2026-05-22  
**Synthesis bead:** `trade-trace-0j1b`  
**Inputs:** `trade-trace-nm7a`, `trade-trace-4d5e`, `trade-trace-34c2`, `trade-trace-d8kr`  
**Status:** Research synthesis only — no implementation approval

## 1. Bottom Line

Trade Trace’s evaluation/learning architecture should be a **closed learning loop over recorded artifacts**, not a trading-performance engine.

The coherent model is:

```text
Strategy scopes the edge thesis
  → forecasts/decisions/non-actions produce probability and process evidence
  → outcomes/scores/calibration diagnose quality and caveats
  → replay/regression evaluates prompt/model/playbook/recall changes against frozen cases
  → reflection/policy quarantine and bootstrap/work queue consume lessons safely
  → multi-agent handoff remains a packet over these surfaces, not a coordination service
```

Ranked product direction:

| Rank | Concept | Classification | Confidence | Why |
|---:|---|---|---:|---|
| 1 | Strategy state and lifecycle | Foundational/core | High for scoping; medium for richer statuses | Strategies are the edge-thesis boundary for memory, diagnostics, reviews, policy scope, and bootstrap. |
| 2 | Forecast-vs-market edge diagnostics | Foundational/core | High for retrospective diagnostics; medium for market-reference details | Forecast/calibration evidence is the clearest objective process signal, especially when caveated by base rates, sample size, source quality, and supplied market context. |
| 3 | Replay/regression substrate | Core, but later-stage than strategy/diagnostics | Medium-high | Essential for evaluating model/prompt/playbook/recall changes without live trading, but depends on stable context bundles and point-in-time boundaries. |
| 4 | Multi-agent handoff protocol | Deferred/supporting | Medium-high defer | Useful only as a handoff packet once bootstrap/work queue/receipts/strategy/replay are stable; standalone coordination is out of scope. |

Minimum conclusion: **make strategy-scoped retrospective diagnostics and frozen-case replay the learning backbone; keep multi-agent handoff downstream and packet-shaped.**

## 2. Inputs Consumed

- `docs/research/agentic-trade-trace/concepts/strategy-state-lifecycle.md`
- `docs/research/agentic-trade-trace/concepts/forecast-vs-market-edge-diagnostics.md`
- `docs/research/agentic-trade-trace/concepts/replay-regression-evaluation-substrate.md`
- `docs/research/agentic-trade-trace/concepts/multi-agent-handoff-protocol.md`
- Supporting synthesis: `docs/research/agentic-trade-trace/synthesis/foundational-continuity.md`
- Supporting synthesis: `docs/research/agentic-trade-trace/synthesis/agent-decision-control-surface.md`
- Supporting synthesis: `docs/research/agentic-trade-trace/synthesis/external-evidence.md`

## 3. Evaluation Architecture

### 3.1 Evaluation target

Trade Trace should evaluate **agent process quality**:

- probability calibration;
- resolution discipline;
- source and evidence hygiene;
- strategy-scoped performance/process patterns;
- recall use and memory usefulness;
- playbook adherence/override outcomes;
- non-action learning cases;
- prompt/model/playbook regression behavior on historical cases.

It should not claim:

- alpha generation;
- profitability;
- trade recommendations;
- broker truth;
- market simulation;
- automatic strategy ranking for live allocation.

### 3.2 Learning loop

```text
1. Record
   thesis, forecast, snapshot, source, decision/non-action, strategy, playbook adherence, recall event.

2. Resolve
   caller-supplied outcome and scoring; unresolved items surface via work queue.

3. Diagnose
   calibration, reference-class/base-rate comparison, market-implied gap if supplied, source quality, adherence, strategy health.

4. Reflect
   agent writes scoped reflection; reflection enters quarantine rather than policy.

5. Replay
   candidate prompt/model/playbook/recall policy is evaluated on frozen historical cases with future labels hidden.

6. Promote / adjust cautiously
   policy or strategy changes require evidence bundles, caveats, and reversibility.

7. Bootstrap next session
   fresh agents receive bounded strategy/diagnostic/queue/receipt context.
```

## 4. Dependency Map

| Layer | Depends on | Produces | Why it matters |
|---|---|---|---|
| Strategy lifecycle | strategy rows, decisions/theses/forecasts/reviews with `strategy_id`, memory edges, reports | scoped strategy state, health, due reviews, low-N caveats | Prevents smearing lessons across unrelated edge theses. |
| Forecast-vs-market diagnostics | forecasts, outcomes, scores, snapshots, sources, strategies, decision types | calibration/reference/market-gap reports with caveats | Gives objective-ish probabilistic feedback without advice. |
| Replay/regression | point-in-time records, strategy state, recall receipts, sources, playbooks, outcomes hidden from candidate | regression diagnostics for prompt/model/playbook/recall changes | Lets agents improve process before live future writes. |
| Multi-agent handoff | bootstrap, work queue, receipts, attribution, strategy state, caveats | handoff packet if needed | Transfers continuity without building coordinator/runtime. |
| Reflection quarantine | outcomes, diagnostics, replay, strategy scope, recall/source evidence | policy candidates/promotions/rejections | Prevents overfit lessons from poisoning future context. |

## 5. Foundational vs Later-Stage Concepts

### Foundational now

1. **Strategy scoping**
   - Every evaluation needs a strategy/null-strategy boundary where possible.
   - Strategies are not tags and not playbooks.
   - Current active/archived state may be enough initially, but dormant/superseded/proposed semantics should remain live research candidates.

2. **Forecast/calibration diagnostics**
   - Brier/log score, reliability bins, ECE-like summaries, sharpness, base-rate baselines, scored/unscored counts, low-N warnings, late-recorded exclusions, and source/outcome caveats form the quantitative spine.
   - Market-implied comparisons are allowed only when caller-supplied and caveated.

3. **Process/evidence caveats**
   - Evaluation output must surface missing sources, stale/contradictory evidence, missing resolution provenance, unsupported scoring, ambiguous outcomes, missing reflections/adherence, and sample-size limitations.

### Core but later-stage

4. **Replay/regression**
   - It depends on point-in-time context assembly, recall receipts, stable strategy/playbook history, and expected-output schemas.
   - It is essential for safe agent self-improvement, but should follow foundation/decision-control clarity.

### Deferred/supporting

5. **Multi-agent handoff**
   - Treat as scoped bootstrap/work-queue/receipt packet for another agent, not coordination infrastructure.
   - Do not build locks, leases, assignment tables, scheduling, or live collaboration unless dogfood falsifies derived packets plus idempotency.

## 6. Boundary Analysis

| Risky direction | Why to reject/narrow it | Safe version |
|---|---|---|
| Strategy ranking by expected profit | Looks like live allocation advice. | Strategy health/review diagnostics with low-N/sample/source caveats. |
| Forecast-vs-market “edge” as signal | Market gaps can be spread/liquidity/reference-class artifacts. | Retrospective recorded-reference comparison, never trade recommendation. |
| Replay as backtest | Would require simulated fills/data paths and profitability claims. | Frozen recorded-case process replay with hidden labels and no market simulation. |
| Handoff as coordination service | Becomes runtime/scheduler/task manager. | Handoff packet generated from existing continuity surfaces. |
| Reflection as automatic learning | Overfits and poisons context. | Quarantined policy candidates with evidence bundles and replay support. |
| Multi-model comparison as leaderboard | Encourages optimizing scores without process caveats. | Compare calibration/process diagnostics with sample-size and scope warnings. |

## 7. Ranked Recommendations

### R1. Make strategy scope mandatory in evaluation thinking.

Confidence: high.  
If records lack `strategy_id`, reports should treat that as a caveated null-strategy population, not silently blend it with active strategies.

### R2. Treat forecast/calibration diagnostics as the main objective learning signal.

Confidence: high.  
This is the most evidence-backed evaluation surface. Keep it retrospective and caveated.

### R3. Use source/outcome/integrity caveats as first-class parts of scores.

Confidence: high.  
A calibrated-looking score with late-recorded forecasts, ambiguous outcomes, stale sources, or tiny samples is not reliable learning evidence.

### R4. Adopt replay/regression as a core future capability, but only after context-pack/receipt/boundary contracts are stable.

Confidence: medium-high.  
Replay is how prompts/models/playbooks learn safely, but it needs stable point-in-time bundles and expected outputs.

### R5. Keep multi-agent handoff deferred and packet-shaped.

Confidence: high.  
It should not lead the product roadmap. It is a downstream consumer of bootstrap/work queue/receipt/strategy/replay surfaces.

### R6. Track doc/source drift found during research as future cleanup, not as this program’s implementation work.

Confidence: high.  
Examples: strategy list `both` vs PRD `all`, strategy.show row-only vs planned counts, and scoring docs/source broader than some PRD binary-only text. These are useful future review items but not blockers for research synthesis.

## 8. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Small samples | False confidence in strategy/model edge. | Low-N warnings, bins with counts, avoid rankings. |
| Hindsight leakage | Replay/policy appears better than it would have been. | Strict `as_of`, hidden labels, validity windows, late-recording flags. |
| Strategy drift | Mutable hypotheses make past evaluations ambiguous. | Audit events; consider point-in-time strategy versions only if needed. |
| Market-reference overclaim | Supplied implied probability treated as truth. | Label as caller-supplied reference with spread/liquidity/source caveats. |
| Context poisoning | Bad reflections/rules influence future sessions. | Quarantine, replay, supersession, recall receipts. |
| Coordinator creep | Handoff becomes scheduler/lock service. | Packet-only unless dogfood proves otherwise. |
| Profitability claims | Misrepresents calibration as tradable edge. | Always phrase as process/evaluation diagnostics. |

## 9. Non-Goals and Redesign Triggers

This architecture does **not** decide or automate:

- live strategy selection or capital allocation;
- buy/sell/enter/exit/hold recommendations;
- broker/execution integration;
- live or historical market-data fetching;
- simulated fills, slippage, or backtesting;
- automatic playbook/policy mutation;
- generic multi-agent scheduling/locking/assignment;
- public profitability or alpha claims.

Redesign would be required if future dogfood shows any of these assumptions are false:

- row-level attribution is insufficient to reconstruct model/prompt/run differences;
- strategy update events cannot reconstruct point-in-time hypotheses for replay;
- derived handoff/work-queue packets cannot prevent duplicate/conflicting agent writes;
- forecast diagnostics are too sparse without stronger reference-class modeling;
- agents optimize calibration metrics in ways that degrade source quality, non-action discipline, or policy safety;
- replay bundles cannot be made token-bounded without hiding decisive context.

## 10. Open Questions / Falsifiers

- Are active/archived strategy states enough, or do dormant/proposed/superseded states become necessary for bootstrap/replay/review?
- Does strategy hypothesis mutation require point-in-time versioning, or are update events sufficient?
- What reference-class baselines are honest enough for forecast diagnostics without overfitting?
- What is the minimum viable replay case schema that prevents hindsight leakage while staying token-bounded?
- Can derived handoff packets plus idempotency prevent conflicting writes, or does dogfood require durable acknowledgement/ownership state?
- Does multi-model replay improve actual future process behavior, or does it create metric gaming?
- Falsifier: if agents can self-improve with existing reports and manual reflections without replay, replay may be later-stage rather than core.
- Falsifier: if strategy scope is rarely used or mostly noisy, strategy lifecycle should remain simple active/archived rather than expanded.

## 11. Downstream Hook

This synthesis should feed `trade-trace-9lgd` cross-concept dependency/conflict mapping. Suggested classification there:

- **Foundational cluster:** bootstrap, decision/non-action lifecycle, recall receipts, strategy scope, forecast/calibration diagnostics.
- **Decision-control cluster:** work queue, non-action materiality, playbook predicates, reflection quarantine.
- **Evaluation cluster:** replay/regression, strategy diagnostics, forecast-vs-market diagnostics.
- **Deferred packet cluster:** multi-agent handoff.

## 12. Side Effects

Files written:

- `docs/research/agentic-trade-trace/synthesis/evaluation-learning-architecture.md`

Memory retained: none.  
External side effects: none.  
Implementation changes: none; no code, schema, tests, README/PRD/VISION, config, or runtime files were edited.
