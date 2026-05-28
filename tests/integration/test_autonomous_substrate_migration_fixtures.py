from __future__ import annotations

from trade_trace.contracts.autonomous_substrate import MIGRATION_CONTRACT_EXPECTATIONS
from trade_trace.storage.migrations import (
    _MIGRATION_COLUMNS_ADDED,
    _MIGRATION_TABLES_CREATED,
    MIGRATIONS,
)


def test_autonomous_substrate_migration_primitives_are_forward_only_registry_scaffolds():
    versions = list(range(1, len(MIGRATIONS) + 1))

    assert [version for version, _tables in _MIGRATION_TABLES_CREATED] == versions
    assert [version for version, _columns in _MIGRATION_COLUMNS_ADDED] == versions
    assert any("forward-only" in item for item in MIGRATION_CONTRACT_EXPECTATIONS)
    assert any("schema hash" in item for item in MIGRATION_CONTRACT_EXPECTATIONS)


def test_autonomous_substrate_fixture_scaffold_adds_no_concrete_migration_tables_yet():
    created_tables = {
        table
        for _version, tables in _MIGRATION_TABLES_CREATED
        for table in tables
    }

    assert not {
        "execution_intents",
        "risk_checks",
        "approval_waivers",
        "execution_imports",
        "account_snapshots",
        "reconciliation_reports",
        "incident_run_sessions",
        "audit_bundles",
        "replay_evaluation_artifacts",
        "paper_fills",
    } & created_tables
