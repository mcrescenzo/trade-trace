"""memory.link explicit tool with endpoint validation per bead trade-trace-ieh.

Coverage:
- Per-edge_type happy path (7 edge types: about, supports, contradicts,
  supersedes, derived_from, violates, follows).
- Endpoint validation: VALIDATION_ERROR on invalid kind / edge_type;
  NOT_FOUND when from-id or to-id refers to a missing row.
- Idempotency: same payload + same key returns the original edge id
  with `meta.idempotent_replay=true`.
- CLI/MCP parity smoke (registry surfaces match).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _mcp(home: Path, tool: str, args: dict | None = None):
    payload = {"home": str(home), **(args or {})}
    return mcp_call(tool, payload, actor_id="agent:default")


def _seed_two_nodes(home: Path) -> tuple[str, str]:
    a = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "first node",
        "idempotency_key": "00000000-0000-4000-8000-link-1-aaaaaa",
    }).data["id"]
    b = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "second node",
        "idempotency_key": "00000000-0000-4000-8000-link-1-bbbbbb",
    }).data["id"]
    return a, b


def _seed_decision(home: Path) -> str:
    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "thesis",
    }).data["id"]
    return _mcp(home, "decision.add", {
        "type": "actual_enter", "instrument_id": inst,
        "thesis_id": thesis, "side": "yes", "quantity": 1, "price": 0.5,
        "idempotency_key": "00000000-0000-4000-8000-link-decis",
    }).data["id"]


# -- registration ---------------------------------------------


def test_memory_link_registered():
    assert "memory.link" in default_registry().names()


# -- per-edge_type happy paths (7 tests) -----------------------


@pytest.mark.parametrize("edge_type", [
    "about", "supports", "contradicts", "supersedes",
    "derived_from", "violates", "follows",
])
def test_each_edge_type_writes_successfully(home, edge_type):
    """All 7 edge types from the MVP enum are accepted between two
    memory_node endpoints (memory_node→memory_node)."""

    a, b = _seed_two_nodes(home)
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "memory_node", "target_id": b,
        "edge_type": edge_type,
        "idempotency_key": f"00000000-0000-4000-8000-edge-{edge_type}",
    })
    assert env.ok, env
    assert env.data["edge_type"] == edge_type
    assert env.data["source_id"] == a
    assert env.data["target_id"] == b


# -- invalid combinations rejected -----------------------------


def test_invalid_edge_type_rejected(home):
    a, b = _seed_two_nodes(home)
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "memory_node", "target_id": b,
        "edge_type": "frobnicates",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "edge_type"


def test_invalid_source_kind_rejected(home):
    env = _mcp(home, "memory.link", {
        "source_kind": "spaceship", "source_id": "x",
        "target_kind": "memory_node", "target_id": "y",
        "edge_type": "about",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "source_kind"


def test_invalid_target_kind_rejected(home):
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": "x",
        "target_kind": "alien", "target_id": "y",
        "edge_type": "about",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "target_kind"


# -- NOT_FOUND on missing endpoints -----------------------------


def test_not_found_on_missing_source(home):
    a, _b = _seed_two_nodes(home)
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": "mem_nope",
        "target_kind": "memory_node", "target_id": a,
        "edge_type": "about",
    })
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "memory_node"


def test_not_found_on_missing_target(home):
    a, _b = _seed_two_nodes(home)
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "decision", "target_id": "dec_nope",
        "edge_type": "about",
    })
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "decision"


# -- idempotency: same payload + same key replays the original ----


def test_idempotent_replay_returns_same_edge_id(home):
    a, b = _seed_two_nodes(home)
    key = "00000000-0000-4000-8000-replay-1abcd"
    first = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "memory_node", "target_id": b,
        "edge_type": "supports",
        "idempotency_key": key,
    })
    assert first.ok
    second = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "memory_node", "target_id": b,
        "edge_type": "supports",
        "idempotency_key": key,
    })
    assert second.ok
    assert second.data["id"] == first.data["id"]
    assert second.meta.idempotent_replay is True


def test_idempotent_conflict_on_different_payload(home):
    """Re-using a key with a different edge_type must surface
    IDEMPOTENCY_CONFLICT (persistence.md §5.2)."""

    a, b = _seed_two_nodes(home)
    key = "00000000-0000-4000-8000-replay-conflict"
    first = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "memory_node", "target_id": b,
        "edge_type": "supports",
        "idempotency_key": key,
    })
    assert first.ok
    second = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "memory_node", "target_id": b,
        "edge_type": "contradicts",   # different payload
        "idempotency_key": key,
    })
    assert second.ok is False
    assert second.error.code.value == "IDEMPOTENCY_CONFLICT"


# -- mixed-endpoint happy paths --------------------------------


def test_link_memory_node_to_decision(home):
    a, _b = _seed_two_nodes(home)
    dec = _seed_decision(home)
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "decision", "target_id": dec,
        "edge_type": "about",
        "idempotency_key": "00000000-0000-4000-8000-mem-2-dec01",
    })
    assert env.ok, env
    assert env.data["target_kind"] == "decision"


def test_link_returns_event_id_on_meta(home):
    """memory.link emits an `edge.created` event; meta.event_id surfaces
    the row id per contracts.md §3.2."""

    a, b = _seed_two_nodes(home)
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "memory_node", "target_id": b,
        "edge_type": "follows",
        "idempotency_key": "00000000-0000-4000-8000-event-id001",
    })
    assert env.ok
    assert isinstance(env.meta.event_id, int) and env.meta.event_id > 0
