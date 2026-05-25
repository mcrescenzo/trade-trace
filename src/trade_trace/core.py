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
import uuid
from typing import Any

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
from trade_trace.tools.adapter_polymarket import register_adapter_polymarket_tools
from trade_trace.tools.admin import register_admin_tools
from trade_trace.tools.csv_import import register_csv_import
from trade_trace.tools.errors import ToolError
from trade_trace.tools.export import register_export_tools
from trade_trace.tools.fixture import register_fixture_tools
from trade_trace.tools.ideas import register_idea_tools
from trade_trace.tools.imports import register_import_stubs
from trade_trace.tools.journal import register_journal_tools
from trade_trace.tools.journal_bundle_status import register_journal_bundle_status
from trade_trace.tools.ledger import register_ledger_tools
from trade_trace.tools.market_bind import register_market_bind_tool
from trade_trace.tools.market_scan import register_market_scan_tools
from trade_trace.tools.memory import register_memory_tools
from trade_trace.tools.playbook import register_playbook_tools
from trade_trace.tools.reflection import register_reflection_tools
from trade_trace.tools.reports import register_report_tools
from trade_trace.tools.review_bundle import register_review_bundle
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
    "strategy.create": "strategy.upsert",
    "strategy.update": "strategy.upsert",
    "strategy.list": "report.strategy_health",
    "strategy.show": "report.strategy_health",
    "playbook.create": "playbook.upsert",
    "playbook.list": "playbook.upsert",
    "playbook.show": "playbook.upsert",
    "playbook.list_versions": "playbook.upsert",
    "playbook.propose_version": "playbook.upsert",
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
    "keyring.revoke": None,
}

V002_ADMIN_TOOLS = {
    "journal.rebuild_projections",
    "journal.repair",
    "signal.scan",
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
    registry.alias(
        "playbook.record_adherence",
        "decision.record_adherence",
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


def build_registry() -> ToolRegistry:
    """Build a fresh registry with every MVP tool registered.

    Validation runs at the end so a process startup never proceeds past
    a CLI-name collision; the test suite re-runs the same code path."""

    registry = ToolRegistry()
    register_admin_tools(registry)
    register_export_tools(registry)
    register_fixture_tools(registry)
    register_idea_tools(registry)
    register_journal_tools(registry)
    register_journal_bundle_status(registry)
    register_ledger_tools(registry)
    register_market_scan_tools(registry)
    register_memory_tools(registry)
    register_playbook_tools(registry)
    register_reflection_tools(registry)
    register_strategy_tools(registry)
    register_review_bundle(registry)
    register_import_stubs(registry)
    register_csv_import(registry)
    register_report_tools(registry)
    register_signal_tools(registry)
    _apply_v002_catalog_overlay(registry)
    registry.validate()
    return registry


def default_registry() -> ToolRegistry:
    """Return the process-wide registry, lazily constructed."""

    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_registry()
    return _DEFAULT_REGISTRY


_REQUEST_ID_COUNTER: list[int] = [0]


def _reset_deterministic_request_id_counter() -> None:
    _REQUEST_ID_COUNTER[0] = 0


def new_request_id() -> str:
    """Generate a request id. When CLOCK_OVERRIDE is set (deterministic
    replay scope), the request id is derived from a process-local
    counter so re-running the same fixture produces matching events
    table rows. Otherwise uses `uuid4().hex` for production-grade
    unpredictability."""

    from trade_trace.tools._helpers import CLOCK_OVERRIDE

    if CLOCK_OVERRIDE.get() is not None:
        _REQUEST_ID_COUNTER[0] += 1
        return f"det-req-{_REQUEST_ID_COUNTER[0]:08d}".ljust(32, "0")[:32]
    return uuid.uuid4().hex


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

    # actor_id grammar validation per PRD §2 / trade-trace-3mp. Runs before
    # the tool lookup so malformed actors are rejected uniformly.
    try:
        validate_actor_id(actor_id)
    except ToolError as exc:
        return error_envelope(meta, exc.code, exc.message, exc.details)

    try:
        registration = reg.get(tool_name)
    except KeyError:
        return error_envelope(
            meta,
            ErrorCode.NOT_FOUND,
            f"unknown tool {tool_name!r}",
            {
                "entity_kind": "tool",
                "tool": tool_name,
                "known_tools": reg.names(),
            },
        )

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
    if (
        registration.is_write
        and not allow_no_idempotency
        and not args.get("idempotency_key")
    ):
        derived = derive_idempotency_key(tool_name, args)
        if derived is not None:
            args = {**args, "idempotency_key": derived}
            ctx_idempotency_source: str | None = "auto"
        else:
            return error_envelope(
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
            )
    else:
        ctx_idempotency_source = (
            "caller" if (
                registration.is_write
                and not allow_no_idempotency
                and args.get("idempotency_key")
            ) else None
        )

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

    try:
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
            if "append-only invariant" in msg:
                code = ErrorCode.INVARIANT_VIOLATION
            elif "VALIDATION_ERROR:" in msg:
                # Trigger-raised validation messages from migration 004.
                code = ErrorCode.VALIDATION_ERROR
            elif "CHECK constraint" in msg or "FOREIGN KEY" in msg or "UNIQUE" in msg:
                code = ErrorCode.VALIDATION_ERROR
            else:
                code = ErrorCode.STORAGE_ERROR
            _apply_hints()
            return error_envelope(meta, code, msg, {"sqlite_error": msg})
        except sqlite3.Error as exc:
            _apply_hints()
            return error_envelope(
                meta,
                ErrorCode.STORAGE_ERROR,
                str(exc),
                {"sqlite_error": str(exc)},
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
    finally:
        if dry_run_token is not None:
            DRY_RUN_FLAG.reset(dry_run_token)
