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
    ErrorBody,
    ErrorEnvelope,
    Meta,
    SuccessEnvelope,
)
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.grammar import validate_actor_id
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.log import IdempotencyConflictError
from trade_trace.events.unit_of_work import DRY_RUN_FLAG
from trade_trace.tools.admin import register_admin_tools
from trade_trace.tools.errors import ToolError
from trade_trace.tools.fixture import register_fixture_tools
from trade_trace.tools.csv_import import register_csv_import
from trade_trace.tools.imports import register_import_stubs
from trade_trace.tools.journal import register_journal_tools
from trade_trace.tools.ledger import register_ledger_tools
from trade_trace.tools.memory import register_memory_tools
from trade_trace.tools.playbook import register_playbook_tools
from trade_trace.tools.reflection import register_reflection_tools
from trade_trace.tools.reports import register_report_tools
from trade_trace.tools.review_bundle import register_review_bundle
from trade_trace.tools.signals import register_signal_tools
from trade_trace.tools.strategy import register_strategy_tools

_DEFAULT_REGISTRY: ToolRegistry | None = None


def build_registry() -> ToolRegistry:
    """Build a fresh registry with every MVP tool registered.

    Validation runs at the end so a process startup never proceeds past
    a CLI-name collision; the test suite re-runs the same code path."""

    registry = ToolRegistry()
    register_admin_tools(registry)
    register_fixture_tools(registry)
    register_journal_tools(registry)
    register_ledger_tools(registry)
    register_memory_tools(registry)
    register_playbook_tools(registry)
    register_reflection_tools(registry)
    register_strategy_tools(registry)
    register_review_bundle(registry)
    register_import_stubs(registry)
    register_csv_import(registry)
    register_report_tools(registry)
    register_signal_tools(registry)
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
        return ErrorEnvelope(
            error=ErrorBody(code=exc.code, message=exc.message, details=exc.details),
            meta=meta,
        )

    try:
        registration = reg.get(tool_name)
    except KeyError:
        return ErrorEnvelope(
            error=ErrorBody(
                code=ErrorCode.NOT_FOUND,
                message=f"unknown tool {tool_name!r}",
                details={
                    "entity_kind": "tool",
                    "tool": tool_name,
                    "known_tools": reg.names(),
                },
            ),
            meta=meta,
        )

    ctx = ToolContext(tool=tool_name, actor_id=actor_id, request_id=rid, raw_args=args)

    # Detect the at-least-once opt-in and surface it on the response meta
    # per trade-trace-3mp.
    if args.get("_allow_no_idempotency") is True:
        meta.idempotency_disabled = True

    # Dry-run plumbing per trade-trace-268. The flag is request-scoped so
    # concurrent dispatches do not contaminate each other; UnitOfWork picks
    # it up and rolls back instead of committing. The meta envelope echoes
    # the flag back to the agent as `meta.dry_run = true`.
    dry_run = args.get("_dry_run") is True
    dry_run_token = DRY_RUN_FLAG.set(True) if dry_run else None
    if dry_run:
        ctx.meta_hints["dry_run"] = True

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
            return ErrorEnvelope(
                error=ErrorBody(code=exc.code, message=exc.message, details=exc.details),
                meta=meta,
            )
        except IdempotencyConflictError as exc:
            _apply_hints()
            return ErrorEnvelope(
                error=ErrorBody(
                    code=ErrorCode.IDEMPOTENCY_CONFLICT,
                    message=str(exc),
                    details={
                        "event_type": exc.event_type,
                        "actor_id": exc.actor_id,
                        "idempotency_key": exc.idempotency_key,
                        "original_event_id": exc.original_event_id,
                        "diff_summary": exc.diff_summary,
                    },
                ),
                meta=meta,
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
            return ErrorEnvelope(
                error=ErrorBody(code=code, message=msg, details={"sqlite_error": msg}),
                meta=meta,
            )
        except sqlite3.Error as exc:
            _apply_hints()
            return ErrorEnvelope(
                error=ErrorBody(
                    code=ErrorCode.STORAGE_ERROR,
                    message=str(exc),
                    details={"sqlite_error": str(exc)},
                ),
                meta=meta,
            )

        if not isinstance(data, dict):
            # Handlers must return a dict; treat anything else as an invariant
            # violation so the bug surfaces immediately rather than producing
            # a malformed envelope.
            _apply_hints()
            return ErrorEnvelope(
                error=ErrorBody(
                    code=ErrorCode.INVARIANT_VIOLATION,
                    message=f"tool {tool_name!r} returned non-dict result",
                    details={"result_type": type(data).__name__},
                ),
                meta=meta,
            )

        _apply_hints()
        return SuccessEnvelope(data=data, meta=meta)
    finally:
        if dry_run_token is not None:
            DRY_RUN_FLAG.reset(dry_run_token)
