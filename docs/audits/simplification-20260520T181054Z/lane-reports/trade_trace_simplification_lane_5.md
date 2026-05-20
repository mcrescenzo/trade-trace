# Lane 5 status: completed

Read-only simplification review lane completed for tests/docs/build config in /home/hermes/code/trade-trace.

What I did:
- Verified repo state: branch main at ffcd97420bf44c846451bd5d39596d39437d6e3e, clean working tree.
- Inspected:
  - tests/
  - tests/docs/
  - docs/
  - .github/workflows/
  - pyproject.toml
  - frontend/console/package.json scripts
  - src/trade_trace/tools/fixture.py
- Ran read-only discovery commands:
  - pytest collection
  - helper/fixture duplication counting via AST
  - targeted fixture-seed test timing
  - docs test timing
  - file/line count accounting
- No edits, no Beads writes, no push/publish/delete.

Coverage accounting:
- tests/: 246 files total, including 120 Python test/helper files and 126 __pycache__ files present on disk.
- pytest collect-only: 1281 collected output lines, completed in 0.77s.
- docs/: 339 files, 40 markdown docs under docs/.
- .github/workflows/: 3 workflow files.
- src/trade_trace/tools/fixture.py: 687 lines.
- tests/integration/test_fixture_seed.py: 282 lines.
- frontend/console/package.json scripts reviewed: dev, build, test, typecheck.

Candidate records:

1. Candidate: Remove per-file `home` alias fixtures now that `initialized_home` exists.

Scope:
- tests/

Evidence:
- tests/conftest.py already provides shared fixture `initialized_home`.
- 37 test files still define a local `home` fixture.
- Many are pure aliases:
  - def home(initialized_home): return initialized_home
  - or the older repeated:
    - h = tmp_path / "home"
    - mcp_call("journal.init", {"home": str(h)})
    - return h
- Representative files:
  - tests/contracts/test_event_enum_coverage.py
  - tests/integration/test_fixture_seed.py
  - tests/integration/test_report_risk.py
  - tests/contracts/test_agent_ergonomics.py
  - tests/contracts/test_report_envelope_completeness.py
  - tests/golden/test_cli_mcp_parity.py

Test drag evidence:
- Repeated helper count from AST scan:
  - def home: 37 definitions across 37 files.
- The shared fixture already exists and its own docstring says it was introduced because “30+ tests previously redefined the same three-line `home` fixture”.
- Current state leaves the simplification half-applied: tests still carry compatibility aliases or duplicate init logic despite the shared substrate.

Simplification:
- Where a local fixture is only an alias, change tests to request `initialized_home` directly, or rename the shared fixture to `home` in conftest.py if that does not collide with specialized local fixtures.
- Keep specialized per-file fixtures only where they intentionally test custom init flows.

Intentional complexity check:
- Some local `home` fixtures may be contract examples or may intentionally bypass shared initialization for init/error tests.
- Do not blindly remove all 37. Filter to pure aliases and exact “tmp_path/home + journal.init” shapes.

Validation path:
- python3 -m pytest tests/contracts tests/integration tests/golden -q
- Also run any strict idempotency/init tests that might require custom home behavior.

Gap:
- I did not edit or produce a safe removal list because this lane is read-only.

Strength:
- Strong candidate.

2. Candidate: Consolidate repeated MCP/envelope dispatch helpers into shared test helpers.

Scope:
- tests/

Evidence:
- AST scan found repeated helper names:
  - def _mcp: 20 files
  - def _envelope: 12 files
  - def _db: 9 files
  - def _env: 16 files
- Representative repeated `_mcp` shape:
  - payload = {"home": str(home), **(args or {})}
  - return mcp_call(tool, payload, actor_id="agent:default")
- Representative repeated `_env` shape:
  - mcp_call(...).model_dump(mode="json", exclude_none=True)
  - or dispatch(...).model_dump(mode="json", exclude_none=True)
- Existing tests/_direct_sql_builders.py indicates the suite already accepts shared test helper modules.

Test drag evidence:
- At least 57 repeated helper definitions across the suite by name count alone.
- These helpers encode transport defaults such as actor_id, home injection, and JSON model_dump behavior, so any envelope/default change requires many edits and risks drift.

Simplification:
- Add a small shared helper module, e.g. tests/_mcp_helpers.py:
  - call_mcp(home, tool, args=None, actor_id="agent:default")
  - envelope_json(...)
  - init_home or initialized_home wrapper if needed
- Convert only exact duplicate helper bodies first.
- Leave domain-specific wrappers in place where helper names document scenario intent.

Intentional complexity check:
- Some duplication is valuable as contract examples in golden/contract tests.
- For user-facing examples, local helper code may improve readability.
- The safer first pass is integration/security tests, not docs-like contract demonstrations.

Validation path:
- python3 -m pytest tests/security tests/integration tests/contracts -q
- Optionally assert no behavior change by comparing collected tests before/after.

Gap:
- I did not inspect every helper body for semantic differences; this needs a mechanical grouping pass before edits.

Strength:
- Strong candidate.

3. Candidate: Split `journal.fixture_seed` into composable fixture builders/profiles.

Scope:
- src/trade_trace/tools/fixture.py
- tests/integration/test_fixture_seed.py
- console/reporting tests using mvp-eval-rich

Evidence:
- src/trade_trace/tools/fixture.py is 687 lines.
- It mixes:
  - deterministic clock/id generation
  - generic dispatch wrapper
  - mvp-eval base seed
  - mvp-eval-rich overlay
  - diagnostic source/outcome fixtures
  - reporting/console position fixtures
- Tests using fixture seed:
  - tests/integration/test_fixture_seed.py: 282 lines
  - tests/console_browser/conftest.py
  - tests/integration/test_console_reporting_adapter.py
  - tests/integration/test_console_reporting_read_model.py
  - tests/contracts/test_console_http_routes.py
- Targeted runtime:
  - python3 -m pytest tests/integration/test_fixture_seed.py -q
  - 9 passed, 1 skipped in 3.29s
  - wall time 3.67s

Test drag evidence:
- A single large seed substrate supports both dogfood, diagnostics, console reporting, and browser tests.
- mvp-eval-rich tests repeatedly seed a broad data set to verify narrow properties such as closed/open positions or declared risk.
- Because the seed is monolithic, small fixture changes can affect many unrelated tests.

Simplification:
- Keep public tool `journal.fixture_seed` behavior stable.
- Internally split into modules/functions by profile:
  - deterministic IDs/clock helpers
  - base journal primitives
  - diagnostic overlays
  - reporting/position overlay
  - profile registry mapping target -> ordered builders
- For narrow console/reporting tests, consider a smaller read-model fixture profile if behavior allows.

Intentional complexity check:
- The public deterministic dogfood fixture is intentionally broad and contract-like.
- Determinism and row-count coverage are important behavior, not accidental complexity.
- Simplify internals and test setup reuse; do not reduce public fixture coverage without a product decision.

Validation path:
- python3 -m pytest tests/integration/test_fixture_seed.py -q
- python3 -m pytest tests/integration/test_console_reporting_adapter.py tests/integration/test_console_reporting_read_model.py tests/contracts/test_console_http_routes.py -q
- Verify deterministic hashes remain identical for mvp-eval and mvp-eval-rich.

Gap:
- Did not inspect lower half of fixture.py in detail beyond counts/usages due read-only summary focus.

Strength:
- Medium/strong candidate.

4. Candidate: Fix/simplify release workflow version check around dynamic versioning.

Scope:
- .github/workflows/workflow.yml
- pyproject.toml
- tests/docs/test_markdown_links.py
- docs/RELEASE_CHECKLIST.md

Evidence:
- pyproject.toml uses:
  - [project] dynamic = ["version"]
  - [tool.setuptools.dynamic] version = {attr = "trade_trace.version.__version__"}
- tests/docs/test_markdown_links.py explicitly asserts:
  - pyproject must declare version dynamically
  - pyproject must not have literal project.version
- But .github/workflows/workflow.yml “Verify tag matches package versions” still runs:
  - tomllib.loads(...pyproject.toml...)['project']['version']
- With dynamic versioning, this key does not exist, so tag publish workflow would fail before comparing versions.
- docs/RELEASE_CHECKLIST.md still says releases are gated on a tag matching pyproject.toml, which is now stale relative to the dynamic-version contract.

Test/build drag evidence:
- CI and tests encode one source of truth (`src/trade_trace/version.py`), while publish workflow still checks two sources.
- This creates release-only failure risk and duplicate release-contract surfaces.

Simplification:
- Remove pyproject project.version lookup from publish workflow.
- Compare tag only to `src/trade_trace/version.py` or use package metadata after build:
  - python -m build
  - python -m twine check
  - inspect wheel metadata version if desired.
- Update release checklist wording to “tag matches src/trade_trace/version.py / built metadata”.

Intentional complexity check:
- A release tag/version check is intentional and valuable.
- The accidental complexity is checking a removed literal source of truth.

Validation path:
- Locally emulate workflow snippet:
  - TAG=<version from version.py>
  - parse version.py
  - optionally build wheel and inspect metadata.
- Run:
  - python3 -m pytest tests/docs/test_markdown_links.py -q
  - python3 -m build
  - python3 -m twine check --strict dist/*

Gap:
- I did not edit workflow or docs because read-only.

Strength:
- Strong candidate.

5. Candidate: Reduce docs contract duplication/special casing by extracting markdown-doc validation helpers.

Scope:
- tests/docs/test_markdown_links.py
- tests/docs/test_status_headers.py
- docs/architecture docs

Evidence:
- docs tests contain local filesystem walking, markdown parsing, heading slugging, and status taxonomy regex.
- tests/docs/test_markdown_links.py also includes a release/version canonical-source check, which is not really a markdown-link concern.
- tests/docs/test_status_headers.py independently walks architecture docs and checks taxonomy.
- Running docs tests showed current known status-header failures:
  - tests/docs/test_status_headers.py failed.
  - This appears to overlap with known coordinator context about docs Status header issues, so I am not filing it as a new bug.

Test drag evidence:
- docs tests are currently small by runtime:
  - docs test wall time 0.39s
- Drag is mostly conceptual/maintenance, not execution time:
  - markdown link checking
  - anchor slugging
  - architecture taxonomy
  - dynamic version source check
  are mixed in two files.

Simplification:
- Extract a shared tests/docs/_markdown.py or tests/_docs_helpers.py:
  - candidate_doc_files()
  - github_slugify()
  - anchors_in()
  - relative_markdown_links()
- Move dynamic-version canonical check to a separate test file, e.g. tests/contracts/test_version_source.py or tests/build/test_version_source.py.

Intentional complexity check:
- Docs contract tests are intentionally explicit and readable.
- Do not over-engineer; only extract if adding more docs checks or fixing status taxonomy requires touching both files.

Validation path:
- python3 -m pytest tests/docs -q
- Note current status-header failure must be accounted for separately and is known.

Gap:
- Current docs tests fail due existing known header issues; simplification validation would need either xfail/baseline handling or fixing known docs issue in another lane.

Strength:
- Medium candidate.

6. Candidate: Consider whether tracked/generated cache artifacts should be excluded from review/test tree noise.

Scope:
- tests/**/__pycache__
- docs/**/__pycache__ if tracked or present

Evidence:
- File scan found:
  - tests/: 246 files total, 126 under __pycache__
  - docs/: 339 files, 1 __pycache__
- These are present on disk and dominate file discovery output.
- I did not verify whether they are tracked by git in this lane.

Test drag evidence:
- Discovery and review noise: initial tests file listing was truncated at 200 results largely because __pycache__ files appeared first.
- Runtime impact on pytest collection appears small, but human/tooling review noise is real.

Simplification:
- If tracked: remove from version control and ensure .gitignore excludes __pycache__/ and *.pyc.
- If untracked: clean local workspace caches outside this read-only lane, or configure review scripts to ignore them.

Intentional complexity check:
- Generated caches should not be source artifacts.
- If intentionally retained for a reason, document that reason; otherwise accidental complexity.

Validation path:
- git ls-files 'tests/**/__pycache__/*' 'docs/**/__pycache__/*'
- git status --ignored --short
- python3 -m pytest --collect-only -q

Gap:
- I did not run git ls-files for cache tracking status because this candidate is lower priority and no edits were allowed.

Strength:
- Medium candidate.

Non-candidates / no action recommended:
- frontend/console/package.json scripts are simple and conventional:
  - dev: vite --host 127.0.0.1
  - build: tsc -b && vite build
  - test: vitest run
  - typecheck: tsc -b
  No simplification candidate found in package scripts alone.
- .github/workflows/ci.yml and _test.yml are already simplified through a reusable workflow. Aside from the publish workflow dynamic-version issue, the workflow split looks intentional.

Issues encountered:
- python was not installed as `python`; used `python3`.
- `python3 -m pytest tests/docs -q` failed because tests/docs/test_status_headers.py reports missing/invalid Status headers in several architecture console docs. This matches the coordinator’s known docs Status header bug area, so I did not treat it as a fresh simplification candidate.
- No files were created or modified. Working tree remained clean.
