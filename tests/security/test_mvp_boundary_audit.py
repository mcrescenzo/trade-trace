"""MVP boundary audit per bead trade-trace-r0v.

The PRD §2.8 product boundary is explicit: Trade Trace is a local journal
+ memory + calibration substrate. It does NOT execute trades, query
external venues for market data, handle execution credentials, or run a
web viewer. This file pins the boundary with grep-style audits over the
shipped surface (registry, source files, doc text).

Failures here are signals that a feature crept into MVP scope. The audit
is deliberately strict — any match in the forbidden-pattern list is a
gate failure.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from trade_trace.core import default_registry

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


def _iter_python_sources() -> list[Path]:
    return sorted(p for p in SRC_ROOT.rglob("*.py")
                  if "__pycache__" not in p.parts)


def _registered_tool_names() -> list[str]:
    return list(default_registry().names())


# -- 1. forbidden-substring audit over source ----------------


FORBIDDEN_PATTERNS = [
    # trade execution
    ("trade_execution",
     re.compile(r"\b(execute_trade|place_order|submit_order|order_submit)\b")),
    # broker integration
    ("broker_integration",
     re.compile(r"\b(broker_api|broker_client|signing_key)\b")),
    # market-data fetching
    ("market_data_fetch",
     re.compile(
         r"\b(fetch_market|fetch_price|fetch_snapshot|"
         r"data_provider|venue_query)\b")),
    # HTTP/SSE transport (the in-process MCP shim is allowed; HTTP is not)
    ("http_transport",
     re.compile(r"\b(http_server|sse_endpoint|websocket_server)\b")),
    # web viewer / dashboard
    ("web_viewer",
     re.compile(r"\b(web_dashboard|browser_ui|html_dashboard)\b")),
]


@pytest.mark.parametrize("kind,pattern", FORBIDDEN_PATTERNS)
def test_no_source_file_matches_forbidden_pattern(kind, pattern):
    offending: list[tuple[str, str]] = []
    for path in _iter_python_sources():
        text = path.read_text(encoding="utf-8")
        match = pattern.search(text)
        if match:
            offending.append((str(path.relative_to(SRC_ROOT)), match.group(0)))
    assert offending == [], (
        f"forbidden pattern {kind!r} matched in source: {offending}"
    )


# -- 2. deferred report names not in registry --------------


@pytest.mark.parametrize("deferred_tool", [
    "report.r_multiple",
])
def test_deferred_report_tools_not_registered(deferred_tool):
    """P1/P2 report names must NOT be in the shipped registry. The
    contract surfaces (review.bundle, journal.rescan_scoring) are
    allowed because they return UNSUPPORTED_CAPABILITY at runtime."""

    assert deferred_tool not in _registered_tool_names(), (
        f"deferred tool {deferred_tool!r} unexpectedly registered"
    )


# -- 3. memory tools: positive + negative ------------------


MEMORY_IN_SCOPE = (
    "memory.retain", "memory.reflect", "memory.link", "memory.recall",
    "reflection.prompt_for_outcome",
)
MEMORY_OUT_OF_SCOPE = (
    "memory.expire", "memory.purge", "memory.subscribe", "memory.bulk_delete",
)


@pytest.mark.parametrize("tool", MEMORY_IN_SCOPE)
def test_memory_tool_in_scope(tool):
    assert tool in _registered_tool_names()


@pytest.mark.parametrize("tool", MEMORY_OUT_OF_SCOPE)
def test_memory_tool_out_of_scope(tool):
    """memory.expire / .purge / .subscribe / .bulk_delete are explicitly
    NOT in MVP scope (per PRD §2.8 + memory-layer.md §12 deferrals)."""

    assert tool not in _registered_tool_names(), (
        f"out-of-scope memory tool {tool!r} unexpectedly registered"
    )


# -- 4. decision.add does not silently accept declared_risk_* args


def test_decision_add_persists_declared_risk_args_after_8z2(tmp_path):
    """Per bead trade-trace-8z2: decision.add now plumbs the P1 risk
    columns (declared_risk_amount, declared_risk_unit, expected_edge,
    expected_edge_after_costs, cost_basis_estimate,
    risk_reward_estimate) through to the row. The previous boundary
    test asserted they were silently dropped; the boundary moved when
    8z2 implemented the write surface."""

    from trade_trace.mcp_server import mcp_call

    home = tmp_path / "home"
    mcp_call("journal.init", {"home": str(home)})
    venue = mcp_call("venue.add", {
        "home": str(home), "name": "PM", "kind": "prediction_market",
    }).data["id"]
    inst = mcp_call("instrument.add", {
        "home": str(home), "venue_id": venue,
        "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    env = mcp_call("decision.add", {
        "home": str(home), "type": "skip",
        "instrument_id": inst, "reason": "x",
        "declared_risk_amount": 100.0,
        "declared_risk_unit": "USD",
        "idempotency_key": "00000000-0000-4000-8000-r0v-risk-01",
    })
    assert env.ok, env
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT declared_risk_amount, declared_risk_unit FROM decisions "
            "WHERE id = ?", (env.data["id"],),
        ).fetchone()
    finally:
        db.close()
    assert row[0] == 100.0
    assert row[1] == "USD"


# -- 5. credential-shaped column-name audit ----------------


def test_no_credential_columns_in_schema(tmp_path):
    """Reaffirms the test_no_credentials.py invariant: no DB column name
    in the shipped schema matches the credential-shape regex.

    Duplicates the contract from tests/security/test_no_credentials.py
    intentionally — the boundary audit is its own QC gate."""

    from trade_trace.mcp_server import mcp_call
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    home = tmp_path / "home"
    mcp_call("journal.init", {"home": str(home)})
    from tests.security._schema_audit import iter_table_columns

    db = open_database(db_path(home), create_parent=False)
    credential_re = re.compile(
        r"wallet|broker|seed|signing|private_key|api_key", re.IGNORECASE,
    )
    try:
        offending: list[tuple[str, str]] = [
            (table, col)
            for table, col in iter_table_columns(db.connection)
            if credential_re.search(col)
        ]
    finally:
        db.close()
    assert offending == [], (
        f"credential-shaped column names in schema: {offending}"
    )


# -- 6. shipped report tool list pinned -------------------


SHIPPED_REPORTS = {
    "report.calibration",
    "report.calibration_integrity",
    "report.source_quality",
    "report.audit_readiness",
    "report.mistakes",
    "report.strengths",
    "report.pnl",
    "report.risk",
    "report.opportunity",
    "report.watchlist",
    "report.unscored_forecasts",
    "report.decision_velocity",
    "report.playbook_adherence",
    "report.coach",
    "report.compare",
    "report.current_exposure",
    "report.exposure_anomalies",
    "report.filter_schema",
    "report.lifecycle",
    "report.work_queue",
    "report.open_positions",
    "report.recall_receipts",
    "report.strategy_performance",
}


def test_shipped_report_tool_set_is_locked():
    """Pin the report.* surface so a new shipped report adds an explicit
    line here (and a new deferred report adds a line to
    test_deferred_report_tools_not_registered)."""

    names = set(_registered_tool_names())
    shipped_reports = {n for n in names if n.startswith("report.")}
    assert shipped_reports == SHIPPED_REPORTS, (
        f"shipped report set drifted from pin. "
        f"added: {shipped_reports - SHIPPED_REPORTS}; "
        f"removed: {SHIPPED_REPORTS - shipped_reports}"
    )


FORBIDDEN_AGENT_CONTINUITY_TOOL_TOKENS = (
    "broker",
    "wallet",
    "order",
    "execute",
    "execution",
    "scheduler",
    "cron",
    "backtest",
    "dashboard",
    "fetch_price",
    "fetch_market",
)


def test_agent_continuity_roadmap_does_not_add_forbidden_tool_families():
    """Agent-continuity features must stay a local memory/evaluation layer.

    New public tools may not smuggle in execution, fetching, scheduling,
    dashboard, broker/wallet, or backtester semantics under the roadmap.
    """

    offending = [
        name for name in _registered_tool_names()
        if any(token in name.replace(".", "_") for token in FORBIDDEN_AGENT_CONTINUITY_TOOL_TOKENS)
    ]
    assert offending == []


def test_registered_tool_descriptions_do_not_emit_uncaveated_advice_claims():
    """Descriptions are model-facing prompts; keep them evidence/reporting-only."""

    forbidden = re.compile(
        r"\b(buy recommendation|sell recommendation|trade recommendation|"
        r"guaranteed profit|profit guarantee|financial advice)\b",
        re.IGNORECASE,
    )
    registry = default_registry()
    offending = []
    for name in registry.names():
        description = registry.get(name).description or ""
        match = forbidden.search(description)
        if match:
            offending.append((name, match.group(0)))
    assert offending == []
