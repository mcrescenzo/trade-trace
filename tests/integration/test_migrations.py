"""Forward-only migration tests per docs/architecture/operability.md §4."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from trade_trace.storage import (
    MIGRATIONS,
    apply_pending_migrations,
    current_version,
    open_database,
)
from trade_trace.storage.paths import db_path


def _open(tmp_path: Path):
    return open_database(db_path(tmp_path / "home"))


def test_initial_version_is_zero(tmp_path: Path):
    db = _open(tmp_path)
    try:
        assert current_version(db.connection) == 0
    finally:
        db.close()


def test_apply_all_migrations(tmp_path: Path):
    db = _open(tmp_path)
    try:
        before, after = apply_pending_migrations(db.connection)
        assert before == 0
        assert after == len(MIGRATIONS)
        assert current_version(db.connection) == len(MIGRATIONS)
    finally:
        db.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    assert row is not None
    return row[0]


def test_migration_012_markets_schema(tmp_path: Path):
    db = _open(tmp_path)
    try:
        before, after = apply_pending_migrations(db.connection)
        assert before == 0
        assert after == len(MIGRATIONS)
        assert current_version(db.connection) == len(MIGRATIONS)

        assert {
            "id", "source", "external_id", "title", "question", "url",
            "state", "mechanism", "resolution_source", "ambiguity_kind",
            "bound_via", "opened_at", "close_at", "closed_for_trading_at",
            "resolving_at", "resolved_at", "voided_at", "ambiguous_at",
            "venue_metadata_json", "metadata_json", "created_at", "actor_id",
        }.issubset(_columns(db.connection, "markets"))
        assert {
            "idx_markets_source_external", "idx_markets_state", "idx_markets_close_at",
        }.issubset(_index_names(db.connection, "markets"))
        sql = _table_sql(db.connection, "markets")
        for fragment in (
            "UNIQUE (source, external_id)",
            "'open','closed_for_trading','resolving','resolved','voided','ambiguous'",
            "'clob','amm','scalar','hybrid'",
            "'market_contract','oracle_feed','manual_review','arbitration'",
            "'market_rules_unclear','oracle_dispute'",
            "'polymarket','kalshi','manifold','predictit','manual'",
            "'adapter','manual'",
            "venue_metadata_json TEXT NOT NULL DEFAULT '{}'",
            "metadata_json TEXT NOT NULL DEFAULT '{}'",
        ):
            assert fragment in sql

        db.connection.execute(
            """
            INSERT INTO markets(
                id, source, external_id, state, mechanism, resolution_source,
                ambiguity_kind, bound_via, created_at, actor_id
            ) VALUES (
                'm_1', 'polymarket', 'ext_1', 'open', 'clob',
                'market_contract', 'market_rules_unclear', 'adapter',
                '2026-05-25T00:00:00Z', 'agent:default'
            )
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO markets(id, source, external_id, state, mechanism, bound_via, created_at, actor_id) "
                "VALUES ('m_2', 'polymarket', 'ext_1', 'open', 'clob', 'adapter', '2026-05-25T00:00:00Z', 'agent:default')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO markets(id, source, external_id, state, mechanism, bound_via, created_at, actor_id) "
                "VALUES ('m_bad', 'polymarket', 'ext_bad', 'paused', 'clob', 'adapter', '2026-05-25T00:00:00Z', 'agent:default')"
            )
    finally:
        db.close()


def test_migration_013_forecast_snapshot_anchor_schema(tmp_path: Path):
    db = _open(tmp_path)
    try:
        before, after = apply_pending_migrations(db.connection)
        assert before == 0
        assert after == len(MIGRATIONS)
        assert current_version(db.connection) == len(MIGRATIONS)

        assert {
            "id", "forecast_id", "snapshot_id", "market_implied_probability",
            "agent_id", "model_id", "environment", "run_id", "metadata_json",
            "created_at", "actor_id",
        }.issubset(_columns(db.connection, "forecast_snapshot_anchor"))
        assert {
            "idx_fsa_forecast", "idx_fsa_snapshot",
        }.issubset(_index_names(db.connection, "forecast_snapshot_anchor"))
        sql = _table_sql(db.connection, "forecast_snapshot_anchor")
        for fragment in (
            "id TEXT PRIMARY KEY",
            "forecast_id TEXT NOT NULL UNIQUE REFERENCES forecasts(id)",
            "snapshot_id TEXT NOT NULL REFERENCES snapshots(id)",
            "market_implied_probability REAL",
            "metadata_json TEXT NOT NULL DEFAULT '{}'",
        ):
            assert fragment in sql

        db.connection.execute(
            "INSERT INTO venues(id, name, kind, created_at, actor_id) VALUES ('v_1', 'manual', 'manual', '2026-05-25T00:00:00Z', 'agent:default')"
        )
        db.connection.execute(
            "INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id) VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-25T00:00:00Z', 'agent:default')"
        )
        db.connection.execute(
            "INSERT INTO snapshots(id, instrument_id, captured_at, implied_probability, created_at, actor_id) VALUES ('s_1', 'i_1', '2026-05-25T00:00:00Z', 0.42, '2026-05-25T00:00:00Z', 'agent:default')"
        )
        db.connection.execute(
            "INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id) VALUES ('t_1', 'i_1', 'yes', 'body', '2026-05-25T00:00:00Z', 'agent:default')"
        )
        db.connection.execute(
            "INSERT INTO forecasts(id, thesis_id, kind, created_at, actor_id) VALUES ('f_1', 't_1', 'binary', '2026-05-25T00:00:00Z', 'agent:default')"
        )
        db.connection.execute(
            "INSERT INTO forecast_snapshot_anchor(id, forecast_id, snapshot_id, market_implied_probability, created_at, actor_id) VALUES ('a_1', 'f_1', 's_1', 0.42, '2026-05-25T00:00:00Z', 'agent:default')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO forecast_snapshot_anchor(id, forecast_id, snapshot_id, created_at, actor_id) VALUES ('a_2', 'f_1', 's_1', '2026-05-25T00:00:00Z', 'agent:default')"
            )
    finally:
        db.close()


def test_migration_014_pm_forecast_memory_transition_schema(tmp_path: Path):
    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)

        assert {
            "market_id", "rationale_body", "falsification_criteria",
            "invalidated_at", "invalidated_by", "updated_rationale_at",
            "updated_rationale_by", "probability",
        }.issubset(_columns(db.connection, "forecasts"))
        assert "metadata_json" in _columns(db.connection, "memory_nodes")
        assert "meta_json" in _columns(db.connection, "memory_nodes")
        assert "idx_forecasts_market" in _index_names(db.connection, "forecasts")

        sql = _table_sql(db.connection, "forecasts")
        assert "market_id TEXT REFERENCES markets(id)" in sql
        assert "probability REAL CHECK (probability IS NULL OR (probability >= 0.0 AND probability <= 1.0))" in sql

        db.connection.execute(
            "INSERT INTO venues(id, name, kind, created_at, actor_id) VALUES ('v_bad_prob', 'manual', 'manual', '2026-05-25T00:00:00Z', 'agent:default')"
        )
        db.connection.execute(
            "INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id) VALUES ('i_bad_prob', 'v_bad_prob', 'Test', 'prediction_market', '2026-05-25T00:00:00Z', 'agent:default')"
        )
        db.connection.execute(
            "INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id) VALUES ('t_bad_prob', 'i_bad_prob', 'yes', 'body', '2026-05-25T00:00:00Z', 'agent:default')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute(
                "INSERT INTO forecasts(id, thesis_id, kind, probability, created_at, actor_id) VALUES ('f_bad_prob', 't_bad_prob', 'binary', 1.2, '2026-05-25T00:00:00Z', 'agent:default')"
            )
    finally:
        db.close()


def test_migration_014_backfills_only_deterministic_forecast_and_memory_fields(tmp_path: Path):
    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection, target_version=13)
        db.connection.executescript(
            """
            INSERT INTO venues(id, name, kind, created_at, actor_id)
                VALUES ('v_1', 'manual', 'manual', '2026-05-25T00:00:00Z', 'agent:default');
            INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
                VALUES ('m_1', 'v_1', 'Mapped', 'prediction_market', '2026-05-25T00:00:00Z', 'agent:default'),
                       ('i_unmapped', 'v_1', 'Unmapped', 'prediction_market', '2026-05-25T00:00:00Z', 'agent:default');
            INSERT INTO markets(id, source, external_id, state, mechanism, bound_via, created_at, actor_id)
                VALUES ('m_1', 'manual', 'm_1', 'open', 'clob', 'manual', '2026-05-25T00:00:00Z', 'agent:default');
            INSERT INTO theses(id, instrument_id, side, body, falsification_criteria, created_at, actor_id)
                VALUES ('t_1', 'm_1', 'yes', 'mapped body', 'mapped falsifier', '2026-05-25T00:00:00Z', 'agent:default'),
                       ('t_2', 'i_unmapped', 'yes', 'unmapped body', 'unmapped falsifier', '2026-05-25T00:00:00Z', 'agent:default');
            INSERT INTO forecasts(id, thesis_id, kind, yes_label, created_at, actor_id)
                VALUES ('f_1', 't_1', 'binary', 'YES', '2026-05-25T00:00:00Z', 'agent:default'),
                       ('f_2', 't_2', 'binary', 'YES', '2026-05-25T00:00:00Z', 'agent:default');
            INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability)
                VALUES ('fo_1', 'f_1', 'yes', 0.64),
                       ('fo_2', 'f_1', 'no', 0.36),
                       ('fo_3', 'f_2', 'no', 0.70);
            INSERT INTO memory_nodes(id, node_type, title, body, meta_json, valid_from, created_at, actor_id)
                VALUES ('mem_1', 'observation', 'Memory', 'Body', '{"legacy": true}', '2026-05-25T00:00:00Z', '2026-05-25T00:00:00Z', 'agent:default');
            """
        )

        apply_pending_migrations(db.connection)

        row = db.connection.execute(
            "SELECT market_id, rationale_body, falsification_criteria, probability FROM forecasts WHERE id = 'f_1'"
        ).fetchone()
        assert tuple(row) == ("m_1", "mapped body", "mapped falsifier", 0.64)

        row = db.connection.execute(
            "SELECT market_id, rationale_body, falsification_criteria, probability FROM forecasts WHERE id = 'f_2'"
        ).fetchone()
        assert tuple(row) == (None, "unmapped body", "unmapped falsifier", None)

        row = db.connection.execute(
            "SELECT meta_json, metadata_json FROM memory_nodes WHERE id = 'mem_1'"
        ).fetchone()
        assert tuple(row) == ('{"legacy": true}', '{"legacy": true, "sources": []}')
    finally:
        db.close()


def test_apply_is_idempotent(tmp_path: Path):
    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        snapshot = current_version(db.connection)
        before, after = apply_pending_migrations(db.connection)
        assert before == after == snapshot  # no work to do
        assert current_version(db.connection) == snapshot
    finally:
        db.close()


def test_meta_table_holds_schema_version(tmp_path: Path):
    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        row = db.connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        assert row is not None
        assert int(row[0]) == len(MIGRATIONS)
    finally:
        db.close()


def test_no_downgrade(tmp_path: Path):
    """target_version cannot exceed available migrations; ditto going backward
    is not supported (forward-only)."""

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        with pytest.raises(ValueError):
            apply_pending_migrations(db.connection, target_version=len(MIGRATIONS) + 99)
    finally:
        db.close()


def test_memory_layer_migration_requires_fts5(tmp_path: Path, monkeypatch):
    """Per bead trade-trace-qis / DEBT-013: when the host SQLite build
    lacks FTS5, migration 006 must raise the typed
    `FTS5UnavailableError` BEFORE creating any memory-layer tables.
    The previous behavior was an opaque `OperationalError` partway
    through after some tables had been created, leaving callers with
    no remediation hint and a partially-migrated schema."""

    import sqlite3

    from trade_trace.storage.migrations import FTS5UnavailableError

    def _fts5_unavailable(conn: sqlite3.Connection) -> None:
        # Simulate the OperationalError SQLite raises when FTS5 is not
        # compiled in while creating the FTS5 virtual table in the
        # migration preflight.
        raise FTS5UnavailableError() from sqlite3.OperationalError(
            "no such module: fts5"
        )

    db = _open(tmp_path)
    try:
        # Stop just before migration 006 so it's the next one to run.
        apply_pending_migrations(db.connection, target_version=5)
        baseline = current_version(db.connection)
        assert baseline == 5

        monkeypatch.setattr(
            "trade_trace.storage.migrations._require_fts5",
            _fts5_unavailable,
        )

        with pytest.raises(FTS5UnavailableError) as exc:
            apply_pending_migrations(db.connection)

        # The descriptive remediation hint is part of the contract.
        msg = str(exc.value)
        assert "FTS5" in msg
        assert "memory" in msg.lower()
        assert (
            "compiled" in msg.lower()
            or "rebuild" in msg.lower()
            or "build" in msg.lower()
        )

        # Schema version stays at the baseline; the memory-layer tables
        # do not exist.
        assert current_version(db.connection) == baseline
        for table in ("memory_nodes", "memory_node_fts", "memory_recall_events"):
            row = db.connection.execute(
                "SELECT name FROM sqlite_master WHERE name = ?", (table,),
            ).fetchone()
            assert row is None, f"{table!r} leaked despite FTS5 failure"
    finally:
        db.close()


def test_schema_meta_mismatch_raises_actionable_error(tmp_path: Path):
    """Per bead trade-trace-0ib / DEBT-015: when the DB has tables on
    disk that the meta.schema_version claims haven't been migrated
    yet, the migration runner raises SchemaMetaMismatchError with
    the offending table names BEFORE attempting the next migration —
    replacing the opaque "table X already exists" DDL failure with
    actionable remediation text."""

    from trade_trace.storage.migrations import SchemaMetaMismatchError

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection, target_version=3)
        assert current_version(db.connection) == 3

        # Simulate an out-of-band recovery that reset meta but left
        # the M1 ledger tables on disk.
        db.connection.execute(
            "UPDATE meta SET value = '1' WHERE key = 'schema_version'"
        )
        assert current_version(db.connection) == 1

        with pytest.raises(SchemaMetaMismatchError) as exc:
            apply_pending_migrations(db.connection)

        msg = str(exc.value)
        assert "schema/meta mismatch" in msg
        assert "meta.schema_version=1" in msg
        # The error names at least one of the M1 ledger tables that
        # exists on disk but is claimed unrun.
        assert any(t in msg for t in ("decisions", "theses", "venues"))
        assert "table venues already exists" not in msg.lower()
        # And points at the recovery surfaces.
        assert "journal restore" in msg or "operability" in msg
    finally:
        db.close()


def test_missing_meta_with_existing_objects_raises_actionable_error(tmp_path: Path):
    """A DB with objects on disk but no usable meta.schema_version should
    fail before migration 001/002 can produce opaque DDL errors."""

    from trade_trace.storage.migrations import SchemaMetaMismatchError

    db = _open(tmp_path)
    try:
        db.connection.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT)"
        )

        with pytest.raises(SchemaMetaMismatchError) as exc:
            apply_pending_migrations(db.connection)

        msg = str(exc.value)
        assert "schema/meta mismatch" in msg
        assert "meta.schema_version=0" in msg
        assert "events" in msg
        assert "already exist" in msg
        assert "journal restore" in msg or "operability" in msg
        assert current_version(db.connection) == 0
    finally:
        db.close()


def test_require_fts5_passes_on_modern_sqlite(tmp_path: Path):
    """The positive case — most CPython distributions ship FTS5, so
    `_require_fts5` must be a no-op on a default SQLite connection."""

    from trade_trace.storage.migrations import _require_fts5

    db = _open(tmp_path)
    try:
        _require_fts5(db.connection)  # no exception
    finally:
        db.close()


def test_partial_migration_rolls_back(tmp_path: Path, monkeypatch):
    """A migration that raises mid-loop must leave schema_version unchanged."""

    def _bad_migration(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE __halfway (x TEXT)")
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(
        "trade_trace.storage.migrations.MIGRATIONS",
        MIGRATIONS + [_bad_migration],
    )

    db = _open(tmp_path)
    try:
        # First, apply only the legit migrations so we have a known starting state.
        apply_pending_migrations(db.connection, target_version=len(MIGRATIONS))
        baseline = current_version(db.connection)
        with pytest.raises(RuntimeError):
            apply_pending_migrations(db.connection)
        # The schema_version must NOT have advanced.
        assert current_version(db.connection) == baseline
        # The half-baked table must NOT survive the rollback.
        cur = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE name = '__halfway'"
        )
        assert cur.fetchone() is None
    finally:
        db.close()


def _legacy_alter_table_on(conn: sqlite3.Connection) -> bool:
    """Read the session-scoped `legacy_alter_table` pragma as a bool."""

    return bool(conn.execute("PRAGMA legacy_alter_table").fetchone()[0])


def test_m025_resets_legacy_alter_table_pragma_after_mid_migration_failure(
    tmp_path: Path, monkeypatch
):
    """Per bead trade-trace-x17b: migration 025 sets the session-scoped
    `PRAGMA legacy_alter_table=ON` before rebuilding the outcomes /
    forecast_scores tables. SQLite does NOT reset session pragmas on
    ROLLBACK, so if the migration body raises between the ON and the
    reset, the pragma would leak ON for the rest of the connection's
    lifetime — silently changing RENAME-based ALTER TABLE semantics for
    any later migration on the same connection (e.g. after a retry).

    The fix wraps the body in try/finally so the pragma is reset to OFF
    even on exception. This test forces a mid-migration failure and
    asserts the pragma is OFF on the connection afterward.
    """

    import trade_trace.storage.migrations.m025_polymarket_resolution_finality as m025

    pragma_was_on_during_body: list[bool] = []

    def _boom(conn: sqlite3.Connection, status_sql: str) -> None:
        # Confirm we are exercising the leak path: the pragma must already
        # be ON when the body runs (otherwise this test would pass
        # vacuously even if the ON line were removed).
        pragma_was_on_during_body.append(_legacy_alter_table_on(conn))
        raise RuntimeError("simulated mid-migration failure inside m025")

    monkeypatch.setattr(m025, "_rebuild_outcomes_and_forecast_scores", _boom)

    db = _open(tmp_path)
    try:
        # Bring the DB to schema_version 24 so migration 025 is next.
        apply_pending_migrations(db.connection, target_version=24)
        assert current_version(db.connection) == 24
        assert _legacy_alter_table_on(db.connection) is False

        with pytest.raises(RuntimeError, match="simulated mid-migration failure"):
            apply_pending_migrations(db.connection, target_version=25)

        # The body did run with the pragma ON (leak path is real)...
        assert pragma_was_on_during_body == [True]
        # ...but the finally clause reset it back to OFF despite the raise.
        assert _legacy_alter_table_on(db.connection) is False, (
            "legacy_alter_table pragma leaked ON after a failed m025 migration"
        )
        # The transaction rolled back, so the version did not advance.
        assert current_version(db.connection) == 24
    finally:
        db.close()


def test_strategy_id_new_row_triggers_grandfather_preexisting_rows(tmp_path: Path):
    """Migration 010 validates only new inserts: orphan strategy_id rows
    that already existed after migration 009 are not retroactively rejected.
    """

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection, target_version=9)
        db.connection.executescript(
            """
            INSERT INTO venues(id, name, kind, created_at, actor_id)
                VALUES ('v_1', 'manual', 'manual', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
                VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO decisions(id, instrument_id, type, strategy_id, created_at, actor_id)
                VALUES ('d_old', 'i_1', 'skip', 'missing_strategy', '2026-05-18T14:00:00Z', 'agent:default');
            INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id)
                VALUES ('t_old', 'i_1', 'yes', '...', 'missing_strategy', '2026-05-18T14:00:00Z', 'agent:default');
            """
        )

        before, after = apply_pending_migrations(db.connection)
        assert (before, after) == (9, len(MIGRATIONS))
        assert db.connection.execute(
            "SELECT strategy_id FROM decisions WHERE id = 'd_old'"
        ).fetchone()[0] == "missing_strategy"
        assert db.connection.execute(
            "SELECT strategy_id FROM theses WHERE id = 't_old'"
        ).fetchone()[0] == "missing_strategy"

        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, type, strategy_id, created_at, actor_id) "
                "VALUES ('d_new', 'i_1', 'skip', 'missing_strategy', '2026-05-18T14:00:00Z', 'agent:default')"
            )
        assert "VALIDATION_ERROR" in str(exc.value)
        assert "decisions.strategy_id" in str(exc.value)
    finally:
        db.close()


def test_playbook_version_id_new_row_trigger_rejects_dangling_fk(tmp_path: Path):
    """Migration 030 (bead trade-trace-2kpi) adds a BEFORE INSERT trigger
    on `decisions` that aborts when a non-NULL `playbook_version_id` is
    absent from `playbook_versions` — mirroring m010's
    `trg_decisions_strategy_id_exists` for `strategy_id`.

    Proves four facts:
    - an orphan `playbook_version_id` row that predated the trigger is
      grandfathered (inserted before migration 030 runs);
    - a NULL `playbook_version_id` stays legal after the trigger lands;
    - a non-NULL `playbook_version_id` that exists in `playbook_versions`
      is accepted;
    - a non-NULL `playbook_version_id` that does NOT exist is rejected at
      insert time with a VALIDATION_ERROR.
    """

    ts = "2026-05-18T14:00:00Z"
    db = _open(tmp_path)
    try:
        # Stop before migration 030 so we can plant a grandfathered orphan.
        apply_pending_migrations(db.connection, target_version=29)
        db.connection.executescript(
            f"""
            INSERT INTO venues(id, name, kind, created_at, actor_id)
                VALUES ('v_1', 'manual', 'manual', '{ts}', 'agent:default');
            INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
                VALUES ('i_1', 'v_1', 'Test', 'prediction_market', '{ts}', 'agent:default');
            INSERT INTO decisions(id, instrument_id, type, playbook_version_id, created_at, actor_id)
                VALUES ('d_old', 'i_1', 'skip', 'missing_pv', '{ts}', 'agent:default');
            """
        )

        before, after = apply_pending_migrations(db.connection)
        assert (before, after) == (29, len(MIGRATIONS))

        # Grandfathered: the pre-existing orphan row survived the migration.
        assert db.connection.execute(
            "SELECT playbook_version_id FROM decisions WHERE id = 'd_old'"
        ).fetchone()[0] == "missing_pv"

        # NULL stays legal.
        db.connection.execute(
            "INSERT INTO decisions(id, instrument_id, type, playbook_version_id, created_at, actor_id) "
            f"VALUES ('d_null', 'i_1', 'skip', NULL, '{ts}', 'agent:default')"
        )

        # A real playbook_version is accepted. Build the chain:
        # reflection memory_node -> playbook -> playbook_version.
        db.connection.executescript(
            f"""
            INSERT INTO memory_nodes(id, node_type, body, valid_from, created_at, actor_id)
                VALUES ('mn_refl', 'reflection', 'lineage', '{ts}', '{ts}', 'agent:default');
            INSERT INTO playbooks(id, name, created_at, actor_id)
                VALUES ('pb_1', 'pb', '{ts}', 'agent:default');
            INSERT INTO playbook_versions(
                id, playbook_id, version, provenance_reflection_node_id, created_at, actor_id
            ) VALUES ('pv_1', 'pb_1', 1, 'mn_refl', '{ts}', 'agent:default');
            """
        )
        db.connection.execute(
            "INSERT INTO decisions(id, instrument_id, type, playbook_version_id, created_at, actor_id) "
            f"VALUES ('d_ok', 'i_1', 'skip', 'pv_1', '{ts}', 'agent:default')"
        )
        assert db.connection.execute(
            "SELECT playbook_version_id FROM decisions WHERE id = 'd_ok'"
        ).fetchone()[0] == "pv_1"

        # A dangling FK is rejected at insert time.
        with pytest.raises(sqlite3.IntegrityError) as exc:
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, type, playbook_version_id, created_at, actor_id) "
                f"VALUES ('d_bad', 'i_1', 'skip', 'missing_pv', '{ts}', 'agent:default')"
            )
        assert "VALIDATION_ERROR" in str(exc.value)
        assert "decisions.playbook_version_id" in str(exc.value)
        # The rejected insert did not land.
        assert db.connection.execute(
            "SELECT COUNT(*) FROM decisions WHERE id = 'd_bad'"
        ).fetchone()[0] == 0
    finally:
        db.close()


def _edges_supersedes_index_sql(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'index' AND name = 'idx_edges_supersedes'"
    ).fetchone()
    return None if row is None else " ".join((row[0] or "").split())


def test_migration_031_creates_supersedes_partial_index(tmp_path: Path):
    """Migration 031 (bead trade-trace-17k9) adds a partial covering
    index keyed on `edge_type='supersedes'` so the `_superseded_node_ids`
    recall scan is a tight index seek instead of a full scan of the
    memory_node target partition. Migration 003 ships only
    idx_edges_source / idx_edges_target / idx_edges_type, none of which
    cover the triple-predicate equality."""

    db = _open(tmp_path)
    try:
        before, after = apply_pending_migrations(db.connection)
        assert before == 0
        assert after == len(MIGRATIONS)

        assert "idx_edges_supersedes" in _index_names(db.connection, "edges")
        sql = _edges_supersedes_index_sql(db.connection)
        assert sql is not None
        # The index must be partial (only supersedes edges) and cover the
        # equality columns, the optional `created_at` range, and the
        # projected `target_id` (so the DISTINCT scan never touches the
        # table).
        assert (
            "CREATE INDEX idx_edges_supersedes ON edges"
            "(source_kind, target_kind, created_at, target_id) "
            "WHERE edge_type = 'supersedes'" == sql
        )
    finally:
        db.close()


def _supersedes_scan_plan(conn: sqlite3.Connection, *, with_as_of: bool) -> str:
    sql = (
        "EXPLAIN QUERY PLAN "
        "SELECT DISTINCT target_id FROM edges "
        "WHERE source_kind = 'memory_node' "
        "AND target_kind = 'memory_node' "
        "AND edge_type = 'supersedes'"
    )
    if with_as_of:
        sql += " AND created_at <= '2026-06-01T00:00:00Z'"
    return " ".join(
        str(row[-1]) for row in conn.execute(sql).fetchall()
    )


def test_migration_031_supersedes_scan_uses_index_seek(tmp_path: Path):
    """With a realistic mix of edges (many cross-type edges into
    memory_nodes, a few supersedes edges) and table statistics, the
    `_superseded_node_ids` query — in both its point-in-time and
    no-as_of forms — resolves through the new partial covering index
    rather than scanning the memory_node target partition row-by-row
    via idx_edges_target."""

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        conn = db.connection

        ts = "2026-01-01T00:00:00Z"
        rows: list[tuple[str, str, str, str, str, str, str, str]] = []
        # Noise: cross-type edges into memory_nodes (about) and same-kind
        # edges with a different edge_type (supports).
        for i in range(2000):
            rows.append(
                (f"e_about_{i}", "memory_node", f"mn_{i}",
                 "instrument", f"ins_{i}", "about", ts, "agent:default")
            )
        for i in range(2000):
            rows.append(
                (f"e_sup_{i}", "memory_node", f"mn_{i}",
                 "memory_node", f"mn_t_{i}", "supports", ts, "agent:default")
            )
        # The needles: a handful of supersedes edges.
        for i in range(25):
            rows.append(
                (f"e_ss_{i}", "memory_node", f"mn_{i}",
                 "memory_node", f"mn_old_{i}", "supersedes", ts, "agent:default")
            )
        conn.executemany(
            "INSERT INTO edges("
            "id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.execute("ANALYZE")

        for with_as_of in (False, True):
            plan = _supersedes_scan_plan(conn, with_as_of=with_as_of)
            assert "idx_edges_supersedes" in plan, (
                f"supersedes scan (with_as_of={with_as_of}) did not use the "
                f"partial index; plan was: {plan!r}"
            )
            # A covering index seek never visits the base table.
            assert "SCAN edges" not in plan, (
                f"supersedes scan (with_as_of={with_as_of}) fell back to a "
                f"full table scan; plan was: {plan!r}"
            )
    finally:
        db.close()


def _positions_opened_at_index_sql(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'index' AND name = 'idx_positions_opened_at'"
    ).fetchone()
    return None if row is None else " ".join((row[0] or "").split())


def test_migration_032_creates_positions_opened_at_index(tmp_path: Path):
    """Migration 032 (bead trade-trace-b5hg) adds a composite keyset
    index matching the `list_positions` page order so the paginated scan
    no longer full-scans `positions` plus a sort pass. Migration 003
    ships only idx_positions_instr / idx_positions_status, neither of
    which covers `opened_at`."""

    db = _open(tmp_path)
    try:
        before, after = apply_pending_migrations(db.connection)
        assert before == 0
        assert after == len(MIGRATIONS)

        assert "idx_positions_opened_at" in _index_names(db.connection, "positions")
        sql = _positions_opened_at_index_sql(db.connection)
        assert sql is not None
        # The index must match the keyset order key exactly:
        # opened_at DESC, id DESC.
        assert (
            "CREATE INDEX idx_positions_opened_at ON positions"
            "(opened_at DESC, id DESC)" == sql
        )
    finally:
        db.close()


def _seed_positions(conn: sqlite3.Connection, *, count: int) -> None:
    ts = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) "
        "VALUES ('v', 'V', 'prediction_market', '{}', ?, 'agent:test')",
        (ts,),
    )
    conn.execute(
        "INSERT INTO instruments("
        "id, venue_id, external_id, title, asset_class, "
        "metadata_json, created_at, actor_id) "
        "VALUES ('i', 'v', 'x', 't', 'prediction_market', '{}', ?, 'agent:test')",
        (ts,),
    )
    conn.executemany(
        "INSERT INTO positions("
        "id, instrument_id, kind, side, status, opened_at, updated_at) "
        "VALUES (?, 'i', 'paper', 'yes', 'open', ?, ?)",
        [
            (f"p{k:05d}", f"2026-01-{(k % 28) + 1:02d}T00:00:00Z", ts)
            for k in range(count)
        ],
    )


def test_migration_032_positions_page_scan_uses_index(tmp_path: Path):
    """With a realistic positions projection and table statistics, the
    keyset page scan (ORDER BY opened_at DESC, id DESC) and the
    opened_from/opened_to range filters resolve through the new covering
    index instead of full-scanning `positions` and sorting."""

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        conn = db.connection
        _seed_positions(conn, count=3000)
        conn.execute("ANALYZE")

        # Range filter (opened_from/opened_to) resolves as an index range.
        range_plan = " ".join(
            str(row[-1])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT p.id FROM positions p "
                "WHERE p.opened_at >= ? AND p.opened_at <= ? "
                "ORDER BY p.opened_at DESC, p.id DESC LIMIT 51",
                ("2026-01-05T00:00:00Z", "2026-01-20T00:00:00Z"),
            ).fetchall()
        )
        assert "idx_positions_opened_at" in range_plan, range_plan
        assert "USE TEMP B-TREE FOR ORDER BY" not in range_plan, range_plan

        # Keyset cursor predicate walks the index in order (no sort pass).
        cursor_plan = " ".join(
            str(row[-1])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT p.id FROM positions p "
                "WHERE (p.opened_at < ? OR (p.opened_at = ? AND p.id < ?)) "
                "ORDER BY p.opened_at DESC, p.id DESC LIMIT 51",
                ("2026-01-20T00:00:00Z", "2026-01-20T00:00:00Z", "p99999"),
            ).fetchall()
        )
        assert "idx_positions_opened_at" in cursor_plan, cursor_plan
        assert "USE TEMP B-TREE FOR ORDER BY" not in cursor_plan, cursor_plan
    finally:
        db.close()


def test_migration_032_list_positions_pagination_and_range_filter(tmp_path: Path):
    """The new index is perf-only: list_positions pagination and the
    opened_from/opened_to range filters must still return identical,
    correctly ordered results."""

    from trade_trace.reporting.position_rows import list_positions

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        conn = db.connection
        _seed_positions(conn, count=120)

        # Full walk via keyset pagination must visit every row exactly
        # once in (opened_at DESC, id DESC) order.
        seen: list[str] = []
        cursor: str | None = None
        while True:
            page = list_positions(conn, cursor=cursor, limit=25)
            seen.extend(r.position_id for r in page.rows)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert len(seen) == 120
        assert len(set(seen)) == 120

        keys = [
            (r.opened_at, r.position_id)
            for r in (
                list_positions(conn, limit=200).rows
            )
        ]
        assert keys == sorted(keys, reverse=True)

        # Range filter narrows to the inclusive [from, to] opened_at window.
        windowed = list_positions(
            conn,
            limit=200,
            opened_from="2026-01-10T00:00:00Z",
            opened_to="2026-01-15T00:00:00Z",
        ).rows
        assert windowed, "expected positions in the opened_at window"
        for r in windowed:
            assert "2026-01-10T00:00:00Z" <= r.opened_at <= "2026-01-15T00:00:00Z"
        # And it is a strict subset of the unfiltered set.
        assert {r.position_id for r in windowed} < set(seen)
    finally:
        db.close()


def _decisions_type_created_at_index_sql(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type = 'index' AND name = 'idx_decisions_type_created_at'"
    ).fetchone()
    return None if row is None else " ".join((row[0] or "").split())


def test_migration_033_creates_decisions_type_created_at_index(tmp_path: Path):
    """Migration 033 (bead trade-trace-ynam) adds a composite index
    matching the `list_trades` filter+sort so the trade-listing scan no
    longer full-scans `decisions` plus a sort pass. Migration 003 ships
    only idx_decisions_instr / idx_decisions_thesis /
    idx_decisions_strategy, none of which cover `type` or `created_at`."""

    db = _open(tmp_path)
    try:
        before, after = apply_pending_migrations(db.connection)
        assert before == 0
        assert after == len(MIGRATIONS)

        assert "idx_decisions_type_created_at" in _index_names(
            db.connection, "decisions"
        )
        sql = _decisions_type_created_at_index_sql(db.connection)
        assert sql is not None
        # The index must match the filter+sort order key: type (the
        # IN-filter), then created_at DESC (the keyset sort key).
        assert (
            "CREATE INDEX idx_decisions_type_created_at ON decisions"
            "(type, created_at DESC)" == sql
        )
    finally:
        db.close()


def _seed_decisions(conn: sqlite3.Connection, *, count: int) -> None:
    ts = "2026-01-01T00:00:00Z"
    conn.execute(
        "INSERT INTO venues(id, name, kind, metadata_json, created_at, actor_id) "
        "VALUES ('v', 'V', 'prediction_market', '{}', ?, 'agent:test')",
        (ts,),
    )
    conn.execute(
        "INSERT INTO instruments("
        "id, venue_id, external_id, title, asset_class, "
        "metadata_json, created_at, actor_id) "
        "VALUES ('i', 'v', 'x', 't', 'prediction_market', '{}', ?, 'agent:test')",
        (ts,),
    )
    # A realistic mix: the six trading types plus non-trading noise rows
    # (watch/skip) that the WHERE clause must exclude.
    trading_types = (
        "actual_enter", "actual_exit", "paper_enter",
        "paper_exit", "add", "reduce",
    )
    noise_types = ("watch", "skip", "hold")
    types = trading_types + noise_types
    conn.executemany(
        "INSERT INTO decisions("
        "id, instrument_id, type, metadata_json, created_at, actor_id) "
        "VALUES (?, 'i', ?, '{}', ?, 'agent:test')",
        [
            (
                f"d{k:05d}",
                types[k % len(types)],
                f"2026-01-{(k % 28) + 1:02d}T00:00:00.{k % 1000:03d}000Z",
            )
            for k in range(count)
        ],
    )


def test_migration_033_list_trades_scan_uses_index(tmp_path: Path):
    """With a realistic decisions table and statistics, the list_trades
    keyset page scan (type IN (...) ORDER BY created_at DESC, id DESC),
    the opened_from/opened_to range filter, and the cursor predicate all
    resolve through the new composite index instead of full-scanning
    `decisions`."""

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        conn = db.connection
        _seed_decisions(conn, count=3000)
        conn.execute("ANALYZE")

        type_placeholders = ",".join("?" * 6)
        trading = (
            "actual_enter", "actual_exit", "paper_enter",
            "paper_exit", "add", "reduce",
        )

        # Base filter + sort: each type partition is walked in index order.
        base_plan = " ".join(
            str(row[-1])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT d.id FROM decisions d "
                f"WHERE d.type IN ({type_placeholders}) "
                "ORDER BY d.created_at DESC, d.id DESC LIMIT 51",
                trading,
            ).fetchall()
        )
        assert "idx_decisions_type_created_at" in base_plan, base_plan
        assert "SCAN decisions" not in base_plan, base_plan

        # opened_from/opened_to range resolves as an index range, not a
        # residual predicate over a full scan.
        range_plan = " ".join(
            str(row[-1])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT d.id FROM decisions d "
                f"WHERE d.type IN ({type_placeholders}) "
                "AND d.created_at >= ? AND d.created_at <= ? "
                "ORDER BY d.created_at DESC, d.id DESC LIMIT 51",
                (*trading, "2026-01-05T00:00:00Z", "2026-01-20T00:00:00Z"),
            ).fetchall()
        )
        assert "idx_decisions_type_created_at" in range_plan, range_plan
        assert "SCAN decisions" not in range_plan, range_plan

        # Keyset cursor predicate seeks via the index rather than scanning.
        cursor_plan = " ".join(
            str(row[-1])
            for row in conn.execute(
                "EXPLAIN QUERY PLAN "
                "SELECT d.id FROM decisions d "
                f"WHERE d.type IN ({type_placeholders}) "
                "AND (d.created_at < ? OR (d.created_at = ? AND d.id < ?)) "
                "ORDER BY d.created_at DESC, d.id DESC LIMIT 51",
                (*trading, "2026-01-20T00:00:00Z", "2026-01-20T00:00:00Z", "d99999"),
            ).fetchall()
        )
        assert "idx_decisions_type_created_at" in cursor_plan, cursor_plan
        assert "SCAN decisions" not in cursor_plan, cursor_plan
    finally:
        db.close()


def test_migration_033_list_trades_pagination_and_range_filter(tmp_path: Path):
    """The new index is perf-only: list_trades pagination, the
    opened_from/opened_to range filter, and the non-trading-type
    exclusion must still return identical, correctly ordered results."""

    from trade_trace.reporting.trade_rows import list_trades

    db = _open(tmp_path)
    try:
        apply_pending_migrations(db.connection)
        conn = db.connection
        _seed_decisions(conn, count=120)

        # Full walk via keyset pagination must visit every trading row
        # exactly once in (created_at DESC, id DESC) order, and never a
        # non-trading (watch/skip/hold) row.
        seen: list[str] = []
        cursor: str | None = None
        while True:
            page = list_trades(conn, cursor=cursor, limit=25)
            seen.extend(r.decision_id for r in page.rows)
            cursor = page.next_cursor
            if cursor is None:
                break
        # 6 trading types out of 9 total → 6/9 of 120 rows are trades.
        expected_trades = sum(
            1
            for k in range(120)
            if k % 9 < 6
        )
        assert len(seen) == expected_trades
        assert len(set(seen)) == expected_trades

        rows = list_trades(conn, limit=200).rows
        keys = [(r.decision_at, r.decision_id) for r in rows]
        assert keys == sorted(keys, reverse=True)
        # No non-trading type ever appears.
        assert all(r.decision_type in {
            "actual_enter", "actual_exit", "paper_enter",
            "paper_exit", "add", "reduce",
        } for r in rows)

        # Range filter narrows to the inclusive [from, to] created_at window.
        windowed = list_trades(
            conn,
            limit=200,
            opened_from="2026-01-10",
            opened_to="2026-01-15",
        ).rows
        assert windowed, "expected trades in the created_at window"
        # Date-only bounds expand to inclusive day boundaries:
        # opened_from -> T00:00:00.000000Z, opened_to -> T23:59:59.999999Z.
        for r in windowed:
            assert (
                "2026-01-10T00:00:00.000000Z"
                <= r.decision_at
                <= "2026-01-15T23:59:59.999999Z"
            )
        assert {r.decision_id for r in windowed} < set(seen)
    finally:
        db.close()


def test_schema_meta_mismatch_detects_column_drift_from_migration_004(tmp_path: Path):
    """Per trade-trace-n1mm: when the DB has columns on disk that a
    not-yet-run column-only migration would add (migration 004's
    risk-units stub), the runner must surface SchemaMetaMismatchError
    with the offending columns instead of letting SQLite raise
    "duplicate column name". Migration 010 is trigger-only and is
    explicitly out of scope per
    docs/architecture/schema-meta-diagnostics.md."""

    from trade_trace.storage.migrations import SchemaMetaMismatchError

    db = _open(tmp_path)
    try:
        # Bring the DB up to migration 4 (which adds the columns), then
        # rewind meta.schema_version to 3 so the runner thinks 004 is
        # still pending. The columns are already on disk.
        apply_pending_migrations(db.connection, target_version=4)
        assert current_version(db.connection) == 4
        db.connection.execute(
            "UPDATE meta SET value = '3' WHERE key = 'schema_version'"
        )
        assert current_version(db.connection) == 3

        with pytest.raises(SchemaMetaMismatchError) as exc:
            apply_pending_migrations(db.connection)

        err = exc.value
        assert err.current_version == 3
        # The diagnostic must enumerate the migration-004 columns the
        # check found already present on disk.
        assert "theses" in err.unexpected_columns
        assert "risk_unit_label" in err.unexpected_columns["theses"]
        assert "decisions" in err.unexpected_columns
        assert "declared_risk_amount" in err.unexpected_columns["decisions"]
        # And must NOT contain a raw SQLite "duplicate column" message.
        msg = str(err)
        assert "duplicate column name" not in msg.lower()
        assert "schema/meta mismatch" in msg
    finally:
        db.close()
