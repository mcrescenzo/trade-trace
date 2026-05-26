from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.contracts.envelope import SuccessEnvelope


def _ok(home: Path, tool: str, args: dict[str, object]) -> dict[str, Any]:
    env = _mcp(home, tool, args)
    assert isinstance(env, SuccessEnvelope), env
    return cast(dict[str, Any], env.data)


def _bind_market(home: Path, suffix: str, title: str) -> dict[str, Any]:
    return _ok(home, "market.bind", {
        "source": "polymarket",
        "external_id": f"pm-backup-restore-{suffix}",
        "title": title,
        "question": title,
        "url": f"https://polymarket.example/market/{suffix}",
        "state": "open",
        "mechanism": "clob",
        "bound_via": "manual",
        "metadata": {"condition_id": f"0x{suffix:0>8}", "tokens": ["YES", "NO"]},
        "idempotency_key": f"00000000-0000-4000-8000-fffm-bind-{suffix}",
    })


def _add_pm_arc(home: Path, suffix: str, title: str, probability: float, quantity: float) -> dict[str, dict[str, Any]]:
    market = _bind_market(home, suffix, title)
    instrument_id = str(market["instrument_id"])
    market_id = str(market["market_id"])

    snapshot = _ok(home, "snapshot.add", {
        "instrument_id": instrument_id,
        "captured_at": "2026-05-18T14:00:00Z",
        "implied_probability": probability,
        "bid": probability - 0.01,
        "ask": probability + 0.01,
        "spread": 0.02,
        "volume": 1250.0,
        "liquidity": 5000.0,
        "idempotency_key": f"00000000-0000-4000-8000-fffm-snap-{suffix}",
    })
    forecast = _ok(home, "forecast.add", {
        "market_id": market_id,
        "rationale_body": f"Backup rehearsal forecast for {title}; deterministic PM-ish local fixture.",
        "kind": "binary",
        "yes_label": "YES",
        "outcomes": [
            {"outcome_label": "YES", "probability": probability},
            {"outcome_label": "NO", "probability": round(1.0 - probability, 2)},
        ],
        "idempotency_key": f"00000000-0000-4000-8000-fffm-fore-{suffix}",
    })
    source = _ok(home, "source.add", {
        "kind": "url",
        "stance": "supports",
        "uri": f"https://news.example/polymarket/{suffix}",
        "title": f"Source for {title}",
        "retrieved_at": "2026-05-18T13:45:00Z",
        "freshness_at": "2026-05-18T13:30:00Z",
        "idempotency_key": f"00000000-0000-4000-8000-fffm-src-{suffix}",
    })
    _ok(home, "source.attach_to_forecast", {
        "source_id": str(source["id"]),
        "target_id": str(forecast["id"]),
        "idempotency_key": f"00000000-0000-4000-8000-fffm-attf-{suffix}",
    })
    decision = _ok(home, "decision.add", {
        "type": "paper_enter",
        "instrument_id": instrument_id,
        "thesis_id": str(forecast["thesis_id"]),
        "forecast_id": str(forecast["id"]),
        "snapshot_id": str(snapshot["id"]),
        "side": "yes",
        "quantity": quantity,
        "price": probability,
        "fees": 0.0,
        "slippage": 0.0,
        "reason": "deterministic backup rehearsal paper position",
        "idempotency_key": f"00000000-0000-4000-8000-fffm-deci-{suffix}",
    })
    return {"market": market, "snapshot": snapshot, "forecast": forecast, "source": source, "decision": decision}


def _current_exposure_instrument_ids(home: Path) -> set[str]:
    report = _ok(home, "report.current_exposure", {"recent_limit": 20})
    rows = report.get("open_positions")
    assert isinstance(rows, list), report
    ids: set[str] = set()
    for row in rows:
        assert isinstance(row, dict), row
        instrument_id = row.get("instrument_id")
        if instrument_id is not None:
            ids.add(str(instrument_id))
    return ids


def test_backup_restore_rehearsal_rebuilds_projection_from_backup_state(tmp_path: Path) -> None:
    """Rollback rehearsal for a Phase 5 dogfood journal.

    Operator rollback procedure documented by this test:
    1. Stop writers against the live TRADE_TRACE_HOME before recovery.
    2. Run `journal.backup --dest <scratch> --confirm` from the last known-good
       journal, preserving the generated manifest with its SHA-256 hashes.
    3. If later writes make the live journal unsafe, provision a fresh
       TRADE_TRACE_HOME (do not restore over the suspect directory first).
    4. Run `journal.restore --src <scratch> --home <fresh-home> --confirm`.
    5. Start Trade Trace against the fresh home and run a read/projection report
       such as `report.current_exposure` to verify rebuilt projections reflect
       the backup-time state and exclude writes made after the backup.
    """

    live_home = tmp_path / "live"
    _ok(live_home, "journal.init", {})
    backup_arc = _add_pm_arc(
        live_home,
        suffix="001",
        title="Will deterministic backup rehearsal pass before mutation?",
        probability=0.62,
        quantity=3.0,
    )
    backed_up_instrument_id = str(backup_arc["market"]["instrument_id"])
    assert backed_up_instrument_id in _current_exposure_instrument_ids(live_home)

    backup_dest = tmp_path / "backup"
    backup = _ok(live_home, "journal.backup", {"dest": str(backup_dest), "_confirm": True})
    assert backup["preview_only"] is False

    mutated_arc = _add_pm_arc(
        live_home,
        suffix="002",
        title="Will post-backup mutation be absent after restore?",
        probability=0.48,
        quantity=7.0,
    )
    mutated_instrument_id = str(mutated_arc["market"]["instrument_id"])
    live_ids_after_mutation = _current_exposure_instrument_ids(live_home)
    assert {backed_up_instrument_id, mutated_instrument_id} <= live_ids_after_mutation

    restored_home = tmp_path / "restored"
    restore = _ok(restored_home, "journal.restore", {
        "src": str(backup_dest),
        "home": str(restored_home),
        "_confirm": True,
    })
    assert restore["preview_only"] is False

    restored_ids = _current_exposure_instrument_ids(restored_home)
    assert backed_up_instrument_id in restored_ids
    assert mutated_instrument_id not in restored_ids
