"""Public export.drain surface tests for JSONL outbox."""

from __future__ import annotations

import json
from pathlib import Path

from trade_trace.core import dispatch
from trade_trace.events import EventWriter
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _ok(envelope):
    dumped = envelope.model_dump(mode="json", exclude_none=True)
    assert dumped["ok"] is True, dumped
    return dumped["data"]


def test_export_drain_schema_is_public() -> None:
    data = _ok(dispatch("tool.schema", {"tool": "export.drain"}, actor_id="agent:test"))

    assert data["tool"] == "export.drain"
    assert data["cli_invocation"] == "tt export drain"
    assert data["json_schema"]["properties"]["cleanup_orphans"]["type"] == "boolean"
    assert any("tt export drain" in example for example in data["metadata"]["examples"])
    assert "JSONL" in data["description"]


def test_public_export_drain_exports_pending_jsonl_outbox(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _ok(dispatch("journal.init", {"home": str(home)}, actor_id="agent:test"))
    _ok(
        dispatch(
            "journal.config_set",
            {
                "home": str(home),
                "key": "outbox.jsonl_enabled",
                "value": "true",
                "_confirm": True,
                "idempotency_key": "cfg-jsonl",
            },
            actor_id="agent:test",
        )
    )

    db = open_database(db_path(home), create_parent=False)
    try:
        record = EventWriter(db.connection).write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_public",
            payload={"instrument_id": "i_1", "type": "skip", "reason": "public drain test"},
            actor_id="agent:test",
            idempotency_key="event-1",
        )
        before = db.connection.execute(
            "SELECT state FROM outbox WHERE event_id = ?", (record.id,)
        ).fetchone()
        assert before == ("pending",)
    finally:
        db.close()

    data = _ok(dispatch("export.drain", {"home": str(home)}, actor_id="agent:test"))

    assert data["jsonl_enabled"] is True
    assert data["exported_count"] == 1
    assert data["exported_event_ids"] == [record.id]
    assert len(data["exported_files"]) == 1
    exported_path = Path(data["exported_files"][0])
    assert exported_path.exists()
    line = json.loads(exported_path.read_text(encoding="utf-8"))
    assert line["_event_id"] == record.id
    assert line["tool"] == "decision.add"

    db = open_database(db_path(home), create_parent=False)
    try:
        after = db.connection.execute(
            "SELECT state, exported_at, error_text FROM outbox WHERE event_id = ?",
            (record.id,),
        ).fetchone()
    finally:
        db.close()
    assert after[0] == "exported"
    assert after[1] is not None
    assert after[2] is None

    second = _ok(dispatch("export.drain", {"home": str(home)}, actor_id="agent:test"))
    assert second["exported_count"] == 0
    assert second["counts_before"]["drainable"] == 0
