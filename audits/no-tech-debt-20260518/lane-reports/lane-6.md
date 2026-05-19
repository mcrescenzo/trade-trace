Read-only test-debt review completed for /home/hermes/code/trade-trace at HEAD a33e676ec9d22d6ec268686424521a3d2586f9dd.

What I did:
- Inspected in-scope test harness/config:
  - tests/conftest.py
  - tests/test_smoke.py
  - tests/test_timestamps.py
  - tests/contracts/*
  - tests/golden/*
  - tests/integration/*
  - tests/property/*
  - pyproject.toml pytest config
- Ran collection and targeted test commands:
  - git rev-parse HEAD && git status --short && python -m pytest --collect-only ... failed because python is not installed as python.
  - python3 -m pytest --collect-only -q tests/conftest.py tests/test_smoke.py tests/test_timestamps.py tests/contracts tests/golden tests/integration tests/property
    - Result: 734 tests collected in 0.15s.
  - python3 -m pytest -q tests/property tests/golden tests/contracts --durations=10
    - Result: 130 passed, 1 failed in 2.06s.
  - python3 -m pytest -q tests/integration/test_fixture_seed.py tests/integration/test_final_dogfood_verification.py --durations=10
    - Result: 22 passed, 1 failed in 2.74s.
- Searched for harness smells:
  - duplicated fixtures/helpers
  - subprocess pytest-in-pytest
  - version pinning/golden drift
  - randomness/time-bound assertions
  - pytest config gaps

Important workspace note:
- The repo was already dirty before my review:
  - Modified source files under src/trade_trace/events, reports, tools.
  - Untracked audits/ and docs/audits/.
- I made no edits.

Structured technical-debt candidates:

1. Golden tests hard-code release version and are already stale against project metadata

Severity: High
Category: docs-contract-drift / tooling-drift / golden-test debt
Files:
- tests/golden/test_journal_status_parity.py:70
- tests/test_smoke.py:9
- pyproject.toml:7

Evidence:
- pyproject.toml declares version = "0.0.1rc0".
- tests/golden/test_journal_status_parity.py asserts:
  - cli_env["data"]["package_version"] == "0.0.1"
- tests/test_smoke.py similarly asserts:
  - trade_trace.__version__ == "0.0.1"
- Targeted contract/golden/property run failed:
  - tests/golden/test_journal_status_parity.py::test_journal_status_parity
  - AssertionError: '0.0.1rc0' != '0.0.1'

Why this is test debt:
- The golden test is acting as a stale release gate rather than a transport-contract oracle.
- It already blocks the contract/golden lane despite CLI/MCP parity itself passing immediately before the hard-coded value check.
- Future version bumps will require manually updating unrelated golden expectations, increasing release friction and creating false failures.

Bounded paydown:
- Centralize expected package version from the package/version module or project metadata.
- Keep contract-version pins explicit where intentional, but avoid hard-coding package release versions in parity/golden tests unless the contract requires that exact public value.
- Add one focused version-consistency test that compares pyproject/package/status output instead of duplicating literal versions across smoke/golden tests.

2. Dogfood final verification embeds a full pytest subprocess inside pytest

Severity: High
Category: slow/misleading harness / maintenance hotspot
File:
- tests/integration/test_final_dogfood_verification.py:379-396

Evidence:
- test_dogfood_full_repo_suite_passes runs:
  - sys.executable -m pytest -q --deselect tests/integration/test_final_dogfood_verification.py::test_dogfood_full_repo_suite_passes
- Targeted run failed because the inner full-suite collection hit an unrelated security test import error:
  - ImportError: cannot import name 'SECRET_PATTERNS' from trade_trace.exporter
  - This made tests/integration/test_final_dogfood_verification.py fail even though the dogfood fixture criteria had otherwise passed.
- The inline comment says “use -p no:cacheprovider”, but the command does not include -p no:cacheprovider, indicating harness/comment drift.

Why this is test debt:
- A single integration test recursively re-runs the whole repo suite, turning any unrelated collection/runtime failure into a dogfood test failure.
- It duplicates CI’s role, hides the real failing test behind an “inner suite failed” assertion, and can multiply runtime/cost as the suite grows.
- The test is not a bounded product contract; it is a meta-runner with broad blast radius.

Bounded paydown:
- Remove this nested full-suite subprocess from normal pytest collection or mark it as an explicit/manual gate.
- If the closure criterion must remain executable, move it to a script/CI job outside the suite, or gate it behind an opt-in marker not selected by default.
- Fix the stale comment/command mismatch if retained.

3. Fixture/helper sprawl across contract/integration/golden tests is creating repeated setup logic and inconsistent transport normalization

Severity: Medium
Category: fixture sprawl / maintenance hotspot
Files/examples:
- tests/conftest.py only adds src/ to sys.path and provides no domain fixtures.
- Repeated local helpers found in many files:
  - home(tmp_path)
  - _mcp(home, tool, args)
  - _cli(...)
  - _seed_venue_instrument(...)
- Examples:
  - tests/contracts/test_event_enum_coverage.py:38,44,60
  - tests/contracts/test_agent_ergonomics.py:35,42,47,61
  - tests/golden/test_cli_mcp_parity.py:39,45,60
  - tests/integration/test_memory_link.py:24,30
  - tests/integration/test_strategy_tools.py:24,30
  - tests/integration/test_memory_layer.py:29,35
  - tests/integration/test_fixture_seed.py:17
  - tests/integration/test_final_dogfood_verification.py:27,41
- Search found 57 repeated fixture/helper definitions in the test tree.

Why this is test debt:
- Transport semantics and normalization rules are copied rather than enforced from one shared harness.
- Different files normalize different fields:
  - tests/golden/test_cli_mcp_parity.py strips request_id, mcp_transport_hints, cli_human_hint, and generated IDs/timestamps.
  - tests/golden/test_journal_status_parity.py strips only transport hints/request_id.
- This increases the chance that future CLI/MCP contract changes require many hand edits and that parity tests drift subtly from each other.

Bounded paydown:
- Add shared fixtures/helpers in tests/conftest.py or tests/helpers.py:
  - initialized_home
  - mcp_call_json / cli_call_json
  - assert_cli_mcp_parity / normalize_envelope
  - seed_venue_instrument
- Migrate high-churn contract/golden tests first.
- Keep domain-specific setup local only when genuinely unique.

4. “Property” tests are example/random-sample tests with an inline reference implementation, not property-based regression tests against production behavior

Severity: Medium
Category: property-test debt / missing high-risk regression seam
File:
- tests/property/test_scoring_properties.py

Evidence:
- The file defines its own brier_binary reference implementation:
  - return (p_yes - y) ** 2
- Tests exercise that inline function, not production scoring/autoscore/report code.
- Random checks use fixed-seed pseudo-random samples:
  - random.Random(20260518)
  - 20_000 samples for expected mean near 1/3
- No Hypothesis/property-testing dependency is configured in pyproject.toml dev extras.

Why this is test debt:
- The tests prove the inline formula, not that production scoring/report paths obey it.
- A production scoring regression could pass this property lane if integration examples do not hit the mutated behavior.
- The large fixed sample gives the appearance of property coverage while still being a deterministic example test with extra runtime.

Bounded paydown:
- Either rename this lane to reference/example tests, or convert to actual production-facing property tests.
- Add a small shared public scoring function or assert through production autoscore/report outputs.
- If adopting property-based testing, add Hypothesis to dev extras and generate p/y cases with explicit invariants:
  - score in [0,1]
  - perfect forecast score = 0
  - maximally wrong score = 1
  - monotone with distance from truth
  - report aggregate equals mean of per-forecast production scores

5. Fixture seed tests include wall-clock performance assertion in default suite

Severity: Low/Medium
Category: flaky/time coupling
File:
- tests/integration/test_fixture_seed.py:143-153

Evidence:
- test_fixture_seed_completes_in_under_five_seconds uses time.monotonic() and asserts elapsed < 5.0.
- Targeted run was currently fast:
  - duration ~0.26s for this test
- But the assertion is host/load dependent and runs in normal integration collection.

Why this is test debt:
- Wall-clock caps in functional integration tests can become false failures under constrained CI, parallelism, virtualization, or coverage runs.
- It mixes performance acceptance with correctness tests.

Bounded paydown:
- Move to an explicit perf marker/job, or make the default test assert algorithmic/deterministic outcomes only.
- If retained, configure pytest markers and skip/xfail policy for slow/perf environments.

Coverage accounting:
- pyproject pytest config reviewed:
  - testpaths = ["tests"], addopts = "-ra"; no markers/timeouts configured.
- Collection coverage:
  - In-scope collection succeeded with python3: 734 tests collected.
- Contract/golden/property targeted execution:
  - 131 tests attempted.
  - 130 passed.
  - 1 failed due stale package_version golden.
- Fixture seed/final dogfood targeted execution:
  - 23 tests attempted.
  - 22 passed.
  - 1 failed due nested full-suite subprocess surfacing unrelated security import error.
- No test files were modified.

Files created or modified:
- None.

Issues encountered:
- The command using python failed because /usr/bin/python is not available; python3 works.
- Repository had pre-existing modified/untracked files; I did not touch them.
- Two targeted test failures were observed and recorded:
  - Stale golden package version expectation.
  - Pytest-in-pytest dogfood gate failing on unrelated inner-suite collection error.