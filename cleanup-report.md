# Repo Cleanup Report — trade-trace

> **REPORT ONLY — NOTHING WAS APPLIED.** Every item below is a *proposal*.
> No code, docs, tests, or dependencies were modified. No Beads issues were
> opened or closed. No commits or pushes were made. Use this report to decide
> what (if anything) to act on later.

## Executive summary

This report consolidates 33 verified cleanup candidates across dead code,
duplication, simplification, best-practice, unused dependencies, stale markers,
and documentation drift. The highest-impact cluster is a **documentation-drift
bug**: the `model.import` tool requires the argument `path`, but its
agent-facing `tool.schema` example and four shipped docs (README, memory-layer,
security, PRD) all tell users/agents to pass `--src`/`"src"`, which fails
dispatch with `"path is required"`. Because the README designates `tool.schema`
as the source of truth, an agent copying the example makes a call that always
fails — this is the top-ranked finding and a small, mechanical fix in five
places.

Beyond that, the bulk of value is low-risk consolidation: several byte-identical
SQL/timestamp/strategy-filter helpers are duplicated across report modules even
though canonical versions already exist (in `trade_trace.timestamps` and
elsewhere), and a handful of trivial simplifications (`dict.get` guards, an
`O(n log n)` `names()` membership test on every MCP dispatch) are safe wins.
A cleanup of clearly dead code (unused private helpers, a write-only attribute,
a never-called public permissions method), a genuinely-unused `tenacity`
dependency, and removal of cruft (a literal `$(mktemp -d)` directory at repo
root, a 425-line permanently-skipped test module) round out the proposals. A
small set of best-practice findings narrow overly-broad `except Exception`
clauses to the project's established narrow exception types.

## Ranked summary

Rank = severity (high > medium > low) weighted by confidence and inversely by
effort (small effort ranks higher).

| Rank | id | category | severity | conf | effort | file:line | description |
|------|----|----------|----------|------|--------|-----------|-------------|
| 1 | doc-drift-32 | doc-drift | high | 95 | small | src/trade_trace/tools/_examples.py:722 | `model.import` `tool.schema` example uses `"src"`; handler requires `path` |
| 2 | doc-drift-33 | doc-drift | high | 95 | small | README.md:86 | README `tt model import --src` example fails; flag must be `--path` |
| 3 | doc-drift-34 | doc-drift | high | 94 | small | docs/architecture/memory-layer.md:210 | Three `tt model import --src` examples wrong; require `--path` |
| 4 | simplification-22 | simplification | low | 97 | small | src/trade_trace/cli.py:441 | Redundant `if k in d else None` around `dict.get` |
| 5 | simplification-23 | simplification | low | 95 | small | src/trade_trace/mcp_server.py:241 | `reg.names()` sort+membership per dispatch; use `by_name.get` |
| 6 | dead-code-2 | dead-code | low | 96 | small | src/trade_trace/reports/operational_health.py:127 | Never-called `_query` helper |
| 7 | dead-code-3 | dead-code | low | 96 | small | src/trade_trace/tools/review_bundle.py:392 | Never-called `_fetch_scoped_table` |
| 8 | dead-code-6 | dead-code | low | 96 | small | src/trade_trace/events/unit_of_work.py:54 | Write-only `_committed` attribute |
| 9 | dead-code-4 | dead-code | low | 95 | small | src/trade_trace/tools/ledger/_shared.py:33 | Unused `_idempotency_key`/`_allow_no_idempotency`; stale docstring |
| 10 | duplication-11 | duplication | low | 96 | small | src/trade_trace/reports/calibration.py:528 | `_placeholders` duplicated in 4 places |
| 11 | unused-deps-10 | unused-deps | medium | 95 | small | pyproject.toml:53 | `tenacity` declared but never imported; stale docstrings |
| 12 | doc-drift-35 | doc-drift | medium | 93 | small | docs/architecture/security.md:163 | `tt model import --src` examples wrong; require `--path` |
| 13 | best-practice-27 | best-practice | low | 92 | small | src/trade_trace/cli.py:6 | Module docstring exit-code claim stale vs real 0/1/2/3 mapping |
| 14 | doc-drift-36 | doc-drift | medium | 92 | small | docs/PRD.md:60 | `tt model import --src` example wrong; require `--path` |
| 15 | duplication-13 | duplication | low | 95 | small | src/trade_trace/reports/strategy_health.py:63 | `_resolve_strategy_filter` byte-identical in 2 files |
| 16 | dead-code-1 | dead-code | medium | 93 | small | src/trade_trace/reports/source_quality.py:440 | Never-called `_sensitive_sources` builder |
| 17 | best-practice-28 | best-practice | medium | 85 | small | src/trade_trace/reports/source_quality.py:299 | Broad `except Exception` should be narrow ValueError/JSONDecodeError |
| 18 | best-practice-29 | best-practice | medium | 85 | small | src/trade_trace/reports/audit_readiness.py:90 | Broad `except Exception` for ts/json parsing |
| 19 | duplication-15 | duplication | low | 90 | small | src/trade_trace/reports/lifecycle.py:402 | `_parse_ts` strict duplicated; replace with timestamps helper |
| 20 | stale-markers-18 | stale-markers | medium | 90 | medium | tests/integration/test_final_dogfood_verification.py:28 | 425-line module unconditionally skipped (superseded gate) |
| 21 | best-practice-30 | best-practice | medium | 82 | small | src/trade_trace/tools/ledger/source.py:47 | Broad `except Exception` around `json.loads` (×3) |
| 22 | stale-markers-20 | stale-markers | low | 88 | small | $(mktemp -d) | Literal `$(mktemp -d)` directory at repo root (cruft) |
| 23 | best-practice-31 | best-practice | low | 78 | small | src/trade_trace/adapters/polymarket/config.py:72 | Broad `except Exception` should be `sqlite3.Error` |
| 24 | dead-code-5 | dead-code | low | 88 | small | src/trade_trace/storage/database.py:65 | Never-called `ensure_user_only_permissions`; false docstring |
| 25 | simplification-26 | simplification | low | 70 | small | src/trade_trace/cli.py:268 | Function-local `import uuid as _uuid` indirection |
| 26 | duplication-12 | duplication | medium | 88 | medium | src/trade_trace/reports/forecast_diagnostics.py:128 | Actor/instrument WHERE-clause builder near-duplicated ×3 |
| 27 | duplication-14 | duplication | medium | 82 | medium | src/trade_trace/reports/execution_quality.py:30 | Lenient ISO-8601 parsing reimplemented in 4 modules |
| 28 | simplification-25 | simplification | low | 60 | small | src/trade_trace/mcp_server.py:73 | Nested ternaries for description augmentation |
| 29 | dead-code-7 | dead-code | low | 88 | medium | src/trade_trace/clock.py:19 | Clock surface is test-only; docstring overstates prod use |
| 30 | simplification-24 | simplification | low | 72 | medium | src/trade_trace/core.py:445 | Idempotency-source ternary re-tests shared predicates |
| 31 | stale-markers-21 | stale-markers | low | 45 | small | src/trade_trace/reports/coach.py:158 | `calibration_drift` placeholder tied to M2/M3 milestone |
| 32 | stale-markers-19 | stale-markers | low | 62 | medium | next-steps.md:1 | 1069-line historical roadmap with knowingly-stale CLI spellings |
| 33 | duplication-16 | duplication | medium | 70 | large | src/trade_trace/tools/ledger/venue.py:33 | Create-handler scaffold copy-pasted across 3 ledger tools |
| 34 | duplication-17 | duplication | low | 66 | large | src/trade_trace/tools/abstention.py:0 | Write-tool DB open/try/finally idiom in ~30 modules |

## Per-finding detail

### Rank 1 — doc-drift-32 — `model.import` example uses wrong field name
**File:** src/trade_trace/tools/_examples.py:722 · **severity** high · **conf** 95 · **effort** small
The `tool.schema` example payload for `model.import` uses the field name `"src"`,
but the handler `_model_import` in admin.py requires `path` (admin.py:646
`require(args, "path")`). Verified by dispatch: `{"src": ...}` returns
VALIDATION_ERROR `"path is required"`, while `{"path": ...}` proceeds. Because
`tool.schema` surfaces this as `example_minimal` and the README explicitly tells
agents to use `tool.schema` as the source of truth, an agent copying the example
makes a call that always fails. The field `src` legitimately belongs to
`journal.restore`, not `model.import`.
**Proposed change:** In `WRITE_TOOL_EXAMPLES["model.import"]["minimal"]`, rename
the key `"src"` to `"path"` so the example matches the handler's required argument.
**Doc impact:** This example feeds `tool.schema`'s `example_minimal` for
`model.import`; fixing the key here corrects the agent-facing schema example.

### Rank 2 — doc-drift-33 — README `model import` flag wrong
**File:** README.md:86 · **severity** high · **conf** 95 · **effort** small
README install section documents `tt --confirm model import --src <dir>
--idempotency-key <key>`. The CLI maps `--src` to arg `src`, but `model.import`
requires `path` (admin.py:646), verified by dispatch (`"path is required"`).
**Proposed change:** Change to `tt --confirm model import --path <pre-staged-dir>
--idempotency-key <key>`.

### Rank 3 — doc-drift-34 — memory-layer.md `model import` flag wrong (×3)
**File:** docs/architecture/memory-layer.md:210 (also ~24, ~279) · **severity** high · **conf** 94 · **effort** small
Documents the only model-staging path as `tt model import --src <path-to-bge-small>
--idempotency-key <uuid> --confirm`. Handler requires `path`. All three `--src`
examples are wrong; `journal.restore` is the tool that legitimately uses `--src`.
**Proposed change:** Replace `--src` with `--path` in the three examples
(lines ~24, 210, 279).

### Rank 4 — simplification-22 — redundant dict membership guard
**File:** src/trade_trace/cli.py:441 · **severity** low · **conf** 97 · **effort** small
`registration = registry.by_name.get(tool_name) if tool_name in registry.by_name
else None`. `dict.get` already returns `None` for absent keys, so the guard does
a second hash lookup that changes nothing.
**Proposed change:** `registration = registry.by_name.get(tool_name)`.

### Rank 5 — simplification-23 — `reg.names()` sort on every dispatch
**File:** src/trade_trace/mcp_server.py:241 · **severity** low · **conf** 95 · **effort** small
`registration = reg.get(name) if name in reg.names() else None` builds and sorts
a fresh list of all tool names on every tool call just for an `in` test, then
re-looks-up via `reg.get`. The registry exposes `by_name` for O(1)
membership/lookup (cli.py already uses it).
**Proposed change:** `registration = reg.by_name.get(name)` — drops the
`O(n log n)` `names()` sort + redundant lookup per dispatch.

### Rank 6 — dead-code-2 — never-called `_query` helper
**File:** src/trade_trace/reports/operational_health.py:127 · **severity** low · **conf** 96 · **effort** small
`_query(conn, table, sql, params)` is never called; `_build()` runs all queries
inline with explicit `_has_table` guards instead.
**Proposed change:** Delete `_query` (lines 127-130). Behavior unchanged.

### Rank 7 — dead-code-3 — never-called `_fetch_scoped_table`
**File:** src/trade_trace/tools/review_bundle.py:392 · **severity** low · **conf** 96 · **effort** small
`_fetch_scoped_table(...)` is never called; every table fetch uses `_fetch_table`
directly. The scoped wrapper that tracks an `omissions` list is unreferenced.
**Proposed change:** Delete `_fetch_scoped_table` (lines 392-404). If omission
tracking was intended, that's a separate bug to wire up, not a reason to keep
dead code.

### Rank 8 — dead-code-6 — write-only `_committed` attribute
**File:** src/trade_trace/events/unit_of_work.py:54 · **severity** low · **conf** 96 · **effort** small
`UnitOfWork._committed` is set `False` in `__init__` and `True` in `_commit()`
but never read; `__exit__` does not consult it.
**Proposed change:** Remove both the `self._committed = False` initializer
(line 54) and the `self._committed = True` assignment (line 84).

### Rank 9 — dead-code-4 — unused ledger `_shared` accessors
**File:** src/trade_trace/tools/ledger/_shared.py:33 · **severity** low · **conf** 95 · **effort** small
`_idempotency_key(args)` and `_allow_no_idempotency(args)` are never called;
ledger submodules import only `examples_for` and `_store_tags`. Idempotency-key
handling now lives centrally in `core.py::dispatch`.
**Proposed change:** Delete both helpers (lines 33-39, 41-42) and update the
module docstring bullet (line 6) that lists them as caller-key plumbing.
**Doc impact:** `_shared.py` module docstring (~line 6) lists these as part of
the shared surface; remove that bullet so the docstring matches actual exports.

### Rank 10 — duplication-11 — `_placeholders` duplicated in 4 places
**File:** src/trade_trace/reports/calibration.py:528 · **severity** low · **conf** 96 · **effort** small
`_placeholders(count) -> ', '.join('?' for _ in range(count))` is byte-identical
in calibration.py:528, pm_native.py:32, review_bundle.py:143, and is imported
from calibration into forecast_diagnostics.py:21. The import path already works,
so the other three copies are pure duplication.
**Proposed change:** Promote one canonical `_placeholders` to a shared module
(e.g. `reports/_filter_support.py` or a new `reports/_sql.py`) and import it in
calibration.py, pm_native.py, and review_bundle.py. Trivial and behavior-preserving.

### Rank 11 — unused-deps-10 — `tenacity` declared but unused
**File:** pyproject.toml:53 · **severity** medium · **conf** 95 · **effort** small
`tenacity>=8.2` is a base runtime dependency but is never imported anywhere. The
Polymarket retry implementation is hand-rolled (stdlib `random` + `time.sleep`);
`retry_policy_kwargs()` returns a dict of string literals that mirror tenacity's
API names but are never passed to tenacity. Adds install weight with no use.
**Proposed change:** Remove `"tenacity>=8.2",` from `[project].dependencies`
(line 53); keep the hand-rolled retry (or, alternatively, actually wire tenacity
in). Re-run `pip install -e .` and `pytest -q` after removal.
**Doc impact:** `client.py:3` docstring falsely states `tenacity` is imported in
that module (only `httpx` is); `retry.py:31` `retry_policy_kwargs()` docstring
("Expose the tenacity policy shape") should clarify it returns plain config
constants, not a tenacity policy.

### Rank 12 — doc-drift-35 — security.md `model import` flag wrong
**File:** docs/architecture/security.md:163 (also ~29) · **severity** medium · **conf** 93 · **effort** small
Documents `tt model import --src <pre-staged bge-small> --confirm`. Handler
requires `path`.
**Proposed change:** Replace `--src` with `--path` at lines ~29 and 163.

### Rank 13 — best-practice-27 — stale exit-code docstring
**File:** src/trade_trace/cli.py:6 · **severity** low · **conf** 92 · **effort** small
The module docstring says "Exit code is 0 when ok=true, 1 otherwise," but the
code maps VALIDATION_ERROR → 2 and INVARIANT_VIOLATION → 3 (main() lines 536-539,
`_emit_cli_error` lines 276-280), and the no-command path returns 2 (line 356).
A reader trusting the docstring would mis-handle exit codes in CI wrappers.
**Proposed change:** Update the docstring to the real contract: 0 success; 2
VALIDATION_ERROR (and no-command); 3 INVARIANT_VIOLATION; 1 every other error.
**Doc impact:** cli.py docstring lines 5-6 are stale; replace with the four-way
mapping that lines 276-280 and 533-540 implement.

### Rank 14 — doc-drift-36 — PRD.md `model import` flag wrong
**File:** docs/PRD.md:60 · **severity** medium · **conf** 92 · **effort** small
Documents `tt model import --src <dir> --confirm`. Handler requires `path`.
**Proposed change:** Change to `tt model import --path <dir> --confirm`.

### Rank 15 — duplication-13 — `_resolve_strategy_filter` duplicated
**File:** src/trade_trace/reports/strategy_health.py:63 · **severity** low · **conf** 95 · **effort** small
`_resolve_strategy_filter(conn, value)` is byte-identical in strategy_health.py:63
and forecast_diagnostics.py:121 (same None/STRATEGY_NONE_SENTINEL early-return,
same `SELECT id FROM strategies WHERE id = ? OR slug = ? ORDER BY id LIMIT 1`).
**Proposed change:** Move into a shared reports helper module and import in both,
deleting the duplicate definition.

### Rank 16 — dead-code-1 — never-called `_sensitive_sources`
**File:** src/trade_trace/reports/source_quality.py:440 · **severity** medium · **conf** 93 · **effort** small
`_sensitive_sources(conn)` is never called; the diagnostics dict (line 99) uses a
separately-computed `redacted` variable instead. Grep finds only the definition.
**Proposed change:** Confirm via `git log -L :_sensitive_sources:...` that it was
superseded, then delete the function (~437-470) and its section header. If its
richer edge/attachment detail is wanted, wire it in instead.

### Rank 17 — best-practice-28 — broad excepts in source_quality.py
**File:** src/trade_trace/reports/source_quality.py:299 · **severity** medium · **conf** 85 · **effort** small
Broad `except Exception` wraps `to_utc_iso8601(...)` (lines 297-299, 323-325) and
`json.loads` (117-118). The project convention is narrow: `to_utc_iso8601` raises
`TimestampValidationError` (a `ValueError` subclass) and sibling modules use
`except ValueError`/`except TimestampValidationError`; `json.loads` is caught as
`json.JSONDecodeError` in 30+ sites. Broad catches can mask real bugs.
**Proposed change:** Narrow lines 299/325 to `except (ValueError,
TimestampValidationError)` and line 118 to `except json.JSONDecodeError`.

### Rank 18 — best-practice-29 — broad excepts in audit_readiness.py
**File:** src/trade_trace/reports/audit_readiness.py:90 · **severity** medium · **conf** 85 · **effort** small
Broad `except Exception` wraps `to_utc_iso8601`/`datetime.fromisoformat` in
`_parse` (line 90) and `json.loads(depth or '{}')` (line 169), contradicting the
module's own neighbors.
**Proposed change:** Change line 90 to `except (ValueError, TimestampValidationError)`
and line 169 to `except json.JSONDecodeError`.

### Rank 19 — duplication-15 — `_parse_ts` strict duplicated
**File:** src/trade_trace/reports/lifecycle.py:402 · **severity** low · **conf** 90 · **effort** small
`_parse_ts` (strict, naive-as-UTC, `astimezone(UTC)`) is byte-identical in
lifecycle.py:402 and strategy_health.py:23 (lifecycle.py even carries the comment
"Match strategy_health._parse_ts"). Both replicate
`trade_trace.timestamps.parse_report_timestamp_strict_utc_naive_as_utc`.
**Proposed change:** Replace both with the centralized helper (it already raises
on empty input, matching strict intent), deleting the duplicates and the comment.
**Doc impact:** lifecycle.py:402 "Match strategy_health._parse_ts" comment goes
stale once both use the shared helper; remove it.

### Rank 20 — stale-markers-18 — 425-line permanently-skipped test module
**File:** tests/integration/test_final_dogfood_verification.py:28 · **severity** medium · **conf** 90 · **effort** medium
The entire 425-line, 17-test module is unconditionally skipped via
`pytestmark = pytest.mark.skip(...)` ("Legacy 0.0.1 dogfood fixture gate
superseded by the v0.0.2 PM-only fixture/report gate..."). It still parses/imports
and can mislead readers into thinking the dogfood scenario is exercised.
**Proposed change:** Confirm the v0.0.2 PM-only gate covers the criteria, port any
still-unique assertions forward, then delete the module and its fixtures rather
than leaving 425 lines permanently skipped. Report-only: do not modify now.
**Doc impact:** docs/architecture/dogfood-protocol.md references the dogfood
verification; if deleted, update that doc to point at the v0.0.2 replacement.

### Rank 21 — best-practice-30 — broad excepts in ledger/source.py
**File:** src/trade_trace/tools/ledger/source.py:47 · **severity** medium · **conf** 82 · **effort** small
Broad `except Exception` around `json.loads(... or '{}')` at three sites
(lines 46-47, 180-181, 210-211). The shared `_helpers.store_metadata_json` and
~30 other sites catch `json.JSONDecodeError`. Existing `isinstance(parsed, dict)`
guards already handle valid-but-non-dict JSON.
**Proposed change:** Narrow lines 47/181/211 to `except json.JSONDecodeError`.

### Rank 22 — stale-markers-20 — literal `$(mktemp -d)` directory at repo root
**File:** $(mktemp -d) · **severity** low · **conf** 88 · **effort** small
A directory literally named `$(mktemp -d)` exists at repo root — a shell-expansion
accident. It is empty and untracked, pure leftover cruft that clutters the root
and confuses tooling.
**Proposed change:** After confirming it is empty, remove it:
`rm -rf './$(mktemp -d)'` (single quotes prevent re-expansion). Untracked, so no
git change beyond deletion. Report-only: do not delete now.

### Rank 23 — best-practice-31 — broad except in polymarket/config.py
**File:** src/trade_trace/adapters/polymarket/config.py:72 · **severity** low · **conf** 78 · **effort** small
`config_from_db()` catches broad `except Exception` around a single SQLite SELECT
to treat a missing config table as "adapter disabled." The precise failure is
`sqlite3.OperationalError`/`sqlite3.Error`, which the rest of the codebase
branches on. Broad catch swallows unrelated bugs and silently degrades the adapter.
**Proposed change:** Narrow line 72 to `except sqlite3.Error` (or
`sqlite3.OperationalError`).

### Rank 24 — dead-code-5 — never-called `ensure_user_only_permissions`
**File:** src/trade_trace/storage/database.py:65 · **severity** low · **conf** 88 · **effort** small
`Database.ensure_user_only_permissions()` is never called; its docstring claims
"Callers run this after writes" but there are none. WAL/SHM perm tightening is
actually done by `close()` via `_chmod_wal_shm_siblings`.
**Proposed change:** Remove the method (lines 65-74). If a post-write re-pin is
desired, add a caller; otherwise it is unreachable and its docstring is false.
**Doc impact:** The method docstring (lines 66-71) claims callers exist — unmet;
remove with the method or document that no caller invokes it.

### Rank 25 — simplification-26 — function-local aliased uuid import
**File:** src/trade_trace/cli.py:268 · **severity** low · **conf** 70 · **effort** small
`_emit_cli_error` does `import uuid as _uuid` inside the function body. `core.py`
exposes `new_request_id()` and uuid is a trivial stdlib import; the function-local
alias is unnecessary indirection.
**Proposed change:** Move `import uuid` to module top-level and use
`uuid.uuid4().hex` directly, dropping the `_uuid` alias and in-function import.

### Rank 26 — duplication-12 — actor/instrument WHERE-clause builder duplicated
**File:** src/trade_trace/reports/forecast_diagnostics.py:128 · **severity** medium · **conf** 88 · **effort** medium
forecast_diagnostics.py::`_base_where` (131-151) and
calibration.py::`_apply_scored_row_filters` (423-440) emit the same five
`rf.actors.{...} IN (...)` blocks plus `instrument.venue_id IN (...)` against the
same aliases/params; pm_native.py::`_market_where` (60-65) repeats the subset
against a parameterized alias.
**Proposed change:** Extract a shared `apply_actor_filters(rf, where, params, *,
forecast_alias='f', instrument_alias='i')` (parameterizing aliases like
pm_native already does) and call it from all three, keeping report-specific
clauses in each caller.

### Rank 27 — duplication-14 — lenient ISO-8601 parsing reimplemented in 4 modules
**File:** src/trade_trace/reports/execution_quality.py:30 · **severity** medium · **conf** 82 · **effort** medium
Lenient ISO-8601 timestamp parsing is reimplemented in execution_quality.py:30
(`_dt`), operational_health.py:33 (`_dt`), opportunity.py:26 (`_parse_ts`), and
pm_native.py:36 (`_parse_ts`) despite canonical parsers in
`trade_trace.timestamps`. The timestamps.py docstrings even name these modules
("opportunity-compatible", "source_quality-compatible"), confirming an incomplete
migration.
**Proposed change:** Replace the local helpers with the matching centralized
parser. **Verify the `astimezone(UTC)` vs preserve-offset nuance per call site**
before swapping — the lenient centralized variant preserves non-UTC offsets while
some local `_dt` copies call `astimezone(UTC)`.

### Rank 28 — simplification-25 — nested ternaries for description augmentation
**File:** src/trade_trace/mcp_server.py:73 · **severity** low · **conf** 60 · **effort** small
The description-augmentation block uses two near-identical nested ternaries
(`f"{description} Usage: ..." if description else metadata['usage_summary']`,
then the same shape for the example), a small readability tax that duplicates
join logic.
**Proposed change:** Accumulate optional parts into a list and join once
(`parts = [description] if description else []; ...; description = ' '.join(parts)`).
Same output, no nested ternaries.

### Rank 29 — dead-code-7 — test-only clock surface with overstated docstring
**File:** src/trade_trace/clock.py:19 · **severity** low · **conf** 88 · **effort** medium
The entire `clock.py` injectable-clock surface (`Clock`, `SystemClock`,
`FixedClock`) is consumed only by `tests/test_timestamps.py`; no src module
imports `trade_trace.clock`. Runtime clock injection is actually done via the
`CLOCK_OVERRIDE` ContextVar in `tools/_helpers.py`, and fixture freezing uses its
own `_FrozenFixtureClock`. The comment (lines 56-60) asserting "Production code
passes a Clock explicitly" is stale — there are zero production consumers.
**Proposed change:** Either (a) move the types into a test helper, or (b) keep the
module but fix the stale comment so it no longer claims production consumers. Do
NOT silently delete `FixedClock` without updating `tests/test_timestamps.py`.
**Doc impact:** clock.py docstring (1-11) and comment block (49-60) describe a
production injection surface; reword to reflect ContextVar-based runtime injection
and test-only use.

### Rank 30 — simplification-24 — idempotency-source ternary re-tests predicates
**File:** src/trade_trace/core.py:445 · **severity** low · **conf** 72 · **effort** medium
The `else` branch of the idempotency-source assignment re-evaluates
`registration.is_write and not allow_no_idempotency and args.get('idempotency_key')`
in a ternary, re-testing predicates already evaluated by the outer `if`
(lines 419-420).
**Proposed change:** Compute once: `is_retryable_write = registration.is_write
and not allow_no_idempotency`, then a single if/elif/else block deriving 'auto' /
'caller' / None without re-spelling the shared predicates.

### Rank 31 — stale-markers-21 — `calibration_drift` milestone placeholder
**File:** src/trade_trace/reports/coach.py:158 · **severity** low · **conf** 45 · **effort** small
`coach.py` emits a hard-coded `calibration_drift = {"status": "not_yet_detected",
...}` (158-162) plus docstring notes (7-8) marking panels as placeholders "until
the M2/M3 drift detector lands." Intentional and labeled, but if M2/M3 has shipped
or been descoped, the static field misleads `report.coach` consumers.
**Proposed change:** Verify M2/M3 status. If shipped, wire to the real detector and
drop the placeholder; if descoped, remove the field and docstring references; if
still planned, leave as-is (it is correctly labeled). Report-only: do not modify now.
**Doc impact:** If removed/wired, update coach.py docstring (7-8) and any
report.coach contract doc describing `calibration_drift`/override-outcome fields.

### Rank 32 — stale-markers-19 — historical roadmap with stale CLI spellings
**File:** next-steps.md:1 · **severity** low · **conf** 62 · **effort** medium
next-steps.md (1069 lines) is self-labeled "Status: Planning / historical roadmap"
for the v0.0.2 PM pivot (approved 2026-05-22, largely shipped). Its own header
warns the CLI examples are "target spellings ... not the current default_registry
surface" and that hyphenated `subject verb` forms don't match the shipped
`subject.verb` grammar. A large, explicitly-historical artifact that can mislead
readers about the current surface.
**Proposed change:** Either archive under docs/ with a "historical, superseded"
banner pointing to docs/architecture/v002-pm-pivot-catalog.md, or prune shipped
sections so only genuinely-open items remain. Cross-check each item against shipped
state first. Report-only: do not modify now.
**Doc impact:** next-steps.md is referenced by
docs/architecture/v002-pm-pivot-catalog.md; if archived/moved/pruned, update that
reference (and any README/AGENTS pointers) so links don't break.

### Rank 33 — duplication-16 — ledger create-handler scaffold copy-pasted
**File:** src/trade_trace/tools/ledger/venue.py:33 · **severity** medium · **conf** 70 · **effort** large
The create-handler scaffold (open_db_for_args → UnitOfWork →
check_idempotency_replay → replay-branch vs new-id/INSERT/emit_event, in a
try/finally) is structurally copy-pasted across venue.py (`_venue_add`),
instrument.py (`_instrument_add`), thesis.py (`_thesis_add`). The replay branch in
particular is the same shape in all three.
**Proposed change:** Factor the open-db + UnitOfWork + replay-vs-insert envelope
into a shared helper (e.g. `create_entity(...)` taking event_type, subject_kind,
INSERT/reload/result callbacks). **Medium-risk**: variance in SELECT columns,
return shapes, and thesis's extra supersedes-edge emission means each handler's
tests must still pass after extraction.

### Rank 34 — duplication-17 — write-tool DB lifecycle idiom in ~30 modules
**File:** src/trade_trace/tools/abstention.py:0 · **severity** low · **conf** 66 · **effort** large
`db = open_db_for_args(args); try: ... finally: db.close()` is repeated in ~30 tool
modules. The read/report side centralizes this in
`reports/tool_handlers/common.py::_run_report_data`, but the write side has no
equivalent.
**Proposed change:** Add a context-manager (`@contextmanager def db_for_args(args)`)
to tools/_helpers.py mirroring `_run_report_data`, then convert write handlers to
`with db_for_args(args) as conn:`. Lower priority, broad blast radius; best done
incrementally per module.

## Docs already stale

These docs are **already out of sync with the current code** (doc-drift lens).
Fixing the underlying code/example is the proposal; until then, these doc paths
mislead readers:

- **src/trade_trace/tools/_examples.py** — `model.import` `tool.schema`
  `example_minimal` uses `"src"`; handler requires `path`. This is the
  agent-facing source of truth, so it is the most consequential stale doc.
- **README.md** (line 86) — `tt model import --src ...` install example fails;
  flag must be `--path`.
- **docs/architecture/memory-layer.md** (lines ~24, 210, 279) — three
  `tt model import --src ...` examples wrong; require `--path`.
- **docs/architecture/security.md** (lines ~29, 163) — `tt model import --src ...`
  examples wrong; require `--path`.
- **docs/PRD.md** (line 60) — `tt model import --src <dir> --confirm` wrong;
  require `--path`.

> Reminder: **nothing in this report was applied.** All items are proposals.
