"""Opt-in Polymarket adapter-backed v0.0.2 tools.

All outbound calls are isolated here and guarded by network.polymarket.enabled.
Disabled paths fail closed with ADAPTER_DISABLED except market.bind manual metadata,
which is implemented in market_bind.py.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import quote

from trade_trace.adapters.polymarket.cache import MARKET_CACHE_TTL_SECONDS
from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.adapters.polymarket.config import load_config
from trade_trace.adapters.polymarket.errors import AdapterError
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    common_metadata,
    db_for_args,
    emit_event,
    new_id,
    now_iso,
    require,
    store_metadata_json,
)
from trade_trace.tools._market_rows import ADAPTER_CACHE_HIT_ROW_SELECT, adapter_cache_hit_row_dict
from trade_trace.tools.errors import ToolError


def _tool_error(exc: AdapterError) -> ToolError:
    return ToolError(exc.code, exc.message, details=exc.details)


def _outcome_fetch_error(exc: AdapterError) -> ToolError:
    """Surface a no-RPC resolution-evidence signpost on outcome.fetch failures.

    outcome.fetch ingests on-chain resolution and so requires
    network.polymarket.polygon_rpc_url; when that is unset it fails closed with
    CONFIG_REQUIRED. The Gamma read path (snapshot.fetch) does NOT need an RPC
    endpoint and already carries Gamma's resolution-evidence fields
    (winningOutcome / outcomePrices, surfaced into markets.venue_metadata_json
    by market.bind/market.refresh). Without this nudge an automated resolution
    feeder dead-ends here and leaves forecasts perpetually pending, never
    reaching the calibration N>=20 floor (bead trade-trace-isqo). We do NOT
    auto-fall back to the Gamma value (that would weaken on-chain resolution
    finality, a resolution-contract change); we only point the caller to the
    documented no-RPC evidence route. The point-of-failure hint mirrors the
    market.search search_hint pattern.
    """

    if exc.code is ErrorCode.CONFIG_REQUIRED and (exc.details or {}).get("config_key") == "network.polymarket.polygon_rpc_url":
        details = dict(exc.details or {})
        details["no_rpc_resolution_evidence_route"] = "snapshot.fetch"
        details["hint"] = (
            "outcome.fetch ingests on-chain resolution and needs "
            "network.polymarket.polygon_rpc_url. With no RPC configured, use the "
            "Gamma read path instead: snapshot.fetch (or market.refresh) carries "
            "Gamma resolution evidence (winningOutcome / outcomePrices) without an "
            "RPC endpoint, then record it via resolution.add. resolution.add is "
            "always available regardless of adapter config."
        )
        return ToolError(exc.code, exc.message, details=details)
    return _tool_error(exc)


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"))


def _first_present(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def _normalize_bool_like(value: Any) -> bool | None:
    """Normalize common API bool encodings without treating 'false' as truthy."""

    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "t", "yes", "y", "1", "on"}:
            return True
        if lowered in {"false", "f", "no", "n", "0", "off"}:
            return False
    return None


def _polymarket_identity_metadata(raw: dict[str, Any], external_id: str) -> dict[str, Any]:
    """Extract public Polymarket IDs/reporting metadata; never credentials."""

    token_ids = _first_present(raw, "clobTokenIds", "clobTokenIDs", "tokenIds", "token_ids") or []
    labels = [_outcome_label(o, external_id, idx) for idx, o in enumerate(raw.get("outcomes") or raw.get("tokens") or [])]
    token_ids_by_label = {
        label: str(token_ids[idx])
        for idx, label in enumerate(labels)
        if isinstance(token_ids, list) and idx < len(token_ids)
    }
    event_id = _first_present(raw, "eventId", "event_id", "gammaEventId")
    return {
        "polymarket_identity": {
            "gamma_market_id": str(_first_present(raw, "id", "marketId", "gammaMarketId") or external_id),
            "gamma_event_id": event_id,
            "market_slug": _first_present(raw, "slug", "marketSlug"),
            "event_slug": _first_present(raw, "eventSlug", "event_slug"),
            "condition_id": _first_present(raw, "conditionId", "condition_id"),
            "outcome_token_ids_by_label": token_ids_by_label,
        },
        "event_grouping": {
            "event_id": event_id,
            "event_slug": _first_present(raw, "eventSlug", "event_slug"),
            "event_title": _first_present(raw, "eventTitle", "event_title", "eventName"),
        },
        "resolution_rule": {
            # Polymarket's Gamma payload carries the resolution prose in
            # ``description`` (the consequential multi-clause "resolve per …"
            # text), not ``resolutionCriteria``/``rules`` — those keys are almost
            # always absent, so the structured ``resolution_rule.text`` was null
            # while the criterion sat unreadable in venue_metadata_json.description
            # (trade-trace-n33z, AX-017). Read ``description`` as the primary
            # source so the criterion an agent needs to forecast travels in the
            # structured field, falling back to the legacy keys if a deployment
            # ever populates them.
            "text": _first_present(
                raw, "resolutionCriteria", "resolution_rule_text", "rules", "description"
            ),
            "source": _first_present(raw, "resolutionSource", "resolutionSourceUrl", "resolution_source_url", "rulesSource"),
            "provenance": "polymarket_gamma_payload",
        },
        "negative_risk": {
            "enabled": bool(_normalize_bool_like(_first_present(raw, "negRisk", "negativeRisk", "negative_risk"))),
            "caveat": _first_present(raw, "negRiskMarketID", "negativeRiskMarketId", "negative_risk_caveat"),
        },
        "market_microstructure": {
            "tick_size": _first_present(raw, "tickSize", "minimumTickSize", "tick_size"),
            "fee_rate_bps": _first_present(raw, "feeRateBps", "fee_rate_bps"),
            "rewards": _first_present(raw, "rewards", "reward", "rewardsDailyRate"),
            "rebates": _first_present(raw, "rebates", "rebate"),
            "tradable": _normalize_bool_like(_first_present(raw, "active", "tradable", "enableOrderBook")),
            "accepting_orders": _normalize_bool_like(_first_present(raw, "acceptingOrders", "accepting_orders")),
        },
    }


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _outcome_label(outcome: Any, external_id: str, index: int) -> str:
    if isinstance(outcome, str):
        return outcome.lower()
    if isinstance(outcome, dict):
        return str(outcome.get("name") or outcome.get("label") or outcome.get("outcome") or "").lower()
    raise ToolError(
        ErrorCode.ADAPTER_PROTOCOL_ERROR,
        "Polymarket adapter outcome elements must be objects or strings",
        details={"external_id": external_id, "outcome_index": index, "outcome_type": type(outcome).__name__},
    )


def _normalize_gamma_json_list_field(raw: dict[str, Any], field: str, external_id: str) -> None:
    """Normalize Gamma list fields that may arrive as JSON-encoded strings."""

    value = raw.get(field)
    if value is None or isinstance(value, list):
        return
    if not isinstance(value, str):
        return
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ToolError(
            ErrorCode.ADAPTER_PROTOCOL_ERROR,
            "Gamma API returned malformed JSON string field",
            details={"external_id": external_id, "field": field},
        ) from exc
    if not isinstance(parsed, list):
        raise ToolError(
            ErrorCode.ADAPTER_PROTOCOL_ERROR,
            "Gamma API JSON string field must decode to a list",
            details={"external_id": external_id, "field": field, "decoded_type": type(parsed).__name__},
        )
    raw[field] = parsed


def _normalize_gamma_market(raw: dict[str, Any], external_id: str) -> dict[str, Any]:
    normalized = dict(raw)
    for field in ("outcomes", "tokens", "clobTokenIds", "clobTokenIDs", "tokenIds", "token_ids"):
        _normalize_gamma_json_list_field(normalized, field, external_id)
    return normalized


def _optional_float(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ToolError(
            ErrorCode.ADAPTER_PROTOCOL_ERROR,
            "Polymarket book field must be numeric",
            details={"field": field, "value": value},
        ) from exc


def _market_cache_hit(state: str | None, metadata_json: str | None, created_at: str | None, *, now: str) -> bool:
    ttl = MARKET_CACHE_TTL_SECONDS.get(state or "")
    if ttl is None:
        return True
    if not ttl:
        return False
    try:
        metadata = json.loads(metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    cached_at = _parse_ts(metadata.get("adapter_cached_at") or created_at)
    now_dt = _parse_ts(now)
    if cached_at is None or now_dt is None:
        return False
    return (now_dt - cached_at).total_seconds() < ttl


def _resolution_source(raw: dict[str, Any], out: dict[str, Any], state: str) -> str:
    """Map a Polymarket market to the venue-agnostic resolution_source taxonomy.

    Taxonomy (markets CHECK, m012): market_contract / oracle_feed / manual_review
    / arbitration. The faithful Polymarket mechanism is the UMA *optimistic
    oracle*: a proposer asserts the outcome by reading the market's stated
    resolution prose, anyone can dispute, and disputes escalate to the UMA DVM
    token-holder vote. There is no purely on-chain, deterministic
    ``market_contract`` resolution on Polymarket — UMA always sits in the loop —
    so ``market_contract`` is the *least* faithful default and was wrong as the
    catch-all (adapter_polymarket.py default pre-trade-trace-v5va).

    Mapping (trade-trace-v5va):

    * ``arbitration`` — the market is disputed: the UMA assertion was challenged
      and escalated to the DVM vote (genuine arbitration), or the venue supplied
      an explicit ``arbitration`` source.
    * ``manual_review`` — ambiguous / unresolvable-by-rule outcomes (the human
      judgement / market-rules-unclear path), or an explicit venue value.
    * ``oracle_feed`` — every other (non-disputed, non-ambiguous) Polymarket
      market: the UMA optimistic oracle is the resolver. This is the faithful
      default and lets ``report.resolution_misreads`` record ``aligned`` for an
      agent that reads a UMA-over-Binance crypto strike as ``oracle_feed``.

    A venue-supplied ``out["resolution_source"]`` that is already a valid enum
    value always wins, so a future Gamma field (or a faithful test fixture)
    overrides the heuristic. Anything else falls through to the mechanism map.
    """

    venue = out.get("resolution_source")
    if isinstance(venue, str) and venue in _RESOLUTION_SOURCE_ENUM:
        return venue
    if raw.get("disputed"):
        return "arbitration"
    if state == "ambiguous" or raw.get("ambiguous") or out.get("status") == "ambiguous":
        return "manual_review"
    return "oracle_feed"


_RESOLUTION_SOURCE_ENUM = frozenset(
    {"market_contract", "oracle_feed", "manual_review", "arbitration"}
)


def _market_payload(raw: dict[str, Any], external_id: str) -> dict[str, Any]:
    raw = _normalize_gamma_market(raw, external_id)
    outcomes = raw.get("outcomes") or raw.get("tokens") or []
    if raw.get("market_type") == "scalar" or raw.get("type") == "scalar" or raw.get("isScalar"):
        raise ToolError(ErrorCode.ADAPTER_PROTOCOL_ERROR, "Polymarket scalar markets are not supported in v0.0.2", details={"external_id": external_id, "market_type": "scalar"})
    if len(outcomes) not in (0, 2):
        raise ToolError(ErrorCode.ADAPTER_PROTOCOL_ERROR, "Polymarket adapter accepts only binary markets in v0.0.2", details={"external_id": external_id, "outcome_count": len(outcomes)})
    labels = [_outcome_label(o, external_id, idx) for idx, o in enumerate(outcomes)]
    if labels and set(labels) != {"yes", "no"}:
        raise ToolError(ErrorCode.ADAPTER_PROTOCOL_ERROR, "Polymarket adapter accepts only YES/NO binary markets", details={"external_id": external_id, "labels": labels})
    state = "open"
    if raw.get("voided") or raw.get("outcome", {}).get("status") == "void":
        state = "voided"
    elif raw.get("ambiguous") or raw.get("outcome", {}).get("status") == "ambiguous":
        state = "ambiguous"
    elif raw.get("resolved") or raw.get("closed") and raw.get("winningOutcome"):
        state = "resolved"
    elif raw.get("closed"):
        state = "closed_for_trading"
    mechanism = "amm" if raw.get("amm") or raw.get("ammCurve") or raw.get("mechanism") == "amm" else "clob"
    out = raw.get("outcome") or {}
    return {
        "source": "polymarket", "external_id": external_id,
        "title": raw.get("title") or raw.get("question"), "question": raw.get("question") or raw.get("title"),
        "url": raw.get("url") or raw.get("marketUrl"), "state": state, "mechanism": mechanism,
        "resolution_source": _resolution_source(raw, out, state),
        "ambiguity_kind": out.get("ambiguity_kind"), "bound_via": "adapter",
        "opened_at": raw.get("startDate") or raw.get("opened_at"), "close_at": raw.get("endDate") or raw.get("close_at"),
        "closed_for_trading_at": raw.get("closed_for_trading_at"), "resolving_at": raw.get("resolving_at"),
        "resolved_at": raw.get("resolved_at") or raw.get("resolvedAt"), "voided_at": raw.get("voided_at"),
        "ambiguous_at": raw.get("ambiguous_at"), "venue_metadata_json": _json(raw),
        "metadata_json": _json({"adapter": "polymarket", **_polymarket_identity_metadata(raw, external_id)}),
    }


def _apply_caller_resolution_rule(payload_meta: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Fill ``resolution_rule.text`` from caller input when the venue has none.

    Polymarket carries the resolution prose in ``description``, not the
    ``resolutionCriteria``/``rules`` keys the adapter reads, so the
    Gamma-derived ``resolution_rule.text`` is almost always null. Without this
    merge a caller's own ``resolution_rule_text`` (the documented n33z
    workaround) is silently dropped on the adapter bind path while the manual
    path preserves it (AX-037). Venue-supplied text always wins; we only fill a
    null/blank text and mark it ``caller_supplied`` so provenance stays honest.
    """

    caller_text = args.get("resolution_rule_text")
    if not caller_text:
        rule_arg = args.get("resolution_rule")
        if isinstance(rule_arg, dict):
            caller_text = rule_arg.get("text")
    if not isinstance(caller_text, str) or not caller_text.strip():
        return payload_meta
    rule = dict(payload_meta.get("resolution_rule") or {})
    existing = rule.get("text")
    if isinstance(existing, str) and existing.strip():
        return payload_meta
    rule["text"] = caller_text.strip()
    rule["provenance"] = "caller_supplied"
    payload_meta["resolution_rule"] = rule
    return payload_meta


def _resolution_rule_text_from_metadata(metadata_json: str | None) -> str | None:
    """Pull the stored ``resolution_rule.text`` out of a market's metadata_json.

    The adapter maps the Gamma ``description`` prose into
    ``metadata_json.resolution_rule.text`` (and the caller-supplied workaround
    fills the same field). This reads it back so the compatibility instrument's
    ``resolution_criteria_text`` carries the venue criterion instead of only the
    question (trade-trace-n33z). Returns ``None`` for absent/blank text so the
    caller can fall back to the question.
    """

    if not metadata_json:
        return None
    try:
        meta = json.loads(metadata_json)
    except (TypeError, ValueError):
        return None
    rule = meta.get("resolution_rule") if isinstance(meta, dict) else None
    text = rule.get("text") if isinstance(rule, dict) else None
    if isinstance(text, str) and text.strip():
        return text.strip()
    return None


def _fetch_market(client: PolymarketClient, external_id: str) -> dict[str, Any]:
    raw = client.gamma_get(f"/markets/{external_id}")
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if isinstance(raw, dict) and "market" in raw and isinstance(raw["market"], dict):
        raw = raw["market"]
    if not isinstance(raw, dict) or not raw:
        raise ToolError(ErrorCode.ADAPTER_PROTOCOL_ERROR, "Gamma API returned no market object", details={"external_id": external_id})
    return raw


def _upsert_market(args: dict[str, Any], ctx: ToolContext, *, refresh_market_id: str | None = None) -> dict[str, Any]:
    with db_for_args(args) as db:
        cfg = load_config(db.connection)
        client = PolymarketClient(cfg)
        try:
            if refresh_market_id:
                row = db.connection.execute("SELECT external_id,state,metadata_json,created_at FROM markets WHERE id=?", (refresh_market_id,)).fetchone()
                if not row:
                    raise ToolError(ErrorCode.NOT_FOUND, "market_id not found", details={"market_id": refresh_market_id})
                external_id = row[0]
                fetch_id = _gamma_request_id(str(external_id), row[2])
                current_now = now_iso()
                if _market_cache_hit(row[1], row[2], row[3], now=current_now):
                    cached = db.connection.execute(
                        f"SELECT {ADAPTER_CACHE_HIT_ROW_SELECT} FROM markets WHERE id=?",
                        (refresh_market_id,),
                    ).fetchone()
                    return adapter_cache_hit_row_dict(cached) | {
                        "cache_hit": True,
                        "state_changed": False,
                    }
            else:
                external_id = require(args, "external_id")
                # First bind: the row does not exist yet, so prefer the
                # caller-supplied gamma_market_id over external_id (mirrors
                # _gamma_request_id for the stored-row paths). This lets a
                # caller bind with a namespaced external_id (e.g.
                # "polymarket:2410562") plus a bare gamma_market_id without the
                # Gamma /markets/{id} lookup 422-ing on the namespaced id.
                gamma_market_id = args.get("gamma_market_id")
                fetch_id = str(gamma_market_id) if gamma_market_id else str(external_id)
            payload = _market_payload(_fetch_market(client, str(fetch_id)), str(external_id))
        except AdapterError as exc:
            raise _tool_error(exc) from exc
        with UnitOfWork(db.connection) as uow:
            existing = uow.conn.execute("SELECT id,state,mechanism,resolution_source,ambiguity_kind FROM markets WHERE source=? AND external_id=?", ("polymarket", str(external_id))).fetchone()
            market_id = refresh_market_id or (existing[0] if existing else args.get("id") or new_id("mkt"))
            created_at = now_iso()
            payload_meta = json.loads(str(payload.get("metadata_json") or "{}"))
            # Bind only: preserve a caller-supplied resolution_rule_text when the
            # Gamma payload carries no rule text (AX-037). Refresh re-syncs venue
            # truth and carries no caller args, so it is left untouched.
            if not refresh_market_id:
                payload_meta = _apply_caller_resolution_rule(payload_meta, args)
            payload["metadata_json"] = _json(payload_meta | {"adapter": "polymarket", "adapter_cached_at": created_at, "cache_ttl_seconds": MARKET_CACHE_TTL_SECONDS.get(str(payload.get("state") or ""))})
            if existing:
                changed = any(existing[i] != payload[k] for i, k in enumerate(("id","state","mechanism","resolution_source","ambiguity_kind")) if k != "id")
                uow.execute("UPDATE markets SET title=?,question=?,url=?,state=?,mechanism=?,resolution_source=?,ambiguity_kind=?,bound_via='adapter',opened_at=?,close_at=?,closed_for_trading_at=?,resolving_at=?,resolved_at=?,voided_at=?,ambiguous_at=?,venue_metadata_json=?,metadata_json=? WHERE id=?", (payload["title"],payload["question"],payload["url"],payload["state"],payload["mechanism"],payload["resolution_source"],payload["ambiguity_kind"],payload["opened_at"],payload["close_at"],payload["closed_for_trading_at"],payload["resolving_at"],payload["resolved_at"],payload["voided_at"],payload["ambiguous_at"],payload["venue_metadata_json"],payload["metadata_json"],market_id))
            else:
                changed = True
                uow.execute("INSERT INTO markets(id,source,external_id,title,question,url,state,mechanism,resolution_source,ambiguity_kind,bound_via,opened_at,close_at,closed_for_trading_at,resolving_at,resolved_at,voided_at,ambiguous_at,venue_metadata_json,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (market_id,"polymarket",str(external_id),payload["title"],payload["question"],payload["url"],payload["state"],payload["mechanism"],payload["resolution_source"],payload["ambiguity_kind"],"adapter",payload["opened_at"],payload["close_at"],payload["closed_for_trading_at"],payload["resolving_at"],payload["resolved_at"],payload["voided_at"],payload["ambiguous_at"],payload["venue_metadata_json"],payload["metadata_json"],created_at,ctx.actor_id))
            # Materialize the compatibility instrument row at bind time so the
            # market_id this tool returns is immediately usable by forecast.add /
            # decision.add, as the docstring promises. The manual bind path does
            # this via _ensure_market_bind_prerequisites; the adapter path
            # previously left it to the first snapshot.fetch, so
            # bind -> forecast.add (no snapshot yet) failed NOT_FOUND (AX-023).
            _ensure_market_instrument(uow, market_id, actor_id=ctx.actor_id)
            out = {"id": market_id, **payload, "state_changed": changed}
            emit_event(uow, event_type="market.refreshed" if refresh_market_id else "market.bound", subject_kind="market", subject_id=market_id, payload=out, actor_id=ctx.actor_id, idempotency_key=args.get("idempotency_key"), ctx=ctx)
            return out


def _market_refresh(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    return _upsert_market(args, ctx, refresh_market_id=require(args, "market_id"))


def _ensure_market_instrument(uow: UnitOfWork, market_id: str, *, actor_id: str) -> None:
    """Ensure public market IDs satisfy legacy snapshot/outcome FKs.

    v0.0.2 public tools take `market_id`, while the existing ledger storage still
    stores snapshots/outcomes under `instrument_id`. Create an idempotent
    compatibility instrument with the same ID as the market before writing those
    tables. This is local-only bookkeeping, not a new public venue/instrument
    surface.
    """

    row = uow.conn.execute(
        "SELECT source, external_id, title, question, close_at, metadata_json FROM markets WHERE id=?",
        (market_id,),
    ).fetchone()
    if row is None:
        raise ToolError(ErrorCode.NOT_FOUND, "market_id not found", details={"market_id": market_id})
    source, external_id, title, question, close_at, metadata_json = row
    created_at = now_iso()
    # Carry the venue resolution prose (description -> resolution_rule.text,
    # set in _polymarket_identity_metadata) into the compatibility instrument's
    # resolution_criteria_text so the criterion travels with the bound market and
    # report surfaces can echo it. Fall back to the question only when no rule
    # text was captured (trade-trace-n33z).
    resolution_criteria_text = _resolution_rule_text_from_metadata(metadata_json) or question
    venue_id = f"venue_{source}"
    uow.execute(
        "INSERT OR IGNORE INTO venues(id,name,kind,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?)",
        (venue_id, str(source), "prediction_market", _json({"source": source}), created_at, actor_id),
    )
    uow.execute(
        "INSERT OR IGNORE INTO instruments(id,venue_id,external_id,symbol,title,asset_class,currency_or_collateral,expiration_or_resolution_at,resolution_criteria_text,contract_multiplier,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            market_id,
            venue_id,
            external_id,
            external_id,
            title or question or external_id or market_id,
            "prediction_market",
            "USDC",
            close_at,
            resolution_criteria_text,
            1.0,
            metadata_json or "{}",
            created_at,
            actor_id,
        ),
    )



def _snapshot_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    bid = raw.get("bestBid") or raw.get("bid")
    ask = raw.get("bestAsk") or raw.get("ask")
    # Sentinel-aware: a legitimate 0.0 price (resolved-NO / dead contract) is
    # falsy, so the old `raw.get("price") or raw.get("lastTradePrice") or ...`
    # chain skipped past a real 0.0 to a later, non-zero field. `_first_present`
    # returns the first key whose value is not None/"" — preserving 0.0
    # (trade-trace-ph4n).
    price = _first_present(raw, "price", "lastTradePrice", "last", "mid")
    bidf = _optional_float(bid, "bestBid")
    askf = _optional_float(ask, "bestAsk")
    pricef = _optional_float(price, "price")
    mid = (bidf + askf) / 2 if bidf is not None and askf is not None else pricef
    # `snapshots.price` is the canonical YES-contract mark the positions
    # projection and PnL reports value open positions against
    # (x-price-convention; projections._latest_snapshot_price). When a live
    # two-sided book exists, the within-book mid is that mark — NOT
    # `lastTradePrice`, which can be a stale print sitting outside the current
    # bid/ask (ax-dogfood AX-027: a live ETH market printed lastTrade=0.49 while
    # the book was 0.41/0.44, marking a 0.44 entry at +PnL when the mid said it
    # was underwater). Anchor `price` to the mid so it agrees with the same
    # snapshot's `mid`/`implied_probability`; `mid` already falls back to the
    # last/raw price when no two-sided book is present.
    # Prefer a real depth/liquidity field; do NOT fall back to the whole raw
    # Gamma payload. Sports and closed/resolved markets often carry none of
    # book/liquidity/orderBook/depth, and the old `or raw` fallback then dumped
    # the entire ~5KB market object (conditionId, clobTokenIds, description, …)
    # into the `liquidity_depth_json` column — semantically wrong and a major
    # size bloat that propagates into snapshot-embedding reports
    # (ax-dogfood AX-031). When no depth field is present, store nothing.
    depth = raw.get("book") or raw.get("liquidity") or raw.get("orderBook") or raw.get("depth")
    metadata = {
        "tick_size": _first_present(raw, "tickSize", "minimumTickSize", "tick_size"),
        "fee_rate_bps": _first_present(raw, "feeRateBps", "fee_rate_bps"),
        "rewards": _first_present(raw, "rewards", "reward", "rewardsDailyRate"),
        "rebates": _first_present(raw, "rebates", "rebate"),
        "tradable": _normalize_bool_like(_first_present(raw, "active", "tradable", "enableOrderBook")),
        "accepting_orders": _normalize_bool_like(_first_present(raw, "acceptingOrders", "accepting_orders")),
        "freshness": {"as_of": _first_present(raw, "asOf", "updatedAt", "timestamp"), "provenance": "polymarket_gamma_payload"},
        "depth_provenance": "caller_or_polymarket_gamma_payload",
    }
    # Sentinel-aware: `impliedProbability` of 0.0 is a real value (resolved-NO /
    # dead YES contract worth $0), but 0.0 is falsy, so the old
    # `raw.get("impliedProbability") or mid` overwrote it with the book mid
    # (e.g. 0.01), misrepresenting the market in calibration/PnL reports. Only
    # fall back to mid when the field is actually absent (trade-trace-ph4n).
    implied = raw.get("impliedProbability")
    implied_probability = implied if implied is not None else mid
    return {"price": mid, "bid": bidf, "ask": askf, "mid": mid, "spread": (askf-bidf) if bidf is not None and askf is not None else None, "volume": raw.get("volume"), "open_interest": raw.get("openInterest"), "implied_probability": implied_probability, "liquidity_depth_json": depth, "metadata_json": metadata}


def _insert_snapshot(args: dict[str, Any], ctx: ToolContext, market_id: str, snap: dict[str, Any], captured_at: str) -> dict[str, Any]:
    seg = common_metadata(args)
    with db_for_args(args) as db:
        with UnitOfWork(db.connection) as uow:
            _ensure_market_instrument(uow, market_id, actor_id=ctx.actor_id)
            sid = args.get("id") or new_id("snp")
            created_at = now_iso()
            caller_meta = json.loads(store_metadata_json(args) or "{}")
            metadata = caller_meta | {"polymarket_snapshot": snap.get("metadata_json") or {}}
            uow.execute("INSERT INTO snapshots(id,instrument_id,captured_at,source,source_url,price,bid,ask,mid,spread,volume,open_interest,implied_probability,liquidity_depth_json,agent_id,model_id,environment,run_id,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (sid,market_id,captured_at,"polymarket",args.get("source_url"),snap.get("price"),snap.get("bid"),snap.get("ask"),snap.get("mid"),snap.get("spread"),snap.get("volume"),snap.get("open_interest"),snap.get("implied_probability"),_json(snap.get("liquidity_depth_json")),seg["agent_id"],seg["model_id"],seg["environment"],seg["run_id"],_json(metadata),created_at,ctx.actor_id))
            emit_event(uow,event_type="snapshot.added",subject_kind="snapshot",subject_id=sid,payload={"id":sid,"instrument_id":market_id,"captured_at":captured_at,"source":"polymarket"},actor_id=ctx.actor_id,idempotency_key=args.get("idempotency_key"),ctx=ctx)
            return {"id": sid, "instrument_id": market_id, "captured_at": captured_at, **snap}


def _gamma_request_id(external_id: str, metadata_json: str | None) -> str:
    """Return the id to use for the Gamma `/markets/{id}` lookup. Prefer the
    explicit `gamma_market_id` captured under `polymarket_identity` at
    market.bind time; fall back to `external_id`. This lets callers bind with
    a namespaced external_id (e.g. ``polymarket:2334107``) without breaking
    snapshot/outcome fetch, which otherwise 422s because Gamma expects the
    bare numeric market id (ax-dogfood AX-009)."""
    try:
        meta = json.loads(metadata_json or "{}")
    except (TypeError, ValueError):
        meta = {}
    identity = meta.get("polymarket_identity") if isinstance(meta, dict) else None
    gid = identity.get("gamma_market_id") if isinstance(identity, dict) else None
    return str(gid) if gid else external_id


def _snapshot_fetch(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    if args.get("at") not in (None, "now"):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "snapshot.fetch supports only at=now in v0.0.2", details={"field":"at"})
    with db_for_args(args) as db:
        client = PolymarketClient(load_config(db.connection))
        market_id = require(args,"market_id")
        row = db.connection.execute("SELECT external_id, metadata_json FROM markets WHERE id=?", (market_id,)).fetchone()
        if not row:
            raise ToolError(ErrorCode.NOT_FOUND,"market_id not found",details={"market_id":market_id})
        try:
            raw = _fetch_market(client, _gamma_request_id(str(row[0]), row[1]))
        except AdapterError as exc:
            raise _tool_error(exc) from exc
    return _insert_snapshot(args, ctx, market_id, _snapshot_from_raw(raw if isinstance(raw, dict) else {}), now_iso())


def _snapshot_fetch_series(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    # v0.0.2 adapter primitive stores returned points; Gamma path is intentionally generic for fixture-backed tests.
    with db_for_args(args) as db:
        client = PolymarketClient(load_config(db.connection))
        market_id=require(args,"market_id")
        row = db.connection.execute("SELECT external_id, metadata_json FROM markets WHERE id=?", (market_id,)).fetchone()
        if not row:
            raise ToolError(ErrorCode.NOT_FOUND,"market_id not found",details={"market_id":market_id})
        try:
            raw = client.gamma_get(f"/markets/{_gamma_request_id(str(row[0]), row[1])}/prices?from={require(args,'from')}&to={require(args,'to')}")
        except AdapterError as exc:
            raise _tool_error(exc) from exc
    points = raw.get("points", raw) if isinstance(raw, dict) else raw
    items = []
    # snapshot.fetch_series is a retryable write whose semantic identity is not
    # in TOOL_PRIMARY_EVENT_TYPE, so — exactly like snapshot.fetch — the
    # dispatcher requires a caller-supplied idempotency_key (MISSING_IDEMPOTENCY
    # otherwise) unless the caller opts into at-least-once via
    # _allow_no_idempotency. Derive a per-point key from the REAL base key so
    # each stored snapshot row is independently idempotent and two distinct
    # series calls do NOT collide on a constant literal default. When no base
    # key is present (the _allow_no_idempotency opt-out path), pass None
    # through per point — matching snapshot.fetch, which forwards
    # args.get("idempotency_key") verbatim (trade-trace-xtdo).
    base_key = args.get("idempotency_key")
    for idx, point in enumerate(points or []):
        item_args = dict(args)
        item_args["idempotency_key"] = f"{base_key}:{idx}" if base_key else None
        items.append(
            _insert_snapshot(
                item_args,
                ctx,
                market_id,
                _snapshot_from_raw(point),
                point.get("captured_at") or point.get("timestamp") or now_iso(),
            )
        )
    return {"items": items, "count": len(items)}


def _candidate_close_at(raw: dict[str, Any]) -> str | None:
    return raw.get("endDate") or raw.get("end_date") or raw.get("close_at") or raw.get("closeTime")


def _market_search_candidate(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Project a Gamma market object into a binary-market discovery candidate.

    Returns ``None`` for markets the v0.0.2 adapter cannot bind (non-binary,
    non-YES/NO, or scalar), so callers only ever see markets they could hand
    straight to ``market.bind`` / ``market.refresh`` without an out-of-band
    Gamma lookup. This is read-only: no normalization side effects, no writes.
    """

    if not isinstance(raw, dict):
        return None
    if raw.get("market_type") == "scalar" or raw.get("type") == "scalar" or raw.get("isScalar"):
        return None
    gamma_market_id = _first_present(raw, "id", "marketId", "gammaMarketId")
    if gamma_market_id is None:
        return None
    external_id = str(gamma_market_id)
    try:
        normalized = _normalize_gamma_market(raw, external_id)
    except ToolError:
        return None
    raw_outcomes = normalized.get("outcomes") or normalized.get("tokens") or []
    if len(raw_outcomes) != 2:
        return None
    try:
        labels = [_outcome_label(o, external_id, idx) for idx, o in enumerate(raw_outcomes)]
    except ToolError:
        return None
    if set(labels) != {"yes", "no"}:
        return None
    return {
        "external_id": external_id,
        "gamma_market_id": external_id,
        "slug": _first_present(raw, "slug", "marketSlug"),
        "question": raw.get("question") or raw.get("title"),
        # Surface the venue resolution prose at discovery time so a bot can tell
        # what YES actually resolves on before binding — e.g. distinguishing a
        # literal P(event) market from one whose price reflects release-timing
        # mechanics — instead of having to bind first to read it
        # (trade-trace-n33z). Falls back to the legacy keys if present.
        "description": _first_present(
            raw, "description", "resolutionCriteria", "rules"
        ),
        "outcomes": labels,
        "close_at": _candidate_close_at(raw),
        "event_slug": _first_present(raw, "eventSlug", "event_slug"),
        "active": _normalize_bool_like(_first_present(raw, "active", "enableOrderBook")),
        "closed": _normalize_bool_like(raw.get("closed")),
    }


def _extract_market_rows(raw: Any) -> list[Any]:
    """Pull the market list out of a Gamma /markets response (list or wrapped)."""
    if isinstance(raw, dict):
        return raw.get("markets") or raw.get("data") or raw.get("results") or []
    if isinstance(raw, list):
        return raw
    return []


def _gamma_public_search_rows(client: PolymarketClient, query: str, limit: int) -> list[Any]:
    """Flatten Gamma /public-search results into individual market rows.

    /public-search is Gamma's real free-text search endpoint (unlike /markets,
    whose `q` param is ignored). Its payload is event-centric: a top-level
    ``events`` array whose entries carry a nested ``markets`` array. Flatten
    those nested markets so the existing candidate projection/binary filter can
    consume them unchanged (trade-trace-yz3q).
    """
    raw = client.gamma_get(f"/public-search?q={quote(query, safe='')}&limit_per_type={limit}")
    rows: list[Any] = []
    if isinstance(raw, dict):
        for event in raw.get("events") or []:
            if isinstance(event, dict):
                rows.extend(m for m in (event.get("markets") or []) if isinstance(m, dict))
        # Some deployments may also surface markets at the top level; include
        # them defensively so we never miss a bindable candidate.
        rows.extend(m for m in (raw.get("markets") or []) if isinstance(m, dict))
    elif isinstance(raw, list):
        rows.extend(m for m in raw if isinstance(m, dict))
    return rows


def _market_search(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Read-only live discovery of bindable binary markets via the Gamma list API.

    Unlike market.bind/refresh/snapshot.fetch (which all require an already-known
    external_id) and market.find_similar (which needs an already-bound market),
    this surfaces candidate markets a bot can forecast on without any out-of-band
    Gamma curl. No DB writes, no advice, no trade execution (bead trade-trace-663l).
    """

    limit = args.get("limit", 20)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "limit must be an integer between 1 and 100",
            details={"field": "limit", "value": args.get("limit")},
        )
    query = args.get("query")
    if query is not None and not isinstance(query, str):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "query must be a string when supplied",
            details={"field": "query"},
        )
    closed = bool(args.get("closed", False))
    # Over-fetch from Gamma so binary-only filtering still yields up to `limit`
    # bindable candidates; cap the upstream request to keep it bounded.
    fetch_limit = min(100, max(limit * 5, limit))
    with db_for_args(args) as db:
        client = PolymarketClient(load_config(db.connection))
        try:
            if query:
                # Gamma's /markets list endpoint has no free-text search and
                # silently ignores an unknown `q` param, so a query there is a
                # no-op (trade-trace-yz3q). The real search endpoint is
                # /public-search, which returns an event-centric shape; flatten
                # events->markets and filter `closed` client-side below.
                rows = _gamma_public_search_rows(client, query, fetch_limit)
            else:
                params = [f"limit={fetch_limit}", f"closed={'true' if closed else 'false'}"]
                if not closed:
                    params.append("active=true")
                raw = client.gamma_get(f"/markets?{'&'.join(params)}")
                rows = _extract_market_rows(raw)
        except AdapterError as exc:
            raise _tool_error(exc) from exc
    candidates: list[dict[str, Any]] = []
    for row in rows:
        candidate = _market_search_candidate(row) if isinstance(row, dict) else None
        if candidate is None:
            continue
        # The /markets path filters closed markets upstream via query params;
        # /public-search does not, so drop closed candidates here unless the
        # caller opted into closed markets. Keeps both paths consistent.
        if not closed and candidate.get("closed"):
            continue
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    # Gamma /public-search matches ALL query terms (conjunctive): a market must
    # contain every word, so a natural multi-keyword query like
    # "bitcoin ethereum price" returns zero even though bitcoin- and
    # ethereum-markets both exist. Surface a point-of-failure nudge so a bot
    # recovers instead of dead-ending on a silent empty result.
    search_hint: str | None = None
    if query and not candidates:
        if len(query.split()) > 1:
            search_hint = (
                "Zero candidates: Gamma /public-search matches ALL query terms "
                "(conjunctive), so a multi-word query often over-specifies. Retry "
                "with fewer / more distinct keywords — one entity or topic at a "
                "time (e.g. 'bitcoin' or 'fed rate', not 'bitcoin ethereum price')."
            )
        else:
            # AX dogfood AX-035: a single-term zero result previously returned a
            # null hint, leaving a bot unable to tell a genuine no-match from a
            # silent search failure (the AX-019 /markets no-op misread). The
            # search did run; the term just matches no live market text.
            search_hint = (
                "Zero candidates: no open market matched this term. Gamma "
                "/public-search is a literal term match over live market text, "
                "so the term may not appear in any current market. Try a "
                "different or broader single keyword, or set closed=true to "
                "include resolved markets."
            )
    return {
        "source": "polymarket",
        "query": query,
        "closed": closed,
        "count": len(candidates),
        "candidates": candidates,
        "search_hint": search_hint,
        "no_advice_boundary": {
            "external_fetch_performed": True,
            "db_write_performed": False,
            "trade_execution_performed": False,
            "advice_generated": False,
        },
    }


def _outcome_fetch_existing(conn: Any, market_id: str) -> Any:
    """Return an existing polymarket outcome id for ``market_id``, or None.

    The (instrument_id, 'polymarket') pair is the de-facto uniqueness key for
    an outcome.fetch ingestion; this helper centralises the lookup so the
    pre-lock fast path and the inside-transaction re-check stay identical.
    """

    return conn.execute(
        "SELECT id FROM outcomes WHERE instrument_id=? AND source='polymarket'",
        (market_id,),
    ).fetchone()


def _outcome_fetch(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    # trade-trace-4kbk: the existence check and the INSERT formerly ran in two
    # separate db_for_args connections (and two separate UnitOfWork
    # transactions). Between the pre-RPC SELECT and the post-RPC INSERT, a
    # concurrent outcome.fetch for the same market could insert a polymarket
    # outcome row, so the second caller's INSERT produced a DUPLICATE row for
    # the (instrument_id, 'polymarket') pair (the outcomes table has no UNIQUE
    # constraint on that pair), yielding ambiguous outcome state that
    # signal.scan / resolved_final NOT EXISTS checks read incorrectly.
    #
    # Fix: keep a single db connection for the whole handler, and re-check
    # existence *inside* the same UnitOfWork that performs the INSERT. The
    # UnitOfWork opens with BEGIN IMMEDIATE, which acquires the SQLite writer
    # lock up front, so two concurrent writers are serialized: the second one
    # blocks at BEGIN IMMEDIATE until the first commits, then its
    # inside-transaction re-check sees the now-existing row and returns the
    # idempotent replay instead of inserting a duplicate. The slow RPC fetch
    # stays OUTSIDE the writer lock so it does not serialize unrelated writers.
    with db_for_args(args) as db:
        conn = db.connection
        client = PolymarketClient(load_config(conn))
        market_id = require(args, "market_id")
        row = conn.execute(
            "SELECT venue_metadata_json FROM markets WHERE id=?", (market_id,)
        ).fetchone()
        if not row:
            raise ToolError(ErrorCode.NOT_FOUND, "market_id not found", details={"market_id": market_id})
        meta = json.loads(row[0] or "{}")
        out = meta.get("outcome") or {}
        # Fast path: if the outcome already exists, skip the RPC round-trip
        # entirely. This is an optimization, not the correctness guarantee —
        # the authoritative re-check happens inside the UnitOfWork below.
        existing = _outcome_fetch_existing(conn, market_id)
        if existing:
            return {"id": existing[0], "instrument_id": market_id, "idempotent_replay": True, "cache_hit": True}
        try:
            tx_hash = out.get("tx_hash") or meta.get("resolution_tx")
            rpc = client.polygon_rpc("eth_getTransactionReceipt", [tx_hash]) if tx_hash else client.check_resolution_available()
        except AdapterError as exc:
            raise _outcome_fetch_error(exc) from exc
        status = out.get("status") or ("void" if meta.get("voided") else "resolved_final")
        label = out.get("label") or meta.get("winningOutcome") or meta.get("winning_outcome") or "unknown"
        with UnitOfWork(conn) as uow:
            # Authoritative TOCTOU-safe re-check: BEGIN IMMEDIATE serialized us
            # against any concurrent writer, so a row that appeared while we
            # were doing the RPC fetch is visible here. Return the idempotent
            # replay instead of inserting a second polymarket outcome row.
            existing = _outcome_fetch_existing(conn, market_id)
            if existing:
                return {"id": existing[0], "instrument_id": market_id, "idempotent_replay": True, "cache_hit": True}
            _ensure_market_instrument(uow, market_id, actor_id=ctx.actor_id)
            oid = args.get("id") or new_id("out")
            created_at = now_iso()
            metadata = _json({"polygon_rpc": rpc, "tx_hash": tx_hash})
            uow.execute("INSERT INTO outcomes(id,instrument_id,resolved_at,outcome_label,outcome_value,status,source,confidence,agent_id,model_id,environment,run_id,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (oid,market_id,out.get("resolved_at") or now_iso(),label,out.get("value"),status,"polymarket",out.get("confidence"),None,None,None,None,metadata,created_at,ctx.actor_id))
            emit_event(uow,event_type="outcome.recorded",subject_kind="outcome",subject_id=oid,payload={"id":oid,"instrument_id":market_id,"status":status,"outcome_label":label},actor_id=ctx.actor_id,idempotency_key=args.get("idempotency_key"),ctx=ctx)
            return {"id":oid,"instrument_id":market_id,"status":status,"outcome_label":label,"metadata_json":metadata}


def register_adapter_polymarket_tools(registry: ToolRegistry) -> None:
    # market.refresh / snapshot.fetch / outcome.fetch are retryable writes whose
    # semantic identity is NOT in the auto-derivation registry
    # (TOOL_PRIMARY_EVENT_TYPE), so the dispatcher cannot synthesize an
    # idempotency_key for them — a call that omits it returns
    # MISSING_IDEMPOTENCY_KEY. The advertised schema must therefore mark
    # idempotency_key REQUIRED, not optional, so schema text and dispatcher
    # enforcement agree (bead trade-trace-2cmb). `at` stays optional because the
    # handler defaults it ("now").
    registry.register("market.refresh", _market_refresh, is_write=True, example_minimal={"market_id":"mkt_...","idempotency_key":"00000000-0000-4000-8000-marketrefresh01"})
    registry.register("snapshot.fetch", _snapshot_fetch, is_write=True, example_minimal={"market_id":"mkt_...","at":"now","idempotency_key":"00000000-0000-4000-8000-snapshotfetch01"}, optional_keys=("at",))
    # snapshot.fetch_series has the SAME retryable-write idempotency contract as
    # snapshot.fetch above: it is is_write=True and absent from
    # TOOL_PRIMARY_EVENT_TYPE, so the dispatcher rejects calls without an
    # explicit idempotency_key (MISSING_IDEMPOTENCY_KEY). Advertise the key in
    # the derived schema (via example_minimal) so the schema matches enforcement
    # — otherwise a schema-trusting bot omits it and gets a confusing rejection
    # (bead trade-trace-xtdo; same gap snapshot.fetch closed in trade-trace-2cmb).
    registry.register("snapshot.fetch_series", _snapshot_fetch_series, is_write=True, example_minimal={"market_id":"mkt_...","from":"2026-01-01T00:00:00Z","to":"2026-01-02T00:00:00Z","idempotency_key":"00000000-0000-4000-8000-snapfetchseries1"})
    registry.register("outcome.fetch", _outcome_fetch, is_write=True, example_minimal={"market_id":"mkt_...","idempotency_key":"00000000-0000-4000-8000-outcomefetch001"})
    # Live read-only discovery: find bindable binary markets WITHOUT a pre-known
    # external_id or an already-bound market (bead trade-trace-663l). Adapter-only;
    # fails closed with ADAPTER_DISABLED when network.polymarket.enabled is false.
    registry.register(
        "market.search",
        _market_search,
        is_write=False,
        example_minimal={"query": "election", "limit": 20, "closed": False},
        optional_keys=("query", "limit", "closed"),
        description=(
            "Discover candidate binary (YES/NO) Polymarket markets to bind/forecast on. "
            "Read-only live Gamma list query: returns external_id/gamma_market_id, slug, "
            "question, outcomes, and close time. No DB writes, no advice, no trade execution. "
            "Adapter-only: fails closed with ADAPTER_DISABLED when the adapter is off. "
            "A query is matched against Gamma's free-text search conjunctively (ALL "
            "terms must appear in one market), so prefer short single-topic queries; "
            "a multi-word query that returns zero is usually over-specified and "
            "carries a search_hint suggesting how to relax it. "
            "Hand a returned external_id straight to market.bind / market.refresh."
        ),
        usage_summary="Find bindable binary markets live without a pre-known external_id.",
        examples=("tt market search --query election --limit 20",),
        common_failures=("ADAPTER_DISABLED", "ADAPTER_TIMEOUT", "EXTERNAL_API_ERROR"),
        next_actions=("Pass a candidate external_id to market.bind, then snapshot.fetch / forecast.add.",),
    )
