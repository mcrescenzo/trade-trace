"""Shared bootstrap fixture seed helpers (trade-trace-r85a).

Both `test_bootstrap_read_model.py` and `test_bootstrap_report_surface.py`
need the same deterministic seed (`_seed_base`) and table-count snapshot
(`_counts`). They used to live only in `test_bootstrap_read_model.py`, and
the surface test reached across modules to import them. That created
cross-test coupling — moving or renaming the helpers in one module
silently broke the other. Hoist them into a dedicated helpers module that
both test files can import safely.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from trade_trace.storage.paths import db_path


def conn_for(home: Path) -> sqlite3.Connection:
    return sqlite3.connect(db_path(home))


def seed_base(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO venues VALUES (?,?,?,?,?,?)", ("ven", "Venue", "manual", "{}", "2026-01-01T00:00:00Z", "test"))
    conn.execute(
        "INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        ("inst", "ven", "Instrument", "equity", "{}", "2026-01-01T00:00:00Z", "test"),
    )
    conn.execute("INSERT INTO strategies(id, name, slug, status, created_at, updated_at, actor_id) VALUES (?,?,?,?,?,?,?)", ("strat-a", "Strategy A", "strat-a", "active", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "test"))
    conn.execute(
        "INSERT INTO theses (id, instrument_id, side, body, strategy_id, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?)",
        ("th", "inst", "long", "body", "strat-a", "{}", "2026-01-01T00:01:00Z", "test"),
    )
    conn.execute(
        """
        INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text,
                               scoring_support, scoring_state, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        ("fc", "th", "binary", "2026-01-10T00:00:00Z", "yes", "caller supplies outcome", "supported", "pending", "{}", "2026-01-01T00:02:00Z", "test"),
    )
    conn.execute("INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability) VALUES (?,?,?,?)", ("fo-yes", "fc", "yes", 0.6))
    conn.execute("INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability) VALUES (?,?,?,?)", ("fo-no", "fc", "no", 0.4))
    conn.execute(
        """
        INSERT INTO decisions (id, instrument_id, thesis_id, forecast_id, type, reason,
                               review_by, strategy_id, run_id, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        ("d-watch", "inst", "th", "fc", "watch", "because", "2026-01-05T00:00:00Z", "strat-a", "run-a", json.dumps({}), "2026-01-01T00:03:00Z", "test"),
    )


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        for name in (
            "decisions",
            "forecasts",
            "forecast_scores",
            "outcomes",
            "edges",
            "memory_nodes",
            "memory_recall_events",
            "decision_playbook_rules",
        )
    }
