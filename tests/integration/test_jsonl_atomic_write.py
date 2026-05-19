"""Outbox JSONL atomic-write tests per trade-trace-pou."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from trade_trace.exporter import (
    FINAL_SUFFIX,
    RESERVED_TRANSPORT_KEYS,
    TMP_SUFFIX,
    cleanup_orphan_tmp_files,
    iter_jsonl_files,
    jsonl_path,
    strip_transport_keys,
    write_event_atomic,
)


def test_path_convention(tmp_path: Path):
    """Path is exactly $HOME/export/jsonl/YYYY/MM/DD/<event_type>-<id>.jsonl."""

    p = jsonl_path(tmp_path, "decision.created", 42, "2026-05-18T14:32:11.123Z")
    relative = p.relative_to(tmp_path)
    assert relative.parts == ("export", "jsonl", "2026", "05", "18", "decision.created-42.jsonl")


def test_atomic_write_creates_final_only(tmp_path: Path):
    write_event_atomic(
        tmp_path,
        event_id=1,
        event_type="decision.created",
        actor_id="agent:default",
        created_at="2026-05-18T14:00:00Z",
        payload={"instrument_id": "i_1", "type": "skip"},
    )
    files = list((tmp_path / "export" / "jsonl").rglob("*"))
    # The .tmp should not survive a successful write.
    assert not any(p.name.endswith(TMP_SUFFIX) for p in files), files
    assert any(p.name.endswith(FINAL_SUFFIX) for p in files), files


def test_jsonl_line_carries_transport_metadata(tmp_path: Path):
    path = write_event_atomic(
        tmp_path,
        event_id=7,
        event_type="venue.created",
        actor_id="cli:user",
        created_at="2026-05-18T14:00:00Z",
        payload={"name": "Polymarket", "kind": "prediction_market"},
    )
    line = json.loads(path.read_text())
    for key in RESERVED_TRANSPORT_KEYS:
        assert key in line
    assert line["_event_id"] == 7
    assert line["_event_type"] == "venue.created"
    assert line["_contract_version"] == "1.0"
    # Importer envelope: tool + args. venue.created → venue.add (per the
    # static event→tool map; see resolve_tool_for_event).
    assert line["tool"] == "venue.add"
    assert line["args"]["name"] == "Polymarket"
    assert line["args"]["kind"] == "prediction_market"


def test_orphan_tmp_cleanup_old(tmp_path: Path):
    """Files older than the cutoff are removed; recent files survive."""

    base = tmp_path / "export" / "jsonl" / "2026" / "05" / "18"
    base.mkdir(parents=True)
    orphan = base / "decision.created-1.jsonl.tmp"
    fresh = base / "decision.created-2.jsonl.tmp"
    orphan.write_text("{}")
    fresh.write_text("{}")
    # Backdate the orphan two hours.
    old = time.time() - 2 * 3600
    os.utime(orphan, (old, old))
    removed = cleanup_orphan_tmp_files(tmp_path, older_than_seconds=3600)
    assert orphan in removed
    assert not orphan.exists()
    assert fresh.exists()


def test_iter_jsonl_files_skips_tmp(tmp_path: Path):
    """The importer's discovery walk must ignore `.jsonl.tmp` files."""

    base = tmp_path / "export" / "jsonl" / "2026" / "05" / "18"
    base.mkdir(parents=True)
    good = base / "decision.created-1.jsonl"
    bad = base / "decision.created-2.jsonl.tmp"
    good.write_text('{"a":1}')
    bad.write_text('{"a":2}')
    files = iter_jsonl_files(tmp_path)
    assert good in files
    assert bad not in files


def test_strip_transport_keys_round_trip():
    """Underscore-prefixed keys are stripped on import; domain keys preserved."""

    payload = {
        "name": "Polymarket",
        "kind": "prediction_market",
        "_event_id": 42,
        "_event_type": "venue.created",
        "_actor_id": "cli:user",
        "_created_at": "2026-05-18T14:00:00Z",
        "_contract_version": "1.0",
    }
    stripped = strip_transport_keys(payload)
    assert stripped == {"name": "Polymarket", "kind": "prediction_market"}


def test_atomic_write_deterministic_canonical_form(tmp_path: Path):
    """The JSONL line uses sort_keys=True so re-export is byte-identical."""

    path = write_event_atomic(
        tmp_path,
        event_id=99,
        event_type="venue.created",
        actor_id="agent:default",
        created_at="2026-05-18T14:00:00Z",
        payload={"kind": "manual", "name": "X"},
    )
    line = path.read_text()
    decoded = json.loads(line)
    # Top-level keys sorted: _actor_id, _contract_version, ..., args, tool.
    assert list(decoded.keys()) == sorted(decoded.keys())
    # `args` is itself sorted, so re-export is byte-identical regardless of
    # the caller's insertion order.
    assert list(decoded["args"].keys()) == sorted(decoded["args"].keys())


def test_reserved_transport_keys_documented():
    """The reserved set is the canonical 5 per operability.md §9.2."""

    assert RESERVED_TRANSPORT_KEYS == frozenset(
        {"_event_id", "_event_type", "_actor_id", "_created_at", "_contract_version"}
    )


def test_two_events_same_day_distinct_files(tmp_path: Path):
    write_event_atomic(
        tmp_path,
        event_id=1,
        event_type="decision.created",
        actor_id="agent:default",
        created_at="2026-05-18T14:00:00Z",
        payload={"a": 1},
    )
    write_event_atomic(
        tmp_path,
        event_id=2,
        event_type="decision.created",
        actor_id="agent:default",
        created_at="2026-05-18T14:01:00Z",
        payload={"a": 2},
    )
    files = iter_jsonl_files(tmp_path)
    assert len(files) == 2
    assert {p.name for p in files} == {"decision.created-1.jsonl", "decision.created-2.jsonl"}
