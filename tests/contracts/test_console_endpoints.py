"""Console read-only backend endpoints (trade-trace-1kkv.4).

The endpoint *functions* here take a read-only `sqlite3.Connection`
and return plain dicts. The FastAPI wiring lives in
`trade_trace.console.serve._build_app`. Decoupling the data path
from the HTTP layer lets these tests run without installing the
`[console]` extra (FastAPI / Uvicorn).

Acceptance covered:

- Pure-read: DB file hash unchanged after every endpoint call.
- Pagination contract: list endpoints honor the cursor-based
  Page contract from §13.
- Lazy-write block: tools in the §7 deny set never appear in
  endpoint code paths (asserted by inspection).
- Status endpoint reports the documented fields.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.storage.paths import db_path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _seed(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    mcp_call("journal.init", {"home": str(home)})
    for i in range(5):
        mcp_call(
            "memory.retain",
            {
                "home": str(home),
                "node_type": "observation",
                "body": f"console endpoint seed {i}",
                "idempotency_key": f"console-ep-{i}",
            },
            actor_id="agent:default",
        )
    mcp_call(
        "strategy.create",
        {
            "home": str(home),
            "name": "console-ep-strat",
            "slug": "console-ep-strat",
            "description": "for endpoint tests",
            "idempotency_key": "console-ep-strat",
        },
        actor_id="agent:default",
    )
    return home


def _open_ro(home: Path):
    from trade_trace.storage.database import open_database_readonly

    return open_database_readonly(db_path(home))


def test_status_endpoint_returns_documented_fields(tmp_path: Path):
    from trade_trace.console.endpoints import status

    home = _seed(tmp_path)
    db = _open_ro(home)
    try:
        data = status(db.connection, db_path=db_path(home))
    finally:
        db.close()
    assert data["db_path"].endswith("trade-trace.sqlite")
    assert data["read_only"] is True
    assert data["schema_version"] is not None
    assert data["row_counts"]["memory_nodes"] == 5
    assert data["lazy_write_handlers_blocked"] == ["report.coach", "signal.scan"]
    assert data["logs_available"] is True


def test_journal_events_list_paginates(tmp_path: Path):
    from trade_trace.console.endpoints import journal_events

    home = _seed(tmp_path)
    db = _open_ro(home)
    try:
        page1 = journal_events(db.connection, cursor=None, limit=3)
        assert len(page1.rows) == 3
        assert page1.next_cursor is not None
        page2 = journal_events(db.connection, cursor=page1.next_cursor, limit=3)
    finally:
        db.close()
    # Pages are disjoint when paginated forward.
    ids_page1 = {row["id"] for row in page1.rows}
    ids_page2 = {row["id"] for row in page2.rows}
    assert ids_page1.isdisjoint(ids_page2)


def test_endpoints_do_not_mutate_db_file(tmp_path: Path):
    from trade_trace.console.endpoints import (
        decisions_list,
        journal_events,
        memory_nodes_list,
        status,
        strategies_list,
    )

    home = _seed(tmp_path)
    path = db_path(home)
    before = _sha256(path)
    db = _open_ro(home)
    try:
        status(db.connection, db_path=path)
        journal_events(db.connection, cursor=None, limit=50)
        decisions_list(db.connection, cursor=None, limit=50)
        memory_nodes_list(db.connection, cursor=None, limit=50)
        strategies_list(db.connection, cursor=None, limit=50)
    finally:
        db.close()
    after = _sha256(path)
    assert before == after, "an endpoint mutated the DB file"


def test_endpoints_do_not_dispatch_lazy_write_handlers(tmp_path: Path):
    """The Console endpoints must not *call* `signal.scan` or
    `report.coach`. We inspect the AST so docstring mentions of
    the deny set (which the §7 contract requires) don't trip the
    test — only actual call/dispatch sites do."""

    import ast

    import trade_trace.console.endpoints as endpoints

    forbidden_handlers = {"signal.scan", "report.coach"}
    src = Path(endpoints.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    bad_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value in forbidden_handlers:
                    bad_calls.append(arg.value)
    assert not bad_calls, (
        f"endpoints module appears to call lazy-write handler(s) {bad_calls}"
    )

    # Belt-and-suspenders: the deny set in the module matches the
    # §7 contract values.
    assert set(endpoints.LAZY_WRITE_DENY_SET) == forbidden_handlers


def test_raw_event_json_returns_full_payload(tmp_path: Path):
    from trade_trace.console.endpoints import event_detail

    home = _seed(tmp_path)
    db = _open_ro(home)
    try:
        event = event_detail(db.connection, event_id=1)
    finally:
        db.close()
    assert event is not None
    assert event["id"] == 1
    assert "payload_json" in event
    assert event["event_type"]


def test_event_detail_missing_returns_none(tmp_path: Path):
    from trade_trace.console.endpoints import event_detail

    home = _seed(tmp_path)
    db = _open_ro(home)
    try:
        assert event_detail(db.connection, event_id=999_999) is None
    finally:
        db.close()


def test_list_endpoints_honor_max_limit_clamp(tmp_path: Path):
    """Calling with `limit=10_000` returns at most MAX_LIMIT rows
    — the Console pagination contract from §13."""

    from trade_trace.console.endpoints import journal_events
    from trade_trace.console.pagination import MAX_LIMIT

    home = _seed(tmp_path)
    db = _open_ro(home)
    try:
        page = journal_events(db.connection, cursor=None, limit=10_000)
    finally:
        db.close()
    assert page.limit == MAX_LIMIT


@pytest.mark.parametrize("statement", [
    "INSERT INTO config(key, value, updated_at) VALUES('ev','x','now')",
    "DELETE FROM config",
    "UPDATE config SET value='evil'",
])
def test_status_handle_rejects_writes_via_open_database_readonly(tmp_path: Path, statement: str):
    """Belt-and-suspenders: every Console endpoint goes through
    `open_database_readonly()`, which the readonly tests already
    pin. This test confirms the contract still holds when the
    handle is acquired the way the endpoints acquire it."""

    import sqlite3

    home = _seed(tmp_path)
    db = _open_ro(home)
    try:
        with pytest.raises(sqlite3.OperationalError) as excinfo:
            db.connection.execute(statement)
        assert "readonly" in str(excinfo.value).lower()
    finally:
        db.close()
