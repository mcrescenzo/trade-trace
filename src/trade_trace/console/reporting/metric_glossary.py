"""Metric glossary + caveat copy system per trade-trace-4nux.

The reporting product surfaces aggregate metrics across many pages
(P&L, risk, calibration, decision intelligence, etc.). Each metric
gets one definition in this module — the dashboard templates render
help affordances by looking up the metric's `MetricEntry` here.
A single source of truth keeps explanations consistent across pages
and prevents copy drift when the underlying report changes.

Plain-language caveats follow the same pattern: each named caveat
code (from `console.reporting.trade_rows` / `position_rows` /
`reports.md`) maps to a one-sentence explanation the UI renders next
to the affected metric tile.

The glossary entries are intentionally short. Detailed math lives
in [`docs/architecture/reporting-product.md`](../../../../docs/architecture/reporting-product.md)
§4 and in the report module's own docstring — the entries here link
to those sources via `reference` fields, but they don't restate
formulas in full. Future dashboards rendering an entry MUST link
back to its `reference` so the user can read the math.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricEntry:
    """One metric definition. `name` is the camel / snake key the
    report tools emit; `label` is the human display name; `summary`
    is one short sentence; `reference` points at the canonical
    formula doc (typically reporting-product.md §4 or a per-report
    architecture doc)."""

    name: str
    label: str
    summary: str
    reference: str


@dataclass(frozen=True)
class CaveatEntry:
    """One caveat code with the copy a dashboard renders when the
    underlying metric carries the flag. The `severity` field tells
    the UI which chrome (banner / chip / icon) to apply."""

    code: str
    label: str
    summary: str
    severity: str  # "info" | "warning"


METRIC_GLOSSARY: dict[str, MetricEntry] = {
    "realized_pnl": MetricEntry(
        name="realized_pnl",
        label="Realized P&L",
        summary=(
            "Cash result from closed positions: sum of (exit - entry) "
            "times signed quantity, less fees."
        ),
        reference="docs/architecture/reporting-product.md §4.1",
    ),
    "unrealized_pnl": MetricEntry(
        name="unrealized_pnl",
        label="Unrealized P&L",
        summary=(
            "Mark-to-market value of open positions using the latest "
            "snapshot price; zero when an open position has no mark."
        ),
        reference="docs/architecture/reporting-product.md §4.1",
    ),
    "open_mark_coverage": MetricEntry(
        name="open_mark_coverage",
        label="Open mark coverage",
        summary=(
            "Share of open positions with a current mark. <100% "
            "triggers a missing-mark caveat on derived metrics."
        ),
        reference="docs/architecture/reporting-product.md §4.1",
    ),
    "r_multiple": MetricEntry(
        name="r_multiple",
        label="R-multiple",
        summary=(
            "Realized return divided by declared risk amount; decisions "
            "without declared risk are excluded and counted in caveats."
        ),
        reference="docs/architecture/risk-units.md §3.2",
    ),
    "expectancy_r": MetricEntry(
        name="expectancy_r",
        label="Expectancy (R)",
        summary=(
            "Win rate * average winning R plus loss rate * average "
            "losing R. Positive means net expected R per trade."
        ),
        reference="docs/architecture/reporting-product.md §4.2",
    ),
    "win_rate": MetricEntry(
        name="win_rate",
        label="Win rate",
        summary="Share of closed trades with R > 0 (within a small tolerance).",
        reference="docs/architecture/reporting-product.md §4.2",
    ),
    "payoff_ratio": MetricEntry(
        name="payoff_ratio",
        label="Payoff ratio",
        summary="Average winning R divided by |average losing R|.",
        reference="docs/architecture/reporting-product.md §4.2",
    ),
    "max_drawdown": MetricEntry(
        name="max_drawdown",
        label="Max drawdown",
        summary=(
            "Largest peak-to-trough decline of the mark-to-market "
            "equity curve over the filter window."
        ),
        reference="docs/architecture/reporting-product.md §4.3",
    ),
    "brier_score": MetricEntry(
        name="brier_score",
        label="Brier score",
        summary=(
            "Mean squared error of binary forecast probabilities "
            "against realized outcomes; lower is better."
        ),
        reference="docs/architecture/scoring.md",
    ),
    "log_score": MetricEntry(
        name="log_score",
        label="Log score",
        summary=(
            "Negative log probability the forecast assigned to the "
            "realized outcome; lower is better."
        ),
        reference="docs/architecture/scoring.md",
    ),
    "ece": MetricEntry(
        name="ece",
        label="Expected Calibration Error",
        summary=(
            "Bin-weighted gap between forecasted probability and "
            "realized rate, over 10 equal-width bins."
        ),
        reference="docs/architecture/reporting-product.md §4.4",
    ),
    "sharpness": MetricEntry(
        name="sharpness",
        label="Sharpness",
        summary=(
            "Variance of forecasted probabilities — how confidently "
            "the agent forecasts."
        ),
        reference="docs/architecture/reporting-product.md §4.4",
    ),
    "baseline_brier": MetricEntry(
        name="baseline_brier",
        label="Baseline Brier",
        summary=(
            "Brier score if every forecast were the unconditional "
            "base rate; the agent's skill is the gap to this."
        ),
        reference="docs/architecture/reporting-product.md §4.4",
    ),
    "stale_threshold_days": MetricEntry(
        name="stale_threshold_days",
        label="Stale threshold (days)",
        summary=(
            "Age (in days) past which a watch decision is flagged "
            "stale by report.watchlist mode='stale'."
        ),
        reference="docs/architecture/reporting-product.md §4.5",
    ),
    "overdue_count": MetricEntry(
        name="overdue_count",
        label="Overdue watches",
        summary=(
            "Watch decisions whose `review_by` deadline has passed "
            "(per bead trade-trace-gbtj)."
        ),
        reference="docs/architecture/reports.md §4.4",
    ),
}


CAVEAT_GLOSSARY: dict[str, CaveatEntry] = {
    "missing_risk_budget": CaveatEntry(
        code="missing_risk_budget",
        label="No declared risk",
        summary=(
            "This trade has no `declared_risk_amount`; R-multiple "
            "aggregates exclude it. Record the risk you accepted at "
            "entry to recover this metric."
        ),
        severity="info",
    ),
    "missing_price": CaveatEntry(
        code="missing_price",
        label="Missing price",
        summary="The decision has no recorded execution price.",
        severity="warning",
    ),
    "missing_quantity": CaveatEntry(
        code="missing_quantity",
        label="Missing quantity",
        summary="The decision has no recorded quantity.",
        severity="warning",
    ),
    "no_strategy": CaveatEntry(
        code="no_strategy",
        label="No strategy",
        summary=(
            "This trade is not assigned to a strategy. Strategy "
            "comparison dashboards bucket it under '(no strategy)'."
        ),
        severity="info",
    ),
    "no_thesis": CaveatEntry(
        code="no_thesis",
        label="No thesis",
        summary=(
            "This trade has no linked thesis. Without a thesis, "
            "thesis-vs-outcome retros cannot include it."
        ),
        severity="info",
    ),
    "no_sources": CaveatEntry(
        code="no_sources",
        label="No source attachments",
        summary=(
            "This trade has no attached source citations. Evidence "
            "drilldowns will be empty."
        ),
        severity="info",
    ),
    "open_no_mark": CaveatEntry(
        code="open_no_mark",
        label="Open without mark",
        summary=(
            "This position is open but has no current mark. "
            "Unrealized P&L cannot be computed; the position will "
            "be excluded from MTM totals until a snapshot lands."
        ),
        severity="warning",
    ),
    "low_sample": CaveatEntry(
        code="low_sample",
        label="Low sample size",
        summary=(
            "The filtered set is below `min_sample` (default 20). "
            "Treat aggregate metrics as indicative, not conclusive."
        ),
        severity="warning",
    ),
}


PAGE_EXPLANATIONS: dict[str, dict[str, str]] = {
    "overview": {
        "what": (
            "Headline P&L, risk, and recent activity across the journal "
            "with the same filter you've applied elsewhere."
        ),
        "how_to_read": (
            "Tiles show server-computed aggregates. Click any number to "
            "open the underlying report tool with the originating filter "
            "and the contributing record ids."
        ),
        "what_can_mislead": (
            "Missing marks shrink the open exposure tile silently — check "
            "open-mark-coverage. A new strategy with one trade is shown "
            "as a low-N group; treat that win/loss as a sample of one."
        ),
    },
    "trades": {
        "what": (
            "Every trade-typed decision (actual / paper enter, add, "
            "reduce, exit) the journal has recorded, paginated by "
            "decision_at."
        ),
        "how_to_read": (
            "Columns surface side, quantity, price, declared risk, and "
            "strategy. Rows missing data carry caveat chips you can "
            "click to read the affected metric."
        ),
        "what_can_mislead": (
            "`paper_enter` rows count as trades; switch the lane filter "
            "to actual if you're auditing real exposure only."
        ),
    },
    "reports": {
        "what": (
            "Index of every read-only report tool available to the "
            "Console, with a one-line summary of what each computes."
        ),
        "how_to_read": (
            "Click a row to open the corresponding dashboard. report.coach "
            "and signal.scan are intentionally hidden — they persist "
            "rows and are out of scope for the read-only Console."
        ),
        "what_can_mislead": (
            "The list reflects the live tool registry; a future report "
            "won't appear here until it's wired through the safe-report "
            "allowlist."
        ),
    },
    "calibration": {
        "what": (
            "Brier score, log score, ECE, sharpness, baseline + skill "
            "for scored binary forecasts in the filter."
        ),
        "how_to_read": (
            "Lower Brier / log-score is better. The reliability bins "
            "(forecasted vs realized rate) show where the agent is "
            "over- or under-confident."
        ),
        "what_can_mislead": (
            "Late-recorded forecasts are excluded by default. The "
            "integrity diagnostics flag suspicious-late, unsupported, "
            "and ambiguous outcomes that can distort the panel."
        ),
    },
    "evidence": {
        "what": (
            "Source attachment analytics: which decisions cite which "
            "sources, and where evidence is missing / stale / "
            "contradictory."
        ),
        "how_to_read": (
            "Each row is a decision; columns count attached sources by "
            "kind and stance. Click a count to see the cited sources."
        ),
        "what_can_mislead": (
            "Stale sources don't necessarily make a decision wrong — "
            "they only mean the agent's evidence is older than the "
            "freshness threshold. Use it as a prompt to refresh, not a "
            "verdict."
        ),
    },
}


def metric_help(name: str) -> MetricEntry | None:
    """Return the glossary entry for `name` or `None` if the metric
    is not (yet) documented. Templates should render the metric raw
    when this is `None` rather than swallowing the value."""

    return METRIC_GLOSSARY.get(name)


def caveat_copy(code: str) -> CaveatEntry | None:
    return CAVEAT_GLOSSARY.get(code)


def page_explanation(slug: str) -> dict[str, str] | None:
    return PAGE_EXPLANATIONS.get(slug)


__all__ = [
    "CAVEAT_GLOSSARY",
    "CaveatEntry",
    "METRIC_GLOSSARY",
    "MetricEntry",
    "PAGE_EXPLANATIONS",
    "caveat_copy",
    "metric_help",
    "page_explanation",
]
