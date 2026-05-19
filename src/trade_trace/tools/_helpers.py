"""Shared helpers for write tools: ID generation, home resolution, common
metadata extraction. The boilerplate that every M1 ledger tool needs.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.storage import open_database, resolve_home
from trade_trace.storage.paths import db_path
from trade_trace.timestamps import TimestampValidationError, to_utc_iso8601
from trade_trace.tools.errors import ToolError

_DETERMINISTIC_ID_COUNTER: dict[str, int] = {}


def reset_deterministic_id_counter() -> None:
    """Reset the deterministic id counter. Called at the start of the
    fixture seed so re-running on a fresh home yields the same id
    sequence."""

    _DETERMINISTIC_ID_COUNTER.clear()


def new_id(prefix: str) -> str:
    """Generate a short, URL-safe ID with a recognizable prefix
    (`i_xxx` for instrument, `t_xxx` for thesis, etc.).

    When the CLOCK_OVERRIDE context var is set (i.e. we're running
    inside a deterministic-replay scope like the fixture seeder or a
    determinism test), the id is derived from a per-prefix counter so
    repeated runs produce the same sequence of ids. Otherwise the id
    comes from `secrets.token_urlsafe(12)` for production-grade
    unpredictability."""

    if CLOCK_OVERRIDE.get() is not None:
        next_idx = _DETERMINISTIC_ID_COUNTER.get(prefix, 0) + 1
        _DETERMINISTIC_ID_COUNTER[prefix] = next_idx
        return f"{prefix}_det{next_idx:08d}"
    return f"{prefix}_{secrets.token_urlsafe(12)}"


from contextvars import ContextVar  # noqa: E402

CLOCK_OVERRIDE: ContextVar[datetime | None] = ContextVar(
    "trade_trace.clock_override", default=None,
)
"""Request-scoped clock override per bead trade-trace-64q. When set,
`now_iso()` returns the injected timestamp's ISO8601 form instead of
`datetime.now(tz=utc)`. Used by deterministic-replay tests + the
fixture seed tool; CLI/MCP transport entry points never set it."""


def now_iso() -> str:
    override = CLOCK_OVERRIDE.get()
    if override is not None:
        return to_utc_iso8601(override.isoformat())
    return to_utc_iso8601(datetime.now(UTC).isoformat())


def open_db_for_args(args: dict[str, Any]):
    """Resolve $TRADE_TRACE_HOME and open a DB connection for write."""

    home = resolve_home(args.get("home"))
    home.mkdir(parents=True, exist_ok=True)
    path = db_path(home)
    if not path.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            "journal not initialized; run `tt journal init` first",
            details={"home": str(home), "db_path": str(path)},
        )
    return open_database(path, create_parent=False)


def require(args: dict[str, Any], field: str) -> Any:
    """Return args[field] or raise VALIDATION_ERROR with details.field set."""

    if field not in args or args[field] is None:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"{field} is required",
            details={"field": field},
        )
    return args[field]


def forbidden(args: dict[str, Any], field: str) -> None:
    """Raise VALIDATION_ERROR if `args[field]` is set (used for the decision
    required-field matrix where some fields are forbidden per type)."""

    if field in args and args[field] is not None:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"{field} is forbidden for this decision type",
            details={"field": field, "decision_type": args.get("type")},
        )


_TIMESTAMP_EXPECTED_FORMAT = (
    "UTC ISO 8601 with millisecond precision (e.g., 2026-05-18T15:30:00.000Z); "
    "operability.md §2.1"
)


def normalize_timestamp(args: dict[str, Any], field: str, *, required: bool = False) -> str | None:
    """Apply operability.md §2.1 timestamp normalization to a field. Returns
    the canonical UTC ISO 8601 string, None if absent and not required, or
    raises VALIDATION_ERROR with `details.expected_format` set so an agent
    can recover from a malformed timestamp without re-reading the docs
    (bead trade-trace-268)."""

    value = args.get(field)
    if value is None:
        if required:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{field} is required",
                details={
                    "field": field,
                    "expected_format": _TIMESTAMP_EXPECTED_FORMAT,
                },
            )
        return None
    try:
        return to_utc_iso8601(value, field=field)
    except TimestampValidationError as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            str(exc),
            details={
                "field": field,
                "expected_format": _TIMESTAMP_EXPECTED_FORMAT,
            },
        ) from exc


def reject_if_contains_secrets(value: Any, *, field: str) -> None:
    """Raise VALIDATION_ERROR with `details.pattern_kind` +
    `details.match_offset` if `value` carries any registered secret
    shape (per bead trade-trace-sy1). No-ops on non-strings and empty
    strings.

    Used to guard user-supplied free-text fields (thesis.body,
    source.excerpt, decision.reason) at write time so the journal
    never holds an unredacted secret in the first place.
    """

    if not isinstance(value, str) or not value:
        return
    from trade_trace.security import scan_text

    matches = scan_text(value)
    if not matches:
        return
    first = matches[0]
    raise ToolError(
        ErrorCode.VALIDATION_ERROR,
        (
            f"{field} contains a secret-shaped substring "
            f"(pattern_kind={first.pattern_kind!r}); strip the secret "
            "before submitting (operability.md §6.3)."
        ),
        details={
            "field": field,
            "pattern_kind": first.pattern_kind,
            "match_offset": first.match_offset,
            "match_length": first.length,
            "additional_matches": len(matches) - 1,
        },
    )


def common_metadata(args: dict[str, Any]) -> dict[str, Any]:
    """Extract the optional segmentation fields per PRD §2."""

    return {
        "agent_id": args.get("agent_id"),
        "model_id": args.get("model_id"),
        "environment": args.get("environment"),
        "run_id": args.get("run_id"),
    }


def check_idempotency_replay(
    uow: UnitOfWork,
    *,
    event_type: str,
    actor_id: str,
    idempotency_key: str | None,
) -> dict[str, Any] | None:
    """Look up an existing event by `(event_type, actor_id, idempotency_key)`.

    Returns the parsed payload of the original event (carrying the original
    `id` field), or None if no match exists. Caller short-circuits the
    relational INSERT and returns the original row's data on a hit.

    The actual semantic-equivalence comparison happens later when the
    caller's EventWriter.write is invoked with the new payload — that path
    raises `IdempotencyConflictError` on a conflict.
    """

    if idempotency_key is None:
        return None
    existing = uow.event_writer.find_existing(
        event_type=event_type,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )
    if existing is None:
        return None
    return json.loads(existing.payload_json)


def emit_event(
    uow: UnitOfWork,
    *,
    event_type: str,
    subject_kind: str,
    subject_id: str,
    payload: dict[str, Any],
    actor_id: str,
    idempotency_key: str | None,
    ctx: ToolContext | None = None,
) -> None:
    """Convenience for ledger tools: write a single event inside the
    current UnitOfWork with `allow_no_idempotency=True` (M1 ledger tools
    tolerate missing keys for backward compatibility — when the agent
    supplies a key, replay is honored).

    Records the resulting event's row id (or the replayed event's id) and
    the `idempotent_replay` flag on `ctx.meta_hints` so the dispatcher
    promotes them onto `meta.event_id` / `meta.idempotent_replay` per
    contracts.md §3.2. The first emit per call wins for `event_id` (the
    "primary" event); subsequent cascaded emits do not overwrite it.
    """

    request_id = ctx.request_id if ctx is not None else None
    record = uow.event_writer.write(
        event_type=event_type,
        subject_kind=subject_kind,
        subject_id=subject_id,
        payload=payload,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        request_id=request_id,
        allow_no_idempotency=True,
    )
    if ctx is not None:
        ctx.meta_hints.setdefault("event_id", record.id)
        if record.idempotent_replay:
            ctx.meta_hints["idempotent_replay"] = True

