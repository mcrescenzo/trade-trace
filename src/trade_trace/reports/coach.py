"""`report.coach` synthesized decision-support packet per trade-trace-2g2.

The coach aggregates outputs from the existing reports and signal.scan
into a single packet the agent can consult at decision time:

- recurring mistake/strength tags (from report.mistakes + report.strengths)
- calibration drift signals (placeholder until the M2 drift detector lands)
- override-outcome counts (placeholder; ties to playbook adherence in M3)
- stale watches (from report.watchlist mode=stale)
- sample-size warnings (from any report whose sample_size < its threshold)
- unscored forecasts (mirror of signal.scan output)

The coach NEVER recommends a trade. The output is enforced free of the
forbidden phrases enumerated in the ux0 acceptance: "buy", "sell",
"profitable", "recommended trade", "long", "short". A `_assert_no_trade_advice`
post-check on the emitted packet raises if a forbidden phrase appears,
catching accidental drift in future revisions.

No LLM call, no network IO, no model loading. The coach is a deterministic
SQL-aggregation packet — every field comes from already-committed rows.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._filter_support import process_filter
from trade_trace.reports.integrity import report_calibration_integrity
from trade_trace.reports.source_quality import report_source_quality
from trade_trace.reports.tag_aggregates import report_mistakes, report_strengths
from trade_trace.reports.unscored import report_unscored_forecasts
from trade_trace.reports.watchlist import report_watchlist

FORBIDDEN_PHRASES = (
    "buy",
    "sell",
    "profitable",
    "recommended trade",
    "long",
    "short",
)
"""Output policy per ux0 acceptance. The coach is a calibration/journal
substrate, never a trading recommender."""


_FORBIDDEN_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in FORBIDDEN_PHRASES) + r")\b",
    re.IGNORECASE,
)


class TradingAdvicePhraseError(RuntimeError):
    """Raised when a coach packet contains a forbidden trading-advice phrase.

    The packet is held inside the tool call; the dispatcher translates this
    into a typed envelope so the agent sees the violation surface."""

    def __init__(self, matches: list[str]) -> None:
        self.matches = matches
        super().__init__(
            f"coach packet contains forbidden phrase(s) {matches!r}; "
            "the coach must not emit trade advice (ux0 acceptance)"
        )


def report_coach(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    stale_threshold_days: int = 14,
) -> dict[str, Any]:
    """Build the coach packet. Returns the `data` portion of the envelope."""

    rf = ReportFilter.model_validate(raw_filter or {})
    filter_dict = process_filter(rf, report="report.coach")

    mistakes = report_mistakes(conn, raw_filter=filter_dict)
    strengths = report_strengths(conn, raw_filter=filter_dict)
    unscored = report_unscored_forecasts(conn, raw_filter=filter_dict)
    stale_watches = report_watchlist(
        conn, raw_filter=filter_dict, stale=True,
        stale_threshold_days=stale_threshold_days,
    )

    top_mistakes = _top_tag_summary(mistakes)
    top_strengths = _top_tag_summary(strengths)
    unscored_summary: dict[str, Any] = {
        "count": unscored["summary"]["metrics"]["unscored_count"],
        "forecast_ids": unscored["groups"][0]["record_ids"]["forecasts"][:5],
    } if unscored["groups"] else {"count": 0, "forecast_ids": []}
    stale_summary: dict[str, Any] = {
        "count": stale_watches["summary"]["metrics"]["watch_count"],
        "stale_threshold_days": stale_threshold_days,
        "decision_ids": [
            g["record_ids"]["decisions"][0]
            for g in stale_watches["groups"][:5]
        ],
    }

    sample_warnings: list[str] = []
    for label, report in (
        ("mistakes", mistakes), ("strengths", strengths),
        ("unscored", unscored), ("stale_watchlist", stale_watches),
    ):
        warn = report["summary"]["sample_warning"]
        if warn:
            sample_warnings.append(f"{label}: {warn}")

    callouts: list[str] = []
    if unscored_summary["count"] > 0:
        callouts.append(
            f"{unscored_summary['count']} pending forecast(s) past resolution_at — "
            "resolve before this dimension distorts calibration aggregates."
        )
    if stale_summary["count"] > 0:
        callouts.append(
            f"{stale_summary['count']} watch decision(s) older than "
            f"{stale_threshold_days} days — revisit or close them."
        )
    if top_mistakes:
        worst = top_mistakes[0]
        callouts.append(
            f"tag '{worst['tag']}' has the highest mean Brier "
            f"({worst['mean_brier']:.3f} over {worst['scored_forecast_count']} "
            "scored forecasts) — review the calibration on this pattern."
        )

    # Placeholder field the M3 drift detector will populate.
    calibration_drift = {
        "status": "not_yet_detected",
        "note": "calibration drift signal landing with the M3 drift detector",
    }

    # Override-outcome panel (M4, bead fbq + Test QC 722). When a
    # decision had a playbook rule marked `overridden`, downstream
    # outcomes on that decision's instrument are interesting: were the
    # overrides justified (outcome went the agent's way) or punished
    # (outcome was adverse)? The coach surfaces raw counts with
    # sample_ids so the agent can drill in; the panel is descriptive,
    # not prescriptive — phrasing is chosen to stay clear of forbidden
    # trade-advice phrases.
    override_outcomes = _override_outcomes_panel(conn)
    if override_outcomes["overridden_count"] > 0:
        callouts.append(
            f"playbook override audit: {override_outcomes['overridden_count']} "
            f"decision(s) marked overridden; review sample_ids before next "
            "similar setup."
        )

    # Source-quality provenance panel (bead trade-trace-l9q). Surfaces the
    # five attachment-hygiene diagnostics; each diagnostic with count>0
    # generates a callout pointing to the sample_ids.
    source_quality = report_source_quality(conn)
    for diagnostic_key, diag in source_quality["diagnostics"].items():
        if diag["count"] > 0:
            callouts.append(
                f"{diagnostic_key}: {diag['count']} record(s) — review "
                "via report.source_quality for sample_ids."
            )

    # Surface the anti-goodhart integrity panel (bead trade-trace-jzn) so
    # the coach output carries the same denominator/hygiene context as
    # report.calibration. The metrics are framed as hygiene warnings, not
    # accusations — phrasing chosen to stay clear of forbidden trade-advice
    # phrases.
    integrity = report_calibration_integrity(conn)
    for diagnostic_key, diag in integrity["diagnostics"].items():
        if diagnostic_key == "forecast_coverage":
            cov = diag["denominator_coverage_pct"]
            if cov is not None and cov < 50.0:
                callouts.append(
                    f"forecast_coverage: only {diag['scored_forecasts']} of "
                    f"{diag['total_decisions']} decisions have scored "
                    f"forecasts ({cov:.1f}%) — calibration numbers reflect a "
                    "narrow slice."
                )
            continue
        rate = diag["rate_pct"]
        if rate is not None and rate > 0:
            callouts.append(
                f"{diagnostic_key}: {diag['count']} of {diag['total']} "
                f"({rate:.1f}%) — hygiene warning, drill into sample_ids."
            )

    packet = {
        "filter": filter_dict,
        "top_mistakes": top_mistakes,
        "top_strengths": top_strengths,
        "unscored_forecasts": unscored_summary,
        "stale_watches": stale_summary,
        "sample_warnings": sample_warnings,
        "calibration_drift": calibration_drift,
        "override_outcomes": override_outcomes,
        "integrity_diagnostics": integrity,
        "source_quality": source_quality,
        "callouts": callouts,
        "is_advisory_only": True,
    }
    _assert_no_trade_advice(packet)
    return packet


def _report_groups(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Unwrap a sub-report's `groups` regardless of whether it arrived
    as the raw data dict (`{"groups": [...]}`) or wrapped inside a
    success envelope (`{"data": {"groups": [...]}}`).

    Per bead trade-trace-d7a / DEBT-025: the coach previously
    handled the wrapped branch only for `mistakes` and the raw
    branch only for `strengths`; both helpers exist because the
    sub-report function may be invoked directly (raw) or routed
    through the dispatcher (wrapped). This helper unifies both
    paths so a future envelope tweak can't produce a KeyError.
    """

    if "data" in report and isinstance(report["data"], dict):
        return list(report["data"].get("groups") or [])
    return list(report.get("groups") or [])


def _top_tag_summary(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Coach helper: top-3 tag groups from a report.mistakes /
    report.strengths sub-report. Filters out empty-sample groups so a
    zero-Brier division never reaches the formatter."""

    return [
        {
            "tag": g["key"],
            "decision_count": g["metrics"]["decision_count"],
            "scored_forecast_count": g["metrics"]["scored_forecast_count"],
            "mean_brier": g["metrics"]["mean_brier"],
            "decision_ids": g["record_ids"]["decisions"][:5],
        }
        for g in _report_groups(report)[:3]
        if g["metrics"]["scored_forecast_count"] > 0
    ]


def _override_outcomes_panel(conn: sqlite3.Connection) -> dict[str, Any]:
    """Aggregate `decision_playbook_rules` rows with `status='overridden'`
    plus any outcomes recorded on the same instrument afterwards.

    Output shape:
        {
          "overridden_count": int,
          "with_subsequent_outcome": int,
          "without_subsequent_outcome": int,
          "sample_decision_ids": [<= 10 ids],
        }

    The panel is descriptive — no judgment about whether the override
    was 'right' or 'wrong' (outcomes are themselves probabilistic).
    The agent reads the sample IDs and forms their own view.
    """

    rows = conn.execute(
        """
        SELECT dpr.id, dpr.decision_id, d.instrument_id, d.created_at
        FROM decision_playbook_rules dpr
        JOIN decisions d ON d.id = dpr.decision_id
        WHERE dpr.status = 'overridden'
        ORDER BY d.created_at, dpr.id
        """
    ).fetchall()
    overridden_count = len(rows)
    decision_ids: list[str] = []
    with_outcome = 0
    for _adh_id, dec_id, instr_id, dec_at in rows:
        if dec_id not in decision_ids:
            decision_ids.append(dec_id)
        has_outcome = conn.execute(
            "SELECT 1 FROM outcomes WHERE instrument_id = ? "
            "AND resolved_at > ? LIMIT 1",
            (instr_id, dec_at),
        ).fetchone()
        if has_outcome is not None:
            with_outcome += 1
    return {
        "overridden_count": overridden_count,
        "with_subsequent_outcome": with_outcome,
        "without_subsequent_outcome": overridden_count - with_outcome,
        "sample_decision_ids": decision_ids[:10],
    }


def _assert_no_trade_advice(packet: dict[str, Any]) -> None:
    """Walk every string in the packet; raise if a forbidden phrase appears.

    The check uses a word-boundary regex so legitimate IDs that happen to
    contain a substring (e.g. an instrument titled "Buy-side ETF") don't
    trip it. Callouts and notes are the most likely places drift would
    appear; this gate catches it before the envelope leaves the process."""

    matches: list[str] = []
    for value in _iter_strings(packet):
        for m in _FORBIDDEN_RE.findall(value):
            matches.append(m.lower())
    if matches:
        raise TradingAdvicePhraseError(sorted(set(matches)))


def _iter_strings(value: Any):
    """Yield every string value in a nested dict/list/scalar structure."""

    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _iter_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _iter_strings(v)
