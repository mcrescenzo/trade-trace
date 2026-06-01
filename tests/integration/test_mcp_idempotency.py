"""MCP/package-surface idempotency replay and conflict proofs.

These tests exercise dispatch + tool handlers via ``mcp_call`` rather than
EventWriter directly.  They pin the substrate contract backed by the partial
unique index on ``(event_type, actor_id, idempotency_key) WHERE idempotency_key
IS NOT NULL``.  Production omitted-key calls for ``decision.add`` auto-derive
``auto:`` + ``sha256(tool:canonical_json)[:32]``; these explicit-key tests prove
same-actor replay/conflict semantics at the package boundary.
"""

from __future__ import annotations

from pathlib import Path

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.contracts.errors import ErrorCode
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _count_events(home: Path, event_type: str | None = None) -> int:
    db = open_database(db_path(home), create_parent=False)
    try:
        if event_type is None:
            row = db.connection.execute("SELECT COUNT(*) FROM events").fetchone()
        else:
            row = db.connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = ?", (event_type,)
            ).fetchone()
        return int(row[0])
    finally:
        db.close()


def _seed_instrument(home: Path) -> str:
    venue_env = _mcp(
        home,
        "venue.add",
        {"name": "Replay Venue", "kind": "prediction_market"},
    )
    assert venue_env.ok, venue_env
    venue = venue_env.model_dump(mode="json")["data"]["id"]
    instrument_env = _mcp(
        home,
        "instrument.add",
        {
            "venue_id": venue,
            "asset_class": "prediction_market",
            "title": "Replay market",
        },
    )
    assert instrument_env.ok, instrument_env
    return instrument_env.model_dump(mode="json")["data"]["id"]


def test_mcp_same_actor_same_key_same_payload_replays_without_new_events(home):
    instrument_id = _seed_instrument(home)
    args = {
        "instrument_id": instrument_id,
        "type": "skip",
        "reason": "spread too wide",
        "tags": ["liquidity"],
        "idempotency_key": "mcp-positive-idempotency-replay",
    }

    first = _mcp(home, "decision.add", args)
    assert first.ok, first
    event_count_after_first = _count_events(home)
    decision_count_after_first = _count_events(home, "decision.created")

    replay = _mcp(home, "decision.add", dict(args))

    assert replay.ok, replay
    first_dump = first.model_dump(mode="json")
    replay_dump = replay.model_dump(mode="json")
    assert replay_dump["data"]["id"] == first_dump["data"]["id"]
    assert replay_dump["meta"]["idempotency_source"] == "caller"
    assert _count_events(home) == event_count_after_first
    assert _count_events(home, "decision.created") == decision_count_after_first


def test_mcp_same_actor_same_key_different_payload_conflicts_without_new_events(home):
    instrument_id = _seed_instrument(home)
    args = {
        "instrument_id": instrument_id,
        "type": "skip",
        "reason": "spread too wide",
        "tags": ["liquidity"],
        "idempotency_key": "mcp-positive-idempotency-conflict",
    }
    first = _mcp(home, "decision.add", args)
    assert first.ok, first
    event_count_after_first = _count_events(home)
    decision_count_after_first = _count_events(home, "decision.created")

    conflict = _mcp(home, "decision.add", {**args, "tags": ["different-structure"]})

    assert not conflict.ok
    conflict_dump = conflict.model_dump(mode="json")
    error = conflict_dump["error"]
    assert error["code"] == ErrorCode.IDEMPOTENCY_CONFLICT
    assert error["details"]["event_type"] == "decision.created"
    assert error["details"]["actor_id"] == "agent:default"
    assert error["details"]["idempotency_key"] == args["idempotency_key"]
    assert "tags" in error["details"]["diff_summary"]["diff_keys"]
    assert _count_events(home) == event_count_after_first
    assert _count_events(home, "decision.created") == decision_count_after_first
