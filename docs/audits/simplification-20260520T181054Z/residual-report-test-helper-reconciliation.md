# Residual report/test-helper reconciliation — trade-trace-2drt

## Scope and method

Scope: reconcile SIMP20-014, SIMP20-015, SIMP20-016, SIMP20-027, and SIMP20-028 against the closed 2026-05-19 simplification backlog, specifically closed beads `trade-trace-qnxt`, `trade-trace-x0po`, `trade-trace-qs5v`, and epic `trade-trace-mea1`.

Method:
- Read `bd show` for `trade-trace-qs5v`, `trade-trace-qnxt`, `trade-trace-x0po`, and `trade-trace-mea1`.
- Read 2026-05-20 matrix and lane reports under `docs/audits/simplification-20260520T181054Z/`.
- Inspected current code in `src/trade_trace/tools/reports.py`, `src/trade_trace/tools/review_bundle.py`, `src/trade_trace/reports/`, `tests/conftest.py`, and test files.
- Ran static AST probes for repeated report-result envelopes and repeated test helper names.
- Ran targeted report validation and broad contracts/integration/golden validation.

No production or test refactor was performed in this bead. This artifact is findings only.

## Readbacks of closed 2026-05-19 beads

### `trade-trace-qnxt` — SIMP-006 report-row/result helpers

Claimed target: extract small shared report-row and result helpers where semantics already match, bounded to scored-row loading, small result construction, and predicate helpers; avoid a broad report hierarchy.

Close reason readback: three helpers were extracted in `calibration.py` and consumed by `compare.py`: `_scored_row_base_where`, `_apply_scored_row_filters`, and `_materialize_scored_row`. Duplicated scored-row SQL/materialization was removed; 1097 tests, mypy, and ruff were reported clean.

Reconciliation: the close evidence satisfies the scored-row portion of the bead. It did not materially address broader report-result envelope construction across report modules, despite the original evidence also mentioning repeated `ReportResult` summary/group envelope shapes. Current code still has 10 standard report-result dict constructions across report modules.

### `trade-trace-x0po` — SIMP-007 report filter support declarations

Claimed target: co-locate or auto-register report filter support declarations to reduce drift, especially repeated report-name strings and supported-filter alignment.

Close reason readback: `process_filter()` was added; 9 reports collapsed enforce+view into one call; calibration and compare gained `REPORT_NAME` constants; 1076 tests, mypy, and ruff were reported clean.

Reconciliation: the report-module filter support simplification landed. A separate residual remains at the tool adapter layer: `review.bundle` still hand-converts `UnsupportedFilterError` differently from `tools/reports.py` and omits `field`/`supported_filter_paths` details. That residual was not the primary x0po target and should not reopen x0po; it is a narrow follow-up if desired.

### `trade-trace-qs5v` — SIMP-008 test home/MCP/CLI fixtures

Claimed target: centralize repeated initialized-home and MCP/CLI helpers without reducing isolation.

Close reason readback: shared `initialized_home` fixture landed in `tests/conftest.py`; 20 test files migrated to a one-line alias; per-test isolation preserved by `tmp_path`; 1076 tests and ruff were reported clean.

Reconciliation: the close evidence is accurate for the shared fixture substrate and the first migration wave. Current suite still has local compatibility aliases and helper duplication. Static AST scan currently finds `def home` in 37 files, `def _mcp` in 21 files, `def _envelope` in 11 files, `def _db` in 8 files, and `def _env` in 4 files. That is residual test drag beyond the original landing, but some aliases are intentionally left for readability/compatibility and some helpers are contract examples. Do not reopen qs5v; create one narrow follow-up only after grouping exact duplicate bodies.

### `trade-trace-mea1` — 2026-05-19 exhaustive simplification epic

Claimed target: exhaustive repo simplification backlog with behavior-preserving rule; deferred/rejected rows remain non-materialized unless a future explicit decision changes disposition.

Close reason readback: all 16 materialized simplification rows plus 4 QC gates and final verification closed.

Reconciliation: the epic can remain closed. The 2026-05-20 residual rows are not proof that mea1 closure was invalid; they are second-pass residuals/overlaps. Route any work through new narrow follow-ups rather than reopening the closed epic.

## Residual report adapter/envelope/filter findings and decision

### SIMP20-014 — report tool adapter boilerplate

Current evidence:
- `src/trade_trace/tools/reports.py` still contains repeated lifecycle and error-conversion code across report handlers:
  - `open_db_for_args(args)`
  - `try/finally db.close()`
  - `ValidationError` -> `ToolError(ErrorCode.VALIDATION_ERROR, details={"field": "filter", "validation_errors": ...})`
  - `UnsupportedFilterError` -> `_unsupported_filter_to_tool_error()`
  - `_propagate_report_meta(ctx, data)`
- Existing partial helper: `_make_filter_only_report(fn)` handles filter-only report wrappers, but many non-filter-only reports still repeat the same adapter shell.

Decision: create a new narrow follow-up, not reopen `trade-trace-qnxt`. `qnxt` completed scored-row extraction and did not claim to finish generic report tool adapter consolidation. This residual is real but must preserve report-specific validation/error details.

### SIMP20-015 — report envelope construction

Current evidence:
- AST probe found standard dicts containing all of `summary`, `groups`, `truncated`, and `next_cursor` in:
  - `src/trade_trace/reports/playbook_adherence.py` (1)
  - `src/trade_trace/reports/calibration.py` (1)
  - `src/trade_trace/reports/risk.py` (1)
  - `src/trade_trace/reports/unscored.py` (1)
  - `src/trade_trace/reports/compare.py` (2)
  - `src/trade_trace/reports/pnl.py` (1)
  - `src/trade_trace/reports/opportunity.py` (1)
  - `src/trade_trace/reports/watchlist.py` (1)
  - `src/trade_trace/reports/decision_velocity.py` (1)
  - `src/trade_trace/reports/tag_aggregates.py` (1)
- This is broader than the scored-row helper work closed in `qnxt`.

Decision: create a new narrow follow-up, optionally combined with SIMP20-014 as a report helper cleanup. Do not reopen `trade-trace-qnxt`; its completed helper extraction was legitimate and behavior-preserving, but not exhaustive for envelope boilerplate.

### SIMP20-016 — report filter validation/support drift with `review.bundle`

Current evidence:
- `src/trade_trace/tools/reports.py:_unsupported_filter_to_tool_error()` emits details including `field`, `report`, `unsupported_filter_paths`, and `supported_filter_paths`.
- `src/trade_trace/tools/review_bundle.py` lines 440-460 locally validates `ReportFilter`, calls `enforce_supported_filter()`, and maps `UnsupportedFilterError` to a `ToolError` with only `report` and `unsupported_filter_paths` in details.
- `review.bundle` then derives `filter_view` via `applied_filter_view()` rather than `process_filter()`.

Decision: create a new narrow follow-up only for tool-layer filter error conversion parity between report tools and `review.bundle`. Do not reopen `trade-trace-x0po`; x0po simplified report-module filter support and name pinning, while this residual is a distinct tool-adapter contract surface. Before changing it, add/confirm explicit tests for the current `review.bundle` unsupported-filter error shape because changing details may be agent-visible.

## Residual test-helper duplication findings and decision

### SIMP20-027 — residual per-file `home` alias fixtures

Current evidence from AST probe:
- `def home`: 37 definitions across 37 files.
- Representative files include `tests/contracts/test_event_enum_coverage.py`, `tests/contracts/test_report_envelope_completeness.py`, `tests/contracts/test_agent_ergonomics.py`, `tests/golden/test_cli_mcp_parity.py`, `tests/integration/test_admin_tools.py`, `tests/integration/test_fixture_seed.py`, and multiple report/memory/playbook integration tests.
- Many current files already document that `initialized_home` is shared by `tests/conftest.py` from `trade-trace-qs5v / SIMP-008`, which confirms these are residual compatibility aliases rather than missing substrate.

Decision: create a new narrow follow-up only after mechanically classifying local `home` fixtures into pure aliases, old exact init clones, and intentional custom homes. Do not reopen `trade-trace-qs5v`; it landed the fixture and migrated 20 files as claimed. Treat pure aliases as residual no-op/readability debt unless a follow-up chooses direct `initialized_home` use.

### SIMP20-028 — repeated MCP/envelope/db dispatch helpers

Current evidence from AST probe:
- `def _mcp`: 21 files.
- `def _envelope`: 11 files.
- `def _db`: 8 files.
- `def _env`: 4 files.
- Representative `_mcp` helpers inject `home`, call `mcp_call`, and often pin `actor_id="agent:default"`.
- Representative `_envelope` / `_env` helpers call `.model_dump(mode="json", exclude_none=True)` around MCP/dispatch results.
- `_db` helpers often open SQLite directly for schema/storage tests and may be intentionally explicit.

Decision: create one new narrow follow-up for exact duplicate MCP/envelope helper shapes in integration/security tests. Reject/defer a blanket `_db` helper consolidation: direct DB helpers in schema/storage tests are intentional assertion scaffolding and should stay explicit unless a future mechanical grouping proves exact duplicates. Do not reopen `trade-trace-qs5v`, whose scope was initialized-home fixture centralization plus first-wave migrations.

## Proposed downstream bead/follow-up 1

Title: SIMP20 residual reports: centralize report tool adapter shell and standard report result envelopes without changing report contracts

File/helper cluster list:
- `src/trade_trace/tools/reports.py`
  - `_report_calibration`
  - `_report_playbook_adherence`
  - `_report_unscored_forecasts`
  - `_report_decision_velocity`
  - `_report_compare`
  - `_report_strategy_performance`
  - `_report_opportunity`
  - `_report_watchlist`
  - `_report_coach`
  - existing `_make_filter_only_report`
  - `_unsupported_filter_to_tool_error`
  - `_propagate_report_meta`
- `src/trade_trace/reports/` standard envelope builders in:
  - `playbook_adherence.py`
  - `calibration.py`
  - `risk.py`
  - `unscored.py`
  - `compare.py`
  - `pnl.py`
  - `opportunity.py`
  - `watchlist.py`
  - `decision_velocity.py`
  - `tag_aggregates.py`

Acceptance criteria:
- Introduce only small private helpers; no report class hierarchy or public API change.
- Preserve exact tool names, report schemas, return keys, insertion-order-sensitive envelopes, `ctx.meta_hints`, error codes, error messages, and details.
- Preserve report-specific validation handling for `bucket`, `mode`, `stale_threshold_days`, `compare`/`strategy_performance`/`opportunity` `ValueError`, `TradingAdvicePhraseError`, and calibration integrity diagnostics.
- Representative pre/post report JSON for calibration, compare, and one non-scored report remains field-compatible.
- No changes to analytics calculations, SQL predicates, filter semantics, sample warning behavior, or pagination fields.

Validation commands:
- `./.venv/bin/python -m pytest tests/contracts/test_report_envelope_completeness.py tests/integration/test_report_filter.py tests/security/test_report_sql_filters.py tests/integration/test_review_bundle_contract.py -q`
- `./.venv/bin/python -m pytest tests/integration/test_report_calibration.py tests/integration/test_report_compare.py tests/integration/test_report_opportunity.py tests/integration/test_report_coach.py tests/integration/test_report_unscored_velocity.py tests/integration/test_report_pnl_watchlist.py tests/integration/test_report_risk.py tests/integration/test_report_tag_aggregates.py tests/integration/test_report_sample_warnings.py -q`
- `./.venv/bin/python -m ruff check src/trade_trace/tools/reports.py src/trade_trace/reports tests/contracts/test_report_envelope_completeness.py tests/integration/test_report_filter.py tests/security/test_report_sql_filters.py tests/integration/test_review_bundle_contract.py`

## Proposed downstream bead/follow-up 2

Title: SIMP20 residual review.bundle/report filter parity: share tool-layer ReportFilter validation and unsupported-filter error conversion

File/helper cluster list:
- `src/trade_trace/tools/reports.py:_unsupported_filter_to_tool_error`
- `src/trade_trace/tools/review_bundle.py:_review_bundle_handler`
- Possible new private helper in `src/trade_trace/tools/_report_filter_helpers.py` or adjacent reports/review-bundle tool helper module.
- Tests in `tests/integration/test_review_bundle_contract.py`, `tests/integration/test_report_filter.py`, and `tests/security/test_report_sql_filters.py`.

Acceptance criteria:
- Characterize current `review.bundle` unsupported-filter error details before changing them.
- If parity is chosen, use a shared tool-layer conversion while preserving `ErrorCode.VALIDATION_ERROR`, `field="filter"` for validation failures, report name, unsupported paths, and supported path listing where compatibility allows.
- Preserve `REVIEW_BUNDLE_REPORT` supported-field subset and `review.bundle` hash/order/redaction behavior.
- Do not change report-module `process_filter()` semantics.

Validation commands:
- `./.venv/bin/python -m pytest tests/integration/test_review_bundle_contract.py tests/integration/test_report_filter.py tests/security/test_report_sql_filters.py -q`
- `./.venv/bin/python -m ruff check src/trade_trace/tools/reports.py src/trade_trace/tools/review_bundle.py tests/integration/test_review_bundle_contract.py tests/integration/test_report_filter.py tests/security/test_report_sql_filters.py`

## Proposed downstream bead/follow-up 3

Title: SIMP20 residual test helpers: classify and migrate exact duplicate initialized-home/MCP/envelope helpers while preserving isolation

File/helper cluster list:
- Shared substrate: `tests/conftest.py`, possible `tests/_mcp_helpers.py`.
- `home` fixture files: 37 files found by AST, including contracts, golden, integration, and security tests.
- `_mcp` helper files: 21 files.
- `_envelope` helper files: 11 files.
- `_env` helper files: 4 files.
- `_db` helper files: 8 files, but default disposition is defer/intentional unless exact duplicates are proven.

Acceptance criteria:
- Produce a mechanical grouping list before edits: pure `home(initialized_home)` aliases, old exact `tmp_path / "home" + journal.init` clones, custom homes, exact `_mcp` bodies, exact envelope/model_dump bodies, intentional DB helpers.
- Migrate only exact duplicate aliases/helpers in the first pass.
- Preserve per-test isolation via `tmp_path` and `initialized_home`.
- Preserve actor defaults, envelope JSON shape, `exclude_none=True`, no-network/security fixture boundaries, and local helper readability in docs-like contract/golden examples where intentional.
- Leave direct DB helpers in schema/storage tests unless a later narrow decision proves safe consolidation.

Validation commands:
- `./.venv/bin/python -m pytest tests/contracts tests/integration tests/golden -q`
- `./.venv/bin/python -m pytest tests/security -q` if security helpers are touched.
- `./.venv/bin/python -m ruff check tests/conftest.py tests`

## Validation run for this reconciliation

Commands run in this bead:
- `./.venv/bin/python -m pytest tests/contracts/test_report_envelope_completeness.py tests/integration/test_report_filter.py tests/security/test_report_sql_filters.py tests/integration/test_review_bundle_contract.py -q`
  - Result: 83 passed in 1.09s.
- `./.venv/bin/python -m pytest tests/contracts tests/integration tests/golden -q`
  - Result: 1050 passed, 6 skipped in 27.75s.
- Static AST probe for report result dicts.
  - Result: 10 report modules/11 dicts with the standard result envelope shape.
- Static AST probe for test helper names.
  - Result: `home=37`, `_mcp=21`, `_envelope=11`, `_db=8`, `_env=4`.

## Final classification

- SIMP20-014: create new narrow follow-up; not covered by qnxt close, not a qnxt reopen.
- SIMP20-015: create new narrow follow-up; qnxt completed scored-row helper work but did not exhaust envelope repetition.
- SIMP20-016: create new narrow follow-up focused on `review.bundle`/report-tool error conversion parity; not an x0po reopen.
- SIMP20-027: create new narrow test-helper follow-up after grouping; treat pure aliases as low-risk residuals, not qs5v reopen.
- SIMP20-028: create new narrow test-helper follow-up for exact MCP/envelope duplicates; defer/reject blanket `_db` consolidation as intentional test assertion scaffolding unless proven otherwise.

No production/test refactor was performed in this bead.
