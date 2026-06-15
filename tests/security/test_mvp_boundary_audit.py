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
    # Unfrozen into the public Phase-2 catalog (bead trade-trace-g776): the
    # external execution-receipt import cluster. external_receipt.import ingests
    # one sanitized, caller-supplied execution-event claim as append-only LOCAL
    # EVIDENCE only (labelled non_executing / credential_blind, never TT-fetched);
    # the module has no venue client, private-auth fetch, signing, placement,
    # cancellation, custody movement, or remediation. Malformed / secret-bearing /
    # credential-shaped / impossible payloads are quarantined at the import
    # boundary. These rows are what reconciliation._build_derived consumes to
    # derive ORPHAN_EXTERNAL_*, DUPLICATE_FILL, and REJECTED_APPROVED_INTENT.
    # external_receipt.report (a report-shaped tool under the external_receipt
    # namespace, not a report.* tool, so it lives here rather than in
    # SHIPPED_REPORTS) reads append-only external_execution_receipts and surfaces
    # caveat codes as evidence only; it never remediates or fetches private state.
    "external_receipt.import",
    "external_receipt.get",
    "external_receipt.list",
    "external_receipt.report",
    # Unfrozen into the public Phase-2 catalog (bead trade-trace-qfn8): the
    # account-snapshot import cluster — the account-truth sibling of the external
    # execution-receipt importer. account_snapshot.import ingests one sanitized,
    # caller-supplied account-state claim (balances, collateral, open orders,
    # positions, fills/trades, unsettled claims, public allowance facts) as
    # append-only LOCAL EVIDENCE only (labelled
    # record_kind=sanitized_imported_account_snapshot with provenance and
    # source-precedence/confidence/staleness, never TT-fetched); the module has no
    # venue client, private-auth fetch, signing, placement, cancellation, custody
    # movement, or remediation. Malformed / secret-bearing / credential-shaped /
    # impossible (negative, available>total) payloads are quarantined at the
    # boundary. These rows are what reconciliation._latest_snapshot reads (by
    # source-precedence ordering) and _build_derived consumes to derive
    # STALE_SNAPSHOT / POSITION_MISMATCH / BALANCE_MISMATCH. account_snapshot.report
    # (a report-shaped tool under the account_snapshot namespace, not a report.*
    # tool, so it lives here rather than in SHIPPED_REPORTS) reads append-only
    # account_snapshots and surfaces stale/missing caveat codes as evidence only.
    "account_snapshot.import",
    "account_snapshot.get",
    "account_snapshot.list",
    "account_snapshot.report",
    "forecast.add",
    "forecast.commit_blind",
    "forecast.independence",
    "forecast.interpret_resolution",
    "forecast.resolution_interpretation",
    "forecast.reveal_snapshot",
    "import.commit",
    "journal.fixture_seed",
    "journal.init",
    "journal.schema",
    "journal.status",
    "market.bind",
    "market.find_similar",
    "market.refresh",
    "market.search",
    "memory.link",
    "memory.recall",
    "memory.reflect",
    "memory.retain",
    "outcome.fetch",
    # Unfrozen into the public Phase-2 catalog (bead trade-trace-xwox): the
    # paper-fill ledger write/read surface. paper_fill.record runs a
    # deterministic conservative limit/depth fill engine over caller-supplied
    # book/snapshot facts (full/partial/no-fill, freshness + slippage rejection)
    # and persists an immutable, append-only, idempotent paper_only record; it
    # never places/signs/routes/cancels an order or touches a live account.
    "paper_fill.record",
    "paper_fill.get",
    "paper_fill.list",
    "playbook.propose_version",
    "playbook.record_adherence",
    "playbook.upsert",
    # Unfrozen into the public Phase-2 catalog (bead trade-trace-2g47): the
    # pre-trade intent cluster is the write side of VISION Phase 2 "the agent
    # proposes trades". Each tool records/reads an immutable, hashed,
    # non-executing local audit packet and never places/signs/routes/approves an
    # order; the packet's risk_check_receipt_id links to an immutable
    # risk.check_record receipt so an evaluated intent surfaces its verdict.
    "pretrade_intent.record",
    "pretrade_intent.get",
    "pretrade_intent.list",
    # Unfrozen into the public Phase-2 catalog (bead trade-trace-opoc): the
    # reconciliation result cluster. reconciliation.record runs a DETERMINISTIC
    # derivation over positions / account_snapshots / external_execution_receipts /
    # paper_fill_records / pretrade_intents / approval_waiver_records and emits a
    # reproducible set of stable mismatch codes; caller-supplied codes are routed
    # to a distinct `manually_flagged` channel and never unioned into the derived
    # set, so the derived set stays byte-reproducible. It is local-evidence-only,
    # credential-blind, and non-executing (no fetch/sign/place/cancel/settle/move).
    "reconciliation.record",
    "reconciliation.get",
    "replay_artifact.get",
    "replay_artifact.list",
    "replay_artifact.record",
    "replay.case_bundle",
    "replay.evaluate_output",
    "resolution.add",
    "review.bundle",
    # Unfrozen into the public Phase-2 catalog (bead trade-trace-ur8w) now that
    # the deterministic evaluator ships (trade-trace-g629). The cluster is one
    # audit-only, credential-blind loop — store an immutable policy version,
    # deterministically evaluate a non-executing intent (read-only), and persist
    # that verdict as an immutable receipt (with an evaluator consistency guard).
    # None of them block/sign/place/route an order, so they are safe in the
    # default public catalog.
    "risk.check_record",
    "risk.evaluate",
    "risk.policy_version_add",
    "snapshot.add",
    "snapshot.fetch",
    # Unfrozen into the Phase-1 public catalog (bead trade-trace-xtdo): the
    # time-series snapshot fetcher that feeds the anchored/terminal calibration
    # readers; markets-table backed, no Phase-2 dependency, same idempotency
    # contract as snapshot.fetch.
    "snapshot.fetch_series",
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
    "report.phase_gate_readiness",
    "report.autonomy_readiness",
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
    "report.rule_lineage",
    "report.coach",
    "report.compare",
    "report.current_exposure",
    "report.execution_quality",
    "report.exposure_anomalies",
    "report.filter_schema",
    "report.forecast_diagnostics",
    "report.lifecycle",
    "report.work_queue",
    "report.open_positions",
    "report.operational_health",
    # Unfrozen into the public Phase-2 catalog (bead trade-trace-xwox): the
    # paper-only exposure/P&L report. It aggregates ONLY filled paper_fill rows
    # into a cost-basis/exposure view carrying mark_source + as_of and explicitly
    # excludes imported/live account truth and any live-execution claim.
    "report.paper_exposure",
    # Unfrozen into the public Phase-2 catalog (bead trade-trace-opoc): the
    # reconciliation mismatch report. It reads append-only reconciliation_records
    # and surfaces the deterministically derived mismatch codes plus a separate
    # manually_flagged aggregate as evidence for external operators; it never
    # cancels, halts, remediates, fetches private state, or moves funds.
    "report.reconciliation_mismatches",
    "report.resolution_misreads",
    "report.strategy_health",
    # Unfrozen into the Phase-1 public catalog (bead trade-trace-y0cr): both
    # read only Phase-1 tables and carry no Phase-2 dependency.
    "report.market_lifecycle",
    "report.resolution_quality",
    # Unfrozen into the Phase-1 public catalog (bead trade-trace-8g7t):
    # read-only diagnostics over Phase-1 tables (recall telemetry, memory
    # nodes, typed edges, decisions) with no Phase-2 dependency.
    # decision_velocity is the sole producer of the per-day/week decision
    # cadence series, so it was unfrozen rather than cut as redundant.
    "report.recall_receipts",
    "report.memory_usefulness",
    "report.decision_velocity",
    # Unfrozen into the Phase-1 public catalog (bead trade-trace-xtdo):
    # market-baseline calibration panels (Brier skill vs the market) over only
    # Phase-1 tables (forecast_snapshot_anchor / forecast_scores / forecasts /
    # outcomes / snapshots), no Phase-2 dependency. The after-the-fact anchor
    # WRITER forecast.anchor_to_snapshot stays frozen (superseded by
    # forecast.commit_blind / forecast.reveal_snapshot, bead trade-trace-4kec.9).
    "report.calibration_anchored",
    "report.calibration_terminal",
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
    # pretrade_intent.record/get/list were UNFROZEN into the public catalog
    # (bead trade-trace-2g47) and moved to SHIPPED_PUBLIC_TOOLS above; they are
    # no longer part of the frozen cluster.
    "approval.record",
    "approval.get",
    "approval.list",
    "approval.report",
    # risk.check_record / risk.policy_version_add / risk.evaluate were UNFROZEN
    # into the public catalog (bead trade-trace-ur8w) and moved to
    # SHIPPED_PUBLIC_TOOLS above; they are no longer part of the frozen cluster.
    # autonomous_run.* and autonomous_incident.* were CUT entirely (trade-trace-irgs).
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


REMOVED_AUTONOMOUS_RUN_INCIDENT_TOOLS = {
    "autonomous_run.record",
    "autonomous_run.get",
    "autonomous_incident.record",
    "autonomous_incident.report",
}


def test_autonomous_run_incident_cluster_is_cut_from_registry():
    registry = default_registry()
    names = set(registry.names())
    public = set(registry.public_names(include_experimental=True, include_legacy=True))
    assert REMOVED_AUTONOMOUS_RUN_INCIDENT_TOOLS.isdisjoint(names)
    assert REMOVED_AUTONOMOUS_RUN_INCIDENT_TOOLS.isdisjoint(public)


EXPERIMENTAL_RECONCILIATION = frozenset({
    # paper_fill.record/get/list and report.paper_exposure were UNFROZEN into
    # the public Phase-2 catalog (bead trade-trace-xwox) and moved to
    # SHIPPED_PUBLIC_TOOLS / SHIPPED_REPORTS above; they are no longer part of
    # the frozen reconciliation cluster. Their public-catalog membership is
    # pinned by test_unfrozen_paper_fill_ledger_is_public below.
    #
    # reconciliation.record/get and report.reconciliation_mismatches were
    # UNFROZEN into the public Phase-2 catalog (bead trade-trace-opoc) and moved
    # to SHIPPED_PUBLIC_TOOLS / SHIPPED_REPORTS above; their public-catalog
    # membership is pinned by test_unfrozen_reconciliation_cluster_is_public
    # below.
    #
    # external_receipt.import/get/list/report were UNFROZEN into the public
    # Phase-2 catalog (bead trade-trace-g776) and moved to SHIPPED_PUBLIC_TOOLS /
    # SHIPPED_REPORTS above; their public-catalog membership is pinned by
    # test_unfrozen_external_receipt_cluster_is_public below.
    #
    # account_snapshot.import/get/list/report were UNFROZEN into the public
    # Phase-2 catalog (bead trade-trace-qfn8) and moved to SHIPPED_PUBLIC_TOOLS
    # above; their public-catalog membership is pinned by
    # test_unfrozen_account_snapshot_cluster_is_public below. The process reports
    # report.execution_quality and report.operational_health were also UNFROZEN
    # (trade-trace-2umy) and are pinned by test_unfrozen_process_reports_are_public.
})


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


UNFROZEN_PROCESS_REPORTS = {
    "report.execution_quality",
    "report.operational_health",
}


def test_unfrozen_process_reports_are_public():
    registry = default_registry()
    public = set(registry.public_names())
    assert UNFROZEN_PROCESS_REPORTS.issubset(public)
    assert UNFROZEN_PROCESS_REPORTS.isdisjoint(EXPERIMENTAL_RECONCILIATION)
    for tool in UNFROZEN_PROCESS_REPORTS:
        assert registry.get(tool).metadata()["catalog_visibility"] == "public"


# paper_fill.record/get/list and report.paper_exposure were UNFROZEN out of
# EXPERIMENTAL_RECONCILIATION into the public Phase-2 catalog (bead
# trade-trace-xwox). They are the local paper-fill ledger: a deterministic
# conservative limit/depth fill engine plus an aggregating exposure report, all
# local-evidence-only and credential-blind (no venue client, no account fetch,
# no signing/placement/cancellation/fund movement). The imported-truth and
# process-report surfaces have since been unfrozen (see the dedicated tests
# below).
UNFROZEN_PAPER_FILL_LEDGER = {
    "paper_fill.record",
    "paper_fill.get",
    "paper_fill.list",
    "report.paper_exposure",
}


def test_unfrozen_paper_fill_ledger_is_public():
    """Bead trade-trace-xwox: the paper-fill ledger cluster ships in the default
    Phase-2 public catalog — visible without any opt-in, and no longer in the
    frozen experimental reconciliation cluster. Pin that non-experimental state
    so a future accidental re-freeze (re-adding paper_fill.* /
    report.paper_exposure to EXPERIMENTAL_RECONCILIATION) is caught here."""

    registry = default_registry()
    public = set(registry.public_names())
    assert UNFROZEN_PAPER_FILL_LEDGER.issubset(public)
    # No longer frozen behind the experimental shelf.
    assert UNFROZEN_PAPER_FILL_LEDGER.isdisjoint(EXPERIMENTAL_RECONCILIATION)
    for tool in UNFROZEN_PAPER_FILL_LEDGER:
        assert registry.get(tool).metadata()["catalog_visibility"] == "public"


# reconciliation.record/get and report.reconciliation_mismatches were UNFROZEN
# out of EXPERIMENTAL_RECONCILIATION into the public Phase-2 catalog (bead
# trade-trace-opoc). reconciliation.record runs a deterministic derivation over
# append-only local + imported tables and emits a reproducible mismatch-code set;
# caller-supplied codes are confined to a separate `manually_flagged` channel.
# The cluster is local-evidence-only, credential-blind, and non-executing (no
# fetch/sign/place/cancel/settle/fund-move/remediate). The imported-truth and
# process-report surfaces have since been unfrozen (see the dedicated tests
# below).
UNFROZEN_RECONCILIATION_CLUSTER = {
    "reconciliation.record",
    "reconciliation.get",
    "report.reconciliation_mismatches",
}


def test_unfrozen_reconciliation_cluster_is_public():
    """Bead trade-trace-opoc: the reconciliation result cluster ships in the
    default Phase-2 public catalog — visible without any opt-in, and no longer in
    the frozen experimental reconciliation cluster. Pin that non-experimental
    state so a future accidental re-freeze (re-adding reconciliation.* /
    report.reconciliation_mismatches to EXPERIMENTAL_RECONCILIATION) is caught
    here."""

    registry = default_registry()
    public = set(registry.public_names())
    assert UNFROZEN_RECONCILIATION_CLUSTER.issubset(public)
    # No longer frozen behind the experimental shelf.
    assert UNFROZEN_RECONCILIATION_CLUSTER.isdisjoint(EXPERIMENTAL_RECONCILIATION)
    for tool in UNFROZEN_RECONCILIATION_CLUSTER:
        assert registry.get(tool).metadata()["catalog_visibility"] == "public"


# external_receipt.import/get/list/report were UNFROZEN out of
# EXPERIMENTAL_RECONCILIATION into the public Phase-2 catalog (bead
# trade-trace-g776). They ingest/read sanitized, caller-supplied execution-event
# claims as append-only LOCAL EVIDENCE only — labelled non_executing /
# credential_blind, never TT-fetched. The module has no venue client,
# private-auth fetch, signing, placement, cancellation, custody movement, or
# remediation; malformed / secret-bearing / credential-shaped / impossible
# payloads are quarantined at the boundary. These rows feed
# reconciliation._build_derived's ORPHAN_EXTERNAL_* / DUPLICATE_FILL /
# REJECTED_APPROVED_INTENT derivation.
UNFROZEN_EXTERNAL_RECEIPT_CLUSTER = {
    "external_receipt.import",
    "external_receipt.get",
    "external_receipt.list",
    "external_receipt.report",
}


def test_unfrozen_external_receipt_cluster_is_public():
    """Bead trade-trace-g776: the external execution-receipt import cluster ships
    in the default Phase-2 public catalog — visible without any opt-in, and no
    longer in the frozen experimental reconciliation cluster. Pin that
    non-experimental state so a future accidental re-freeze (re-adding
    external_receipt.* to EXPERIMENTAL_RECONCILIATION) is caught here."""

    registry = default_registry()
    public = set(registry.public_names())
    assert UNFROZEN_EXTERNAL_RECEIPT_CLUSTER.issubset(public)
    # No longer frozen behind the experimental shelf.
    assert UNFROZEN_EXTERNAL_RECEIPT_CLUSTER.isdisjoint(EXPERIMENTAL_RECONCILIATION)
    for tool in UNFROZEN_EXTERNAL_RECEIPT_CLUSTER:
        assert registry.get(tool).metadata()["catalog_visibility"] == "public"


# account_snapshot.import/get/list/report were UNFROZEN out of
# EXPERIMENTAL_RECONCILIATION into the public Phase-2 catalog (bead
# trade-trace-qfn8). They ingest/read sanitized, caller-supplied account-state
# claims (balances, collateral, open orders, positions, fills/trades, unsettled
# claims, public allowance facts) as append-only LOCAL EVIDENCE only — labelled
# record_kind=sanitized_imported_account_snapshot with provenance and
# source-precedence/confidence/staleness, never TT-fetched. The module has no
# venue client, private-auth fetch, signing, placement, cancellation, custody
# movement, or remediation; malformed / secret-bearing / credential-shaped /
# impossible payloads are quarantined at the boundary. These rows feed
# reconciliation._latest_snapshot / _build_derived's STALE_SNAPSHOT /
# POSITION_MISMATCH / BALANCE_MISMATCH derivation.
UNFROZEN_ACCOUNT_SNAPSHOT_CLUSTER = {
    "account_snapshot.import",
    "account_snapshot.get",
    "account_snapshot.list",
    "account_snapshot.report",
}


def test_unfrozen_account_snapshot_cluster_is_public():
    """Bead trade-trace-qfn8: the account-snapshot import cluster ships in the
    default Phase-2 public catalog — visible without any opt-in, and no longer in
    the frozen experimental reconciliation cluster. Pin that non-experimental
    state so a future accidental re-freeze (re-adding account_snapshot.* to
    EXPERIMENTAL_RECONCILIATION) is caught here."""

    registry = default_registry()
    public = set(registry.public_names())
    assert UNFROZEN_ACCOUNT_SNAPSHOT_CLUSTER.issubset(public)
    # No longer frozen behind the experimental shelf.
    assert UNFROZEN_ACCOUNT_SNAPSHOT_CLUSTER.isdisjoint(EXPERIMENTAL_RECONCILIATION)
    for tool in UNFROZEN_ACCOUNT_SNAPSHOT_CLUSTER:
        assert registry.get(tool).metadata()["catalog_visibility"] == "public"


EXPERIMENTAL_ANCHORED_VIEWERS = {
    # forecast.anchor_to_snapshot stays frozen: bead trade-trace-4kec.9
    # (forecast.commit_blind / forecast.reveal_snapshot) was built as its
    # explicit semantic replacement, so the after-the-fact anchor WRITER must
    # not ship in the public Phase-1 catalog. Its anchor write is already
    # folded into forecast.add. Its three READERS
    # (report.calibration_anchored / report.calibration_terminal /
    # snapshot.fetch_series) were UNFROZEN into the public Phase-1 catalog
    # (bead trade-trace-xtdo); their public-catalog membership is pinned by
    # test_unfrozen_anchored_calibration_readers_are_public below.
    "forecast.anchor_to_snapshot",
    # report.decision_velocity, report.memory_usefulness, and
    # report.recall_receipts were unfrozen into the Phase-1 public catalog
    # (bead trade-trace-8g7t); their public-catalog membership is pinned by
    # test_unfrozen_memory_process_reports_are_public below.
    # report.market_lifecycle and report.resolution_quality were unfrozen into
    # the Phase-1 public catalog (bead trade-trace-y0cr); their public-catalog
    # membership is pinned by test_pm_native_report_tools_registered.
    # journal.restore was grouped here as a speculative viewer, but it is a
    # destructive operator tool now admin-gated by bead trade-trace-6rnk; its
    # gating is pinned by ADMIN_GATED_OPERATOR_TOOLS /
    # test_admin_tools_are_not_in_default_catalog instead. It stays
    # catalog_visibility='experimental' AND is_admin=True, so it is absent from
    # public_names(include_experimental=True) (which does not opt into admin).
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


# report.decision_velocity, report.memory_usefulness, and
# report.recall_receipts were UNFROZEN out of EXPERIMENTAL_ANCHORED_VIEWERS into
# the Phase-1 public catalog (bead trade-trace-8g7t). They are read-only
# diagnostics over Phase-1 tables with no Phase-2 dependency.
UNFROZEN_MEMORY_PROCESS_REPORTS = {
    "report.decision_velocity",
    "report.memory_usefulness",
    "report.recall_receipts",
}


def test_unfrozen_memory_process_reports_are_public():
    """Bead trade-trace-8g7t: the memory/process diagnostics ship in the
    default Phase-1 public catalog — visible without any opt-in, and
    explicitly no longer in the frozen experimental cluster."""

    registry = default_registry()
    public = set(registry.public_names())
    assert UNFROZEN_MEMORY_PROCESS_REPORTS.issubset(public)
    # No longer frozen behind the experimental shelf.
    assert UNFROZEN_MEMORY_PROCESS_REPORTS.isdisjoint(EXPERIMENTAL_ANCHORED_VIEWERS)
    for tool in UNFROZEN_MEMORY_PROCESS_REPORTS:
        assert registry.get(tool).metadata()["catalog_visibility"] == "public"


# report.calibration_anchored, report.calibration_terminal, and
# snapshot.fetch_series were UNFROZEN out of EXPERIMENTAL_ANCHORED_VIEWERS into
# the Phase-1 public catalog (bead trade-trace-xtdo). They are read-only
# market-baseline calibration diagnostics (plus the time-series snapshot fetcher
# that feeds them) over only Phase-1 tables, with no Phase-2 dependency. The
# anchor WRITER forecast.anchor_to_snapshot stays frozen because bead
# trade-trace-4kec.9 (forecast.commit_blind / forecast.reveal_snapshot)
# superseded it.
UNFROZEN_ANCHORED_CALIBRATION_READERS = {
    "report.calibration_anchored",
    "report.calibration_terminal",
    "snapshot.fetch_series",
}


def test_unfrozen_anchored_calibration_readers_are_public():
    """Bead trade-trace-xtdo: the anchored/terminal market-baseline calibration
    readers and the series snapshot fetcher ship in the default Phase-1 public
    catalog — visible without any opt-in, and no longer in the frozen
    experimental cluster. The anchor WRITER stays frozen (superseded by
    forecast.commit_blind / forecast.reveal_snapshot)."""

    registry = default_registry()
    public = set(registry.public_names())
    assert UNFROZEN_ANCHORED_CALIBRATION_READERS.issubset(public)
    # No longer frozen behind the experimental shelf.
    assert UNFROZEN_ANCHORED_CALIBRATION_READERS.isdisjoint(EXPERIMENTAL_ANCHORED_VIEWERS)
    for tool in UNFROZEN_ANCHORED_CALIBRATION_READERS:
        assert registry.get(tool).metadata()["catalog_visibility"] == "public"
    # The after-the-fact anchor writer remains frozen (superseded by 4kec.9).
    assert "forecast.anchor_to_snapshot" in EXPERIMENTAL_ANCHORED_VIEWERS
    assert "forecast.anchor_to_snapshot" not in public
    assert (
        registry.get("forecast.anchor_to_snapshot").metadata()["catalog_visibility"]
        == "experimental"
    )


# Destructive operator-only tools admin-gated by bead trade-trace-6rnk.
# journal.backup/config_set were catalog_visibility='public' and journal.restore
# was 'experimental', but none carried is_admin=True — so the default catalog
# (and, for backup/config_set, every non-admin agent) saw them with no admin
# signal. model.import/memory.reindex are 'legacy' but added for defense in
# depth so include_legacy=True cannot re-surface them to non-admin callers.
ADMIN_GATED_OPERATOR_TOOLS = {
    "journal.rebuild_projections",
    "journal.repair",
    "signal.scan",
    "journal.backup",
    "journal.restore",
    "journal.config_set",
    "model.import",
    "memory.reindex",
}


def test_admin_tools_are_not_in_default_catalog():
    registry = default_registry()
    # No non-admin listing surface — default, include_legacy, or
    # include_experimental — may expose an admin-gated operator tool.
    assert ADMIN_GATED_OPERATOR_TOOLS.isdisjoint(registry.public_names())
    assert ADMIN_GATED_OPERATOR_TOOLS.isdisjoint(
        registry.public_names(include_legacy=True)
    )
    assert ADMIN_GATED_OPERATOR_TOOLS.isdisjoint(
        registry.public_names(include_experimental=True)
    )
    # They reappear only when the operator explicitly opts into admin tools.
    assert ADMIN_GATED_OPERATOR_TOOLS.issubset(
        registry.public_names(
            include_admin=True, include_legacy=True, include_experimental=True
        )
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
