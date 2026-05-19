What I did:
- Ran test collection and targeted/full pytest validation in /home/hermes/code/trade-trace.
- Inspected pytest config, test fixtures, and source paths needed to verify failures.
- Re-checked git status after test runs.

Commands run / results:
- git status --short && python -m pytest --collect-only -q
  - python not found; initial status showed only pre-existing untracked audit dirs.
- python3 -m pytest --collect-only -q
  - 1046 tests collected successfully.
- python3 -m pytest -q tests/integration/test_fixture_seed.py tests/integration/test_final_dogfood_verification.py tests/contracts/test_agent_ergonomics.py tests/security/test_no_network_default.py
  - 50 passed, 2 skipped.
- python3 -m pytest -q
  - 1038 passed, 6 skipped, 2 failed.
- python3 -m pytest -q tests/golden/test_journal_status_parity.py::test_journal_status_parity tests/integration/test_ndjson_streaming.py::test_exit_code_one_on_other_error; git status --short
  - Both targeted tests failed; git status showed only pre-existing untracked dirs plus audits/no-tech-debt-20260519T180002Z/ already present after suite activity, no tracked changes.
- tmp=$(mktemp -d); TRADE_TRACE_HOME="$tmp/home" python3 -m pytest -q tests/golden/test_journal_status_parity.py::test_journal_status_parity; rm -rf "$tmp"
  - 1 passed, confirming default-home contamination drives that failure.

Files opened/probed/search-reviewed:
- tests/conftest.py
- pyproject.toml
- tests/golden/test_journal_status_parity.py
- tests/integration/test_ndjson_streaming.py
- tests/security/test_mvp_boundary_audit.py
- src/trade_trace/storage/paths.py
- src/trade_trace/tools/review_bundle.py
- src/trade_trace/cli.py
- Search-reviewed tests/** for fixtures/env/tmp_path/HOME/TRADE_TRACE/subprocess/skip/xfail patterns.
- Search-reviewed src/** for default home, schema_version, review.bundle registration, exit code mapping.

Areas not inspected / why:
- Did not individually open all 177 test/source files due time; instead used full-suite execution plus targeted searches around cross-cutting fixture/env/CLI reliability patterns.
- Did not run ruff/mypy because lane is tests/fixtures validation reliability and pytest produced concrete failures; no installs/package manager use.
- Did not inspect Beads DB or mutate issues per task constraints.

Side-effect caveats:
- Read-only from my side: no intentional file edits, no Beads changes, no package installs.
- Pytest created/used temporary files under /tmp and may have interacted with default ~/.trade-trace due an existing test bug.
- git status after commands showed untracked audit dirs only:
  - audits/no-tech-debt-20260519T180002Z/
  - docs/audits/bughunt-20260519T175941Z/
  - docs/audits/simplification-20260519T180020Z/
  No tracked files modified.

Candidate records:

id: TT-BUGHUNT-TESTS-001
title: journal.status golden parity test reads the developer’s real default Trade Trace home, making the suite fail when ~/.trade-trace is initialized
severity: P2
confidence: confirmed
domain: tests-fixtures-crosscutting
bug_class: test isolation / environment contamination / false red
evidence_type: full-suite failure + targeted reproduction + source/test inspection

evidence:
- tests/golden/test_journal_status_parity.py:
  - lines 33-43 call mcp_call("journal.status", {}, ...) with no home override.
  - lines 48-56 call cli_main([... "journal", "status"], ...) with no --home.
  - line 73 asserts cli_env["data"]["schema_version"] == 0.
- src/trade_trace/storage/paths.py:
  - lines 16-22 default_home() uses TRADE_TRACE_HOME, else XDG_DATA_HOME/trade-trace, else Path.home() / ".trade-trace".
- Full suite failed:
  - tests/golden/test_journal_status_parity.py::test_journal_status_parity
  - E assert 10 == 0 at line 73.
- Targeted isolated env passed:
  - TRADE_TRACE_HOME="$tmp/home" python3 -m pytest -q tests/golden/test_journal_status_parity.py::test_journal_status_parity
  - 1 passed.

failure mode:
- The test is supposed to validate CLI/MCP envelope parity and M0 uninitialized status, but it uses the process default home instead of a tmp_path fixture or monkeypatched TRADE_TRACE_HOME.
- If the runner has a real initialized Trade Trace DB, journal.status returns schema_version 10 instead of 0, causing a false test failure.
- If a runner has no default DB, the test passes, so reliability depends on machine state.

observed vs expected:
- Observed: schema_version was 10 in this environment and the test failed.
- Expected: The test should be hermetic and force an uninitialized temporary home, so schema_version is deterministically 0 regardless of the user’s real ~/.trade-trace or XDG_DATA_HOME.

reproduction/trace path:
- From /home/hermes/code/trade-trace:
  - python3 -m pytest -q tests/golden/test_journal_status_parity.py::test_journal_status_parity
  - Fails with E assert 10 == 0 when default home is initialized.
  - TRADE_TRACE_HOME="$(mktemp -d)/home" python3 -m pytest -q tests/golden/test_journal_status_parity.py::test_journal_status_parity
  - Passes.

duplicate/overlap analysis:
- Not a duplicate of the known stale version tests. This is a separate fixture/isolation bug: test behavior depends on the runner’s default Trade Trace home.
- Related broadly to docs/CI validation reliability but materially different from broken docs commands/links.

proposed Bead body:
- The journal.status parity golden test is not hermetic. It calls both MCP and CLI journal.status without a home override, then asserts schema_version == 0. Because default_home() resolves to TRADE_TRACE_HOME/XDG_DATA_HOME/~/.trade-trace, any developer or CI runner with an initialized default Trade Trace home gets schema_version > 0 and the suite fails. Make the test use tmp_path and pass --home / {"home": ...}, or monkeypatch TRADE_TRACE_HOME to a fresh temporary directory, so the M0 schema_version=0 assertion is deterministic.

acceptance criteria:
- test_journal_status_parity uses an isolated tmp_path/default home and no longer reads ~/.trade-trace or XDG_DATA_HOME unless explicitly monkeypatched to the temp dir.
- The test passes both when the user’s real default home is absent and when it contains an initialized schema_version 10 DB.
- Full pytest suite no longer fails on this test due local machine state.

validation command:
- python3 -m pytest -q tests/golden/test_journal_status_parity.py::test_journal_status_parity
- Optional robustness check:
  - TRADE_TRACE_HOME=/path/to/initialized/home python3 -m pytest -q tests/golden/test_journal_status_parity.py::test_journal_status_parity

risks/uncertainty:
- Confirmed. The only nuance is whether this test intentionally exercises default-home behavior; if so, that should be separated from the schema_version=0 M0 assertion and isolated via monkeypatch.

---

id: TT-BUGHUNT-TESTS-002
title: NDJSON exit-code test still expects review.bundle to be unsupported even though review.bundle is now implemented and returns success
severity: P2
confidence: confirmed
domain: tests-fixtures-crosscutting
bug_class: stale test assertion / false red
evidence_type: full-suite failure + targeted reproduction + source/test inspection

evidence:
- tests/integration/test_ndjson_streaming.py:
  - lines 163-173 define test_exit_code_one_on_other_error.
  - lines 166-168 comment says UNSUPPORTED_CAPABILITY (review.bundle) should exit 1.
  - lines 169-173 run CLI ["review", "bundle", "--filter-json", "{}"] and assert rc == 1.
- src/trade_trace/tools/review_bundle.py:
  - lines 568-583 register review.bundle with _review_bundle_handler and a functional description.
- tests/security/test_no_network_default.py:
  - lines 82-86 explicitly include review.bundle among functional clusters under no_network.
  - line 137 lists ("review.bundle", "noop").
- Full suite failed:
  - tests/integration/test_ndjson_streaming.py::test_exit_code_one_on_other_error
  - E assert 0 == 1 at line 173.
- Targeted reproduction:
  - python3 -m pytest -q tests/integration/test_ndjson_streaming.py::test_exit_code_one_on_other_error
  - Fails with rc 0 instead of expected 1.

failure mode:
- The test uses review.bundle as a representative non-validation/non-invariant error path, expecting UNSUPPORTED_CAPABILITY and exit code 1.
- review.bundle has since become a registered functional tool; with an empty/default DB and "{}" filter it returns ok=true, so CLI exit code mapping correctly returns 0.
- This makes the test stale and causes a false red in the full suite.

observed vs expected:
- Observed: cli_main(["review", "bundle", "--filter-json", "{}"]) returned rc 0.
- Expected: The exit-code mapping test should trigger a real current error class, such as a known NOT_FOUND/STORAGE_ERROR/UNSUPPORTED_CAPABILITY tool that is still unsupported, or update expectations if review.bundle success is now the contract.

reproduction/trace path:
- From /home/hermes/code/trade-trace:
  - python3 -m pytest -q tests/integration/test_ndjson_streaming.py::test_exit_code_one_on_other_error
  - Fails at line 173 with E assert 0 == 1.
- Source trace:
  - cli.py lines 358-368 map ok=true to 0 and non-validation/non-invariant errors to 1.
  - review_bundle.py lines 568-583 shows review.bundle is now registered as functional, explaining ok=true/rc 0.

duplicate/overlap analysis:
- This overlaps thematically with stale tests, but is materially different from the known stale package-version assertion. It is a stale unsupported-capability assumption for a now-implemented tool.
- It is also distinct from missing malformed JSON envelope coverage.

proposed Bead body:
- test_exit_code_one_on_other_error in tests/integration/test_ndjson_streaming.py still assumes review.bundle is an UNSUPPORTED_CAPABILITY stub and asserts CLI rc == 1. review.bundle is now registered and implemented, and the same suite treats it as a functional no-network tool. The test now fails because CLI returns 0 for ok=true. Replace review.bundle with a currently failing non-validation/non-invariant scenario, or update/remove the stale unsupported review.bundle expectation.

acceptance criteria:
- The test exercises an actually current “other error” path and asserts rc == 1 only for an error envelope.
- review.bundle success is not used as an UNSUPPORTED_CAPABILITY fixture unless the tool is intentionally reverted to unsupported.
- python3 -m pytest -q tests/integration/test_ndjson_streaming.py::test_exit_code_one_on_other_error passes.
- Full suite no longer fails on the stale review.bundle assertion.

validation command:
- python3 -m pytest -q tests/integration/test_ndjson_streaming.py::test_exit_code_one_on_other_error
- python3 -m pytest -q tests/integration/test_ndjson_streaming.py tests/integration/test_review_bundle_contract.py

risks/uncertainty:
- Confirmed. Low implementation risk: choose a stable current NOT_FOUND or unsupported stub. Avoid using default-home-dependent errors for this fixture, or it may introduce another isolation bug.