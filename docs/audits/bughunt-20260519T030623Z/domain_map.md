# Trade Trace exhaustive bughunt domain map

Tracked files: 158

## cli-mcp-contracts-tools
Count: 25

Paths:
- `src/trade_trace/cli.py`
- `src/trade_trace/contracts/__init__.py`
- `src/trade_trace/contracts/envelope.py`
- `src/trade_trace/contracts/errors.py`
- `src/trade_trace/contracts/grammar.py`
- `src/trade_trace/contracts/report_filter.py`
- `src/trade_trace/contracts/tool_registry.py`
- `src/trade_trace/mcp_server.py`
- `src/trade_trace/tools/__init__.py`
- `src/trade_trace/tools/_examples.py`
- `src/trade_trace/tools/_helpers.py`
- `src/trade_trace/tools/admin.py`
- `src/trade_trace/tools/decision_matrix.py`
- `src/trade_trace/tools/errors.py`
- `src/trade_trace/tools/fixture.py`
- `src/trade_trace/tools/imports.py`
- `src/trade_trace/tools/journal.py`
- `src/trade_trace/tools/ledger.py`
- `src/trade_trace/tools/memory.py`
- `src/trade_trace/tools/playbook.py`
- `src/trade_trace/tools/reflection.py`
- `src/trade_trace/tools/reports.py`
- `src/trade_trace/tools/review_bundle.py`
- `src/trade_trace/tools/signals.py`
- `src/trade_trace/tools/strategy.py`

## storage-events-domain-security
Count: 15

Paths:
- `src/trade_trace/core.py`
- `src/trade_trace/events/__init__.py`
- `src/trade_trace/events/log.py`
- `src/trade_trace/events/semantic_keys.py`
- `src/trade_trace/events/unit_of_work.py`
- `src/trade_trace/exporter.py`
- `src/trade_trace/models/ledger.py`
- `src/trade_trace/projections.py`
- `src/trade_trace/security/__init__.py`
- `src/trade_trace/security/patterns.py`
- `src/trade_trace/storage/__init__.py`
- `src/trade_trace/storage/database.py`
- `src/trade_trace/storage/migrations.py`
- `src/trade_trace/storage/paths.py`
- `src/trade_trace/storage/policy.py`

## reports-memory-playbook-strategy
Count: 13

Paths:
- `src/trade_trace/models/memory.py`
- `src/trade_trace/reports/__init__.py`
- `src/trade_trace/reports/buckets.py`
- `src/trade_trace/reports/calibration.py`
- `src/trade_trace/reports/coach.py`
- `src/trade_trace/reports/decision_velocity.py`
- `src/trade_trace/reports/integrity.py`
- `src/trade_trace/reports/playbook_adherence.py`
- `src/trade_trace/reports/pnl.py`
- `src/trade_trace/reports/source_quality.py`
- `src/trade_trace/reports/tag_aggregates.py`
- `src/trade_trace/reports/unscored.py`
- `src/trade_trace/reports/watchlist.py`

## docs-packaging-ci-ops
Count: 20

Paths:
- `.claude/settings.json`
- `.github/workflows/workflow.yml`
- `.gitignore`
- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `docs/PRD.md`
- `docs/VISION.md`
- `docs/architecture/contracts.md`
- `docs/architecture/dogfood-protocol.md`
- `docs/architecture/imports.md`
- `docs/architecture/memory-layer.md`
- `docs/architecture/operability.md`
- `docs/architecture/opportunity-analysis.md`
- `docs/architecture/persistence.md`
- `docs/architecture/reports.md`
- `docs/architecture/risk-units.md`
- `docs/architecture/scoring.md`
- `docs/architecture/security.md`
- `pyproject.toml`

## tests-fixtures-crosscutting
Count: 80

Paths:
- `src/trade_trace/__init__.py`
- `src/trade_trace/clock.py`
- `src/trade_trace/models/__init__.py`
- `src/trade_trace/timestamps.py`
- `src/trade_trace/version.py`
- `tests/__init__.py`
- `tests/conftest.py`
- `tests/contracts/__init__.py`
- `tests/contracts/test_agent_ergonomics.py`
- `tests/contracts/test_cli_name_uniqueness.py`
- `tests/contracts/test_envelope.py`
- `tests/contracts/test_event_enum_coverage.py`
- `tests/contracts/test_grammar.py`
- `tests/contracts/test_report_envelope_completeness.py`
- `tests/golden/__init__.py`
- `tests/golden/test_cli_mcp_parity.py`
- `tests/golden/test_journal_status_parity.py`
- `tests/integration/__init__.py`
- `tests/integration/test_admin_tools.py`
- `tests/integration/test_append_only.py`
- `tests/integration/test_bucket_constants.py`
- `tests/integration/test_calibration_integrity.py`
- `tests/integration/test_cli_no_writes.py`
- `tests/integration/test_coach_override_outcomes.py`
- `tests/integration/test_edges.py`
- `tests/integration/test_final_dogfood_verification.py`
- `tests/integration/test_fixture_seed.py`
- `tests/integration/test_idempotency.py`
- `tests/integration/test_journal_init.py`
- `tests/integration/test_jsonl_atomic_write.py`
- `tests/integration/test_jsonl_contract.py`
- `tests/integration/test_jsonl_replay_readiness.py`
- `tests/integration/test_ledger_event_emission.py`
- `tests/integration/test_manual_ledger_flow.py`
- `tests/integration/test_memory_layer.py`
- `tests/integration/test_memory_link.py`
- `tests/integration/test_memory_recall_budgets.py`
- `tests/integration/test_memory_retrieval_constants.py`
- `tests/integration/test_migration_policy.py`
- `tests/integration/test_migrations.py`
- `tests/integration/test_ndjson_streaming.py`
- `tests/integration/test_operability_drill.py`
- `tests/integration/test_outbox_export.py`
- `tests/integration/test_p1_stub_columns.py`
- `tests/integration/test_playbook_layer.py`
- `tests/integration/test_projection_rebuild.py`
- `tests/integration/test_reflection_prompt.py`
- `tests/integration/test_report_calibration.py`
- `tests/integration/test_report_coach.py`
- `tests/integration/test_report_filter.py`
- `tests/integration/test_report_pnl_watchlist.py`
- `tests/integration/test_report_sample_warnings.py`
- `tests/integration/test_report_tag_aggregates.py`
- `tests/integration/test_report_unscored_velocity.py`
- `tests/integration/test_reproducibility_replay.py`
- `tests/integration/test_rescan_scoring_stub.py`
- `tests/integration/test_review_bundle_contract.py`
- `tests/integration/test_schema.py`
- `tests/integration/test_scoring_lifecycle.py`
- `tests/integration/test_semantic_keys.py`
- `tests/integration/test_signal_scan.py`
- `tests/integration/test_signals_schema.py`
- `tests/integration/test_source_attach_to_memory_node.py`
- `tests/integration/test_source_quality.py`
- `tests/integration/test_strategy_tools.py`
- `tests/integration/test_transactions.py`
- `tests/property/__init__.py`
- `tests/property/test_scoring_properties.py`
- `tests/security/__init__.py`
- `tests/security/test_embeddings_off_by_default.py`
- `tests/security/test_file_permissions.py`
- `tests/security/test_mvp_boundary_audit.py`
- `tests/security/test_no_credentials.py`
- `tests/security/test_no_network_default.py`
- `tests/security/test_no_telemetry_packages.py`
- `tests/security/test_redacted_exports.py`
- `tests/security/test_report_sql_filters.py`
- `tests/security/test_secret_pattern_writes.py`
- `tests/test_smoke.py`
- `tests/test_timestamps.py`

## excluded-grouped
Count: 5

Paths:
- `.beads/.gitignore`
- `.beads/README.md`
- `.beads/config.yaml`
- `.beads/metadata.json`
- `LICENSE`
