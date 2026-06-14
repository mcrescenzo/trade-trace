"""Deterministic reports per docs/architecture/reports.md."""

from trade_trace.reports.audit_readiness import report_audit_readiness
from trade_trace.reports.autonomy_readiness import (
    AUTONOMY_READINESS_CONTRACT_VERSION,
    report_autonomy_readiness,
)
from trade_trace.reports.bootstrap import BOOTSTRAP_CONTRACT_VERSION, compose_bootstrap_packet
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
    report_calibration_advisory,
    report_calibration_anchored,
    report_calibration_terminal,
)
from trade_trace.reports.coach import (
    FORBIDDEN_PHRASES,
    TradingAdvicePhraseError,
    report_coach,
)
from trade_trace.reports.compare import report_compare
from trade_trace.reports.decision_velocity import report_decision_velocity
from trade_trace.reports.forecast_diagnostics import report_forecast_diagnostics
from trade_trace.reports.integrity import (
    MAX_SAMPLE_IDS,
    report_calibration_integrity,
)
from trade_trace.reports.lifecycle import report_lifecycle
from trade_trace.reports.memory_usefulness import report_memory_usefulness
from trade_trace.reports.opportunity import (
    DEFAULT_OPPORTUNITY_MIN_SAMPLE,
    report_opportunity,
)
from trade_trace.reports.phase_gate_readiness import report_phase_gate_readiness
from trade_trace.reports.playbook_adherence import (
    DEFAULT_ADHERENCE_MIN_SAMPLE,
    report_playbook_adherence,
)
from trade_trace.reports.pm_native import (
    report_market_lifecycle,
    report_resolution_quality,
    report_time_decay_sharpening,
)
from trade_trace.reports.pnl import report_pnl
from trade_trace.reports.policy_candidates import report_policy_candidates
from trade_trace.reports.process_analytics import report_process_analytics
from trade_trace.reports.process_quality import report_process_quality
from trade_trace.reports.recall_receipts import report_recall_receipts
from trade_trace.reports.replay import export_case_bundle
from trade_trace.reports.replay_evaluate import evaluate_output
from trade_trace.reports.resolution_misreads import report_resolution_misreads
from trade_trace.reports.risk import DEFAULT_RISK_MIN_SAMPLE, report_risk
from trade_trace.reports.rule_lineage import report_rule_lineage
from trade_trace.reports.source_quality import (
    STALE_SOURCE_THRESHOLD_DAYS,
    report_source_quality,
)
from trade_trace.reports.strategy_health import (
    DEFAULT_HEALTH_MIN_SAMPLE,
    report_strategy_health,
)
from trade_trace.reports.tag_aggregates import (
    report_mistake_tripwire,
    report_mistakes,
    report_strengths,
)
from trade_trace.reports.unscored import report_unscored_forecasts
from trade_trace.reports.watchlist import report_watchlist
from trade_trace.reports.work_queue import agent_next_actions, report_work_queue

__all__ = [
    "AUTONOMY_READINESS_CONTRACT_VERSION",
    "CONFIDENCE_LABELS",
    "BOOTSTRAP_CONTRACT_VERSION",
    "DEFAULT_ADHERENCE_MIN_SAMPLE",
    "DEFAULT_BIN_POLICY",
    "DEFAULT_HEALTH_MIN_SAMPLE",
    "DEFAULT_MIN_SAMPLE",
    "DEFAULT_OPPORTUNITY_MIN_SAMPLE",
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
    "agent_next_actions",
    "compose_bootstrap_packet",
    "confidence_bucket",
    "export_case_bundle",
    "evaluate_output",
    "liquidity_bucket",
    "report_calibration",
    "report_calibration_advisory",
    "report_calibration_anchored",
    "report_calibration_terminal",
    "report_calibration_integrity",
    "report_market_lifecycle",
    "report_resolution_quality",
    "report_lifecycle",
    "report_memory_usefulness",
    "report_coach",
    "report_compare",
    "report_decision_velocity",
    "report_forecast_diagnostics",
    "report_mistakes",
    "report_mistake_tripwire",
    "report_opportunity",
    "report_phase_gate_readiness",
    "report_pnl",
    "report_process_analytics",
    "report_process_quality",
    "report_recall_receipts",
    "report_resolution_misreads",
    "report_rule_lineage",
    "report_playbook_adherence",
    "report_policy_candidates",
    "report_risk",
    "report_source_quality",
    "report_strategy_health",
    "report_strengths",
    "report_time_decay_sharpening",
    "report_unscored_forecasts",
    "report_watchlist",
    "report_work_queue",
    "spread_bucket",
    "report_audit_readiness",
    "report_autonomy_readiness",
    "volume_bucket",
]
