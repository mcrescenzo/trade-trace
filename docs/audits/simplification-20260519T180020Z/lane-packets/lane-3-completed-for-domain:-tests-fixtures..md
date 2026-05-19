Read-only exhaustive simplification review completed for domain: tests-fixtures.

What I did:
- Read domain map at:
  /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z/domain-map.json
- Inspected the full tests-fixtures assignment from the map: 76 paths, 16,637 mapped lines.
- Used static AST scans and targeted file reads to review fixture sprawl, duplicate MCP/CLI helpers, repeated DB seed flows, slow/overcoupled tests, and prior-audit overlap.
- Ran read-only verification/discovery:
  - git rev-parse HEAD
  - git status --short
  - pytest --collect-only tests -q
- Confirmed expected commit:
  6f62a5f7a83cec823302bbe80892172b1e6936cb
- Pytest collection succeeded:
  1051 tests collected in 0.20s

Coverage accounting:
- Domain paths assigned: 76
- Domain paths inspected: 76
- Not inspected: 0
- Tests collected by pytest across tests/: 1051
- Files created: none
- Files modified: none
- Beads created/updated: none

Important workspace note:
- I did not modify files, but git status already showed pre-existing workspace changes/untracked audit artifacts:
  - M tests/contracts/test_grammar.py
  - ?? audits/no-tech-debt-20260519T180002Z/
  - ?? docs/audits/bughunt-20260519T175941Z/
  - ?? docs/audits/simplification-20260519T180020Z/

Candidate records:

Candidate TESTS-SIMPLIFY-001
Title: Centralize repeated initialized-home and MCP/CLI test helpers in tests/conftest.py or a small tests support module.
Domain: tests-fixtures
Type: simplification
Priority: high
Confidence: high

Evidence:
- tests/conftest.py currently only inserts src/ into sys.path and defines no project fixtures.
- Repeated initialized-home fixtures appear across many assigned files, usually:
  - h = tmp_path / "home"
  - mcp_call("journal.init", {"home": str(h)})
  - return h
- Examples:
  - tests/contracts/test_agent_ergonomics.py:34-39
  - tests/contracts/test_event_enum_coverage.py:37-41
  - tests/contracts/test_report_envelope_completeness.py:35-39
  - tests/golden/test_cli_mcp_parity.py:38-42
  - tests/integration/test_admin_tools.py:20-24
  - tests/integration/test_memory_layer.py:28-32
  - tests/integration/test_playbook_layer.py:26-30
  - tests/integration/test_report_risk.py:22-26
  - tests/integration/test_fixture_seed.py:17-21
- Static scan found 252 occurrences across tests of the combined patterns:
  mcp_call("journal.init"), def home(...), fixture_home, _init_home, tmp_path / "home".
- Repeated MCP wrappers also appear in many files:
  - tests/contracts/test_agent_ergonomics.py:42-44
  - tests/golden/test_cli_mcp_parity.py:60-67
  - tests/integration/test_memory_layer.py:35 etc.
  - tests/integration/test_playbook_layer.py:33 etc.
  - tests/integration/test_review_bundle_contract.py:42 etc.
- CLI wrappers are duplicated with slightly different implementations:
  - tests/contracts/test_agent_ergonomics.py:47-58 uses subprocess with PYTHONPATH=src.
  - tests/golden/test_cli_mcp_parity.py:45-57 invokes cli_main directly and captures stdout.

Cost / complexity:
- Low to medium.
- A bounded refactor can add shared fixtures/helpers without changing application behavior:
  - initialized_home
  - mcp_env(home, tool, args=None, actor_id="agent:default", request_id=None)
  - cli_result(...)
  - possibly normalize_envelope(...)
- The main migration cost is updating imports/call sites gradually; this can be done file-by-file.

Bounded shape:
- Add shared test helpers under tests/conftest.py or tests/support.py.
- Keep local wrappers where behavior is intentionally unique, e.g. subprocess CLI checks vs in-process CLI checks.
- Avoid changing test semantics; only replace exact boilerplate.

Behavior preservation:
- Each test should still get isolated tmp_path-backed home unless explicitly module-scoped.
- Preserve actor_id/request_id defaults and current assertions.
- Do not change test data or expected envelopes.

Validation:
- pytest tests/contracts tests/golden tests/integration -q
- pytest tests -q
- For staged migration, run touched files first, e.g.:
  pytest tests/contracts/test_agent_ergonomics.py tests/golden/test_cli_mcp_parity.py -q

Overlap notes:
- This is not a bug/deadcode finding. It is test harness simplification.
- Prior bughunt/deadcode artifacts mention tests-fixtures coverage but did not appear to own this exact simplification as a current bug.


Candidate TESTS-SIMPLIFY-002
Title: Replace copy-pasted minimal SQLite seed SQL with explicit test seed builders.
Domain: tests-fixtures
Type: simplification
Priority: high
Confidence: high

Evidence:
- Several integration tests define their own direct-SQL _db and _seed_minimal helpers with overlapping venue/instrument/thesis/forecast/decision/source/outcome rows.
- Examples:
  - tests/integration/test_append_only.py:38-80
    - _db opens db at tmp_path / "home"
    - _seed_minimal inserts venues, instruments, events, theses, forecasts, forecast_outcomes, snapshots, decisions, decision_tags, outcomes, sources, edges, position_events, forecast_scores, signals.
  - tests/integration/test_edges.py:14-39
    - _db and _seed_minimal insert venues, instruments, theses, forecasts, decisions, sources, outcomes.
  - tests/integration/test_edge_endpoint_audit.py:13-20 and following
  - tests/integration/test_p1_stub_columns.py:20-26 and following
- Static helper inventory shows repeated helpers:
  - _db in test_append_only.py, test_edge_endpoint_audit.py, test_edges.py, test_idempotency.py, test_p1_stub_columns.py, test_schema.py, test_signals_schema.py, test_transactions.py
  - _seed_minimal in test_append_only.py, test_edge_endpoint_audit.py, test_edges.py, test_p1_stub_columns.py
- These direct SQL fixtures are brittle because schema column additions or default changes require multiple SQL blobs to be updated.

Cost / complexity:
- Medium.
- Direct SQL is sometimes intentional to test storage constraints below tool-layer validation, so this should not be replaced blindly with mcp_call.
- A dedicated tests/support_db.py can preserve direct SQL while centralizing canonical row builders.

Bounded shape:
- Introduce small direct-SQL builders:
  - open_test_db(tmp_path)
  - seed_venue(conn, id="v_1", ...)
  - seed_instrument(conn, id="i_1", venue_id="v_1", ...)
  - seed_minimal_ledger(conn, include_events=False, include_signals=False, include_position=False)
- Keep fixture shape explicit and opt-in by flags so each test can state which rows matter.
- Do not route append-only/storage tests through public tools where the test explicitly needs raw SQL.

Behavior preservation:
- Preserve current IDs such as v_1, i_1, t_1, f_1, d_1, s_1, o_1.
- Preserve timestamps and actor IDs.
- Preserve direct SQL writes in tests checking storage-level constraints.

Validation:
- pytest tests/integration/test_append_only.py tests/integration/test_edges.py tests/integration/test_edge_endpoint_audit.py tests/integration/test_p1_stub_columns.py -q
- pytest tests/integration/test_schema.py tests/integration/test_transactions.py -q
- pytest tests -q

Overlap notes:
- Not a deadcode/removal recommendation.
- This is simplification/investigation because direct SQL has legitimate reachability in storage-level tests.


Candidate TESTS-SIMPLIFY-003
Title: Consolidate repeated venue/instrument/thesis/scoring setup flows used through MCP.
Domain: tests-fixtures
Type: simplification
Priority: medium-high
Confidence: high

Evidence:
- Many tests build the same minimal MCP graph:
  venue.add -> instrument.add -> thesis.add -> forecast.add -> outcome.add / decision.add
- Examples:
  - tests/contracts/test_agent_ergonomics.py:61-68 defines _seed_venue_instrument.
  - tests/contracts/test_event_enum_coverage.py:60 onward defines a similar _seed_venue_instrument.
  - tests/integration/test_scoring_lifecycle.py:44 onward defines _setup_venue_instr_thesis.
  - tests/integration/test_scoring_p1.py:23-25 defines _setup with venue.add and instrument.add, then thesis.
  - tests/golden/test_cli_mcp_parity.py:88-120 manually creates venue/instrument/thesis for validation parity.
  - tests/integration/test_report_risk.py has _instrument, _thesis_for, _closed_position.
  - tests/integration/test_report_opportunity.py has _instrument, _seed_decision_path, _report, _record.
- Helper inventory found many localized seed helpers:
  - _seed_venue_instrument
  - _seed_instrument
  - _seed_decision
  - _seed_resolved_forecast
  - _seed_scored_forecast_for_actor
  - _seed_one_scored_forecast
  - _setup_venue_instr_thesis
  - _seed_decision_path
  - _closed_position
- These are close enough to centralize common primitive builders while keeping scenario-specific helpers local.

Cost / complexity:
- Medium.
- The danger is over-abstracting scenario intent; a small builder API is preferable to a large fixture factory.

Bounded shape:
- Add a tiny tests/support_builders.py with primitives:
  - add_venue(home, name="PM", kind="prediction_market")
  - add_instrument(home, venue_id=None, title="Test", asset_class="prediction_market")
  - add_thesis(home, instrument_id, side="yes", body="...")
  - add_binary_forecast(home, thesis_id, p_yes=0.6, yes_label="YES")
  - add_resolved_outcome(home, instrument_id, label="YES")
- Tests can still define readable scenario-level helpers using these primitives.

Behavior preservation:
- Keep all idempotency keys, actor IDs, and expected labels when tests rely on them.
- Avoid changing envelope assertions.
- Central builders should return the same data shape currently used by tests: envelope or ID, but be consistent.

Validation:
- pytest tests/contracts/test_event_enum_coverage.py tests/integration/test_scoring_lifecycle.py tests/integration/test_scoring_p1.py -q
- pytest tests/integration/test_report_calibration.py tests/integration/test_report_risk.py tests/integration/test_report_opportunity.py -q
- pytest tests -q

Overlap notes:
- This is not deletion; it reduces copy-paste fixture construction and schema-change blast radius.


Candidate TESTS-SIMPLIFY-004
Title: Split or mark dogfood final verification to avoid normal-suite overcoupling and mutable shared fixture effects.
Domain: tests-fixtures
Type: simplification / investigation
Priority: medium
Confidence: medium-high

Evidence:
- tests/integration/test_final_dogfood_verification.py is a large 421-line integration gate with:
  - module-scoped fixture_home at lines 36-47 that initializes and fixture-seeds one shared journal.
  - 16 PRD dogfood assertions sharing that journal.
  - test_p7_adherence_rows_present_and_reportable mutates the shared fixture by adding three adherence rows at lines 169-199.
  - test_dogfood_full_repo_suite_passes at lines 388-421 shells out to run pytest again, although it is currently opt-in via TRADE_TRACE_RUN_DOGFOOD_FULL_SUITE.
- The file itself documents prior runtime/blast-radius concern:
  - lines 27-33: nested pytest invocation duplicates CI and is off by default.
  - lines 400-405: nested run multiplies runtime by ~2x and lets unrelated errors obscure the dogfood gate.
- Because tests share one module-scoped seeded DB and one test mutates it, ordering assumptions are subtle. It currently likely works because no later tests depend on pre-p7 adherence counts, but the coupling is non-obvious.

Cost / complexity:
- Low to medium.
- The nested full-suite issue has already been mitigated by env-gated skip, so do not file as a bug.
- Remaining simplification is to make dogfood invariants less order-sensitive and easier to maintain.

Bounded shape:
- Keep the dogfood fixture_seed coverage.
- Options:
  1. Move the opt-in nested pytest close-condition into a separate explicitly named test module or CI/manual script so normal collect still sees the skip but the dogfood file is not responsible for whole-suite orchestration.
  2. Split mutable p7 setup into its own isolated home or seed the fixture to already meet the adherence floor, avoiding mutation of the module-shared fixture.
  3. Group pure SQL count assertions through a local helper that opens the DB once per test or use a read-only query helper, but avoid expanding abstraction.

Behavior preservation:
- The dogfood acceptance criteria remain the same.
- The full-suite rerun remains available only by explicit opt-in.
- No reduction in PRD §10.1/§10.2 assertion coverage.

Validation:
- pytest tests/integration/test_final_dogfood_verification.py -q
- TRADE_TRACE_RUN_DOGFOOD_FULL_SUITE=1 pytest tests/integration/test_final_dogfood_verification.py::test_dogfood_full_repo_suite_passes -q
- pytest tests -q

Overlap notes:
- Prior no-tech-debt/debt context appears to have addressed the nested suite runtime by skipping it by default; this candidate deliberately scopes only the remaining simplification/ordering concern.


Candidate TESTS-SIMPLIFY-005
Title: Factor repeated report envelope/meta assertions into reusable assertions.
Domain: tests-fixtures
Type: simplification
Priority: medium
Confidence: medium

Evidence:
- Report-oriented tests repeat similar patterns around:
  - calling report tools via _mcp/_envelope/_env
  - asserting env.ok
  - asserting standard meta fields, sample warnings, truncated/cursor behavior, unsupported filter errors
- Examples:
  - tests/contracts/test_report_envelope_completeness.py defines _envelope_dict and _seed_scored_forecasts and tests standard report meta across many report tools.
  - tests/integration/test_report_calibration.py defines _envelope and many assertions on warnings, record_ids, truncation, filter rejection.
  - tests/integration/test_report_filter.py tests report filter schema and unsupported leaves across many reports.
  - tests/integration/test_report_sample_warnings.py repeats warning checks for mistakes/pnl.
  - tests/integration/test_report_unscored_velocity.py and test_report_pnl_watchlist.py repeat empty-db and registered-tool patterns.
- Helper inventory shows many report files defining local _env/_envelope/home wrappers:
  - test_report_calibration.py
  - test_report_coach.py
  - test_report_compare.py
  - test_report_opportunity.py
  - test_report_pnl_watchlist.py
  - test_report_risk.py
  - test_report_tag_aggregates.py
  - test_report_unscored_velocity.py

Cost / complexity:
- Low to medium.
- A small assertion helper is safe; large fixture merging could obscure report-specific expectations.

Bounded shape:
- Add reusable assert helpers:
  - assert_ok(env)
  - assert_report_meta_complete(env)
  - assert_validation_error(env, field=None)
  - assert_sample_warning(env, present=True, contains=None)
- Keep report-specific seed data local unless it exactly matches an existing shared builder from Candidate 003.

Behavior preservation:
- Assertions remain equivalent, just less repeated.
- Keep explicit tests for each report tool and each edge case.

Validation:
- pytest tests/contracts/test_report_envelope_completeness.py -q
- pytest tests/integration/test_report_* -q
- pytest tests -q

Overlap notes:
- Not a duplicate of report implementation simplification; this is only test assertion/harness simplification.

No recommended deletion/removal:
- I did not find a strong reachability/deadcode proof in this lane.
- All candidates are behavior-preserving simplification or bounded investigation, not removal.

Issues encountered:
- The first shell attempt used python, but only python3 is installed; reran successfully with python3.
- search_files only accepts a single path, so one multi-path search attempt failed; I retried with specific paths.
- Workspace had pre-existing modified/untracked files, but I made no edits.