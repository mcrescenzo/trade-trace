# trade-trace-alwf helper grouping

Mechanical pre-edit classification for residual duplicate test helpers.

## Pure `home(initialized_home)` aliases

Exact alias body migrated to the shared `tests/conftest.py::home` fixture and removed locally:

- tests/security/test_report_sql_filters.py
- tests/security/test_secret_pattern_writes.py
- tests/integration/test_admin_tools.py
- tests/integration/test_memory_link.py
- tests/integration/test_report_sample_warnings.py
- tests/integration/test_source_attach_to_memory_node.py
- tests/integration/test_report_compare.py
- tests/integration/test_calibration_integrity.py
- tests/integration/test_memory_recall_budgets.py
- tests/integration/test_source_quality.py
- tests/integration/test_report_opportunity.py
- tests/integration/test_coach_override_outcomes.py
- tests/integration/test_memory_layer.py
- tests/integration/test_reflection_prompt.py
- tests/integration/test_strategy_tools.py
- tests/integration/test_review_bundle_contract.py
- tests/integration/test_playbook_layer.py
- tests/integration/test_fixture_seed.py
- tests/integration/test_report_risk.py
- tests/contracts/test_event_enum_coverage.py

## Old exact `tmp_path / "home"` + `journal.init` clones

Classified as exact/near-exact initialized-home clones but left local in this first pass unless they already used the pure alias shape, to avoid changing docs-like contract/golden examples or assertion style:

- tests/security/test_restore_manifest_paths.py
- tests/security/test_no_network_default.py (`_initialized_home`)
- tests/security/test_no_credentials.py
- tests/integration/test_report_coach.py
- tests/integration/test_report_unscored_velocity.py
- tests/integration/test_scoring_p1.py
- tests/integration/test_manual_ledger_flow.py
- tests/integration/test_report_pnl_watchlist.py
- tests/integration/test_projection_rebuild.py
- tests/integration/test_rescan_scoring_stub.py
- tests/integration/test_report_calibration.py
- tests/integration/test_signal_scan.py
- tests/integration/test_report_filter.py (`_journal_home`)
- tests/integration/test_ndjson_streaming.py (`_init_home`)
- tests/integration/test_scoring_lifecycle.py
- tests/golden/test_cli_mcp_parity.py
- tests/contracts/test_report_envelope_completeness.py
- tests/contracts/test_agent_ergonomics.py

## Custom homes / seeded homes

Intentionally kept local because they seed data, use custom names/scopes, frozen clocks, console/browser behavior, or other test-specific setup:

- tests/console_browser/conftest.py (`seeded_home`)
- tests/integration/test_console_reporting_read_model.py (`rich_home`)
- tests/integration/test_console_reporting_adapter.py (`rich_home`)
- tests/integration/test_final_dogfood_verification.py (`fixture_home`)
- tests/integration/test_reproducibility_replay.py (`populated_home`)
- tests/contracts/test_console_endpoints.py (`_seed`)
- tests/contracts/test_console_http_routes.py (`_seed_home`)
- tests/security/test_readonly_database.py (`_seeded_home`)
- tests/integration/test_ledger_event_emission.py (`home`, enables outbox)

## Exact `_mcp` bodies

Exact body migrated to `tests/_mcp_helpers.py::mcp_default` and imported as `_mcp`:

- tests/security/test_report_sql_filters.py
- tests/security/test_secret_pattern_writes.py
- tests/integration/test_admin_tools.py
- tests/integration/test_operability_drill.py
- tests/integration/test_memory_link.py
- tests/integration/test_report_sample_warnings.py
- tests/integration/test_source_attach_to_memory_node.py
- tests/integration/test_memory_recall_budgets.py
- tests/integration/test_source_quality.py
- tests/integration/test_coach_override_outcomes.py
- tests/integration/test_memory_layer.py
- tests/integration/test_reflection_prompt.py
- tests/integration/test_strategy_tools.py
- tests/integration/test_final_dogfood_verification.py
- tests/integration/test_review_bundle_contract.py
- tests/integration/test_playbook_layer.py
- tests/contracts/test_agent_ergonomics.py
- tests/contracts/test_event_enum_coverage.py

Near variants kept local: actor_id `cli:test`, request_id, required args, explicit env variable, or extra post-processing.

## Exact envelope/model_dump bodies

Exact body migrated to `tests/_mcp_helpers.py::envelope_default` and imported as `_envelope`:

- tests/integration/test_report_coach.py
- tests/integration/test_report_unscored_velocity.py
- tests/integration/test_report_pnl_watchlist.py
- tests/integration/test_projection_rebuild.py
- tests/integration/test_report_calibration.py
- tests/integration/test_signal_scan.py
- tests/integration/test_ledger_event_emission.py
- tests/integration/test_report_tag_aggregates.py

Near variants kept local: `_env` names, trailing-comma formatting variants, actor override parameter, actor_id `agent:test`/`cli:test`, dispatch-based helpers, or exclude_none=False determinism checks.

## Intentional DB helpers

Left local, especially schema/storage/read-model tests and helpers that open SQLite directly or inspect migrations/projections:

- tests/integration/test_report_risk.py (`_closed_position`)
- tests/integration/test_console_reporting_read_model.py (read model DB queries)
- tests/integration/test_ledger_event_emission.py (outbox setup)
- tests/security/test_readonly_database.py
- schema/storage-style direct DB helpers found in integration/contracts remain untouched.
