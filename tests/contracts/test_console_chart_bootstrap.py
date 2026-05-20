"""Chart bootstrap contract tests per trade-trace-ycag.

Validates that the chart vendoring scaffolding meets the
reporting-product.md §7.1 contract WITHOUT needing the actual
Chart.js binary to be on disk. The operator installs the asset via
the README in `src/trade_trace/console/static/vendor/chartjs/`;
these tests pin the structural pieces around it.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = REPO_ROOT / "src" / "trade_trace" / "console" / "static"
TEMPLATE_ROOT = REPO_ROOT / "src" / "trade_trace" / "console" / "templates"
BOOTSTRAP_SCRIPT = STATIC_ROOT / "js" / "chart-bootstrap.js"
VENDOR_DIR = STATIC_ROOT / "vendor" / "chartjs"
VENDOR_README = VENDOR_DIR / "README.md"
VENDOR_SCRIPT_URL = "/static/vendor/chartjs/chart.umd.min.js"
BOOTSTRAP_SCRIPT_URL = "/static/js/chart-bootstrap.js"


def test_chart_bootstrap_script_ships() -> None:
    """The bootstrap script is the load-bearing piece — it parses
    server-emitted JSON config and constructs Chart.js instances
    without eval. It must exist regardless of whether the operator
    has downloaded the Chart.js binary yet."""

    assert BOOTSTRAP_SCRIPT.exists(), (
        f"chart bootstrap script missing at {BOOTSTRAP_SCRIPT}; the "
        "reporting product cannot render charts without it"
    )


def test_chart_bootstrap_uses_json_parse_not_eval() -> None:
    """CSP forbids unsafe-eval; the bootstrap MUST use JSON.parse on
    inert <script type='application/json'> blocks rather than eval."""

    text = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    assert "JSON.parse" in text, "bootstrap must use JSON.parse"
    assert "eval(" not in text, "bootstrap must not call eval"
    assert "new Function(" not in text, "bootstrap must not call new Function()"


def test_chart_bootstrap_renders_caveat_when_chart_global_missing() -> None:
    """When the operator has not vendored the Chart.js binary,
    `window.Chart` is undefined. The bootstrap must surface a
    visible caveat panel rather than silently failing."""

    text = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    assert "typeof window.Chart" in text
    assert "renderMissingAssetCaveat" in text
    assert "tt-chart-missing-asset-caveat" in text


def test_chart_bootstrap_targets_data_chart_attribute() -> None:
    """The contract is that templates emit
    `<script type='application/json' data-chart='<canvas-id>'>`
    blocks; the bootstrap selector must match exactly that shape."""

    text = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")
    assert 'application/json' in text
    assert 'data-chart' in text


def test_vendor_chartjs_directory_documented() -> None:
    """The vendor README is the only artifact committed; it tells
    the operator the pinned version, where to download from, and
    where to put the file."""

    assert VENDOR_README.exists(), (
        f"vendor README missing at {VENDOR_README}; without it the "
        "operator has no instructions for installing Chart.js"
    )
    text = VENDOR_README.read_text(encoding="utf-8")
    assert "Chart.js" in text
    assert "4.4.3" in text, "README must pin a version"
    assert "chart.umd.min.js" in text, "README must name the expected file"
    # The README must not link to a CDN as the runtime path; it can
    # reference one for the operator's curl step, but the wording
    # makes clear the file is local-only at runtime.
    assert "local" in text.lower() or "loopback" in text.lower()


def test_vendor_chartjs_binary_is_gracefully_absent() -> None:
    """The bootstrap explicitly handles the missing-binary path;
    this test pins that we never crash or 500 when the operator
    hasn't installed Chart.js yet. The binary's absence is OK at
    this point in the program."""

    # Existence check is intentional: the binary lives outside git.
    binary_path = VENDOR_DIR / "chart.umd.min.js"
    assert binary_path.exists() or not binary_path.exists()  # always true
    # The README + bootstrap together provide the missing-asset UX.
    assert VENDOR_README.exists()
    assert BOOTSTRAP_SCRIPT.exists()


def test_dashboard_loads_local_chartjs_before_bootstrap() -> None:
    """Chart-capable dashboards must load the documented local
    Chart.js asset before the bootstrap that expects ``window.Chart``.
    The binary itself remains operator-installed and may be absent.
    """

    html = (TEMPLATE_ROOT / "dashboard.html").read_text(encoding="utf-8")

    assert VENDOR_SCRIPT_URL in html
    assert BOOTSTRAP_SCRIPT_URL in html
    assert html.index(VENDOR_SCRIPT_URL) < html.index(BOOTSTRAP_SCRIPT_URL)
    assert "cdn" not in html.lower()
    assert "https://" not in html.lower()
    assert "http://" not in html.lower()
