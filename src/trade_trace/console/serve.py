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
from pathlib import Path
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
    """Construct the FastAPI app. Page handlers in
    `trade_trace.console.pages` produce render contexts; this
    function maps HTML routes to those handlers and JSON data
    routes to `trade_trace.console.endpoints`. The lazy-write
    deny set from console.md §7 is enforced by the pages /
    endpoints modules never *calling* either handler."""

    deps = _import_server_deps()
    assert deps is not None, "_build_app must not be called without deps"
    fastapi, _ = deps

    from fastapi.responses import HTMLResponse  # type: ignore[import-not-found]
    from fastapi.staticfiles import StaticFiles  # type: ignore[import-not-found]
    from fastapi.templating import Jinja2Templates  # type: ignore[import-not-found]

    from trade_trace.console import endpoints, pages
    from trade_trace.console.security import apply_security_headers
    from trade_trace.storage.database import (
        ReadOnlyDatabaseError,
        open_database_readonly,
    )
    from trade_trace.storage.paths import db_path as _db_path

    console_root = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(console_root / "templates"))

    app = fastapi.FastAPI(
        title="Trade Trace Console",
        version="1",
        docs_url=None,
        redoc_url=None,
    )
    app.mount(
        "/static",
        StaticFiles(directory=str(console_root / "static")),
        name="static",
    )

    @app.middleware("http")
    async def _security_headers(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        apply_security_headers(response.headers)
        return response

    def _open():
        path = _db_path(resolve_home(home_path))
        return path, open_database_readonly(path)

    def _page_to_dict(page: Any) -> dict[str, Any]:
        return {"rows": page.rows, "next_cursor": page.next_cursor, "limit": page.limit}

    def _render(request: Any, template_name: str, context: dict[str, Any]) -> Any:
        return templates.TemplateResponse(request, template_name, context)

    # -- HTML pages --------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def overview_html(request: Any) -> Any:
        path, db = _open()
        try:
            ctx = pages.overview_context(db.connection, db_path=path)
        finally:
            db.close()
        return _render(request, "overview.html", ctx)

    @app.get("/journal", response_class=HTMLResponse)
    def journal_html(request: Any, cursor: str | None = None, limit: int = 50) -> Any:
        _, db = _open()
        try:
            ctx = pages.journal_context(db.connection, cursor=cursor, limit=limit)
        finally:
            db.close()
        return _render(request, "journal.html", ctx)

    @app.get("/decisions", response_class=HTMLResponse)
    def decisions_html(request: Any, cursor: str | None = None, limit: int = 50) -> Any:
        _, db = _open()
        try:
            ctx = pages.decisions_context(db.connection, cursor=cursor, limit=limit)
        finally:
            db.close()
        return _render(request, "decisions.html", ctx)

    @app.get("/decisions/{decision_id}", response_class=HTMLResponse)
    def decision_detail_html(request: Any, decision_id: str) -> Any:
        _, db = _open()
        try:
            ctx = pages.decision_detail_context(db.connection, decision_id=decision_id)
        finally:
            db.close()
        if ctx is None:
            raise fastapi.HTTPException(status_code=404, detail=f"decision {decision_id} not found")
        return _render(request, "decision_detail.html", ctx)

    @app.get("/reports", response_class=HTMLResponse)
    def reports_html(request: Any) -> Any:
        _, db = _open()
        try:
            ctx = pages.reports_context(db.connection)
        finally:
            db.close()
        return _render(request, "reports.html", ctx)

    @app.get("/calibration", response_class=HTMLResponse)
    def calibration_html(request: Any) -> Any:
        _, db = _open()
        try:
            ctx = pages.calibration_context(db.connection)
        finally:
            db.close()
        return _render(request, "calibration.html", ctx)

    @app.get("/strategies", response_class=HTMLResponse)
    def strategies_html(request: Any, cursor: str | None = None, limit: int = 50) -> Any:
        _, db = _open()
        try:
            ctx = pages.strategies_context(db.connection, cursor=cursor, limit=limit)
        finally:
            db.close()
        return _render(request, "strategies.html", ctx)

    @app.get("/playbooks", response_class=HTMLResponse)
    def playbooks_html(request: Any, cursor: str | None = None, limit: int = 50) -> Any:
        _, db = _open()
        try:
            ctx = pages.playbooks_context(db.connection, cursor=cursor, limit=limit)
        finally:
            db.close()
        return _render(request, "playbooks.html", ctx)

    @app.get("/integrity", response_class=HTMLResponse)
    def integrity_html(request: Any) -> Any:
        _, db = _open()
        try:
            ctx = pages.integrity_context(db.connection)
        finally:
            db.close()
        return _render(request, "integrity.html", ctx)

    @app.get("/raw", response_class=HTMLResponse)
    def raw_html(request: Any, event_id: int | None = None) -> Any:
        _, db = _open()
        try:
            ctx = pages.raw_context(db.connection, event_id=event_id)
        finally:
            db.close()
        return _render(request, "raw.html", ctx)

    # -- JSON data endpoints ----------------------------------------------

    @app.get("/status")
    def status() -> dict[str, Any]:
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
            return endpoints.status(db.connection, db_path=path)
        finally:
            db.close()

    def _bind_list(route: str, fn: Any) -> None:
        @app.get(route)
        def _handler(cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
            _, db = _open()
            try:
                return _page_to_dict(fn(db.connection, cursor=cursor, limit=limit))
            finally:
                db.close()

        _handler.__name__ = fn.__name__

    _bind_list("/api/events", endpoints.journal_events)
    _bind_list("/api/decisions", endpoints.decisions_list)
    _bind_list("/api/memory_nodes", endpoints.memory_nodes_list)
    _bind_list("/api/strategies", endpoints.strategies_list)
    _bind_list("/api/playbooks", endpoints.playbooks_list)
    _bind_list("/api/instruments", endpoints.instruments_list)
    _bind_list("/api/forecasts", endpoints.forecasts_list)
    _bind_list("/api/outcomes", endpoints.outcomes_list)

    @app.get("/api/events/{event_id}")
    def event_detail(event_id: int) -> dict[str, Any]:
        _, db = _open()
        try:
            event = endpoints.event_detail(db.connection, event_id=event_id)
        finally:
            db.close()
        if event is None:
            raise fastapi.HTTPException(status_code=404, detail=f"event {event_id} not found")
        return event

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
