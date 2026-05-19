"""Console page handlers (trade-trace-1kkv.6/.7/.8/.9).

Each `<page>_context()` function takes a read-only DB connection
and the request's query args (cursor + filters), runs the
read-only endpoint queries, and returns the rendering context for
the corresponding Jinja template. The handlers are pure Python —
they don't import FastAPI/Jinja, which lets tests verify the
context shape without the `[console]` extra installed.

Empty-state onboarding (per .6) is encoded as a top-level
`empty_state` key in the context dict: when present, the
template renders the CLI-hint affordance instead of an empty
table.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trade_trace.console import endpoints


def overview_context(
    conn: sqlite3.Connection,
    *,
    db_path: Path,
) -> dict[str, Any]:
    status = endpoints.status(conn, db_path=db_path)
    is_empty = status["row_counts"].get("events", 0) == 0
    return {
        "page_title": "Overview",
        "generated_at": _iso_now(),
        "db_path": status["db_path"],
        "schema_version": status["schema_version"],
        "last_event_at": status["last_event_at"],
        "row_counts": status["row_counts"],
        "lazy_write_handlers_blocked": status["lazy_write_handlers_blocked"],
        "logs_deferred": True,
        "empty_state": {
            "title": "No journal data yet.",
            "next_steps": [
                ("Initialize a journal", "tt journal init"),
                ("Seed with the M0 fixture", "tt journal fixture-seed --target=mvp-eval"),
            ],
        }
        if is_empty
        else None,
    }


def journal_context(
    conn: sqlite3.Connection,
    *,
    cursor: str | None,
    limit: int,
    filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    page = endpoints.journal_events(conn, cursor=cursor, limit=limit)
    return {
        "page_title": "Journal",
        "generated_at": _iso_now(),
        "rows": page.rows,
        "next_cursor": page.next_cursor,
        "limit": page.limit,
        "filters": filters or {},
        "empty_state": {
            "title": "No events recorded yet.",
            "next_steps": [
                ("Seed the M0 fixture", "tt journal fixture-seed --target=mvp-eval"),
                ("Write a memory node", "tt memory retain --node-type=observation --body='...'"),
            ],
        }
        if not page.rows
        else None,
    }


def decisions_context(
    conn: sqlite3.Connection,
    *,
    cursor: str | None,
    limit: int,
    filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    page = endpoints.decisions_list(conn, cursor=cursor, limit=limit)
    return {
        "page_title": "Decisions",
        "generated_at": _iso_now(),
        "rows": page.rows,
        "next_cursor": page.next_cursor,
        "limit": page.limit,
        "filters": filters or {},
        "empty_state": {
            "title": "No decisions recorded yet.",
            "next_steps": [
                ("Record a paper-entry decision", "tt decision add --type=paper_enter ..."),
                ("Record a hold decision", "tt decision add --type=hold ..."),
            ],
        }
        if not page.rows
        else None,
    }


def decision_detail_context(
    conn: sqlite3.Connection, *, decision_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, type, instrument_id, thesis_id, side, quantity, price, "
        "reason, created_at FROM decisions WHERE id = ?",
        (decision_id,),
    ).fetchone()
    if row is None:
        return None
    columns = ("id", "type", "instrument_id", "thesis_id", "side",
               "quantity", "price", "reason", "created_at")
    detail = dict(zip(columns, row, strict=True))
    related_events = conn.execute(
        "SELECT id, event_type, created_at FROM events "
        "WHERE subject_kind = 'decision' AND subject_id = ? ORDER BY id",
        (decision_id,),
    ).fetchall()
    return {
        "page_title": f"Decision {decision_id}",
        "generated_at": _iso_now(),
        "decision": detail,
        "related_events": [
            {"id": e[0], "event_type": e[1], "created_at": e[2]}
            for e in related_events
        ],
    }


def reports_context(conn: sqlite3.Connection) -> dict[str, Any]:
    from trade_trace.core import default_registry

    registry = default_registry()
    report_tools = [
        name for name in registry.names()
        if name.startswith("report.") and name != "report.coach"
    ]
    return {
        "page_title": "Reports",
        "generated_at": _iso_now(),
        "report_tools": sorted(report_tools),
        "lazy_write_handlers_blocked": ["report.coach", "signal.scan"],
    }


def calibration_context(conn: sqlite3.Connection) -> dict[str, Any]:
    forecasts = conn.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
    scores = conn.execute("SELECT COUNT(*) FROM forecast_scores").fetchone()[0]
    return {
        "page_title": "Calibration",
        "generated_at": _iso_now(),
        "forecasts_total": forecasts,
        "forecasts_scored": scores,
        "empty_state": {
            "title": "No forecasts to calibrate yet.",
            "next_steps": [
                ("Add a forecast", "tt forecast add --probability=0.65 ..."),
                ("Record an outcome", "tt outcome add ..."),
            ],
        }
        if forecasts == 0
        else None,
    }


def strategies_context(
    conn: sqlite3.Connection, *, cursor: str | None, limit: int,
) -> dict[str, Any]:
    page = endpoints.strategies_list(conn, cursor=cursor, limit=limit)
    return {
        "page_title": "Strategies",
        "generated_at": _iso_now(),
        "rows": page.rows,
        "next_cursor": page.next_cursor,
        "limit": page.limit,
        "empty_state": {
            "title": "No strategies recorded yet.",
            "next_steps": [
                ("Create a strategy", "tt strategy create --slug=my-strat --name='My strat'"),
            ],
        }
        if not page.rows
        else None,
    }


def playbooks_context(
    conn: sqlite3.Connection, *, cursor: str | None, limit: int,
) -> dict[str, Any]:
    page = endpoints.playbooks_list(conn, cursor=cursor, limit=limit)
    return {
        "page_title": "Playbooks",
        "generated_at": _iso_now(),
        "rows": page.rows,
        "next_cursor": page.next_cursor,
        "limit": page.limit,
        "empty_state": {
            "title": "No playbooks recorded yet.",
            "next_steps": [
                ("Create a playbook", "tt playbook create --name='my-pb' --description=..."),
            ],
        }
        if not page.rows
        else None,
    }


def integrity_context(conn: sqlite3.Connection) -> dict[str, Any]:
    """`.9` Evidence & Integrity page surfaces source-attachment
    counts + the basic event-log invariants the audit harness
    pins so an operator can spot-check at a glance."""

    sources_total = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    attached_decisions = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE target_kind = 'decision' AND source_kind = 'source'",
    ).fetchone()[0]
    events_total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    outbox_pending = conn.execute(
        "SELECT COUNT(*) FROM outbox WHERE state = 'pending'",
    ).fetchone()[0]
    return {
        "page_title": "Evidence & Integrity",
        "generated_at": _iso_now(),
        "sources_total": sources_total,
        "attached_decisions": attached_decisions,
        "events_total": events_total,
        "outbox_pending": outbox_pending,
    }


def raw_context(
    conn: sqlite3.Connection, *, event_id: int | None = None,
) -> dict[str, Any]:
    if event_id is None:
        page = endpoints.journal_events(conn, cursor=None, limit=20)
        return {
            "page_title": "Raw JSON",
            "generated_at": _iso_now(),
            "rows": page.rows,
            "selected_event": None,
        }
    event = endpoints.event_detail(conn, event_id=event_id)
    return {
        "page_title": f"Raw Event {event_id}",
        "generated_at": _iso_now(),
        "rows": [],
        "selected_event": event,
    }


def _iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
