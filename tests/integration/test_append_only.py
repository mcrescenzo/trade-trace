"""Append-only invariants per persistence.md §8.

Migrations install BEFORE UPDATE / BEFORE DELETE triggers on append-only
tables that raise sqlite3.IntegrityError with an explicit "append-only
invariant" message.

Correction path for any append-only row is a `supersedes` edge from the new
row to the old, per PRD §3.1.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests._direct_sql_builders import seed_full_append_only_graph
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path

APPEND_ONLY_TABLES = [
    # M0–M5 ledger tables (seeded by seed_full_append_only_graph).
    "events",
    "snapshots",
    "theses",
    "forecasts",
    "forecast_outcomes",
    "forecast_scores",
    "decisions",
    "decision_tags",
    "outcomes",
    "sources",
    "edges",
    "position_events",
    "signals",
    # m016–m029 trigger-guarded append-only tables (trade-trace-cm0l).
    # Each installs its own BEFORE UPDATE / BEFORE DELETE trigger raising the
    # canonical "append-only invariant" message; seeded by
    # _seed_extended_tables below.
    "risk_policy_versions",  # m016
    "risk_check_receipts",  # m016
    "risk_check_rule_results",  # m016
    "account_snapshots",  # m021
    "paper_fill_records",  # m022
    "reconciliation_records",  # m023
    "autonomous_run_records",  # m024
    "autonomous_incident_records",  # m024
    "replay_evaluation_artifacts",  # m026
    "abstentions",  # m027
    "forecast_independence_locks",  # m028
    "resolution_interpretations",  # m029
]

# Classification note (trade-trace-cm0l open question):
# forecast_snapshot_anchor (m013) is append-only *by convention* — the writer
# never updates an anchor — but m013 installs NO BEFORE UPDATE / BEFORE DELETE
# trigger, so there is no enforced invariant for this test to assert. It is
# therefore intentionally EXCLUDED from APPEND_ONLY_TABLES, which exists to
# prove the *trigger-enforced* invariant. test_forecast_snapshot_anchor_has_no_trigger
# below pins this classification so a future trigger-add (or accidental removal
# of an expectation) surfaces here rather than silently drifting.

# Classification note (trade-trace-0lvg / INV-2):
# `markets` (m012) is deliberately a MUTABLE-METADATA table — the §2 sibling of
# venues/instruments/strategies — NOT an append-only ledger table. Its `id` is a
# stable foreign-key target (forecasts, paper_fill_records, risk_check_receipts,
# pretrade_intents, approval/waiver/external-execution ledgers), so
# adapter_polymarket._upsert_market refreshes the existing row in place rather
# than appending a re-keyed one. The append-only audit trail is the
# `market.bound` / `market.refreshed` event stream emitted in the same
# transaction — not a row-level trigger. `markets` is therefore intentionally
# EXCLUDED from APPEND_ONLY_TABLES; test_markets_is_mutable_metadata_no_trigger
# below pins that decision (see persistence.md §2 / §8).


def _db(tmp_path: Path):
    db = open_database(db_path(tmp_path / "home"))
    apply_pending_migrations(db.connection)
    return db


def _seed_minimal(conn: sqlite3.Connection) -> None:
    """Seed one row in every append-only ledger table via the shared
    direct-SQL builders (trade-trace-24ia / SIMP-009), then one row in each
    of the newer m016–m029 trigger-guarded tables (trade-trace-cm0l)."""

    seed_full_append_only_graph(conn)
    _seed_extended_tables(conn)


def _seed_extended_tables(conn: sqlite3.Connection) -> None:
    """Insert a minimal valid row into each m016–m029 append-only table.

    Reuses the FK targets already established by `seed_full_append_only_graph`
    (`i_1` instrument, `f_1` forecast, `t_1` thesis, `snap_1` snapshot). Rows
    satisfy every NOT NULL column and CHECK constraint; nullable FK columns
    (e.g. market_id) are left NULL so no `markets` row is required.
    """

    ts = "2026-05-18T14:00:00Z"
    actor = "agent:default"

    # m016: risk_policy_versions -> risk_check_receipts -> risk_check_rule_results
    conn.execute(
        "INSERT INTO risk_policy_versions("
        "id, policy_key, version, policy_hash, limits_json, rules_json, source, "
        "effective_from, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("rpv_1", "default", "1", "hash_rpv_1", "{}", "[]", "builtin", ts, ts, actor),
    )
    conn.execute(
        "INSERT INTO risk_check_receipts("
        "id, receipt_hash, policy_version_id, status, outcome, as_of, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("rcr_1", "hash_rcr_1", "rpv_1", "pass", "pass", ts, ts, actor),
    )
    conn.execute(
        "INSERT INTO risk_check_rule_results("
        "id, receipt_id, rule_id, reason_code, severity, waiver_required) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("rrr_1", "rcr_1", "rule_a", "ok", "info", 0),
    )

    # m021: account_snapshots
    conn.execute(
        "INSERT INTO account_snapshots("
        "id, schema_version, semantic_key, material_hash, source_system, "
        "confidence_label, staleness_status, captured_at, as_of, imported_at, "
        "artifact_hash, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("as_1", "1", "sk_as_1", "mh_as_1", "manual", "high", "fresh",
         ts, ts, ts, "art_as_1", actor),
    )

    # m022: paper_fill_records
    conn.execute(
        "INSERT INTO paper_fill_records("
        "id, schema_version, semantic_key, material_hash, environment_label, "
        "account_label, side, requested_quantity, filled_quantity, remaining_quantity, "
        "limit_price, order_as_of, freshness_status, fill_status, "
        "conservative_fill_model, mark_source, mark_as_of, confidence_label, "
        "staleness_status, recorded_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("pfr_1", "1", "sk_pfr_1", "mh_pfr_1", "paper", "acct", "buy",
         10.0, 0.0, 10.0, 0.5, ts, "fresh", "no_fill", "mid_cross",
         "snapshot", ts, "high", "fresh", ts, actor),
    )

    # m023: reconciliation_records
    conn.execute(
        "INSERT INTO reconciliation_records("
        "id, schema_version, semantic_key, material_hash, as_of, source, "
        "diff_severity, resolution_status, recorded_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("rec_1", "1", "sk_rec_1", "mh_rec_1", ts, "manual", "none",
         "unresolved", ts, actor),
    )

    # m024: autonomous_run_records -> autonomous_incident_records
    conn.execute(
        "INSERT INTO autonomous_run_records("
        "id, schema_version, semantic_key, material_hash, mode, run_status, "
        "run_id, started_at, as_of, recorded_at, recorder_actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("arr_1", "1", "sk_arr_1", "mh_arr_1", "autonomous", "started",
         "run_1", ts, ts, ts, actor),
    )
    conn.execute(
        "INSERT INTO autonomous_incident_records("
        "id, schema_version, semantic_key, material_hash, incident_type, severity, "
        "resolution_status, occurred_at, as_of, summary, evidence_state, "
        "recorded_at, recorder_actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("air_1", "1", "sk_air_1", "mh_air_1", "operator_note", "info",
         "unresolved", ts, ts, "note", "unknown", ts, actor),
    )

    # m026: replay_evaluation_artifacts
    conn.execute(
        "INSERT INTO replay_evaluation_artifacts("
        "id, schema_version, semantic_key, material_hash, artifact_type, "
        "evidence_mode, dataset_hash, strategy_version, redaction_profile, "
        "as_of, imported_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("rea_1", "1", "sk_rea_1", "mh_rea_1", "paper", "paper", "dh_1",
         "1", "default", ts, ts, actor),
    )

    # m027: abstentions
    conn.execute(
        "INSERT INTO abstentions("
        "id, instrument_id, reason, as_of, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("ab_1", "i_1", "insufficient_edge", ts, ts, actor),
    )

    # m028: forecast_independence_locks
    conn.execute(
        "INSERT INTO forecast_independence_locks("
        "id, forecast_id, snapshot_id, blind_committed_at, blind_commit_seq, "
        "revealed_at, reveal_seq, independence_proven, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("fil_1", "f_1", "snap_1", ts, 1, ts, 2, 1, ts, actor),
    )

    # m029: resolution_interpretations
    conn.execute(
        "INSERT INTO resolution_interpretations("
        "id, forecast_id, instrument_id, interpreted_yes_condition, as_of, "
        "created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("ri_1", "f_1", "i_1", "resolves YES if X", ts, ts, actor),
    )


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_update_forbidden(tmp_path: Path, table: str):
    """Every append-only table's BEFORE UPDATE trigger raises with an
    append-only-invariant message."""

    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        # Find a sample row.
        cur = db.connection.execute(f"SELECT * FROM {table} LIMIT 1")
        row = cur.fetchone()
        assert row is not None, f"seeded {table} but found no row"

        # Get the primary key column. For tables with a single 'id' column
        # we use that; for decision_tags we have a composite key, but UPDATE
        # on any column still fires the trigger.
        cur = db.connection.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        # Pick the first non-FK-ish column to try to UPDATE.
        target_col = next((c for c in cols if c not in ("decision_id",)), cols[0])
        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(f"UPDATE {table} SET {target_col} = {target_col}")
        assert "append-only invariant" in str(exc.value)
    finally:
        db.close()


@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_delete_forbidden(tmp_path: Path, table: str):
    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)
        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(f"DELETE FROM {table}")
        assert "append-only invariant" in str(exc.value)
    finally:
        db.close()


def test_supersedes_edge_is_correction_path(tmp_path: Path):
    """Per PRD §3.1 outcomes: corrections produce a NEW outcomes row
    connected to the prior via a `supersedes` edge. No mutation needed."""

    db = _db(tmp_path)
    try:
        _seed_minimal(db.connection)

        # Append a corrected outcome row (NOT updating the original).
        db.connection.execute(
            "INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, "
            "status, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("o_2", "i_1", "2026-05-18T14:00:00Z", "NO", "resolved_final",
             "2026-05-19T14:00:00Z", "agent:default"),
        )
        # And the supersedes edge from new → prior.
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("e_2", "outcome", "o_2", "outcome", "o_1", "supersedes",
             "2026-05-19T14:00:00Z", "agent:default"),
        )
        # Both outcome rows still readable.
        count = db.connection.execute("SELECT COUNT(*) FROM outcomes WHERE instrument_id = 'i_1'").fetchone()[0]
        assert count == 2
        cur = db.connection.execute(
            "SELECT target_id FROM edges WHERE source_id = 'o_2' AND edge_type = 'supersedes'"
        )
        assert cur.fetchone()[0] == "o_1"
    finally:
        db.close()


def test_outbox_state_update_allowed(tmp_path: Path):
    """`outbox` is an exception: the exporter updates state/exported_at/
    error_text/attempt_count (persistence.md §8 exemption). The migration
    002 outbox table doesn't have the append-only trigger."""

    db = _db(tmp_path)
    try:
        # Insert an event + outbox row.
        db.connection.execute(
            "INSERT INTO events(event_type, subject_kind, subject_id, payload_json, "
            "actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("decision.created", "decision", "d_1", "{}", "agent:default", "2026-05-18T14:00:00Z"),
        )
        event_id = db.connection.execute("SELECT id FROM events").fetchone()[0]
        db.connection.execute(
            "INSERT INTO outbox(event_id, export_kind, state) VALUES (?, 'jsonl', 'pending')",
            (event_id,),
        )
        # Update the outbox row's state (the exporter's pattern).
        db.connection.execute(
            "UPDATE outbox SET state = 'exported', exported_at = ? WHERE event_id = ?",
            ("2026-05-18T14:01:00Z", event_id),
        )
        row = db.connection.execute("SELECT state FROM outbox WHERE event_id = ?", (event_id,)).fetchone()
        assert row[0] == "exported"
    finally:
        db.close()


def test_forecast_snapshot_anchor_has_no_trigger(tmp_path: Path):
    """forecast_snapshot_anchor (m013) is append-only by convention but is
    NOT trigger-guarded — so it is intentionally excluded from
    APPEND_ONLY_TABLES (trade-trace-cm0l classification). This test pins that
    decision: if a future migration adds an append-only trigger, this test
    fails and forces a deliberate move into the parametrized list.
    """

    db = _db(tmp_path)
    try:
        cur = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' "
            "AND tbl_name = 'forecast_snapshot_anchor'"
        )
        triggers = [r[0] for r in cur.fetchall()]
        assert triggers == [], (
            "forecast_snapshot_anchor now has trigger(s) "
            f"{triggers}; if it is now append-only-enforced, add it to "
            "APPEND_ONLY_TABLES (and seed it) and update this classification."
        )
        assert "forecast_snapshot_anchor" not in APPEND_ONLY_TABLES
    finally:
        db.close()


def test_markets_is_mutable_metadata_no_trigger(tmp_path: Path):
    """`markets` (m012) is a mutable-metadata table (persistence.md §2 sibling
    of venues/instruments/strategies), NOT an append-only ledger table.

    market.refresh (adapter_polymarket._upsert_market) intentionally mutates the
    existing row in place because `markets.id` is a stable foreign-key target;
    the append-only audit trail is the `market.bound` / `market.refreshed` event
    stream, not a row-level trigger (trade-trace-0lvg / INV-2). This test pins
    that classification:

    * `markets` carries NO BEFORE UPDATE / BEFORE DELETE trigger, so it is
      correctly excluded from the trigger-enforced APPEND_ONLY_TABLES list, and
    * an in-place UPDATE on a `markets` row is *permitted* (it is the documented
      refresh mechanism).

    If a future migration adds an append-only trigger to `markets`, the first
    assertion fails and forces a deliberate reclassification (move it into
    APPEND_ONLY_TABLES, rewrite _upsert_market to append + supersedes, and update
    persistence.md §2 / §8).
    """

    db = _db(tmp_path)
    try:
        conn = db.connection

        # No append-only trigger is installed on markets.
        triggers = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'markets'"
            ).fetchall()
        ]
        assert triggers == [], (
            f"markets now has trigger(s) {triggers}; if it is now "
            "append-only-enforced, add it to APPEND_ONLY_TABLES (and seed it), "
            "rewrite adapter_polymarket._upsert_market to append + supersedes, "
            "and update persistence.md §2 / §8."
        )
        assert "markets" not in APPEND_ONLY_TABLES

        # An in-place UPDATE is permitted — this is the documented market.refresh
        # mechanism, and it must NOT raise an append-only IntegrityError.
        ts = "2026-05-18T14:00:00Z"
        conn.execute(
            "INSERT INTO markets("
            "id, source, external_id, title, question, url, state, mechanism, "
            "bound_via, venue_metadata_json, metadata_json, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("mkt_1", "polymarket", "ext_1", "T", "Q?", "https://x",
             "open", "clob", "adapter", "{}", "{}", ts, "agent:default"),
        )
        conn.execute(
            "UPDATE markets SET state = 'resolved' WHERE id = 'mkt_1'"
        )
        state = conn.execute(
            "SELECT state FROM markets WHERE id = 'mkt_1'"
        ).fetchone()[0]
        assert state == "resolved"
    finally:
        db.close()
