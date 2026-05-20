# Domain map — repo simplification review 20260520

```yaml
- domain_id: cli-mcp-contracts
  paths:
    - src/trade_trace/cli.py
    - src/trade_trace/mcp_server.py
    - src/trade_trace/core.py
    - src/trade_trace/contracts/
    - src/trade_trace/tools/_helpers.py
    - src/trade_trace/tools/errors.py
    - src/trade_trace/tools/_examples.py
    - tests/contracts/
    - tests/golden/
  entrypoints:
    - tt / trade-trace CLI
    - trade-trace-mcp stdio server
    - default_registry/tool.schema
  responsibilities:
    - CLI grammar and exit/envelope behavior
    - MCP/tool schema projection
    - registry metadata and derived schemas
  neighboring_domains:
    - ledger-tools-projections
    - reports-memory-playbook
    - tests-docs-build
  complexity_lenses:
    - duplicate-schema-example-plumbing
    - duplicated-registry-projection
    - error-contract-drift
  tests:
    - tests/contracts/test_cli_parse_kv_args.py
    - tests/contracts/test_tool_schema_runtime_parity.py
    - tests/contracts/test_agent_ergonomics.py
    - tests/golden/test_cli_mcp_parity.py
  validation_commands:
    - pytest -q tests/contracts/test_cli_parse_kv_args.py tests/contracts/test_tool_schema_runtime_parity.py tests/contracts/test_cli_command_help.py tests/golden/test_cli_mcp_parity.py
  review_priority: high
  lane_prompt_target: lane_0

- domain_id: storage-events-security
  paths:
    - src/trade_trace/storage/
    - src/trade_trace/events/
    - src/trade_trace/exporter.py
    - src/trade_trace/security/
    - src/trade_trace/tools/admin.py
    - tests/security/
    - tests/integration/test_migrations*.py
  entrypoints:
    - journal.init/backup/restore/config
    - outbox export/write_event_atomic
    - migrations runner
  responsibilities:
    - SQLite lifecycle, migrations, append-only and outbox semantics
    - file permissions and path containment
    - backup/restore security posture
  neighboring_domains:
    - ledger-tools-projections
    - tests-docs-build
  complexity_lenses:
    - duplicate-permission-helpers
    - path-validation-tangled-ownership
    - parallel-migration-metadata
    - jsonl-envelope-duplication
  tests:
    - tests/security/test_file_permissions.py
    - tests/security/test_restore_manifest_paths.py
    - tests/integration/test_migrations.py
    - tests/integration/test_migrations_schema_hash.py
    - tests/integration/test_outbox_export.py
  validation_commands:
    - uv run pytest tests/integration/test_outbox_export.py tests/integration/test_migrations.py tests/integration/test_migrations_schema_hash.py tests/security -q
  review_priority: high
  lane_prompt_target: lane_1

- domain_id: ledger-tools-projections
  paths:
    - src/trade_trace/tools/ledger.py
    - src/trade_trace/models/ledger.py
    - src/trade_trace/projections.py
    - src/trade_trace/events/unit_of_work.py
  entrypoints:
    - venue/instrument/snapshot/thesis/forecast/decision/outcome/source tools
    - journal.rebuild_projections
  responsibilities:
    - ledger writes, idempotency, event emission, scoring, projections
  neighboring_domains:
    - storage-events-security
    - reports-memory-playbook
  complexity_lenses:
    - large-handler-decomposition
    - duplicate-idempotent-write-skeletons
    - tuple-index-state-branching
    - source-attach-metadata-scattering
  tests:
    - tests/integration/test_ledger_event_emission.py
    - tests/integration/test_projection_rebuild.py
    - tests/integration/test_manual_ledger_flow.py
  validation_commands:
    - python3 -m pytest tests/integration/test_projection_rebuild.py tests/integration/test_ledger_event_emission.py tests/integration/test_memory_layer.py::test_memory_node_stats_rebuildable_from_events -q
  review_priority: high
  lane_prompt_target: lane_2

- domain_id: reports-memory-playbook
  paths:
    - src/trade_trace/reports/
    - src/trade_trace/tools/reports.py
    - src/trade_trace/tools/memory.py
    - src/trade_trace/tools/playbook.py
    - src/trade_trace/tools/strategy.py
    - src/trade_trace/tools/review_bundle.py
    - src/trade_trace/models/memory.py
  entrypoints:
    - report.* tools
    - memory.retain/recall/reflect
    - playbook/strategy/review.bundle tools
  responsibilities:
    - deterministic reports, memory retrieval, strategy/playbook learning-loop surfaces
  neighboring_domains:
    - cli-mcp-contracts
    - ledger-tools-projections
    - console-backend-frontend
  complexity_lenses:
    - duplicate-report-adapters
    - report-envelope-duplication
    - filter-error-contract-drift
    - hash/ranking-sensitive-god-functions
    - write-tool-idempotency-patterns
  tests:
    - tests/integration/test_report_*.py
    - tests/integration/test_memory_*.py
    - tests/integration/test_playbook_layer.py
    - tests/integration/test_strategy_tools.py
    - tests/integration/test_review_bundle_contract.py
  validation_commands:
    - targeted report/memory/playbook/strategy/review_bundle tests per candidate
  review_priority: high
  lane_prompt_target: lane_3

- domain_id: console-backend-frontend
  paths:
    - src/trade_trace/console/
    - frontend/console/src/
    - frontend/console/package.json
    - src/trade_trace/console/static/app/
    - docs/CONSOLE.md
    - docs/architecture/console*.md
  entrypoints:
    - tt console serve
    - local FastAPI routes
    - React/Vite Console app
  responsibilities:
    - optional read-only local dashboard, packaged static app, backend/frontend page/report routes
  neighboring_domains:
    - reports-memory-playbook
    - tests-docs-build
  complexity_lenses:
    - route-catalog-duplication
    - static-source-drift
    - unused-or-overpowered-ui-dependencies
    - backend-pagination-vs-ui-state
  tests:
    - tests/contracts/test_console_*.py
    - tests/console_browser/test_overview_smoke.py
    - frontend/console npm tests/build/typecheck
  validation_commands:
    - python3 -m pytest tests/contracts/test_console_shell.py tests/contracts/test_console_http_routes.py tests/contracts/test_console_endpoints.py -q
    - cd frontend/console && npm test && npm run build
  review_priority: medium
  lane_prompt_target: lane_4

- domain_id: tests-docs-build
  paths:
    - tests/
    - docs/
    - .github/workflows/
    - pyproject.toml
    - src/trade_trace/tools/fixture.py
  entrypoints:
    - pytest suite
    - release workflow
    - docs contract tests
    - journal.fixture_seed
  responsibilities:
    - behavior preservation harness, release gates, docs/source-of-truth contracts, deterministic fixtures
  neighboring_domains:
    - all runtime domains
  complexity_lenses:
    - test-helper-duplication
    - fixture-monolith
    - docs-contract-special-casing
    - release-version-source-drift
  tests:
    - tests/docs/
    - tests/integration/test_fixture_seed.py
    - full tests/contracts + tests/integration where helper migrations touch broad surfaces
  validation_commands:
    - python3 -m pytest tests/contracts tests/integration tests/golden -q
    - python3 -m pytest tests/integration/test_fixture_seed.py -q
  review_priority: high
  lane_prompt_target: lane_5
```
