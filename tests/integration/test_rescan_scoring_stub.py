"""`journal.rescan_scoring` deferred-but-introspectable contract per
trade-trace-7a8.

Scoring.md §4.3 / §7: when categorical/scalar scorers ship in P1, this
tool will re-score forecasts whose `scoring_support` flips from
`unsupported` to `supported`. MVP exposes the tool surface (and an
accurate `affected_rows` count) so an agent can introspect the future
migration cost without waiting for P1.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


def _envelope(home: Path, tool: str, args: dict):
    payload = {"home": str(home), **args}
    return mcp_call(tool, payload, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True
    )


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


def test_rescan_scoring_registered():
    """The tool name must be in the public registry so journal.schema and
    MCP listings expose it."""

    assert "journal.rescan_scoring" in default_registry().names()


def test_rescan_scoring_returns_unsupported_capability(home):
    env = _envelope(home, "journal.rescan_scoring", {})
    assert env["ok"] is False
    assert env["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    details = env["error"]["details"]
    assert details["reason"] == "implementation_deferred_p1"
    assert "affected_rows" in details
    assert isinstance(details["affected_rows"], int)


def test_rescan_scoring_affected_rows_zero_on_empty_db(home):
    """Fresh DB: no forecasts of any kind. affected_rows must be 0."""

    env = _envelope(home, "journal.rescan_scoring", {})
    assert env["error"]["details"]["affected_rows"] == 0


def test_rescan_scoring_affected_rows_counts_unsupported_pending(home):
    """affected_rows = COUNT(forecasts WHERE scoring_support='unsupported'
    AND scoring_state='pending'). Seed two unsupported pending and one
    supported pending forecast; only the two unsupported count."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    # Two unsupported pending — categorical kinds.
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"],
        "kind": "categorical",
        "outcomes": [
            {"outcome_label": "a", "probability": 0.5},
            {"outcome_label": "b", "probability": 0.5},
        ],
    })
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"],
        "kind": "categorical",
        "outcomes": [
            {"outcome_label": "x", "probability": 0.3},
            {"outcome_label": "y", "probability": 0.7},
        ],
    })
    # One supported pending — binary kind.
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"],
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })

    env = _envelope(home, "journal.rescan_scoring", {})
    assert env["error"]["details"]["affected_rows"] == 2


def test_rescan_scoring_schema_introspectable():
    """The tool description includes the P1-stub marker so journal.schema
    callers know what the surface promises (and doesn't)."""

    reg = default_registry().get("journal.rescan_scoring")
    assert "P1" in reg.description
    assert "rescore" in reg.description.lower() or "re-score" in reg.description.lower()
