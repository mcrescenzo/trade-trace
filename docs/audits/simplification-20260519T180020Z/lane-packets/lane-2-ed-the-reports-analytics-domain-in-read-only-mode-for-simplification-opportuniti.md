What I did:
Reviewed the reports-analytics domain in read-only mode for simplification opportunities.

Coverage accounting:
Inspected assigned domain map entry:
- docs/audits/simplification-20260519T180020Z/domain-map.json

Inspected all 17 assigned reports-analytics files:
- src/trade_trace/contracts/report_filter.py
- src/trade_trace/reports/__init__.py
- src/trade_trace/reports/_filter_support.py
- src/trade_trace/reports/buckets.py
- src/trade_trace/reports/calibration.py
- src/trade_trace/reports/coach.py
- src/trade_trace/reports/compare.py
- src/trade_trace/reports/decision_velocity.py
- src/trade_trace/reports/integrity.py
- src/trade_trace/reports/opportunity.py
- src/trade_trace/reports/playbook_adherence.py
- src/trade_trace/reports/pnl.py
- src/trade_trace/reports/risk.py
- src/trade_trace/reports/source_quality.py
- src/trade_trace/reports/tag_aggregates.py
- src/trade_trace/reports/unscored.py
- src/trade_trace/reports/watchlist.py

Also inspected related adapter surface:
- src/trade_trace/tools/reports.py

Duplicate/overlap checks:
- Searched prior audit artifacts under docs/audits for report/filter-related prior findings.
- Tried to inspect open Beads read-only with bd, but the command was blocked by the environment policy. I did not retry or mutate anything.

Files created or modified:
- None. Read-only review only.

Issues encountered:
- `python` was unavailable; used `python3` instead for AST/function inventory.
- A read-only `bd list` attempt was blocked by the tool policy. No Beads were created or updated.

Candidate records:

Candidate SIMPL-REPORTS-001

Title:
Deduplicate calibration scored-row loading between report.calibration and report.compare

Domain:
reports-analytics

Primary files:
- src/trade_trace/reports/calibration.py
- src/trade_trace/reports/compare.py

Evidence:
- calibration.py has the canonical scored forecast loader in `_load_scored_rows` at lines 136-202. It builds the base WHERE predicates, applies actor/venue/strategy filters, joins forecast_scores/forecasts/theses/instruments/outcomes, resolves `p_yes` and `y`, parses `late_recorded`, and returns `_ScoredRow`.
- compare.py duplicates much of that substrate in `_load_grouped_scored_rows` at lines 232-272. It repeats the same core predicates:
  - `fs.metric = 'brier_binary'`
  - `fs.score IS NOT NULL`
  - `f.kind = 'binary'`
  - superseded outcome exclusion
  - actor/venue/strategy filter wiring
  - late-recorded handling via metadata JSON
  - `_resolve_p_yes_and_y` call
- The two implementations already share `_ScoredRow`, `_resolve_p_yes_and_y`, `_compute_metrics`, `_empty_metrics`, and `_build_examples`, so the duplicated loader is the remaining parallel shape.

Simplification:
Refactor the calibration row-loading substrate so `report.compare(base_report='calibration')` can reuse the same predicate/filter/row materialization logic as `report.calibration`, with only the grouping expression layered on top.

Possible approach:
- Extract a shared helper in calibration.py or a small private module, e.g. `_scored_forecast_query_parts(rf)` or `_iter_scored_rows(conn, rf, group_expr=None)`.
- Keep the public report outputs unchanged.
- Preserve the allowlisted `CALIBRATION_GROUP_SQL` in compare.py; only reuse the common scored-forecast base query/predicate construction.
- Preserve late-recorded semantics:
  - `report.calibration` currently loads late rows, then excludes them after loading unless `include_late_recorded` is true.
  - compare.py currently pushes late-recorded exclusion into SQL when `include_late_recorded` is false.
  - Reconcile carefully so sample size, caveats, and group metrics remain behavior-compatible.

Behavior preservation notes:
- This is not a dead-code deletion.
- The goal is to prevent future contract drift between standalone calibration and grouped calibration.
- Tests likely covering this area:
  - tests/integration/test_report_calibration.py
  - tests/integration/test_report_compare.py
  - tests/integration/test_calibration_integrity.py
  - tests/integration/test_report_filter.py

Risk:
Medium. The SQL is contract-sensitive and late-recorded behavior differs slightly in placement. Needs golden/fixture preservation.

Estimated effort:
Medium.

Validation:
- pytest tests/integration/test_report_calibration.py tests/integration/test_report_compare.py tests/integration/test_report_filter.py -q
- pytest tests/contracts/test_report_envelope_completeness.py -q
- pytest tests -q if behavior changes are non-trivial

Non-duplication rationale:
This is a simplification/duplication candidate, not a bughunt/deadcode finding. It targets parallel loader logic, not unused code or incorrect output.

Candidate SIMPL-REPORTS-002

Title:
Introduce a small ReportResult construction helper for repeated summary/group envelope boilerplate

Domain:
reports-analytics

Primary files:
- src/trade_trace/reports/calibration.py
- src/trade_trace/reports/pnl.py
- src/trade_trace/reports/risk.py
- src/trade_trace/reports/unscored.py
- src/trade_trace/reports/watchlist.py
- src/trade_trace/reports/tag_aggregates.py
- src/trade_trace/reports/decision_velocity.py
- src/trade_trace/reports/playbook_adherence.py
- src/trade_trace/reports/opportunity.py
- src/trade_trace/reports/source_quality.py
- src/trade_trace/reports/integrity.py

Evidence:
Many reports hand-build the same result envelope shape:
- `summary` with:
  - `sample_size`
  - `sample_warning`
  - `filter`
  - `metrics`
  - `caveats`
- `groups` with:
  - `key`
  - `label`
  - `metrics`
  - `filter`
  - `record_ids`
  - `examples`
  - `sample_size`
  - `sample_warning`
  - `truncated`
- top-level:
  - `truncated`
  - `next_cursor`

Examples:
- calibration.py lines 100-130
- pnl.py lines 79-115
- risk.py lines 166-195
- unscored.py lines 72-101
- watchlist.py lines 60-97
- compare.py lines 141-154 and 216-229
- decision_velocity.py lines 80-106 per search evidence
- tag_aggregates.py lines 99-147 per search evidence

Simplification:
Add a tiny internal helper for common report envelope assembly, not a heavy abstraction. For example:
- `make_summary(sample_size, sample_warning, filter_view, metrics, caveats)`
- `make_group(key, label, metrics, filter_view, record_ids, examples, sample_size, sample_warning=None, truncated=False)`
- `make_report_result(summary, groups, truncated=None, next_cursor=None, **extras)`

This would reduce repeated literal dict scaffolding while leaving report-specific SQL, metrics, examples, and caveats local.

Behavior preservation notes:
- Avoid forcing all reports into a rigid class hierarchy.
- Keep report-specific fields like `bin_policy`, `as_of`, `integrity_diagnostics`, opportunity-specific labels, and source-quality diagnostics as explicit extras.
- Do not normalize away intentional differences in metrics names or group shape.
- This should be a mechanical refactor with no output shape changes.

Risk:
Low to medium. The output envelope is contract-tested, but the helper can be introduced incrementally.

Estimated effort:
Small to medium.

Validation:
- pytest tests/contracts/test_report_envelope_completeness.py -q
- pytest tests/integration/test_report_*.py -q
- pytest tests -q

Non-duplication rationale:
This is not dead code and not a bug; it is repeated report-envelope construction. It should be kept narrowly scoped to avoid over-abstraction.

Candidate SIMPL-REPORTS-003

Title:
Move report filter support declarations closer to report implementations or auto-register them to reduce contract drift

Domain:
reports-analytics

Primary files:
- src/trade_trace/reports/_filter_support.py
- src/trade_trace/reports/calibration.py
- src/trade_trace/reports/decision_velocity.py
- src/trade_trace/reports/compare.py
- src/trade_trace/reports/pnl.py
- src/trade_trace/reports/watchlist.py
- src/trade_trace/reports/unscored.py
- src/trade_trace/reports/tag_aggregates.py
- src/trade_trace/reports/coach.py
- src/trade_trace/reports/risk.py
- src/trade_trace/reports/opportunity.py
- src/trade_trace/tools/reports.py

Evidence:
- _filter_support.py centralizes `SUPPORTED_FILTER_FIELDS` at lines 46-95.
- Individual reports separately call `enforce_supported_filter(rf, report="...")` and `applied_filter_view(rf, report="...")`.
- The string report names are repeated across modules:
  - calibration.py uses `"report.calibration"` at lines 60, 103, 113.
  - pnl.py uses `"report.pnl"` at lines 47-48.
  - risk.py uses `"report.risk"` at lines 89-90.
  - watchlist.py uses `"report.watchlist"` at lines 36-37.
  - unscored.py uses `"report.unscored_forecasts"` at lines 31-32.
  - compare.py special-cases calibration and pnl support at lines 110, 168, 222, 275-276.
- _filter_support.py includes report names outside the reports module too, e.g. `"review.bundle"` lines 88-94, creating a cross-domain central registry.
- compare.py has a special behavior where standalone `report.pnl` supports only empty filters, but compare/strategy performance adds strategy slicing via custom logic at lines 164-176 and returns `rf.model_dump()` for strategy-filtered pnl compare at lines 222 and 276. This makes the filter contract harder to reason about from the central table alone.

Simplification:
Reduce stringly-typed central drift by colocating each report’s supported filter leaves with its implementation, or by introducing constants/registration.

Possible approaches:
1. Minimal:
   - Define `REPORT_NAME` and `SUPPORTED_FILTER_FIELDS` constants in each report module.
   - `_filter_support.py` imports/collects them.
   - Each report calls `enforce_supported_filter(rf, report=REPORT_NAME)`.
2. Moderate:
   - Add `enforce_report_filter(rf, supported_fields, report_name)` so reports do not need global registry lookup.
   - Keep a derived registry for introspection and tool error details.
3. For compare:
   - Declare compare-specific filter support under `"report.compare"` / base-report combination rather than borrowing `"report.pnl"` and then bypassing it for strategy filtering.

Behavior preservation notes:
- The current central registry intentionally prevents silently broadened reports; keep that behavior.
- Do not remove unsupported filter rejection.
- Keep `UnsupportedFilterError` details with `unsupported_filter_paths` and `supported_filter_paths`.
- Be careful with `review.bundle`, which is outside this domain but uses the same registry.

Risk:
Medium. This touches validation contracts and error details.

Estimated effort:
Medium.

Validation:
- pytest tests/integration/test_report_filter.py -q
- pytest tests/security/test_report_sql_filters.py -q
- pytest tests/contracts/test_report_envelope_completeness.py -q
- pytest tests/integration/test_report_compare.py -q
- pytest tests -q

Non-duplication rationale:
This is a contract-drift simplification candidate, not a bug. It specifically preserves the strict rejection model introduced in _filter_support.py.

Candidate SIMPL-REPORTS-004

Title:
Extract common SQL predicate helpers for ReportFilter leaves used by multiple reports

Domain:
reports-analytics

Primary files:
- src/trade_trace/reports/calibration.py
- src/trade_trace/reports/compare.py
- src/trade_trace/reports/decision_velocity.py
- src/trade_trace/reports/_filter_support.py
- src/trade_trace/contracts/report_filter.py

Evidence:
Multiple reports hand-build SQL WHERE fragments from ReportFilter leaves:
- calibration.py lines 153-164:
  - actor_id IN placeholders
  - venue_id IN placeholders
  - strategy_id sentinel handling
- compare.py lines 238-249 repeats similar actor_id, venue_id, strategy_id logic.
- compare.py lines 171-176 separately handles `strategy.strategy_id` for PnL grouping.
- decision_velocity.py, per search evidence, validates and applies `time_window.decision_at_gte`, `time_window.decision_at_lt`, and `decision.decision_type`.
- calibration.py has `_placeholders(count)` at lines 205-206, while compare.py constructs placeholders inline with `', '.join('?' for _ in ...)`.

Simplification:
Add narrow SQL helper functions for supported leaf predicates, for example:
- `append_in_filter(where, params, sql_expr, values)`
- `append_strategy_filter(where, params, sql_expr, strategy_id)`
- `append_time_bounds(where, params, column, gte, lt)`
- `placeholders(count)`

This avoids duplicating security-sensitive parameterized SQL construction while keeping report-specific JOINs and metrics local.

Behavior preservation notes:
- Helpers must only generate parameterized SQL, never interpolate caller values.
- Keep allowlisted group expressions in compare.py.
- Keep `STRATEGY_NONE_SENTINEL` semantics from report_filter.py:
  - None means no filter
  - `"__none__"` means IS NULL
  - other string means equality match

Risk:
Low to medium. SQL predicate helpers are simple, but tests should catch output drift.

Estimated effort:
Small.

Validation:
- pytest tests/security/test_report_sql_filters.py -q
- pytest tests/integration/test_report_filter.py -q
- pytest tests/integration/test_report_calibration.py tests/integration/test_report_compare.py tests/integration/test_report_unscored_velocity.py -q

Non-duplication rationale:
This does not change report behavior. It targets duplicated parameterized SQL predicate construction, especially around the strategy sentinel.

Candidate SIMPL-REPORTS-005

Title:
Keep report-specific metric code local; do not introduce a broad report class hierarchy

Domain:
reports-analytics

Primary files:
- src/trade_trace/reports/calibration.py
- src/trade_trace/reports/risk.py
- src/trade_trace/reports/opportunity.py
- src/trade_trace/reports/source_quality.py
- src/trade_trace/reports/integrity.py
- src/trade_trace/reports/coach.py

Evidence:
Several report implementations are intentionally different:
- calibration.py has scoring-specific Brier/log/ECE/bin metrics and late-recorded caveats.
- risk.py computes R-multiple metrics, histogram bins, coverage, missing-risk and pending-risk caveats.
- opportunity.py computes path-dependent decision/outcome movement diagnostics.
- source_quality.py is intentionally global and has provenance-hygiene diagnostics; its docstring explicitly says it has no ReportFilter input.
- integrity.py emits denominator/hygiene diagnostics and no standard filter path.
- coach.py composes other reports and enforces no-trade-advice language.

Simplification recommendation:
Avoid a sweeping BaseReport class or generalized metric pipeline. Only extract narrow, mechanical helpers:
- report envelope dict construction
- filter validation/view plumbing
- SQL predicate fragments
- calibration scored-row substrate

Behavior preservation notes:
The absence of a shared metric abstraction appears intentional because reports have report-specific semantics and caveats. Over-unifying them would likely make behavior less clear.

Risk:
This is a negative/guardrail candidate: no direct code change recommended except to constrain future simplification scope.

Estimated effort:
None, unless captured as guidance in the simplification epic.

Validation:
Not applicable unless paired with another candidate.

Non-duplication rationale:
This records an intentional non-finding to prevent over-abstraction churn.

Overall findings:
- The domain is generally well-structured and already has some useful shared kernels (`_pnl_metrics_for_rows`, calibration metric helpers, `_filter_support`).
- Best simplification opportunities are narrow:
  1. Deduplicate calibration scored-row loading between calibration and compare.
  2. Add small report envelope/group construction helpers.
  3. Reduce filter support registry drift/string repetition.
  4. Extract parameterized SQL predicate helpers.
- I did not find evidence that a broad report framework/class hierarchy would be beneficial; report-specific semantics appear intentionally preserved.