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

import json as _json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from trade_trace.console import endpoints


def overview_context(
    conn: sqlite3.Connection,
    *,
    db_path: Path,
) -> dict[str, Any]:
    status = endpoints.status(conn, db_path=db_path)
    is_empty = status["row_counts"].get("events", 0) == 0
    recent_events = conn.execute(
        "SELECT id, event_type, subject_kind, subject_id, actor_id, created_at "
        "FROM events ORDER BY id DESC LIMIT 8",
    ).fetchall()
    decisions_total = status["row_counts"].get("decisions", 0) or 0
    sources_total = status["row_counts"].get("sources", 0) or 0
    forecasts_total = status["row_counts"].get("forecasts", 0) or 0
    scored_forecasts = conn.execute("SELECT COUNT(*) FROM forecast_scores").fetchone()[0]
    attached_decisions = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE target_kind = 'decision' AND source_kind = 'source'",
    ).fetchone()[0]
    return {
        "page_title": "Overview",
        "generated_at": _iso_now(),
        "db_path": status["db_path"],
        "schema_version": status["schema_version"],
        "last_event_at": status["last_event_at"],
        "row_counts": status["row_counts"],
        "headline_metrics": [
            {
                "label": "Journal events",
                "value": status["row_counts"].get("events", 0),
                "tone": "neutral",
                "href": "/journal",
                "detail": "append-only audit trail",
            },
            {
                "label": "Decisions",
                "value": decisions_total,
                "tone": "accent",
                "href": "/decisions",
                "detail": "paper and actual entries",
            },
            {
                "label": "Forecasts scored",
                "value": f"{scored_forecasts}/{forecasts_total}",
                "tone": "neutral",
                "href": "/calibration",
                "detail": "calibration coverage",
            },
            {
                "label": "Evidence links",
                "value": f"{attached_decisions}/{decisions_total}",
                "tone": "neutral" if attached_decisions >= decisions_total else "warn",
                "href": "/integrity",
                "detail": f"{sources_total} source records",
            },
        ],
        "recent_events": [
            {
                "id": row[0],
                "event_type": row[1],
                "subject_kind": row[2],
                "subject_id": row[3],
                "actor_id": row[4],
                "created_at": row[5],
            }
            for row in recent_events
        ],
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
    decision_type = (filters or {}).get("decision_type") or None
    instrument_id = (filters or {}).get("instrument_id") or None
    page = endpoints.decisions_list(
        conn,
        cursor=cursor,
        limit=limit,
        decision_type=decision_type,
        instrument_id=instrument_id,
    )
    active_filters = {
        "decision_type": decision_type or "",
        "instrument_id": instrument_id or "",
    }
    return {
        "page_title": "Decisions",
        "generated_at": _iso_now(),
        "rows": page.rows,
        "next_cursor": page.next_cursor,
        "limit": page.limit,
        "filters": active_filters,
        "next_query": _next_query(page.next_cursor, page.limit, active_filters),
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


def position_detail_context(
    conn: sqlite3.Connection, *, position_id: str,
) -> dict[str, Any] | None:
    """Context for the per-position audit page (trade-trace-svp2).

    Returns `None` when the position is unknown — the route renders a
    404 in that case. The context surfaces the lifecycle projection,
    the full position_events lineage, the opening decision's
    strategy/playbook for audit, and the caveat list for missing
    marks / risk / strategy."""

    from trade_trace.console.reporting import position_detail

    detail = position_detail(conn, position_id)
    if detail is None:
        return None
    return {
        "page_title": f"Position {position_id}",
        "generated_at": _iso_now(),
        "position": {
            "id": detail.position_id,
            "instrument_id": detail.instrument_id,
            "instrument_symbol": detail.instrument_symbol,
            "instrument_title": detail.instrument_title,
            "venue_id": detail.venue_id,
            "venue_kind": detail.venue_kind,
            "kind": detail.kind,
            "side": detail.side,
            "status": detail.status,
            "opened_at": detail.opened_at,
            "closed_at": detail.closed_at,
            "realized_pnl": detail.realized_pnl,
            "unrealized_pnl": detail.unrealized_pnl,
            "avg_entry_price": detail.avg_entry_price,
            "updated_at": detail.updated_at,
            "initial_risk_amount": detail.initial_risk_amount,
            "realized_r_multiple": detail.realized_r_multiple,
            "unrealized_r_multiple": detail.unrealized_r_multiple,
            "opening_decision_id": detail.opening_decision_id,
            "opening_strategy_id": detail.opening_strategy_id,
            "opening_playbook_version_id": detail.opening_playbook_version_id,
        },
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "quantity_delta": e.quantity_delta,
                "price": e.price,
                "fees": e.fees,
                "slippage": e.slippage,
                "created_at": e.created_at,
                "decision_id": e.decision_id,
            }
            for e in detail.events
        ],
        "caveats": list(detail.caveats),
    }


REPORTING_DASHBOARD_TILES: dict[str, list[dict[str, Any]]] = {
    "pnl": [
        {"key": "realized_pnl", "label": "Realized P&L", "tone": "accent"},
        {"key": "unrealized_pnl", "label": "Unrealized P&L", "tone": "neutral"},
        {"key": "open_position_count", "label": "Open positions",
         "tone": "neutral", "fallback": 0},
        {"key": "open_mark_coverage", "label": "Open-mark coverage",
         "tone": "warn"},
    ],
    "risk": [
        {"key": "mean_r", "label": "Mean R", "tone": "accent",
         "metric_name": "r_multiple"},
        {"key": "median_r", "label": "Median R", "tone": "neutral",
         "metric_name": "r_multiple"},
        {"key": "expectancy_r", "label": "Expectancy (R)", "tone": "accent",
         "metric_name": "expectancy_r"},
        {"key": "win_rate", "label": "Win rate", "tone": "neutral",
         "metric_name": "win_rate"},
        {"key": "payoff_ratio", "label": "Payoff ratio", "tone": "neutral",
         "metric_name": "payoff_ratio"},
        {"key": "n_pending_with_risk", "label": "Pending w/ risk",
         "tone": "warn", "fallback": 0},
    ],
    "calibration": [
        {"key": "brier", "label": "Brier", "tone": "accent",
         "metric_name": "brier_score"},
        {"key": "log_score", "label": "Log score", "tone": "neutral",
         "metric_name": "log_score"},
        {"key": "ece", "label": "ECE", "tone": "warn",
         "metric_name": "ece"},
        {"key": "sharpness", "label": "Sharpness", "tone": "neutral",
         "metric_name": "sharpness"},
        {"key": "baseline_brier", "label": "Baseline Brier",
         "tone": "neutral", "metric_name": "baseline_brier"},
    ],
    "performance": [
        {"key": "realized_pnl", "label": "Realized P&L", "tone": "accent",
         "metric_name": "realized_pnl"},
        {"key": "max_drawdown", "label": "Max drawdown", "tone": "warn",
         "metric_name": "max_drawdown"},
        {"key": "win_rate", "label": "Win rate", "tone": "neutral",
         "metric_name": "win_rate"},
    ],
    "strategy": [
        {"key": "realized_pnl", "label": "Realized P&L", "tone": "accent"},
        {"key": "scored_forecast_count", "label": "Scored forecasts",
         "tone": "neutral", "fallback": 0},
    ],
    "decision_intelligence": [
        {"key": "watch_count", "label": "Watches", "tone": "neutral",
         "fallback": 0},
        {"key": "overdue_count", "label": "Overdue watches",
         "tone": "warn", "fallback": 0, "metric_name": "overdue_count"},
    ],
    "evidence": [
        {"key": "missing_sources_on_actual_enter",
         "label": "Missing sources", "tone": "warn", "fallback": 0},
        {"key": "stale_sources", "label": "Stale sources",
         "tone": "warn", "fallback": 0},
        {"key": "contradictory_sources", "label": "Contradictions",
         "tone": "warn", "fallback": 0},
    ],
}


def reporting_dashboard_context(
    *,
    home: str,
    tool: str,
    args: dict[str, Any] | None = None,
    page_slug: str | None = None,
    page_title: str | None = None,
) -> dict[str, Any]:
    """Generic dashboard context shared by the report-backed pages
    (P&L, Risk, Performance, Strategy, Decision intelligence, etc.).

    Calls the safe-report adapter (which enforces deny set +
    allowlist), then projects the DashboardContext into a shape the
    Jinja templates can iterate over. Per dashboard bead a per-page
    template specializes the tile / chart layout; the context shape
    stays consistent so the templates can share macros.

    `tool` is a member of `console.reporting.adapter.SAFE_REPORT_TOOLS`;
    invalid names raise the adapter's ReportAdapterError, which the
    route handler surfaces as a typed error page.
    """

    from trade_trace.console.reporting import run_report
    from trade_trace.console.reporting.metric_glossary import page_explanation

    payload = args or {}
    ctx = run_report(tool, payload, actor_id="agent:console", home=home)
    return {
        "page_title": page_title or tool,
        "generated_at": _iso_now(),
        "tool": ctx.tool,
        "summary_metrics": ctx.summary_metrics,
        "summary_sample_warning": ctx.summary_sample_warning,
        "summary_filter": ctx.summary_filter,
        "summary_caveats": ctx.summary_caveats,
        "groups": [
            {
                "key": g.key,
                "label": g.label,
                "metrics": g.metrics,
                "filter": g.filter,
                "record_ids": g.record_ids,
                "examples": g.examples,
                "sample_size": g.sample_size,
                "sample_warning": g.sample_warning,
                "truncated": g.truncated,
            }
            for g in ctx.groups
        ],
        "drilldowns": ctx.drilldowns,
        "as_of": ctx.as_of,
        "truncated": ctx.truncated,
        "next_cursor": ctx.next_cursor,
        "evidence": {
            "tool": ctx.evidence.tool,
            "cli_invocation": ctx.evidence.cli_invocation,
            "filter": ctx.evidence.filter,
            "request_id": ctx.evidence.request_id,
            "record_ids": ctx.evidence.record_ids,
            "examples": ctx.evidence.examples,
        },
        "raw_envelope": ctx.raw_envelope,
        "page_explanation": page_explanation(page_slug) if page_slug else None,
    }


def dashboard_overview_context(home: str) -> dict[str, Any]:
    """Per-bead trade-trace-w422 the Overview page upgrades from the
    DB-meta snapshot to a P&L / risk / performance roll-up dashboard.

    The page combines two report calls into one dashboard context:
    - report.pnl provides realized/unrealized totals + open mark coverage.
    - report.risk provides expectancy + win rate + R distribution.

    Tile selection comes from the `pnl` + `risk` REPORTING_DASHBOARD_TILES
    sets, ordered so the headline P&L numbers come first."""

    from trade_trace.console.reporting import run_report
    from trade_trace.console.reporting.metric_glossary import page_explanation

    pnl_ctx = run_report("report.pnl", {"filter": {}},
                        actor_id="agent:console", home=home)
    risk_ctx = run_report("report.risk", {"filter": {}},
                         actor_id="agent:console", home=home)

    combined_metrics = {**pnl_ctx.summary_metrics, **risk_ctx.summary_metrics}
    combined_caveats = list(pnl_ctx.summary_caveats) + list(risk_ctx.summary_caveats)
    combined_sample_warning = (
        pnl_ctx.summary_sample_warning or risk_ctx.summary_sample_warning
    )

    # Aggregate evidence so the Overview tile drilldowns surface both
    # tools' record_ids; the user can pivot to whichever report
    # backs the metric they clicked.
    aggregated_records: dict[str, list[str]] = {}
    for ctx in (pnl_ctx, risk_ctx):
        for kind, ids in ctx.evidence.record_ids.items():
            aggregated_records.setdefault(kind, []).extend(ids)

    # `evidence.tool` carries report.pnl as the primary surface since
    # the headline tiles are P&L. The CLI invocation matches so a
    # user reproducing the call lands on the right report.
    # The Overview surfaces P&L (4 tiles) + mean R + expectancy. Pick
    # specific risk tiles so the headline shows the two metrics most
    # users want from the landing dashboard.
    overview_tiles = list(REPORTING_DASHBOARD_TILES["pnl"]) + [
        tile for tile in REPORTING_DASHBOARD_TILES["risk"]
        if tile["key"] in ("mean_r", "expectancy_r")
    ]

    return {
        "page_title": "Overview",
        "generated_at": _iso_now(),
        "tool": "report.pnl",
        "summary_metrics": combined_metrics,
        "summary_sample_warning": combined_sample_warning,
        "summary_filter": pnl_ctx.summary_filter,
        "summary_caveats": combined_caveats,
        "groups": [
            {
                "key": g.key,
                "label": g.label,
                "metrics": g.metrics,
                "filter": g.filter,
                "record_ids": g.record_ids,
                "examples": g.examples,
                "sample_size": g.sample_size,
                "sample_warning": g.sample_warning,
                "truncated": g.truncated,
            }
            for g in pnl_ctx.groups
        ],
        "drilldowns": pnl_ctx.drilldowns,
        "as_of": pnl_ctx.as_of,
        "truncated": pnl_ctx.truncated,
        "next_cursor": pnl_ctx.next_cursor,
        "evidence": {
            "tool": "report.pnl",
            "cli_invocation": "tt report pnl",
            "filter": pnl_ctx.summary_filter,
            "request_id": pnl_ctx.evidence.request_id,
            "record_ids": aggregated_records,
            "examples": pnl_ctx.evidence.examples,
        },
        "raw_envelope": pnl_ctx.raw_envelope,
        "page_explanation": page_explanation("overview"),
        "dashboard_slug": "overview",
        "dashboard_eyebrow": "Overview",
        "dashboard_heading": "P&L · risk · performance overview",
        "highlighted_metrics": overview_tiles,
        "chart_canvas_id": "chart-overview-pnl-by-group",
        "chart_config_json": _dashboard_bar_chart_json(
            label="Realized P&L by instrument",
            groups=[{
                "label": g.label,
                "metrics": g.metrics,
            } for g in pnl_ctx.groups],
            metric_key="realized_pnl",
        ),
    }


def dashboard_pnl_context(home: str) -> dict[str, Any]:
    """Per-page context for the P&L dashboard (trade-trace-a94a)."""

    base = reporting_dashboard_context(
        home=home, tool="report.pnl", args={"filter": {}},
        page_slug="reports", page_title="P&L",
    )
    base.update({
        "dashboard_slug": "pnl",
        "dashboard_eyebrow": "P&L",
        "dashboard_heading": "P&L dashboard",
        "highlighted_metrics": REPORTING_DASHBOARD_TILES["pnl"],
        "chart_canvas_id": "chart-pnl-by-group",
        "chart_config_json": _dashboard_bar_chart_json(
            label="Realized P&L",
            groups=base["groups"], metric_key="realized_pnl",
        ),
    })
    return base


def dashboard_risk_context(home: str) -> dict[str, Any]:
    """Per-page context for the Risk dashboard (trade-trace-1viz)."""

    base = reporting_dashboard_context(
        home=home, tool="report.risk", args={"filter": {}},
        page_slug="reports", page_title="Risk",
    )
    base.update({
        "dashboard_slug": "risk",
        "dashboard_eyebrow": "Risk",
        "dashboard_heading": "Risk dashboard (R-multiple)",
        "highlighted_metrics": REPORTING_DASHBOARD_TILES["risk"],
        "chart_canvas_id": "chart-risk-histogram",
        "chart_config_json": _dashboard_bar_chart_json(
            label="R distribution",
            groups=base["groups"], metric_key="mean_r",
        ),
    })
    return base


def dashboard_calibration_context(home: str) -> dict[str, Any]:
    """Per-page context for the full Calibration dashboard
    (trade-trace-lv7n)."""

    base = reporting_dashboard_context(
        home=home, tool="report.calibration",
        args={"filter": {}, "min_sample": 1},
        page_slug="calibration", page_title="Calibration",
    )
    base.update({
        "dashboard_slug": "calibration",
        "dashboard_eyebrow": "Calibration",
        "dashboard_heading": "Calibration + integrity",
        "highlighted_metrics": REPORTING_DASHBOARD_TILES["calibration"],
        "chart_canvas_id": "chart-calibration-reliability",
        "chart_config_json": _dashboard_reliability_chart_json(
            summary_metrics=base["summary_metrics"],
        ),
    })
    return base


def dashboard_performance_context(home: str) -> dict[str, Any]:
    """Per-page context for the Performance dashboard
    (trade-trace-ai45). Uses report.decision_velocity for the time
    series until the dedicated equity curve / drawdown report ships."""

    base = reporting_dashboard_context(
        home=home, tool="report.decision_velocity",
        args={"filter": {}, "bucket": "day"},
        page_slug="reports", page_title="Performance",
    )
    base.update({
        "dashboard_slug": "performance",
        "dashboard_eyebrow": "Performance",
        "dashboard_heading": "Performance — calendar, equity, drawdown",
        "highlighted_metrics": REPORTING_DASHBOARD_TILES["performance"],
        "chart_canvas_id": "chart-performance-decision-velocity",
        "chart_config_json": _dashboard_bar_chart_json(
            label="Decisions per day",
            groups=base["groups"], metric_key="count",
        ),
    })
    return base


def dashboard_strategy_context(home: str) -> dict[str, Any]:
    """Per-page context for the Strategy / Playbook performance
    dashboard (trade-trace-avn7)."""

    base = reporting_dashboard_context(
        home=home, tool="report.strategy_performance",
        args={"filter": {}},
        page_slug="reports", page_title="Strategy performance",
    )
    base.update({
        "dashboard_slug": "strategy",
        "dashboard_eyebrow": "Strategy & Playbook",
        "dashboard_heading": "Strategy performance",
        "highlighted_metrics": REPORTING_DASHBOARD_TILES["strategy"],
        "chart_canvas_id": "chart-strategy-pnl",
        "chart_config_json": _dashboard_bar_chart_json(
            label="Realized P&L per strategy",
            groups=base["groups"], metric_key="realized_pnl",
        ),
    })
    return base


def dashboard_decision_intelligence_context(home: str) -> dict[str, Any]:
    """Per-page context for the Decision intelligence dashboard
    (trade-trace-nvkr). Uses report.watchlist for the dashboard
    surface; mistakes / strengths land via the comparison builder
    (sqtq)."""

    base = reporting_dashboard_context(
        home=home, tool="report.watchlist", args={"filter": {}},
        page_slug="reports", page_title="Decision intelligence",
    )
    base.update({
        "dashboard_slug": "decision_intelligence",
        "dashboard_eyebrow": "Decision intelligence",
        "dashboard_heading": "Mistakes · strengths · watches · forecast backlog",
        "highlighted_metrics": REPORTING_DASHBOARD_TILES["decision_intelligence"],
        "chart_canvas_id": "chart-decision-watch-overdue",
        "chart_config_json": _dashboard_bar_chart_json(
            label="Watch overdue", groups=base["groups"], metric_key="overdue",
        ),
    })
    return base


def dashboard_compare_context(
    home: str, *,
    base_report: str = "calibration",
    group_by: str = "strategy_id",
) -> dict[str, Any]:
    """Per-page context for the comparison builder (trade-trace-sqtq).

    Wraps report.compare and projects the cross-group result into the
    standard dashboard shape. Defaults compare calibration across
    strategies; the per-page filter form lets the user change the
    base report (`calibration` or `pnl`) and the group_by axis."""

    base = reporting_dashboard_context(
        home=home, tool="report.compare",
        args={"base_report": base_report, "group_by": group_by, "filter": {}},
        page_slug="reports", page_title="Compare",
    )
    base.update({
        "dashboard_slug": "compare",
        "dashboard_eyebrow": "Reports · Comparison",
        "dashboard_heading": f"Compare {base_report} by {group_by}",
        "highlighted_metrics": [
            {"key": "n_groups", "label": "Groups", "tone": "neutral",
             "fallback": 0},
            {"key": "skipped_groups", "label": "Skipped groups",
             "tone": "warn", "fallback": 0},
        ],
        "chart_canvas_id": "chart-compare",
        "chart_config_json": _dashboard_bar_chart_json(
            label=f"{base_report} per {group_by}",
            groups=base["groups"],
            metric_key="brier" if base_report == "calibration" else "realized_pnl",
        ),
        "compare_form": {
            "base_report": base_report,
            "group_by": group_by,
            "allowed_base_reports": ["calibration", "pnl"],
            "allowed_group_by": [
                "strategy_id", "agent_id", "model_id",
                "playbook_version_id", "decision_type",
            ],
        },
    })
    return base


def report_export_packet(
    *, home: str, tool: str, args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only export packet per trade-trace-sqtq.

    Bundles the report's full envelope, the originating filter, the
    request_id, and the CLI invocation a user would run to reproduce
    the call. Returns a plain dict so the route handler can serialize
    it as JSON. Never includes credentials or cross-session identifiers
    — every field comes from the public ReportResult envelope.
    """

    from trade_trace.console.reporting import run_report

    ctx = run_report(tool, args or {}, actor_id="agent:console", home=home)
    return {
        "tool": ctx.tool,
        "cli_invocation": ctx.evidence.cli_invocation,
        "filter": ctx.summary_filter,
        "request_id": ctx.evidence.request_id,
        "as_of": ctx.as_of,
        "envelope": ctx.raw_envelope,
        "record_ids": ctx.evidence.record_ids,
        "exported_at": _iso_now(),
    }


def dashboard_evidence_context(home: str) -> dict[str, Any]:
    """Per-page context for the Evidence / provenance dashboard
    (trade-trace-5own). Replaces the developer-lane integrity view
    on the reporting side."""

    base = reporting_dashboard_context(
        home=home, tool="report.source_quality", args={},
        page_slug="evidence", page_title="Evidence & provenance",
    )
    base.update({
        "dashboard_slug": "evidence",
        "dashboard_eyebrow": "Evidence",
        "dashboard_heading": "Evidence & provenance analytics",
        "highlighted_metrics": REPORTING_DASHBOARD_TILES["evidence"],
        "chart_canvas_id": "chart-evidence-source-quality",
        "chart_config_json": _dashboard_bar_chart_json(
            label="Source diagnostics", groups=base["groups"], metric_key="count",
        ),
    })
    return base


def _dashboard_bar_chart_json(
    *, label: str, groups: list[dict[str, Any]], metric_key: str,
) -> str:
    """Encode a minimal Chart.js bar-chart config for the dashboard.
    Returns JSON the template injects into a
    `<script type="application/json">` block; the chart bootstrap
    consumes it via JSON.parse (no eval / no client math)."""

    config = {
        "type": "bar",
        "data": {
            "labels": [g["label"] for g in groups],
            "datasets": [{
                "label": label,
                "data": [
                    (g["metrics"].get(metric_key) or 0)
                    if isinstance(g["metrics"], dict) else 0
                    for g in groups
                ],
            }],
        },
        "options": {"responsive": True},
    }
    return _json.dumps(config)


def _dashboard_reliability_chart_json(
    *, summary_metrics: dict[str, Any],
) -> str:
    """Encode the calibration reliability diagram from
    `summary_metrics.reliability_bins` (or its alternates), falling
    back to an empty chart when the bins aren't present."""

    bins = summary_metrics.get("reliability_bins") or []
    config = {
        "type": "line",
        "data": {
            "labels": [
                f"{b.get('forecast_mid', i / 10):.1f}" if isinstance(b, dict)
                else f"bin {i}"
                for i, b in enumerate(bins)
            ],
            "datasets": [{
                "label": "Empirical rate",
                "data": [
                    (b.get("empirical_rate") or 0) if isinstance(b, dict) else 0
                    for b in bins
                ],
            }],
        },
        "options": {"responsive": True},
    }
    return _json.dumps(config)


def trades_context(
    conn: sqlite3.Connection,
    *,
    cursor: str | None,
    limit: int,
    strategy_id: str | None = None,
    instrument_id: str | None = None,
    decision_type: str | None = None,
) -> dict[str, Any]:
    """Context for the Trades index page (trade-trace-q2li).

    Backed by `console.reporting.list_trades`. Surfaces the full
    `TradeRow` shape including the named missing-data caveats so the
    template can render caveat chips next to incomplete rows. Filter
    args narrow the page server-side; the global ReportFilter URL
    state encoder (hayy) and the per-page form normalize these into
    the same shape.
    """

    from trade_trace.console.reporting import list_trades
    from trade_trace.console.reporting.metric_glossary import page_explanation

    page = list_trades(
        conn,
        cursor=cursor,
        limit=limit,
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        decision_type=decision_type,
    )
    return {
        "page_title": "Trades",
        "generated_at": _iso_now(),
        "rows": [
            {
                "decision_id": r.decision_id,
                "decision_type": r.decision_type,
                "decision_at": r.decision_at,
                "instrument_id": r.instrument_id,
                "instrument_symbol": r.instrument_symbol,
                "instrument_title": r.instrument_title,
                "venue_kind": r.venue_kind,
                "side": r.side,
                "quantity": r.quantity,
                "price": r.price,
                "declared_risk_amount": r.declared_risk_amount,
                "declared_risk_unit": r.declared_risk_unit,
                "strategy_id": r.strategy_id,
                "strategy_slug": r.strategy_slug,
                "tag_count": r.tag_count,
                "source_count": r.source_count,
                "caveats": list(r.caveats),
            }
            for r in page.rows
        ],
        "next_cursor": page.next_cursor,
        "limit": page.limit,
        "filters": {
            "strategy_id": strategy_id or "",
            "instrument_id": instrument_id or "",
            "decision_type": decision_type or "",
        },
        "next_query": _next_query(page.next_cursor, page.limit, {
            "strategy_id": strategy_id or "",
            "instrument_id": instrument_id or "",
            "decision_type": decision_type or "",
        }),
        "page_explanation": page_explanation("trades"),
        "empty_state": {
            "title": "No trades recorded yet.",
            "next_steps": [
                ("Seed the rich reporting fixture",
                 "tt journal fixture-seed --target=mvp-eval-rich"),
                ("Record a paper-entry decision",
                 "tt decision add --type=paper_enter ..."),
            ],
        }
        if not page.rows
        else None,
    }


def _next_query(next_cursor: str | None, limit: int, filters: dict[str, Any]) -> str:
    params: dict[str, Any] = {"cursor": next_cursor or "", "limit": limit}
    params.update({k: v for k, v in filters.items() if v not in (None, "")})
    return urlencode(params)


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
