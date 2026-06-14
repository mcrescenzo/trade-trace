"""Read-only market scan dry-run planner.

This tool turns caller-supplied venue/instrument/snapshot/research inputs into a
primitive journal call plan. It never fetches external data, gives no advice, and
performs no database writes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.tools.decision_matrix import DECISION_MATRIX, decision_matrix_contract
from trade_trace.tools.errors import ToolError

CONTRACT_VERSION = "1.0"
_ALLOWED_ACTIONS = {"watch", "skip", "paper_enter"}
_SEGMENTATION_KEYS = ("agent_id", "model_id", "environment", "run_id")
_DECISION_KEYS = (
    "side", "quantity", "price", "fees", "slippage", "reason", "review_by",
    "playbook_version_id", "strategy_id", "tags", "metadata_json",
)


class MarketScanDryRunInput(BaseModel):
    """Input contract for market.scan.dry_run."""

    model_config = ConfigDict(extra="forbid")

    actor_id: str | None = None
    idempotency_key: str
    agent_id: str | None = None
    model_id: str | None = None
    environment: str | None = None
    run_id: str | None = None
    venue: dict[str, Any] | None = None
    instrument: dict[str, Any]
    snapshot: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    thesis: dict[str, Any] | None = None
    forecast: dict[str, Any] | None = None
    decision: dict[str, Any]
    attachments: dict[str, Any] = Field(default_factory=dict)
    current_time: str | None = Field(default=None, description="Deterministic clock for stale_snapshot checks.")
    stale_snapshot_hours: int = Field(default=24, ge=1, le=87600)
    wide_spread_bps: int = Field(default=500, ge=1, le=100000)
    home: str | None = Field(default=None, description="Accepted for transport parity; dry-run does not open the DB.")


class MarketScanPromoteInput(MarketScanDryRunInput):
    """Input contract for market.scan.promote."""

    promote_hash: str | None = None
    stale_source_days: int = Field(default=14, ge=1, le=3650, description="Source-staleness window forwarded to the final journal.bundle.status check.")


_EXAMPLE_MINIMAL = {
    "idempotency_key": "run-42:market-scan:pm:event-x:v1",
    "venue": {"name": "Polymarket", "kind": "prediction_market"},
    "instrument": {"asset_class": "prediction_market", "title": "Will event X happen?", "resolution_criteria_text": "Caller supplied rules."},
    "snapshot": {"captured_at": "2026-05-21T12:00:00Z", "source": "manual", "price": 0.52, "bid": 0.50, "ask": 0.54},
    "decision": {"action": "watch", "side": "yes", "reason": "Caller-selected watch rationale.", "review_by": "2026-05-28T12:00:00Z"},
}

_EXAMPLE_RICH = {
    **_EXAMPLE_MINIMAL,
    "agent_id": "agent:research-bot",
    "sources": [{"kind": "url", "stance": "supports", "uri": "https://example.invalid/source", "title": "Primary evidence", "summary": "Caller supplied summary."}],
    "thesis": {"side": "yes", "body": "Caller-authored thesis.", "falsification_criteria": "What would disprove it."},
    "forecast": {"kind": "binary", "resolution_rule_text": "Caller supplied rules.", "outcomes": [{"outcome_label": "YES", "probability": 0.57}, {"outcome_label": "NO", "probability": 0.43}]},
    "attachments": {"attach_sources_to": ["thesis", "forecast", "decision"]},
}

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["idempotency_key", "instrument", "decision"],
    "additionalProperties": False,
    "properties": {
        "actor_id": {"type": "string"},
        "idempotency_key": {"type": "string"},
        "agent_id": {"type": "string"}, "model_id": {"type": "string"}, "environment": {"type": "string"}, "run_id": {"type": "string"},
        "venue": {"type": "object", "additionalProperties": True},
        "instrument": {"type": "object", "additionalProperties": True},
        "snapshot": {"type": "object", "additionalProperties": True},
        "sources": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "thesis": {"type": "object", "additionalProperties": True},
        "forecast": {"type": "object", "additionalProperties": True},
        "decision": {"type": "object", "required": ["action"], "properties": {"action": {"type": "string", "enum": ["watch", "skip", "paper_enter"]}}, "additionalProperties": True},
        "attachments": {"type": "object", "additionalProperties": True},
        "current_time": {"type": "string"},
        "stale_snapshot_hours": {"type": "integer", "minimum": 1, "maximum": 87600},
        "wide_spread_bps": {"type": "integer", "minimum": 1, "maximum": 100000},
        "home": {"type": "string", "description": "Accepted for transport parity; dry-run does not open the DB."},
    },
    "description": "Read-only validator/planner for caller-supplied market scan bundles. No external fetch, no advice, no trade execution, no DB writes.",
    "examples": [_EXAMPLE_MINIMAL, _EXAMPLE_RICH],
    "x-decision-matrix": {k: decision_matrix_contract()[k] for k in sorted(_ALLOWED_ACTIONS)},
}

_PROMOTE_SCHEMA: dict[str, Any] = {
    **_SCHEMA,
    "properties": {
        **_SCHEMA["properties"],
        "promote_hash": {"type": "string", "description": "Optional dry-run promote_hash guard; mismatches fail before writes."},
        "stale_source_days": {"type": "integer", "minimum": 1, "maximum": 3650, "description": "Source-staleness window forwarded to the final journal.bundle.status check."},
    },
    "description": "Write-capable materializer for market.scan.dry_run plans using deterministic child idempotency keys.",
}


def _check(severity: str, code: str, field: str, message: str, recovery: str | None = None) -> dict[str, Any]:
    out = {"severity": severity, "code": code, "field": field, "message": message}
    if recovery:
        out["recovery"] = recovery
    return out


def _iso_parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_timezone_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _placeholder(name: str) -> str:
    return f"<{name}>"


def _copy_args(src: dict[str, Any], exclude: set[str] | frozenset[str] = frozenset()) -> dict[str, Any]:
    return {k: v for k, v in src.items() if k not in exclude and v is not None}


def _call(tool: str, purpose: str, args: dict[str, Any], creates: str, key: str | None = None) -> dict[str, Any]:
    out = {"tool": tool, "purpose": purpose, "args": args, "creates": creates}
    if key:
        out["child_idempotency_key"] = key
    return out


def _market_scan_dry_run(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    try:
        parsed = MarketScanDryRunInput.model_validate(args)
    except ValidationError as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"market.scan.dry_run input validation failed: {exc.errors()}", details={"validation_errors": exc.errors()}) from exc

    parent = parsed.idempotency_key
    action = str(parsed.decision.get("action", "")).strip()
    checks = [_check("info", "caller_supplied_data_only", "bundle", "All market/source fields are caller supplied and unverified; no fetch is performed.")]
    if action == "paper_enter":
        checks.append(_check("info", "paper_enter_is_journal_only", "decision.action", "paper_enter is a paper journal entry only; no broker trade is executed."))
    if any(s.get("uri") or s.get("source_url") for s in parsed.sources):
        checks.append(_check("info", "source_url_not_fetched", "sources", "Source URLs are stored as caller-supplied provenance only and are not fetched."))
    if (parsed.snapshot or {}).get("source_url"):
        checks.append(_check("info", "source_url_not_fetched", "snapshot.source_url", "Snapshot source_url is stored as caller-supplied provenance only and is not fetched."))

    now = _iso_parse(parsed.current_time) if parsed.current_time else datetime.now(UTC)
    if parsed.current_time and (not now or not _is_timezone_aware(now)):
        checks.append(_check("blocking", "invalid_timestamp", "current_time", "current_time must be an ISO timestamp with timezone."))
        now = None

    missing_fields: list[str] = []
    if action not in _ALLOWED_ACTIONS:
        checks.append(_check("blocking", "invalid_enum", "decision.action", "decision.action must be one of watch, skip, paper_enter.", "Choose an allowed caller-selected action."))

    if not parsed.sources:
        checks.append(_check("warning", "missing_source", "sources", "No caller-supplied source/research attachment was supplied."))
    if not parsed.forecast:
        checks.append(_check("warning", "missing_forecast", "forecast", "No forecast was supplied; calibration/audit trail may be weak."))
    if not (parsed.instrument.get("resolution_criteria_text") or (parsed.forecast or {}).get("resolution_rule_text")):
        checks.append(_check("blocking", "missing_resolution_criteria", "instrument.resolution_criteria_text", "No auditable resolution criteria were supplied."))
        missing_fields.append("instrument.resolution_criteria_text")
    if action == "watch" and not parsed.decision.get("review_by"):
        checks.append(_check("warning", "missing_revisit_deadline", "decision.review_by", "Watch decisions should include a review_by deadline."))

    snap = parsed.snapshot or {}
    if snap:
        bid, ask = snap.get("bid"), snap.get("ask")
        spread = snap.get("spread")
        mid = snap.get("mid") or snap.get("price")
        if (bid is None or ask is None) and spread is None:
            checks.append(_check("warning", "missing_bid_ask", "snapshot", "Snapshot lacks bid/ask and spread/liquidity fields."))
        try:
            calc_spread = float(spread) if spread is not None else (float(ask) - float(bid) if bid is not None and ask is not None else None)
            denom = float(mid) if mid is not None else None
            if calc_spread is not None and denom and denom > 0 and (calc_spread / denom) * 10000 >= parsed.wide_spread_bps:
                checks.append(_check("warning", "wide_spread", "snapshot.spread", "Snapshot spread is high relative to mid/price."))
        except (TypeError, ValueError):
            checks.append(_check("blocking", "invalid_number", "snapshot.spread", "Snapshot bid/ask/spread/mid values must be numeric when supplied."))
        captured = _iso_parse(snap.get("captured_at"))
        if snap.get("captured_at") and (not captured or not _is_timezone_aware(captured)):
            checks.append(_check("blocking", "invalid_timestamp", "snapshot.captured_at", "captured_at must be an ISO timestamp with timezone."))
        elif captured and now and (now - captured).total_seconds() > parsed.stale_snapshot_hours * 3600:
            checks.append(_check("warning", "stale_snapshot", "snapshot.captured_at", "Snapshot is older than the dry-run freshness threshold."))

    decision_args: dict[str, Any] = {"type": action}
    decision_args["instrument_id"] = parsed.instrument.get("instrument_id") or _placeholder("instrument_id")
    if parsed.thesis:
        decision_args["thesis_id"] = parsed.thesis.get("thesis_id") or _placeholder("thesis_id")
    if parsed.forecast:
        decision_args["forecast_id"] = parsed.forecast.get("forecast_id") or _placeholder("forecast_id")
    if parsed.snapshot:
        decision_args["snapshot_id"] = parsed.snapshot.get("snapshot_id") or _placeholder("snapshot_id")
    for k in _DECISION_KEYS:
        if k in parsed.decision and parsed.decision[k] is not None:
            decision_args[k] = parsed.decision[k]
    for k in _SEGMENTATION_KEYS:
        v = getattr(parsed, k)
        if v is not None:
            decision_args[k] = v
    dkey = f"{parent}:decision:{action or '<action>'}"
    decision_args["idempotency_key"] = dkey

    if action in DECISION_MATRIX:
        for field, kind in DECISION_MATRIX[action].items():
            val = decision_args.get(field)
            if kind == "R" and (val is None or val == ""):
                checks.append(_check("blocking", "decision_matrix_violation", f"decision.{field}", f"{field} is required for decision.action={action}."))
                missing_fields.append(f"decision.{field}")
            if kind == "X" and val is not None and val != "":
                checks.append(_check("blocking", "decision_matrix_violation", f"decision.{field}", f"{field} is forbidden for decision.action={action}."))

    keys: dict[str, str] = {}
    calls: list[dict[str, Any]] = []
    if parsed.venue and not parsed.venue.get("venue_id"):
        key = f"{parent}:venue"
        keys["venue"] = key
        calls.append(_call("venue.add", "Create/reuse caller-supplied venue row.", {**_copy_args(parsed.venue, {"venue_id"}), "idempotency_key": key}, "venue_id", key))
    instr_id = parsed.instrument.get("instrument_id") or _placeholder("instrument_id")
    if not parsed.instrument.get("instrument_id"):
        key = f"{parent}:instrument"
        keys["instrument"] = key
        iargs = _copy_args(parsed.instrument, {"instrument_id"})
        iargs.setdefault("venue_id", (parsed.venue or {}).get("venue_id") or _placeholder("venue_id"))
        iargs["idempotency_key"] = key
        calls.append(_call("instrument.add", "Create/reuse caller-supplied instrument row.", iargs, "instrument_id", key))
    if parsed.snapshot and not parsed.snapshot.get("snapshot_id"):
        key = f"{parent}:snapshot"
        keys["snapshot"] = key
        sargs = {**_copy_args(parsed.snapshot, {"snapshot_id"}), "instrument_id": instr_id, "idempotency_key": key}
        calls.append(_call("snapshot.add", "Record caller-supplied snapshot; no venue fetch is performed.", sargs, "snapshot_id", key))
    for idx, source in enumerate(parsed.sources):
        if source.get("source_id"):
            continue
        key = f"{parent}:source:{idx}"
        keys[f"source:{idx}"] = key
        calls.append(_call("source.add", "Store caller-supplied source metadata/content only.", {**_copy_args(source, {"source_id"}), "idempotency_key": key}, "source_id", key))
    if parsed.thesis and not parsed.thesis.get("thesis_id"):
        key = f"{parent}:thesis"
        keys["thesis"] = key
        calls.append(_call("thesis.add", "Create/reuse caller-authored thesis.", {**_copy_args(parsed.thesis, {"thesis_id"}), "instrument_id": instr_id, "idempotency_key": key}, "thesis_id", key))
    attach_to = parsed.attachments.get("attach_sources_to", []) or []
    for idx, source in enumerate(parsed.sources):
        for target in ("thesis",):
            if target in attach_to and parsed.thesis:
                key = f"{parent}:source:{idx}:attach:{target}"
                keys[f"source_attach:{idx}:{target}"] = key
                calls.append(_call("source.attach_to_thesis", "Attach source to thesis.", {"source_id": source.get("source_id") or _placeholder("source_id"), "target_id": parsed.thesis.get("thesis_id") or _placeholder("thesis_id"), "idempotency_key": key}, "edge_id", key))
    if parsed.forecast and not parsed.forecast.get("forecast_id"):
        key = f"{parent}:forecast"
        keys["forecast"] = key
        calls.append(_call("forecast.add", "Create/reuse caller-supplied forecast.", {**_copy_args(parsed.forecast, {"forecast_id"}), "thesis_id": (parsed.thesis or {}).get("thesis_id") or _placeholder("thesis_id"), "idempotency_key": key}, "forecast_id", key))
    for idx, source in enumerate(parsed.sources):
        for target in ("forecast",):
            if target in attach_to and parsed.forecast:
                key = f"{parent}:source:{idx}:attach:{target}"
                keys[f"source_attach:{idx}:{target}"] = key
                calls.append(_call("source.attach_to_forecast", "Attach source to forecast.", {"source_id": source.get("source_id") or _placeholder("source_id"), "target_id": parsed.forecast.get("forecast_id") or _placeholder("forecast_id"), "idempotency_key": key}, "edge_id", key))
    keys[f"decision:{action}"] = dkey
    calls.append(_call("decision.add", f"Record caller-selected {action} decision using existing decision.add matrix.", decision_args, "decision_id", dkey))
    for idx, source in enumerate(parsed.sources):
        if "decision" in attach_to:
            key = f"{parent}:source:{idx}:attach:decision"
            keys[f"source_attach:{idx}:decision"] = key
            calls.append(_call("source.attach_to_decision", "Attach source to decision.", {"source_id": source.get("source_id") or _placeholder("source_id"), "target_id": _placeholder("decision_id"), "idempotency_key": key}, "edge_id", key))

    normalized_bundle = parsed.model_dump(exclude_none=True, exclude={"home"})
    normalized_bundle["decision"] = {**parsed.decision, "action": action}
    payload_for_hash = {"contract_version": CONTRACT_VERSION, "normalized_bundle": normalized_bundle, "ordered_calls": calls, "child_idempotency_keys": keys}
    promote_hash = "sha256:" + hashlib.sha256(_canonical(payload_for_hash).encode("utf-8")).hexdigest()
    blocking = any(c["severity"] == "blocking" for c in checks)
    return {
        "plan_state": "dry_run",
        "bundle_status": "blocked" if blocking else "ready_to_promote",
        "normalized_action": action,
        "ordered_calls": calls,
        "checks": checks,
        "missing_fields": sorted(set(missing_fields)),
        "child_idempotency_keys": keys,
        "promote_payload_hint": {"idempotency_key": parent, "plan_hash": promote_hash, "bundle": normalized_bundle, "ordered_calls": calls},
        "promote_hash": promote_hash,
        "no_advice_boundary": {"external_fetch_performed": False, "trade_execution_performed": False, "advice_generated": False},
    }


def _replace_placeholders(value: Any, ids: dict[str, Any], *, source_idx: int | None = None) -> Any:
    if isinstance(value, str) and value.startswith("<") and value.endswith(">"):
        name = value[1:-1]
        if name == "source_id" and source_idx is not None:
            return ids.get(f"source:{source_idx}", value)
        return ids.get(name, value)
    if isinstance(value, list):
        return [_replace_placeholders(v, ids, source_idx=source_idx) for v in value]
    if isinstance(value, dict):
        return {k: _replace_placeholders(v, ids, source_idx=source_idx) for k, v in value.items()}
    return value


def _source_idx_from_key(key: str | None) -> int | None:
    if not key:
        return None
    parts = key.split(":")
    try:
        pos = parts.index("source")
        return int(parts[pos + 1])
    except (ValueError, IndexError):
        return None


def _append_unique_id(container: dict[str, Any], key: str, rid: Any) -> None:
    values = container.setdefault(key, [])
    if rid not in values:
        values.append(rid)


def _record_promote_id(ids: dict[str, Any], bucket: dict[str, Any], creates: str, rid: Any, child_key: str | None) -> None:
    """Record a child ID without collapsing repeated source/edge resources."""
    if creates == "source_id":
        sidx = _source_idx_from_key(child_key)
        if sidx is not None:
            ids[f"source:{sidx}"] = rid
            bucket[f"source:{sidx}"] = rid
        ids.setdefault("source_id", rid)
        bucket.setdefault("source_id", rid)
        _append_unique_id(ids, "source_ids", rid)
        _append_unique_id(bucket, "source_ids", rid)
        return
    if creates == "edge_id":
        if child_key:
            parts = child_key.split(":")
            try:
                pos = parts.index("source")
                stable_key = f"source_attach:{parts[pos + 1]}:{parts[pos + 3]}"
                ids[stable_key] = rid
                bucket[stable_key] = rid
            except (ValueError, IndexError):
                pass
        _append_unique_id(ids, "edge_ids", rid)
        _append_unique_id(bucket, "edge_ids", rid)
        return
    ids[creates] = rid
    if creates.endswith("_id"):
        ids.setdefault(creates[:-3], rid)
    bucket[creates] = rid


def _market_scan_promote(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    try:
        parsed = MarketScanPromoteInput.model_validate(args)
    except ValidationError as exc:
        raise ToolError(ErrorCode.VALIDATION_ERROR, f"market.scan.promote input validation failed: {exc.errors()}", details={"validation_errors": exc.errors()}) from exc

    dry_args = parsed.model_dump(exclude_none=True, exclude={"promote_hash", "stale_source_days"})
    dry_run = _market_scan_dry_run(dry_args, ctx)
    if parsed.promote_hash and parsed.promote_hash != dry_run["promote_hash"]:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "promote_hash does not match current market.scan.dry_run plan", details={"field": "promote_hash", "expected": dry_run["promote_hash"], "actual": parsed.promote_hash})
    blocking = [c for c in dry_run["checks"] if c.get("severity") == "blocking"]
    if blocking:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "market.scan.promote blocked by dry-run validation checks", details={"checks": blocking, "promote_hash": dry_run["promote_hash"]})

    from trade_trace.core import dispatch  # Lazy import avoids import cycle.

    ids: dict[str, Any] = {}
    for key in ("venue_id", "instrument_id", "snapshot_id"):
        container = key[:-3]
        if isinstance(dry_args.get(container), dict) and dry_args[container].get(key):
            ids[key] = dry_args[container][key]
    for idx, source in enumerate(dry_args.get("sources") or []):
        if source.get("source_id"):
            ids[f"source:{idx}"] = source["source_id"]
            ids.setdefault("source_id", source["source_id"])
            _append_unique_id(ids, "source_ids", source["source_id"])
    for key in ("thesis_id", "forecast_id"):
        container = key[:-3]
        if isinstance(dry_args.get(container), dict) and dry_args[container].get(key):
            ids[key] = dry_args[container][key]

    primitive_results: list[dict[str, Any]] = []
    created_ids: dict[str, Any] = {}
    reused_ids: dict[str, Any] = {}
    for step_no, planned in enumerate(dry_run["ordered_calls"], start=1):
        ckey = planned.get("child_idempotency_key")
        call_args = _replace_placeholders(planned["args"], ids, source_idx=_source_idx_from_key(ckey))
        if parsed.home:
            call_args.setdefault("home", parsed.home)
        env = dispatch(planned["tool"], call_args, actor_id=ctx.actor_id)
        primitive_results.append({"step": step_no, "tool": planned["tool"], "ok": env.ok, "args": call_args, "data": env.data if env.ok else None, "error": None if env.ok else env.error.model_dump(mode="json")})
        if not env.ok:
            raise ToolError(env.error.code, f"market.scan.promote child step {step_no} {planned['tool']} failed: {env.error.message}", details={"step": step_no, "tool": planned["tool"], "child_error": env.error.model_dump(mode="json"), "primitive_results": primitive_results})
        rid = env.data.get("id") if isinstance(env.data, dict) else None
        if rid:
            creates = planned["creates"]
            if env.meta.idempotent_replay is True:
                _record_promote_id(ids, reused_ids, creates, rid, ckey)
            else:
                _record_promote_id(ids, created_ids, creates, rid, ckey)

    reflection_result = None
    reflection = (dry_args.get("attachments") or {}).get("reflection") or {}
    if reflection.get("enabled") and (reflection.get("body") or reflection.get("insight")):
        target_kind = reflection.get("target_kind") or "decision"
        target_id = reflection.get("target_id") or ids.get(f"{target_kind}_id")
        rargs = {k: v for k, v in reflection.items() if k not in {"enabled", "target_kind", "target_id"} and v is not None}
        rargs.update({"target_kind": target_kind, "target_id": target_id, "idempotency_key": f"{parsed.idempotency_key}:reflection"})
        if parsed.home:
            rargs["home"] = parsed.home
        env = dispatch("memory.reflect", rargs, actor_id=ctx.actor_id)
        reflection_result = env.data if env.ok else None
        if not env.ok:
            raise ToolError(env.error.code, f"market.scan.promote memory.reflect failed: {env.error.message}", details={"child_error": env.error.model_dump(mode="json"), "primitive_results": primitive_results})
        if reflection_result and reflection_result.get("id"):
            ids["memory_node_id"] = reflection_result["id"]
            if env.meta.idempotent_replay is True:
                reused_ids["memory_node_id"] = reflection_result["id"]
            else:
                created_ids["memory_node_id"] = reflection_result["id"]

    status_args = {k: ids[k] for k in ("decision_id", "forecast_id", "thesis_id", "instrument_id", "source_id", "memory_node_id") if ids.get(k)}
    # Thread the deterministic clock + staleness window so final_check is
    # reproducible instead of flipping with the wall clock (trade-trace-efmq).
    if parsed.current_time:
        status_args["current_time"] = parsed.current_time
    status_args["stale_source_days"] = parsed.stale_source_days
    if parsed.home:
        status_args["home"] = parsed.home
    final_env = dispatch("journal.bundle.status", status_args, actor_id=ctx.actor_id)
    if not final_env.ok:
        raise ToolError(final_env.error.code, f"market.scan.promote final journal.bundle.status failed: {final_env.error.message}", details={"child_error": final_env.error.model_dump(mode="json"), "status_args": status_args})
    return {
        "plan_state": "promoted",
        "promote_hash": dry_run["promote_hash"],
        "normalized_action": dry_run["normalized_action"],
        "created_ids": created_ids,
        "reused_ids": reused_ids,
        "ids": ids,
        "primitive_results": primitive_results,
        "reflection_result": reflection_result,
        "final_check": final_env.data,
        "bundle_status": final_env.data.get("status"),
        "transaction_semantics": "logical_replay_safe_child_idempotency_not_physical_rollback",
    }


def register_market_scan_tools(registry: ToolRegistry) -> None:
    registry.register(
        "market.scan.dry_run",
        _market_scan_dry_run,
        is_write=False,
        json_schema=_SCHEMA,
        example_minimal=_EXAMPLE_MINIMAL,
        example_rich=_EXAMPLE_RICH,
        description="Read-only market-scan validator/planner; returns primitive call plan and checks without DB writes, fetches, advice, or execution.",
        usage_summary="Plan a caller-supplied watch/skip/paper_enter journal bundle. Use --*-json for nested objects on CLI.",
        examples=("tt market scan dry_run --idempotency-key run-42 --instrument-json '{...}' --decision-json '{\"action\":\"watch\"}'",),
        enum_notes={"decision.action": "Caller supplied; one of watch, skip, paper_enter. Maps to decision.add type."},
        common_failures=("missing_resolution_criteria", "decision_matrix_violation", "missing_source", "stale_snapshot"),
        next_actions=("Review checks, then call market.scan.promote with the same payload and optional promote_hash guard.",),
    )
    registry.register(
        "market.scan.promote",
        _market_scan_promote,
        is_write=True,
        json_schema=_PROMOTE_SCHEMA,
        example_minimal={**_EXAMPLE_MINIMAL, "promote_hash": "sha256:<optional dry-run hash>"},
        example_rich={**_EXAMPLE_RICH, "promote_hash": "sha256:<optional dry-run hash>"},
        description="Write-capable replay-safe materializer for market.scan.dry_run primitive plans.",
        usage_summary="Promote a caller-supplied watch/skip/paper_enter market scan into local journal rows using deterministic child idempotency keys.",
        examples=("tt market scan promote --idempotency-key run-42 --instrument-json '{...}' --decision-json '{\"action\":\"watch\"}'",),
        enum_notes={"decision.action": "Caller supplied; one of watch, skip, paper_enter. Maps to decision.add type."},
        common_failures=("promote_hash mismatch", "blocking dry-run checks", "child primitive validation error"),
        next_actions=("Inspect final_check/journal.bundle.status and suggested_next_calls.",),
    )
