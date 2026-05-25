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
        assert tuple(row) == ('{"legacy": true}', '{"legacy": true}')
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
