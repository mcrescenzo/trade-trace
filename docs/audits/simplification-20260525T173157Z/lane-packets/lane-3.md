## What I did

- Performed a read-only simplification review of the assigned `reports-reporting` domain under `/home/hermes/code/trade-trace`.
- Verified repository commit/worktree state:
  - HEAD: `d37136e9684138d9f9540f2a71860f36eba354f5`
  - No file edits made.
- Inspected:
  - `src/trade_trace/reports/**`
  - `src/trade_trace/reporting/**`
  - Relevant test references for report handlers, read-model pagination, open/current exposure, and registration/schema parity.
- Focused on additive, behavior-preserving simplification candidates only, avoiding prior/known coverage such as:
  - report-row/result helpers
  - ReportFilter support declarations
  - report adapter shell / standard envelope residuals
  - report filter parity
  - source_quality/calibration truncation fixes
  - report.coach group extraction
  - watchlist `as_of` capture
  - low-level report metric semantics
  - open period/process analytics issues `trade-trace-2vq5` and `trade-trace-4exy`

## Coverage accounting

### Files / areas inspected

- `src/trade_trace/reports/tool_handlers/registration.py`
  - ~595 lines, central report tool registration surface.
- `src/trade_trace/reports/tool_handlers/common.py`
  - Shared report handler helpers, envelope/meta propagation, filter-only report wrapper.
- `src/trade_trace/reports/tool_handlers/portfolio_exposure.py`
  - Open positions/current exposure/exposure anomaly handlers and helper logic.
- `src/trade_trace/reporting/pagination.py`
  - Existing generic and composite cursor pagination helpers.
- `src/trade_trace/reporting/position_rows.py`
  - Position read-model query/filter/pagination path.
- `src/trade_trace/reporting/trade_rows.py`
  - Trade read-model query/filter/pagination path.
- `src/trade_trace/timestamps.py`
  - Existing canonical UTC timestamp normalization utilities.
- Targeted searches across `src/trade_trace/reports/**`, `src/trade_trace/reporting/**`, and relevant tests for:
  - duplicated timestamp parsing
  - pagination/cursor handling
  - report registration metadata
  - open/current exposure behavior
  - schema/runtime parity coverage

### Tests identified as relevant validation handles

- `tests/integration/test_reporting_read_model.py`
- `tests/contracts/test_reporting_pagination.py`
- `tests/integration/test_reporting_pagination_perf_baseline.py`
- `tests/integration/test_report_open_positions.py`
- `tests/integration/test_report_current_exposure.py`
- `tests/integration/test_open_trades_agent_surface.py`
- `tests/contracts/test_tool_schema_runtime_parity.py`
- `tests/contracts/test_report_envelope_completeness.py`

No tests were run because this lane was read-only review; validation commands are provided per candidate.

---

# Candidate records

## Candidate RPT-SIMP-A: Data-driven report tool registration descriptors

### id

`RPT-SIMP-A`

### title

Convert repeated `registry.register(...)` blocks in `register_report_tools` into a small descriptor table plus loop.

### complexity class

Mechanical duplication / registration metadata sprawl.

### evidence

Observed in `src/trade_trace/reports/tool_handlers/registration.py`:

- `register_report_tools` is a single ~560-line function inside a 595-line file.
- It contains many consecutive `registry.register(...)` calls with the same structural fields:
  - tool name
  - handler
  - description
  - `example_minimal`
  - `example_rich`
  - `optional_keys`
  - `json_schema`
  - `usage_summary`
  - `examples`
  - `enum_notes`
  - `common_failures`
  - `next_actions`
- Examples:
  - `report.bootstrap` and `agent.bootstrap` duplicate nearly identical metadata at lines 39-105.
  - Many report registrations differ only by name/handler/description/schema/optional keys.
- Existing tests already check registration/schema discoverability:
  - `tests/contracts/test_tool_schema_runtime_parity.py`
  - `tests/contracts/test_report_envelope_completeness.py`
  - report-specific integration tests inspect registration descriptions and metadata.

### observed facts

- `register_report_tools` is structurally repetitive, not merely long.
- Tool metadata is contractually important and tested.
- Current implementation makes small registration metadata changes high-churn and review-heavy.

### inferences

- A descriptor table would reduce accidental complexity without changing behavior if it preserves registration order and exact argument values.
- A dataclass or typed dict such as `ReportToolRegistration` can centralize default handling while keeping metadata explicit.

### assumptions

- `ToolRegistry.register` preserves registration semantics independent of whether calls are made directly or through a loop.
- No tests rely on source-code layout of `registration.py`; tests appear to inspect runtime registry behavior.

### open questions

- Does any documentation generator scrape `registration.py` source text directly rather than using the registry? I did not see evidence in inspected tests, but this should be confirmed before implementation.

### behavior contract

Must preserve:

- Exact tool names.
- Exact handlers.
- Exact registration order, unless tests prove order is irrelevant.
- Exact metadata values:
  - descriptions
  - examples
  - optional keys
  - JSON schemas
  - usage summaries
  - common failures
  - next actions
  - enum notes
- Runtime output of all report handlers.

### cost

Medium.

Likely implementation shape:

- Introduce a local dataclass/typed dict in `registration.py`, e.g. `_ToolSpec`.
- Build `_REPORT_TOOL_SPECS: tuple[_ToolSpec, ...]`.
- `register_report_tools` loops over specs and calls `registry.register(spec.name, spec.handler, **spec.kwargs)`.
- Optionally keep special comments/group separators around descriptor groups.

### benefit

- Reduces one large procedural registration function into auditable declarative metadata.
- Makes schema/runtime parity failures easier to trace to one descriptor entry.
- Lowers risk of omitting `json_schema`/`optional_keys` during future report additions.
- Makes duplicate aliases such as `report.bootstrap` / `agent.bootstrap` easier to compare.

### refactor shape

Additive/mechanical:

1. Create an internal descriptor type.
2. Move existing literal registration arguments into descriptors.
3. Replace repeated calls with a loop.
4. Preserve imports and exported names.
5. Avoid changing handler implementations.

### non-goals

- Do not rename tools.
- Do not change descriptions for style.
- Do not change schema definitions.
- Do not split registration into multiple modules unless a separate need appears.
- Do not alter report behavior/envelopes.

### behavior-preservation plan

- Snapshot registry metadata before/after for all `report.*`, `agent.*`, and `replay.*` tools.
- Compare:
  - names
  - handler callables
  - optional keys
  - schemas
  - examples
  - descriptions
  - usage metadata
- Run existing contract/integration tests.

### validation command/gap

Suggested validation:

```bash
pytest \
  tests/contracts/test_tool_schema_runtime_parity.py \
  tests/contracts/test_report_envelope_completeness.py \
  tests/integration/test_report_open_positions.py \
  tests/integration/test_report_current_exposure.py \
  tests/integration/test_open_trades_agent_surface.py
```

Additional gap to close during implementation:

- Add or extend a focused test that serializes registry metadata for all report tools and asserts unchanged key fields if not already fully covered.

### size/risk/priority/confidence

- Size: Medium
- Risk: Medium-low
- Priority: Medium
- Confidence: High

### why-not-style

This is not merely style or LOC reduction. The current registration surface is a contract-bearing metadata registry, and duplicated procedural calls create real omission/drift risk for schemas, optional keys, examples, and discoverability metadata.

### intentional complexity check

Some verbosity is intentional because tool metadata is user-facing and safety-relevant. The candidate preserves explicit metadata; it only removes repeated registration boilerplate.

### duplicate/overlap notes

- Related to known static hotspot `registration.py register_report_tools is ~560 lines`.
- Not duplicating prior “report tool adapter shell and standard envelopes” coverage; this is specifically registration metadata declaration, not handler/envelope mechanics.

### proposed bead body/acceptance

Proposed bead title:

> Simplify report tool registration with declarative descriptors

Proposed bead body:

> `src/trade_trace/reports/tool_handlers/registration.py` currently registers every report/agent/replay tool through repeated `registry.register(...)` calls in one large function. Convert the repeated registration metadata into an internal descriptor table and loop while preserving exact runtime registry behavior, metadata, schemas, handlers, and order. This is a mechanical simplification only; no report behavior or schema semantics should change.

Acceptance criteria:

- All existing report/agent/replay tools are registered with the same names, handlers, JSON schemas, optional keys, examples, descriptions, usage summaries, failure notes, and next actions as before.
- Registration order is preserved unless proven irrelevant by tests.
- Existing schema/runtime parity and report envelope tests pass.
- Add or update a focused regression test comparing registry metadata for representative descriptor fields.
- No report output/envelope behavior changes.

### coordinator disposition recommendation

Recommend backlog as additive simplification candidate.

---

## Candidate RPT-SIMP-B: Reuse composite pagination helper in trade/position read-models

### id

`RPT-SIMP-B`

### title

Unify duplicated `(created_at/opened_at, id)` cursor pagination in `list_trades` and `list_positions` using a shared composite keyset helper.

### complexity class

Duplicated query-tail / cursor pagination mechanics.

### evidence

Existing generic helper:

- `src/trade_trace/reporting/pagination.py`
  - `paginate_created_at_id_query(...)` implements newest-first composite keyset pagination over `(created_at, id)`.
  - Lines 136-179 encode/decode `[created_at, id]`, clamp limit, append keyset predicate, order, and compute `next_cursor`.

Duplicated local logic:

- `src/trade_trace/reporting/trade_rows.py`
  - `list_trades` manually clamps `limit`, decodes cursor, appends:
    - `AND (d.created_at < ? OR (d.created_at = ? AND d.id < ?))`
    - `ORDER BY d.created_at DESC, d.id DESC LIMIT ?`
  - Encodes cursor as `[last_row[2], last_row[0]]`.
- `src/trade_trace/reporting/position_rows.py`
  - `list_positions` manually clamps `limit`, decodes cursor, appends:
    - `AND (p.opened_at < ? OR (p.opened_at = ? AND p.id < ?))`
    - `ORDER BY p.opened_at DESC, p.id DESC LIMIT ?`
  - Encodes cursor as `[last.opened_at, last.position_id]`.

Relevant tests:

- `tests/contracts/test_reporting_pagination.py`
- `tests/integration/test_reporting_read_model.py`
- `tests/integration/test_reporting_pagination_perf_baseline.py`

### observed facts

- The shared helper exists but is not used by these two higher-level read models.
- The helper currently hardcodes unqualified `created_at` and `id` column names, while callers need aliases:
  - `d.created_at`, `d.id`
  - `p.opened_at`, `p.id`
- The helper already covers the same core behavior: composite cursor, descending timestamp/id order, limit+1, next cursor.

### inferences

- The helper could be generalized with optional parameters:
  - `created_at_column`
  - `id_column`
  - `order_created_at_column`
  - `order_id_column`
  - or a more neutral `timestamp_column` / `id_column`
- `list_trades` and `list_positions` could delegate pagination tail construction while retaining their row mapping and filter construction.

### assumptions

- The helper can be extended without breaking existing callers/tests by keeping defaults as `created_at` and `id`.
- SQL strings passed to the helper can safely receive additional predicates after existing `WHERE`/`AND` clauses if connector handling remains intact.

### open questions

- Should the helper remain specifically named `paginate_created_at_id_query` or be generalized to `paginate_timestamp_id_query` while preserving the old name as an alias?
- Should it support `opened_at` directly or keep the semantic term `created_at` but allow custom column names?

### behavior contract

Must preserve:

- Cursor encoding shape: base64url JSON `{"after": [timestamp, id]}`.
- Accepted legacy scalar cursor fallback in `list_trades` and `list_positions`:
  - Both currently tolerate non-list cursor payloads by treating `after_id = ""`.
- Limit clamping behavior:
  - `limit < 1` maps to `DEFAULT_LIMIT` in `list_trades`/`list_positions`, while `pagination.py` helper clamps to at least `1`.
  - This difference must be preserved or explicitly covered by tests before changing.
- Query ordering:
  - `d.created_at DESC, d.id DESC`
  - `p.opened_at DESC, p.id DESC`
- Performance characteristics for deep cursor walks.

### cost

Small to medium.

Potentially simple if the helper grows alias parameters and caller-specific limit normalization remains outside the helper.

### benefit

- Removes duplicated and easy-to-get-wrong cursor decode/order/limit logic.
- Consolidates composite cursor behavior in one tested place.
- Makes future read-models less likely to reimplement keyset pagination inconsistently.
- Keeps performance-sensitive pagination behavior centralized.

### refactor shape

1. Extend `paginate_created_at_id_query` with optional parameters while preserving defaults:
   - predicate timestamp column
   - predicate id column
   - order timestamp column
   - order id column
   - selected row timestamp index
   - selected row id index
   - optional legacy scalar cursor fallback behavior, if needed.
2. Update `list_trades` to build filters only, then call helper.
3. Update `list_positions` similarly.
4. Keep row conversion after pagination.
5. Preserve current limit semantics explicitly in callers.

### non-goals

- Do not change read-model API.
- Do not change cursor format.
- Do not replace keyset pagination with offset pagination.
- Do not change SQL joins or selected columns.
- Do not alter performance budgets.

### behavior-preservation plan

- Add focused tests for:
  - scalar legacy cursor behavior if still contractually needed.
  - duplicate timestamps with stable full walk.
  - `limit < 1`, `limit > MAX_LIMIT`.
  - aliased timestamp/id columns.
- Run existing read-model and perf baseline tests.

### validation command/gap

Suggested validation:

```bash
pytest \
  tests/contracts/test_reporting_pagination.py \
  tests/integration/test_reporting_read_model.py \
  tests/integration/test_reporting_pagination_perf_baseline.py
```

Potential additional validation:

```bash
pytest tests/integration/test_report_open_positions.py tests/integration/test_report_current_exposure.py
```

because `report.open_positions` uses `list_positions`.

### size/risk/priority/confidence

- Size: Small-medium
- Risk: Medium
- Priority: Medium
- Confidence: High

### why-not-style

This is not style-only. Cursor pagination is correctness- and performance-sensitive. Duplicated composite cursor logic can produce skips/repeats under duplicate timestamps if one implementation drifts.

### intentional complexity check

Some query-local complexity is justified because `list_trades` and `list_positions` have different filters and selected columns. The candidate targets only the repeated pagination tail, not the domain-specific filtering or row mapping.

### duplicate/overlap notes

- Not duplicating prior report-row/result helper coverage; this targets reporting read-model pagination mechanics.
- Related to known hotspot `reporting/position_rows.py` but grounded in duplicated behavior, not LOC alone.

### proposed bead body/acceptance

Proposed bead title:

> Reuse shared composite pagination helper for trade and position read-models

Proposed bead body:

> `list_trades` and `list_positions` each manually implement newest-first composite cursor pagination despite `reporting.pagination.paginate_created_at_id_query` already providing the same core behavior. Extend the shared helper to support aliased/custom timestamp/id columns while preserving current cursor format, ordering, limit behavior, and performance, then delegate the duplicated pagination tail from the read-models.

Acceptance criteria:

- `list_trades` and `list_positions` preserve existing public behavior and cursor format.
- Duplicate timestamp walks remain stable with no skipped/repeated rows.
- `report.open_positions` behavior remains unchanged.
- Existing pagination contract, read-model, open/current exposure, and perf baseline tests pass.
- The shared helper remains backward compatible for existing direct callers.

### coordinator disposition recommendation

Recommend backlog as additive simplification candidate.

---

## Candidate RPT-SIMP-C: Shared `as_of` / stale-threshold argument parsing for exposure report handlers

### id

`RPT-SIMP-C`

### title

Extract common `as_of` and `stale_mark_threshold_days` validation in `portfolio_exposure` handlers.

### complexity class

Repeated validation / handler argument normalization.

### evidence

In `src/trade_trace/reports/tool_handlers/portfolio_exposure.py`:

- `_report_open_positions` lines 79-97:
  - reads `stale_mark_threshold_days`
  - validates integer and non-negative
  - parses `as_of`
  - defaults to `datetime.now(UTC)`
  - computes stale cutoff
- `_report_exposure_anomalies` lines 185-203:
  - repeats the same `stale_mark_threshold_days` validation
  - repeats the same `as_of` parsing/defaulting
  - computes stale cutoff
- `_report_current_exposure` then calls both lower-level handlers:
  - lines 600-603 build `open_args` and `anomaly_args`
  - each lower-level handler independently parses the same `as_of`/threshold fields.
- Existing shared helper available:
  - `tool_handlers/common.py` has `_parse_report_timestamp`.
  - `timestamps.py` has `to_utc_iso8601`.

### observed facts

- The duplicated code is not just cosmetic; it is validation behavior for user-facing tool arguments.
- `current_exposure` composes lower-level reports and may parse the same temporal inputs multiple times.
- Similar error envelopes/details should remain consistent.

### inferences

- A small internal helper could return a normalized bundle:
  - `as_of: datetime`
  - `as_of_iso: str`
  - `stale_mark_threshold_days: int`
  - `stale_cutoff: datetime`
- Both handlers would use it, reducing drift risk.
- `current_exposure` could optionally call the helper once for its summary filter normalization, while still delegating to lower-level reports.

### assumptions

- The exact error messages/details are part of tests or user contracts and should be preserved.
- Defaulting to `datetime.now(UTC)` rather than injected `now_iso()` is intentional for these handlers unless separately changed; this candidate should not alter it.

### open questions

- Should `current_exposure.summary.filter.as_of` continue echoing raw `args.get("as_of")` as currently done at line 648, or should it echo normalized `to_utc_iso8601(as_of)` like lower-level reports? Changing this may be behavior-affecting and should not be included unless tests/contract say so.

### behavior contract

Must preserve:

- Error code: `VALIDATION_ERROR`.
- Error messages:
  - `"stale_mark_threshold_days must be a non-negative integer"`
  - `"as_of must be an ISO timestamp string"`
- Error details shape:
  - `{"field": ..., "value": ...}`
- Default threshold: `14`.
- Default `as_of`: current UTC wall-clock behavior.
- Stale cutoff semantics.
- Lower-level report summaries and caveat behavior.

### cost

Small.

### benefit

- Reduces validation drift across related exposure handlers.
- Makes future threshold/as-of changes localized.
- Improves readability in `portfolio_exposure.py` without changing report semantics.

### refactor shape

1. Add private helper in `portfolio_exposure.py`, e.g.:

   ```python
   def _exposure_temporal_args(args: dict[str, Any]) -> ExposureTemporalArgs:
       ...
   ```

2. Use it in:
   - `_report_open_positions`
   - `_report_exposure_anomalies`
3. Optionally use it in `_report_current_exposure` only for local summary normalization if behavior is explicitly preserved.

### non-goals

- Do not change default clock source.
- Do not change normalized vs raw `as_of` echo semantics unless separately specified.
- Do not modify anomaly detection logic.
- Do not modify open-position payloads.

### behavior-preservation plan

- Unit-test helper indirectly through existing tool handlers.
- Add focused validation tests only if current coverage is incomplete:
  - invalid threshold type
  - negative threshold
  - non-string `as_of`
  - invalid timestamp string
  - default threshold
- Run open/current exposure tests.

### validation command/gap

Suggested validation:

```bash
pytest \
  tests/integration/test_report_open_positions.py \
  tests/integration/test_report_current_exposure.py \
  tests/integration/test_open_trades_agent_surface.py \
  tests/contracts/test_report_envelope_completeness.py
```

Potential gap:

- If no test asserts invalid `as_of`/threshold error details for both handlers, add small contract tests before/with refactor.

### size/risk/priority/confidence

- Size: Small
- Risk: Low
- Priority: Low-medium
- Confidence: High

### why-not-style

The repeated code validates public tool inputs and determines stale mark caveats. Centralizing it reduces the risk of inconsistent validation/error behavior across reports.

### intentional complexity check

Exposure handlers are intentionally explicit because they are safety/user-facing. The helper should stay narrow and local to exposure temporal arguments rather than introducing a broad generic argument parser.

### duplicate/overlap notes

- Not duplicating report adapter shell/envelope simplification.
- Not changing report metric semantics.
- Related to known hotspot `portfolio_exposure.py`, but candidate is behavior-specific and local.

### proposed bead body/acceptance

Proposed bead title:

> Extract shared exposure report temporal argument parsing

Proposed bead body:

> `_report_open_positions` and `_report_exposure_anomalies` duplicate validation/defaulting for `stale_mark_threshold_days` and `as_of`, including error envelopes and stale cutoff derivation. Extract a narrow private helper in `portfolio_exposure.py` and use it from both handlers while preserving exact validation errors, defaults, normalized timestamp behavior, and report outputs.

Acceptance criteria:

- Existing open/current exposure outputs remain unchanged.
- Invalid `as_of` and invalid `stale_mark_threshold_days` still return the same `VALIDATION_ERROR` messages/details.
- Default threshold remains `14`.
- Existing open/current exposure and envelope tests pass.
- No anomaly/open-position business logic changes.

### coordinator disposition recommendation

Recommend backlog as small additive simplification candidate.

---

## Candidate RPT-SIMP-D: Add a report-facing timestamp parse helper instead of repeated local `_parse_ts`

### id

`RPT-SIMP-D`

### title

Provide a shared report timestamp-to-`datetime` helper that preserves existing report semantics.

### complexity class

Repeated timestamp parsing / normalization edge-case drift.

### evidence

Search found multiple report modules parsing timestamps independently:

- `src/trade_trace/reports/pm_native.py`
  - `_parse_ts(value: str | None) -> datetime | None`
  - uses `datetime.fromisoformat(str(value).replace("Z", "+00:00"))`
  - returns `None` on `ValueError`.
- `src/trade_trace/reports/opportunity.py`
  - local `_parse_ts`.
- `src/trade_trace/reports/lifecycle.py`
  - local `_parse_ts`, with comment:
    - “Match strategy_health._parse_ts”
    - normalizes naive timestamps to UTC for historical behavior.
- `src/trade_trace/reports/decision_velocity.py`
  - directly parses `created_at` with `datetime.fromisoformat(...).astimezone(UTC)`.
- `src/trade_trace/reports/source_quality.py`
  - normalizes through `to_utc_iso8601`, then immediately reparses with `datetime.fromisoformat(...replace("Z", "+00:00"))`.

Existing central utility:

- `src/trade_trace/timestamps.py`
  - `to_utc_iso8601(...)` validates and normalizes to canonical UTC strings.
  - Does not expose a general “parse to UTC datetime” helper.

### observed facts

- There are multiple report-local timestamp parsing variants.
- Some tolerate invalid values by returning `None`; others raise.
- Some preserve historical naive-as-UTC behavior; `to_utc_iso8601` rejects naive timestamps.
- Therefore this cannot be a blind replacement with `to_utc_iso8601`.

### inferences

- A shared helper must support explicit modes to preserve behavior, e.g.:
  - strict vs optional
  - naive policy: reject vs assume UTC
  - invalid policy: raise vs return `None`
- The first implementation should migrate only one or two modules with matching semantics to avoid broad behavior risk.

### assumptions

- Report read paths may encounter historical journal rows with non-canonical/naive timestamps, so strict write-path normalization rules cannot simply be imposed on all reports.
- Existing comments in `lifecycle.py` indicate some naive handling is intentionally locked by prior bugfix/compatibility work.

### open questions

- Which report modules have tests that lock invalid timestamp behavior?
- Should the helper live in `trade_trace.reports._time`, `trade_trace.reports._timestamps`, or `trade_trace.timestamps`?
  - Because behavior may be report/read-path specific, a report-local helper module may be safer.

### behavior contract

Must preserve per-call-site behavior:

- Whether invalid input raises or returns `None`.
- Whether naive timestamps are rejected or assumed UTC.
- Whether output is timezone-aware UTC.
- Whether canonical string truncation to milliseconds is involved.
- Existing report output ordering/bucketing/staleness decisions.

### cost

Medium.

### benefit

- Reduces subtle timestamp parsing drift across reports.
- Makes historical compatibility choices explicit.
- Provides one place to document report/read-path timestamp parsing policy distinct from write-path timestamp validation.
- Reduces future bugs around `Z` replacement, naive values, and UTC conversion.

### refactor shape

Incremental/additive:

1. Add a small helper module, e.g. `src/trade_trace/reports/_time.py`.
2. Implement narrow functions such as:
   - `parse_report_datetime(value, *, field, naive="assume_utc"|"reject", invalid="raise"|"none")`
   - or simpler wrappers for current patterns.
3. Migrate the lowest-risk direct parse sites first, likely:
   - `decision_velocity.py`
   - `source_quality.py` reparse after `to_utc_iso8601`
4. Leave `lifecycle.py` until helper supports its explicitly documented behavior.
5. Add tests for helper modes before broad migration.

### non-goals

- Do not impose write-path strict timestamp validation on historical report reads.
- Do not change timestamp storage format.
- Do not change report bucketing/staleness semantics.
- Do not “fix” naive timestamp handling unless separately specified by tests/contracts.

### behavior-preservation plan

- Add helper tests that encode current local behaviors.
- Migrate one module at a time.
- Compare representative report outputs before/after on seeded fixtures.
- Run report-specific tests.

### validation command/gap

Suggested validation:

```bash
pytest \
  tests/integration/test_report_*.py \
  tests/integration/test_reporting_*.py \
  tests/contracts/test_report_envelope_completeness.py
```

More targeted depending on migrated modules:

```bash
pytest \
  tests/integration/test_source_quality.py \
  tests/integration/test_audit_readiness.py \
  tests/integration/test_pm_native_reports.py
```

Potential gap:

- Add direct helper tests for invalid/naive timestamp modes before relying on broad report tests.

### size/risk/priority/confidence

- Size: Medium
- Risk: Medium
- Priority: Low-medium
- Confidence: Medium

### why-not-style

Timestamp parsing affects report bucketing, stale-source detection, lifecycle overdue status, and point-in-time behavior. The value is reducing semantic drift and making compatibility policy explicit, not just deduplicating code.

### intentional complexity check

Timestamp handling has intentional complexity due to historical data compatibility and strict write-path contracts. This candidate should introduce explicit modes rather than a single oversimplified parser.

### duplicate/overlap notes

- This overlaps with the known static hotspot “many report modules parse timestamps separately,” but I did not see a prior closed simplification specifically covering a shared report read-path timestamp parser.
- Must avoid overlapping with prior source_quality/calibration truncation fixes by preserving current truncation behavior.

### proposed bead body/acceptance

Proposed bead title:

> Add shared report read-path timestamp parser with explicit compatibility modes

Proposed bead body:

> Several report modules parse ISO timestamps locally with subtly different behavior around `Z`, invalid values, timezone awareness, and historical naive timestamps. Add a narrow report read-path timestamp helper with explicit modes for invalid and naive values, then migrate only matching call sites incrementally. Preserve existing report outputs and historical compatibility behavior.

Acceptance criteria:

- New helper has focused tests for strict/optional invalid handling and naive timestamp policy.
- Migrated report modules preserve current behavior on existing fixtures.
- No change to write-path timestamp normalization contracts in `timestamps.py`.
- Relevant report integration/contract tests pass.
- Migration is incremental and avoids changing lifecycle/source-quality semantics unless tests lock equivalence.

### coordinator disposition recommendation

Recommend backlog as lower-priority additive simplification candidate, gated by focused tests because timestamp compatibility risk is non-trivial.

---

# Rejected / not recommended items

## Broad split of `portfolio_exposure.py`

- Reason rejected: LOC hotspot alone is insufficient. The file contains related exposure/open-position/anomaly/current-exposure behavior with safety-sensitive caveats. A broad split would be mostly organizational and risk churn without clear behavior-preserving simplification.
- Narrow candidate `RPT-SIMP-C` is preferable.

## Broad rewrite of report registration or schemas

- Reason rejected: User-facing descriptions and schema discoverability are contract-bearing. Candidate `RPT-SIMP-A` recommends a mechanical descriptor table only, not semantic edits.

## Low-level metric/report semantics cleanup

- Reason rejected: Explicitly out of scope / prior coverage noted. No new additive simplification proposed there.

## ReportFilter support / parity changes

- Reason rejected: Prior coverage exists; no new non-duplicative candidate identified in this pass.

---

# Files created or modified

None.

I performed read-only inspection only.

# Issues encountered

None blocking.

One caution: timestamp parsing simplification has real compatibility risk because different report modules intentionally handle invalid/naive timestamps differently. That candidate should be implemented incrementally with focused tests, not as a broad mechanical replacement.