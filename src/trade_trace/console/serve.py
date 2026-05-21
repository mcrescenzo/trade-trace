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
import json
import socket
import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
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
    from fastapi import Query as _Query  # type: ignore[import-not-found]
    from fastapi import Request as _Request  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — gated by _import_server_deps
    _Query = None  # type: ignore[assignment,misc]
    _Request = None  # type: ignore[assignment,misc]

_STATUS_QUERY_DEFAULT = _Query(default=None) if _Query is not None else None
_KIND_QUERY_DEFAULT = _Query(default=None) if _Query is not None else None
_INSTRUMENT_QUERY_DEFAULT = _Query(default=None) if _Query is not None else None
_STRATEGY_QUERY_DEFAULT = _Query(default=None) if _Query is not None else None
_OUTCOME_QUERY_DEFAULT = _Query(default=None) if _Query is not None else None
_DECISION_TYPE_QUERY_DEFAULT = _Query(default=None) if _Query is not None else None

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
    """Construct the FastAPI app.

    The clean-break Console is a read-only JSON API plus a packaged
    React/Vite SPA. FastAPI owns local serving, security headers,
    read-only DB handles, and report dispatch. The browser owns all
    routing and presentation over server-provided data.
    """

    deps = _import_server_deps()
    assert deps is not None, "_build_app must not be called without deps"
    fastapi, _ = deps

    from fastapi.responses import FileResponse, JSONResponse  # type: ignore[import-not-found]
    from fastapi.staticfiles import StaticFiles  # type: ignore[import-not-found]

    from trade_trace.console import endpoints
    from trade_trace.console.pagination import PaginationError
    from trade_trace.console.reporting import (
        SAFE_REPORT_TOOLS,
        ReportAdapterError,
        list_positions,
        list_trades,
        position_detail,
        run_report,
    )
    from trade_trace.console.reporting.filter_state import FilterStateError, decode_filter
    from trade_trace.console.security import apply_security_headers
    from trade_trace.storage.database import (
        ReadOnlyDatabaseError,
        open_database_readonly,
    )
    from trade_trace.storage.paths import db_path as _db_path

    console_root = Path(__file__).resolve().parent
    spa_root = console_root / "static" / "app"
    assets_root = spa_root / "assets"
    index_html = spa_root / "index.html"

    app = fastapi.FastAPI(
        title="Trade Trace Console",
        version="2",
        docs_url=None,
        redoc_url=None,
    )
    if assets_root.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_root)), name="console_assets")
    app.mount("/static", StaticFiles(directory=str(console_root / "static")), name="static")

    def _generated_at() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    @app.exception_handler(ReadOnlyDatabaseError)
    async def _readonly_database_error(request: Any, exc: ReadOnlyDatabaseError) -> Any:
        detail = {
            "type": "readonly_database_error",
            "reason": exc.reason,
            "message": str(exc),
        }
        return JSONResponse(status_code=503, content={"detail": detail})

    @app.exception_handler(PaginationError)
    async def _pagination_error(request: Any, exc: PaginationError) -> Any:
        detail = {
            "type": "pagination_error",
            "message": str(exc),
        }
        return JSONResponse(status_code=400, content={"detail": detail})

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

    def _jsonable(value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return asdict(value)
        if isinstance(value, tuple):
            return [_jsonable(v) for v in value]
        if isinstance(value, list):
            return [_jsonable(v) for v in value]
        if isinstance(value, dict):
            return {k: _jsonable(v) for k, v in value.items()}
        return value

    def _decoded_filter_arg(value: str | None) -> dict[str, Any]:
        try:
            decoded = decode_filter(value)
        except FilterStateError as exc:
            # Do not echo the raw query value back in HTTP error details:
            # the filter can contain user-controlled/high-cardinality state
            # and malformed values are not useful to render verbatim.
            details = dict(exc.details)
            details.pop("raw", None)
            raise fastapi.HTTPException(
                status_code=400,
                detail={
                    "type": "filter_state_error",
                    "message": str(exc),
                    "details": details,
                },
            ) from exc
        return decoded.model_dump(mode="json", exclude_defaults=True)

    # -- JSON API ----------------------------------------------------------

    @app.get("/status")
    @app.get("/api/console/status")
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
                "logs_available": True,
            }
        try:
            data = endpoints.status(db.connection, db_path=path)
            data["generated_at"] = _generated_at()
            return data
        finally:
            db.close()

    @app.get("/api/console/catalog")
    def catalog() -> dict[str, Any]:
        route_catalog = json.loads(
            (Path(__file__).resolve().parent / "route_catalog.json").read_text(encoding="utf-8")
        )
        return {
            "routes": [route["path"] for route in route_catalog],
            "report_tools": list(SAFE_REPORT_TOOLS),
            "lazy_write_handlers_blocked": list(endpoints.LAZY_WRITE_DENY_SET),
        }

    def _bind_list(route: str, fn: Any) -> None:
        @app.get(route)
        def _handler(cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
            _, db = _open()
            try:
                return _page_to_dict(fn(db.connection, cursor=cursor, limit=limit))
            finally:
                db.close()

        _handler.__name__ = fn.__name__

    @app.get("/api/console/events")
    def journal_events(
        cursor: str | None = None,
        limit: int = 50,
        request_id: str | None = None,
        actor_id: str | None = None,
        subject_kind: str | None = None,
        subject_id: str | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        _, db = _open()
        try:
            page = endpoints.journal_events(
                db.connection,
                cursor=cursor,
                limit=limit,
                request_id=request_id,
                actor_id=actor_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                event_type=event_type,
            )
            return _page_to_dict(page)
        finally:
            db.close()

    _bind_list("/api/console/memory-nodes", endpoints.memory_nodes_list)
    _bind_list("/api/console/strategies", endpoints.strategies_list)
    _bind_list("/api/console/playbooks", endpoints.playbooks_list)
    _bind_list("/api/console/instruments", endpoints.instruments_list)
    _bind_list("/api/console/forecasts", endpoints.forecasts_list)
    _bind_list("/api/console/outcomes", endpoints.outcomes_list)

    @app.get("/api/console/decisions")
    def decisions(
        cursor: str | None = None,
        limit: int = 50,
        decision_type: list[str] | None = _DECISION_TYPE_QUERY_DEFAULT,
        instrument_id: str | None = None,
    ) -> dict[str, Any]:
        _, db = _open()
        try:
            page = endpoints.decisions_list(
                db.connection,
                cursor=cursor,
                limit=limit,
                decision_type=decision_type,
                instrument_id=instrument_id,
            )
            return _page_to_dict(page)
        finally:
            db.close()

    @app.get("/api/console/trades")
    def trades(
        cursor: str | None = None,
        limit: int = 50,
        strategy_id: list[str] | None = _STRATEGY_QUERY_DEFAULT,
        instrument_id: list[str] | None = _INSTRUMENT_QUERY_DEFAULT,
        decision_type: list[str] | None = _DECISION_TYPE_QUERY_DEFAULT,
        opened_from: str | None = None,
        opened_to: str | None = None,
    ) -> dict[str, Any]:
        _, db = _open()
        try:
            page = list_trades(
                db.connection,
                cursor=cursor,
                limit=limit,
                strategy_id=strategy_id,
                instrument_id=instrument_id,
                decision_type=decision_type,
                opened_from=opened_from,
                opened_to=opened_to,
            )
            return _jsonable(_page_to_dict(page))
        finally:
            db.close()

    @app.get("/api/console/positions")
    def positions(
        cursor: str | None = None,
        limit: int = 50,
        status: list[str] | None = _STATUS_QUERY_DEFAULT,
        kind: list[str] | None = _KIND_QUERY_DEFAULT,
        instrument_id: list[str] | None = _INSTRUMENT_QUERY_DEFAULT,
        strategy_id: list[str] | None = _STRATEGY_QUERY_DEFAULT,
        opened_from: str | None = None,
        opened_to: str | None = None,
        outcome: list[str] | None = _OUTCOME_QUERY_DEFAULT,
    ) -> dict[str, Any]:
        _, db = _open()
        try:
            page = list_positions(
                db.connection,
                cursor=cursor,
                limit=limit,
                status=status,
                kind=kind,
                instrument_id=instrument_id,
                strategy_id=strategy_id,
                opened_from=opened_from,
                opened_to=opened_to,
                outcome=outcome,
            )
            return _jsonable(_page_to_dict(page))
        finally:
            db.close()

    @app.get("/api/console/positions/{position_id}")
    def position(position_id: str) -> dict[str, Any]:
        _, db = _open()
        try:
            detail = position_detail(db.connection, position_id)
        finally:
            db.close()
        if detail is None:
            raise fastapi.HTTPException(status_code=404, detail=f"position {position_id} not found")
        return _jsonable(detail)

    @app.get("/api/console/raw/{event_id}")
    @app.get("/api/console/events/{event_id}")
    def event_detail(event_id: int) -> dict[str, Any]:
        _, db = _open()
        try:
            event = endpoints.event_detail(db.connection, event_id=event_id)
        finally:
            db.close()
        if event is None:
            raise fastapi.HTTPException(status_code=404, detail=f"event {event_id} not found")
        return event

    @app.get("/api/console/events/{event_id}/related")
    def event_related(event_id: int) -> dict[str, Any]:
        _, db = _open()
        try:
            related = endpoints.event_related_records(db.connection, event_id=event_id)
        finally:
            db.close()
        if related is None:
            raise fastapi.HTTPException(status_code=404, detail=f"event {event_id} not found")
        return related

    @app.get("/api/console/record-events")
    def record_events(subject_kind: str, subject_id: str, limit: int = 20) -> list[dict[str, Any]]:
        _, db = _open()
        try:
            return endpoints.record_events(
                db.connection,
                subject_kind=subject_kind,
                subject_id=subject_id,
                limit=limit,
            )
        finally:
            db.close()

    @app.get("/api/console/logs")
    def logs(level: str | None = None, tail: int = 200) -> dict[str, Any]:
        from trade_trace.console.logs import logs_context

        return logs_context(
            home=resolve_home(home_path),
            tail=max(10, min(int(tail), 2000)),
            level_filter=level or None,
        )

    @app.post("/api/console/reports/{tool}/run")
    def report_run(tool: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(payload or {})
        if "filter" not in args:
            args["filter"] = {}
        try:
            ctx = run_report(tool, args, home=str(resolve_home(home_path)))
        except ReportAdapterError as exc:
            raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
        return _jsonable(ctx)

    @app.get("/api/console/reports/{tool}/export")
    def report_export(tool: str, f: str | None = None) -> dict[str, Any]:
        filter_arg = _decoded_filter_arg(f)
        try:
            ctx = run_report(
                tool,
                {"filter": filter_arg},
                home=str(resolve_home(home_path)),
            )
        except ReportAdapterError as exc:
            raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "tool": tool,
            "filter": filter_arg,
            "request_id": ctx.evidence.request_id,
            "as_of": ctx.as_of,
            "record_ids": ctx.evidence.record_ids,
            "exported_at": datetime.now(UTC).isoformat(),
            "envelope": ctx.raw_envelope,
        }

    # -- SPA fallback ------------------------------------------------------

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Any:
        if full_path.startswith("api/"):
            raise fastapi.HTTPException(status_code=404, detail="not found")
        if not index_html.exists():
            raise fastapi.HTTPException(
                status_code=503,
                detail="Console app assets are missing; run npm --prefix frontend/console run build",
            )
        return FileResponse(index_html, media_type="text/html")

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
                f"{port + 1}` or choose another explicit free port",
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
    if port == 0:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "--port=0 is not supported for `tt console serve` because the "
            "startup banner and browser URL must name the actual bound port; "
            "choose an explicit free port instead (for example, --port 8766).",
            details={"field": "port", "port": port},
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
