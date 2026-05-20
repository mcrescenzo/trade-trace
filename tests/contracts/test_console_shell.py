"""Console frontend shell — navigation, filters, drilldown,
no-CDN posture (trade-trace-1kkv.5).

The shell is HTML + CSS + vanilla JS. The tests don't render via
Jinja2 (the `[console]` extra is optional); they treat the
templates as text and verify the contract that the wheel ships
the shell with the right nav entries, no external resources, and
the documented accessibility scaffolding.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from trade_trace.console.security import external_resources_in_template

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "src" / "trade_trace" / "console" / "templates"
STATIC_DIR = Path(__file__).resolve().parents[2] / "src" / "trade_trace" / "console" / "static"


REQUIRED_NAV_ROUTES = [
    "/",
    "/trades",
    "/journal",
    "/decisions",
    "/reports",
    "/calibration",
    "/strategies",
    "/playbooks",
    "/integrity",
    "/logs",
    "/raw",
]


def _base_html() -> str:
    return (TEMPLATE_DIR / "base.html").read_text(encoding="utf-8")


def test_base_template_exists():
    assert (TEMPLATE_DIR / "base.html").is_file()


def test_base_template_lists_every_required_nav_route():
    html = _base_html()
    for route in REQUIRED_NAV_ROUTES:
        assert f'href="{route}"' in html, f"nav missing route {route!r}"


def test_base_template_includes_logs_nav_after_jtec():
    """trade-trace-jtec restored the Logs nav entry now that the
    operational-logging contract (trade-trace-3zvl) is in place."""

    html = _base_html()
    assert 'href="/logs"' in html
    # The deferred-logs footer note from before jtec is gone.
    assert "Logs page deferred" not in html


def test_base_template_splits_nav_into_three_lanes_per_i1ds():
    """Per `docs/architecture/reporting-product.md` §3.1 the nav must
    visibly split reporting / strategies+playbooks / developer
    audiences. trade-trace-i1ds wires the three `<ul data-nav-lane>`
    blocks; this test pins the IA so a follow-up bead can't quietly
    collapse them back into a flat list."""

    html = _base_html()
    for lane in ("reporting", "strategies", "developer"):
        assert f'data-nav-lane="{lane}"' in html, (
            f"nav missing lane {lane!r}; per reporting-product.md §3.1 "
            "the IA splits reporting / strategies / developer-audit"
        )
    # The reporting lane MUST surface the user-facing reading
    # entrypoints (Overview + Reports + Calibration + Evidence) and
    # MUST NOT mix in developer surfaces.
    reporting_block = html.split('data-nav-lane="reporting"', 1)[1].split("</ul>", 1)[0]
    for required in ('href="/"', 'href="/reports"',
                     'href="/calibration"', 'href="/integrity"'):
        assert required in reporting_block, (
            f"reporting lane missing {required}"
        )
    for forbidden in ('href="/journal"', 'href="/raw"', 'href="/logs"'):
        assert forbidden not in reporting_block, (
            f"reporting lane must not include developer/audit route {forbidden}"
        )
    # Strategies and playbooks share their own lane.
    strategies_block = html.split('data-nav-lane="strategies"', 1)[1].split("</ul>", 1)[0]
    assert 'href="/strategies"' in strategies_block
    assert 'href="/playbooks"' in strategies_block
    # Developer/audit lane keeps the inspection surfaces.
    dev_block = html.split('data-nav-lane="developer"', 1)[1].split("</ul>", 1)[0]
    for required in ('href="/journal"', 'href="/decisions"',
                     'href="/logs"', 'href="/raw"'):
        assert required in dev_block, (
            f"developer lane missing {required}"
        )


@pytest.mark.parametrize("name", [
    "overview", "journal", "decisions", "reports", "calibration",
    "strategies", "playbooks", "integrity", "raw", "trades",
])
def test_top_level_template_exists(name: str):
    assert (TEMPLATE_DIR / f"{name}.html").is_file(), f"missing template {name}.html"


def test_no_template_references_external_resources():
    bad: list[tuple[str, list[str]]] = []
    for tpl in TEMPLATE_DIR.rglob("*.html"):
        findings = external_resources_in_template(tpl.read_text(encoding="utf-8"))
        if findings:
            bad.append((tpl.name, findings))
    assert not bad, f"templates with external resources: {bad}"


def test_shell_has_visible_staleness_indicator():
    html = _base_html()
    assert "data-staleness" in html
    assert "Data as of" in html


def test_shell_has_refresh_button_and_keyboard_shortcut():
    html = _base_html()
    assert 'data-refresh' in html
    js = (STATIC_DIR / "js" / "console.js").read_text(encoding="utf-8")
    # The keyboard shortcut is documented in console.md §10 as "R".
    assert 'ev.key === "r"' in js


def test_shell_has_timezone_toggle_with_utc_default():
    html = _base_html()
    assert "tt-tz-toggle" in html
    # UTC is the default; Local is the alternative.
    assert re.search(r'name="tt-tz"\s+value="utc"\s+checked', html), html
    assert 'value="local"' in html


def test_shell_has_optional_poll_control():
    html = _base_html()
    assert "data-poll-interval" in html
    assert ">Off<" in html
    for option in ("10s", "30s", "60s"):
        assert f">{option}<" in html


def test_filter_state_is_url_encoded_via_hash():
    """console.js's filter-state path writes to `location.hash`,
    not to a server-side preference store. The hash is
    reload-survivable and shareable."""

    js = (STATIC_DIR / "js" / "console.js").read_text(encoding="utf-8")
    assert "location.hash" in js
    assert "decodeHash" in js


def test_static_assets_are_vendored():
    """Every static asset referenced from the shell lives under
    `src/trade_trace/console/static/`. Tests assert the wheel
    ships them; the network-isolation contract (.13) blocks any
    runtime fetch outside loopback."""

    expected = [
        STATIC_DIR / "css" / "console.css",
        STATIC_DIR / "js" / "console.js",
        STATIC_DIR / "js" / "htmx.min.js",
    ]
    for path in expected:
        assert path.is_file(), f"missing vendored asset {path}"


def test_main_element_has_focus_target_for_accessibility():
    html = _base_html()
    # Per the §UX accessibility smoke: the main content region must be
    # focusable so keyboard users can skip the chrome.
    assert 'id="tt-main"' in html
    assert 'tabindex="-1"' in html
    assert 'role="main"' in html


def test_nav_uses_landmark_role():
    html = _base_html()
    assert '<nav class="tt-nav" aria-label="Primary">' in html
    assert 'role="banner"' in html
    assert 'role="contentinfo"' in html
