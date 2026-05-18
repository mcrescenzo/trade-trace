"""Event log writer with idempotency + outbox per persistence.md §3-§6.

`EventWriter.write()` is the single entry point for committing an event row.
It enforces the persistence.md §5 idempotency contract:

- Caller supplies `(event_type, actor_id, idempotency_key, payload)`.
- A pure replay (same key, semantically equivalent payload) returns the
  original event's row WITHOUT writing a new one; the caller surfaces
  `meta.idempotent_replay = true`.
- An incompatible-payload reuse (same key, semantically different payload)
  raises `IdempotencyConflictError` with a structural diff summary.
- A missing key on a retryable write raises `ValueError` (the dispatcher
  translates this to a `VALIDATION_ERROR` envelope; persistence.md §5.3).
- A successful new event also inserts an `outbox` row when the config flag
  `outbox.jsonl_enabled` is set.

The writer is transport-agnostic; it does not know whether the call came
from CLI, MCP, or an importer. The same primitive backs all three.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from trade_trace.contracts.grammar import validate_actor_id, validate_idempotency_key
from trade_trace.events.semantic_keys import (
    SEMANTIC_KEYS,
    canonicalize_payload,
    payloads_equivalent,
)
from trade_trace.timestamps import to_utc_iso8601


class IdempotencyConflictError(RuntimeError):
    """Raised when an idempotency-key replay carries a semantically different
    payload than the original write. The error carries the structural diff
    (no raw payload bodies, per persistence.md §5.2)."""

    def __init__(
        self,
        *,
        event_type: str,
        actor_id: str,
        idempotency_key: str,
        original_event_id: int,
        diff_summary: dict[str, Any],
    ) -> None:
        self.event_type = event_type
        self.actor_id = actor_id
        self.idempotency_key = idempotency_key
        self.original_event_id = original_event_id
        self.diff_summary = diff_summary
        super().__init__(
            f"IDEMPOTENCY_CONFLICT: event_type={event_type!r} "
            f"actor_id={actor_id!r} idempotency_key={idempotency_key!r} "
            f"diff_keys={diff_summary.get('diff_keys')}"
        )


@dataclass
class EventRecord:
    id: int
    event_type: str
    subject_kind: str
    subject_id: str
    payload_json: str
    actor_id: str
    idempotency_key: str | None
    created_at: str
    request_id: str | None
    agent_id: str | None
    model_id: str | None
    environment: str | None
    run_id: str | None
    idempotent_replay: bool = False

    def to_jsonl_line(self) -> dict[str, Any]:
        """Shape the row for JSONL export per operability.md §9.2 and
        imports.md §2.1.

        The line carries a `{tool, args}` envelope so the importer can
        dispatch directly without bespoke per-event glue. Underscore-prefixed
        keys are transport metadata the importer ignores on input.
        """

        from trade_trace.exporter import resolve_tool_for_event

        payload = json.loads(self.payload_json)
        args = {k: v for k, v in payload.items() if not k.startswith("_")}
        return {
            "tool": resolve_tool_for_event(self.event_type, args),
            "args": args,
            "_event_id": self.id,
            "_event_type": self.event_type,
            "_actor_id": self.actor_id,
            "_created_at": self.created_at,
            "_contract_version": "1.0",
        }


class EventWriter:
    """SQLite-backed event-log writer. Construct with a live connection;
    every method runs in the caller's transaction (no implicit BEGIN/COMMIT).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # -- helpers -----------------------------------------------------------

    def _outbox_jsonl_enabled(self) -> bool:
        cur = self.conn.execute("SELECT value FROM config WHERE key = 'outbox.jsonl_enabled'")
        row = cur.fetchone()
        return bool(row and row[0] == "true")

    def set_outbox_jsonl_enabled(self, *, now: datetime | None = None) -> None:
        ts = to_utc_iso8601((now or datetime.now(timezone.utc)).isoformat())
        self.conn.execute(
            "INSERT INTO config(key, value, updated_at) VALUES "
            "('outbox.jsonl_enabled', 'true', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (ts,),
        )

    def find_existing(
        self, *, event_type: str, actor_id: str, idempotency_key: str
    ) -> EventRecord | None:
        """Public idempotency lookup. Tools call this BEFORE doing the
        relational INSERT so the replay path can short-circuit without
        triggering a PK conflict on the ledger row."""

        return self._find_existing(
            event_type=event_type, actor_id=actor_id, idempotency_key=idempotency_key
        )

    def _find_existing(
        self, *, event_type: str, actor_id: str, idempotency_key: str
    ) -> EventRecord | None:
        cur = self.conn.execute(
            """
            SELECT id, event_type, subject_kind, subject_id, payload_json,
                   actor_id, idempotency_key, created_at, request_id,
                   agent_id, model_id, environment, run_id
            FROM events
            WHERE event_type = ? AND actor_id = ? AND idempotency_key = ?
            """,
            (event_type, actor_id, idempotency_key),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return EventRecord(
            id=row[0],
            event_type=row[1],
            subject_kind=row[2],
            subject_id=row[3],
            payload_json=row[4],
            actor_id=row[5],
            idempotency_key=row[6],
            created_at=row[7],
            request_id=row[8],
            agent_id=row[9],
            model_id=row[10],
            environment=row[11],
            run_id=row[12],
        )

    # -- public surface ----------------------------------------------------

    def write(
        self,
        *,
        event_type: str,
        subject_kind: str,
        subject_id: str,
        payload: dict[str, Any],
        actor_id: str,
        idempotency_key: str | None,
        request_id: str | None = None,
        agent_id: str | None = None,
        model_id: str | None = None,
        environment: str | None = None,
        run_id: str | None = None,
        now: datetime | None = None,
        allow_no_idempotency: bool = False,
    ) -> EventRecord:
        """Write an event row (or surface the original on a clean replay).

        Raises:
          KeyError: when `event_type` is not in the semantic_keys registry
            (default-deny — guards against silent contract drift).
          ValueError: when `idempotency_key` is missing on a retryable write
            and `allow_no_idempotency` is False.
          IdempotencyConflictError: when the key collides with a previous
            event whose payload is semantically different.
        """

        if event_type not in SEMANTIC_KEYS:
            raise KeyError(
                f"event_type {event_type!r} is not registered in "
                f"events_semantic_keys; refusing to write to guard against "
                f"silent contract drift (persistence.md §5.2)"
            )

        # Grammar validation (trade-trace-3mp). actor_id is always required;
        # idempotency_key is validated if present.
        validate_actor_id(actor_id)
        idempotency_key = validate_idempotency_key(idempotency_key)

        if idempotency_key is None and not allow_no_idempotency:
            raise ValueError(
                f"event_type {event_type!r} requires idempotency_key by default; "
                f"pass allow_no_idempotency=True to opt into at-least-once "
                f"semantics (persistence.md §5.3)"
            )

        # Replay check.
        if idempotency_key is not None:
            existing = self._find_existing(
                event_type=event_type,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            if existing is not None:
                old_payload = json.loads(existing.payload_json)
                equivalent, diff_summary = payloads_equivalent(
                    event_type, old_payload, payload
                )
                if not equivalent:
                    raise IdempotencyConflictError(
                        event_type=event_type,
                        actor_id=actor_id,
                        idempotency_key=idempotency_key,
                        original_event_id=existing.id,
                        diff_summary=diff_summary,
                    )
                existing.idempotent_replay = True
                return existing

        # Fresh write. Respect CLOCK_OVERRIDE so deterministic-replay
        # scopes (fixture seed, replay tests) produce identical
        # `created_at` values across runs.
        if now is None:
            from trade_trace.tools._helpers import CLOCK_OVERRIDE

            override = CLOCK_OVERRIDE.get()
            now = override if override is not None else datetime.now(timezone.utc)
        ts = to_utc_iso8601(now.isoformat())
        # Canonicalize payload for storage so semantic comparison on replay
        # works byte-equal on structural fields. We store the canonical form;
        # the original free-text values are still in there.
        canonical_for_storage = json.dumps(payload, sort_keys=True, default=str)
        # Sanity: the canonical form must be parseable by the registry.
        _ = canonicalize_payload(event_type, payload)

        cur = self.conn.execute(
            """
            INSERT INTO events(
                event_type, subject_kind, subject_id, payload_json,
                actor_id, idempotency_key, created_at, request_id,
                agent_id, model_id, environment, run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                subject_kind,
                subject_id,
                canonical_for_storage,
                actor_id,
                idempotency_key,
                ts,
                request_id,
                agent_id,
                model_id,
                environment,
                run_id,
            ),
        )
        event_id = cur.lastrowid

        # Outbox row (if JSONL export is enabled).
        if self._outbox_jsonl_enabled():
            self.conn.execute(
                "INSERT INTO outbox(event_id, export_kind, state) VALUES (?, 'jsonl', 'pending')",
                (event_id,),
            )

        return EventRecord(
            id=event_id,
            event_type=event_type,
            subject_kind=subject_kind,
            subject_id=subject_id,
            payload_json=canonical_for_storage,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            created_at=ts,
            request_id=request_id,
            agent_id=agent_id,
            model_id=model_id,
            environment=environment,
            run_id=run_id,
        )


def write_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    subject_kind: str,
    subject_id: str,
    payload: dict[str, Any],
    actor_id: str,
    idempotency_key: str | None = None,
    **kwargs: Any,
) -> EventRecord:
    """Convenience function that wraps EventWriter for one-off callers."""

    return EventWriter(conn).write(
        event_type=event_type,
        subject_kind=subject_kind,
        subject_id=subject_id,
        payload=payload,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        **kwargs,
    )
