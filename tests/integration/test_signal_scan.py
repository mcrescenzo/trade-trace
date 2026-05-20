"""Lazy signals emission via `signal.scan` per trade-trace-2ry.

Covers ux0 chunk 3 acceptance:
- Signals only appear after explicit scan/coach (lazy-only invariant).
- ≥3 tests including the lazy-only assertion (no daemon process exists
  in code).
- Signal row shape matches the schema enumerated in trade-trace-och.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


def _signal_count(home: Path) -> int:
    db = open_database(db_path(home))
    try:
        return db.connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    finally:
        db.close()


def _seed_unscored_forecast(home: Path) -> str:
    """Seed a forecast past its resolution_at with no resolved_final outcome.
    Returns the forecast_id."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"], "side": "yes", "body": "...",
    })
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"], "kind": "binary", "yes_label": "yes",
        # resolution_at in the past
        "resolution_at": "2026-04-01T00:00:00Z",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    return f["data"]["id"]


# -- registration ---------------------------------------------------------


def test_signal_scan_registered():
    assert "signal.scan" in default_registry().names()


# -- lazy-only invariant ------------------------------------------------


def test_signals_table_is_empty_before_any_scan(home):
    """Lazy invariant: no rows appear on journal init or on ledger writes."""

    _seed_unscored_forecast(home)
    # Add a decision too; the ledger flow shouldn't emit signals on its own.
    _envelope(home, "decision.add", {
        "instrument_id": "i_does_not_matter", "type": "skip", "reason": "x",
    })
    assert _signal_count(home) == 0


def test_signal_scan_appends_signals(home):
    _seed_unscored_forecast(home)
    res = _envelope(home, "signal.scan", {})
    assert res["ok"] is True
    assert res["data"]["emitted_count"] == 1
    assert _signal_count(home) == 1


def test_signal_scan_dedupe_default(home):
    """Re-running the scan on the same DB state is a no-op (the dedupe
    guard checks `related_refs_json` membership)."""

    _seed_unscored_forecast(home)
    _envelope(home, "signal.scan", {})
    second = _envelope(home, "signal.scan", {})
    assert second["data"]["emitted_count"] == 0
    assert _signal_count(home) == 1


def test_signal_scan_dedupe_survives_alternate_json_formatting(home):
    """Per bead trade-trace-c2h / DEBT-020: the dedupe guard must match
    structurally, not as a LIKE substring of the JSON blob.
    Previously a producer that wrote `related_refs_json` with extra
    whitespace, reordered keys, or unicode-escaped values would
    bypass the dedupe (the LIKE expected one specific compact
    formatting). The json_extract walk is formatting-agnostic.
    """

    forecast_id = _seed_unscored_forecast(home)

    # Pre-insert a signal row directly, formatted differently from
    # what _emit_signal produces (spaces in the JSON, keys reordered),
    # but with the same logical (forecast_id, instrument_id) refs.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO signals(id, kind, severity, body, related_refs_json, "
            "meta_json, created_at, actor_id) VALUES "
            "(?, 'unscored_forecast', 'warn', 'preseed body', ?, '{}', "
            "?, 'system:report.signal_scan')",
            (
                "sig_preseed",
                # Indented JSON with the same logical refs — historically
                # bypassed the LIKE pattern but must now hit the dedupe.
                '[ { "instrument_id": "preseed_i" }, '
                f'{{ "forecast_id": "{forecast_id}" }} ]',
                "2026-05-19T12:00:00Z",
            ),
        )
        db.connection.commit()
    finally:
        db.close()

    # First scan should now NOT emit (dedupe sees the preseed row).
    env = _envelope(home, "signal.scan", {})
    assert env["data"]["emitted_count"] == 0, (
        "dedupe missed an alternate-formatting preseed row; the "
        "LIKE pattern would have missed this, json_extract must not"
    )


def test_signal_scan_dedupe_off_forces_reemission(home):
    _seed_unscored_forecast(home)
    _envelope(home, "signal.scan", {})
    forced = _envelope(home, "signal.scan", {"dedupe": False})
    assert forced["data"]["emitted_count"] == 1
    assert _signal_count(home) == 2


# -- signal row shape ---------------------------------------------------


def test_signal_row_shape(home):
    fid = _seed_unscored_forecast(home)
    _envelope(home, "signal.scan", {})

    db = open_database(db_path(home))
    try:
        row = db.connection.execute(
            "SELECT id, kind, severity, body, meta_json, related_refs_json, "
            "created_at, actor_id FROM signals"
        ).fetchone()
    finally:
        db.close()
    assert row is not None
    sid, kind, severity, body, meta_json, refs_json, _created_at, actor_id = row
    assert sid.startswith("sig_")
    assert kind == "unscored_forecast"
    assert severity == "warn"
    assert fid in body
    assert actor_id == "system:report.coach"
    refs = json.loads(refs_json)
    assert {"forecast_id": fid} in refs


# -- input validation -------------------------------------------------


def test_signal_scan_rejects_unknown_kind(home):
    env = _envelope(home, "signal.scan", {"kinds": ["fully_made_up_kind"]})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_signal_scan_rejects_kinds_not_yet_scannable(home):
    """`calibration_drift` is in the open enum but the M2 scan doesn't yet
    know how to detect it — surfaces UNSUPPORTED_CAPABILITY so agents know
    the feature is partly shipped."""

    env = _envelope(home, "signal.scan", {"kinds": ["calibration_drift"]})
    assert env["ok"] is False
    assert env["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert "scannable_now" in env["error"]["details"]


# -- no daemon: positive grep gate -----------------------------------


def test_no_daemon_process_exists_in_code():
    """Lazy-only invariant per ux0 chunk 3: there is no background daemon.

    A positive grep gate: the source tree must contain no spawn of
    threading.Thread, multiprocessing.Process, asyncio.create_task, or
    a background polling loop. Test scopes the search to src/ (tests/
    legitimately exercise some of these via test harness)."""

    src = Path(__file__).resolve().parents[2] / "src" / "trade_trace"
    forbidden_markers = [
        "threading.Thread",
        "multiprocessing.Process",
        "asyncio.create_task",
        "subprocess.Popen",  # could be used for a watcher subprocess
    ]
    offenders: list[tuple[str, str]] = []
    for py in src.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for marker in forbidden_markers:
            if marker in text:
                offenders.append((str(py.relative_to(src)), marker))
    assert offenders == [], (
        f"Daemon-shaped primitives found in src/: {offenders}. "
        "Signals are emitted lazily by explicit tool calls only."
    )
