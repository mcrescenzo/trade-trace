"""`tt console serve` entrypoint (trade-trace-1kkv.2).

Boots the local read-only dashboard. FastAPI + Uvicorn ship in
the `[console]` extra, NOT the base wheel — operators who never
use the dashboard should not pay for the dependency tree. When
the extra is absent, this module's surface still exists and
returns a typed error envelope with the install command.

Per `docs/architecture/console.md`:

- §1 grammar: `tt console serve` (subject-verb).
- §2 browser-open default: open unless `--no-browser`.
- §5 dependency strategy: `[console]` optional extra.
- §6 read-only DB access via `open_database_readonly()`.
- §9–10 banner content: URL, DB path, read-only mode, non-trading
  notice, Logs-deferred status.
"""

from __future__ import annotations

import errno
import socket
import sys
from datetime import UTC
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.storage.paths import resolve_home
from trade_trace.tools.errors import ToolError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

PORT_IN_USE_EXIT_CODE = 73
"""Documented non-zero exit code for "port in use" failures.
Operators script around this; tests pin it."""

_CONSOLE_EXTRA_HINT = (
    "Console requires the [console] extra:\n"
    "    pip install 'trade-trace[console]'"
)


def _import_server_deps() -> tuple[Any, Any] | None:
    """Lazy-import the optional dependencies. Returns
    `(fastapi_module, uvicorn_module)` or `None` if either is
    missing. Wrapped in a function so the import error message is
    deterministic per docs/architecture/console.md §5."""

    try:
        import fastapi  # type: ignore[import-not-found]  # noqa: F401
        import uvicorn  # type: ignore[import-not-found]
    except ImportError:
        return None
    return fastapi, uvicorn


def _build_app(home_path: str) -> Any:
    """Construct the FastAPI app. Kept thin so the
    backend-endpoints bead (.4) builds on a known import shape.
    The MVP app exposes the `/status` self-check; everything else
    lands in .4."""

    deps = _import_server_deps()
    assert deps is not None, "_build_app must not be called without deps"
    fastapi, _ = deps

    app = fastapi.FastAPI(
        title="Trade Trace Console",
        version="0",  # bumped when .4 ships endpoint contracts
        docs_url=None,  # no OpenAPI exposure in MVP
        redoc_url=None,
    )

    @app.get("/status")
    def status() -> dict[str, Any]:
        from datetime import datetime

        from trade_trace.storage.database import (
            ReadOnlyDatabaseError,
            open_database_readonly,
        )
        from trade_trace.storage.paths import db_path as _db_path

        path = _db_path(resolve_home(home_path))
        try:
            db = open_database_readonly(path)
        except ReadOnlyDatabaseError as exc:
            return {
                "db_path": str(path),
                "read_only": True,
                "reason": exc.reason,
                "message": str(exc),
                "logs_deferred": True,
            }
        try:
            schema_version = db.connection.execute(
                "SELECT MAX(version) FROM schema_meta",
            ).fetchone()[0]
            last_event_ts = db.connection.execute(
                "SELECT MAX(created_at) FROM events",
            ).fetchone()[0]
            row_counts = {
                table: db.connection.execute(
                    f"SELECT COUNT(*) FROM {table}",
                ).fetchone()[0]
                for table in ("events", "decisions", "memory_nodes", "strategies", "playbooks")
            }
        finally:
            db.close()
        return {
            "db_path": str(path),
            "read_only": True,
            "schema_version": schema_version,
            "last_event_at": last_event_ts,
            "row_counts": row_counts,
            "lazy_write_handlers_blocked": ["signal.scan", "report.coach"],
            "logs_deferred": True,
            "now": datetime.now(UTC).isoformat(),
        }

    return app


def _format_banner(
    *,
    url: str,
    db_path: str,
    log_status: str = "logs deferred — see trade-trace-jtec",
    read_only: bool = True,
) -> str:
    """Render the startup banner per console.md §10."""

    lines = [
        "Trade Trace Console",
        f"  URL:           {url}",
        f"  DB path:       {db_path}",
        f"  Mode:          {'read-only' if read_only else 'read/write (DEV)'}",
        f"  Logs:          {log_status}",
        "  Notice:        does not execute trades; does not call broker APIs.",
        "                 No outbound network calls.",
    ]
    return "\n".join(lines)


def _open_browser(url: str) -> None:  # pragma: no cover — interactive
    import webbrowser

    try:
        webbrowser.open(url, new=2, autoraise=True)
    except Exception:
        # Operators on headless boxes get the URL on stdout instead.
        pass


def _check_port_free(host: str, port: int) -> None:
    """Pre-flight check so the error path doesn't have to unwind
    a partially-built Uvicorn lifecycle when the port is taken."""

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, errno.EACCES):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"port {port} on {host} is already in use; try `--port "
                f"{port + 1}` or pass `--port=0` to let the OS pick one",
                details={
                    "field": "port", "host": host, "port": port,
                    "errno": exc.errno, "exit_code": PORT_IN_USE_EXIT_CODE,
                },
            ) from exc
        raise
    finally:
        s.close()


def _console_serve(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`console.serve` handler. Returns a dict describing what was
    served; the CLI prints the banner and Uvicorn takes over. In
    tests, callers pass `_dry_run=True` so the function exits before
    actually starting the server."""

    host = str(args.get("host") or DEFAULT_HOST)
    port_arg = args.get("port")
    port = int(port_arg) if port_arg is not None else DEFAULT_PORT
    no_browser = bool(args.get("no_browser") or args.get("_no_browser"))
    allow_non_loopback = bool(
        args.get("allow_non_loopback") or args.get("_allow_non_loopback"),
    )

    if host not in ("127.0.0.1", "localhost", "::1") and not allow_non_loopback:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"refusing to bind {host!r}: non-loopback host requires "
            "--allow-non-loopback (with explicit awareness that the "
            "dashboard becomes reachable from your LAN).",
            details={"field": "host", "value": host,
                     "loopback_hosts": ["127.0.0.1", "localhost", "::1"]},
        )
    if not allow_non_loopback:
        # No-op for default flow; the warning lives in the actual
        # binding path for non-loopback (printed to stderr below).
        pass

    home_str = resolve_home(args.get("home")).as_posix()

    from trade_trace.storage.paths import db_path as _db_path

    url = f"http://{host}:{port}/"
    banner = _format_banner(url=url, db_path=str(_db_path(resolve_home(args.get("home")))))

    if args.get("_dry_run"):
        # Test hook: the CLI/MCP layers can ask "what would you do
        # without actually binding?" and get the assembled answer.
        # The dry-run path intentionally skips the [console] extra
        # check so CI can pin the banner/flag contract without
        # installing FastAPI.
        return {
            "host": host,
            "port": port,
            "url": url,
            "no_browser": no_browser,
            "allow_non_loopback": allow_non_loopback,
            "banner": banner,
            "home": home_str,
        }

    deps = _import_server_deps()
    if deps is None:
        raise ToolError(
            ErrorCode.UNSUPPORTED_CAPABILITY,
            _CONSOLE_EXTRA_HINT,
            details={"missing_extra": "console", "exit_code": 2},
        )

    if host not in ("127.0.0.1", "localhost", "::1") and allow_non_loopback:
        sys.stderr.write(
            f"warning: binding to {host} — the dashboard is reachable from your LAN. "
            "Pass --host=127.0.0.1 to restrict to loopback.\n",
        )

    _check_port_free(host, port)

    app = _build_app(home_str)
    sys.stdout.write(banner + "\n")
    sys.stdout.flush()
    if not no_browser:
        _open_browser(url)

    _, uvicorn = deps
    config = uvicorn.Config(app=app, host=host, port=port, log_config=None)
    server = uvicorn.Server(config=config)
    try:
        server.run()
    except KeyboardInterrupt:  # pragma: no cover — interactive
        sys.stderr.write("\nshutdown\n")
        return {"host": host, "port": port, "url": url, "shutdown": True}
    return {"host": host, "port": port, "url": url, "shutdown": True}


def register_console_tools(registry: ToolRegistry) -> None:
    registry.register(
        "console.serve",
        _console_serve,
        description="Start the local read-only Trade Trace Console dashboard.",
        is_write=False,
        example_minimal={"host": DEFAULT_HOST, "port": DEFAULT_PORT, "_dry_run": True},
    )
