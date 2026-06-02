from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools.tracelab.substrate_invariants import (
    FAIL,
    LIMITATION,
    PASS,
    check_lock_recovery,
    check_quiesced_backup_restore,
    check_rebuild_positions,
    check_substrate_invariants,
)


def _write_trace(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n", encoding="utf-8")


def _seed_rebuildable_position(home: Path) -> None:
    db_path = home / "trade-trace.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO venues(id, name, kind, created_at, actor_id) VALUES (?, ?, ?, ?, ?)",
            ("venue-1", "Manual", "manual", "2026-01-01T00:00:00Z", "test"),
        )
        conn.execute(
            """
            INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("instrument-1", "venue-1", "Instrument", "other", "2026-01-01T00:00:00Z", "test"),
        )
        conn.execute(
            """
            INSERT INTO position_events(
                id, position_id, instrument_id, event_type, quantity_delta, price,
                fees, slippage, created_at, actor_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("pe-1", "position-1", "instrument-1", "open", 2.0, 10.0, 0.0, 0.0, "2026-01-01T00:00:01Z", "test"),
        )
        conn.execute(
            """
            INSERT INTO positions(
                id, instrument_id, kind, side, status, opened_at, closed_at,
                resolved_at, realized_pnl, unrealized_pnl, avg_entry_price,
                updated_at, initial_risk_amount, realized_r_multiple, unrealized_r_multiple
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "position-1",
                "instrument-1",
                "simulation",
                "long",
                "open",
                "2026-01-01T00:00:01Z",
                None,
                None,
                None,
                None,
                10.0,
                "2026-01-01T00:00:01Z",
                None,
                None,
                None,
            ),
        )
        conn.commit()


def test_lock_recovery_passes_paired_single_writer_retry(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    _write_trace(
        trace,
        [
            {"tool": "decision.add", "actor_id": "agent:a", "request_id": "r1", "ok": False, "attempt": 1, "error_code": "STORAGE_ERROR", "details": {"reason": "single_writer_lock"}},
            {"tool": "decision.add", "actor_id": "agent:a", "request_id": "r1", "ok": True, "attempt": 2, "retry_of": "r1"},
        ],
    )

    report = check_lock_recovery(trace)

    assert report["status"] == PASS
    assert report["evidence"]["paired_single_writer_locks"] == 1


def test_non_lock_storage_error_fails_invariant_2(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    _write_trace(
        trace,
        [{"tool": "decision.add", "actor_id": "agent:a", "request_id": "r1", "ok": False, "error_code": "STORAGE_ERROR", "details": {"reason": "disk_full"}}],
    )

    report = check_lock_recovery(trace)

    assert report["status"] == FAIL
    assert report["evidence"]["non_lock_storage_errors"] == [{"request_id": "r1", "tool": "decision.add", "reason": "disk_full"}]


def test_unpaired_keyless_single_writer_lock_is_limitation_not_fail(tmp_path: Path):
    trace = tmp_path / "trace.jsonl"
    _write_trace(trace, [{"tool": "decision.add", "actor_id": "agent:a", "ok": False, "error_code": "STORAGE_ERROR", "details": {"reason": "single_writer_lock"}}])

    report = check_lock_recovery(trace)

    assert report["status"] == LIMITATION
    assert report["evidence"]["keyless_lock_limitations"] == 1


def test_rebuild_positions_passes_when_projection_is_unchanged(initialized_home: Path):
    _seed_rebuildable_position(initialized_home)

    report = check_rebuild_positions(initialized_home / "trade-trace.sqlite")

    assert report["status"] == PASS
    assert report["evidence"]["diff"] == {"before_only": [], "after_only": []}


def test_rebuild_positions_fails_with_diff_when_projection_is_corrupt(initialized_home: Path):
    _seed_rebuildable_position(initialized_home)
    with sqlite3.connect(initialized_home / "trade-trace.sqlite") as conn:
        conn.execute("UPDATE positions SET status = 'closed' WHERE id = 'position-1'")
        conn.commit()

    report = check_rebuild_positions(initialized_home / "trade-trace.sqlite")

    assert report["status"] == FAIL
    assert len(report["evidence"]["diff"]["before_only"]) == 1
    assert len(report["evidence"]["diff"]["after_only"]) == 1


def test_quiesced_backup_restore_invariant_passes_for_temp_db(initialized_home: Path, tmp_path: Path):
    report = check_quiesced_backup_restore(
        home=initialized_home,
        run_db_path=initialized_home / "trade-trace.sqlite",
        backup_dest_root=tmp_path / "backups",
        quiescence_window="test-quiesced-window",
    )

    assert report["status"] == PASS
    assert report["evidence"]["original_sha256"] == report["evidence"]["restored_sha256"]


def test_clean_synthetic_run_passes_all_invariants(initialized_home: Path, tmp_path: Path):
    _seed_rebuildable_position(initialized_home)
    trace = tmp_path / "trace.jsonl"
    _write_trace(
        trace,
        [
            {"tool": "decision.add", "actor_id": "agent:a", "request_id": "r1", "ok": False, "attempt": 1, "error_code": "STORAGE_ERROR", "details": {"reason": "single_writer_lock"}},
            {"tool": "decision.add", "actor_id": "agent:a", "request_id": "r1", "ok": True, "attempt": 2, "retry_of": "r1"},
        ],
    )

    report = check_substrate_invariants(
        run_db_path=initialized_home / "trade-trace.sqlite",
        home=initialized_home,
        dispatch_trace_path=trace,
        backup_dest_root=tmp_path / "backups",
        quiescence_window="clean-run-window",
    )

    assert report["overall_status"] == PASS
    assert report["throughput_scored"] is False
    assert [item["status"] for item in report["invariants"]] == [PASS, PASS, PASS]
