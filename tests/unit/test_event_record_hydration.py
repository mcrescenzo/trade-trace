import sqlite3

from trade_trace import exporter
from trade_trace.events import log as event_log
from trade_trace.events.log import EventRecord, EventWriter


def _conn_with_event() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE events(
            id INTEGER PRIMARY KEY,
            event_type TEXT NOT NULL,
            subject_kind TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            idempotency_key TEXT,
            created_at TEXT NOT NULL,
            request_id TEXT,
            agent_id TEXT,
            model_id TEXT,
            environment TEXT,
            run_id TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO events(
            id, event_type, subject_kind, subject_id, payload_json,
            actor_id, idempotency_key, created_at, request_id,
            agent_id, model_id, environment, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "idea.created",
            "idea",
            "idea-1",
            '{"idea_id":"idea-1"}',
            "actor-1",
            "idem-1",
            "2026-01-01T00:00:00Z",
            "req-1",
            "agent-1",
            "model-1",
            "test",
            "run-1",
        ),
    )
    return conn


def test_event_replay_and_exporter_load_hydrate_with_shared_event_record_api(monkeypatch):
    assert event_log.EVENT_RECORD_SELECT_COLUMNS == (
        "id",
        "event_type",
        "subject_kind",
        "subject_id",
        "payload_json",
        "actor_id",
        "idempotency_key",
        "created_at",
        "request_id",
        "agent_id",
        "model_id",
        "environment",
        "run_id",
    )

    conn = _conn_with_event()
    calls = []
    original_from_row = EventRecord.from_row

    def tracking_from_row(row):
        calls.append(tuple(row))
        return original_from_row(row)

    monkeypatch.setattr(EventRecord, "from_row", staticmethod(tracking_from_row))

    replay_record = EventWriter(conn).find_existing(
        event_type="idea.created", actor_id="actor-1", idempotency_key="idem-1"
    )
    exported_record = exporter._load_event(conn, 1)

    assert replay_record == exported_record
    assert replay_record.request_id == "req-1"
    assert replay_record.agent_id == "agent-1"
    assert replay_record.model_id == "model-1"
    assert replay_record.environment == "test"
    assert replay_record.run_id == "run-1"
    assert len(calls) == 2
