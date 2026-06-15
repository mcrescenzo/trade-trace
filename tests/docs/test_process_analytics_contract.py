"""Docs contract pins for target report.process_analytics.

These tests pin the backend/read-model reporting contract only. They do not
assert runtime implementation and intentionally avoid UI/Console scope.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS_DOC = ROOT / "docs" / "architecture" / "reports.md"


def _section() -> str:
    text = REPORTS_DOC.read_text(encoding="utf-8")
    start = text.index("## 6A. Shipped partial + target contract: `report.process_analytics`")
    end = text.index("## 7. Bucketing Policies")
    return text[start:end]


def test_process_analytics_contract_section_exists_and_is_shipped_partial():
    section = _section()

    required_terms = [
        "Status: **shipped / partial**",
        "decision-tags-only",
        "tag frequency and tag-pair co-occurrence",
        "runtime reports as unsupported",
        "read-only backend/reporting contract",
        "shipped partial behavior",
        "distinct report contract",
        "not a broadening of `report.mistakes` or `report.strengths`",
        "ReportFilter-compatible scope",
        "dimensions",
        "metrics",
        "include_costs",
        "min_sample",
        "max_groups",
        "max_record_ids_per_group",
        "as_of",
        "requested_scope",
        "applied_scope",
    ]

    missing = [term for term in required_terms if term not in section]
    assert not missing, "process analytics contract missing terms: " + ", ".join(missing)


def test_process_analytics_dimensions_metrics_and_cost_semantics_are_pinned():
    section = _section()

    required_terms = [
        "tag_frequency",
        "tag_pair_cooccurrence",
        "review_classification",
        "decision_type",
        "strategy",
        "actor_id",
        "run_id",
        "model_id",
        "environment",
        "decision_count",
        "review_count",
        "tag_count",
        "pair_count",
        "support",
        "jaccard",
        "lift",
        "confidence",
        "local_pnl_projection",
        "r_multiple",
        "fees_slippage",
        "opportunity_path_diagnostics",
        "No invented counterfactual profit",
        "broker truth",
    ]

    missing = [term for term in required_terms if term not in section]
    assert not missing, "process analytics dimensions/metrics/cost terms missing: " + ", ".join(missing)


def test_process_analytics_example_pins_machine_readable_contract_shape():
    section = _section()

    example_terms = [
        '"tool": "report.process_analytics"',
        '"contract_version": "1.0"',
        '"requested_scope"',
        '"applied_scope"',
        '"supported_filter_paths"',
        '"unsupported_filter_paths"',
        '"supported_features"',
        '"unsupported_features"',
        '"unsupported_feature"',
        '"groups"',
        '"metric_definitions"',
        '"coverage"',
        '"record_ids"',
        '"examples"',
        '"sample_warning"',
        '"caveat_codes"',
        '"LOCAL_ROWS_ONLY"',
        '"PARTIAL_COVERAGE"',
        '"DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM"',
        '"next_cursor"',
    ]

    missing = [term for term in example_terms if term not in section]
    assert not missing, "process analytics example missing shape terms: " + ", ".join(missing)


def test_process_analytics_compatibility_boundaries_are_pinned():
    section = _section()

    required_terms = [
        "Current shipped `report.mistakes` and `report.strengths` semantics remain unchanged",
        "mean Brier",
        "non-empty filters",
        "must not be silently broadened",
        "MUST NOT fetch external market",
        "call brokers",
        "place or cancel orders",
        "schedule alerts",
        "trading advice",
        "buy/sell/hold signals",
        "alpha/edge",
        "profit claims",
        "Console/UI",
        "tt console serve",
        "trade_trace.console",
        "browser dashboard",
        "frontend scope",
    ]

    missing = [term for term in required_terms if term not in section]
    assert not missing, "process analytics boundary missing terms: " + ", ".join(missing)
