"""Local-only execution-quality diagnostics over imported receipt evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from trade_trace.timestamps import (
    parse_report_timestamp_lenient_utc_naive_as_utc as _dt,
)
from trade_trace.tools._helpers import db_for_args

DEFAULT_MIN_SAMPLE = 5
DEFAULT_STALE_SNAPSHOT_MINUTES = 15
DEFAULT_STALE_OPEN_MINUTES = 60
_OPEN_STATES = {"submitted", "accepted", "cancel_requested"}
_REJECT_STATES = {"rejected", "failed", "mismatch"}
_CANCEL_FAILURE_STATES = {"failed", "mismatch"}


def _loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value




def _iso_now(args: dict[str, Any]) -> datetime:
    return _dt(str(args.get("as_of"))) or datetime.now(UTC)


def _num(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _side(intent_shape: dict[str, Any], facts: dict[str, Any]) -> str | None:
    value = _first(intent_shape, ("side", "action", "direction")) or _first(facts, ("side", "action", "direction"))
    if value is None:
        return None
    text = str(value).lower()
    if text in {"buy", "yes", "long", "bid"}:
        return "buy"
    if text in {"sell", "no", "short", "ask"}:
        return "sell"
    return text


def _reference(snapshot: dict[str, Any]) -> tuple[str | None, float | None]:
    for key in ("mid", "price", "implied_probability", "ask", "bid"):
        value = _num(snapshot.get(key))
        if value is not None:
            return key, value
    return None, None


def _caveat(codes: list[str], code: str) -> None:
    if code not in codes:
        codes.append(code)


def _range(values: list[str | None]) -> dict[str, str | None]:
    present = sorted(value for value in values if value)
    return {"min": present[0] if present else None, "max": present[-1] if present else None}


def _find_snapshot(conn: Any, intent: dict[str, Any]) -> dict[str, Any] | None:
    row = None
    if intent.get("snapshot_id"):
        row = conn.execute(
            "SELECT id, captured_at, source, price, bid, ask, mid, spread, implied_probability FROM snapshots WHERE id = ?",
            (intent["snapshot_id"],),
        ).fetchone()
    if row is None and intent.get("instrument_id") and intent.get("as_of"):
        row = conn.execute(
            "SELECT id, captured_at, source, price, bid, ask, mid, spread, implied_probability FROM snapshots WHERE instrument_id = ? AND captured_at <= ? ORDER BY captured_at DESC, id DESC LIMIT 1",
            (intent["instrument_id"], intent["as_of"]),
        ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "captured_at": row[1], "source": row[2], "price": row[3], "bid": row[4], "ask": row[5], "mid": row[6], "spread": row[7], "implied_probability": row[8]}


def report_execution_quality(args: dict[str, Any]) -> dict[str, Any]:
    """Return read-only process diagnostics from local intents/snapshots/receipts."""
    limit = min(int(args.get("limit", 100)), 500)
    min_sample = int(args.get("min_sample", DEFAULT_MIN_SAMPLE))
    stale_snapshot_minutes = float(args.get("stale_snapshot_minutes", DEFAULT_STALE_SNAPSHOT_MINUTES))
    stale_open_minutes = float(args.get("stale_open_minutes", DEFAULT_STALE_OPEN_MINUTES))
    as_of_dt = _iso_now(args)

    where: list[str] = []
    params: list[Any] = []
    for field in ("pretrade_intent_id", "market_id", "instrument_id", "lifecycle_state"):
        if args.get(field):
            where.append(f"r.{field} = ?")
            params.append(args[field])
    sql = """
        SELECT r.id, r.lifecycle_state, r.external_event_type, r.pretrade_intent_id, r.market_id, r.instrument_id,
               r.external_order_ref, r.external_fill_ref, r.source_system, r.source_run_id, r.retrieved_at, r.as_of,
               r.imported_at, r.sanitized_facts_json, r.caveats_json, r.provenance_json,
               i.id, i.snapshot_id, i.as_of, i.proposed_shape_json
          FROM external_execution_receipts r
          LEFT JOIN pretrade_intents i ON i.id = r.pretrade_intent_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.as_of DESC, r.id DESC LIMIT ?"

    with db_for_args(args) as db:
        records = db.connection.execute(sql, (*params, limit)).fetchall()
        rows: list[dict[str, Any]] = []
        all_codes: set[str] = set()
        snapshot_staleness_values: list[float] = []
        receipt_source_systems: set[str] = set()
        receipt_source_run_ids: set[str] = set()
        retrieved_at_values: list[str | None] = []
        imported_at_values: list[str | None] = []
        counts = {"partial_fill": 0, "rejected": 0, "cancel_failure": 0, "stale_open": 0, "improved": 0, "adverse": 0, "slippage_available": 0}
        for r in records:
            if r[8]:
                receipt_source_systems.add(str(r[8]))
            if r[9]:
                receipt_source_run_ids.add(str(r[9]))
            retrieved_at_values.append(r[10])
            imported_at_values.append(r[12])
            facts = _loads(r[13], {})
            receipt_caveats = _loads(r[14], [])
            provenance = _loads(r[15], {})
            intent = {"id": r[16], "snapshot_id": r[17], "as_of": r[18], "proposed_shape": _loads(r[19], {}), "instrument_id": r[5]}
            snapshot = _find_snapshot(db.connection, intent) if intent["id"] else None
            codes: list[str] = []
            if not intent["id"]:
                _caveat(codes, "MISSING_INTENT")
            if snapshot is None:
                _caveat(codes, "MISSING_SNAPSHOT")
                _caveat(codes, "SLIPPAGE_UNAVAILABLE")
            lifecycle = str(r[1])
            side = _side(intent["proposed_shape"], facts)
            fill_price = _num(_first(facts, ("fill_price", "average_fill_price", "avg_fill_price", "execution_price", "price")))
            filled_qty = _num(_first(facts, ("filled_quantity", "filled_qty", "fill_quantity", "quantity_filled")))
            order_qty = _num(_first(facts, ("order_quantity", "requested_quantity", "submitted_quantity", "quantity")), _first(intent["proposed_shape"], ("quantity", "size", "order_quantity")))
            if lifecycle == "partial_fill" or (filled_qty is not None and order_qty is not None and filled_qty < order_qty):
                _caveat(codes, "PARTIAL_FILL")
                counts["partial_fill"] += 1
            if lifecycle in _REJECT_STATES:
                _caveat(codes, "REJECTED_RECEIPT")
                counts["rejected"] += 1
            if r[2] == "cancel" and lifecycle in _CANCEL_FAILURE_STATES:
                _caveat(codes, "CANCEL_FAILURE_IMPORTED_EVIDENCE")
                counts["cancel_failure"] += 1
            receipt_dt = _dt(r[11])
            intent_dt = _dt(intent["as_of"])
            latency_seconds = (receipt_dt - intent_dt).total_seconds() if receipt_dt and intent_dt else None
            age_minutes = (as_of_dt - receipt_dt).total_seconds() / 60 if receipt_dt else None
            if lifecycle in _OPEN_STATES and age_minutes is not None and age_minutes > stale_open_minutes:
                _caveat(codes, "STALE_OPEN_RECEIPT_IMPORTED_EVIDENCE")
                counts["stale_open"] += 1
            snapshot_staleness_minutes = None
            ref_type = None
            ref_value = None
            slippage = None
            slippage_bps = None
            if snapshot is not None:
                snap_dt = _dt(snapshot["captured_at"])
                if intent_dt and snap_dt:
                    snapshot_staleness_minutes = (intent_dt - snap_dt).total_seconds() / 60
                    snapshot_staleness_values.append(snapshot_staleness_minutes)
                    if snapshot_staleness_minutes > stale_snapshot_minutes:
                        _caveat(codes, "STALE_PRETRADE_SNAPSHOT")
                ref_type, ref_value = _reference(snapshot)
                if fill_price is not None and ref_value is not None:
                    signed = fill_price - ref_value if side != "sell" else ref_value - fill_price
                    slippage = signed
                    slippage_bps = (signed / ref_value * 10000) if ref_value else None
                    counts["slippage_available"] += 1
                    if signed > 0:
                        _caveat(codes, "ADVERSE_FILL_VS_SNAPSHOT")
                        counts["adverse"] += 1
                    elif signed < 0:
                        _caveat(codes, "IMPROVED_FILL_VS_SNAPSHOT")
                        counts["improved"] += 1
                else:
                    _caveat(codes, "SLIPPAGE_UNAVAILABLE")
                if side == "buy" and fill_price is not None and _num(snapshot.get("ask")) is not None and fill_price >= float(snapshot["ask"]):
                    _caveat(codes, "SPREAD_CROSSED")
                if side == "sell" and fill_price is not None and _num(snapshot.get("bid")) is not None and fill_price <= float(snapshot["bid"]):
                    _caveat(codes, "SPREAD_CROSSED")
            if len(records) < min_sample:
                _caveat(codes, "SPARSE_SAMPLE")
            all_codes.update(codes)
            rows.append({
                "receipt_id": r[0], "pretrade_intent_id": r[3], "snapshot_id": snapshot["id"] if snapshot else None,
                "market_id": r[4], "instrument_id": r[5], "lifecycle_state": lifecycle, "external_event_type": r[2],
                "receipt_provenance": {"source_system": r[8], "source_run_id": r[9], "retrieved_at": r[10], "imported_at": r[12], "provenance": provenance},
                "contributing_ids": {"receipt_ids": [r[0]], "intent_ids": [r[3]] if r[3] else [], "snapshot_ids": [snapshot["id"]] if snapshot else [], "market_ids": [r[4]] if r[4] else []},
                "snapshot_staleness_minutes": snapshot_staleness_minutes, "latency_seconds": latency_seconds,
                "order_quantity": order_qty, "filled_quantity": filled_qty, "fill_price": fill_price,
                "snapshot_reference_type": ref_type, "snapshot_reference_value": ref_value, "slippage": slippage, "slippage_bps": slippage_bps,
                "receipt_caveats": receipt_caveats, "caveat_codes": codes,
            })
        if not rows:
            all_codes.add("MISSING_RECEIPT_INPUTS")
        retrieved_at_range = _range(retrieved_at_values)
        imported_at_range = _range(imported_at_values)
        summary = {
            "receipt_count": len(rows), "min_sample": min_sample, "sparse_sample": len(rows) < min_sample,
            "partial_fill_count": counts["partial_fill"], "rejected_count": counts["rejected"],
            "cancel_failure_count": counts["cancel_failure"], "stale_open_count": counts["stale_open"],
            "improved_fill_count": counts["improved"], "adverse_fill_count": counts["adverse"],
            "slippage_available_count": counts["slippage_available"], "caveat_codes": sorted(all_codes),
            "snapshot_staleness_summary": {
                "available_count": len(snapshot_staleness_values),
                "stale_count": sum(value > stale_snapshot_minutes for value in snapshot_staleness_values),
                "min_minutes": min(snapshot_staleness_values) if snapshot_staleness_values else None,
                "max_minutes": max(snapshot_staleness_values) if snapshot_staleness_values else None,
                "average_minutes": (sum(snapshot_staleness_values) / len(snapshot_staleness_values)) if snapshot_staleness_values else None,
            },
            "receipt_provenance_summary": {
                "source_systems": sorted(receipt_source_systems),
                "source_run_ids": sorted(receipt_source_run_ids),
                "retrieved_at_min": retrieved_at_range["min"],
                "retrieved_at_max": retrieved_at_range["max"],
                "imported_at_min": imported_at_range["min"],
                "imported_at_max": imported_at_range["max"],
            },
            "contributing_ids": {"receipt_ids": [row["receipt_id"] for row in rows], "intent_ids": sorted({x for row in rows for x in row["contributing_ids"]["intent_ids"]}), "snapshot_ids": sorted({x for row in rows for x in row["contributing_ids"]["snapshot_ids"]})},
        }
        return {"summary": summary, "rows": rows, "report_kind": "execution_quality_diagnostics", "non_executing": True, "local_evidence_only": True, "credential_blind": True, "advice_free": True, "truncated": len(records) == limit, "next_cursor": None}
