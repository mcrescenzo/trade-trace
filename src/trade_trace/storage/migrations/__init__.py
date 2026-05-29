"""Migration registry per docs/architecture/migrations-split-investigation.md.

Re-exports every public name the legacy `storage/migrations.py` module
exposed. Each migration body lives in its own `mNNN_*.py` sibling
module; the runner (`apply_pending_migrations`, `current_version`,
`SchemaMetaMismatchError`, `_assert_schema_matches_meta`,
`FTS5UnavailableError`, `_require_fts5`) lives in `_runner.py`.

Schema equivalence after this split is verified by
`tests/integration/test_migrations_schema_hash.py` (trade-trace-y5pj).
"""

from __future__ import annotations

from trade_trace.storage.migrations._runner import (
    FTS5UnavailableError,
    Migration,
    SchemaMetaMismatchError,
    _assert_schema_matches_meta,
    _require_fts5,
    apply_pending_migrations,
    current_version,
)
from trade_trace.storage.migrations.m001_meta import _migration_001_meta_table
from trade_trace.storage.migrations.m002_events_outbox import (
    _migration_002_events_outbox,
)
from trade_trace.storage.migrations.m003_m1_ledger import _migration_003_m1_ledger
from trade_trace.storage.migrations.m004_p1_stub_columns import (
    _migration_004_p1_stub_columns,
)
from trade_trace.storage.migrations.m005_signals import _migration_005_signals
from trade_trace.storage.migrations.m006_memory_layer import _migration_006_memory_layer
from trade_trace.storage.migrations.m007_strategies import _migration_007_strategies
from trade_trace.storage.migrations.m008_playbooks import _migration_008_playbooks
from trade_trace.storage.migrations.m009_events_append_only import (
    _migration_009_events_append_only,
)
from trade_trace.storage.migrations.m010_strategy_id_new_row_triggers import (
    _migration_010_strategy_id_new_row_triggers,
)
from trade_trace.storage.migrations.m011_agent_continuity_provenance import (
    _migration_011_agent_continuity_provenance,
)
from trade_trace.storage.migrations.m012_markets import _migration_012_markets
from trade_trace.storage.migrations.m013_forecast_snapshot_anchor import (
    _migration_013_forecast_snapshot_anchor,
)
from trade_trace.storage.migrations.m014_pm_forecast_memory_transition import (
    _migration_014_pm_forecast_memory_transition,
)
from trade_trace.storage.migrations.m015_pm_inline_sources_transition import (
    _migration_015_pm_inline_sources_transition,
)
from trade_trace.storage.migrations.m016_risk_policy_receipts import (
    _migration_016_risk_policy_receipts,
)
from trade_trace.storage.migrations.m017_expanded_source_stances import (
    _migration_017_expanded_source_stances,
)
from trade_trace.storage.migrations.m018_pretrade_intents import (
    _migration_018_pretrade_intents,
)
from trade_trace.storage.migrations.m019_approval_waiver_ledger import (
    _migration_019_approval_waiver_ledger,
)
from trade_trace.storage.migrations.m020_external_execution_receipts import (
    _migration_020_external_execution_receipts,
)
from trade_trace.storage.migrations.m021_account_snapshots import (
    _migration_021_account_snapshots,
)
from trade_trace.storage.migrations.m022_paper_fills import _migration_022_paper_fills
from trade_trace.storage.migrations.m023_reconciliation_records import (
    _migration_023_reconciliation_records,
)
from trade_trace.storage.migrations.m024_autonomous_records import (
    _migration_024_autonomous_records,
)
from trade_trace.storage.migrations.m025_polymarket_resolution_finality import (
    _migration_025_polymarket_resolution_finality,
)
from trade_trace.storage.migrations.m026_replay_evaluation_artifacts import (
    _migration_026_replay_evaluation_artifacts,
)
from trade_trace.storage.migrations.m027_abstentions import (
    _migration_027_abstentions,
)
from trade_trace.storage.migrations.m028_forecast_independence_locks import (
    _migration_028_forecast_independence_locks,
)

MIGRATIONS: list[Migration] = [
    _migration_001_meta_table,
    _migration_002_events_outbox,
    _migration_003_m1_ledger,
    _migration_004_p1_stub_columns,
    _migration_005_signals,
    _migration_006_memory_layer,
    _migration_007_strategies,
    _migration_008_playbooks,
    _migration_009_events_append_only,
    _migration_010_strategy_id_new_row_triggers,
    _migration_011_agent_continuity_provenance,
    _migration_012_markets,
    _migration_013_forecast_snapshot_anchor,
    _migration_014_pm_forecast_memory_transition,
    _migration_015_pm_inline_sources_transition,
    _migration_016_risk_policy_receipts,
    _migration_017_expanded_source_stances,
    _migration_018_pretrade_intents,
    _migration_019_approval_waiver_ledger,
    _migration_020_external_execution_receipts,
    _migration_021_account_snapshots,
    _migration_022_paper_fills,
    _migration_023_reconciliation_records,
    _migration_024_autonomous_records,
    _migration_025_polymarket_resolution_finality,
    _migration_026_replay_evaluation_artifacts,
    _migration_027_abstentions,
    _migration_028_forecast_independence_locks,
]


# Tables each migration is the FIRST to create. Used by
# `_assert_schema_matches_meta` (bead trade-trace-0ib) to detect a
# stale/lost `meta.schema_version` against the actual on-disk schema.
# Migrations that only add columns/triggers (004, 010) appear with an
# empty list; column drift is detected separately via
# `_MIGRATION_COLUMNS_ADDED` (trade-trace-n1mm). Trigger drift is
# explicitly out of scope per
# `docs/architecture/schema-meta-diagnostics.md`.
_MIGRATION_TABLES_CREATED: list[tuple[int, list[str]]] = [
    (1, ["meta"]),
    (2, ["events", "outbox", "config"]),
    (3, [
        "venues", "instruments", "snapshots", "theses", "forecasts",
        "forecast_outcomes", "forecast_scores", "decisions",
        "decision_tags", "outcomes", "sources", "edges",
        "position_events", "positions",
    ]),
    (4, []),
    (5, ["signals"]),
    (6, ["memory_nodes", "memory_recall_events", "memory_node_stats",
         "memory_node_fts"]),
    (7, ["strategies"]),
    (8, ["playbooks", "playbook_versions", "decision_playbook_rules"]),
    (9, ["memory_node_embeddings"]),
    (10, []),
    (11, []),
    (12, ["markets"]),
    (13, ["forecast_snapshot_anchor"]),
    (14, []),
    (15, []),
    (16, ["risk_policy_versions", "risk_check_receipts", "risk_check_rule_results"]),
    (17, []),
    (18, ["pretrade_intents"]),
    (19, ["approval_waiver_records"]),
    (20, ["external_execution_receipts"]),
    (21, ["account_snapshots"]),
    (22, ["paper_fill_records"]),
    (23, ["reconciliation_records"]),
    (24, ["autonomous_run_records", "autonomous_incident_records"]),
    (25, []),
    (26, ["replay_evaluation_artifacts"]),
    (27, ["abstentions"]),
    (28, ["forecast_independence_locks"]),
]


# Columns each column-only migration adds. Used by
# `_assert_schema_matches_meta` (trade-trace-n1mm) to surface a typed
# diagnostic when a stale `meta.schema_version` row hides the fact
# that a column-only migration already ran. Trigger-only migrations
# (010) appear as empty dicts; trigger drift is out of scope per
# `docs/architecture/schema-meta-diagnostics.md`.
_MIGRATION_COLUMNS_ADDED: list[tuple[int, dict[str, list[str]]]] = [
    (1, {}),
    (2, {}),
    (3, {}),
    (4, {
        "theses": [
            "risk_unit_label", "max_loss_budget", "invalidation_condition",
        ],
        "decisions": [
            "declared_risk_amount", "declared_risk_unit", "expected_edge",
            "expected_edge_after_costs", "cost_basis_estimate",
            "risk_reward_estimate",
        ],
        "position_events": [
            "initial_risk_amount", "realized_r_multiple",
            "unrealized_r_multiple",
        ],
        "positions": [
            "initial_risk_amount", "realized_r_multiple",
            "unrealized_r_multiple",
        ],
    }),
    (5, {}),
    (6, {}),
    (7, {}),
    (8, {}),
    (9, {}),
    (10, {}),
    (11, {
        "snapshots": ["agent_id", "model_id", "environment", "run_id"],
        "sources": ["agent_id", "model_id", "environment", "run_id"],
    }),
    (12, {}),
    (13, {}),
    (14, {
        "forecasts": [
            "market_id", "rationale_body", "falsification_criteria",
            "updated_rationale_at", "updated_rationale_by", "probability",
        ],
        "memory_nodes": ["metadata_json"],
    }),
    (15, {}),
    (16, {}),
    (17, {}),
    (18, {}),
    (19, {}),
    (20, {}),
    (21, {}),
    (22, {}),
    (23, {}),
    (24, {}),
    (25, {}),
    (26, {}),
    (27, {}),
    (28, {}),
]


__all__ = [
    "FTS5UnavailableError",
    "MIGRATIONS",
    "Migration",
    "SchemaMetaMismatchError",
    "_MIGRATION_COLUMNS_ADDED",
    "_MIGRATION_TABLES_CREATED",
    "_assert_schema_matches_meta",
    "_migration_001_meta_table",
    "_migration_002_events_outbox",
    "_migration_003_m1_ledger",
    "_migration_004_p1_stub_columns",
    "_migration_005_signals",
    "_migration_006_memory_layer",
    "_migration_007_strategies",
    "_migration_008_playbooks",
    "_migration_009_events_append_only",
    "_migration_010_strategy_id_new_row_triggers",
    "_migration_011_agent_continuity_provenance",
    "_migration_012_markets",
    "_migration_013_forecast_snapshot_anchor",
    "_migration_014_pm_forecast_memory_transition",
    "_migration_015_pm_inline_sources_transition",
    "_migration_016_risk_policy_receipts",
    "_migration_017_expanded_source_stances",
    "_migration_018_pretrade_intents",
    "_migration_019_approval_waiver_ledger",
    "_migration_020_external_execution_receipts",
    "_migration_021_account_snapshots",
    "_migration_022_paper_fills",
    "_migration_023_reconciliation_records",
    "_migration_024_autonomous_records",
    "_migration_025_polymarket_resolution_finality",
    "_migration_026_replay_evaluation_artifacts",
    "_migration_027_abstentions",
    "_migration_028_forecast_independence_locks",
    "_require_fts5",
    "apply_pending_migrations",
    "current_version",
]
