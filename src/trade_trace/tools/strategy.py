"""First-class strategy tools per bead trade-trace-ubp.

Strategies are first-class rows (not tags). Each row carries a unique
slug, a name, optional description/hypothesis, and a status
(active | archived). Decisions and theses reference strategies via
`strategy_id`; the report-filter sentinel `__none__` selects rows whose
`strategy_id IS NULL` (reports.md §2.1).

Archived strategies remain valid FK targets — the soft-archive does
not cascade; historical decisions continue to read back without
referential-integrity violations.
"""

from __future__ import annotations

import json
import re
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.events.unit_of_work import UnitOfWork
from trade_trace.tools._helpers import (
    check_idempotency_replay,
    emit_event,
    new_id,
    now_iso,
    open_db_for_args,
    reject_if_contains_secrets,
    require,
)
from trade_trace.tools.errors import ToolError

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
"""lowercase-kebab: alphanumeric segments separated by single hyphens."""


_STATUS_VALUES = ("active", "archived")


def _normalize_slug(value: Any) -> str:
    if not isinstance(value, str) or not SLUG_PATTERN.match(value):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"slug must be lowercase-kebab (regex {SLUG_PATTERN.pattern!r}); "
            f"got {value!r}",
            details={"field": "slug", "value": value,
                     "expected_format": SLUG_PATTERN.pattern},
        )
    if len(value) > 64:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "slug must be <= 64 chars",
            details={"field": "slug", "value": value, "max_length": 64},
        )
    return value


def _strategy_create(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`strategy.create` — append a strategy row. `slug` is required and
    must be unique; duplicate slug raises VALIDATION_ERROR with
    `details.field='slug'`."""

    name = require(args, "name")
    slug = _normalize_slug(require(args, "slug"))
    description = args.get("description")
    hypothesis = args.get("hypothesis")
    # Scan long-form strategy free-text per bead trade-trace-7j1l.
    # name and slug are short identifiers and exempt; description and
    # hypothesis can hold pasted notes that might carry credentials.
    reject_if_contains_secrets(description, field="description")
    reject_if_contains_secrets(hypothesis, field="hypothesis")
    status = args.get("status", "active")
    if status not in _STATUS_VALUES:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"status must be one of {_STATUS_VALUES}; got {status!r}",
            details={"field": "status", "value": status,
                     "allowed": list(_STATUS_VALUES)},
        )
    meta_json = json.dumps(args.get("meta_json") or {}, sort_keys=True)
    idempotency_key = args.get("idempotency_key")

    db = open_db_for_args(args)
    try:
        # Slug uniqueness check happens before the INSERT so the error
        # surfaces with `details.field='slug'`, not as a UNIQUE
        # constraint translated to a generic VALIDATION_ERROR.
        existing = db.connection.execute(
            "SELECT id FROM strategies WHERE slug = ?", (slug,),
        ).fetchone()
        if existing is not None and idempotency_key is None:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"strategy slug {slug!r} is already taken",
                details={
                    "field": "slug", "value": slug,
                    "existing_strategy_id": existing[0],
                },
            )
        with UnitOfWork(db.connection) as uow:
            replay = check_idempotency_replay(
                uow, event_type="strategy.created",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                strategy_id = replay["id"]
                emit_event(
                    uow, event_type="strategy.created",
                    subject_kind="strategy", subject_id=strategy_id,
                    payload=replay, actor_id=ctx.actor_id,
                    idempotency_key=idempotency_key, ctx=ctx,
                )
                row = uow.conn.execute(
                    "SELECT name, slug, description, hypothesis, status, "
                    "created_at, updated_at FROM strategies WHERE id = ?",
                    (strategy_id,),
                ).fetchone()
                return _strategy_row_to_dict(strategy_id, row)

            # Re-check slug uniqueness inside the transaction (no idempotent
            # replay matched, but another concurrent write may have raced).
            collision = uow.execute(
                "SELECT id FROM strategies WHERE slug = ?", (slug,),
            ).fetchone()
            if collision is not None:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"strategy slug {slug!r} is already taken",
                    details={
                        "field": "slug", "value": slug,
                        "existing_strategy_id": collision[0],
                    },
                )

            strategy_id = args.get("id") or new_id("strat")
            created_at = now_iso()
            uow.execute(
                "INSERT INTO strategies(id, name, slug, description, "
                "hypothesis, status, meta_json, created_at, updated_at, "
                "actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (strategy_id, name, slug, description, hypothesis,
                 status, meta_json, created_at, created_at, ctx.actor_id),
            )
            emit_event(
                uow, event_type="strategy.created",
                subject_kind="strategy", subject_id=strategy_id,
                payload={
                    "id": strategy_id, "name": name, "slug": slug,
                    "description": description, "hypothesis": hypothesis,
                    "status": status,
                },
                actor_id=ctx.actor_id, idempotency_key=idempotency_key, ctx=ctx,
            )
    finally:
        db.close()
    return _strategy_response({
        "id": strategy_id, "name": name, "slug": slug,
        "description": description, "hypothesis": hypothesis,
        "status": status, "created_at": created_at, "updated_at": created_at,
    })


def _strategy_response(data: dict[str, Any]) -> dict[str, Any]:
    """Return the public strategy response shape.

    This intentionally omits internal-only columns such as ``meta_json`` and
    ``actor_id`` and preserves the stable response keys used by create, update,
    list, show, and idempotent replay paths.
    """

    return {
        "id": data["id"], "name": data["name"], "slug": data["slug"],
        "description": data.get("description"),
        "hypothesis": data.get("hypothesis"), "status": data["status"],
        "created_at": data["created_at"], "updated_at": data["updated_at"],
    }


def _strategy_row_to_dict(strategy_id: str, row: tuple) -> dict[str, Any]:
    return _strategy_response({
        "id": strategy_id, "name": row[0], "slug": row[1],
        "description": row[2], "hypothesis": row[3], "status": row[4],
        "created_at": row[5], "updated_at": row[6],
    })


def _strategy_full_row_to_dict(row: tuple) -> dict[str, Any]:
    return _strategy_row_to_dict(row[0], row[1:])


def _strategy_list(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`strategy.list` — paginated list. Optional `status` filter (active /
    archived / both). Default returns active only."""

    status_filter = args.get("status")
    limit = int(args.get("limit", 100))
    if limit < 1 or limit > 1000:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "limit must be in [1, 1000]",
            details={"field": "limit", "value": limit},
        )
    if status_filter is not None and status_filter not in (*_STATUS_VALUES, "both"):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"status must be one of {(*_STATUS_VALUES, 'both')}",
            details={"field": "status", "value": status_filter},
        )
    sql = (
        "SELECT id, name, slug, description, hypothesis, status, "
        "created_at, updated_at FROM strategies"
    )
    params: tuple = ()
    if status_filter is None or status_filter == "active":
        sql += " WHERE status = 'active'"
    elif status_filter == "archived":
        sql += " WHERE status = 'archived'"
    sql += " ORDER BY slug LIMIT ?"
    params = (limit,)
    db = open_db_for_args(args)
    try:
        rows = db.connection.execute(sql, params).fetchall()
    finally:
        db.close()
    items = [_strategy_full_row_to_dict(row) for row in rows]
    return {"items": items, "count": len(items), "truncated": len(items) == limit}


def _strategy_show(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`strategy.show` — fetch a strategy by id or slug.

    Accepts either `strategy_id` or `slug`; one is required.
    """

    strategy_id = args.get("strategy_id")
    slug = args.get("slug")
    if not strategy_id and not slug:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "strategy_id or slug is required",
            details={"field": "strategy_id_or_slug"},
        )
    db = open_db_for_args(args)
    try:
        if strategy_id:
            row = db.connection.execute(
                "SELECT id, name, slug, description, hypothesis, status, "
                "created_at, updated_at FROM strategies WHERE id = ?",
                (strategy_id,),
            ).fetchone()
        else:
            row = db.connection.execute(
                "SELECT id, name, slug, description, hypothesis, status, "
                "created_at, updated_at FROM strategies WHERE slug = ?",
                (slug,),
            ).fetchone()
    finally:
        db.close()
    if row is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            "strategy not found",
            details={
                "entity_kind": "strategy",
                "strategy_id": strategy_id, "slug": slug,
            },
        )
    return _strategy_full_row_to_dict(row)


def _strategy_update(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`strategy.update` — partial update. Immutable fields: `name`,
    `slug`. Updatable: `description`, `hypothesis`, `status` (active or
    archived), `meta_json`. `status='archived'` is the only archival
    surface — there is no separate `strategy.archive` tool.
    """

    strategy_id = require(args, "strategy_id")
    updates: list[tuple[str, Any]] = []
    if "description" in args:
        reject_if_contains_secrets(args["description"], field="description")
        updates.append(("description", args["description"]))
    if "hypothesis" in args:
        reject_if_contains_secrets(args["hypothesis"], field="hypothesis")
        updates.append(("hypothesis", args["hypothesis"]))
    if "status" in args:
        status = args["status"]
        if status not in _STATUS_VALUES:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"status must be one of {_STATUS_VALUES}",
                details={"field": "status", "value": status,
                         "allowed": list(_STATUS_VALUES)},
            )
        updates.append(("status", status))
    if "meta_json" in args:
        updates.append(("meta_json", json.dumps(args["meta_json"] or {},
                                                 sort_keys=True)))
    # Reject attempts to set immutable fields (name / slug). Detect
    # before opening the DB so we don't write anything.
    for forbidden in ("name", "slug"):
        if forbidden in args:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"{forbidden} is immutable on strategy.update; create a new "
                "strategy or use strategy.update status=archived to retire "
                "the old one",
                details={"field": forbidden, "policy": "immutable"},
            )
    if not updates:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "no mutable fields provided; pass description, hypothesis, "
            "status, or meta_json",
            details={"field": "update_set"},
        )

    idempotency_key = args.get("idempotency_key")
    db = open_db_for_args(args)
    try:
        with UnitOfWork(db.connection) as uow:
            row = uow.conn.execute(
                "SELECT name, slug, description, hypothesis, status, "
                "created_at, updated_at FROM strategies WHERE id = ?",
                (strategy_id,),
            ).fetchone()
            if row is None:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"strategy {strategy_id!r} not found",
                    details={"entity_kind": "strategy",
                             "strategy_id": strategy_id},
                )

            update_values = dict(updates)
            updated_at = now_iso()
            candidate_result: dict[str, Any] = {
                "id": strategy_id,
                "name": row[0],
                "slug": row[1],
                "description": update_values.get("description", row[2]),
                "hypothesis": update_values.get("hypothesis", row[3]),
                "status": update_values.get("status", row[4]),
                "created_at": row[5],
                "updated_at": updated_at,
            }
            payload = {
                **candidate_result,
                "strategy_id": strategy_id,  # alias matching semantic_keys
            }

            replay = check_idempotency_replay(
                uow, event_type="strategy.updated",
                actor_id=ctx.actor_id, idempotency_key=idempotency_key,
            )
            if replay is not None:
                emit_event(
                    uow, event_type="strategy.updated",
                    subject_kind="strategy", subject_id=strategy_id,
                    payload=payload, actor_id=ctx.actor_id,
                    idempotency_key=idempotency_key, ctx=ctx,
                )
                return _strategy_response(replay)

            emit_event(
                uow, event_type="strategy.updated",
                subject_kind="strategy", subject_id=strategy_id,
                payload=payload, actor_id=ctx.actor_id,
                idempotency_key=idempotency_key, ctx=ctx,
            )
            set_clause = ", ".join(f"{col} = ?" for col, _ in updates)
            params: list[Any] = [val for _, val in updates]
            params.append(updated_at)
            params.append(strategy_id)
            uow.execute(
                f"UPDATE strategies SET {set_clause}, updated_at = ? "
                "WHERE id = ?",
                tuple(params),
            )
    finally:
        db.close()
    return _strategy_response(candidate_result)


def register_strategy_tools(registry: ToolRegistry) -> None:
    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    registry.register(
        "strategy.create",
        _strategy_create,
        is_write=True,
        **_examples_for("strategy.create"),
        description=(
            "Create a first-class strategy row (not a tag). Required: "
            "name, slug (lowercase-kebab, unique). Optional: description, "
            "hypothesis, status (active|archived; default active). "
            "Duplicate slug raises VALIDATION_ERROR with details.field='slug'."
        ),
    )
    registry.register(
        "strategy.list",
        _strategy_list,
        description=(
            "List strategies. Default returns active rows. Pass "
            "status='archived' or 'both' to broaden. limit defaults to 100."
        ),
    )
    registry.register(
        "strategy.show",
        _strategy_show,
        description=(
            "Show one strategy by id or slug. NOT_FOUND when neither "
            "matches."
        ),
    )
    registry.register(
        "strategy.update",
        _strategy_update,
        is_write=True,
        **_examples_for("strategy.update"),
        description=(
            "Partial update on description, hypothesis, status, meta_json. "
            "name and slug are immutable. status='archived' is the archival "
            "surface; archived rows remain valid FK targets."
        ),
    )
