"""Static accessibility contract tests for the reporting dashboards
per trade-trace-0d3p.

Full browser/visual QA requires the `[console-test]` Playwright
extra (see `tests/console_browser/`); these static checks catch the
common a11y / structural regressions that don't need a real browser:

- One H1 per dashboard page.
- Top-level sections carry `aria-label` so screen readers can
  navigate landmarks.
- Page explanation uses semantic `<details>/<summary>` (not
  div-based pseudo-disclosure).
- No `tabindex > 0` (a positive tabindex jumps focus order and
  hurts keyboard navigation).
- Caveat / sample-warning banners include text content (color
  alone never carries meaning).
- Tables surface a `<thead>` so screen readers announce column
  headers.

The Playwright suite under `tests/console_browser/` covers the
remaining runtime checks (visible focus rings, color contrast under
actual browser rendering, chart fallback readability with the
operator-installed Chart.js binary).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "src" / "trade_trace" / "console" / "templates"

DASHBOARD_TEMPLATES: tuple[str, ...] = (
    "dashboard.html",
    "dashboard_pnl.html",
    "trades.html",
    "position_detail.html",
)


def _template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def test_dashboard_macros_template_exists() -> None:
    assert (TEMPLATE_DIR / "_dashboard_macros.html").is_file()


def test_dashboard_templates_have_one_h1() -> None:
    for name in DASHBOARD_TEMPLATES:
        text = _template(name)
        h1_count = len(re.findall(r"<h1[\s>]", text))
        assert h1_count == 1, (
            f"{name} has {h1_count} <h1> tags; dashboards must have exactly one"
        )


def test_dashboard_templates_use_semantic_details_for_explanation() -> None:
    """The page explanation accordion uses <details>/<summary> so the
    disclosure is keyboard-accessible by default and announced
    properly by screen readers."""

    macros = _template("_dashboard_macros.html")
    assert "<details" in macros, (
        "page explanation macro must use <details> for disclosure"
    )
    assert "<summary>" in macros, (
        "page explanation macro must label its disclosure with <summary>"
    )


def test_dashboard_templates_have_no_positive_tabindex() -> None:
    """A positive `tabindex` jumps focus order — never appropriate
    inside the reporting dashboards. `tabindex=0` (focusable in
    document order) and `tabindex=-1` (programmatic focus target)
    are fine; anything else is a regression."""

    for name in DASHBOARD_TEMPLATES + ("base.html", "_dashboard_macros.html"):
        text = _template(name)
        bad = re.findall(r'tabindex\s*=\s*"([0-9]+)"', text)
        offending = [v for v in bad if int(v) > 0]
        assert offending == [], (
            f"{name} has positive tabindex(es) {offending!r}; these break "
            "keyboard navigation order"
        )


def test_dashboard_templates_label_sections_with_aria() -> None:
    """Top-level reporting sections that group metrics MUST carry an
    `aria-label` so screen readers announce the landmark."""

    macros = _template("_dashboard_macros.html")
    assert "aria-label" in macros


def test_caveat_banners_include_text_not_color_only() -> None:
    """Banners + chips render text alongside their color/border
    treatment so color-blind users still get the signal. The macros
    are the canonical source; this test asserts the banner copy is
    present in the macro definition."""

    macros = _template("_dashboard_macros.html")
    # sample_warning_banner contains <strong>Sample warning:</strong>
    assert "Sample warning" in macros
    # caveats_banner contains <strong>Caveats:</strong>
    assert "Caveats" in macros


def test_dashboard_tables_use_thead() -> None:
    """Every table the dashboards render uses <thead> so screen
    readers announce column headers."""

    for name in DASHBOARD_TEMPLATES:
        text = _template(name)
        if "<table" not in text:
            continue
        assert "<thead>" in text, (
            f"{name} has a <table> without <thead>; screen readers won't "
            "announce the column headers"
        )


def test_evidence_affordance_uses_semantic_disclosure() -> None:
    """The evidence drilldown affordance is also a <details>/<summary>
    so keyboard users can open it with Enter."""

    macros = _template("_dashboard_macros.html")
    # Locate the evidence_affordance macro body
    assert "evidence_affordance" in macros
    # The macro body uses <details ... class="tt-evidence-affordance">
    assert 'class="tt-evidence-affordance"' in macros


def test_chart_canvas_has_aria_label() -> None:
    """Every <canvas> element rendered by the dashboards carries an
    `aria-label` describing its content, since the canvas itself is
    opaque to screen readers."""

    for name in DASHBOARD_TEMPLATES:
        text = _template(name)
        for canvas_match in re.finditer(r"<canvas\b[^>]*>", text):
            tag = canvas_match.group(0)
            assert "aria-label" in tag, (
                f"{name} has a <canvas> without aria-label: {tag}"
            )
