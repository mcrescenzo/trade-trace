What I did:
Inspected the reports/memory/strategy/playbook lane read-only under /home/hermes/code/trade-trace. I focused on:
- src/trade_trace/reports/**
- src/trade_trace/contracts/report_filter.py
- src/trade_trace/models/memory.py
- src/trade_trace/tools/memory.py
- src/trade_trace/tools/reflection.py
- src/trade_trace/tools/strategy.py
- relevant docs/tests for reports, memory, strategy, playbook behavior

Files created or modified:
None. Read-only review only.

Issues encountered:
No tooling or repo access issues. I did not run write commands, package managers, destructive commands, or Beads mutations.

Candidate records:

1. id: reports-memory-strategy-playbook-001
title: reflection.prompt_for_outcome can attach the wrong forecast/thesis when multiple forecasts exist on the same instrument
severity: P2
confidence: high
domain: reports-memory-strategy-playbook
bug_class: deterministic packet/report correctness
evidence_type: code/docs mismatch

evidence:
- docs/architecture/memory-layer.md:287-291 defines reflection.prompt_for_outcome as returning “the resolved outcome, the original thesis and forecast it resolved”.
- src/trade_trace/tools/reflection.py:42-53 loads the requested outcome and extracts outcome.instrument_id.
- src/trade_trace/tools/reflection.py:60-74 then selects:
  SELECT f.id, f.thesis_id, ...
  FROM forecasts f
  JOIN theses t ON t.id = f.thesis_id
  WHERE t.instrument_id = ?
  ORDER BY f.created_at, f.id
  LIMIT 1
  This picks the earliest forecast on the same instrument, not the forecast that was actually scored/resolved by the requested outcome.
- src/trade_trace/tools/reflection.py:97-108 similarly selects the earliest thesis for the instrument:
  SELECT t.id, ...
  FROM theses t
  WHERE t.instrument_id = ?
  ORDER BY t.created_at, t.id
  LIMIT 1
  It does not tie the thesis to the selected/resolved forecast either.
- src/trade_trace/tools/reflection.py:86-95 computes calibration_delta from the selected forecast’s outcome labels, so the delta can also be for the wrong forecast.

failure mode:
If an instrument has multiple forecasts/theses and an outcome resolves a later forecast, reflection.prompt_for_outcome(outcome_id=that_outcome) can return the earliest forecast/thesis on the instrument rather than the forecast_scores.forecast_id / forecast.thesis_id associated with the requested outcome. The prompt packet then misleads the agent into reflecting on the wrong trade/forecast.

observed vs expected:
Observed:
- Forecast/thesis selection is based only on instrument_id and earliest created_at/id.
Expected:
- The packet should select the forecast(s) actually connected to the outcome through forecast_scores or the canonical scoring/resolution relationship, then use that forecast’s thesis_id for the thesis payload.

reproduction/trace path:
1. Create one instrument.
2. Create thesis A + forecast A on that instrument.
3. Create thesis B + forecast B on the same instrument later.
4. Resolve outcome O that scored forecast B, so forecast_scores.forecast_id = forecast B and forecast_scores.outcome_id = O.
5. Call reflection.prompt_for_outcome(outcome_id=O).
6. Observe packet.forecast.id == forecast A and packet.thesis.id == thesis A, despite O resolving/scoring forecast B.

duplicate/overlap analysis:
This is not the existing “memory.reflect transaction/retry/idempotency” theme. It is read-only packet correctness in reflection.prompt_for_outcome. It also differs from broad “docs command/link issues”; the implementation deterministically picks the wrong row under a concrete multi-forecast same-instrument state.

proposed Bead body:
reflection.prompt_for_outcome currently selects the earliest forecast and thesis on the outcome’s instrument, not the forecast/thesis actually resolved by the requested outcome. In src/trade_trace/tools/reflection.py, _packet_for() loads the outcome, then uses WHERE t.instrument_id = ? ORDER BY f.created_at LIMIT 1 for forecast and a separate earliest-thesis query. When multiple forecasts exist for the same instrument, the returned deterministic prompt packet can reflect on the wrong forecast/thesis and compute calibration_delta against the wrong probability. Fix by selecting forecast(s) via forecast_scores WHERE outcome_id = ? (or the canonical outcome→forecast relation), then selecting thesis via that forecast.thesis_id. Add a regression with two forecasts on one instrument where the later forecast is scored by the requested outcome.

acceptance criteria:
- reflection.prompt_for_outcome(outcome_id=O) returns a forecast whose id is linked to O via forecast_scores/outcome scoring.
- packet.thesis.id equals packet.forecast.thesis_id when include_thesis=true.
- calibration_delta is computed from the returned forecast’s outcome probabilities.
- Regression test covers two forecasts on the same instrument and verifies the later/scored forecast is returned, not the earliest instrument forecast.
- Deterministic packet hash remains stable for identical inputs.

validation command:
TRADE_TRACE_HOME="$(mktemp -d)" pytest -q tests/integration -k "reflection or prompt_for_outcome"

risks/uncertainty:
I did not execute a custom seed because the code path is explicit and the docs contract is clear. Need confirm exact canonical outcome→forecast relation in schema; forecast_scores appears to be the right join because report_calibration also treats forecast_scores as the scored forecast/outcome link.


2. id: reports-memory-strategy-playbook-002
title: reflection.prompt_for_outcome omits prior reflections about the same strategy despite documented packet scope
severity: P3
confidence: medium-high
domain: reports-memory-strategy-playbook
bug_class: memory recall / prompt packet completeness
evidence_type: code/docs mismatch

evidence:
- docs/architecture/memory-layer.md:291 says reflection.prompt_for_outcome returns prior reflections “on the same instrument/strategy”.
- src/trade_trace/tools/reflection.py:110-128 builds prior_reflections only from:
  - about edges to the same instrument
  - about edges to outcomes whose instrument_id matches
- The SQL does not join theses/forecasts/decisions to discover the strategy_id for the outcome/forecast, and it does not include:
  e.target_kind = 'strategy' AND e.target_id = <strategy_id>
- The registered tool description in src/trade_trace/tools/reflection.py:218-224 says “prior reflections on the same instrument or outcome”, which itself has drifted from memory-layer.md’s “instrument/strategy” scope.

failure mode:
For strategy-scoped learning, an agent can have reflections attached directly to a strategy endpoint, but reflection.prompt_for_outcome will not include them in the prior_reflections packet for an outcome generated under that strategy. The agent receives a narrower packet than documented and may miss prior lessons for the active strategy.

observed vs expected:
Observed:
- Prior reflections query only covers instrument and same-instrument outcomes.
Expected:
- It should include prior reflections about the same strategy when the resolved forecast/thesis/decision has a strategy_id, consistent with docs/architecture/memory-layer.md.

reproduction/trace path:
1. Create strategy S.
2. Create thesis/forecast/outcome flow associated with strategy S.
3. Write memory.reflect(target_kind="strategy", target_id=S, body="Important prior lesson").
4. Call reflection.prompt_for_outcome(outcome_id=O, include_prior_reflections=true).
5. Observe the strategy reflection is absent from packet.prior_reflections.

duplicate/overlap analysis:
This is not the same as filter echo/ignore bugs or memory.reflect write bugs. It is a prompt-packet retrieval scope mismatch. It may relate conceptually to memory.recall strategy context, but the failing surface is reflection.prompt_for_outcome.

proposed Bead body:
reflection.prompt_for_outcome does not include strategy-scoped prior reflections even though memory-layer.md says the packet includes prior reflections on the same instrument/strategy. The implementation in src/trade_trace/tools/reflection.py only queries reflections about the same instrument or outcomes on that instrument. Add strategy resolution from the selected scored forecast/thesis/decision path and include about edges to target_kind='strategy'. Update tests and, if intentional, reconcile the tool description/docs; otherwise implement the documented strategy scope.

acceptance criteria:
- A reflection with about edge to strategy S appears in packet.prior_reflections for an outcome whose originating thesis/forecast/decision is strategy S.
- as_of filtering applies to strategy-scoped prior reflections exactly as it does to instrument/outcome reflections.
- Existing instrument/outcome prior reflection behavior remains unchanged.
- Tool description and memory-layer docs agree on the scope.

validation command:
TRADE_TRACE_HOME="$(mktemp -d)" pytest -q tests/integration -k "reflection or memory"

risks/uncertainty:
Depends on how the implementation resolves an outcome to a single strategy. This should be straightforward once candidate 001’s forecast/thesis linkage is corrected. If multiple decisions/strategies can legitimately tie to one outcome, acceptance criteria should specify deterministic tie-breaking or include all linked strategy reflections.


3. id: reports-memory-strategy-playbook-003
title: report.compare advertises/documented group_by values that are rejected at runtime
severity: P3
confidence: medium
domain: reports-memory-strategy-playbook
bug_class: report contract / user-visible validation mismatch
evidence_type: code/docs/tests mismatch

evidence:
- docs/PRD.md:385 documents report.compare(group_by, filter) groups including:
  agent_id, model_id, strategy_id, playbook_version_id, decision_type, venue_id, asset_class, liquidity_bucket, confidence_bucket, environment.
- src/trade_trace/reports/compare.py:50-53 defines DOCUMENTED_GROUP_BY with the same broader set:
  {"agent_id", "model_id", "strategy_id", "playbook_version_id", "decision_type", "venue_id", "asset_class", "liquidity_bucket", "confidence_bucket", "environment"}
- But implemented allowlists are narrower:
  - calibration: CALIBRATION_GROUP_SQL at src/trade_trace/reports/compare.py:30-41 lacks playbook_version_id, liquidity_bucket, confidence_bucket.
  - pnl: PNL_GROUP_SQL at src/trade_trace/reports/compare.py:43-48 supports only instrument_id, status, venue_id, asset_class, with special-case strategy_id at lines 157-163.
- Runtime rejection:
  - src/trade_trace/reports/compare.py:106-108 raises ValueError for unsupported calibration group_by.
  - src/trade_trace/reports/compare.py:157-163 raises ValueError for unsupported pnl group_by.
- tests/integration/test_report_compare.py only tests status grouping and injection rejection; it does not pin the documented group_by set.

failure mode:
Agents following docs or the in-code DOCUMENTED_GROUP_BY can call report.compare with group_by="playbook_version_id", "liquidity_bucket", or "confidence_bucket" and receive a validation error instead of the documented grouped report. This is deterministic and user-visible.

observed vs expected:
Observed:
- Public/documented values are rejected unless present in the base_report-specific SQL allowlist.
Expected:
- Either report.compare should support all documented group_by values where data exists, or report.filter_schema/tool docs should expose base_report-specific supported group_by values and docs should not advertise unsupported ones.

reproduction/trace path:
1. Initialize a temp journal.
2. Call report.compare with base_report="calibration", group_by="playbook_version_id".
3. Observe VALIDATION_ERROR/unsupported group_by despite the group being listed in docs/PRD.md and DOCUMENTED_GROUP_BY.
4. Repeat with liquidity_bucket/confidence_bucket.

duplicate/overlap analysis:
Not a duplicate of “ReportFilter echoed but ignored” because this is group_by contract drift, not filter application. Not a broad analytics wishlist because the values are explicitly listed in the docs and code as documented group_by values.

proposed Bead body:
report.compare exposes/documented group_by values that are not actually accepted by the implementation. docs/PRD.md and DOCUMENTED_GROUP_BY list playbook_version_id, liquidity_bucket, and confidence_bucket, but _compare_calibration/_compare_pnl reject them because they are missing from CALIBRATION_GROUP_SQL/PNL_GROUP_SQL. This causes docs-following agents to get VALIDATION_ERROR on advertised inputs. Fix either by implementing the missing group_by mappings where schema supports them, or by narrowing docs/tool schema to the actually supported base_report-specific sets and adding regression tests.

acceptance criteria:
- report.compare’s advertised group_by values match runtime behavior.
- If a value is documented, a call using it succeeds for the documented base_report(s), or the schema/docs clearly mark it unsupported/deferred.
- Regression tests cover every advertised group_by value or assert the schema omits unsupported values.
- Error messages distinguish unsupported-for-base-report from invalid/injected group_by.

validation command:
TRADE_TRACE_HOME="$(mktemp -d)" pytest -q tests/integration/test_report_compare.py

risks/uncertainty:
Some PRD lines still call report.compare P1/deferred, while the implementation now exists. If the current intended contract is intentionally narrower than PRD, the fix may be docs/schema tightening rather than implementing all groups.


Coverage accounting:

Files opened/probed/search-reviewed:
- /home/hermes/code/trade-trace/src/trade_trace/contracts/report_filter.py
- /home/hermes/code/trade-trace/src/trade_trace/reports/_filter_support.py
- /home/hermes/code/trade-trace/src/trade_trace/reports/playbook_adherence.py
- /home/hermes/code/trade-trace/src/trade_trace/reports/compare.py
- /home/hermes/code/trade-trace/src/trade_trace/reports/pnl.py
- /home/hermes/code/trade-trace/src/trade_trace/reports/calibration.py
- /home/hermes/code/trade-trace/src/trade_trace/reports/watchlist.py
- /home/hermes/code/trade-trace/src/trade_trace/models/memory.py
- /home/hermes/code/trade-trace/src/trade_trace/tools/memory.py
- /home/hermes/code/trade-trace/src/trade_trace/tools/reflection.py
- /home/hermes/code/trade-trace/src/trade_trace/tools/strategy.py
- /home/hermes/code/trade-trace/tests/integration/test_report_compare.py
- /home/hermes/code/trade-trace/docs/architecture/memory-layer.md
- Search-reviewed docs/PRD.md, docs/architecture/reports.md, docs/architecture/dogfood-protocol.md, docs/architecture/opportunity-analysis.md, docs/architecture/risk-units.md for relevant report/playbook/strategy terms.
- Search-reviewed tests list for report, memory, strategy coverage.

Commands/tools run and results:
- search_files file listing for repo and report/test/doc subsets.
- search_files content searches for ReportFilter, memory, playbook, strategy, reflect, recall, report.compare, group_by, strategy_performance, playbook_adherence.
- read_file on the source/docs/tests listed above.
- No pytest or custom Python snippet was run; findings are based on direct code/docs inspection.

Areas not inspected / why:
- Low-level storage/migrations were not exhaustively read except indirectly through report/memory code because the lane scope was behavior and the candidates were provable from implementation-level joins/queries.
- CLI parsing was not inspected because the bugs are in tool/report functions and deterministic packets, not invocation parsing.
- Full tests for memory/playbook were not all opened due time; focused inspection covered the directly relevant implementation and docs.

Side-effect caveats:
- No files created or modified.
- No Beads created/updated/closed.
- No package managers/installers/destructive commands.
- No shared-service mutations.
- Tool use was read-only.