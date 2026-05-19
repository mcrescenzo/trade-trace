"""`tt console serve` CLI registration + dependency strategy
(trade-trace-1kkv.2).

These tests pin:

- The `console.serve` tool is registered in the default registry.
- The `tt console serve` CLI invocation surface accepts the flags
  named in `docs/architecture/console.md` (§1–§2).
- Non-loopback host requires `--allow-non-loopback`.
- Missing the `[console]` extra returns the documented
  install-instruction error.
- Port-in-use produces a typed error with the documented exit
  code, not a traceback.
- The startup banner mentions URL, DB path, read-only mode,
  non-trading notice, and Logs-deferred status (§10).
"""

from __future__ import annotations

import socket
from pathlib import Path

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call


def _serve_dry_run(home: Path, **overrides):
    """Invoke `console.serve` with `_dry_run=True` so the function
    assembles the banner and config without binding a socket."""

    args = {"home": str(home), "_dry_run": True, **overrides}
    return mcp_call("console.serve", args, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True,
    )


def test_console_serve_tool_is_registered():
    assert "console.serve" in default_registry().names()


def test_dry_run_returns_default_host_and_port(tmp_path: Path):
    env = _serve_dry_run(tmp_path)
    assert env["ok"] is True, env
    data = env["data"]
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 8765
    assert data["url"] == "http://127.0.0.1:8765/"


def test_non_loopback_host_requires_explicit_opt_in(tmp_path: Path):
    env = _serve_dry_run(tmp_path, host="0.0.0.0")
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "host"


def test_non_loopback_host_with_opt_in_succeeds(tmp_path: Path):
    env = _serve_dry_run(tmp_path, host="0.0.0.0", _allow_non_loopback=True)
    assert env["ok"] is True, env
    assert env["data"]["host"] == "0.0.0.0"
    assert env["data"]["allow_non_loopback"] is True


def test_banner_includes_required_fields(tmp_path: Path):
    env = _serve_dry_run(tmp_path)
    banner = env["data"]["banner"]
    assert "URL:" in banner
    assert "DB path:" in banner
    assert "read-only" in banner
    assert "does not execute trades" in banner
    assert "logs deferred" in banner.lower()


def test_missing_console_extra_returns_typed_error(tmp_path: Path, monkeypatch):
    """When the `[console]` extra is not installed, a real
    `tt console serve` (not dry-run) returns a typed
    UNSUPPORTED_CAPABILITY envelope pointing at the install
    command. The dry-run path short-circuits before the import
    check so we force the real path by passing `_dry_run=False`."""

    # Stub the dep importer to simulate the missing extra.
    import trade_trace.console.serve as serve_module

    monkeypatch.setattr(serve_module, "_import_server_deps", lambda: None)

    env = mcp_call(
        "console.serve",
        {"home": str(tmp_path), "_dry_run": False},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert "pip install 'trade-trace[console]'" in env["error"]["message"]
    assert env["error"]["details"]["missing_extra"] == "console"


def test_port_in_use_returns_typed_error_with_exit_code(tmp_path: Path, monkeypatch):
    """`tt console serve` on a held port surfaces the port + a
    documented exit code instead of a traceback. The test binds a
    socket then asks the tool to bind the same port."""

    import trade_trace.console.serve as serve_module

    monkeypatch.setattr(serve_module, "_import_server_deps",
                        lambda: (object(), object()))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    held_port = sock.getsockname()[1]
    sock.listen(1)
    try:
        env = mcp_call(
            "console.serve",
            {"home": str(tmp_path), "port": held_port, "_dry_run": False},
            actor_id="agent:default",
        ).model_dump(mode="json", exclude_none=True)
    finally:
        sock.close()

    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "port"
    assert env["error"]["details"]["port"] == held_port
    assert env["error"]["details"]["exit_code"] == serve_module.PORT_IN_USE_EXIT_CODE


def test_pyproject_declares_console_extra():
    """The `[console]` extra ships in the wheel's metadata so
    `pip install 'trade-trace[console]'` works after publish."""

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "\nconsole = [" in text, "pyproject.toml missing the [console] extra"
    assert "fastapi" in text
    assert "uvicorn" in text
    assert "jinja2" in text
