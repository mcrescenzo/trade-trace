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
    assert page.get_by_text("Trade Trace").is_visible()
    assert page.get_by_text("Read-only Console").is_visible()
    assert page.get_by_text("read-only").first.is_visible()

    # Nav contains the documented routes.
    for label in (
        "Overview", "Journal", "Decisions", "Reports",
        "Calibration", "Strategies", "Playbooks",
        "Evidence", "Raw JSON", "Logs",
    ):
        assert page.get_by_role("link", name=label).is_visible(), label

    # Refresh control and dashboard content present.
    assert page.get_by_role("button", name="Refresh").is_visible()
    assert page.get_by_text("Journal intelligence at a glance").is_visible()

    assert errors == [], errors
