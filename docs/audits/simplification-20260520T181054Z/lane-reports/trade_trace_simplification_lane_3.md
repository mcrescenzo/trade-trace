# Lane 3 status: completed

Read-only simplification review complete for assigned domain: reports-memory-playbook.

What I did:
- Verified repo/branch/commit: /home/hermes/code/trade-trace, main, ffcd97420bf44c846451bd5d39596d39437d6e3e.
- Inspected in-scope code only:
  - src/trade_trace/reports/
  - src/trade_trace/tools/reports.py
  - src/trade_trace/tools/memory.py
  - src/trade_trace/tools/playbook.py
  - src/trade_trace/tools/strategy.py
  - src/trade_trace/tools/review_bundle.py
  - src/trade_trace/models/memory.py
  - relevant integration/contract tests by file discovery.
- Performed read-only discovery only. No edits, no Beads writes, no memory/Hindsight, no push/publish/delete.
- Verified working tree remained clean.

Files created or modified:
- None.

Issues encountered:
- The prompt listed tools/... paths, but actual files are under src/trade_trace/tools/...
- python was unavailable as python; used python3 for read-only AST/line-count inspection.
- No other issues.

Candidate records:

1) Candidate: consolidate report tool adapter boilerplate beyond existing filter-only wrapper

File/line evidence:
- src/trade_trace/tools/reports.py:109-144 _report_calibration
- src/trade_trace/tools/reports.py:147-176 _report_playbook_adherence
- src/trade_trace/tools/reports.py:227-247 _report_unscored_forecasts
- src/trade_trace/tools/reports.py:250-279 _report_decision_velocity
- src/trade_trace/tools/reports.py:282-311 _report_compare
- src/trade_trace/tools/reports.py:314-343 _report_strategy_performance
- src/trade_trace/tools/reports.py:346-372 _report_opportunity
- src/trade_trace/tools/reports.py:400-432 _report_watchlist
- src/trade_trace/tools/reports.py:435-465 _report_coach
- Existing partial helper: src/trade_trace/tools/reports.py:375-397 _make_filter_only_report

Simplification:
- Introduce a bounded internal helper for the common lifecycle:
  open_db_for_args(args)
  try/finally db.close()
  translate ValidationError to ToolError VALIDATION_ERROR field=filter
  translate UnsupportedFilterError via _unsupported_filter_to_tool_error
  call _propagate_report_meta(ctx, data)
  return data
- Keep special per-report validation/call-shaping outside the helper, or pass a small callable/lambda.

Behavior contract:
- Preserve exact tool names, return envelopes, ctx.meta_hints propagation, error codes/details/messages where tests assert them.
- Preserve report-specific ValueError mappings for compare/strategy_performance/opportunity.
- Preserve TradingAdvicePhraseError handling for report.coach.
- Preserve calibration’s embedded integrity_diagnostics behavior.

Validation path/gap:
- Existing coverage likely:
  - tests/contracts/test_report_envelope_completeness.py
  - tests/integration/test_report_filter.py
  - tests/security/test_report_sql_filters.py
  - tests/integration/test_report_sample_warnings.py
  - tests/integration/test_report_calibration.py
  - tests/integration/test_report_compare.py
  - tests/integration/test_report_opportunity.py
  - tests/integration/test_report_coach.py
  - tests/integration/test_report_unscored_velocity.py
  - tests/integration/test_report_pnl_watchlist.py
  - tests/integration/test_report_risk.py
  - tests/integration/test_report_tag_aggregates.py
- Gap: add/confirm focused parity tests for ValueError translation details on compare/strategy_performance/opportunity if refactoring the adapter.

Overlap notes:
- Related to known hotspot “tools/reports.py ~709 lines” and duplicate filtering/report envelopes.
- Avoids known bughunt items: report.playbook_adherence nonexistent playbook_id and report.opportunity process labels are not the target here.

Coverage accounting:
- Adapter duplication appears in at least 9 handlers plus the existing helper; likely moderate line reduction without analytics changes.

2) Candidate: centralize report envelope construction in report modules

File/line evidence:
- src/trade_trace/reports/tag_aggregates.py:131-143 returns summary/groups/truncated/next_cursor
- src/trade_trace/reports/decision_velocity.py:85-98 same envelope pattern
- src/trade_trace/reports/watchlist.py:84-98 same envelope pattern
- src/trade_trace/reports/pnl.py:92-108 same envelope pattern
- src/trade_trace/reports/unscored.py:68-93 same envelope pattern
- src/trade_trace/reports/playbook_adherence.py:128-143 same envelope pattern
- src/trade_trace/reports/opportunity.py:317-333 same envelope pattern
- src/trade_trace/reports/compare.py:157-166 and 232-241 same envelope pattern

Simplification:
- Add a small internal report helper, e.g. make_report_result(summary, groups, truncated=False, next_cursor=None, **extra), used by modules with the standard envelope.
- Optionally pair with summary builder for common keys: sample_size, sample_warning, filter, metrics, caveats.

Behavior contract:
- Preserve dict shape and key names exactly:
  summary
  groups
  truncated
  next_cursor
- Preserve deterministic ordering where tests/hash contracts rely on insertion order.
- Preserve report-specific fields such as bin_policy, integrity_diagnostics, report_summaries, etc. where present.
- Do not alter filtering semantics or sample-size calculations.

Validation path/gap:
- Existing tests cover report envelopes and sample warnings:
  - tests/contracts/test_report_envelope_completeness.py
  - tests/integration/test_report_sample_warnings.py
  - all test_report_*.py integration tests.
- Gap: if helper changes insertion order, review_bundle hash-like consumers may not care for report modules, but contract tests should verify JSON key presence. Add snapshot/parity only if current tests do not assert exact envelope shape.

Overlap notes:
- Directly addresses duplicate report result construction.
- Does not touch dashboard presentation except possible reporting adapter overlap.

Coverage accounting:
- 8+ report modules have visible repeated envelope construction. Bounded helper could reduce repeated boilerplate and make future report contracts less drift-prone.

3) Candidate: unify report filter validation/support handling between reports and review.bundle

File/line evidence:
- src/trade_trace/reports/_filter_support.py:156-182 already provides applied_filter_view/process_filter
- src/trade_trace/tools/reports.py:50-66 translates UnsupportedFilterError to ToolError with details
- src/trade_trace/tools/reports.py:130-137, 165-172, 236-243, 268-275, etc. repeat ValidationError/UnsupportedFilterError handling
- src/trade_trace/tools/review_bundle.py:440-459 repeats ReportFilter validation and UnsupportedFilterError-to-ToolError mapping, but with local details shape

Simplification:
- Extract a tool-layer helper, e.g. validate_report_filter_for_tool(raw_filter, report), that returns filter view and consistently translates:
  - Pydantic ValidationError
  - UnsupportedFilterError
- Use it in review.bundle and report tool wrappers where applicable.

Behavior contract:
- Preserve review.bundle’s accepted filter subset and REVIEW_BUNDLE_REPORT.
- Preserve current ErrorCode.VALIDATION_ERROR and detail keys expected by tests:
  - field=filter for ReportFilter validation
  - unsupported_filter_paths for unsupported fields
- Avoid changing report module process_filter behavior.

Validation path/gap:
- Existing:
  - tests/integration/test_review_bundle_contract.py
  - tests/integration/test_report_filter.py
  - tests/security/test_report_sql_filters.py
  - tests/contracts/test_tool_schema_runtime_parity.py
- Gap: review.bundle unsupported-filter contract should be explicitly asserted before consolidating error conversion, because reports.py uses _unsupported_filter_to_tool_error while review_bundle.py currently builds details inline.

Overlap notes:
- Related to duplicate filtering/report result construction.
- No overlap with known bughunt analytics bugs.

Coverage accounting:
- One review_bundle block plus many report wrappers share the same failure pattern; small but high-value contract-drift reduction.

4) Candidate: split memory.recall orchestration into parse/validate, rank, format, log helpers

File/line evidence:
- src/trade_trace/tools/memory.py:623-859 _memory_recall is 237 lines
- Input validation and option parsing: 630-707
- Ranking orchestration: 712-751
- budget/body/provenance formatting: 755-787
- recall event + stats write transaction: 789-823
- response/meta_hints construction: 827-859
- Ranking helpers already exist below: 865-1116

Simplification:
- Keep tool surface intact, but split into private helpers:
  - _parse_recall_args(args)
  - _rank_memory_nodes(conn, query, context, as_of, requested_strategies, node_types)
  - _format_recall_items(conn, scored, in_scope_rows, budget options)
  - _log_recall_event_and_update_stats(conn, ...)
  - _recall_meta_hints(...)
- This is behavior-preserving because ranking algorithms already live in separate helpers.

Behavior contract:
- Preserve ranking order, RRF constants, semantic auto-inclusion behavior, supersession discount, importance boost, min_confidence filtering order, budget hard-stop behavior, per_strategy contents, recall event insert, stats projection maintenance, and ctx.meta_hints.
- Preserve write side effects of memory.recall: it logs memory_recall_events and updates memory_node_stats.

Validation path/gap:
- Existing:
  - tests/integration/test_memory_recall_budgets.py
  - tests/integration/test_memory_retrieval_constants.py
  - tests/integration/test_memory_layer.py
  - tests/integration/test_projection_rebuild.py
  - tests/integration/test_reproducibility_replay.py
  - tests/security/test_embeddings_off_by_default.py
  - tests/security/test_embeddings_api_keyring.py
  - tests/security/test_no_network_default.py
- Gap: add/confirm tests for exact ordering when min_confidence and max_chars both apply, since helper extraction could accidentally reorder filter/budget application.

Overlap notes:
- This is simplification through decomposition, not analytics behavior change.
- Intentional complexity: RRF/ranking/semantic-off-by-default/security controls should remain explicit.

Coverage accounting:
- One 237-line function has five distinct responsibilities. Moderate maintainability gain with low conceptual risk if covered by existing memory recall tests.

5) Candidate: extract common write-tool idempotency result/emit patterns for strategy/playbook/memory

File/line evidence:
- src/trade_trace/tools/memory.py:192-215 idempotent replay branch for memory_node.retained
- src/trade_trace/tools/playbook.py:347-371 idempotent replay branch for playbook.proposed_version
- src/trade_trace/tools/playbook.py:517-540 idempotent replay branch for playbook_rule followed/overridden
- src/trade_trace/tools/strategy.py:101-119 idempotent replay branch for strategy.created
- src/trade_trace/tools/strategy.py:344-363 idempotent replay branch for strategy.updated
- Repeated final return dicts:
  - strategy.create: 157-161
  - strategy.update: 388-393
  - playbook.propose_version: 431-436
  - decision.record_adherence: 569-574

Simplification:
- Introduce small local helpers for:
  - emitting replay payload with common emit_event arguments
  - row-to-response mapping for playbook version/adherence, analogous to _strategy_row_to_dict
- Keep this bounded; do not create a broad generic framework.

Behavior contract:
- Preserve idempotency conflict semantics from EventWriter.
- Preserve payload content exactly where semantic_keys/replay checks depend on it.
- Preserve subject_kind, subject_id, event_type, actor_id, ctx propagation.
- Preserve response dict fields and created_at/updated_at semantics.

Validation path/gap:
- Existing:
  - tests/integration/test_playbook_layer.py
  - tests/integration/test_strategy_tools.py
  - tests/integration/test_reproducibility_replay.py
  - tests/contracts/test_event_enum_coverage.py
  - tests/integration/test_semantic_keys.py
- Gap: add/confirm idempotency replay assertions for playbook.propose_version and decision.record_adherence before any helper consolidation.

Overlap notes:
- Pass-through/idempotency adapter cleanup, not a behavior change.
- Keep intentional explicit endpoint validation; do not hide DB constraints behind too generic a helper.

Coverage accounting:
- Repeated branches in 5 write handlers; small to moderate line reduction, mainly contract-drift prevention.

6) Candidate: normalize meta_json object parsing/validation in memory.reflect and memory.retain

File/line evidence:
- src/trade_trace/tools/memory.py:168-186 _memory_retain_in_uow parses string meta_json, validates object, json.dumps(sort_keys=True)
- src/trade_trace/tools/memory.py:366-383 _normalize_reflect_input repeats string meta_json parsing/object validation for tag folding
- src/trade_trace/tools/strategy.py:81 and 288-290 dumps meta_json without same object-shape validation
- src/trade_trace/tools/playbook.py:308 and 467 dumps metadata_json similarly

Simplification:
- Add an internal helper for “metadata object from args field”:
  - accept None -> {}
  - accept JSON string -> object or validation error
  - require dict/object
  - optionally return canonical JSON string or dict depending caller
- First apply in memory.py only to avoid widening behavior unexpectedly; later consider strategy/playbook if contract allows.

Behavior contract:
- Preserve current error codes/messages/details for memory.retain and memory.reflect, especially field names meta_json and invalid_json.
- Be careful: strategy/playbook may currently accept list/scalar metadata_json by serializing it; changing that could be behavior-changing unless explicitly desired.

Validation path/gap:
- Existing:
  - tests/integration/test_memory_layer.py
  - tests/integration/test_memory_link.py
  - tests/integration/test_memory_recall_budgets.py
  - tests/security/test_secret_pattern_writes.py
- Gap: add direct tests for meta_json string/object/scalar behavior on memory.retain and memory.reflect before extracting.

Overlap notes:
- Contract drift lens: memory has stricter object-shape behavior than adjacent write tools. The simplification candidate is memory-local unless a separate behavior-change issue is opened.

Coverage accounting:
- Small duplication inside memory.py; broader standardization would touch strategy/playbook but may not be behavior-preserving.

7) Candidate: review.bundle can reuse generic row-fetch utilities more consistently

File/line evidence:
- src/trade_trace/tools/review_bundle.py:136-158 _decision_rows manually defines cols/SQL/dict zip
- src/trade_trace/tools/review_bundle.py:161-188 _fetch_by_ids provides a generic table/id/cols fetcher
- src/trade_trace/tools/review_bundle.py:191-249 _related_record_rows manually orchestrates related fetches
- src/trade_trace/tools/review_bundle.py:430-548 _review_bundle_handler orchestrates many unrelated steps

Simplification:
- Use _fetch_by_ids for decisions too if its ordering semantics can match decision ordering, or introduce _fetch_ordered_rows(table, ids, cols, order_by).
- Split _review_bundle_handler into phases:
  - parse/validate filter
  - gather bundle components
  - gather report summaries
  - redact/build caveats
  - hash/meta
- Keep canonical JSON/hash logic unchanged.

Behavior contract:
- Preserve deterministic row ordering and key insertion order because bundle_hash depends on canonical JSON over data.
- Preserve sensitive/redacted source caveats and secret replacement counts.
- Preserve partial failure behavior for calibration summary: broad catch at lines 496-500 intentionally continues with sample_size 0.

Validation path/gap:
- Existing:
  - tests/integration/test_review_bundle_contract.py
  - tests/security/test_redacted_exports.py
  - tests/security/test_secret_pattern_writes.py
- Gap: bundle_hash stability test should be run/strengthened before any helper extraction that changes key order or included empty lists.

Overlap notes:
- Intentional complexity: redaction, canonical hash, deterministic ordering should remain explicit and well tested.
- This is bounded decomposition, not a schema redesign.

Coverage accounting:
- One 119-line handler plus duplicated row fetch patterns. Moderate readability gain; high caution due to hash contract.

8) Candidate: strategy.create/update response construction can be centralized

File/line evidence:
- src/trade_trace/tools/strategy.py:164-169 _strategy_row_to_dict exists
- src/trade_trace/tools/strategy.py:157-161 create manually returns same shape
- src/trade_trace/tools/strategy.py:329-338 candidate_result manually builds same shape
- src/trade_trace/tools/strategy.py:355-363 replay return manually builds same shape
- src/trade_trace/tools/strategy.py:388-393 final update return manually builds same shape

Simplification:
- Reuse one response builder for all strategy response shapes, possibly extending _strategy_row_to_dict to accept dict/row or adding _strategy_response(...).
- Avoid changing create/update SQL or idempotency handling.

Behavior contract:
- Preserve exact response keys:
  id, name, slug, description, hypothesis, status, created_at, updated_at.
- Preserve updated_at behavior on update and create.
- Preserve idempotent replay returns.

Validation path/gap:
- Existing:
  - tests/integration/test_strategy_tools.py
  - tests/integration/test_reproducibility_replay.py
  - tests/contracts/test_tool_schema_runtime_parity.py
- Gap: none obvious if response equality is already asserted; if not, add a simple response-key contract test.

Overlap notes:
- Low-risk pass-through adapter cleanup.
- No analytics/report overlap.

Coverage accounting:
- Small line reduction, but reduces future strategy contract drift.

Intentional complexity / not recommended as simplification targets:
- src/trade_trace/tools/memory.py ranking helpers (_bm25_rank, _temporal_rank, _graph_rank, _semantic_rank, _rrf_combine) are complex for good reason: reproducible retrieval, optional semantic provider, no-network/default security constraints, and provenance requirements.
- src/trade_trace/tools/review_bundle.py canonical hashing/redaction/caveat flow should remain explicit; only decompose, do not generalize away.
- src/trade_trace/reports/_filter_support.py already centralizes supported filter enforcement and applied filter projection; avoid bypassing it.
- Existing report.playbook_adherence and report.opportunity known bughunt items were not duplicated here.

Coverage/accounting summary:
- Reports adapter duplication: high-confidence simplification, covered by broad report tests.
- Report envelope construction: high-confidence simplification, should preserve key order/shape.
- Filter error conversion: medium-confidence, needs review_bundle unsupported-filter detail assertions.
- memory.recall decomposition: medium-confidence, good tests exist but exact ordering/budget interactions need care.
- write-tool idempotency helpers: medium-confidence, ensure replay/event semantic tests.
- meta_json helper: low-to-medium, memory-local is safe; cross-tool standardization may be behavior-changing.
- review.bundle decomposition: medium-confidence but hash/determinism-sensitive.
- strategy response builder: low-risk small cleanup.
