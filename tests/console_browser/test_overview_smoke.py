"""Worked example browser smoke test (trade-trace-1kkv.15).

Confirms the Overview page loads, the nav bar is present, and
no console-side JS errors fire. Per-page beads (.6 / .7 / .8 /
.9) copy this shape — see `tests/console_browser/conftest.py`
docstring for the three-step pattern.
"""

from __future__ import annotations


def test_overview_renders_navigation_and_no_console_errors(page, console_url):
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )
    page.goto(console_url + "/")

    # Header brand + read-only badge.
    assert page.locator(".tt-brand-link").is_visible()
    assert page.locator(".tt-mode-badge").text_content().strip().lower() == "read-only"

    # Nav contains the documented routes.
    for label in (
        "Overview", "Journal", "Decisions", "Reports",
        "Calibration", "Strategies", "Playbooks",
        "Evidence & Integrity", "Raw JSON",
    ):
        assert page.get_by_role("link", name=label).is_visible(), label

    # No "Logs" entry (§12 / -jtec).
    assert page.get_by_role("link", name="Logs").count() == 0

    # Staleness indicator + refresh button + tz toggle present.
    assert page.locator("[data-staleness]").is_visible()
    assert page.locator("button[data-refresh]").is_visible()
    assert page.locator("input[name='tt-tz'][value='utc']").is_checked()

    assert errors == [], errors
