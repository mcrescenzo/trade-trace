"""Journal admin tools per PRD §4 / docs/architecture/operability.md.

M0 ships:

- `journal.init` — idempotent SQLite bootstrap. Creates `$TRADE_TRACE_HOME`
  if missing, opens (or creates) `trade-trace.sqlite` with WAL, busy_timeout,
  and 0600 permissions where supported, then runs forward-only migrations.
  Makes zero outbound calls.
- `journal.status` — reports package/contract/schema versions, embeddings
  provider, and the outbound-network-active boolean. Reads from `meta`
  when a DB exists; falls back to defaults when called before init.
- `journal.schema` — emits per-tool JSON schemas via Pydantic
  `model_json_schema()`. Lets agents introspect the public surface without
  reading docs.

Tools accept an optional `home` arg pointing to a different `$TRADE_TRACE_HOME`
than the env-resolved default; this is the load-bearing knob for the tests
that exercise isolated DBs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.storage import (
    apply_pending_migrations,
    current_version,
    open_database,
    resolve_home,
)
from trade_trace.storage.database import has_fts5
from trade_trace.storage.paths import db_path
from trade_trace.tools.errors import ToolError
from trade_trace.version import CONTRACT_VERSION, __version__


def _polymarket_adapter_status(conn=None) -> tuple[dict[str, Any], bool]:
    from trade_trace.adapters.polymarket.config import adapter_state_from_config, load_config

    config = load_config(conn)
    return adapter_state_from_config(config), config.outbound_network_active


_TOOL_SCHEMA_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool": {
            "type": "string",
            "description": "Registered tool name to introspect; omit to enumerate the default v0.0.2 catalog.",
        },
        "include_admin": {
            "type": "boolean",
            "description": "Include admin-only tools in catalog mode.",
        },
        "include_legacy": {
            "type": "boolean",
            "description": "Include legacy/folded tools preserved for transitional dispatch.",
        },
        "include_experimental": {
            "type": "boolean",
            "description": "Include experimental/frozen tools hidden from the default catalog; they remain dispatchable.",
        },
    },
    "required": [],
}


def _journal_init(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`journal.init` — idempotent. Returns the new or existing schema_version,
    plus capability flags. Zero outbound calls."""

    home = resolve_home(args.get("home"))
    home.mkdir(parents=True, exist_ok=True)
    path = db_path(home)
    db = open_database(path)
    try:
        before = current_version(db.connection)
        from_v, to_v = apply_pending_migrations(db.connection)
        # Record bootstrap metadata; idempotent (replace on conflict).
        db.connection.execute(
            "INSERT INTO meta(key, value) VALUES ('package_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (__version__,),
        )
        db.connection.execute(
            "INSERT INTO meta(key, value) VALUES ('contract_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (CONTRACT_VERSION,),
        )
        fts5 = has_fts5(db.connection)
        # Per trade-trace-mehh: report the real sqlite-vec capability
        # instead of hard-coding False. `has_sqlite_vec` runs a
        # best-effort load + smoke-test of the vec0 virtual table; it
        # returns False on any failure. Vectors stay off-by-default
        # regardless of capability (the operator opts in via
        # `journal.config_set embeddings.provider …`).
        from trade_trace.storage.database import has_sqlite_vec

        vec = has_sqlite_vec(db.connection)
        adapter_state, outbound_network_active = _polymarket_adapter_status(db.connection)
    finally:
        db.close()

    return {
        "home": str(home),
        "db_path": str(path),
        "schema_version_before": before,
        "schema_version": to_v,
        "applied_migrations": list(range(from_v + 1, to_v + 1)),
        "fts5_available": fts5,
        "sqlite_vec_available": vec,
        "embeddings_provider": "none",
        "outbound_network_active": outbound_network_active,
        "adapter_state": adapter_state,
    }


def _journal_status(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`journal.status` — read package/contract/schema metadata. Works against
    an initialized DB; gracefully reports defaults for an uninitialized home."""

    home = resolve_home(args.get("home"))
    path = db_path(home)
    schema_version = 0
    if path.exists():
        db = open_database(path, create_parent=False)
        try:
            schema_version = current_version(db.connection)
            adapter_state, outbound_network_active = _polymarket_adapter_status(db.connection)
        finally:
            db.close()
    else:
        adapter_state, outbound_network_active = _polymarket_adapter_status()

    return {
        "home": str(home),
        "db_path": str(path),
        "db_exists": path.exists(),
        "package_version": __version__,
        "contract_version": CONTRACT_VERSION,
        "schema_version": schema_version,
        "embeddings_provider": "none",
        "outbound_network_active": outbound_network_active,
        "adapter_state": adapter_state,
    }


def _journal_schema(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`journal.schema` — emit per-model JSON schemas.

    Optional `tool` arg filters to a specific tool/model. Without it, the
    response is a dict of `{model_name: json_schema}` over the M0 model
    surface. Future write tools register their own schemas; this is the
    bootstrap version.
    """

    from trade_trace import models

    targets: dict[str, type[BaseModel]] = {
        "Decision": models.Decision,
        "Forecast": models.Forecast,
        "ForecastOutcome": models.ForecastOutcome,
        "MemoryNode": models.MemoryNode,
        "Outcome": models.Outcome,
        "Snapshot": models.Snapshot,
        "Source": models.Source,
        "Strategy": models.Strategy,
        "Thesis": models.Thesis,
    }
    wanted = args.get("tool")
    if wanted:
        if wanted not in targets:
            return {
                "schemas": {},
                "unknown_tool": wanted,
                "known_tools": sorted(targets),
            }
        targets = {wanted: targets[wanted]}

    return {
        "schemas": {name: cls.model_json_schema() for name, cls in targets.items()},
        "known_tools": sorted(targets),
    }


_VALID_PROJECTIONS = ("positions", "memory_node_stats", "all")


def _journal_rebuild_projections(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`journal.rebuild_projections` — drop and rebuild projection tables.

    Per persistence.md §7, the admin tool drops the chosen projection and
    rebuilds it from its append-only source tables, all inside one
    transaction. Used after a corruption-recovery restore, a schema
    upgrade, or a projection-logic bug.

    `projection` is required (default would be ambiguous). Accepted
    values: `positions`, `memory_node_stats`, `all`.
    """

    import time

    from trade_trace.projections import (
        rebuild_memory_node_stats,
        rebuild_positions,
    )

    projection = args.get("projection")
    if projection not in _VALID_PROJECTIONS:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"projection must be one of {_VALID_PROJECTIONS!r}",
            details={"field": "projection", "value": projection,
                     "allowed": list(_VALID_PROJECTIONS)},
        )

    home = resolve_home(args.get("home"))
    path = db_path(home)
    if not path.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            "journal not initialized; run `tt journal init` first",
            details={"home": str(home), "db_path": str(path)},
        )

    db = open_database(path, create_parent=False)
    results: list[dict[str, Any]] = []
    start = time.monotonic()
    try:
        with db.transaction():
            if projection in ("positions", "all"):
                res = rebuild_positions(db.connection)
                results.append({
                    "projection": res.projection,
                    "dropped_rows": res.dropped_rows,
                    "rebuilt_rows": res.rebuilt_rows,
                    "skipped_corrupt_rows": res.skipped_corrupt_rows,
                })
            if projection in ("memory_node_stats", "all"):
                res = rebuild_memory_node_stats(db.connection)
                results.append({
                    "projection": res.projection,
                    "dropped_rows": res.dropped_rows,
                    "rebuilt_rows": res.rebuilt_rows,
                    "skipped_corrupt_rows": res.skipped_corrupt_rows,
                })
    finally:
        db.close()
    duration_ms = int((time.monotonic() - start) * 1000)

    return {
        "projection": projection,
        "results": results,
        "duration_ms": duration_ms,
    }


def _tool_schema(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`tool.schema` — per-tool example payloads + actor/idempotency notes.

    Lets an autonomous agent discover the call surface for any registered
    MVP tool without re-reading contracts.md. The response shape is:

        {
          "tool": "thesis.add",
          "cli_invocation": "tt thesis add",
          "description": "...",
          "is_write": true,
          "example_minimal": { ... },
          "example_rich": { ... },
          "required_metadata": {
             "actor_id_pattern": "...",
             "idempotency_key_pattern": "...",
             "supports_dry_run": true,
          },
        }

    Pass `tool` to introspect one; omit it to enumerate every registered
    tool name (so the agent can build a catalog before drilling in).
    Per bead trade-trace-268.
    """

    from trade_trace.contracts.grammar import ACTOR_ID_PATTERN, IDEMPOTENCY_KEY_PATTERN
    from trade_trace.core import default_registry

    registry = default_registry()
    wanted = args.get("tool")
    include_admin = bool(args.get("include_admin"))
    include_legacy = bool(args.get("include_legacy"))
    include_experimental = bool(args.get("include_experimental"))
    if wanted is None:
        # Per bead trade-trace-dgdq: catalog mode mirrors MCP list-tools
        # by exposing each tool's `json_schema` so agents can discover
        # the full call shape in one round-trip. `json_schema=None`
        # for tools without an example/explicit schema (typically
        # read-only with no required args) keeps the shape homogeneous.
        return {
            "tools": [
                {
                    "name": reg.name,
                    "cli_invocation": "tt " + " ".join(reg.cli_invocation),
                    "is_write": reg.is_write,
                    "has_example": reg.example_minimal is not None,
                    "json_schema": reg.json_schema,
                    "metadata": reg.metadata(),
                }
                for reg in registry.public_registrations(
                    include_admin=include_admin,
                    include_legacy=include_legacy,
                    include_experimental=include_experimental,
                )
            ],
        }

    if wanted not in registry.by_name:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"unknown tool {wanted!r}",
            details={
                "entity_kind": "tool",
                "tool": wanted,
                "known_tools": registry.names(),
            },
        )
    reg = registry.by_name[wanted]
    return {
        "tool": reg.name,
        "cli_invocation": "tt " + " ".join(reg.cli_invocation),
        "description": reg.description,
        "is_write": reg.is_write,
        "example_minimal": reg.display_example_minimal(),
        "example_rich": reg.example_rich,
        "required_metadata": {
            "actor_id_pattern": ACTOR_ID_PATTERN,
            "idempotency_key_pattern": IDEMPOTENCY_KEY_PATTERN,
            "supports_dry_run": reg.is_write,
            "dry_run_flag_cli": "--dry-run",
            "dry_run_flag_mcp": "_dry_run",
            "allow_no_idempotency_cli": "--allow-no-idempotency",
            "allow_no_idempotency_mcp": "_allow_no_idempotency",
        },
        "json_schema": reg.json_schema,
        "metadata": reg.metadata(),
    }


def _journal_rescan_scoring(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`journal.rescan_scoring` — preview/confirm scorer upgrade rescan.

    The rescan is idempotent: it appends a score only when no score exists
    yet for the forecast/head outcome pair. It never mutates events,
    outcomes, forecast_outcomes, forecasts, or forecast_scores rows.
    """

    from trade_trace.events.unit_of_work import UnitOfWork
    from trade_trace.tools._helpers import now_iso
    from trade_trace.tools.ledger import (
        _current_resolved_final_outcome,
        _emit_forecast_scored,
        _score_one_forecast,
    )

    mode = args.get("mode") or ("confirm" if args.get("confirm") is True else "preview")
    if mode not in ("preview", "confirm"):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "mode must be 'preview' or 'confirm'", details={"field": "mode", "value": mode})

    home = resolve_home(args.get("home"))
    path = db_path(home)
    if not path.exists():
        raise ToolError(ErrorCode.STORAGE_ERROR, "journal not initialized; run `tt journal init` first", details={"home": str(home), "db_path": str(path)})

    db = open_database(path, create_parent=False)
    try:
        rows = db.connection.execute(
            """
            SELECT f.id, f.kind, f.scoring_support, f.yes_label, f.resolution_at,
                   f.created_at, t.instrument_id
            FROM forecasts f
            JOIN theses t ON t.id = f.thesis_id
            WHERE f.kind IN ('categorical','scalar')
              AND f.scoring_state = 'pending'
            ORDER BY f.created_at, f.id
            """
        ).fetchall()
        candidates: list[dict[str, Any]] = []
        for r in rows:
            head = _current_resolved_final_outcome(db.connection, instrument_id=r[6])
            already = False
            if head is not None:
                already = db.connection.execute(
                    "SELECT 1 FROM forecast_scores WHERE forecast_id = ? AND outcome_id = ?",
                    (r[0], head[0]),
                ).fetchone() is not None
            candidates.append({
                "forecast_id": r[0], "kind": r[1], "prior_scoring_support": r[2],
                "instrument_id": r[6], "head_outcome_id": head[0] if head else None,
                "will_score": bool(head is not None and not already),
                "already_scored_head": already,
            })
        if mode == "preview":
            return {"mode": mode, "affected_rows": len(candidates), "would_score_rows": sum(1 for c in candidates if c["will_score"]), "candidates": candidates}

        scored: list[dict[str, Any]] = []
        with UnitOfWork(db.connection) as uow:
            for r, c in zip(rows, candidates, strict=True):
                if not c["will_score"]:
                    continue
                outcome = uow.conn.execute(
                    "SELECT id, outcome_label FROM outcomes WHERE id = ?",
                    (c["head_outcome_id"],),
                ).fetchone()
                if outcome is None:
                    continue
                scored_at = now_iso()
                score = _score_one_forecast(
                    uow.conn,
                    forecast_row=(r[0], r[1], "supported", r[3], r[4], r[5]),
                    outcome_id=outcome[0], outcome_label=outcome[1],
                    actor_id=ctx.actor_id, scored_at=scored_at,
                )
                _emit_forecast_scored(uow, score, actor_id=ctx.actor_id, ctx=ctx, scored_at=scored_at)
                scored.append(score)
        return {"mode": mode, "affected_rows": len(candidates), "scored_rows": len(scored), "scores": scored, "candidates": candidates}
    finally:
        db.close()


def register_journal_tools(registry: ToolRegistry) -> None:
    """Register `journal.*` tools on the supplied registry."""

    registry.register(
        "journal.init",
        _journal_init,
        description=(
            "Initialize $TRADE_TRACE_HOME with a fresh SQLite DB. Idempotent: "
            "re-running on an existing journal succeeds and reports the current "
            "schema_version. Makes zero outbound network calls (PRD §2.4.1)."
        ),
    )
    registry.register(
        "journal.status",
        _journal_status,
        description=(
            "Return current package, contract, and schema version plus the "
            "active embeddings provider and the boolean state of any outbound "
            "network path. MVP default reports outbound_network_active=False "
            "because the only opt-in outbound path (PRD §2.4.1) is off by default."
        ),
    )
    registry.register(
        "journal.schema",
        _journal_schema,
        description=(
            "Emit Pydantic JSON schemas for ledger/memory models. Optional "
            "`tool` arg restricts output to one model name."
        ),
    )
    registry.register(
        "journal.rescan_scoring",
        _journal_rescan_scoring,
        description=(
            "[P1 contract; M1 stub] Re-score forecasts whose `scoring_support` "
            "was upgraded by a new scorer installation. Returns "
            "UNSUPPORTED_CAPABILITY in MVP with `affected_rows` set to the "
            "count of pending unsupported forecasts so the agent can size the "
            "future migration. See scoring.md §4.3 / §7."
        ),
    )
    registry.register(
        "tool.schema",
        _tool_schema,
        json_schema=_TOOL_SCHEMA_JSON_SCHEMA,
        description=(
            "Introspect a registered MVP tool: returns description, "
            "cli_invocation, example_minimal/example_rich payloads (for write "
            "tools), and required_metadata notes (actor_id pattern, "
            "idempotency_key pattern, dry-run support). Omit `tool` to "
            "enumerate the full tool catalog. Per bead trade-trace-268."
        ),
    )
    registry.register(
        "journal.rebuild_projections",
        _journal_rebuild_projections,
        description=(
            "Admin tool: drop and rebuild projection tables from their source "
            "append-only tables inside one atomic transaction. "
            "`projection` is required (one of `positions`, `memory_node_stats`, "
            "`all`). Used after corruption-restore or projection bug per "
            "persistence.md §7. memory_node_stats rebuild is a no-op until "
            "the M3 memory layer lands."
        ),
    )
