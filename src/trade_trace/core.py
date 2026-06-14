"""Single core dispatcher backing both CLI and MCP transports.

CLI and MCP each prepare an envelope-shaped result by calling
`dispatch(tool_name, args, *, actor_id, request_id, registry)`. They differ
only in how `args` is decoded from transport input (kebab-case flags vs JSON)
and how the resulting envelope is serialized (NDJSON to stdout for CLI, MCP
framing for MCP). The dispatch path itself is identical — which is the
PRD §2.3 / contracts.md §2 parity contract.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

from trade_trace import dispatch_trace
from trade_trace.contracts.envelope import (
    ErrorEnvelope,
    Meta,
    SuccessEnvelope,
    error_envelope,
)
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.grammar import validate_actor_id
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.log import IdempotencyConflictError
from trade_trace.events.semantic_keys import derive_idempotency_key
from trade_trace.events.unit_of_work import DRY_RUN_FLAG
from trade_trace.storage.paths import HomePathValidationError
from trade_trace.tools._helpers import CLOCK_OVERRIDE
from trade_trace.tools.abstention import register_abstention_tools
from trade_trace.tools.account_snapshots import register_account_snapshot_tools
from trade_trace.tools.adapter_polymarket import register_adapter_polymarket_tools
from trade_trace.tools.admin import register_admin_tools
from trade_trace.tools.approval import register_approval_tools
from trade_trace.tools.autonomous_records import register_autonomous_record_tools
from trade_trace.tools.csv_import import register_csv_import
from trade_trace.tools.errors import ToolError
from trade_trace.tools.export import register_export_tools
from trade_trace.tools.external_receipts import register_external_receipt_tools
from trade_trace.tools.fixture import register_fixture_tools
from trade_trace.tools.forecast_independence import register_forecast_independence_tools
from trade_trace.tools.ideas import register_idea_tools
from trade_trace.tools.imports import register_import_stubs
from trade_trace.tools.journal import register_journal_tools
from trade_trace.tools.journal_bundle_status import register_journal_bundle_status
from trade_trace.tools.ledger import register_ledger_tools
from trade_trace.tools.market_bind import register_market_bind_tool
from trade_trace.tools.market_scan import register_market_scan_tools
from trade_trace.tools.market_similarity import register_market_similarity_tools
from trade_trace.tools.memory import register_memory_tools
from trade_trace.tools.paper_fills import register_paper_fill_tools
from trade_trace.tools.playbook import register_playbook_tools
from trade_trace.tools.pretrade_intent import register_pretrade_intent_tools
from trade_trace.tools.reconciliation import register_reconciliation_tools
from trade_trace.tools.reflection import register_reflection_tools
from trade_trace.tools.replay_artifacts import register_replay_artifact_tools
from trade_trace.tools.reports import register_report_tools
from trade_trace.tools.resolution_interpretation import register_resolution_interpretation_tools
from trade_trace.tools.review_bundle import register_review_bundle
from trade_trace.tools.risk import register_risk_tools
from trade_trace.tools.signals import register_signal_tools
from trade_trace.tools.strategy import register_strategy_tools

_DEFAULT_REGISTRY: ToolRegistry | None = None

V002_RENAMED_TO: dict[str, str] = {
    "outcome.add": "resolution.add",
    "decision.record_adherence": "playbook.record_adherence",
}

V002_FOLDED_OR_REMOVED: dict[str, str | None] = {
    "venue.add": "market.bind",
    "instrument.add": "market.bind",
    "thesis.add": "forecast.add",
    "forecast.supersede": "forecast.add",
    "source.add": None,
    "source.attach_to_thesis": "forecast.add",
    "source.attach_to_decision": "decision.add",
    "source.attach_to_forecast": "forecast.add",
    "source.attach_to_memory_node": "memory.retain",
    "source.attach_to_outcome": "resolution.add",
    "source.attach_to_snapshot": "snapshot.add",
    "source.attach_to_instrument": "market.bind",
    "strategy.create": "strategy.upsert",
    "strategy.update": "strategy.upsert",
    "strategy.list": "report.strategy_health",
    "strategy.show": "report.strategy_health",
    "playbook.create": "playbook.upsert",
    "playbook.list": "playbook.upsert",
    "playbook.show": "playbook.upsert",
    "playbook.list_versions": "playbook.upsert",
    # playbook.propose_version is NOT folded: it is the ONLY tool that mints a
    # playbook_version_id, and playbook.record_adherence (catalog-visible)
    # HARD-REQUIRES one (NOT_FOUND otherwise). Folding it to playbook.upsert
    # left the report.playbook_adherence POPULATED path structurally
    # unreachable from the MCP catalog — a consumer (record_adherence) shipped
    # without its producer, and the redirect pointed at a tool (playbook.upsert
    # → _playbook_create) that creates only a playbook row, never a version. It
    # stays catalog-visible so the adherence chain is completable end-to-end
    # (bead trade-trace-47tp / AX dogfood 2026-06-05-08).
    "import.validate": "import.commit",
    "journal.rescan_scoring": "journal.rebuild_projections",
    "agent.bootstrap": "report.bootstrap",
    "agent.next_actions": "report.work_queue",
    "playbook.adherence": "report.playbook_adherence",
    "resolve.record": "resolution.add",
    "resolve.pending": "report.work_queue",
    "idea.capture": "memory.retain",
    "market.scan.dry_run": "market.bind",
    "market.scan.promote": "market.bind",
    "journal.bundle.plan": None,
    "journal.bundle.status": None,
    "reflection.prompt_for_outcome": None,
    "import.csv_fills": "import.commit",
    "memory.reindex": None,
    "model.import": None,
    "model.warm": None,
}

V002_ADMIN_TOOLS = {
    "journal.rebuild_projections",
    "journal.repair",
    "signal.scan",
    # Destructive operator-only tools (bead trade-trace-6rnk). These are
    # registered is_write=True but defaulted to is_admin=False, so the default
    # catalog view (public_names(include_admin=False)) surfaced journal.backup
    # and journal.config_set — both catalog_visibility='public' — to non-admin
    # agents (e.g. automated trading bots) with no admin-tier signal.
    # journal.restore is an admin-tier disaster-recovery tool (it was un-frozen
    # from the experimental Phase-2 shelf in bead trade-trace-26sl); is_admin
    # keeps include_admin=False callers from ever seeing it regardless of any
    # future visibility change. model.import and memory.reindex are 'legacy' (hidden by
    # default) but are added for defense in depth: include_legacy=True must not
    # re-surface destructive operator tools to non-admin callers.
    "journal.backup",
    "journal.restore",
    "journal.config_set",
    "model.import",
    "memory.reindex",
}


def _apply_v002_catalog_overlay(registry: ToolRegistry) -> None:
    """Add v0.0.2 canonical catalog names while preserving legacy dispatch.

    Bead trade-trace-rooi consolidates the tool catalog without destructively
    removing old local handlers in the same slice. Legacy names remain callable
    for existing tests/import paths, but default catalog listings hide them and
    advertise redirect/rename metadata.
    """

    register_market_bind_tool(registry)
    register_adapter_polymarket_tools(registry)
    registry.alias("resolution.add", "outcome.add", legacy_name="outcome.add")
    # playbook.record_adherence is the canonical registered name (playbook.py).
    # The legacy decision.record_adherence name is retained ONLY as a dispatch
    # alias so historic JSONL exports / import.commit replay carrying
    # tool='decision.record_adherence' still resolve to the same handler. The
    # V002_RENAMED_TO loop below marks it catalog_visibility='legacy' so it
    # stays hidden from the default v0.0.2 catalog (bead trade-trace-va77).
    registry.alias(
        "decision.record_adherence",
        "playbook.record_adherence",
        legacy_name="decision.record_adherence",
    )
    registry.alias(
        "strategy.upsert",
        "strategy.create",
        legacy_name="strategy.create",
        description=(
            "Create/update strategy surface for the v0.0.2 catalog. The current "
            "additive implementation delegates create-mode to the legacy handler; "
            "update/read cleanup remains guarded by legacy redirect metadata."
        ),
    )
    registry.alias(
        "playbook.upsert",
        "playbook.create",
        legacy_name="playbook.create",
        description=(
            "Create/propose playbook surface for the v0.0.2 catalog. The current "
            "additive implementation delegates create-mode to the legacy handler; "
            "version/read cleanup remains guarded by legacy redirect metadata."
        ),
    )

    for old, new in V002_RENAMED_TO.items():
        if old in registry.by_name:
            registry.mark(
                old,
                catalog_visibility="legacy",
                renamed_to=new,
                removed_in="0.0.2",
            )
    for old, redirect in V002_FOLDED_OR_REMOVED.items():
        if old in registry.by_name:
            registry.mark(
                old,
                catalog_visibility="legacy",
                redirect=redirect,
                removed_in="0.0.2",
            )
    for name in V002_ADMIN_TOOLS:
        if name in registry.by_name:
            registry.mark(name, is_admin=True)


# Epic trade-trace-4kec freezes the Product-B surface behind the experimental
# tier rather than deleting it: handlers stay dispatchable for tests and
# explicit opt-in callers, but they leave the default public catalog so a future
# "contract surface" story can revive them. Each cluster is a separate child
# bead; the sets are unioned and marked in one pass.
EXPERIMENTAL_AUTONOMOUS_OPS: frozenset[str] = frozenset({
    # The pre-trade intent cluster (pretrade_intent.record/get/list) was
    # UNFROZEN into the public Phase-2 catalog (bead trade-trace-2g47). It is
    # the write side of VISION Phase 2 "the agent proposes trades": each tool
    # records/reads an immutable, hashed, non-executing local audit packet and
    # never places, signs, routes, approves, or cancels an order. The packet's
    # risk_check_receipt_id links to an immutable risk.check_record receipt, so
    # an intent that has been run through the deterministic risk evaluator
    # surfaces an `evaluation` block (status from the linked receipt) on
    # pretrade_intent.get/list — "intent awaiting check" vs "intent with check"
    # are derived from append-only rows, not a mutable status column. A
    # freeze-state regression test pins this non-experimental state so a future
    # accidental re-freeze is caught
    # (tests/integration/test_pretrade_intent.py::test_pretrade_intent_cluster_is_not_frozen).
    "approval.record",
    "approval.get",
    "approval.list",
    "approval.report",
    # The risk policy/receipt/evaluate cluster was UNFROZEN into the public
    # Phase-2 catalog (bead trade-trace-ur8w) now that the deterministic
    # evaluator ships (trade-trace-g629). The three tools form one closed loop:
    #   risk.policy_version_add  -> stores an immutable versioned policy;
    #   risk.evaluate            -> deterministic, read-only verdict over a
    #                               proposed non-executing intent (is_write=False);
    #   risk.check_record        -> persists that verdict as an immutable receipt,
    #                               with an optional consistency guard that
    #                               re-runs evaluate_risk_policy when evaluator
    #                               inputs are supplied (see _risk_check_record).
    # None of them block, sign, place, or route an order; the cluster is
    # audit-only and credential-blind, so it is safe in the public catalog. A
    # freeze-state regression test pins this so a future re-freeze is caught
    # (tests/integration/test_report_risk.py::test_risk_cluster_is_not_frozen).
    "autonomous_run.record",
    "autonomous_run.get",
    "autonomous_incident.record",
    "autonomous_incident.report",
})

EXPERIMENTAL_RECONCILIATION: frozenset[str] = frozenset({
    # The paper-fill ledger cluster (paper_fill.record/get/list +
    # report.paper_exposure) was UNFROZEN into the public Phase-2 catalog (bead
    # trade-trace-xwox). It is the VISION Phase 2 "paper fills track what would
    # have happened" surface: paper_fill.record runs a deterministic,
    # conservative limit/depth fill ENGINE (conservative_fill_model =
    # limit_depth_v1) over caller-supplied book/snapshot facts — full/partial/
    # no-fill by limit price, snapshot freshness/staleness rejection, and
    # slippage-cap rejection — and persists an immutable, append-only,
    # idempotent local record. It has no venue client, no private-account fetch,
    # no signing, no order placement, no cancellation, and no fund-movement path;
    # every record is paper_only / non_executing / not_imported_account_truth.
    # report.paper_exposure aggregates ONLY filled rows into a paper-only
    # exposure/P&L basis carrying mark_source + as_of and excluding imported/live
    # account truth. The cluster is local-evidence-only and credential-blind, so
    # it is safe in the default public catalog. A freeze-state regression test
    # pins this so a future re-freeze is caught
    # (tests/integration/test_paper_fill_records.py::test_paper_fill_cluster_is_not_frozen).
    #
    # The reconciliation result cluster (reconciliation.record/get +
    # report.reconciliation_mismatches) was UNFROZEN into the public Phase-2
    # catalog (bead trade-trace-opoc). It is the VISION Phase 2 "reconciliation
    # compares records against imported account truth" surface: reconciliation.record
    # runs a DETERMINISTIC derivation (_build_derived) that queries positions,
    # account_snapshots, external_execution_receipts, paper_fill_records,
    # pretrade_intents, and approval_waiver_records and derives a reproducible set
    # of stable mismatch codes (MISSING_EXTERNAL_EVENT, ORPHAN_EXTERNAL_*,
    # DUPLICATE_FILL, REJECTED_APPROVED_INTENT, PARTIAL_FILL_REMAINING_MISMATCH,
    # POSITION/PRICE/FEE/BALANCE_MISMATCH, STALE_SNAPSHOT, EVENT_EXPOSURE_UNAVAILABLE,
    # POLICY_WAIVER_BREACH). Caller-supplied codes are NOT unioned into that derived
    # set; they are recorded on a distinct `manually_flagged` channel so the derived
    # set stays byte-reproducible (the determinism hole at the old caller-union is
    # closed). The cluster is local-evidence-only, credential-blind, and
    # non-executing (no fetch, signing, placement, cancellation, settlement, fund
    # movement, or remediation), so it is safe in the default public catalog. A
    # freeze-state regression test pins this so a future re-freeze is caught
    # (tests/integration/test_reconciliation_records.py::test_reconciliation_cluster_is_not_frozen).
    #
    # The external execution-receipt import cluster
    # (external_receipt.import/get/list/report) was UNFROZEN into the public
    # Phase-2 catalog (bead trade-trace-g776). It is the import side of the
    # VISION Phase 2 "reconciliation compares records against imported account
    # truth" surface: external_receipt.import ingests one sanitized,
    # caller-supplied execution-event claim (submission/acceptance/rejection,
    # partial/full fill, cancel, expiry, correction, status) as APPEND-ONLY
    # LOCAL EVIDENCE only — labelled record_kind=
    # sanitized_imported_external_execution_receipt with provenance, never a
    # fact Trade Trace fetched. The module has no venue client, no private-auth
    # fetch, no signing, no placement, no cancellation, no custody movement, and
    # no remediation path; every record is non_executing / credential_blind.
    # Imports are quarantined at the boundary: malformed JSON / non-object
    # payloads raise malformed_*_quarantined, secret-bearing free text and
    # credential-shaped metadata are rejected before persistence
    # (reject_if_contains_secrets / reject_credential_metadata), and
    # material_hash / semantic_key mismatches are refused, so no
    # impossible/credential-bearing row lands. These rows are exactly what
    # reconciliation._build_derived consumes to derive ORPHAN_EXTERNAL_FILL/
    # ORDER, DUPLICATE_FILL, and REJECTED_APPROVED_INTENT, so freezing the
    # importer would starve the (already-public) reconciliation cluster. The
    # cluster is local-evidence-only, credential-blind, and non-executing, so it
    # is safe in the default public catalog. A freeze-state regression test pins
    # this so a future re-freeze is caught
    # (tests/integration/test_external_receipts.py::test_external_receipt_cluster_is_not_frozen).
    #
    # The account-snapshot import cluster (account_snapshot.import/get/list/report)
    # was UNFROZEN into the public Phase-2 catalog (bead trade-trace-qfn8). It is
    # the account-truth side of the VISION Phase 2 "reconciliation compares records
    # against imported account truth" surface (substrate spec §2.2 / §5.2):
    # account_snapshot.import ingests one sanitized, caller-supplied account-state
    # claim (balances, available/committed collateral, open orders, positions,
    # fills/trades, unsettled claims, public allowance facts, venue timestamps,
    # account label, environment) as APPEND-ONLY LOCAL EVIDENCE only — labelled
    # record_kind=sanitized_imported_account_snapshot with provenance and
    # source-precedence/confidence/staleness semantics, never a fact Trade Trace
    # fetched (local_evidence_only / non_executing / credential_blind). The module
    # has no venue client, no private-auth fetch, no signing, no placement, no
    # cancellation, no custody movement, and no remediation path. Imports are
    # quarantined at the boundary: malformed JSON / non-object / non-array payloads
    # raise malformed_*_quarantined, impossible/conflicting numeric account-state
    # (negative values, available>total) is refused, secret-bearing free text and
    # credential-shaped metadata are rejected before persistence, and
    # material_hash / semantic_key mismatches are refused, so no
    # impossible/credential-bearing row lands. These rows are exactly what
    # reconciliation._latest_snapshot reads (source_precedence ASC, as_of DESC,
    # imported_at DESC, id DESC) and _build_derived consumes to derive
    # STALE_SNAPSHOT / BALANCE_MISMATCH / POSITION_MISMATCH against local
    # projections, so freezing the importer would starve the (already-public)
    # reconciliation cluster. The cluster is local-evidence-only, credential-blind,
    # and non-executing, so it is safe in the default public catalog. A freeze-state
    # regression test pins this so a future re-freeze is caught
    # (tests/integration/test_account_snapshots.py::test_account_snapshot_cluster_is_not_frozen).
    "report.execution_quality",
    "report.operational_health",
})

# Anchored-calibration unit. The standalone anchor WRITER
# (forecast.anchor_to_snapshot) stays frozen: bead trade-trace-4kec.9
# (forecast.commit_blind / forecast.reveal_snapshot, in
# tools/forecast_independence.py) was built as its explicit semantic
# replacement — that module's docstring states it "supersedes the frozen
# forecast.anchor_to_snapshot, which linked a snapshot after the fact and
# proved nothing about blindness." Promoting the after-the-fact anchor writer
# into the public Phase-1 catalog would re-surface the deprecated anti-pattern
# the supersession removed. The anchor write it performs is ALREADY folded into
# forecast.add (see _anchor_forecast_to_snapshot_in_transaction, called inline
# from _insert_forecast's commit path when a snapshot_id /
# _anchor_to_latest_snapshot is supplied), so anchor_to_snapshot is retained
# only as a frozen backfill path, satisfying the 4kec.5 acceptance.
#
# Its three READERS, by contrast, are NOT superseded — they are read-only
# Phase-1 calibration diagnostics that measure forecast skill vs the market
# baseline (VISION Phase 1 "forecast scoring, calibration reports") over only
# Phase-1 tables (forecast_snapshot_anchor / forecast_scores / forecasts /
# outcomes / snapshots), with zero Phase-2 dependency. They were UNFROZEN into
# the public Phase-1 catalog (bead trade-trace-xtdo):
#   - report.calibration_anchored / report.calibration_terminal: market-baseline
#     Brier-skill panels over the inline-captured anchor.
#   - snapshot.fetch_series: the time-series snapshot fetcher (markets-table
#     backed) that populates the snapshot history those reports read; its
#     idempotency_key contract matches snapshot.fetch (both is_write, both
#     absent from TOOL_PRIMARY_EVENT_TYPE, so both require an explicit caller
#     key — pinned by test_snapshot_fetch_series_requires_idempotency_key).
EXPERIMENTAL_ANCHORED_VIEWERS: frozenset[str] = frozenset({
    "forecast.anchor_to_snapshot",
    # report.decision_velocity, report.memory_usefulness, and
    # report.recall_receipts were unfrozen into the Phase-1 public catalog
    # (bead trade-trace-8g7t). All three are fully-implemented, read-only
    # diagnostics over Phase-1 tables with zero Phase-2 dependency:
    # recall_receipts reconstructs recall attribution from
    # memory_recall_events / memory_nodes / edges; memory_usefulness wraps it
    # with negative controls; decision_velocity counts decisions bucketed by
    # day/week FROM decisions only. The original freeze rationale claimed
    # decision_velocity's day/week cadence was redundant with
    # calibration_integrity, but calibration_integrity emits only static
    # hygiene rates and process_analytics groups by tag/pair — neither
    # produces a per-day/week decision-count series, so decision_velocity is
    # the sole producer and was UNFROZEN rather than cut.
    # report.market_lifecycle and report.resolution_quality were unfrozen into
    # the Phase-1 public catalog (bead trade-trace-y0cr). Both read only
    # Phase-1 tables (markets, snapshots, decisions, forecasts, outcomes,
    # forecast_scores) and carry no Phase-2 dependency. market_lifecycle is
    # PM-native situational awareness with no public equivalent;
    # resolution_quality is the resolution-status quality family (status mix,
    # ambiguous/void/disputed/cancelled, pre-resolution uncertainty), distinct
    # from the public report.resolution_misreads (which classifies an agent's
    # interpreted-vs-actual resolution *source* over resolution_interpretations).
    # journal.restore was swept into this cluster only because it was "operator
    # DR, never dogfooded" — it has nothing to do with Phase 2 or the anchored
    # calibration flow (bead trade-trace-26sl). It is an admin-tier disaster-
    # recovery tool: gated via V002_ADMIN_TOOLS / is_admin alongside its
    # journal.backup counterpart, not frozen behind the experimental shelf.
})

EXPERIMENTAL_FROZEN_TOOLS: frozenset[str] = (
    EXPERIMENTAL_AUTONOMOUS_OPS
    | EXPERIMENTAL_RECONCILIATION
    | EXPERIMENTAL_ANCHORED_VIEWERS
)


def _apply_experimental_freeze(registry: ToolRegistry) -> None:
    """Mark frozen Product-B tools experimental (epic trade-trace-4kec)."""

    for name in EXPERIMENTAL_FROZEN_TOOLS:
        if name in registry.by_name:
            registry.mark(name, catalog_visibility="experimental")


def build_registry() -> ToolRegistry:
    """Build a fresh registry with every MVP tool registered.

    Validation runs at the end so a process startup never proceeds past
    a CLI-name collision; the test suite re-runs the same code path."""

    registry = ToolRegistry()
    register_abstention_tools(registry)
    register_account_snapshot_tools(registry)
    register_admin_tools(registry)
    register_approval_tools(registry)
    register_autonomous_record_tools(registry)
    register_external_receipt_tools(registry)
    register_export_tools(registry)
    register_fixture_tools(registry)
    register_forecast_independence_tools(registry)
    register_idea_tools(registry)
    register_journal_tools(registry)
    register_journal_bundle_status(registry)
    register_ledger_tools(registry)
    register_market_scan_tools(registry)
    register_market_similarity_tools(registry)
    register_memory_tools(registry)
    register_paper_fill_tools(registry)
    register_playbook_tools(registry)
    register_pretrade_intent_tools(registry)
    register_reflection_tools(registry)
    register_reconciliation_tools(registry)
    register_resolution_interpretation_tools(registry)
    register_replay_artifact_tools(registry)
    register_strategy_tools(registry)
    register_review_bundle(registry)
    register_risk_tools(registry)
    register_import_stubs(registry)
    register_csv_import(registry)
    register_report_tools(registry)
    register_signal_tools(registry)
    _apply_v002_catalog_overlay(registry)
    _apply_experimental_freeze(registry)
    registry.validate()
    return registry


def default_registry() -> ToolRegistry:
    """Return the process-wide registry, lazily constructed."""

    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_registry()
    return _DEFAULT_REGISTRY


_REQUEST_ID_COUNTER: list[int] = [0]
_SINGLE_WRITER_LOCK_MAX_RETRIES = 1


def _reset_deterministic_request_id_counter() -> None:
    _REQUEST_ID_COUNTER[0] = 0


def new_request_id() -> str:
    """Generate a request id. When CLOCK_OVERRIDE is set (deterministic
    replay scope), the request id is derived from a process-local
    counter so re-running the same fixture produces matching events
    table rows. Otherwise uses `uuid4().hex` for production-grade
    unpredictability."""

    if CLOCK_OVERRIDE.get() is not None:
        _REQUEST_ID_COUNTER[0] += 1
        return f"det-req-{_REQUEST_ID_COUNTER[0]:08d}".ljust(32, "0")[:32]
    return uuid.uuid4().hex


def _is_single_writer_lock_error(env: SuccessEnvelope | ErrorEnvelope) -> bool:
    if not isinstance(env, ErrorEnvelope):
        return False
    if env.error.code != ErrorCode.STORAGE_ERROR:
        return False
    return env.error.details.get("reason") == "single_writer_lock"


def _classify_integrity_error(msg: str) -> ErrorCode:
    """Map a sqlite3.IntegrityError message to a typed error code.

    Constraint checks match SQLite's full violation phrases ("UNIQUE
    constraint failed", "FOREIGN KEY constraint failed", "CHECK constraint
    failed") rather than the bare keyword, so a table/column name that merely
    contains the word UNIQUE/FOREIGN KEY cannot misclassify an unrelated
    storage error as a VALIDATION_ERROR (trade-trace-1k5d)."""

    if "append-only invariant" in msg:
        return ErrorCode.INVARIANT_VIOLATION
    if "VALIDATION_ERROR:" in msg:
        # Trigger-raised validation messages from migration 004.
        return ErrorCode.VALIDATION_ERROR
    if (
        "CHECK constraint" in msg
        or "FOREIGN KEY constraint" in msg
        or "UNIQUE constraint" in msg
    ):
        return ErrorCode.VALIDATION_ERROR
    return ErrorCode.STORAGE_ERROR


def dispatch(
    tool_name: str,
    args: dict[str, Any],
    *,
    actor_id: str = "cli:default",
    request_id: str | None = None,
    registry: ToolRegistry | None = None,
) -> SuccessEnvelope | ErrorEnvelope:
    """Invoke a registered tool and return a typed envelope.

    Both CLI and MCP adapters call into this function. The returned envelope
    is normalized for parity tests; the only divergence between transports
    happens during serialization (CLI NDJSON / MCP framing)."""

    reg = registry if registry is not None else default_registry()
    rid = request_id or new_request_id()
    meta = Meta(tool=tool_name, actor_id=actor_id, request_id=rid)
    trace_started_ns = dispatch_trace.now_ns() if dispatch_trace.is_enabled() else 0

    def _trace_return(
        env: SuccessEnvelope | ErrorEnvelope,
        *,
        attempt: int | None = None,
        retry_of: str | None = None,
    ) -> SuccessEnvelope | ErrorEnvelope:
        if trace_started_ns:
            dispatch_trace.emit(
                tool=tool_name,
                actor_id=actor_id,
                request_id=rid,
                args=args,
                env=env,
                started_ns=trace_started_ns,
                attempt=attempt,
                retry_of=retry_of,
            )
        return env

    # actor_id grammar validation per PRD §2 / trade-trace-3mp. Runs before
    # the tool lookup so malformed actors are rejected uniformly.
    try:
        validate_actor_id(actor_id)
    except ToolError as exc:
        return _trace_return(error_envelope(meta, exc.code, exc.message, exc.details))

    try:
        registration = reg.get(tool_name)
    except KeyError:
        return _trace_return(error_envelope(
            meta,
            ErrorCode.NOT_FOUND,
            f"unknown tool {tool_name!r}",
            {
                "entity_kind": "tool",
                "tool": tool_name,
                "known_tools": reg.names(),
            },
        ))

    ctx = ToolContext(tool=tool_name, actor_id=actor_id, request_id=rid, raw_args=args)

    # Detect the at-least-once opt-in and surface it on the response meta
    # per trade-trace-3mp.
    allow_no_idempotency = args.get("_allow_no_idempotency") is True
    if allow_no_idempotency:
        meta.idempotency_disabled = True

    # Enforce the idempotency_key contract for retryable writes per
    # persistence.md §5.3 + AI_AGENT_MCP_GETTING_STARTED.md §7 (bead
    # trade-trace-cpz2). The opt-out (`--allow-no-idempotency` /
    # `_allow_no_idempotency: true`) is the only legal absence path.
    #
    # Per bead trade-trace-t7hi: when the agent omits an explicit key
    # for a write tool whose semantic identity is covered by the
    # `TOOL_PRIMARY_EVENT_TYPE` registry, derive a deterministic
    # `auto:` key from `sha256(tool_name + canonical_json(structural))`.
    # This honors the v0.0.2 "zero hand-crafted idempotency keys"
    # promise without weakening the at-least-once invariant — replays
    # of identical input collapse onto the same key, while collisions
    # surface through the existing IDEMPOTENCY_CONFLICT path. Tools
    # outside the registry continue to require an explicit key.
    is_retryable_write = registration.is_write and not allow_no_idempotency
    ctx_idempotency_source: str | None
    if is_retryable_write and not args.get("idempotency_key"):
        derived = derive_idempotency_key(tool_name, args)
        if derived is not None:
            args = {**args, "idempotency_key": derived}
            ctx_idempotency_source = "auto"
        else:
            return _trace_return(error_envelope(
                meta,
                ErrorCode.VALIDATION_ERROR,
                (
                    f"{tool_name!r} is a retryable write and requires "
                    "`idempotency_key`; pass `_allow_no_idempotency: true` "
                    "(CLI: `--allow-no-idempotency`) to opt into at-least-once "
                    "semantics for batch importers/admin paths."
                ),
                {
                    "field": "idempotency_key",
                    "tool": tool_name,
                    "opt_out_cli": "--allow-no-idempotency",
                    "opt_out_mcp": "_allow_no_idempotency",
                    "auto_derivation_available": False,
                },
            ))
    elif is_retryable_write:
        # Reached only when an idempotency_key is present (the branch above
        # consumed the missing-key case), so the caller supplied the key.
        ctx_idempotency_source = "caller"
    else:
        ctx_idempotency_source = None

    # Dry-run plumbing per trade-trace-268. The flag is request-scoped so
    # concurrent dispatches do not contaminate each other; UnitOfWork picks
    # it up and rolls back instead of committing. The meta envelope echoes
    # the flag back to the agent as `meta.dry_run = true`.
    dry_run = args.get("_dry_run") is True
    dry_run_token = DRY_RUN_FLAG.set(True) if dry_run else None
    if dry_run:
        ctx.meta_hints["dry_run"] = True

    # Surface the auto/caller origin of the idempotency key (bead
    # trade-trace-t7hi) so audit and the calibration-of-correctness
    # surface can distinguish hand-supplied keys from server-derived ones.
    if ctx_idempotency_source is not None:
        ctx.meta_hints["idempotency_source"] = ctx_idempotency_source

    def _apply_hints() -> None:
        """Propagate ctx.meta_hints onto the envelope's Meta object.

        Per bead trade-trace-30u / DEBT-008: Meta is declared with
        `extra='allow'`, signalling that callers may surface custom
        metadata the standard model doesn't know about. Known keys
        land on typed fields via setattr; unknown keys land in
        `Meta.__pydantic_extra__` so they serialize into the envelope's
        `meta` dict instead of disappearing silently.
        """

        extras = meta.__pydantic_extra__
        if extras is None:  # pragma: no cover - extra='allow' guarantees a dict
            extras = {}
            meta.__pydantic_extra__ = extras
        for key, value in ctx.meta_hints.items():
            if key in Meta.model_fields:
                setattr(meta, key, value)
            else:
                extras[key] = value

    def _invoke_once() -> SuccessEnvelope | ErrorEnvelope:
        try:
            data = registration.handler(args, ctx)
        except ToolError as exc:
            _apply_hints()
            return error_envelope(meta, exc.code, exc.message, exc.details)
        except HomePathValidationError as exc:
            # Traversal attempts in --home / journal home (bead trade-trace-pqex)
            # surface as a typed VALIDATION_ERROR envelope regardless of which
            # tool handler called resolve_home.
            _apply_hints()
            return error_envelope(
                meta,
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                {
                    "field": "home",
                    "value": exc.value,
                    "reason": "path_traversal_rejected",
                },
            )
        except IdempotencyConflictError as exc:
            _apply_hints()
            return error_envelope(
                meta,
                ErrorCode.IDEMPOTENCY_CONFLICT,
                str(exc),
                {
                    "event_type": exc.event_type,
                    "actor_id": exc.actor_id,
                    "idempotency_key": exc.idempotency_key,
                    "original_event_id": exc.original_event_id,
                    "diff_summary": exc.diff_summary,
                },
            )
        except sqlite3.IntegrityError as exc:
            # SQLite CHECK / FK / UNIQUE / append-only-trigger violations all
            # surface as IntegrityError. Translate them into a typed envelope so
            # callers can branch on a stable code.
            msg = str(exc)
            code = _classify_integrity_error(msg)
            _apply_hints()
            return error_envelope(meta, code, msg, {"sqlite_error": msg})
        except sqlite3.Error as exc:
            _apply_hints()
            msg = str(exc)
            details: dict[str, object] = {"sqlite_error": msg}
            if "database is locked" in msg.lower() or "database table is locked" in msg.lower():
                # operability.md §3.2: second writer contention is a transient
                # single-writer failure. The envelope reports the initial
                # recommended wait; callers may exponentially back off from
                # that 2-second starting point. SQLite already waited for the
                # connection's busy_timeout before surfacing this error.
                details.update({"reason": "single_writer_lock", "retry_after_seconds": 2})
            return error_envelope(
                meta,
                ErrorCode.STORAGE_ERROR,
                msg,
                details,
            )

        if not isinstance(data, dict):
            # Handlers must return a dict; treat anything else as an invariant
            # violation so the bug surfaces immediately rather than producing
            # a malformed envelope.
            _apply_hints()
            return error_envelope(
                meta,
                ErrorCode.INVARIANT_VIOLATION,
                f"tool {tool_name!r} returned non-dict result",
                {"result_type": type(data).__name__},
            )

        _apply_hints()
        return SuccessEnvelope(data=data, meta=meta)

    try:
        retry_of: str | None = None
        for attempt in range(1, _SINGLE_WRITER_LOCK_MAX_RETRIES + 2):
            env = _invoke_once()
            if (
                isinstance(env, ErrorEnvelope)
                and _is_single_writer_lock_error(env)
                and attempt <= _SINGLE_WRITER_LOCK_MAX_RETRIES
            ):
                _trace_return(env, attempt=attempt, retry_of=retry_of)
                retry_of = rid
                retry_after = env.error.details.get("retry_after_seconds", 2)
                try:
                    delay = float(retry_after)
                except (TypeError, ValueError):
                    delay = 2.0
                time.sleep(max(delay, 0.0))
                continue
            return _trace_return(env, attempt=attempt, retry_of=retry_of)
        raise AssertionError("unreachable single-writer retry loop exit")
    finally:
        if dry_run_token is not None:
            DRY_RUN_FLAG.reset(dry_run_token)
