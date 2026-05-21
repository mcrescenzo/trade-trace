"""Metric glossary + caveat copy + page explanation contract tests
per trade-trace-4nux.

The glossary is the single source of truth for help affordances
rendered across reporting dashboards. These tests pin coverage and
shape so a future dashboard can't reference a metric without first
adding the definition here.
"""

from __future__ import annotations

from trade_trace.reporting import (
    CAVEAT_GLOSSARY,
    METRIC_GLOSSARY,
    PAGE_EXPLANATIONS,
    CaveatEntry,
    MetricEntry,
    caveat_copy,
    metric_help,
    page_explanation,
)
from trade_trace.reporting.trade_rows import ALL_CAVEAT_CODES

# -- shape -----------------------------------------------------------


def test_every_metric_entry_has_a_reference() -> None:
    """A metric without a `reference` would force the reader to guess
    where the formula lives; pin the architecture cross-link."""

    missing = [name for name, m in METRIC_GLOSSARY.items() if not m.reference]
    assert missing == [], (
        f"metrics missing `reference`: {missing!r}. Add the architecture "
        "doc cross-link (typically reporting-product.md §4)."
    )


def test_every_metric_entry_has_a_one_sentence_summary() -> None:
    """The UI tooltip renders the summary verbatim; multi-paragraph
    blobs blow up the tooltip layout."""

    for name, m in METRIC_GLOSSARY.items():
        assert "\n" not in m.summary, f"{name!r} summary is multi-line"
        assert len(m.summary) > 10, f"{name!r} summary is empty/too short"
        assert len(m.summary) < 400, f"{name!r} summary exceeds the tooltip budget"


def test_metric_help_returns_entry_for_known_metric() -> None:
    entry = metric_help("realized_pnl")
    assert isinstance(entry, MetricEntry)
    assert entry.label == "Realized P&L"


def test_metric_help_returns_none_for_unknown_metric() -> None:
    """Templates render the raw value when the glossary lacks an
    entry rather than silently swallowing the metric."""

    assert metric_help("not_a_real_metric") is None


# -- caveats ---------------------------------------------------------


def test_every_trade_row_caveat_code_has_glossary_copy() -> None:
    """The trade read model emits named caveat codes via
    `trade_trace.reporting.trade_rows.ALL_CAVEAT_CODES`. Every one of
    those codes MUST have a copy entry, otherwise the UI renders
    an unlabeled chip."""

    missing = [code for code in ALL_CAVEAT_CODES if code not in CAVEAT_GLOSSARY]
    assert missing == [], (
        f"trade row caveat codes without glossary copy: {missing!r}"
    )


def test_position_open_no_mark_caveat_is_documented() -> None:
    """`position_rows.CAVEAT_OPEN_NO_MARK` is the only caveat the
    position read model emits today; future codes from that module
    should also land in the glossary."""

    from trade_trace.reporting import CAVEAT_OPEN_NO_MARK

    assert CAVEAT_OPEN_NO_MARK in CAVEAT_GLOSSARY


def test_caveat_severity_is_constrained() -> None:
    """Severity drives UI chrome — banner vs chip vs icon. Restrict to
    the documented set so a typo doesn't ship as a new severity."""

    for code, entry in CAVEAT_GLOSSARY.items():
        assert entry.severity in ("info", "warning"), (
            f"caveat {code!r} has unsupported severity {entry.severity!r}"
        )
        assert isinstance(entry, CaveatEntry)


def test_caveat_copy_helper_returns_none_for_unknown_code() -> None:
    assert caveat_copy("not_a_real_caveat") is None


# -- page explanations ----------------------------------------------


def test_every_page_explanation_has_three_required_sections() -> None:
    """Per reporting-product.md (and the bead acceptance) every page
    needs What this page does / How to read it / What can mislead."""

    required = {"what", "how_to_read", "what_can_mislead"}
    for slug, entry in PAGE_EXPLANATIONS.items():
        missing = required - entry.keys()
        assert missing == set(), f"page {slug!r} missing {missing!r}"


def test_page_explanation_helper_returns_none_for_unknown_slug() -> None:
    assert page_explanation("not_a_real_page") is None


def test_page_explanation_reporting_lane_pages_are_covered() -> None:
    """The reporting-lane pages declared by the IA bead (i1ds) must
    all have explanation copy."""

    for slug in ("overview", "reports", "calibration", "evidence"):
        entry = page_explanation(slug)
        assert entry is not None, f"reporting lane page {slug!r} has no explanation"
