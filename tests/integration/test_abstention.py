"""abstention.record/get/list + integrity coverage (trade-trace-4kec.8).

A first-class "considered and passed" record so calibration denominators are
not survivorship-biased. Append-only, idempotent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.reports.integrity import report_calibration_integrity
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _instrument(home: Path) -> str:
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})["data"]["id"]
    return _envelope(
        home,
        "instrument.add",
        {"venue_id": venue, "asset_class": "prediction_market", "title": "Will X?"},
    )["data"]["id"]


def _record(home: Path, inst: str, **extra):
    return mcp_call(
        "abstention.record",
        {
            "home": str(home),
            "instrument_id": inst,
            "reason": "spread too wide vs edge",
            "as_of": "2027-01-05T00:00:00Z",
            **extra,
        },
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)


def test_abstention_tools_registered_public():
    names = set(default_registry().public_names())
    assert {"abstention.record", "abstention.get", "abstention.list"}.issubset(names)


def test_record_and_read_abstention(home: Path):
    inst = _instrument(home)
    env = _record(home, inst, considered_probability=0.55)
    assert env["ok"], env
    data = env["data"]
    assert data["instrument_id"] == inst
    assert data["reason"] == "spread too wide vs edge"
    assert data["considered_probability"] == 0.55
    assert data["record_kind"] == "abstention"

    got = mcp_call("abstention.get", {"home": str(home), "id": data["id"]}).model_dump(mode="json", exclude_none=True)
    assert got["ok"]
    assert got["data"]["id"] == data["id"]


def test_abstention_list_filters_by_instrument(home: Path):
    inst_a = _instrument(home)
    inst_b = _instrument(home)
    _record(home, inst_a)
    _record(home, inst_b)
    listed = mcp_call(
        "abstention.list", {"home": str(home), "instrument_id": inst_a}
    ).model_dump(mode="json", exclude_none=True)
    assert listed["ok"]
    assert listed["data"]["count"] == 1
    assert listed["data"]["records"][0]["instrument_id"] == inst_a


def test_abstention_is_idempotent_on_key(home: Path):
    inst = _instrument(home)
    first = _record(home, inst, idempotency_key="k-1")
    second = _record(home, inst, idempotency_key="k-1")
    assert first["ok"] and second["ok"]
    assert first["data"]["id"] == second["data"]["id"]
    listed = mcp_call("abstention.list", {"home": str(home), "instrument_id": inst}).model_dump(mode="json", exclude_none=True)
    assert listed["data"]["count"] == 1


def test_abstention_is_append_only(home: Path):
    inst = _instrument(home)
    abst_id = _record(home, inst)["data"]["id"]
    import sqlite3

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(home))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute("UPDATE abstentions SET reason = 'x' WHERE id = ?", (abst_id,))
        with pytest.raises(sqlite3.IntegrityError):
            db.connection.execute("DELETE FROM abstentions WHERE id = ?", (abst_id,))
    finally:
        db.close()


def test_record_rejects_missing_instrument(home: Path):
    env = mcp_call(
        "abstention.record",
        {"home": str(home), "instrument_id": "inst_missing", "reason": "r", "as_of": "2027-01-05T00:00:00Z"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("bad", [-0.1, 1.5])
def test_record_rejects_out_of_range_probability(home: Path, bad):
    inst = _instrument(home)
    env = _record(home, inst, considered_probability=bad)
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_abstentions_surface_in_calibration_integrity(home: Path):
    inst = _instrument(home)
    _record(home, inst)
    _record(home, inst, idempotency_key="k-2")
    import sqlite3

    with sqlite3.connect(db_path(home)) as conn:
        integrity = report_calibration_integrity(conn)
    cov = integrity["diagnostics"]["abstention_coverage"]
    assert cov["count"] == 2
    # No committed forecasts, so abstentions are the entire considered set.
    assert cov["total"] == 2
    assert cov["abstention_share_pct"] == 100.0
