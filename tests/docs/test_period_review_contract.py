"""Docs contract pins for target report.period_review.

These tests pin the period-scoped backend/reporting contract only. They do
not assert runtime implementation and intentionally avoid UI/Console scope.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS_DOC = ROOT / "docs" / "architecture" / "reports.md"


def _section() -> str:
    text = REPORTS_DOC.read_text(encoding="utf-8")
    start = text.index("## 6. Target contract: `report.period_review`")
    end = text.index("## 7. Bucketing Policies")
    return text[start:end]


def test_period_review_contract_section_exists_and_is_target_only():
    section = _section()

    required_terms = [
        "Status: **target / not implemented**",
        "read-only backend contract",
        "does not describe shipped runtime behavior",
        "separate from `review.bundle`",
        "section-oriented period packet",
        "ReportFilter-compatible scope",
        "period.basis = \"decision_at\"",
        "created_at",
        "resolved_at",
        "non-row-backed period metadata",
        "as_of",
        "sections",
        "budgets",
        "requested_scope",
        "applied_scope",
    ]

    missing = [term for term in required_terms if term not in section]
    assert not missing, "period review contract missing terms: " + ", ".join(missing)


def test_period_review_section_states_and_unsupported_invariants_are_pinned():
    section = _section()

    required_terms = [
        "included",
        "unsupported",
        "insufficient_data",
        "omitted_by_request",
        "truncated",
        "unsupported_sections",
        "unsupported_features",
        "pnl",
        "risk",
        "strategy",
        "calibration",
        "process_evidence",
        "sources_evidence",
        "reflections_playbook_adherence",
        "recall_receipts",
        "Silent omission",
        "zero-filled metrics",
        "unscoped global fallbacks",
    ]

    missing = [term for term in required_terms if term not in section]
    assert not missing, "period review unsupported/state invariant missing terms: " + ", ".join(missing)


def test_period_review_example_pins_machine_readable_contract_shape():
    section = _section()

    example_terms = [
        '"tool": "report.period_review"',
        '"contract_version": "1.0"',
        '"requested_scope"',
        '"applied_scope"',
        '"period"',
        '"basis": "decision_at"',
        '"source_fields"',
        '"supported_filter_paths"',
        '"unsupported_filter_paths"',
        '"supported_sections"',
        '"unsupported_sections"',
        '"sections"',
        '"metric_definitions"',
        '"coverage"',
        '"record_ids"',
        '"examples"',
        '"sample_warning"',
        '"caveat_codes"',
        '"LOCAL_ROWS_ONLY"',
        '"DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM"',
        '"REDACTED_SOURCE_CONTENT"',
        '"next_cursor"',
    ]

    missing = [term for term in example_terms if term not in section]
    assert not missing, "period review example missing shape terms: " + ", ".join(missing)


def test_period_review_boundaries_exclude_console_and_advice_scope():
    section = _section()

    required_terms = [
        "local-only",
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
    assert not missing, "period review boundary missing terms: " + ", ".join(missing)
