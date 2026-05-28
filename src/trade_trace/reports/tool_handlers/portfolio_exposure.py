"""Family-oriented report tool handlers.

Mechanical extraction from trade_trace.tools.reports; keep behavior stable.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from .common import (
    UTC,
    Any,
    ErrorCode,
    ToolContext,
    ToolError,
    UnsupportedFilterError,
    ValidationError,
    _latest_snapshot_mark_by_instrument,
    _open_position_hints,
    _parse_report_timestamp,
    _position_row_payload,
    _propagate_report_meta,
    _unsupported_filter_to_tool_error,
    datetime,
    open_db_for_args,
    report_filter_validation_to_tool_error,
    report_watchlist,
    timedelta,
    to_utc_iso8601,
)


def _report_watchlist(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.watchlist` — list open watch decisions. `mode='stale'` opts in
    to the stale subset; `stale_threshold_days` overrides the default 14."""

    raw_filter = args.get("filter")
    mode = args.get("mode", "all")
    if mode not in ("all", "stale"):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"mode must be 'all' or 'stale'; got {mode!r}",
            details={"field": "mode", "value": mode, "allowed": ["all", "stale"]},
        )
    stale_threshold_days = args.get("stale_threshold_days", 14)
    db = open_db_for_args(args)
    try:
        try:
            data = report_watchlist(
                db.connection, raw_filter=raw_filter,
                stale=(mode == "stale"),
                stale_threshold_days=stale_threshold_days,
            )
        except ValidationError as exc:
            raise report_filter_validation_to_tool_error(exc) from exc
        except UnsupportedFilterError as exc:
            raise _unsupported_filter_to_tool_error(exc) from exc
    finally:
        db.close()
    _propagate_report_meta(ctx, data)
    return data


def _exposure_temporal_bounds(args: dict[str, Any]) -> tuple[datetime, int, datetime]:
    stale_mark_threshold_days = args.get("stale_mark_threshold_days", 14)
    if not isinstance(stale_mark_threshold_days, int) or stale_mark_threshold_days < 0:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "stale_mark_threshold_days must be a non-negative integer",
            details={"field": "stale_mark_threshold_days", "value": stale_mark_threshold_days},
        )
    as_of_raw = args.get("as_of")
    if as_of_raw is None:
        as_of = datetime.now(UTC)
    elif isinstance(as_of_raw, str):
        as_of = _parse_report_timestamp(as_of_raw, field="as_of")
    else:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "as_of must be an ISO timestamp string",
            details={"field": "as_of", "value": as_of_raw},
        )
    stale_cutoff = as_of - timedelta(days=stale_mark_threshold_days)
    return as_of, stale_mark_threshold_days, stale_cutoff


def _safe_json(text: Any) -> dict[str, Any]:
    if not text:
        return {}
    if isinstance(text, dict):
        return text
    try:
        parsed = json.loads(str(text))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _market_metadata_by_instrument(connection: Any, instrument_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not instrument_ids:
        return {}
    placeholders = ", ".join("?" for _ in instrument_ids)
    rows = connection.execute(
        f"""
        SELECT id, source, external_id, title, metadata_json
        FROM markets
        WHERE id IN ({placeholders})
        """,
        tuple(instrument_ids),
    ).fetchall()
    return {
        row[0]: {"market_id": row[0], "source": row[1], "external_id": row[2], "title": row[3], "metadata": _safe_json(row[4])}
        for row in rows
    }


def _event_key_from_metadata(instrument_id: str, metadata: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    grouping = metadata.get("event_grouping") or {}
    identity = metadata.get("polymarket_identity") or {}
    negative_risk = metadata.get("negative_risk") or {}
    event_id = grouping.get("event_id") or identity.get("gamma_event_id")
    event_slug = grouping.get("event_slug") or identity.get("event_slug")
    return str(event_id or event_slug or f"ungrouped:{instrument_id}"), grouping, identity, negative_risk


def _outcome_label(position: dict[str, Any], identity: dict[str, Any], info: dict[str, Any] | None) -> str:
    labels = identity.get("outcome_token_ids_by_label")
    if isinstance(labels, dict) and len(labels) == 1:
        return str(next(iter(labels.keys())))
    title = (info or {}).get("title")
    if title:
        return str(title)
    return str(position.get("instrument_id"))


def _side_sign(side: Any) -> Decimal:
    normalized = str(side or "").strip().lower()
    return Decimal("-1") if normalized in {"no", "short", "sell"} else Decimal("1")


def _event_exposure_sets(connection: Any, open_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    market_info = _market_metadata_by_instrument(connection, {p["instrument_id"] for p in open_positions})
    grouped: dict[str, dict[str, Any]] = {}
    outcome_buckets: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for position in open_positions:
        info = market_info.get(position["instrument_id"])
        metadata = (info or {}).get("metadata") or {}
        event_key, grouping, identity, negative_risk = _event_key_from_metadata(position["instrument_id"], metadata)
        event = grouped.setdefault(
            event_key,
            {
                "event_key": event_key,
                "event_id": grouping.get("event_id") or identity.get("gamma_event_id"),
                "event_slug": grouping.get("event_slug") or identity.get("event_slug"),
                "event_title": grouping.get("event_title"),
                "mutually_exclusive": bool(grouping.get("mutually_exclusive") or grouping.get("mutually_exclusive_outcomes")),
                "source_precedence": ["local_projected_positions", "imported_account_snapshots_reference_only", "paper_fill_records_reference_only", "market_metadata"],
                "truth_label": "local_projection_only_not_imported_account_truth",
                "market_count": 0,
                "markets": [],
                "contributing_record_ids": {"positions": [], "decisions": [], "snapshots": [], "account_snapshots": [], "paper_fills": []},
                "market_level_net_exposure": [],
                "outcome_side_buckets": [],
                "event_level_directional_summary": {
                    "raw_market_gross_quantity": 0.0,
                    "directional_net_quantity": 0.0,
                    "total_initial_risk_amount": 0.0,
                    "conservative_event_risk_amount": 0.0,
                    "unrealized_pnl": 0.0,
                    "metric_caveat": "Local projection from position rows; no broker/account reconciliation, redemption, settlement, or negative-risk equivalence conversion is performed.",
                    "unconverted_negative_risk_caveated": False,
                    "mutually_exclusive_netting_caveated": bool(grouping.get("mutually_exclusive") or grouping.get("mutually_exclusive_outcomes")),
                },
                "negative_risk": {"flagged": bool(negative_risk), "metadata": negative_risk, "caveats": []},
                "caveat_codes": [],
            },
        )
        if negative_risk and "NEGATIVE_RISK_EQUIVALENCE_UNCONVERTED" not in event["caveat_codes"]:
            event["caveat_codes"].append("NEGATIVE_RISK_EQUIVALENCE_UNCONVERTED")
            event["negative_risk"]["caveats"].append("Negative-risk metadata is provenance/caveat context only; no conversion, equivalence transform, redemption, settlement, or fund movement is performed.")
            event["event_level_directional_summary"]["unconverted_negative_risk_caveated"] = True
        if info is None and "MISSING_EVENT_METADATA" not in event["caveat_codes"]:
            event["caveat_codes"].append("MISSING_EVENT_METADATA")
        if position.get("mark_state") in {"missing", "stale"}:
            code = "MISSING_MARK" if position.get("mark_state") == "missing" else "STALE_MARK"
            if code not in event["caveat_codes"]:
                event["caveat_codes"].append(code)
        if event["mutually_exclusive"] and "MUTUALLY_EXCLUSIVE_EVENT_CONCENTRATION_UNCONVERTED" not in event["caveat_codes"]:
            event["caveat_codes"].append("MUTUALLY_EXCLUSIVE_EVENT_CONCENTRATION_UNCONVERTED")
        qty = _dec(position.get("net_quantity"))
        signed_qty = qty * _side_sign(position.get("side"))
        initial_risk = _dec(position.get("initial_risk_amount"))
        unrealized_pnl = _dec(position.get("unrealized_pnl"))
        rollup = event["event_level_directional_summary"]
        rollup["raw_market_gross_quantity"] = float(_dec(rollup["raw_market_gross_quantity"]) + abs(qty))
        rollup["directional_net_quantity"] = float(_dec(rollup["directional_net_quantity"]) + signed_qty)
        rollup["total_initial_risk_amount"] = float(_dec(rollup["total_initial_risk_amount"]) + initial_risk)
        rollup["conservative_event_risk_amount"] = float(_dec(rollup["conservative_event_risk_amount"]) + initial_risk)
        rollup["unrealized_pnl"] = float(_dec(rollup["unrealized_pnl"]) + unrealized_pnl)
        event["market_count"] += 1
        event["markets"].append(position["instrument_id"])
        event["contributing_record_ids"]["positions"].append(position["position_id"])
        if position.get("opening_decision_id"):
            event["contributing_record_ids"]["decisions"].append(position["opening_decision_id"])
        latest_mark = position.get("latest_mark") or {}
        if latest_mark.get("snapshot_id"):
            event["contributing_record_ids"]["snapshots"].append(latest_mark["snapshot_id"])
        outcome = _outcome_label(position, identity, info)
        side = str(position.get("side") or "unknown")
        bucket = outcome_buckets.setdefault(event_key, {}).setdefault(
            (outcome, side),
            {"outcome_label": outcome, "side": side, "signed_projected_quantity": 0.0, "raw_market_gross_quantity": 0.0, "initial_risk_amount": 0.0, "unrealized_pnl": 0.0, "contributing_record_ids": {"positions": [], "decisions": [], "markets": []}},
        )
        bucket["signed_projected_quantity"] = float(_dec(bucket["signed_projected_quantity"]) + signed_qty)
        bucket["raw_market_gross_quantity"] = float(_dec(bucket["raw_market_gross_quantity"]) + abs(qty))
        bucket["initial_risk_amount"] = float(_dec(bucket["initial_risk_amount"]) + initial_risk)
        bucket["unrealized_pnl"] = float(_dec(bucket["unrealized_pnl"]) + unrealized_pnl)
        bucket["contributing_record_ids"]["positions"].append(position["position_id"])
        bucket["contributing_record_ids"]["markets"].append(position["instrument_id"])
        if position.get("opening_decision_id"):
            bucket["contributing_record_ids"]["decisions"].append(position["opening_decision_id"])
        event["market_level_net_exposure"].append({
            "instrument_id": position["instrument_id"],
            "position_id": position["position_id"],
            "public_market_identity": {"source": (info or {}).get("source"), "external_id": (info or {}).get("external_id"), "title": (info or {}).get("title"), "polymarket_identity": identity},
            "outcome_label": outcome,
            "side": side,
            "net_quantity": float(qty),
            "signed_projected_quantity": float(signed_qty),
            "unrealized_pnl": position.get("unrealized_pnl"),
            "initial_risk_amount": position.get("initial_risk_amount"),
            "mark_state": position.get("mark_state"),
            "source_label": "local_projected_position",
        })
    for event_key, event in grouped.items():
        event["outcome_side_buckets"] = list(outcome_buckets.get(event_key, {}).values())
    return list(grouped.values())


def _report_open_positions(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.open_positions` — row-level current open exposure."""

    limit = args.get("limit")
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "limit must be a positive integer",
            details={"field": "limit", "value": limit},
        )
    kind = args.get("kind")
    if kind is not None and kind not in ("paper", "actual", "simulation"):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "kind must be one of: paper, actual, simulation",
            details={"field": "kind", "value": kind, "allowed": ["paper", "actual", "simulation"]},
        )
    as_of, stale_mark_threshold_days, stale_cutoff = _exposure_temporal_bounds(args)
    db = open_db_for_args(args)
    try:
        from trade_trace.reporting.position_rows import list_positions

        page = list_positions(
            db.connection,
            cursor=args.get("cursor"),
            limit=limit if limit is not None else 100,
            status=("open", "partial"),
            kind=kind,
            instrument_id=args.get("instrument_id"),
            strategy_id=args.get("strategy_id"),
        )
        latest_marks = _latest_snapshot_mark_by_instrument(
            db.connection,
            {row.instrument_id for row in page.rows},
        )
        connection = db.connection
        rows = [
            _position_row_payload(
                row,
                latest_marks.get(row.instrument_id),
                stale_cutoff=stale_cutoff,
            )
            for row in page.rows
        ]
        event_exposure_sets = _event_exposure_sets(connection, rows)
    finally:
        db.close()

    caveat_codes = sorted({code for row in rows for code in row["caveat_codes"]})
    if not rows:
        caveat_codes = ["NO_OPEN_POSITIONS"]
    hints = _open_position_hints(len(rows), caveat_codes)
    data = {
        "summary": {
            "bucket": "open_positions",
            "count": len(rows),
            "open_position_count": len(rows),
            "filter": {
                "status": ["open", "partial"],
                "kind": kind,
                "instrument_id": args.get("instrument_id"),
                "strategy_id": args.get("strategy_id"),
                "limit": page.limit,
                "cursor": args.get("cursor"),
                "stale_mark_threshold_days": stale_mark_threshold_days,
                "as_of": to_utc_iso8601(as_of),
            },
            "caveat_codes": caveat_codes,
            "agent_answer_hints": hints,
        },
        "groups": event_exposure_sets,
        "event_exposure_sets": event_exposure_sets,
        "open_positions": rows,
        "agent_answer_hints": hints,
        "truncated": page.next_cursor is not None,
        "next_cursor": page.next_cursor,
    }
    _propagate_report_meta(ctx, data)
    return data


_RECORD_ONLY_TERMS = (
    "record-only",
    "record only",
    "not external",
    "not externally executed",
    "journal-only",
    "journal only",
    "manual record",
    "dogfood",
    "simulated",
)


def _exposure_anomaly(code: str, summary: str, affected_ids: dict[str, list[str]], evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "category": "data_quality",
        "severity": "warning",
        "summary": summary,
        "affected_ids": affected_ids,
        "evidence": evidence,
    }


def _report_exposure_anomalies(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.exposure_anomalies` — current-exposure ambiguity caveats."""

    as_of, stale_mark_threshold_days, stale_cutoff = _exposure_temporal_bounds(args)
    anomalies: list[dict[str, Any]] = []

    db = open_db_for_args(args)
    try:
        connection = db.connection
        decisions = connection.execute(
            """
            SELECT d.id, d.instrument_id, d.type, d.side, d.quantity, d.price,
                   d.run_id, d.reason, d.metadata_json, d.created_at,
                   COUNT(pe.id) AS event_count
            FROM decisions d
            LEFT JOIN position_events pe ON pe.decision_id = d.id
            WHERE d.type IN ('paper_enter','actual_enter','actual_exit','add','reduce')
            GROUP BY d.id
            ORDER BY d.created_at, d.id
            """
        ).fetchall()
        for row in decisions:
            payload = {
                "decision_id": row[0], "instrument_id": row[1], "type": row[2],
                "side": row[3], "quantity": row[4], "price": row[5],
                "run_id": row[6], "created_at": row[9], "linked_position_event_count": row[10],
            }
            if row[2] in ("paper_enter", "actual_enter", "add") and row[10] == 0:
                anomalies.append(_exposure_anomaly(
                    "ENTRY_DECISION_WITHOUT_POSITION_EVENT",
                    "Entry decision lacks linked position_events row; do not count as exposure.",
                    {"decisions": [row[0]], "instruments": [row[1]]},
                    payload,
                ))
            if row[2] in ("actual_enter", "actual_exit", "add", "reduce") and row[10] == 0:
                text = f"{row[7] or ''} {row[8] or ''}".lower()
                matched = [term for term in _RECORD_ONLY_TERMS if term in text]
                evidence = {**payload, "record_only_phrase_matches": matched}
                anomalies.append(_exposure_anomaly(
                    "RECORD_ONLY_ACTUAL",
                    "Actual-recorded/add/reduce/exit decision has no linked position_event/projection lineage; treat as journal activity, not open exposure.",
                    {"decisions": [row[0]], "instruments": [row[1]]},
                    evidence,
                ))

        dupes = connection.execute(
            """
            SELECT instrument_id, type, COALESCE(side,''), COALESCE(quantity,''), COALESCE(price,''),
                   COALESCE(run_id,''), COUNT(*) AS n, GROUP_CONCAT(id), MIN(created_at), MAX(created_at)
            FROM decisions
            WHERE type IN ('paper_enter','actual_enter','add')
            GROUP BY instrument_id, type, COALESCE(side,''), COALESCE(quantity,''), COALESCE(price,''), COALESCE(run_id,'')
            HAVING COUNT(*) > 1
            ORDER BY MIN(created_at), instrument_id, type
            """
        ).fetchall()
        for row in dupes:
            decision_ids = row[7].split(",") if row[7] else []
            anomalies.append(_exposure_anomaly(
                "DUPLICATE_DECISIONS",
                "Duplicate entry-like journal decisions found; exposure should be based only on linked position projection/events.",
                {"decisions": decision_ids, "instruments": [row[0]]},
                {"instrument_id": row[0], "type": row[1], "side": row[2] or None,
                 "quantity": row[3] or None, "price": row[4] or None, "run_id": row[5] or None,
                 "count": row[6], "first_created_at": row[8], "last_created_at": row[9]},
            ))

        open_positions = connection.execute(
            """
            SELECT id, instrument_id, kind, side, status, unrealized_pnl, updated_at
            FROM positions
            WHERE status IN ('open','partial')
            ORDER BY updated_at, id
            """
        ).fetchall()
        latest_marks = _latest_snapshot_mark_by_instrument(connection, {row[1] for row in open_positions})
        for row in open_positions:
            mark = latest_marks.get(row[1])
            base = {"position_id": row[0], "instrument_id": row[1], "kind": row[2], "side": row[3], "status": row[4], "updated_at": row[6]}
            if row[5] is None and mark is None:
                anomalies.append(_exposure_anomaly(
                    "MISSING_MARK",
                    "Open/partial position has no unrealized P&L and no latest snapshot/mark.",
                    {"positions": [row[0]], "instruments": [row[1]]},
                    base,
                ))
            elif mark is not None:
                captured_at = _parse_report_timestamp(mark["captured_at"], field="snapshots.captured_at")
                if captured_at < stale_cutoff:
                    anomalies.append(_exposure_anomaly(
                        "STALE_MARK",
                        "Open/partial position latest snapshot/mark is stale as of the report threshold.",
                        {"positions": [row[0]], "instruments": [row[1]], "snapshots": [mark["snapshot_id"]]},
                        {**base, "latest_mark": mark},
                    ))

        stale_projection = connection.execute(
            """
            SELECT p.id, p.instrument_id, p.updated_at, MAX(pe.created_at) AS latest_event_at
            FROM positions p
            JOIN position_events pe ON pe.position_id = p.id
            GROUP BY p.id
            HAVING latest_event_at > p.updated_at
            ORDER BY latest_event_at, p.id
            """
        ).fetchall()
        for row in stale_projection:
            anomalies.append(_exposure_anomaly(
                "PROJECTION_STALE",
                "positions projection predates later position_events; rebuild/check projections before relying on exposure.",
                {"positions": [row[0]], "instruments": [row[1]]},
                {"position_id": row[0], "instrument_id": row[1], "position_updated_at": row[2], "latest_event_at": row[3]},
            ))

        missing_projection = connection.execute(
            """
            SELECT pe.position_id, pe.instrument_id, GROUP_CONCAT(pe.id), MIN(pe.created_at), MAX(pe.created_at)
            FROM position_events pe
            LEFT JOIN positions p ON p.id = pe.position_id
            WHERE p.id IS NULL
            GROUP BY pe.position_id, pe.instrument_id
            ORDER BY MIN(pe.created_at), pe.position_id
            """
        ).fetchall()
        for row in missing_projection:
            anomalies.append(_exposure_anomaly(
                "PROJECTION_MISSING",
                "position_events exist for a position_id with no readable positions projection row.",
                {"positions": [row[0]], "instruments": [row[1]], "position_events": row[2].split(",") if row[2] else []},
                {"position_id": row[0], "instrument_id": row[1], "first_event_at": row[3], "latest_event_at": row[4]},
            ))
    finally:
        db.close()

    codes = sorted({item["code"] for item in anomalies})
    if anomalies:
        hints = [
            "Projection/data-quality caveats found; do not infer open trades from decisions-only evidence.",
            "These anomalies are local journal/projection caveats, not market risk or broker truth.",
        ]
    else:
        hints = [
            "No projection anomalies detected; use canonical position reports for current exposure.",
            "Clean result does not query brokers or prove external market risk.",
        ]
    data = {
        "summary": {
            "bucket": "projection_anomalies",
            "count": len(anomalies),
            "anomaly_count": len(anomalies),
            "codes": codes,
            "severity_counts": {"data_quality": len(anomalies), "market_risk": 0},
            "agent_answer_hints": hints,
            "filter": {"stale_mark_threshold_days": stale_mark_threshold_days, "as_of": to_utc_iso8601(as_of)},
        },
        "groups": [],
        "projection_anomalies": anomalies,
        "agent_answer_hints": hints,
    }
    _propagate_report_meta(ctx, data)
    return data


def _watchlist_for_current_exposure(
    connection: Any,
    *,
    instrument_id: str | None,
    strategy_id: str | None,
    kind: str | None,
) -> list[dict[str, Any]]:
    """Return watch rows scoped to current_exposure's packet-level filters."""

    # Watch rows are explicitly not exposure and have no paper/actual/simulation kind.
    # When a caller asks for a kind-scoped exposure packet, omitting watch rows is
    # safer than leaking unkinded ideas into a supposedly scoped answer.
    if kind is not None:
        return []

    clauses = ["d.type = 'watch'"]
    params: list[Any] = []
    if instrument_id is not None:
        clauses.append("d.instrument_id = ?")
        params.append(instrument_id)
    if strategy_id is not None:
        clauses.append("d.strategy_id = ?")
        params.append(strategy_id)

    rows = connection.execute(
        f"""
        SELECT d.id, d.instrument_id, d.strategy_id, d.reason, d.created_at, d.review_by
        FROM decisions d
        WHERE {' AND '.join(clauses)}
        ORDER BY d.created_at DESC, d.id DESC
        """,
        tuple(params),
    ).fetchall()
    return [
        {
            "decision_id": row[0],
            "instrument_id": row[1],
            "strategy_id": row[2],
            "reason": row[3],
            "created_at": row[4],
            "review_by": row[5],
            "overdue": False,
            "age_days": None,
            "caveat_codes": ["WATCH_ONLY_IDEA"],
            "exposure_hint": "Watch idea only; not counted as exposure.",
        }
        for row in rows
    ]


def _kind_decision_types(kind: str | None) -> tuple[str, ...]:
    if kind == "paper":
        return ("paper_enter", "paper_exit")
    if kind == "actual":
        return ("actual_enter", "actual_exit", "add", "reduce")
    if kind == "simulation":
        return ()
    return ("paper_enter", "paper_exit", "actual_enter", "actual_exit", "add", "reduce")


def _recent_trade_activity(
    connection: Any,
    *,
    recent_limit: int,
    instrument_id: str | None = None,
    strategy_id: str | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    if recent_limit == 0:
        return []
    decision_types = _kind_decision_types(kind)
    if not decision_types:
        return []
    clauses = [f"d.type IN ({','.join('?' for _ in decision_types)})"]
    params: list[Any] = list(decision_types)
    if instrument_id is not None:
        clauses.append("d.instrument_id = ?")
        params.append(instrument_id)
    if strategy_id is not None:
        clauses.append("d.strategy_id = ?")
        params.append(strategy_id)
    params.append(recent_limit)

    rows = connection.execute(
        f"""
        SELECT d.id, d.instrument_id, d.thesis_id, d.forecast_id, d.snapshot_id,
               d.type, d.side, d.quantity, d.price, d.created_at, d.reason,
               d.strategy_id, d.run_id, COUNT(pe.id) AS event_count
        FROM decisions d
        LEFT JOIN position_events pe ON pe.decision_id = d.id
        WHERE {' AND '.join(clauses)}
        GROUP BY d.id
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    activity = []
    for row in rows:
        caveat_codes = ["JOURNAL_ACTIVITY_NOT_CANONICAL_EXPOSURE"]
        if row[5] in ("actual_enter", "actual_exit", "add", "reduce") and row[13] == 0:
            caveat_codes.append("RECORD_ONLY_ACTUAL")
        activity.append({
            "decision_id": row[0],
            "instrument_id": row[1],
            "thesis_id": row[2],
            "forecast_id": row[3],
            "snapshot_id": row[4],
            "type": row[5],
            "side": row[6],
            "quantity": row[7],
            "price": row[8],
            "created_at": row[9],
            "reason": row[10],
            "strategy_id": row[11],
            "run_id": row[12],
            "linked_position_event_count": row[13],
            "caveat_codes": caveat_codes,
            "exposure_hint": "Recent journal activity is not canonical open exposure by itself; use open_positions for exposure.",
        })
    return activity


def _filter_current_exposure_anomalies(
    connection: Any,
    anomalies: list[dict[str, Any]],
    *,
    instrument_id: str | None,
    strategy_id: str | None,
    kind: str | None,
) -> list[dict[str, Any]]:
    """Scope anomaly rows to current_exposure's packet-level filters."""

    if instrument_id is None and strategy_id is None and kind is None:
        return anomalies

    decision_rows = connection.execute("SELECT id, instrument_id, strategy_id, type FROM decisions").fetchall()
    decision_info = {row[0]: {"instrument_id": row[1], "strategy_id": row[2], "type": row[3]} for row in decision_rows}
    position_rows = connection.execute(
        """
        SELECT p.id, p.instrument_id, p.kind, d.strategy_id
        FROM positions p
        LEFT JOIN position_events pe ON pe.position_id = p.id AND pe.event_type = 'open'
        LEFT JOIN decisions d ON d.id = pe.decision_id
        GROUP BY p.id
        """
    ).fetchall()
    position_info = {row[0]: {"instrument_id": row[1], "kind": row[2], "strategy_id": row[3]} for row in position_rows}

    def matches(anomaly: dict[str, Any]) -> bool:
        affected = anomaly.get("affected_ids") or {}
        evidence = anomaly.get("evidence") or {}
        insts = set(affected.get("instruments") or [])
        if evidence.get("instrument_id") is not None:
            insts.add(evidence["instrument_id"])
        decisions = set(affected.get("decisions") or [])
        if evidence.get("decision_id") is not None:
            decisions.add(evidence["decision_id"])
        positions = set(affected.get("positions") or [])
        if evidence.get("position_id") is not None:
            positions.add(evidence["position_id"])

        if instrument_id is not None:
            related_insts = set(insts)
            related_insts.update(info["instrument_id"] for did, info in decision_info.items() if did in decisions)
            related_insts.update(info["instrument_id"] for pid, info in position_info.items() if pid in positions)
            if instrument_id not in related_insts:
                return False
        if strategy_id is not None:
            related_strategies = {info["strategy_id"] for did, info in decision_info.items() if did in decisions}
            related_strategies.update(info["strategy_id"] for pid, info in position_info.items() if pid in positions)
            if strategy_id not in related_strategies:
                return False
        if kind is not None:
            related_kinds = {info["kind"] for pid, info in position_info.items() if pid in positions}
            related_types = {info["type"] for did, info in decision_info.items() if did in decisions}
            if not related_kinds and related_types:
                if related_types <= {"paper_enter", "paper_exit"}:
                    related_kinds.add("paper")
                elif related_types <= {"actual_enter", "actual_exit", "add", "reduce"}:
                    related_kinds.add("actual")
            if kind not in related_kinds:
                return False
        return True

    return [anomaly for anomaly in anomalies if matches(anomaly)]


def _current_exposure_hints(open_count: int, watch_count: int, recent_count: int, anomaly_count: int) -> list[str]:
    hints = [f"Canonical open positions: {open_count}."]
    if open_count == 0 and recent_count:
        hints[0] = "Canonical open positions: zero; recent journal entries exist but are not open exposure."
    if watch_count:
        hints.append("Watchlist rows are WATCH_ONLY_IDEA; do not count them as exposure.")
    if recent_count:
        hints.append("Recent trade activity is an audit/journal trail; it can explain trading but does not define current exposure.")
    if anomaly_count:
        hints.append("Projection anomalies caveat the answer; do not infer open trades from decisions-only evidence.")
    if open_count == 0 and watch_count == 0 and recent_count == 0 and anomaly_count == 0:
        hints.append("No watch ideas, recent trade activity, or projection anomalies found in the local journal.")
    hints.append("Trade Trace reports local journal/projection state only; it does not assert broker or external portfolio truth.")
    hints.append("When imported account snapshots exist, compare projected positions against imported-observed positions via reconciliation reports before treating them as externally observed holdings.")
    return hints


def _report_current_exposure(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`report.current_exposure` — trader-agent packet for exposure questions."""

    recent_limit = args.get("recent_limit", 10)
    if not isinstance(recent_limit, int) or recent_limit < 0:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "recent_limit must be a non-negative integer", details={"field": "recent_limit", "value": recent_limit})
    include_watchlist = args.get("include_watchlist", True)
    include_anomalies = args.get("include_anomalies", True)
    if not isinstance(include_watchlist, bool):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "include_watchlist must be a boolean", details={"field": "include_watchlist", "value": include_watchlist})
    if not isinstance(include_anomalies, bool):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "include_anomalies must be a boolean", details={"field": "include_anomalies", "value": include_anomalies})

    effective_as_of = args.get("as_of")
    if effective_as_of is None:
        effective_as_of = to_utc_iso8601(datetime.now(UTC))

    open_args = {k: v for k, v in args.items() if k in {"home", "limit", "kind", "instrument_id", "strategy_id", "stale_mark_threshold_days", "as_of"}}
    open_args["as_of"] = effective_as_of
    open_data = _report_open_positions(open_args, ctx)
    effective_as_of = open_data.get("summary", {}).get("filter", {}).get("as_of", effective_as_of)
    anomaly_args = {k: v for k, v in args.items() if k in {"home", "stale_mark_threshold_days", "as_of"}}
    anomaly_args["as_of"] = effective_as_of
    anomaly_data = _report_exposure_anomalies(anomaly_args, ctx) if include_anomalies else None

    db = open_db_for_args(args)
    try:
        watchlist = _watchlist_for_current_exposure(
            db.connection,
            instrument_id=args.get("instrument_id"),
            strategy_id=args.get("strategy_id"),
            kind=args.get("kind"),
        ) if include_watchlist else []
        recent_activity = _recent_trade_activity(
            db.connection,
            recent_limit=recent_limit,
            instrument_id=args.get("instrument_id"),
            strategy_id=args.get("strategy_id"),
            kind=args.get("kind"),
        )
        anomalies = _filter_current_exposure_anomalies(
            db.connection,
            anomaly_data.get("projection_anomalies", []) if anomaly_data is not None else [],
            instrument_id=args.get("instrument_id"),
            strategy_id=args.get("strategy_id"),
            kind=args.get("kind"),
        )
        event_exposure_sets = _event_exposure_sets(db.connection, open_data.get("open_positions", []))
        latest_account_snapshot = db.connection.execute(
            "SELECT id, as_of, imported_at, staleness_status FROM account_snapshots ORDER BY source_precedence ASC, as_of DESC, imported_at DESC, id DESC LIMIT 1",
        ).fetchone()
    finally:
        db.close()

    open_positions = open_data.get("open_positions", [])
    hints = _current_exposure_hints(len(open_positions), len(watchlist), len(recent_activity), len(anomalies))
    data = {
        "summary": {
            "bucket": "current_exposure",
            "buckets": ["open_positions", "event_exposure_sets", "watchlist", "recent_trade_activity", "projection_anomalies"],
            "open_position_count": open_data.get("summary", {}).get("open_position_count", len(open_positions)),
            "event_exposure_set_count": len(event_exposure_sets),
            "watch_count": len(watchlist),
            "recent_trade_decision_count": len(recent_activity),
            "anomaly_count": len(anomalies),
            "position_truth_caveat": "projected_local_positions_not_imported_account_truth",
            "latest_imported_account_snapshot": None if latest_account_snapshot is None else {"id": latest_account_snapshot[0], "as_of": latest_account_snapshot[1], "imported_at": latest_account_snapshot[2], "staleness_status": latest_account_snapshot[3]},
            "filter": {
                "kind": args.get("kind"),
                "instrument_id": args.get("instrument_id"),
                "strategy_id": args.get("strategy_id"),
                "recent_limit": recent_limit,
                "include_watchlist": include_watchlist,
                "include_anomalies": include_anomalies,
                "stale_mark_threshold_days": args.get("stale_mark_threshold_days", 14),
                "as_of": effective_as_of,
            },
            "agent_answer_hints": hints,
        },
        "groups": event_exposure_sets,
        "event_exposure_sets": event_exposure_sets,
        "open_positions": open_positions,
        "watchlist": watchlist,
        "recent_trade_activity": recent_activity,
        "projection_anomalies": anomalies,
        "agent_answer_hints": hints,
        "lower_level_reports": {
            "open_positions": "report.open_positions",
            "watchlist": "report.watchlist",
            "projection_anomalies": "report.exposure_anomalies",
        },
    }
    _propagate_report_meta(ctx, data)
    return data


__all__ = [name for name in globals() if not name.startswith("__")]
