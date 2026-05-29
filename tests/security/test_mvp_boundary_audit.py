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
    return list(default_registry().public_names())


def _all_dispatchable_tool_names() -> list[str]:
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
)
MEMORY_OUT_OF_SCOPE = (
    "memory.expire", "memory.purge", "memory.subscribe", "memory.bulk_delete",
    "reflection.prompt_for_outcome",
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


# -- 6. shipped v0.0.2 catalog pins -------------------

SHIPPED_PUBLIC_TOOLS = {
    "abstention.get",
    "abstention.list",
    "abstention.record",
    "decision.add",
    "export.drain",
    "forecast.add",
    "forecast.commit_blind",
    "forecast.independence",
    "forecast.interpret_resolution",
    "forecast.resolution_interpretation",
    "forecast.reveal_snapshot",
    "import.commit",
    "journal.backup",
    "journal.config_set",
    "journal.fixture_seed",
    "journal.init",
    "journal.schema",
    "journal.status",
    "market.bind",
    "market.refresh",
    "memory.link",
    "memory.recall",
    "memory.reflect",
    "memory.retain",
    "outcome.fetch",
    "playbook.record_adherence",
    "playbook.upsert",
    "replay_artifact.get",
    "replay_artifact.list",
    "replay_artifact.record",
    "replay.case_bundle",
    "replay.evaluate_output",
    "resolution.add",
    "review.bundle",
    "snapshot.add",
    "snapshot.fetch",
    "strategy.upsert",
    "tool.schema",
}


SHIPPED_REPORTS = {
    "report.bootstrap",
    "report.calibration",
    "report.calibration_advisory",
    "report.calibration_integrity",
    "report.time_decay_sharpening",
    "report.source_quality",
    "report.audit_readiness",
    "report.mistakes",
    "report.mistake_tripwire",
    "report.strengths",
    "report.process_analytics",
    "report.process_quality",
    "report.pnl",
    "report.risk",
    "report.opportunity",
    "report.watchlist",
    "report.unscored_forecasts",
    "report.playbook_adherence",
    "report.policy_candidates",
    "report.coach",
    "report.compare",
    "report.current_exposure",
    "report.exposure_anomalies",
    "report.filter_schema",
    "report.forecast_diagnostics",
    "report.lifecycle",
    "report.work_queue",
    "report.open_positions",
    "report.resolution_misreads",
    "report.strategy_health",
}


def test_shipped_public_tool_catalog_is_locked():
    """Pin the default v0.0.2 model-facing catalog.

    Transitional legacy handlers may remain dispatchable for local compatibility,
    but they must be hidden from the default catalog unless explicitly requested.
    """

    names = set(_registered_tool_names())
    expected = SHIPPED_PUBLIC_TOOLS | SHIPPED_REPORTS
    assert names == expected, (
        f"shipped public tool catalog drifted from pin. "
        f"added: {names - expected}; "
        f"removed: {expected - names}"
    )


LEGACY_HIDDEN_TOOLS = {
    "venue.add",
    "instrument.add",
    "thesis.add",
    "forecast.supersede",
    "outcome.add",
    "decision.record_adherence",
    "source.add",
    "source.attach_to_thesis",
    "source.attach_to_decision",
    "source.attach_to_forecast",
    "source.attach_to_memory_node",
    "strategy.create",
    "strategy.list",
    "strategy.show",
    "strategy.update",
    "playbook.create",
    "playbook.list",
    "playbook.show",
    "playbook.list_versions",
    "playbook.propose_version",
    "playbook.adherence",
    "resolve.record",
    "resolve.pending",
    "idea.capture",
    "market.scan.dry_run",
    "market.scan.promote",
    "journal.bundle.plan",
    "journal.bundle.status",
    "journal.rescan_scoring",
    "reflection.prompt_for_outcome",
    "import.validate",
    "import.csv_fills",
    "memory.reindex",
    "model.import",
    "model.warm",
    "keyring.revoke",
}


def test_legacy_catalog_tools_are_hidden_but_metadata_explains_transition():
    registry = default_registry()
    public = set(registry.public_names())
    missing_dispatch = LEGACY_HIDDEN_TOOLS - set(_all_dispatchable_tool_names())
    assert missing_dispatch == set()
    assert LEGACY_HIDDEN_TOOLS.isdisjoint(public)
    missing_transition_metadata = []
    for tool in LEGACY_HIDDEN_TOOLS:
        reg = registry.get(tool)
        metadata = reg.metadata()
        if metadata.get("catalog_visibility") != "legacy":
            missing_transition_metadata.append((tool, metadata))
        if not (metadata.get("redirect") is not None or metadata.get("renamed_to") is not None or metadata.get("removed_in") == "0.0.2"):
            missing_transition_metadata.append((tool, metadata))
    assert missing_transition_metadata == []


EXPERIMENTAL_AUTONOMOUS_OPS = {
    "pretrade_intent.record",
    "pretrade_intent.get",
    "pretrade_intent.list",
    "approval.record",
    "approval.get",
    "approval.list",
    "approval.report",
    "risk.check_record",
    "risk.policy_version_add",
    "autonomous_run.record",
    "autonomous_run.get",
    "autonomous_incident.record",
    "autonomous_incident.report",
}


def test_frozen_autonomous_ops_cluster_is_experimental_but_dispatchable():
    """Epic trade-trace-4kec.3: the autonomous-ops cluster is frozen behind the
    experimental tier — hidden from the default catalog, surfaced only under the
    explicit opt-in, and still dispatchable for tests/contract revival."""

    registry = default_registry()
    public = set(registry.public_names())
    assert EXPERIMENTAL_AUTONOMOUS_OPS.isdisjoint(public)
    assert EXPERIMENTAL_AUTONOMOUS_OPS.isdisjoint(
        set(registry.public_names(include_legacy=True))
    )
    assert EXPERIMENTAL_AUTONOMOUS_OPS.issubset(
        set(registry.public_names(include_experimental=True))
    )
    assert EXPERIMENTAL_AUTONOMOUS_OPS.issubset(set(_all_dispatchable_tool_names()))
    for tool in EXPERIMENTAL_AUTONOMOUS_OPS:
        assert registry.get(tool).metadata()["catalog_visibility"] == "experimental"


EXPERIMENTAL_RECONCILIATION = {
    "paper_fill.record",
    "paper_fill.get",
    "paper_fill.list",
    "report.paper_exposure",
    "external_receipt.import",
    "external_receipt.get",
    "external_receipt.list",
    "external_receipt.report",
    "account_snapshot.import",
    "account_snapshot.get",
    "account_snapshot.list",
    "account_snapshot.report",
    "reconciliation.record",
    "reconciliation.get",
    "report.reconciliation_mismatches",
    "report.execution_quality",
    "report.operational_health",
}


def test_frozen_reconciliation_cluster_is_experimental_but_dispatchable():
    """Epic trade-trace-4kec.4: the reconciliation/execution-truth cluster is
    frozen behind the experimental tier — hidden from the default catalog,
    surfaced only under explicit opt-in, still dispatchable."""

    registry = default_registry()
    public = set(registry.public_names())
    assert EXPERIMENTAL_RECONCILIATION.isdisjoint(public)
    assert EXPERIMENTAL_RECONCILIATION.isdisjoint(
        set(registry.public_names(include_legacy=True))
    )
    assert EXPERIMENTAL_RECONCILIATION.issubset(
        set(registry.public_names(include_experimental=True))
    )
    assert EXPERIMENTAL_RECONCILIATION.issubset(set(_all_dispatchable_tool_names()))
    for tool in EXPERIMENTAL_RECONCILIATION:
        assert registry.get(tool).metadata()["catalog_visibility"] == "experimental"


EXPERIMENTAL_ANCHORED_VIEWERS = {
    "forecast.anchor_to_snapshot",
    "report.calibration_anchored",
    "report.calibration_terminal",
    "snapshot.fetch_series",
    "report.decision_velocity",
    "report.memory_usefulness",
    "report.recall_receipts",
    "report.market_lifecycle",
    "report.resolution_quality",
    "journal.restore",
}


def test_frozen_anchored_viewers_cluster_is_experimental_but_dispatchable():
    """Epic trade-trace-4kec.5: the anchored-calibration unit and speculative
    viewers are frozen behind the experimental tier — hidden from the default
    catalog, surfaced only under explicit opt-in, still dispatchable."""

    registry = default_registry()
    public = set(registry.public_names())
    assert EXPERIMENTAL_ANCHORED_VIEWERS.isdisjoint(public)
    assert EXPERIMENTAL_ANCHORED_VIEWERS.isdisjoint(
        set(registry.public_names(include_legacy=True))
    )
    assert EXPERIMENTAL_ANCHORED_VIEWERS.issubset(
        set(registry.public_names(include_experimental=True))
    )
    assert EXPERIMENTAL_ANCHORED_VIEWERS.issubset(set(_all_dispatchable_tool_names()))
    for tool in EXPERIMENTAL_ANCHORED_VIEWERS:
        assert registry.get(tool).metadata()["catalog_visibility"] == "experimental"


def test_admin_tools_are_not_in_default_catalog():
    registry = default_registry()
    assert {"journal.rebuild_projections", "journal.repair", "signal.scan"}.isdisjoint(
        registry.public_names()
    )
    assert {"journal.rebuild_projections", "journal.repair", "signal.scan"}.issubset(
        registry.public_names(include_admin=True)
    )


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

    allowed_diagnostic_names = {"report.execution_quality"}
    offending = [
        name for name in _registered_tool_names()
        if name not in allowed_diagnostic_names
        and any(token in name.replace(".", "_") for token in FORBIDDEN_AGENT_CONTINUITY_TOOL_TOKENS)
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


def test_diagnostic_report_descriptions_caveat_edge_signal_ranking_language():
    """New diagnostics must stay retrospective/process-only in model-facing text."""

    registry = default_registry()
    required_fragments = {
        "report.forecast_diagnostics": (
            "retrospective diagnostics",
            "caller-supplied retrospective reference comparison",
            "not a trading signal",
            "No external fetching",
            "trading advice",
            "alpha/profit claim",
            "performance ranking",
        ),
        "report.strategy_health": (
            "process-health report",
            "administrative",
            "not profit/performance ranking",
            "edge/signal detection",
            "trading advice",
        ),
    }
    missing = []
    for tool, fragments in required_fragments.items():
        registration = registry.get(tool)
        surfaces = {
            "registry.description": registration.description or "",
            "json_schema.description": (registration.json_schema or {}).get("description", ""),
        }
        for surface, description in surfaces.items():
            for fragment in fragments:
                if fragment not in description:
                    missing.append((tool, surface, fragment, description))

    assert missing == []
