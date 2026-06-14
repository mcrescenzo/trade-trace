"""Structural/analogical recall over markets (trade-trace-4kec.13).

Lexical `memory.recall` (FTS5) only fires when markets share words. This sibling
retrieves STRUCTURALLY similar markets — same mechanism, resolution source,
ambiguity posture, liquidity/spread band, longshot shape — so continuity helps
even when two markets share no keywords ("same mechanism, ambiguous-resolution,
thin-liquidity longshot").

It is deterministic and uses only locally-stored market/snapshot features: no
embeddings call, no remote provider. It therefore respects the local-only
embeddings posture (none|local) by construction — the structural score is
identical whether or not a local embeddings provider is configured.
"""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.reports.buckets import liquidity_bucket, spread_bucket
from trade_trace.tools._helpers import db_for_args, require
from trade_trace.tools.errors import ToolError

_AMBIGUOUS_SOURCES = {"manual_review", "arbitration"}
_LONGSHOT_LO = 0.15
_LONGSHOT_HI = 0.85


def _latest_snapshot(conn: Any, instrument_id: str) -> tuple[float | None, float | None, float | None]:
    row = conn.execute(
        "SELECT spread, volume, COALESCE(implied_probability, mid, price) "
        "FROM snapshots WHERE instrument_id = ? "
        "ORDER BY captured_at DESC, created_at DESC, id DESC LIMIT 1",
        (instrument_id,),
    ).fetchone()
    if row is None:
        return None, None, None
    return row[0], row[1], row[2]


def _fingerprint(conn: Any, market_row: tuple) -> dict[str, Any]:
    instrument_id, mechanism, resolution_source, ambiguity_kind = market_row
    spread, volume, prob = _latest_snapshot(conn, instrument_id)
    ambiguous = ambiguity_kind is not None or resolution_source in _AMBIGUOUS_SOURCES
    longshot: bool | None
    if prob is None:
        longshot = None
    else:
        longshot = float(prob) < _LONGSHOT_LO or float(prob) > _LONGSHOT_HI
    return {
        "mechanism": mechanism,
        "resolution_source": resolution_source,
        "ambiguous": ambiguous,
        "liquidity_bucket": liquidity_bucket(float(volume)) if volume is not None else None,
        "spread_bucket": (
            spread_bucket(float(spread), float(prob))
            if spread is not None and prob is not None
            else None
        ),
        "longshot": longshot,
    }


_DIMENSIONS = ("mechanism", "resolution_source", "ambiguous", "liquidity_bucket", "spread_bucket", "longshot")


def _similarity(ref: dict[str, Any], cand: dict[str, Any]) -> tuple[float | None, list[str], int]:
    comparable = 0
    matched: list[str] = []
    for dim in _DIMENSIONS:
        a, b = ref[dim], cand[dim]
        if a is None or b is None:
            continue
        comparable += 1
        if a == b:
            matched.append(dim)
    if comparable == 0:
        return None, matched, 0
    return len(matched) / comparable, matched, comparable


def _market_find_similar(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    instrument_id = require(args, "instrument_id")
    limit = min(int(args.get("limit", 10)), 100)
    min_score = float(args.get("min_score", 0.0))
    with db_for_args(args) as db:
        conn = db.connection
        ref_row = conn.execute(
            "SELECT id, mechanism, resolution_source, ambiguity_kind FROM markets WHERE id = ?",
            (instrument_id,),
        ).fetchone()
        if ref_row is None:
            raise ToolError(ErrorCode.NOT_FOUND, "instrument_id is not a bound market", details={"instrument_id": instrument_id})
        ref_fp = _fingerprint(conn, ref_row)
        candidates = conn.execute(
            "SELECT id, mechanism, resolution_source, ambiguity_kind, title FROM markets WHERE id != ?",
            (instrument_id,),
        ).fetchall()
        scored: list[dict[str, Any]] = []
        for cid, mech, rsrc, amb, title in candidates:
            score, matched, comparable = _similarity(ref_fp, _fingerprint(conn, (cid, mech, rsrc, amb)))
            if score is None or score < min_score:
                continue
            scored.append({
                "instrument_id": cid,
                "title": title,
                "score": round(score, 6),
                "matched_dimensions": matched,
                # Denominator behind `score` (= len(matched_dimensions)/comparable):
                # the number of dimensions where both markets had a non-null value.
                # A snapshot-less candidate is comparable on fewer dims, so a 1.0
                # score over 3 comparable dims is weaker evidence than 1.0 over 6.
                "comparable_dimensions": comparable,
            })
        # Rank by score, then by coverage so a fuller, more-corroborated match
        # outranks a sparse coincidence that ties on the comparable-fraction score.
        scored.sort(key=lambda r: (-r["score"], -r["comparable_dimensions"], r["instrument_id"]))
        return {
            "reference_instrument_id": instrument_id,
            "reference_fingerprint": ref_fp,
            "dimensions": list(_DIMENSIONS),
            "matches": scored[:limit],
            "count": min(len(scored), limit),
            "retrieval_kind": "structural_similarity",
            "embeddings_used": False,
            "caveats": [
                "Structural similarity over locally-stored market features only "
                "(no embeddings call, no remote provider); complements lexical "
                "memory.recall. Not trade advice or a signal.",
            ],
        }


def register_market_similarity_tools(registry: ToolRegistry) -> None:
    registry.register(
        "market.find_similar",
        _market_find_similar,
        description=(
            "Retrieve structurally/analogically similar markets to a reference "
            "market — same mechanism, resolution source, ambiguity posture, "
            "liquidity/spread band, and longshot shape — even when they share no "
            "keywords with it. Deterministic; uses only local market/snapshot "
            "features (no embeddings call, no remote provider), so it respects the "
            "local-only embeddings posture. Complements lexical memory.recall."
        ),
        example_minimal={"instrument_id": "ins_INSTRUMENT_ID_HERE"},
        json_schema={
            "type": "object",
            "properties": {
                "instrument_id": {"type": "string", "description": "Reference bound market to find analogues for."},
                "limit": {"type": "integer"},
                "min_score": {"type": "number", "minimum": 0, "maximum": 1},
                "home": {"type": "string"},
            },
            "required": ["instrument_id"],
        },
    )


__all__ = ["register_market_similarity_tools"]
