"""UnitOfWork rollback tests per docs/architecture/persistence.md §6.

A failing tool call must leave zero rows committed across the primary
write, cascades, the `events` row, the `outbox` row, and any projection
updates.
"""

from __future__ import annotations

import pytest

from trade_trace.events import EventWriter, UnitOfWork
from trade_trace.events.unit_of_work import DRY_RUN_FLAG, transaction
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


def _db(tmp_path):
    db = open_database(db_path(tmp_path / "home"))
    apply_pending_migrations(db.connection)
    return db


def _decision_payload():
    return {
        "instrument_id": "i_1",
        "type": "skip",
        "reason": "spread too wide",
        "tags": ["liquidity-ignored"],
    }


def test_uow_commits_event_and_outbox(tmp_path):
    db = _db(tmp_path)
    try:
        # Enable outbox so we can assert the cascade.
        EventWriter(db.connection).set_outbox_jsonl_enabled()

        with UnitOfWork(db.connection) as uow:
            uow.event_writer.write(
                event_type="decision.created",
                subject_kind="decision",
                subject_id="d_1",
                payload=_decision_payload(),
                actor_id="agent:default",
                idempotency_key="abc",
            )

        # After the `with` exits, both rows are committed.
        assert db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert db.connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1
    finally:
        db.close()


def test_uow_rollback_on_exception(tmp_path):
    """A raise inside the with-block must roll back ALL writes — primary,
    event, outbox, and projection."""

    db = _db(tmp_path)
    try:
        EventWriter(db.connection).set_outbox_jsonl_enabled()

        class BoomError(RuntimeError):
            pass

        with pytest.raises(BoomError):
            with UnitOfWork(db.connection) as uow:
                uow.event_writer.write(
                    event_type="decision.created",
                    subject_kind="decision",
                    subject_id="d_1",
                    payload=_decision_payload(),
                    actor_id="agent:default",
                    idempotency_key="abc",
                )
                raise BoomError("simulated cascade failure")

        # Nothing committed.
        assert db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert db.connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    finally:
        db.close()


def test_uow_projection_runs_inside_transaction(tmp_path):
    """Projection updaters run BEFORE commit; if a projection raises, the
    primary write is rolled back too."""

    db = _db(tmp_path)
    try:
        db.connection.execute("CREATE TABLE side_effect (x INTEGER)")
        db.connection.commit()

        # Successful projection.
        with UnitOfWork(db.connection) as uow:
            uow.event_writer.write(
                event_type="decision.created",
                subject_kind="decision",
                subject_id="d_1",
                payload=_decision_payload(),
                actor_id="agent:default",
                idempotency_key="abc-good",
            )

            def _update(conn):
                conn.execute("INSERT INTO side_effect(x) VALUES (1)")

            uow.register_projection(_update)

        assert db.connection.execute("SELECT COUNT(*) FROM side_effect").fetchone()[0] == 1
        assert db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1

        # Failing projection rolls everything back.
        class ProjectionError(RuntimeError):
            pass

        with pytest.raises(ProjectionError):
            with UnitOfWork(db.connection) as uow:
                uow.event_writer.write(
                    event_type="decision.created",
                    subject_kind="decision",
                    subject_id="d_2",
                    payload=_decision_payload(),
                    actor_id="agent:default",
                    idempotency_key="abc-bad",
                )

                def _bad_update(conn):
                    raise ProjectionError("projection blew up")

                uow.register_projection(_bad_update)

        # Only the first event survives; the failing block's event is rolled back.
        assert db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        # `side_effect` stays at 1; the failing block didn't run its updater.
        assert db.connection.execute("SELECT COUNT(*) FROM side_effect").fetchone()[0] == 1
    finally:
        db.close()


def test_transaction_context_manager_equivalent_to_uow(tmp_path):
    db = _db(tmp_path)
    try:
        with transaction(db.connection) as uow:
            uow.event_writer.write(
                event_type="decision.created",
                subject_kind="decision",
                subject_id="d_1",
                payload=_decision_payload(),
                actor_id="agent:default",
                idempotency_key="abc",
            )
        assert db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    finally:
        db.close()


def test_replay_inside_uow_is_idempotent(tmp_path):
    """A replay inside a unit-of-work surfaces idempotent_replay=true without
    double-writing the event row. The UoW still commits cleanly (the replay
    is not an error)."""

    db = _db(tmp_path)
    try:
        with UnitOfWork(db.connection) as uow:
            first = uow.event_writer.write(
                event_type="decision.created",
                subject_kind="decision",
                subject_id="d_1",
                payload=_decision_payload(),
                actor_id="agent:default",
                idempotency_key="abc",
            )

        # Second UoW with the same key.
        with UnitOfWork(db.connection) as uow:
            replay = uow.event_writer.write(
                event_type="decision.created",
                subject_kind="decision",
                subject_id="d_1",
                payload=_decision_payload(),
                actor_id="agent:default",
                idempotency_key="abc",
            )

        assert replay.id == first.id
        assert replay.idempotent_replay is True
        assert db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    finally:
        db.close()


def test_uow_dry_run_rolls_back_all_writes(tmp_path):
    """Under the request-scoped DRY_RUN_FLAG, a UoW that exits normally (no
    exception) must still issue ROLLBACK — guarding the
    `DRY_RUN_FLAG.get()` → ROLLBACK branch in UnitOfWork._commit. If that
    check were removed (or the rollback replaced by a no-op commit), the
    `decision.created` event below would persist and this assertion would
    catch it at the unit level instead of only via the slow MCP path."""

    db = _db(tmp_path)
    try:
        EventWriter(db.connection).set_outbox_jsonl_enabled()

        tok = DRY_RUN_FLAG.set(True)
        try:
            with UnitOfWork(db.connection) as uow:
                # Handlers still observe dry-run via the convenience property.
                assert uow.dry_run is True
                uow.event_writer.write(
                    event_type="decision.created",
                    subject_kind="decision",
                    subject_id="d_1",
                    payload=_decision_payload(),
                    actor_id="agent:default",
                    idempotency_key="dry-run-key",
                )
            # The `with` exited normally — no exception — yet the dry-run
            # branch rolled everything back instead of committing.
        finally:
            DRY_RUN_FLAG.reset(tok)

        assert db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert db.connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    finally:
        db.close()


def test_uow_dry_run_projection_runs_but_side_effects_roll_back(tmp_path):
    """Under dry-run the spec is 'handlers run normally, projections compute,
    then ROLLBACK'. So a registered projection updater MUST still be invoked
    (we assert via a call counter), but any DB write it performs is discarded
    by the rollback — proving projections compute but their side effects do
    not persist."""

    db = _db(tmp_path)
    try:
        db.connection.execute("CREATE TABLE side_effect (x INTEGER)")
        db.connection.commit()

        calls = {"n": 0}

        tok = DRY_RUN_FLAG.set(True)
        try:
            with UnitOfWork(db.connection) as uow:
                uow.event_writer.write(
                    event_type="decision.created",
                    subject_kind="decision",
                    subject_id="d_1",
                    payload=_decision_payload(),
                    actor_id="agent:default",
                    idempotency_key="dry-run-projection",
                )

                def _update(conn):
                    calls["n"] += 1
                    conn.execute("INSERT INTO side_effect(x) VALUES (1)")

                uow.register_projection(_update)
            # Normal exit under dry-run → projection computed, then ROLLBACK.
        finally:
            DRY_RUN_FLAG.reset(tok)

        # The projection callable WAS invoked (it computed inside the txn)...
        assert calls["n"] == 1
        # ...but its write was rolled back along with the event row.
        assert db.connection.execute("SELECT COUNT(*) FROM side_effect").fetchone()[0] == 0
        assert db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    finally:
        db.close()
