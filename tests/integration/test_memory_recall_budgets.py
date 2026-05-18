"""memory.recall budget / provenance knobs per bead trade-trace-5n4.

Five filterable budget surfaces: k, max_chars, compact, include_body,
include_provenance, min_confidence. Each test exercises one knob and
asserts the documented effect.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _mcp(home: Path, tool: str, args: dict | None = None):
    payload = {"home": str(home), **(args or {})}
    return mcp_call(tool, payload, actor_id="agent:default")


def _seed_n_nodes(home: Path, n: int, *, body_prefix: str = "obs",
                  confidence: float | None = None) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        args = {
            "node_type": "observation",
            "body": f"{body_prefix} #{i} — earnings volatility pattern",
            "idempotency_key": f"00000000-0000-4000-8000-budget-{i:08d}",
        }
        if confidence is not None:
            args["confidence_base"] = confidence
        ids.append(_mcp(home, "memory.retain", args).data["id"])
    return ids


# -- k --------------------------------------------------------------


def test_k_limits_returned_items(home):
    _seed_n_nodes(home, 5)
    env = _mcp(home, "memory.recall", {"query": "earnings", "k": 3})
    assert env.ok
    assert len(env.data["items"]) <= 3


def test_k_rejects_out_of_range(home):
    env = _mcp(home, "memory.recall", {"query": "x", "k": 0})
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


# -- max_chars + compact -------------------------------------------


def test_max_chars_truncates_response_aggregate(home):
    _seed_n_nodes(home, 5, body_prefix="this-is-a-fairly-long-body-fragment")
    env = _mcp(home, "memory.recall", {
        "query": "earnings", "k": 10, "max_chars": 50,
    })
    assert env.ok
    total = sum(len(it.get("body", "")) for it in env.data["items"])
    assert total <= 50


def test_compact_truncates_each_body(home):
    long_body = "X" * 500
    _mcp(home, "memory.retain", {
        "node_type": "observation", "body": long_body,
        "idempotency_key": "00000000-0000-4000-8000-compact-long",
    })
    env = _mcp(home, "memory.recall", {
        "query": "XX", "k": 1, "compact": True,
    })
    assert env.ok
    item = env.data["items"][0]
    assert len(item["body"]) <= 120


# -- include_body / include_provenance ----------------------------


def test_include_body_false_omits_body(home):
    _seed_n_nodes(home, 2)
    env = _mcp(home, "memory.recall", {
        "query": "earnings", "k": 2, "include_body": False,
    })
    assert env.ok
    for item in env.data["items"]:
        assert "body" not in item


def test_include_provenance_false_omits_strategy_provenance(home):
    _seed_n_nodes(home, 2)
    env = _mcp(home, "memory.recall", {
        "query": "earnings", "k": 2, "include_provenance": False,
    })
    assert env.ok
    for item in env.data["items"]:
        assert "strategy_provenance" not in item


# -- min_confidence -----------------------------------------------


def test_min_confidence_filters_below_threshold(home):
    high = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "high confidence observation",
        "confidence_base": 0.9,
        "idempotency_key": "00000000-0000-4000-8000-conf-high1",
    }).data["id"]
    low = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "low confidence observation",
        "confidence_base": 0.1,
        "idempotency_key": "00000000-0000-4000-8000-conf-low01",
    }).data["id"]
    env = _mcp(home, "memory.recall", {
        "query": "confidence observation", "k": 10, "min_confidence": 0.5,
    })
    assert env.ok
    ids = [it["id"] for it in env.data["items"]]
    assert high in ids
    assert low not in ids


def test_min_confidence_rejects_out_of_range(home):
    env = _mcp(home, "memory.recall", {
        "query": "x", "min_confidence": 1.5,
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
