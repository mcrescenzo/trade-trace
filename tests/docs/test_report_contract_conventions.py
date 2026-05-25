"""Docs contract pins for shared backend report conventions.

These tests intentionally assert the presence of the report-contract
vocabulary that future period-review and process-analytics implementations
must reuse. They do not exercise runtime report behavior.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS_DOC = ROOT / "docs" / "architecture" / "reports.md"


def _section() -> str:
    text = REPORTS_DOC.read_text(encoding="utf-8")
    start = text.index("### 3.0 Shared backend report-contract conventions")
    end = text.index("### 3.1 Drill-down rule")
    return text[start:end]


def test_shared_report_contract_convention_section_exists_with_required_terms():
    section = _section()

    required_terms = [
        "meta.contract_version",
        "data.requested_scope",
        "data.applied_scope",
        "data.applied_filter",
        "supported_filter_paths",
        "unsupported_filter_paths",
        "supported_sections",
        "unsupported_sections",
        "supported_features",
        "unsupported_features",
        "caveat_codes",
        "sample_warning",
        "coverage",
        "LOW_SAMPLE_SIZE",
        "PARTIAL_COVERAGE",
        "record_ids",
        "record_ids_unavailable",
        "reason_code",
        "Stable JSON shape",
        "Truncation and cursoring",
        "next_cursor",
        "review.bundle` §5.3",
        "sensitive",
        "redacted",
        "none",
        "MUST NOT fetch external",
        "call brokers",
        "execute trades",
        "trading advice",
        "buy/sell/hold signals",
        "profit claims",
    ]

    missing = [term for term in required_terms if term not in section]
    assert not missing, "shared report convention missing terms: " + ", ".join(missing)


def test_unsupported_analytics_invariant_is_machine_readable_and_non_silent():
    section = _section()

    assert "Mandatory unsupported-analytics invariant" in section
    assert "machine-readable `unsupported_*` or" in section
    assert "`insufficient_data` metadata" in section
    assert "instead of silently omitting" in section
    assert "zero-filling" in section
    assert "returning an unscoped" in section
    assert "global result while echoing the requested scope" in section
    assert '"applied": false' in section
    assert '"reason_code"' in section


def test_shared_report_contract_example_pins_reusable_shape():
    section = _section()

    example_terms = [
        '"requested_scope"',
        '"applied_scope"',
        '"supported_filter_paths"',
        '"unsupported_filter_paths"',
        '"supported_sections"',
        '"unsupported_sections"',
        '"supported_features"',
        '"unsupported_features"',
        '"coverage"',
        '"caveat_codes"',
        '"summary"',
        '"sample_warning"',
        '"record_ids"',
        '"truncated"',
        '"contract_version": "1.0"',
    ]

    missing = [term for term in example_terms if term not in section]
    assert not missing, "shared report example missing shape terms: " + ", ".join(missing)
