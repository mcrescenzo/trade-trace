"""Console browser-test harness (trade-trace-1kkv.15).

Per `docs/architecture/console.md` §11 we adopted Playwright. The
fixtures here are intentionally thin so per-page smoke tests
(.6/.7/.8/.9) reuse the same Console server + seeded DB + browser
driver. The harness is opt-in: every test under
`tests/console_browser/` skips automatically when the
`[console]` + `[console-test]` extras are not installed, so the
default `pytest` run on a base install stays green.

Adding a smoke test for a new page is a three-step pattern:

1. Add the page route to `_REQUIRED_NAV_ROUTES` if missing.
2. Write a test function under `tests/console_browser/` that
   takes the `console_url` fixture and a Playwright `page`,
   navigates to `console_url + "/<route>"`, and asserts on the
   rendered DOM with `page.locator(...).is_visible()`.
3. Re-run `pytest tests/console_browser/`. The fixture starts
   the server on an ephemeral port, seeds the DB once per
   session, and tears down cleanly.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

playwright_sync_api = pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "Console browser tests require the [console-test] extra. "
        "Install with: pip install 'trade-trace[console]' "
        "'trade-trace[console-test]' && playwright install chromium"
    ),
)


def _ephemeral_port() -> int:
    """Pick an unused TCP port for the Console server. Borrow
    from the OS rather than guessing so the harness composes
    cleanly with parallel test runs."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def _wait_for_port(host: str, port: int, *, timeout: float = 10.0) -> None:
    """Poll until the Console server accepts a TCP connect or the
    budget runs out. Per-poll budget kept tight so a missing
    server fails fast instead of hanging the CI run."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.25)
        try:
            sock.connect((host, port))
            return
        except OSError:
            time.sleep(0.05)
        finally:
            sock.close()
    raise RuntimeError(f"Console server never opened {host}:{port}")


@pytest.fixture(scope="session")
def seeded_home(tmp_path_factory) -> Path:
    """Session-wide Trade Trace home seeded by `journal.fixture_seed`
    (the M0-eval profile from trade-trace-8dv). Smoke tests share
    the seed for speed; reset across pages via the polling
    indicator if the test mutates state (which it should not, since
    the Console is read-only)."""

    from trade_trace.mcp_server import mcp_call

    home = tmp_path_factory.mktemp("console-browser-home")
    init = mcp_call("journal.init", {"home": str(home)})
    assert init.ok
    seed = mcp_call(
        "journal.fixture_seed",
        {"home": str(home), "target": "mvp-eval"},
        actor_id="agent:test",
    )
    assert seed.ok
    return home


@pytest.fixture(scope="session")
def console_url(seeded_home) -> Iterator[str]:
    """Boot `tt console serve` against the seeded home on an
    ephemeral port. Yields the base URL and tears the server
    down at session teardown."""

    port = _ephemeral_port()
    env = {
        "PATH": "/usr/bin:/bin",
        "TRADE_TRACE_HOME": str(seeded_home),
    }
    process = subprocess.Popen(
        [
            sys.executable, "-m", "trade_trace.cli",
            "console", "serve",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--no-browser",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_port("127.0.0.1", port)
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture
def browser_context(playwright):
    """Headless chromium with reduced-motion + UTC time zone so
    smoke tests don't flake on machine locale or animations."""

    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        timezone_id="UTC",
        reduced_motion="reduce",
        viewport={"width": 1280, "height": 800},
    )
    try:
        yield context
    finally:
        context.close()
        browser.close()


@pytest.fixture
def page(browser_context):
    """One fresh page per test so test isolation is the default."""

    page = browser_context.new_page()
    try:
        yield page
    finally:
        page.close()
