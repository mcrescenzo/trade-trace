"""Per-tool event emission per trade-trace-vvt.

Every M1 write tool must write (a) the relational row, (b) one `events`
row, (c) one `outbox` row when `outbox.jsonl_enabled = true`. All three
inside one transaction (persistence.md §6 unit-of-work boundary).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.events import EventWriter
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True

    # Enable outbox so each emit also lands an outbox row.
    db = open_database(db_path(h))
    try:
        apply_pending_migrations(db.connection)
        EventWriter(db.connection).set_outbox_jsonl_enabled()
        db.connection.commit()
    finally:
        db.close()
    return h


def _event_count(home: Path, event_type: str) -> int:
    db = open_database(db_path(home))
    try:
        row = db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = ?", (event_type,)
        ).fetchone()
        return int(row[0])
    finally:
        db.close()


def _outbox_count(home: Path) -> int:
    db = open_database(db_path(home))
    try:
        row = db.connection.execute("SELECT COUNT(*) FROM outbox").fetchone()
        return int(row[0])
    finally:
        db.close()


def _event_payload(home: Path, event_type: str) -> dict:
    db = open_database(db_path(home))
    try:
        row = db.connection.execute(
            "SELECT payload_json FROM events WHERE event_type = ? "
            "ORDER BY id DESC LIMIT 1",
            (event_type,),
        ).fetchone()
    finally:
        db.close()
    return json.loads(row[0])


# -- per-tool emission ---------------------------------------------------


def test_venue_add_emits_event(home):
    res = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    assert res["ok"] is True
    assert _event_count(home, "venue.created") == 1
    payload = _event_payload(home, "venue.created")
    assert payload["id"] == res["data"]["id"]
    assert payload["name"] == "PM"


def test_instrument_add_emits_event(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"], "asset_class": "equity", "title": "AAPL",
    })
    assert _event_count(home, "instrument.created") == 1
    payload = _event_payload(home, "instrument.created")
    assert payload["id"] == inst["data"]["id"]
    assert payload["venue_id"] == venue["data"]["id"]


def test_snapshot_add_emits_event(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X",
    })
    snap = _envelope(home, "snapshot.add", {
        "instrument_id": inst["data"]["id"],
        "captured_at": "2026-05-18T14:00:00Z", "price": 0.42,
    })
    assert _event_count(home, "snapshot.added") == 1
    payload = _event_payload(home, "snapshot.added")
    assert payload["id"] == snap["data"]["id"]


def test_thesis_add_emits_event(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    assert _event_count(home, "thesis.created") == 1
    assert _event_payload(home, "thesis.created")["id"] == thesis["data"]["id"]


def test_forecast_add_emits_event(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    assert _event_count(home, "forecast.created") == 1
    payload = _event_payload(home, "forecast.created")
    assert payload["id"] == f["data"]["id"]
    assert payload["yes_label"] == "yes"


def test_decision_add_emits_event(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X",
    })
    dec = _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"], "type": "skip", "reason": "spread wide",
    })
    assert _event_count(home, "decision.created") == 1
    assert _event_payload(home, "decision.created")["id"] == dec["data"]["id"]


def test_outcome_add_emits_event(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X",
    })
    out = _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
        "confidence": 0.99,
    })
    assert _event_count(home, "outcome.recorded") == 1
    assert _event_payload(home, "outcome.recorded")["id"] == out["data"]["id"]


def test_outcome_add_auto_scores_emits_forecast_scored(home):
    """resolved_final outcome triggers auto-score → forecast.scored event."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
        "confidence": 0.99,
    })
    assert _event_count(home, "forecast.scored") == 1
    payload = _event_payload(home, "forecast.scored")
    assert payload["metric"] == "brier_binary"
    assert payload["score"] == pytest.approx(0.16)


def test_source_add_emits_event(home):
    src = _envelope(home, "source.add", {"kind": "url", "ref": "https://example.com"})
    assert _event_count(home, "source.added") == 1
    assert _event_payload(home, "source.added")["id"] == src["data"]["id"]


def test_source_attach_to_thesis_emits_event(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    src = _envelope(home, "source.add", {"kind": "url", "ref": "https://x", "stance": "supports"})
    att = _envelope(home, "source.attach_to_thesis", {
        "source_id": src["data"]["id"], "target_id": thesis["data"]["id"],
    })
    assert _event_count(home, "source.attached") == 1
    payload = _event_payload(home, "source.attached")
    assert payload["id"] == att["data"]["id"]
    assert payload["edge_type"] == "supports"


def test_forecast_supersede_emits_superseded_event(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"], "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    first = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    })
    sup = _envelope(home, "forecast.supersede", {
        "prior_forecast_id": first["data"]["id"],
        "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.7},
            {"outcome_label": "no", "probability": 0.3},
        ],
    })
    assert _event_count(home, "forecast.superseded") == 1
    payload = _event_payload(home, "forecast.superseded")
    assert payload["new_forecast_id"] == sup["data"]["id"]
    assert payload["prior_forecast_id"] == first["data"]["id"]


# -- outbox row appended in same transaction -----------------------------


def test_each_emit_appends_outbox_row(home):
    """One write tool call → one outbox row (when outbox.jsonl_enabled)."""

    assert _outbox_count(home) == 0
    _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    assert _outbox_count(home) == 1


# -- idempotency replay ------------------------------------------------


def test_replay_with_same_idempotency_key_returns_same_id(home):
    """Replay invariant: same key → same row id, no second row, no PK
    conflict."""

    first = _envelope(home, "venue.add", {
        "name": "PM", "kind": "prediction_market", "idempotency_key": "ven-1",
    })
    second = _envelope(home, "venue.add", {
        "name": "PM", "kind": "prediction_market", "idempotency_key": "ven-1",
    })
    assert first["ok"] is True and second["ok"] is True
    assert second["data"]["id"] == first["data"]["id"]
    # Only one row in venues.
    db = open_database(db_path(home))
    try:
        count = db.connection.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
    finally:
        db.close()
    assert count == 1


def test_replay_with_conflicting_payload_raises(home):
    """Same key with structurally different fields → IDEMPOTENCY_CONFLICT."""

    _envelope(home, "venue.add", {
        "name": "PM", "kind": "prediction_market", "idempotency_key": "ven-conf",
    })
    env = _envelope(home, "venue.add", {
        # Same key, different structural fields → conflict.
        "name": "Different", "kind": "prediction_market", "idempotency_key": "ven-conf",
    })
    assert env["ok"] is False
    assert env["error"]["code"] in ("STORAGE_ERROR", "IDEMPOTENCY_CONFLICT")


# -- end-to-end drain → replay round trip ------------------------------


def test_drain_then_replay_round_trip(home, tmp_path):
    """The capstone: a sequence of dispatch() calls populates events +
    outbox; drain produces JSONL files; each file replays through dispatch
    on a fresh DB without error."""

    from trade_trace.exporter import drain_outbox

    # Build a small flow.
    venue = _envelope(home, "venue.add", {
        "id": "ven_rt_1", "name": "PM", "kind": "prediction_market",
        "idempotency_key": "rt-venue",
    })
    inst = _envelope(home, "instrument.add", {
        "id": "ins_rt_1", "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
        "idempotency_key": "rt-instr",
    })
    _envelope(home, "thesis.add", {
        "id": "th_rt_1", "instrument_id": inst["data"]["id"],
        "side": "yes", "body": "Catalyst rationale.",
        "idempotency_key": "rt-thesis",
    })

    # Drain to disk.
    db = open_database(db_path(home))
    try:
        with db.transaction():
            result = drain_outbox(db.connection, home)
    finally:
        db.close()
    assert len(result.exported_files) >= 3

    # Replay each line against a fresh DB. Iterate in drain order (event_id
    # ASC) — `result.exported_files` preserves that. Sorting by path would
    # alphabetize and break the parents-before-children invariant.
    dst_home = tmp_path / "dst"
    mcp_call("journal.init", {"home": str(dst_home)})
    for path in result.exported_files:
        line = json.loads(path.read_text())
        if line["_event_type"] not in (
            "venue.created", "instrument.created", "thesis.created"
        ):
            continue
        env = _envelope(dst_home, line["tool"], line["args"])
        assert env["ok"] is True, (line["tool"], env)

    # The replayed DB has the same caller-assigned IDs.
    db = open_database(db_path(dst_home))
    try:
        assert db.connection.execute("SELECT id FROM venues").fetchone()[0] == "ven_rt_1"
        assert db.connection.execute("SELECT id FROM instruments").fetchone()[0] == "ins_rt_1"
        assert db.connection.execute("SELECT id FROM theses").fetchone()[0] == "th_rt_1"
    finally:
        db.close()
