Read-only technical-debt review completed for reports / projections / exporter lane.

What I did:
- Verified repo/commit: /home/hermes/code/trade-trace at a33e676ec9d22d6ec268686424521a3d2586f9dd.
- Inspected in-scope source:
  - src/trade_trace/reports/*.py
  - src/trade_trace/projections.py
  - src/trade_trace/exporter.py
  - Related report tool wiring in src/trade_trace/tools/reports.py
  - ReportFilter contract in src/trade_trace/contracts/report_filter.py
  - Relevant tests under tests/integration and tests/security
- Stayed read-only. No edits, no Beads, no installs, no formatters.

Workspace note:
- The working tree already had unrelated modified files before review:
  - src/trade_trace/events/log.py
  - src/trade_trace/events/unit_of_work.py
  - several src/trade_trace/reports/*.py
  - untracked audits/ and docs/audits/
- I did not modify anything.

Structured technical-debt candidates:

1. ReportFilter is widely validated and echoed but not actually applied by most reports
   Lens: type-schema-debt, test-debt, maintenance-hotspot
   Severity: High
   Paths:
   - src/trade_trace/reports/calibration.py
   - src/trade_trace/reports/tag_aggregates.py
   - src/trade_trace/reports/pnl.py
   - src/trade_trace/reports/unscored.py
   - src/trade_trace/reports/watchlist.py
   - src/trade_trace/reports/playbook_adherence.py
   - src/trade_trace/reports/decision_velocity.py
   Evidence:
   - ReportFilter has many filter dimensions: time_window, actors, strategy, instrument, decision, market_context, outcome, source.
   - Most reports call ReportFilter.model_validate(raw_filter or {}) and echo rf.model_dump(), but query only a tiny subset or none:
     - report_pnl validates raw_filter but always SELECTs all positions.
     - report_watchlist validates raw_filter but always SELECTs all type='watch' decisions.
     - report_unscored_forecasts validates raw_filter but does not apply actor/instrument/strategy/time filters.
     - report_calibration validates raw_filter but only uses outcome.include_late_recorded; all other filters are ignored.
     - tag_aggregates validates raw_filter but does not filter by any ReportFilter field.
     - playbook_adherence docstring claims it honors decision.tags_any, decision.decision_type, actor/segmentation slices, but implementation only applies top-level playbook_id and strategy_id arguments.
     - decision_velocity only applies decision_at bounds and decision.decision_type.
   Why this is maintenance debt:
   - The schema and echoed normalized_filter make callers believe scoped reports were computed, while the SQL may still use global data.
   - Future reports can repeat the same “validate but ignore” pattern.
   - Tests currently mostly prove schema rejection/echo behavior, not semantic filtering.
   Bounded remediation:
   - Add a shared ReportFilter-to-SQL helper per base table/view, e.g. compile_report_filter(base='decisions'|'forecasts'|'positions').
   - Each report should explicitly declare supported filter fields and either apply them or reject unsupported non-empty fields with VALIDATION_ERROR.
   - Add integration tests that seed two actors/instruments/strategies/time windows and assert filtered reports exclude the non-matching rows.
   Avoid duplicate theme note:
   - This is not docs QC; it is concrete runtime/schema mismatch in report query behavior.

2. Projection rebuild computes realized P&L with sign ambiguity likely inverted for common long-close fixtures
   Lens: state-persistence-debt, test-debt
   Severity: High
   Path:
   - src/trade_trace/projections.py lines 221-227
   Evidence:
   - _accumulate_position calculates:
     realized_pnl += (price - avg_entry_price) * qty_delta
   - Related tests seed long-like opens with quantity_delta=100 and closes with quantity_delta=-100:
     tests/integration/test_report_sample_warnings.py lines 121-135.
   - Under that convention, opening at 0.40 and closing at 0.50 gives:
     (0.50 - 0.40) * -100 = -10, which is opposite expected long P&L.
   - The code comment says “Direction-agnostic realized PnL” but then multiplies by signed qty_delta.
   Why this is maintenance debt:
   - positions is a rebuildable projection and report.pnl consumes it; incorrect sign becomes persistent derived state after rebuild.
   - The current tests exercise sample warnings/idempotency but appear not to pin P&L sign semantics.
   Bounded remediation:
   - Define the canonical signed-quantity convention in code/tests.
   - Use side/kind and abs(exit_qty) where appropriate, e.g. long: (exit - avg_entry) * abs(exit_qty), short: (avg_entry - exit) * abs(exit_qty).
   - Add projection rebuild test asserting realized_pnl for long profitable close, long losing close, and short equivalent cases.

3. report.source_quality truncation corrupts diagnostic count
   Lens: observability-debt, type-schema-debt
   Severity: Medium
   Path:
   - src/trade_trace/reports/source_quality.py lines 92-104
   Evidence:
   - _bundle computes truncated = len(items) > MAX_SAMPLE_IDS.
   - If truncated, it mutates items = items[:MAX_SAMPLE_IDS].
   - Then returns "count": len(items).
   - Result: any diagnostic with more than 100 hits reports count=100 rather than true underlying count.
   Why this is maintenance debt:
   - Observability reports understate the actual hygiene problem exactly when the diagnostic is large.
   - Callers cannot distinguish “exactly 100” from “many more than 100” except truncated=true, and rate/summary math cannot be added reliably later.
   Bounded remediation:
   - Preserve total_count before truncating.
   - Return count=total_count and samples/sample_ids capped to MAX_SAMPLE_IDS.
   - Add test with MAX_SAMPLE_IDS + 1 matching source-quality rows.

4. report.calibration top-level truncated flag can disagree with group truncation
   Lens: observability-debt, contract-debt
   Severity: Medium
   Path:
   - src/trade_trace/reports/calibration.py lines 88-121
   Evidence:
   - group_record_ids are capped at 1000 and local variable truncated is set True.
   - That variable is placed on the group at line 113.
   - Top-level return always sets "truncated": False at line 120.
   Why this is maintenance debt:
   - Tool meta propagation only sees top-level data["truncated"] in src/trade_trace/tools/reports.py lines 64-68.
   - A caller relying on meta.truncated will miss that record_ids were capped.
   Bounded remediation:
   - Return top-level "truncated": truncated when any group truncates.
   - Optionally include next_cursor or explicit truncation reason if pagination remains deferred.
   - Add a contract test with >1000 scored rows asserting both group and top-level/meta truncation.

5. report.coach has envelope-shape compatibility branch only for mistakes, not strengths
   Lens: maintenance-hotspot, type-schema-debt
   Severity: Medium
   Path:
   - src/trade_trace/reports/coach.py lines 87-118
   Evidence:
   - top_mistakes supports two shapes:
     - mistakes["data"]["groups"] if wrapped
     - mistakes["groups"] if raw
   - top_strengths only supports strengths["groups"].
   - In current direct function use both likely raw, but the asymmetry is a brittle partial compatibility shim.
   Why this is maintenance debt:
   - If report_strengths is ever called through the same wrapped path as mistakes, coach fails with KeyError.
   - The branch duplicates mapping logic and makes future report-envelope changes risky.
   Bounded remediation:
   - Introduce a small helper: _groups(report) = report.get("data", report)["groups"].
   - Use it for both mistakes and strengths.
   - Add a unit test for coach helper with raw and wrapped report shapes, or remove wrapped-shape support entirely if not needed.

6. report.watchlist uses live wall-clock twice, causing internally inconsistent stale/age/as_of values
   Lens: observability-debt, test-debt
   Severity: Low-Medium
   Path:
   - src/trade_trace/reports/watchlist.py lines 38-41, 50, 77, 83-91
   Evidence:
   - stale threshold uses datetime.now(UTC).
   - each row’s age_days calls datetime.now(UTC) again.
   - return as_of uses now_iso(), a third clock read.
   Why this is maintenance debt:
   - Boundary tests around stale_threshold_days can be flaky.
   - A report can classify a watch using one instant but compute age/as_of with later instants.
   Bounded remediation:
   - Capture one as_of datetime at report entry.
   - Pass it into _age_days and _is_stale.
   - Return as_of derived from the same captured instant.
   - Add boundary test for exactly threshold age.

7. exporter.drain_outbox leaves invalid event payload JSON as an untyped crash path
   Lens: state-persistence-debt, observability-debt
   Severity: Medium
   Path:
   - src/trade_trace/exporter.py lines 286-316
   Evidence:
   - _load_event returns payload_json from events.
   - drain_outbox does payload = json.loads(payload_json) outside the OSError try block.
   - If events.payload_json is corrupted or non-object JSON, the drain can raise JSONDecodeError/TypeError and abort, without marking the outbox row failed or incrementing attempt_count.
   - Missing event rows are handled defensively; filesystem OSError is handled; malformed payload is not.
   Why this is maintenance debt:
   - Outbox is a state machine with pending/failed/exported states; malformed event payloads can wedge the drain with a repeat crash and no per-row error_text.
   Bounded remediation:
   - Catch json.JSONDecodeError and non-dict payload cases per outbox row.
   - Mark state='failed', increment attempt_count, set error_text='invalid_payload_json' or similar.
   - Continue draining subsequent rows.
   - Add outbox export test with corrupted payload_json.

8. exporter JSONL file path uses unsanitized event_type directly in filename
   Lens: state-persistence-debt, maintenance-hotspot
   Severity: Low-Medium
   Path:
   - src/trade_trace/exporter.py lines 36-46, 117-118
   Evidence:
   - jsonl_path returns f"{event_type}-{event_id}.jsonl".
   - Current known event types are dotted names, but exporter itself accepts arbitrary event_type.
   - If a future/internal event_type includes "/" or path-ish characters, exporter writes nested or unintended paths below the day directory.
   Why this is maintenance debt:
   - Exporter is a persistence boundary; it should enforce filename-safe transport names locally rather than relying on all upstream event_type producers forever.
   Bounded remediation:
   - Add a local filename encoder/sanitizer for event_type, e.g. allow [A-Za-z0-9._-] and reject/escape anything else.
   - Add test for slash-containing event_type either rejected or encoded deterministically.

9. report.playbook_adherence counts rows for summary.sample_size but decisions for group.sample_size
   Lens: observability-debt, type-schema-debt
   Severity: Low
   Path:
   - src/trade_trace/reports/playbook_adherence.py lines 78, 111-122
   Evidence:
   - group sample_size = number of distinct decision_ids.
   - summary sample_size = len(rows), i.e. adherence-row count.
   - Summary also separately reports total_adherence_rows, so sample_size duplicates row count while group sample_size means decision count.
   Why this is maintenance debt:
   - “sample_size” has inconsistent semantics inside the same report envelope.
   - Sample warning threshold is defined as decisions with adherence rows, but summary.sample_size reports adherence rows.
   Bounded remediation:
   - Change summary.sample_size to distinct decision count, leaving total_adherence_rows in metrics.
   - Add a test with one decision and multiple rule rows.

10. report.pnl data_coverage denominator includes closed positions, making mark coverage misleading
   Lens: observability-debt
   Severity: Low
   Path:
   - src/trade_trace/reports/pnl.py lines 32-37, 78-85
   Evidence:
   - marked = positions with unrealized_pnl is not None.
   - coverage = marked / len(rows), including closed positions.
   - Closed positions correctly have unrealized_pnl absent/None, so many fully valid closed positions lower “data_coverage”.
   Why this is maintenance debt:
   - The metric is described as positions_with_marks / total_positions, but as operational observability it conflates closed positions with unmarked open positions.
   - Agents may read low coverage as missing market marks even when all open positions are marked.
   Bounded remediation:
   - Either rename metric to mark_presence_across_all_positions, or compute open_mark_coverage = marked_open / open_count.
   - Add tests with closed-only, open-unmarked, and open-marked position sets.

Coverage accounting:
- Reviewed all 12 files under src/trade_trace/reports:
  - __init__.py
  - buckets.py
  - calibration.py
  - coach.py
  - decision_velocity.py
  - integrity.py
  - playbook_adherence.py
  - pnl.py
  - source_quality.py
  - tag_aggregates.py
  - unscored.py
  - watchlist.py
- Reviewed projections:
  - src/trade_trace/projections.py
- Reviewed exporter:
  - src/trade_trace/exporter.py
- Reviewed supporting report wiring/schema:
  - src/trade_trace/tools/reports.py
  - src/trade_trace/contracts/report_filter.py
- Spot-checked related tests:
  - tests/integration/test_report_sample_warnings.py
  - tests/security/test_report_sql_filters.py
  - test file inventory under tests/integration/test_report_*.py and named related tests

Files created or modified:
- None.

Issues encountered:
- Working tree was dirty before review; I treated all files as read-only and made no changes.
- Some in-scope report files already had local modifications, so line references reflect the current workspace content at review time, not necessarily a clean checkout diff.