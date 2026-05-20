# Lane packets — deadcode hunt 2026-05-20

Repo: `/home/hermes/code/trade-trace`
Mode: exhaustive read-only discovery lanes. Delegates were instructed not to edit files, delete files, or create/update Beads.

## Lane 1 — python-core-storage-security

Coverage: 43 assigned source files; direct inspection of clock, timestamps, credential keyring, storage database/policy/migrations, contracts, event log, tests for candidate validation. Commands included AST inventory, import/dynamic import search, targeted git-grep, `python3 -m vulture src/trade_trace tests --min-confidence 60` (no findings), and targeted pytest (12 passed).

Reported candidates:
- DC-PY-CORE-001: `trade_trace.clock` Clock/SystemClock/FixedClock appear test/support-only after prior process-global accessor cleanup. Caveat: module comments explicitly say these stay; test support/public utility; recommended triage only.
- DC-PY-CORE-002: `EventRecord.to_jsonl_line` has no production exporter caller; only local call is `tests/integration/test_idempotency.py`. Exporter uses `_load_event` + `write_event_atomic`. Public method caveat.
- DC-PY-SEC-001: `security.keyring.delete_api_key` has no production caller; store/load have admin/memory callers; delete only in keyring test. Product capability caveat.
- DC-PY-STOR-001: `Database.ensure_user_only_permissions` has no repo-local caller; permission enforcement occurs at open/close. Public method/docstring caveat.

Rejected/keep leads: migrations are reachable through `MIGRATIONS`; security pattern API and credential key constants have runtime/tests; storage policy helpers are exported/tested migration policy surfaces.

## Lane 2 — tools-cli-mcp-reports

Coverage: 36 assigned files; inspected pyproject entrypoints, CLI dispatch, MCP list/call registration, `build_registry`, report tool registration, examples, AST register calls. Runtime registry probe found 67 registered tools, 67 unique CLI invocations, MCP names matched registry. Targeted CLI/MCP/schema tests: 39 passed. Ruff unused/import checks passed. Vulture unavailable.

Reported candidates: none.

Rejected/keep leads: low-reference helpers are handler callbacks, decorators, registry callbacks, public report exports, or aliases (`resolve.record` shares `outcome.add`).

## Lane 3 — console-backend-frontend

Coverage: 32 assigned console files; inspected Python console routes/static serving/reporting adapters, frontend sources/configs, pyproject package data, Vite config/static artifacts. Frontend validation: `npm --prefix frontend/console run typecheck` passed; `npm --prefix frontend/console run test` passed.

Reported candidates:
- DC-CONSOLE-001: unused direct frontend deps `@radix-ui/react-tabs` and `@tanstack/react-virtual`; only found in package.json/lockfile, no source/config imports.
- DC-CONSOLE-002: `trade_detail(conn, decision_id)` exported/tested/docs but no production HTTP route/frontend caller; public/read-model contract caveat.
- DC-CONSOLE-003: metric glossary/page explanation copy exported/tested but not consumed by backend routes or React UI; likely planned feature, do not delete without product decision.
- DC-CONSOLE-004: `encode_filter`/`summarize_filter` only used by tests/docs/exports while `decode_filter` is runtime-used by export route; however `encode_filter` supports route contract tests and planned filter URL producer; do not delete without product decision.

Rejected/keep leads: built static app assets are package data reachable through Vite config + FastAPI static mount + pyproject package-data; favicon served by /static and tested; browser/API routes not linked from UI are public routes and not dead.

## Lane 4 — tests-fixtures

Coverage: all 120 tracked `tests/` paths enumerated; inspected conftests, shared SQL builders, security schema audit helper, selected autouse/local fixtures. `pytest --collect-only -q tests` collected 1277 tests; console browser suite skipped due missing Playwright extra as expected.

Reported candidates: none new.

Duplicate-suppressed observation:
- `tests/security/_schema_audit.py::assert_required_tables_present` appears textually unused, but overlaps explicitly with prior resolved `security schema-audit helpers` theme; no new bead recommended.

Rejected/keep leads: pytest autouse fixtures, fixture injection, marker fixtures, browser fixtures, shared SQL builders, and schema helpers are reachable by pytest/imports.

## Lane 5 — docs-ci-config-audit

Coverage: root config/workflows/public docs command contracts; inspected `.claude/settings.json`, `.codex/hooks.json`, GitHub workflows, `.gitignore`, AGENTS/CLAUDE, README, SECURITY, pyproject, targeted docs. CLI help/probes run with `PYTHONPATH=src python3 -m trade_trace.cli ...`.

Reported candidates:
- DC-DOCS-001: embeddings docs still publish positional `tt journal config_set embeddings.provider ...` and stale `openai` provider value; live CLI requires `--key/--value` and enum `api:openai`.
- DC-DOCS-002: operability docs still mention removed restore flag `--from`; live help uses `--src`. (Backup `--to` was checked; live help uses `--dest`, but current grep only found stale restore `--from` in tracked docs.)
- DC-DOCS-003: model import docs inconsistently use `tt model import <path>` / `--path` while public schema/help advertises `--src`; `--path` may still be a compatibility alias, so lower-confidence and mergeable with DC-DOCS-001.

Rejected/keep leads: workflows are wired to reusable `_test.yml`; root hooks/config point to active `bd prime`; `.gitignore` intentionally ignores audit artifacts; markdown link scan had placeholder false positives and no clear missing tracked-file link.
