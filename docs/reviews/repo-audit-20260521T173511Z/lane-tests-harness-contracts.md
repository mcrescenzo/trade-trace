# Lane report: tests-harness-contracts

Audit run: `repo-audit-20260521T173511Z`  
Scope fingerprint: `1901b8097953e720`  
Lane: `tests-harness-contracts`  
HEAD context: `a1023ea4f2d498e916acbcbe25eecc0570d873bf` on `main`

## Scope and method

Assigned manifest rows are all `owner_lane: tests-harness-contracts` rows in `manifest-coverage-ledger.yaml`: 132 tracked Python files under `tests/`, covering root harness helpers, browser tests, contracts, docs tests, golden tests, integration tests, property tests, security tests, and smoke/timestamp tests.

Read-only audit actions performed:

- Read the assigned manifest slice from `manifest-coverage-ledger.yaml` lines 1925-2980.
- Enumerated all tracked test Python files under `tests/` (132 files) with `python` over the repository tree.
- Searched assigned tests for skip/xfail/TODO/stub/direct-SQL/subprocess/network patterns.
- Directly inspected high-signal files: `tests/_direct_sql_builders.py`, `tests/console_browser/conftest.py`, `tests/console_browser/test_overview_smoke.py`, `tests/contracts/test_tool_schema_runtime_parity.py`, and `pyproject.toml`.
- Checked existing audit-family inventory for obvious overlap titles/labels; no exact duplicate for the accepted candidates below was found in the inspected inventory excerpt.

## Per-assigned-row treatment

All 132 assigned rows were treated as part of one test-harness/contract lane. Per-row direct/semantic treatment:

- Harness/root helpers: `tests/__init__.py`, `tests/conftest.py`, `tests/_mcp_helpers.py`, `tests/_direct_sql_builders.py` were reviewed for fixture/helper drift and dead helper sprawl.
- Browser harness/tests: `tests/console_browser/**` were reviewed for skip behavior, coverage breadth, subprocess/server setup, fixture seed use, and page coverage gaps.
- Contract tests: `tests/contracts/**` were reviewed for stale schema/runtime parity, subprocess/path assumptions, optional dependency skips, and contract coverage shape.
- Docs/golden tests: `tests/docs/**`, `tests/golden/**` were included in file enumeration and pattern searches for stale assertions and truthfulness/parity coverage.
- Integration tests: `tests/integration/**` were included in file enumeration and pattern searches, with special attention to direct SQL helper use and fixture/data setup patterns.
- Property/security tests: `tests/property/**`, `tests/security/**` were included in searches for skips, security boundary coverage, and helper drift.
- Root smoke/timestamp tests: `tests/test_smoke.py`, `tests/test_timestamps.py` were included in enumeration/search treatment.

No destructive commands, package-manager operations, installers, formatters, Beads writes, or product/source/test edits were performed.

## Accepted candidates

### THC-20260521-001 — Contract test hard-codes `.venv/bin/tt`, making the suite non-portable outside one local checkout layout

- **Candidate id:** `THC-20260521-001`
- **Title:** Contract test hard-codes `.venv/bin/tt`, making the suite non-portable outside one local checkout layout
- **Remediation track:** bughunt / test-harness reliability
- **Owner track:** tests-harness-contracts
- **Affected paths/symbols:** `tests/contracts/test_tool_schema_runtime_parity.py::test_snapshot_add_cli_help_lists_optional_market_state_flags`; project console script declaration in `pyproject.toml`
- **Observed facts with evidence:**
  - The test computes `ROOT = Path(__file__).resolve().parents[2]` (`tests/contracts/test_tool_schema_runtime_parity.py:20`).
  - It invokes `[str(ROOT / ".venv/bin/tt"), "snapshot", "add", "--help"]` with `check=True` (`tests/contracts/test_tool_schema_runtime_parity.py:172-179`).
  - The package declares a normal `tt` console script (`pyproject.toml:82-85`), so the intended executable is environment-provided, not necessarily located at repository-relative `.venv/bin/tt`.
- **Inferences:** This contract test will fail or be skipped only by environment accident in CI/build systems that install the package into a tox/nox/uv/pipx/global environment, use Windows paths, or run pytest without a repository-local `.venv`. The assertion is meant to verify CLI help content, but its hard-coded launcher tests local developer setup instead.
- **Assumptions:** The parent CI may currently create `.venv`; even then, the test remains brittle for downstream packagers and alternate runners.
- **Open questions:** Should CLI-help contract tests consistently call `sys.executable -m trade_trace.cli ...` or use an installed `tt` discovered via `shutil.which`? The rest of this file already imports runtime code directly for schema checks.
- **Validation command/gap:** `pytest tests/contracts/test_tool_schema_runtime_parity.py::test_snapshot_add_cli_help_lists_optional_market_state_flags` in an environment without repository-local `.venv/bin/tt` should reproduce the failure. I did not run it because the lane is read-only and reproducing by mutating/removing `.venv` would be out of scope.
- **Prior match status:** No exact prior match found in inspected audit inventory. Related but not duplicate: `trade-trace-rtsw` covered exposing instrument audit fields; this candidate is about test launcher portability for `snapshot add` help.
- **Duplicate/overlap notes:** Potentially overlaps build/CI lane only insofar as CI environment determines whether `.venv/bin/tt` exists; the decisive defect is in the test harness path assumption.
- **Recommended disposition:** Accept as bug.
- **Proposed Bead:**
  - **Title:** Make CLI help contract tests launch `tt` portably instead of hard-coding `.venv/bin/tt`
  - **Type:** bug
  - **Labels:** `bughunt`, `tests`, `contract-tests`, `ci-portability`
  - **Acceptance:** The snapshot help contract test runs in a fresh installed environment without a repo-local `.venv`; it uses `sys.executable -m trade_trace.cli` or a documented launcher helper; no contract coverage is removed.

### THC-20260521-002 — Browser smoke harness documents per-page coverage but only tracks one Overview smoke test while the route catalog has many routes

- **Candidate id:** `THC-20260521-002`
- **Title:** Browser smoke harness documents per-page coverage but only tracks one Overview smoke test while the route catalog has many routes
- **Remediation track:** bughunt / regression-gap
- **Owner track:** tests-harness-contracts
- **Affected paths/symbols:** `tests/console_browser/conftest.py`, `tests/console_browser/test_overview_smoke.py`, `frontend/console/src/routeCatalog.json`
- **Observed facts with evidence:**
  - The browser harness docstring says page smoke tests `(.6/.7/.8/.9) reuse the same Console server + seeded DB + browser driver` and gives instructions for adding a smoke test for a new page (`tests/console_browser/conftest.py:3-20`).
  - The only tracked browser test file in the assigned manifest/listing is `tests/console_browser/test_overview_smoke.py`; it navigates only to `/` (`tests/console_browser/test_overview_smoke.py:12-20`).
  - That test asserts nav links are visible for many labels, but it does not click or load those routes (`tests/console_browser/test_overview_smoke.py:26-32`).
  - The route catalog contains 17 routes/components, including `/trades`, `/reports`, `/review`, multiple `/reports/...` routes, `/process`, `/calibration`, `/evidence`, `/strategies`, `/playbooks`, `/journal`, and `/decisions` (`frontend/console/src/routeCatalog.json:2-18`).
- **Inferences:** The browser harness gives a false sense of per-page coverage: it only proves the Overview route and nav render. Route-specific JavaScript/runtime failures on non-root pages can pass browser smoke coverage as long as their nav labels are present.
- **Assumptions:** Some non-browser contract/frontend tests may cover pieces of these pages, but they do not replace an end-to-end browser navigation smoke for each shipped route.
- **Open questions:** Should the browser smoke be parametrized from the shared route catalog, or should route-specific assertions remain hand-written per route?
- **Validation command/gap:** `pytest tests/console_browser/` after installing `[console,console-test]` and Chromium validates current browser smoke behavior. A gap-closing validation would parametrize over `routeCatalog.json` and fail on any route that cannot load without console errors.
- **Prior match status:** No exact prior match found in inspected inventory. Related console product/audit tasks exist (`trade-trace-t33l`, `trade-trace-i1ds`, `trade-trace-q6wj`) but those are broader console implementation/audit items, not this harness regression gap.
- **Duplicate/overlap notes:** Console frontend/backend lane may identify page bugs; this candidate is specifically about missing browser contract coverage.
- **Recommended disposition:** Accept as bug/regression-gap.
- **Proposed Bead:**
  - **Title:** Expand browser smoke coverage to navigate every shipped Console route
  - **Type:** bug
  - **Labels:** `bughunt`, `tests`, `browser-tests`, `console`, `regression-gap`
  - **Acceptance:** `tests/console_browser/` derives or enumerates all shipped routes and visits each route under Playwright, asserting no page/console errors plus a route-specific heading or landmark; the Overview-only smoke remains or is folded into the parametrized coverage.

### THC-20260521-003 — Direct-SQL seed helper has grown into fixture sprawl with many unreferenced public builders

- **Candidate id:** `THC-20260521-003`
- **Title:** Direct-SQL seed helper has grown into fixture sprawl with many unreferenced public builders
- **Remediation track:** deadcode/reachability / simplification
- **Owner track:** tests-harness-contracts
- **Affected paths/symbols:** `tests/_direct_sql_builders.py`; consumers `tests/integration/test_edges.py`, `tests/integration/test_edge_endpoint_audit.py`, `tests/integration/test_append_only.py`
- **Observed facts with evidence:**
  - The helper advertises composable direct-SQL seed helpers and canonical ids/timestamps (`tests/_direct_sql_builders.py:1-16`).
  - It defines many table-specific insert helpers, including `insert_forecast_outcome` (`tests/_direct_sql_builders.py:92-104`), `insert_snapshot` (`tests/_direct_sql_builders.py:107-120`), `insert_decision_tag` (`tests/_direct_sql_builders.py:139-145`), `insert_edge` (`tests/_direct_sql_builders.py:190-207`), `insert_position_event` (`tests/_direct_sql_builders.py:210-224`), `insert_forecast_score` (`tests/_direct_sql_builders.py:227-242`), `insert_signal` (`tests/_direct_sql_builders.py:245-258`), and `insert_audit_event` (`tests/_direct_sql_builders.py:261-276`).
  - Source-scoped counting over tracked `tests/**/*.py` excluding the helper itself found direct references outside the helper for only a subset: `insert_venue`, `insert_instrument`, `insert_thesis`, `insert_forecast`, `insert_decision`, `insert_outcome`, `insert_source`, and `seed_full_append_only_graph`; the helpers listed above had zero direct external references. The only importer hits found were `tests/integration/test_edges.py:10-17`, `tests/integration/test_edge_endpoint_audit.py:8-12`, and `tests/integration/test_append_only.py:18`.
  - `seed_full_append_only_graph` internally calls all of the unreferenced helpers (`tests/_direct_sql_builders.py:279-297`), so they are reachable only as implementation details of one aggregate seeder.
- **Inferences:** The module exposes table-level helpers that are not actually consumed as composable public fixtures. This increases fixture surface area and can mask schema drift because direct SQL builders must be manually kept aligned with migrations. The unused helpers should either be private implementation details of `seed_full_append_only_graph` or removed/relocated until a test needs them directly.
- **Assumptions:** The Python name-count search is sufficient for direct test references because these helpers are normal functions imported by name, not dynamically resolved.
- **Open questions:** Does the append-only test need one-row-per-table direct SQL at all, or could it seed through public tools for higher-fidelity integration coverage?
- **Validation command/gap:** Run `pytest tests/integration/test_append_only.py tests/integration/test_edges.py tests/integration/test_edge_endpoint_audit.py` after making helper visibility/scope changes. I did not mutate tests in this audit.
- **Prior match status:** No exact prior match found in inspected inventory. Related historical simplification note `SIMP-009` is referenced in the helper docstring, but the current issue is residual fixture sprawl after consolidation.
- **Duplicate/overlap notes:** Adjacent to simplification/deadcode lanes, but the artifact is test-owned and affects test fixture maintainability.
- **Recommended disposition:** Accept as simplification/deadcode task.
- **Proposed Bead:**
  - **Title:** Trim or privatize unused direct-SQL test seed builders
  - **Type:** task
  - **Labels:** `simplification`, `deadcode`, `tests`, `fixture-sprawl`
  - **Acceptance:** Public helper exports in `tests/_direct_sql_builders.py` match actual direct consumers; aggregate-only helpers are private or inlined; append-only/edge tests still pass; no direct-SQL helper is retained without a named consuming test or comment explaining why it must remain public.

## Rejected / not-filed observations

- `tests/console_browser/conftest.py` intentionally uses `pytest.importorskip("playwright.sync_api")` (`tests/console_browser/conftest.py:34-41`) because browser tests require optional extras documented in `pyproject.toml:64-72`. This is acceptable as opt-in behavior by itself; the filed issue is the narrower route-coverage gap.
- Several tests use subprocesses/sockets intentionally for CLI/import-cycle/server contracts. I did not file these as issues absent evidence of flakiness or leaked resources.
- Many integration tests use fixtures and direct DB setups; I only filed the direct-SQL helper sprawl where reachability evidence was concrete.

## Commands/searches used

- `read_file manifest-coverage-ledger.yaml` offsets 1 and 1925 to identify assigned rows.
- `search_files` under `tests/` for `(skip|xfail|TODO|FIXME|stub|placeholder|pass|assert True|pytest.mark|monkeypatch|direct_sql|network|socket|subprocess)`.
- `read_file` on:
  - `tests/contracts/test_tool_schema_runtime_parity.py`
  - `tests/console_browser/conftest.py`
  - `tests/console_browser/test_overview_smoke.py`
  - `tests/_direct_sql_builders.py`
  - `frontend/console/src/routeCatalog.json`
  - `pyproject.toml`
  - `existing-audit-family-inventory.json`
- `python` enumeration of tracked test-like files under `/home/hermes/code/trade-trace/tests`.
- `python` AST/name-count check for external references to functions defined in `tests/_direct_sql_builders.py`.

## Side-effect declaration

Only this lane packet was written: `/home/hermes/code/trade-trace/docs/reviews/repo-audit-20260521T173511Z/lane-tests-harness-contracts.md`. No source, product docs, tests, Beads, package files, lockfiles, caches, services, or external systems were modified.
