"""Deterministic reports per docs/architecture/reports.md."""

from trade_trace.reports.buckets import (
    CONFIDENCE_LABELS,
    LIQUIDITY_BUCKET_THRESHOLDS,
    LIQUIDITY_BUCKET_VALUES,
    SPREAD_BUCKET_THRESHOLDS,
    SPREAD_BUCKET_VALUES,
    VOLUME_BUCKET_THRESHOLDS,
    VOLUME_BUCKET_VALUES,
    confidence_bucket,
    liquidity_bucket,
    spread_bucket,
    volume_bucket,
)
from trade_trace.reports.calibration import (
    DEFAULT_BIN_POLICY,
    DEFAULT_MIN_SAMPLE,
    report_calibration,
)
from trade_trace.reports.coach import (
    FORBIDDEN_PHRASES,
    TradingAdvicePhraseError,
    report_coach,
)
from trade_trace.reports.compare import report_compare, report_strategy_performance
from trade_trace.reports.decision_velocity import report_decision_velocity
from trade_trace.reports.integrity import (
    MAX_SAMPLE_IDS,
    report_calibration_integrity,
)
from trade_trace.reports.playbook_adherence import (
    DEFAULT_ADHERENCE_MIN_SAMPLE,
    report_playbook_adherence,
)
from trade_trace.reports.pnl import report_pnl
from trade_trace.reports.risk import DEFAULT_RISK_MIN_SAMPLE, report_risk
from trade_trace.reports.source_quality import (
    STALE_SOURCE_THRESHOLD_DAYS,
    report_source_quality,
)
from trade_trace.reports.tag_aggregates import report_mistakes, report_strengths
from trade_trace.reports.unscored import report_unscored_forecasts
from trade_trace.reports.watchlist import report_watchlist

__all__ = [
    "CONFIDENCE_LABELS",
    "DEFAULT_ADHERENCE_MIN_SAMPLE",
    "DEFAULT_BIN_POLICY",
    "DEFAULT_MIN_SAMPLE",
    "DEFAULT_RISK_MIN_SAMPLE",
    "FORBIDDEN_PHRASES",
    "LIQUIDITY_BUCKET_THRESHOLDS",
    "LIQUIDITY_BUCKET_VALUES",
    "MAX_SAMPLE_IDS",
    "SPREAD_BUCKET_THRESHOLDS",
    "SPREAD_BUCKET_VALUES",
    "STALE_SOURCE_THRESHOLD_DAYS",
    "TradingAdvicePhraseError",
    "VOLUME_BUCKET_THRESHOLDS",
    "VOLUME_BUCKET_VALUES",
    "confidence_bucket",
    "liquidity_bucket",
    "report_calibration",
    "report_calibration_integrity",
    "report_coach",
    "report_compare",
    "report_decision_velocity",
    "report_mistakes",
    "report_pnl",
    "report_playbook_adherence",
    "report_risk",
    "report_source_quality",
    "report_strategy_performance",
    "report_strengths",
    "report_unscored_forecasts",
    "report_watchlist",
    "spread_bucket",
    "volume_bucket",
]
