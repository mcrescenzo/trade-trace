"""`signal.*` tool surface per docs/architecture/reports.md + trade-trace-2ry.

Signals are emitted lazily — only when an agent explicitly invokes
`signal.scan` or `report.coach`. There is no background daemon. This file
ships:

- `signal.scan(home, *, kinds?)` — walks the DB once, detecting the open-
  enum kinds the M2 surface knows about, and appends one signals row per
  detected condition. Idempotent over the same DB state if `dedupe=True`
  (the default for the M2 scan).

- `_emit_signal(conn, ...)` — internal helper invoked by the scan and (in
  a separate bead) by `report.coach`. Wraps the INSERT so the actor_id
  default (`system:report.coach`) and the canonical timestamp are pinned
  in one place.

The kinds the scan detects in M2:

- `unscored_forecast`: any binary forecast past its `resolution_at` with
  no `resolved_final` (non-superseded) outcome on its instrument.

Additional kinds (`calibration_drift`, `stale_watch`,
`sample_size_warning`, `override_outcome_*`, `risk_data_missing`) land
incrementally with their respective report implementations
(trade-trace-77z and trade-trace-2g2).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.tools._helpers import new_id, now_iso, open_db_for_args
from trade_trace.tools.errors import ToolError

# The signals.kind open enum, mirrored from storage/policy.py for ergonomics.
# Adding a value here is non-breaking (it's an open enum); the scan emits
# only the subset it knows how to detect.
KNOWN_KINDS: frozenset[str] = frozenset(
    {
        "calibration_drift",
        "override_outcome_negative",
        "override_outcome_positive",
        "stale_watch",
        "unscored_forecast",
        "sample_size_warning",
        "risk_data_missing",
    }
)

SCANNABLE_KINDS: frozenset[str] = frozenset({"unscored_forecast"})
"""Kinds the M2 scan knows how to detect. Future reports/coach extend this."""

DEFAULT_ACTOR_ID = "system:report.coach"


def _emit_signal(
    conn: sqlite3.Connection,
    *,
    kind: str,
    severity: str,
    body: str | None = None,
    meta: dict[str, Any] | None = None,
    related_refs: list[dict[str, Any]] | None = None,
    expires_at: str | None = None,
    actor_id: str = DEFAULT_ACTOR_ID,
    created_at: str | None = None,
) -> str:
    """Append one signals row. Returns the new signal id.

    Caller is responsible for transaction/UnitOfWork wrapping — `_emit_signal`
    just does the INSERT so the scan can batch many emissions in one
    transaction."""

    signal_id = new_id("sig")
    conn.execute(
        "INSERT INTO signals(id, kind, severity, body, meta_json, "
        "related_refs_json, created_at, expires_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            signal_id,
            kind,
            severity,
            body,
            json.dumps(meta or {}, sort_keys=True, separators=(",", ":"), default=str),
            json.dumps(related_refs or [], sort_keys=True, separators=(",", ":"), default=str),
            created_at or now_iso(),
            expires_at,
            actor_id,
        ),
    )
    return signal_id


def _detect_unscored_forecasts(
    conn: sqlite3.Connection, *, now_iso_str: str
) -> list[dict[str, Any]]:
    """Return forecasts past their `resolution_at` whose instrument has no
    `resolved_final` (non-superseded) outcome. One signal row per forecast.

    Mirrors `resolve.pending`'s discovery query but emits to signals
    instead of returning a list, so an agent that polls `signal.scan`
    weekly gets an auditable record of every unscored forecast they
    haven't acted on."""

    cur = conn.execute(
        """
        SELECT f.id, f.thesis_id, f.resolution_at, t.instrument_id
        FROM forecasts f
        JOIN theses t ON t.id = f.thesis_id
        WHERE f.resolution_at IS NOT NULL
          AND f.resolution_at < ?
          AND f.scoring_state = 'pending'
          AND f.scoring_support = 'supported'
          AND NOT EXISTS (
            SELECT 1 FROM outcomes o
            WHERE o.instrument_id = t.instrument_id
              AND o.status = 'resolved_final'
              AND NOT EXISTS (
                SELECT 1 FROM edges e
                WHERE e.source_kind = 'outcome' AND e.target_kind = 'outcome'
                  AND e.edge_type = 'supersedes' AND e.target_id = o.id
              )
          )
        ORDER BY f.resolution_at ASC, f.id ASC
        """,
        (now_iso_str,),
    )
    return [
        {
            "forecast_id": row[0],
            "thesis_id": row[1],
            "resolution_at": row[2],
            "instrument_id": row[3],
        }
        for row in cur.fetchall()
    ]


def _already_signaled(
    conn: sqlite3.Connection, *, kind: str, ref_key: str, ref_id: str
) -> bool:
    """Lookup whether a signal with `kind` already references `(ref_key, ref_id)`.

    Used by the scan's idempotency guard so re-running `signal.scan`
    on the same DB state does not append duplicate rows.

    Per bead trade-trace-c2h / DEBT-020: the previous implementation
    used a substring `LIKE '%"<key>":"<id>"%'` against the raw
    `related_refs_json` blob. That matched only one specific JSON
    formatting (compact, value-quoted, no extra whitespace) — a
    future producer that wrote a re-ordered key set or any
    whitespace would silently bypass the dedupe. The query now
    uses SQLite's `json_extract` so the comparison is structural
    against the JSON value regardless of formatting.
    """

    # `related_refs_json` is a JSON array of single-key dicts like
    # `[{"forecast_id": "fid_123"}, {"instrument_id": "..."}]`. The
    # dedupe check asks "does any element have key=ref_key with
    # value=ref_id?". We walk the array via `json_each` and pull
    # `json_extract(value, $.<ref_key>)` per element so the match is
    # structural regardless of JSON whitespace or sibling-key
    # ordering.
    cur = conn.execute(
        "SELECT s.id FROM signals s, json_each(s.related_refs_json) e "
        "WHERE s.kind = ? AND json_extract(e.value, ?) = ? LIMIT 1",
        (kind, f"$.{ref_key}", ref_id),
    )
    return cur.fetchone() is not None


def _signal_scan(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`signal.scan` — explicit, on-demand scan that appends signal rows
    for every condition the M2 surface knows how to detect.

    Args:
      `kinds`: optional list of kinds to scan. Defaults to all
      `SCANNABLE_KINDS`. Unknown kinds raise VALIDATION_ERROR.
      `dedupe`: bool (default True). When true, skip emissions whose
      `related_refs_json` already exists in the signals table for the
      same kind. Pass `false` to force a fresh emission (e.g. after
      manual cleanup).
    """

    kinds_arg = args.get("kinds")
    if kinds_arg is None:
        kinds = SCANNABLE_KINDS
    else:
        if not isinstance(kinds_arg, list):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "kinds must be a list of strings",
                details={"field": "kinds", "value": kinds_arg},
            )
        unknown = [k for k in kinds_arg if k not in KNOWN_KINDS]
        if unknown:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"unknown signal kinds: {unknown!r}",
                details={
                    "field": "kinds", "unknown": unknown,
                    "known": sorted(KNOWN_KINDS),
                },
            )
        not_scannable = [k for k in kinds_arg if k not in SCANNABLE_KINDS]
        if not_scannable:
            raise ToolError(
                ErrorCode.UNSUPPORTED_CAPABILITY,
                "the M2 scan does not yet emit these kinds; they land with "
                "reports and the coach (see trade-trace-77z, trade-trace-2g2)",
                details={"field": "kinds", "not_scannable": not_scannable,
                         "scannable_now": sorted(SCANNABLE_KINDS)},
            )
        kinds = frozenset(kinds_arg)

    dedupe = bool(args.get("dedupe", True))
    db = open_db_for_args(args)
    emitted: list[dict[str, Any]] = []
    try:
        now_str = now_iso()
        with db.transaction():
            conn = db.connection
            if "unscored_forecast" in kinds:
                for detection in _detect_unscored_forecasts(conn, now_iso_str=now_str):
                    fid = detection["forecast_id"]
                    if dedupe and _already_signaled(
                        conn, kind="unscored_forecast", ref_key="forecast_id", ref_id=fid
                    ):
                        continue
                    sig_id = _emit_signal(
                        conn,
                        kind="unscored_forecast",
                        severity="warn",
                        body=(
                            f"forecast {fid} is past resolution_at "
                            f"({detection['resolution_at']}) but no resolved_final "
                            f"outcome exists on its instrument."
                        ),
                        meta={
                            "resolution_at": detection["resolution_at"],
                            "thesis_id": detection["thesis_id"],
                        },
                        related_refs=[
                            {"forecast_id": fid},
                            {"instrument_id": detection["instrument_id"]},
                        ],
                        actor_id=DEFAULT_ACTOR_ID,
                        created_at=now_str,
                    )
                    emitted.append({
                        "id": sig_id,
                        "kind": "unscored_forecast",
                        "severity": "warn",
                        "forecast_id": fid,
                    })
    finally:
        db.close()

    return {
        "kinds_scanned": sorted(kinds),
        "emitted_count": len(emitted),
        "emitted": emitted,
        "scanned_at": now_str,
    }


def register_signal_tools(registry: ToolRegistry) -> None:
    """Register `signal.*` tools on the supplied registry."""

    registry.register(
        "signal.scan",
        _signal_scan,
        description=(
            "Explicit, on-demand scan that appends signals.kind=* rows for "
            "every condition the M2 surface detects. Lazy: this is the ONLY "
            "way signals appear (besides report.coach in trade-trace-2g2). "
            "No background daemon exists. Use `kinds=[...]` to restrict, "
            "`dedupe=false` to force re-emission."
        ),
    )
