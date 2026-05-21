"""Console security headers, CSP, and network-isolation contract
(trade-trace-1kkv.13). The tests use pure-Python entry points so
the `[console]` extra (FastAPI / Uvicorn) is not required."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from trade_trace.console.security import (
    CSP,
    PERMISSIONS_POLICY,
    SECURITY_HEADERS,
    OutboundConnectionAttempted,
    apply_security_headers,
    csp_forbids,
    external_resources_in_markup,
    is_loopback_address,
)


def test_csp_forbids_unsafe_inline_and_unsafe_eval():
    assert csp_forbids("script-src", "'unsafe-inline'")
    assert csp_forbids("script-src", "'unsafe-eval'")
    assert csp_forbids("style-src", "'unsafe-inline'")


def test_csp_allows_only_self_for_script_style_image_font_connect():
    for directive in ("script-src", "style-src", "img-src", "font-src", "connect-src"):
        clause = next(c.strip() for c in CSP.split(";") if c.strip().startswith(directive))
        assert "'self'" in clause, clause
        # Nothing else allowed for the asset-source directives.
        tokens = clause.split()
        # tokens[0] is the directive name; the rest are source expressions.
        for token in tokens[1:]:
            assert token == "'self'", (directive, token, clause)


def test_csp_disallows_framing_and_form_submission():
    assert "frame-ancestors 'none'" in CSP
    assert "form-action 'none'" in CSP


def test_permissions_policy_locks_down_sensitive_features():
    for feature in ("camera=()", "microphone=()", "geolocation=()",
                    "payment=()", "interest-cohort=()"):
        assert feature in PERMISSIONS_POLICY


def test_apply_security_headers_mutates_dict_in_place():
    headers: dict[str, str] = {}
    apply_security_headers(headers)
    assert headers["Content-Security-Policy"] == CSP
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert headers["Cross-Origin-Embedder-Policy"] == "require-corp"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Permissions-Policy"] == PERMISSIONS_POLICY
    assert headers["Cache-Control"] == "no-store"


def test_security_headers_set_is_stable_and_minimal():
    """If a header is added, an explicit test must accompany it.
    This guard exists so a future change can't quietly drop a
    header (e.g., Referrer-Policy) without a corresponding test
    update."""

    expected = {
        "Content-Security-Policy",
        "Cross-Origin-Opener-Policy",
        "Cross-Origin-Embedder-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Cache-Control",
    }
    assert set(SECURITY_HEADERS) == expected


def test_external_resource_detection_in_markup():
    markup = """
    <html>
      <link href="https://cdn.example.com/main.css">
      <img src="//other.example/foo.png">
    </html>
    """
    findings = external_resources_in_markup(markup)
    assert any("cdn.example.com" in f for f in findings)
    assert any("//other.example" in f for f in findings)


def test_self_relative_paths_are_not_flagged():
    markup = """
    <html>
      <link rel="icon" href="/static/favicon.svg">
      <script src="/assets/console.js"></script>
    </html>
    """
    assert external_resources_in_markup(markup) == []


def test_console_static_app_has_no_external_resources():
    """The built SPA must be self-contained: no CDN, analytics,
    remote font, or external chart bundle references."""

    root = Path(__file__).resolve().parents[2] / "src" / "trade_trace" / "console" / "static" / "app"
    bad: list[tuple[Path, list[str]]] = []
    for asset in root.rglob("*"):
        if asset.suffix not in {".html", ".css"}:
            continue
        findings = external_resources_in_markup(asset.read_text(encoding="utf-8"))
        if findings:
            bad.append((asset.relative_to(root), findings))
    assert not bad, f"SPA assets with external resources: {bad}"


def test_is_loopback_helper_recognizes_localhost():
    assert is_loopback_address(("127.0.0.1", 8765))
    assert is_loopback_address("localhost")
    assert is_loopback_address("::1")
    assert is_loopback_address("127.0.0.42")
    assert not is_loopback_address(("8.8.8.8", 53))
    assert not is_loopback_address("example.com")


def test_outbound_socket_fixture_blocks_external_connect(monkeypatch):
    """The Console's test posture is: any non-loopback connect
    attempt during a representative smoke run fails the test.
    The fixture here is the canonical implementation; downstream
    tests `monkeypatch` it onto `socket.socket.connect`."""

    def _guarded_connect(self, address):
        if not is_loopback_address(address):
            raise OutboundConnectionAttempted(
                f"refusing non-loopback connect to {address!r} from Console"
                " test scope (trade-trace-1kkv.13)",
            )
        return None

    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)

    with pytest.raises(OutboundConnectionAttempted):
        _guarded_connect(object(), ("8.8.8.8", 53))
    assert _guarded_connect(object(), ("127.0.0.1", 8765)) is None
