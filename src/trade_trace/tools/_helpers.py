"""Shared helpers for write tools: ID generation, home resolution, common
metadata extraction. The boilerplate that every M1 ledger tool needs.
"""

from __future__ import annotations

import json
import math
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from trade_trace._permissions import chmod_user_only_dir
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.security.credential_keys import PROJECT_CREDENTIAL_KEYS
from trade_trace.storage import open_database, resolve_home
from trade_trace.storage.database import ReadOnlyDatabaseError, open_database_readonly
from trade_trace.storage.paths import HomePathValidationError, db_path
from trade_trace.timestamps import TimestampValidationError, to_utc_iso8601
from trade_trace.tools.errors import ToolError

# Allowed `theses.confidence_label` values. Mirrors the SQLite CHECK
# constraint in storage/migrations/m003_m1_ledger.py and
# reports/buckets.py:CONFIDENCE_LABELS. Validated in Python so an invalid
# label returns a clean VALIDATION_ERROR with the allowed set instead of
# leaking the raw SQLite CHECK-constraint failure (ax-dogfood AX-010).
CONFIDENCE_LABELS: tuple[str, ...] = (
    "very_low", "low", "medium", "high", "very_high",
)


def canonical_json(value: Any) -> str:
    """Return deterministic compact JSON for material-hash inputs."""

    return json.dumps(value if value is not None else {}, sort_keys=True, separators=(",", ":"), default=str)


def validate_confidence_label(value: Any) -> None:
    """Raise a clean VALIDATION_ERROR (with allowed values) for an
    out-of-enum `confidence_label`. None is allowed (column is nullable)."""

    if value is None or value in CONFIDENCE_LABELS:
        return
    raise ToolError(
        ErrorCode.VALIDATION_ERROR,
        "invalid confidence_label",
        details={
            "field": "confidence_label",
            "value": value,
            "allowed": list(CONFIDENCE_LABELS),
        },
    )


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


def _resolve_home_arg(args: dict[str, Any]):
    """Resolve `args["home"]` via `storage.paths.resolve_home`, translating
    `HomePathValidationError` into a typed `VALIDATION_ERROR` envelope
    (bead trade-trace-pqex)."""

    try:
        return resolve_home(args.get("home"))
    except HomePathValidationError as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            str(exc),
            details={
                "field": "home",
                "value": exc.value,
                "reason": "path_traversal_rejected",
            },
        ) from exc


def open_db_for_args(args: dict[str, Any]):
    """Resolve $TRADE_TRACE_HOME and open a DB connection for write."""

    home = _resolve_home_arg(args)
    home.mkdir(parents=True, exist_ok=True)
    # Pin home to 0700 immediately after creation (bead trade-trace-pqex)
    # so a fresh journal-home directory cannot leak via the caller's
    # umask while the journal-not-initialized error is being raised.
    chmod_user_only_dir(home)
    path = db_path(home)
    if not path.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            "journal not initialized; run `tt journal init` first",
            details={"home": str(home), "db_path": str(path)},
        )
    return open_database(path, create_parent=False)


def open_ro_db_for_args(args: dict[str, Any]):
    """Resolve $TRADE_TRACE_HOME and open a DB connection for read-only access."""

    home = _resolve_home_arg(args)
    path = db_path(home)
    if not path.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            "journal not initialized; run `tt journal init` first",
            details={"home": str(home), "db_path": str(path)},
        )
    try:
        return open_database_readonly(path)
    except ReadOnlyDatabaseError as exc:
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            str(exc),
            details={"home": str(home), "db_path": str(path), "reason": exc.reason},
        ) from exc


@contextmanager
def db_for_args(args: dict[str, Any]) -> Iterator[Any]:
    """Context-manager form of `open_db_for_args` for write handlers.

    Opens the write DB and guarantees `close()` on exit, replacing the
    repeated ``db = open_db_for_args(args); try: ... finally: db.close()``
    idiom. Yields the `Database`; use ``db.connection`` for the underlying
    sqlite3 connection (e.g. ``with db_for_args(args) as db: UnitOfWork(db.connection)``).
    """

    db = open_db_for_args(args)
    try:
        yield db
    finally:
        db.close()


@contextmanager
def ro_db_for_args(args: dict[str, Any]) -> Iterator[Any]:
    """Context-manager form of `open_ro_db_for_args` for read-only handlers."""

    db = open_ro_db_for_args(args)
    try:
        yield db
    finally:
        db.close()


def require(args: dict[str, Any], field: str) -> Any:
    """Return args[field] or raise VALIDATION_ERROR with details.field set."""

    if field not in args or args[field] is None:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"{field} is required",
            details={"field": field},
        )
    return args[field]


def validate_fk_refs(
    conn: Any,
    args: dict[str, Any],
    ref_tables: dict[str, str],
) -> list[dict[str, str]]:
    """Return missing foreign-key-like references for simple id fields."""

    missing: list[dict[str, str]] = []
    for field, table in ref_tables.items():
        value = args.get(field)
        if value and conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (value,)).fetchone() is None:
            missing.append({"field": field, "id": str(value), "table": table})
    return missing


def parse_int_arg(
    args: dict[str, Any],
    field: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
    message: str | None = None,
    range_message: str | None = None,
) -> int:
    raw = args.get(field, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            message or f"{field} must be an integer",
            details={"field": field, "value": raw},
        ) from exc
    if (minimum is not None and value < minimum) or (
        maximum is not None and value > maximum
    ):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            range_message or message or f"{field} is out of range",
            details={"field": field, "value": value},
        )
    return value


def parse_float_arg(
    args: dict[str, Any],
    field: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    message: str | None = None,
    range_message: str | None = None,
) -> float:
    raw = args.get(field, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            message or f"{field} must be a number",
            details={"field": field, "value": raw},
        ) from exc
    if not math.isfinite(value) or (
        minimum is not None and value < minimum
    ) or (maximum is not None and value > maximum):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            range_message or message or f"{field} is out of range",
            details={"field": field, "value": raw},
        )
    return value


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


def reject_credential_metadata(value: Any, *, field: str) -> None:
    """Reject explicit metadata JSON that tries to carry credentials.

    Unknown top-level credential-shaped args are ignored by schemas, but
    caller-provided metadata_json is intentionally persisted. Guard it
    recursively so explicit JSON objects or raw JSON strings cannot bypass
    the no-credentials policy. Shared across ledger, strategy, and playbook
    surfaces (bead trade-trace-21q4).
    """

    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(forbidden in key_text for forbidden in PROJECT_CREDENTIAL_KEYS):
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"{field} contains credential-shaped key "
                    f"{key!r}; strip credentials before submitting",
                    details={"field": field,
                             "credential_key": str(key)},
                )
            reject_credential_metadata(child, field=field)
        return
    if isinstance(value, list):
        for child in value:
            reject_credential_metadata(child, field=field)
        return
    if isinstance(value, str):
        reject_if_contains_secrets(value, field=field)


def store_metadata_json(args: dict[str, Any], key: str = "metadata_json") -> str:
    """Serialize a caller-supplied metadata_json/meta_json field with the
    dual-layer secret + credential guard (bead trade-trace-21q4).

    Returns the canonical JSON string ready for INSERT. Accepts a parsed
    object (dict/list/primitive) or a JSON string; either way both
    `reject_if_contains_secrets` and `reject_credential_metadata` see the
    decoded structure so credential keys cannot hide inside raw JSON text.
    """

    value = args.get(key)
    if value is None:
        return "{}"
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as err:
            reject_if_contains_secrets(value, field=key)
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{key} must be valid JSON when supplied as a string",
                details={"field": key, "reason": "invalid_json"},
            ) from err
        else:
            reject_credential_metadata(decoded, field=key)
        return value
    reject_credential_metadata(value, field=key)
    return json.dumps(value, sort_keys=True, default=str)


def reject_if_contains_secrets(value: Any, *, field: str) -> None:
    """Raise VALIDATION_ERROR with `details.pattern_kind` +
    `details.match_offset` if `value` carries any registered secret
    shape (per bead trade-trace-sy1). No-ops on non-strings and empty
    strings.

    Used to guard user-supplied free-text fields (thesis.body,
    source title/note/excerpt/extracted_text/summary, decision.reason)
    at write time so the journal never holds an unredacted secret in
    the first place.
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
