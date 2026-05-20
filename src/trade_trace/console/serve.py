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

# FastAPI ships in the [console] extra, so this import is guarded.
# When the extra is absent, _build_app is never called (see
# _console_serve below), so the only consumers of `_Request` are
# the route handlers' annotations — which FastAPI evaluates via
# `get_type_hints()` against this module's globals. A local import
# inside `_build_app` is *not* visible to that lookup, which is
# why an earlier `request: Any` (and a later `request: _Request`
# referencing a local binding) caused FastAPI to treat `request`
# as a query parameter and return 422 on every page.
try:
    from fastapi import Request as _Request  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — gated by _import_server_deps
    _Request = None  # type: ignore[assignment,misc]

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
    def overview_html(request: _Request) -> Any:
        """Reporting-lane Overview per trade-trace-w422.

        Replaces the legacy DB-meta snapshot with a P&L / risk roll-up
        dashboard built on the safe-report adapter. The legacy
        `pages.overview_context` function still exists for tests that
        pin its shape, but this route now serves the canonical reader
        view per reporting-product.md §3 (Reporting lane Overview)."""

        return _render_dashboard(request, pages.dashboard_overview_context)

    @app.get("/overview-legacy", response_class=HTMLResponse, include_in_schema=False)
    def overview_legacy_html(request: _Request) -> Any:
        """Legacy DB-meta snapshot kept under a developer-lane URL so
        operators auditing schema_version / row counts can still reach
        it. Linked from the Audit / Integrity page when needed."""

        path, db = _open()
        try:
            ctx = pages.overview_context(db.connection, db_path=path)
        finally:
            db.close()
        return _render(request, "overview.html", ctx)

    @app.get("/journal", response_class=HTMLResponse)
    def journal_html(request: _Request, cursor: str | None = None, limit: int = 50) -> Any:
        _, db = _open()
        try:
            ctx = pages.journal_context(db.connection, cursor=cursor, limit=limit)
        finally:
            db.close()
        return _render(request, "journal.html", ctx)

    @app.get("/decisions", response_class=HTMLResponse)
    def decisions_html(request: _Request, cursor: str | None = None, limit: int = 50) -> Any:
        _, db = _open()
        try:
            ctx = pages.decisions_context(db.connection, cursor=cursor, limit=limit)
        finally:
            db.close()
        return _render(request, "decisions.html", ctx)

    @app.get("/decisions/{decision_id}", response_class=HTMLResponse)
    def decision_detail_html(request: _Request, decision_id: str) -> Any:
        _, db = _open()
        try:
            ctx = pages.decision_detail_context(db.connection, decision_id=decision_id)
        finally:
            db.close()
        if ctx is None:
            raise fastapi.HTTPException(status_code=404, detail=f"decision {decision_id} not found")
        return _render(request, "decision_detail.html", ctx)

    @app.get("/positions/{position_id}", response_class=HTMLResponse)
    def position_detail_html(request: _Request, position_id: str) -> Any:
        """Per-position audit page per bead trade-trace-svp2.

        Backed by `console.reporting.position_detail`. Renders the
        lifecycle projection, full chronological position_events
        lineage, and the named missing-data caveats (open_no_mark,
        missing_risk_budget, no_strategy)."""

        _, db = _open()
        try:
            ctx = pages.position_detail_context(db.connection, position_id=position_id)
        finally:
            db.close()
        if ctx is None:
            raise fastapi.HTTPException(status_code=404, detail=f"position {position_id} not found")
        return _render(request, "position_detail.html", ctx)

    def _render_dashboard(request: _Request, builder: Any, template: str = "dashboard.html") -> Any:
        """Common error wrapper for the report-backed dashboards.
        The adapter raises `ReportAdapterError` on validation failures
        / unsupported tools / lazy-write attempts; the route surfaces
        those as 400s rather than letting them bubble as 500s."""

        from trade_trace.console.reporting import ReportAdapterError

        home, db = _open()
        try:
            try:
                ctx = builder(str(home))
            except ReportAdapterError as exc:
                raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            db.close()
        return _render(request, template, ctx)

    @app.get("/reports/pnl", response_class=HTMLResponse)
    def dashboard_pnl_html(request: _Request) -> Any:
        return _render_dashboard(request, pages.dashboard_pnl_context)

    @app.get("/reports/risk", response_class=HTMLResponse)
    def dashboard_risk_html(request: _Request) -> Any:
        return _render_dashboard(request, pages.dashboard_risk_context)

    @app.get("/reports/performance", response_class=HTMLResponse)
    def dashboard_performance_html(request: _Request) -> Any:
        return _render_dashboard(request, pages.dashboard_performance_context)

    @app.get("/reports/strategy", response_class=HTMLResponse)
    def dashboard_strategy_html(request: _Request) -> Any:
        return _render_dashboard(request, pages.dashboard_strategy_context)

    @app.get("/reports/decisions", response_class=HTMLResponse)
    def dashboard_decision_intelligence_html(request: _Request) -> Any:
        return _render_dashboard(request, pages.dashboard_decision_intelligence_context)

    @app.get("/reports/calibration", response_class=HTMLResponse)
    def dashboard_calibration_full_html(request: _Request) -> Any:
        return _render_dashboard(request, pages.dashboard_calibration_context)

    @app.get("/evidence", response_class=HTMLResponse)
    def dashboard_evidence_html(request: _Request) -> Any:
        return _render_dashboard(request, pages.dashboard_evidence_context)

    @app.get("/reports/compare", response_class=HTMLResponse)
    def dashboard_compare_html(
        request: _Request,
        base_report: str = "calibration",
        group_by: str = "strategy_id",
    ) -> Any:
        """Comparison builder per bead trade-trace-sqtq. Wraps
        report.compare(base_report, group_by, filter={}). Defaults
        compare calibration across strategies; the per-page form
        rebinds base_report (calibration|pnl) and group_by."""

        from trade_trace.console.reporting import ReportAdapterError

        home, db = _open()
        try:
            try:
                ctx = pages.dashboard_compare_context(
                    str(home), base_report=base_report, group_by=group_by,
                )
            except ReportAdapterError as exc:
                raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            db.close()
        return _render(request, "dashboard.html", ctx)

    @app.get("/reports/{tool}/export.json")
    def report_export_json(tool: str) -> Any:
        """Read-only export packet per bead trade-trace-sqtq. Returns
        the report's full envelope + filter + request_id + as_of +
        record_ids + exported_at as JSON, with no credentials. The
        adapter enforces the safe-report allowlist; any
        non-allowlisted tool surfaces as a 400."""

        from trade_trace.console.reporting import ReportAdapterError

        # The CLI invocation uses dots in tool names; the URL path
        # uses the same dotted name (e.g. `/reports/report.pnl/export.json`).
        home, db = _open()
        try:
            try:
                packet = pages.report_export_packet(home=str(home), tool=tool)
            except ReportAdapterError as exc:
                raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            db.close()
        return packet

    @app.get("/trades", response_class=HTMLResponse)
    def trades_html(
        request: _Request,
        cursor: str | None = None,
        limit: int = 50,
        strategy_id: str | None = None,
        instrument_id: str | None = None,
        decision_type: str | None = None,
    ) -> Any:
        """Reporting-lane Trades index per bead trade-trace-q2li.

        Read-only paginated view of trading-typed decisions; backed by
        `console.reporting.list_trades`. Query params double as the
        per-page filter form's persistence layer; the global
        ReportFilter URL state (the `f=` parameter from hayy) is
        consumed by the dashboard pages that render aggregate metrics.
        """

        _, db = _open()
        try:
            ctx = pages.trades_context(
                db.connection, cursor=cursor, limit=limit,
                strategy_id=strategy_id or None,
                instrument_id=instrument_id or None,
                decision_type=decision_type or None,
            )
        finally:
            db.close()
        return _render(request, "trades.html", ctx)

    @app.get("/reports", response_class=HTMLResponse)
    def reports_html(request: _Request) -> Any:
        _, db = _open()
        try:
            ctx = pages.reports_context(db.connection)
        finally:
            db.close()
        return _render(request, "reports.html", ctx)

    @app.get("/calibration", response_class=HTMLResponse)
    def calibration_html(request: _Request) -> Any:
        _, db = _open()
        try:
            ctx = pages.calibration_context(db.connection)
        finally:
            db.close()
        return _render(request, "calibration.html", ctx)

    @app.get("/strategies", response_class=HTMLResponse)
    def strategies_html(request: _Request, cursor: str | None = None, limit: int = 50) -> Any:
        _, db = _open()
        try:
            ctx = pages.strategies_context(db.connection, cursor=cursor, limit=limit)
        finally:
            db.close()
        return _render(request, "strategies.html", ctx)

    @app.get("/playbooks", response_class=HTMLResponse)
    def playbooks_html(request: _Request, cursor: str | None = None, limit: int = 50) -> Any:
        _, db = _open()
        try:
            ctx = pages.playbooks_context(db.connection, cursor=cursor, limit=limit)
        finally:
            db.close()
        return _render(request, "playbooks.html", ctx)

    @app.get("/integrity", response_class=HTMLResponse)
    def integrity_html(request: _Request) -> Any:
        _, db = _open()
        try:
            ctx = pages.integrity_context(db.connection)
        finally:
            db.close()
        return _render(request, "integrity.html", ctx)

    @app.get("/logs", response_class=HTMLResponse)
    def logs_html(request: _Request, level: str | None = None, tail: int = 200) -> Any:
        from trade_trace.console.logs import logs_context

        ctx = logs_context(
            home=resolve_home(home_path),
            tail=max(10, min(int(tail), 2000)),
            level_filter=level or None,
        )
        return _render(request, "logs.html", ctx)

    @app.get("/raw", response_class=HTMLResponse)
    def raw_html(request: _Request, event_id: int | None = None) -> Any:
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
    log_status: str = "logs at <home>/logs/trade-trace.log",
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
