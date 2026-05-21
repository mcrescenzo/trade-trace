"""Read-only guided status for partial market journal arcs.

`journal.bundle.status` inspects already-local journal rows and returns an
audit-oriented checklist with concrete ids and suggested next tool calls. It is
intentionally conservative: no external market fetch, no trade execution, no
investment advice, and no new lifecycle table.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.storage import resolve_home
from trade_trace.storage.database import ReadOnlyDatabaseError, open_database_readonly
from trade_trace.storage.paths import db_path
from trade_trace.tools.errors import ToolError

CONTRACT_VERSION = "1.0"

_RECORD_ID_KEYS = {
    "venue": "venues",
    "instrument": "instruments",
    "snapshot": "snapshots",
    "source": "sources",
    "thesis": "theses",
    "forecast": "forecasts",
    "decision": "decisions",
}

_IDEA_SOURCE_METADATA_KEYS = {
    "idea_capture_source_id",
    "idea_source_id",
    "source_id",
    "raw_source_id",
}
_IDEA_MEMORY_METADATA_KEYS = {
    "idea_capture_memory_node_id",
    "idea_memory_node_id",
    "memory_node_id",
    "draft_memory_node_id",
}
_IDEA_PROVENANCE_CONTAINER_KEYS = {
    "idea_capture",
    "idea_capture_provenance",
    "provenance",
}


class JournalBundleStatusInput(BaseModel):
    """Input contract for journal.bundle.status."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str | None = None
    forecast_id: str | None = None
    thesis_id: str | None = None
    instrument_id: str | None = None
    source_id: str | None = None
    memory_node_id: str | None = None
    max_related: int = Field(default=10, ge=1, le=50)
    stale_source_days: int = Field(default=14, ge=1, le=3650)
    home: str | None = None


class JournalBundlePlanInput(BaseModel):
    """Input contract for journal.bundle.plan."""

    model_config = ConfigDict(extra="forbid")

    arc_type: Literal["watch", "skip"]
    idempotency_key_prefix: str | None = None
    venue_id: str | None = None
    instrument_id: str | None = None
    snapshot_id: str | None = None
    source_id: str | None = None
    thesis_id: str | None = None
    forecast_id: str | None = None
    decision_id: str | None = None
    memory_node_id: str | None = None
    venue_name: str | None = None
    instrument_title: str | None = None
    source_uri: str | None = None


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision_id": {"type": "string"},
        "forecast_id": {"type": "string"},
        "thesis_id": {"type": "string"},
        "instrument_id": {"type": "string"},
        "source_id": {"type": "string"},
        "memory_node_id": {"type": "string"},
        "max_related": {"type": "integer", "minimum": 1, "maximum": 50},
        "stale_source_days": {"type": "integer", "minimum": 1, "maximum": 3650},
        "home": {"type": "string"},
    },
    "description": (
        "Read-only status checklist for a partial market journal arc. Inspects "
        "local venues/instruments/snapshots/theses/forecasts/decisions/sources/"
        "memory links and returns relevant ids plus next suggested calls; no "
        "external market data, execution, or advice."
    ),
}

_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["arc_type"],
    "additionalProperties": False,
    "properties": {
        "arc_type": {"type": "string", "enum": ["watch", "skip"], "description": "Plan a watch or skip market journal arc."},
        "idempotency_key_prefix": {"type": "string", "description": "Optional prefix for placeholder idempotency keys."},
        "venue_id": {"type": "string"},
        "instrument_id": {"type": "string"},
        "snapshot_id": {"type": "string"},
        "source_id": {"type": "string"},
        "thesis_id": {"type": "string"},
        "forecast_id": {"type": "string"},
        "decision_id": {"type": "string"},
        "memory_node_id": {"type": "string"},
        "venue_name": {"type": "string"},
        "instrument_title": {"type": "string"},
        "source_uri": {"type": "string"},
    },
    "description": "Read-only plan for primitive local journal calls; no writes, external fetch, advice, or trades.",
}


def _journal_bundle_status(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    try:
        parsed = JournalBundleStatusInput.model_validate(args)
    except ValidationError as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"journal.bundle.status input validation failed: {exc.errors()}",
            details={"validation_errors": exc.errors()},
        ) from exc

    db = _open_db_readonly_for_args(args)
    try:
        conn = db.connection
        seeds = _seed_ids(parsed)
        related = _walk_related(conn, seeds, limit=parsed.max_related)
        rows = _load_rows(conn, related)
        checks = _build_checks(conn, rows, stale_source_days=parsed.stale_source_days)
        next_calls = _next_calls(checks, rows)
        provenance = _idea_capture_provenance(rows)
    finally:
        db.close()

    status = "complete_enough" if not any(c["status"] == "missing" for c in checks) else "needs_enrichment"
    if any(c["status"] == "weak" for c in checks) and status == "complete_enough":
        status = "has_weak_steps"

    return {
        "status": status,
        "contract_version": CONTRACT_VERSION,
        "input_ids": seeds,
        "relevant_ids": {k: sorted(v) for k, v in related.items()},
        "checklist": checks,
        "next_calls": next_calls,
        "idea_capture_provenance": provenance,
        "no_advice_boundary": {
            "external_fetch_performed": False,
            "trade_execution_performed": False,
            "advice_generated": False,
        },
    }


def _open_db_readonly_for_args(args: dict[str, Any]):
    """Resolve and open the journal DB without creating directories or files."""

    home = resolve_home(args.get("home"))
    path = db_path(home)
    try:
        return open_database_readonly(path)
    except ReadOnlyDatabaseError as exc:
        if exc.reason == "missing":
            raise ToolError(
                ErrorCode.STORAGE_ERROR,
                "journal not initialized; run `tt journal init` first",
                details={"home": str(home), "db_path": str(path)},
            ) from exc
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            str(exc),
            details={"home": str(home), "db_path": str(path), "reason": exc.reason},
        ) from exc


def _seed_ids(parsed: JournalBundleStatusInput) -> dict[str, str]:
    pairs = {
        "decision": parsed.decision_id,
        "forecast": parsed.forecast_id,
        "thesis": parsed.thesis_id,
        "instrument": parsed.instrument_id,
        "source": parsed.source_id,
        "memory_node": parsed.memory_node_id,
    }
    return {k: v for k, v in pairs.items() if v}


def _walk_related(conn: sqlite3.Connection, seeds: dict[str, str], *, limit: int) -> dict[str, set[str]]:
    kinds = ["venue", "instrument", "snapshot", "thesis", "forecast", "decision", "source", "memory_node"]
    ids: dict[str, set[str]] = {k: set() for k in kinds}
    for kind, value in seeds.items():
        ids.setdefault(kind, set()).add(value)

    # Expand direct row relationships until stable.
    for _ in range(3):
        changed = False
        for dec_id in list(ids["decision"]):
            row = conn.execute(
                "SELECT instrument_id, thesis_id, forecast_id, snapshot_id FROM decisions WHERE id = ?",
                (dec_id,),
            ).fetchone()
            if row:
                changed |= _add(ids, "instrument", row[0]) | _add(ids, "thesis", row[1]) | _add(ids, "forecast", row[2]) | _add(ids, "snapshot", row[3])
        for forecast_id in list(ids["forecast"]):
            row = conn.execute("SELECT thesis_id FROM forecasts WHERE id = ?", (forecast_id,)).fetchone()
            if row:
                changed |= _add(ids, "thesis", row[0])
        for thesis_id in list(ids["thesis"]):
            row = conn.execute("SELECT instrument_id FROM theses WHERE id = ?", (thesis_id,)).fetchone()
            if row:
                changed |= _add(ids, "instrument", row[0])
            for r in conn.execute("SELECT id FROM forecasts WHERE thesis_id = ? ORDER BY created_at, id LIMIT ?", (thesis_id, limit)):
                changed |= _add(ids, "forecast", r[0])
        for instr_id in list(ids["instrument"]):
            row = conn.execute("SELECT venue_id FROM instruments WHERE id = ?", (instr_id,)).fetchone()
            if row:
                changed |= _add(ids, "venue", row[0])
            for table, kind in (("snapshots", "snapshot"), ("theses", "thesis"), ("decisions", "decision")):
                for r in conn.execute(f"SELECT id FROM {table} WHERE instrument_id = ? ORDER BY created_at, id LIMIT ?", (instr_id, limit)):
                    changed |= _add(ids, kind, r[0])
        # Downstream promoted rows may carry idea.capture source/memory ids in
        # metadata instead of explicit source edges. Pull those ids forward so
        # provenance is visible even when status starts from a decision/forecast.
        for table, kind in (
            ("instruments", "instrument"),
            ("snapshots", "snapshot"),
            ("theses", "thesis"),
            ("forecasts", "forecast"),
            ("decisions", "decision"),
        ):
            seed_values = sorted(ids[kind])
            if not seed_values:
                continue
            marks = ",".join("?" for _ in seed_values)
            for (metadata_json,) in conn.execute(f"SELECT metadata_json FROM {table} WHERE id IN ({marks})", seed_values):
                refs = _idea_capture_refs_from_metadata(_json(metadata_json))
                for source_id in refs["source"]:
                    changed |= _add(ids, "source", source_id)
                for memory_node_id in refs["memory_node"]:
                    changed |= _add(ids, "memory_node", memory_node_id)
        # Promotion metadata from idea.capture often carries source/memory ids
        # before explicit edges are attached to promoted rows.
        for ref_id in sorted(ids["source"] | ids["memory_node"]):
            like = f"%{_escape_like(ref_id)}%"
            for table, kind in (("instruments", "instrument"), ("snapshots", "snapshot"), ("theses", "thesis"), ("forecasts", "forecast"), ("decisions", "decision")):
                for r in conn.execute(f"SELECT id FROM {table} WHERE metadata_json LIKE ? ESCAPE '\\' ORDER BY created_at, id LIMIT ?", (like, limit)):
                    changed |= _add(ids, kind, r[0])

        # Edges connect sources/memory and promoted rows in either direction.
        clauses = []
        params: list[Any] = []
        for kind, values in ids.items():
            if not values:
                continue
            marks = ",".join("?" for _ in values)
            clauses.append(f"(source_kind = ? AND source_id IN ({marks}))")
            params.extend([kind, *sorted(values)])
            clauses.append(f"(target_kind = ? AND target_id IN ({marks}))")
            params.extend([kind, *sorted(values)])
        if clauses:
            for s_kind, s_id, t_kind, t_id in conn.execute(
                "SELECT source_kind, source_id, target_kind, target_id FROM edges WHERE " + " OR ".join(clauses) + " LIMIT ?",
                [*params, limit * 20],
            ):
                changed |= _add(ids, s_kind, s_id) | _add(ids, t_kind, t_id)
        if not changed:
            break
    return ids


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _add(ids: dict[str, set[str]], kind: str, value: Any) -> bool:
    if not value or kind not in ids:
        return False
    before = len(ids[kind])
    ids[kind].add(str(value))
    return len(ids[kind]) != before


def _load_rows(conn: sqlite3.Connection, ids: dict[str, set[str]]) -> dict[str, list[dict[str, Any]]]:
    specs = {
        "venue": ("venues", ["id", "name", "kind", "metadata_json", "created_at"]),
        "instrument": ("instruments", ["id", "venue_id", "symbol", "title", "asset_class", "expiration_or_resolution_at", "resolution_criteria_text", "metadata_json", "created_at"]),
        "snapshot": ("snapshots", ["id", "instrument_id", "captured_at", "price", "bid", "ask", "mid", "implied_probability", "source", "source_url", "metadata_json", "created_at"]),
        "thesis": ("theses", ["id", "instrument_id", "side", "body", "confidence_label", "time_horizon_at", "strategy_id", "metadata_json", "created_at"]),
        "forecast": ("forecasts", ["id", "thesis_id", "kind", "yes_label", "resolution_at", "scoring_state", "scoring_support", "metadata_json", "created_at"]),
        "decision": ("decisions", ["id", "instrument_id", "thesis_id", "forecast_id", "snapshot_id", "type", "reason", "review_by", "playbook_version_id", "metadata_json", "created_at"]),
        "source": ("sources", ["id", "kind", "title", "ref", "uri", "freshness_at", "captured_at", "metadata_json", "created_at"]),
        "memory_node": ("memory_nodes", ["id", "node_type", "title", "meta_json", "created_at"]),
    }
    out: dict[str, list[dict[str, Any]]] = {}
    for kind, (table, cols) in specs.items():
        values = sorted(ids.get(kind) or [])
        if not values:
            out[kind] = []
            continue
        marks = ",".join("?" for _ in values)
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE id IN ({marks}) ORDER BY created_at, id", values).fetchall()
        out[kind] = [dict(zip(cols, r, strict=True)) for r in rows]
    return out


def _build_checks(conn: sqlite3.Connection, rows: dict[str, list[dict[str, Any]]], *, stale_source_days: int) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    _check(checks, "venue_recorded", rows["venue"], "venue.add")
    _check(checks, "instrument_recorded", rows["instrument"], "instrument.add")
    _check(checks, "snapshot_recorded", rows["snapshot"], "snapshot.add")
    _check(checks, "source_attached", rows["source"], "source.add / source.attach_to_*", weak_if=_stale_sources(conn, rows["source"], stale_source_days))
    _check(checks, "thesis_recorded", rows["thesis"], "thesis.add")
    _check(checks, "forecast_recorded", rows["forecast"], "forecast.add")
    _check(checks, "decision_recorded", rows["decision"], "decision.add")

    unresolved = [f["id"] for f in rows["forecast"] if f.get("scoring_state") == "pending"]
    checks.append(_entry("unresolved_forecasts", "weak" if unresolved else "ok", {"forecasts": unresolved}, "outcome.add when resolution is known"))

    reflected = _has_reflection(conn, [d["id"] for d in rows["decision"]])
    checks.append(_entry("reflection_attached", "ok" if reflected else "missing", {"decisions": [d["id"] for d in rows["decision"]]}, "memory.reflect / memory.link"))

    adherence_missing = [d["id"] for d in rows["decision"] if d.get("playbook_version_id") and not _has_playbook_rows(conn, d["id"])]
    checks.append(_entry("playbook_adherence_rows", "weak" if adherence_missing else "ok", {"decisions": adherence_missing}, "decision.record_adherence for playbook-scoped decisions"))
    return checks


def _check(checks: list[dict[str, Any]], name: str, rows: list[dict[str, Any]], call: str, *, weak_if: list[str] | None = None) -> None:
    status = "ok" if rows else "missing"
    kind = name.split("_")[0]
    record_ids = {_RECORD_ID_KEYS.get(kind, f"{kind}s"): [r["id"] for r in rows]}
    if rows and weak_if:
        status = "weak"
        record_ids["weak_source_ids"] = weak_if
    checks.append(_entry(name, status, record_ids, call))


def _entry(name: str, status: str, record_ids: dict[str, list[str]], call: str) -> dict[str, Any]:
    return {"step": name, "status": status, "record_ids": record_ids, "next_call": call}


def _stale_sources(conn: sqlite3.Connection, sources: list[dict[str, Any]], days: int) -> list[str]:
    rows = conn.execute("SELECT datetime('now', ?)", (f"-{days} days",)).fetchone()
    cutoff = rows[0] if rows else None
    stale: list[str] = []
    for src in sources:
        stamp = src.get("freshness_at") or src.get("captured_at") or src.get("created_at")
        if cutoff and stamp and stamp < cutoff:
            stale.append(src["id"])
    return stale


def _has_reflection(conn: sqlite3.Connection, decision_ids: list[str]) -> bool:
    if not decision_ids:
        return False
    marks = ",".join("?" for _ in decision_ids)
    return conn.execute(
        "SELECT 1 FROM edges e JOIN memory_nodes m ON m.id = e.source_id "
        "WHERE e.source_kind = 'memory_node' AND e.target_kind = 'decision' "
        f"AND e.target_id IN ({marks}) AND e.edge_type = 'about' AND m.node_type = 'reflection' LIMIT 1",
        decision_ids,
    ).fetchone() is not None


def _has_playbook_rows(conn: sqlite3.Connection, decision_id: str) -> bool:
    return conn.execute("SELECT 1 FROM decision_playbook_rules WHERE decision_id = ? LIMIT 1", (decision_id,)).fetchone() is not None


def _next_calls(checks: list[dict[str, Any]], rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    context = {
        "source_ids": [r["id"] for r in rows["source"]],
        "memory_node_ids": [r["id"] for r in rows["memory_node"]],
        "instrument_ids": [r["id"] for r in rows["instrument"]],
        "thesis_ids": [r["id"] for r in rows["thesis"]],
        "forecast_ids": [r["id"] for r in rows["forecast"]],
        "decision_ids": [r["id"] for r in rows["decision"]],
    }
    for check in checks:
        if check["status"] in {"missing", "weak"}:
            calls.append({
                "for_step": check["step"],
                "tool": check["next_call"],
                "carry_forward_ids": {k: v for k, v in context.items() if v},
            })
    return calls


def _idea_capture_provenance(rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    found: list[dict[str, str]] = []
    for kind in ("source", "memory_node"):
        meta_field = "meta_json" if kind == "memory_node" else "metadata_json"
        for row in rows[kind]:
            meta = _json(row.get(meta_field))
            if meta.get("trade_trace_flow") == "idea.capture":
                found.append({"kind": kind, "id": row["id"], "draft_state": str(meta.get("draft_state") or "")})
    return {"present": bool(found), "records": found}


def _idea_capture_refs_from_metadata(meta: dict[str, Any]) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {"source": set(), "memory_node": set()}

    def visit(value: Any, *, in_provenance: bool = False) -> None:
        if not isinstance(value, dict):
            return
        for key, raw in value.items():
            nested = in_provenance or key in _IDEA_PROVENANCE_CONTAINER_KEYS
            if key in _IDEA_SOURCE_METADATA_KEYS:
                _add_ref_values(refs["source"], raw)
            elif key in _IDEA_MEMORY_METADATA_KEYS:
                _add_ref_values(refs["memory_node"], raw)
            if nested and isinstance(raw, dict):
                visit(raw, in_provenance=True)

    visit(meta)
    return refs


def _add_ref_values(target: set[str], raw: Any) -> None:
    if isinstance(raw, str) and raw:
        target.add(raw)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item:
                target.add(item)


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _journal_bundle_plan(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    del ctx
    try:
        parsed = JournalBundlePlanInput.model_validate(args)
    except ValidationError as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"journal.bundle.plan input validation failed: {exc.errors()}",
            details={"validation_errors": exc.errors()},
        ) from exc

    ids = {k: v for k, v in parsed.model_dump().items() if k.endswith("_id") and v}
    prefix = parsed.idempotency_key_prefix or "<idempotency_key_prefix>"

    def ph(kind: str) -> str:
        if kind == "memory_node":
            return ids.get("memory_node_id", "<memory_node_id from prior memory.reflect or memory.retain output>")
        return ids.get(f"{kind}_id", f"<{kind}_id from prior {kind}.add output>")

    def step(tool: str, purpose: str, args_template: dict[str, Any], *, creates: str | None = None, uses: list[str] | None = None, skip_when: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "tool": tool,
            "purpose": purpose,
            "schema_call": {"tool": "tool.schema", "args": {"tool": tool}},
            "args_template": args_template,
        }
        if creates:
            out["creates"] = creates
        if uses:
            out["uses"] = uses
        if skip_when:
            out["skip_when"] = skip_when
        return out

    decision_args: dict[str, Any] = {
        "type": parsed.arc_type,
        "instrument_id": ph("instrument"),
        "reason": "<required reason for skip; optional rationale for watch>",
        "idempotency_key": f"{prefix}-decision-add",
    }
    if parsed.arc_type == "watch":
        decision_args["review_by"] = "<optional_review_by_iso8601_for_watchlist>"
    for key in ("thesis", "snapshot", "forecast"):
        decision_args[f"{key}_id"] = ph(key)

    ordered_calls = [
        step(
            "venue.add",
            "Create venue if one was not supplied.",
            {"name": parsed.venue_name or "<venue_name>", "kind": "prediction_market", "idempotency_key": f"{prefix}-venue-add"},
            creates="venue_id",
            skip_when="venue_id supplied",
        ),
        step(
            "instrument.add",
            "Create or identify the market instrument.",
            {"venue_id": ph("venue"), "title": parsed.instrument_title or "<instrument_title>", "asset_class": "prediction_market", "idempotency_key": f"{prefix}-instrument-add"},
            creates="instrument_id",
            uses=["venue_id"],
            skip_when="instrument_id supplied",
        ),
        step(
            "snapshot.add",
            "Record an agent-supplied local market snapshot.",
            {
                "instrument_id": ph("instrument"),
                "captured_at": "2026-01-01T00:00:00Z",
                "price": 0.0,
                "source": "manual_or_public_market_readback",
                "metadata_json": {"note": "manual/local snapshot; no external fetch by journal.bundle.plan"},
                "idempotency_key": f"{prefix}-snapshot-add",
            },
            creates="snapshot_id",
            uses=["instrument_id"],
            skip_when="snapshot_id supplied",
        ),
        step(
            "source.add",
            "Record local source/provenance used by the arc.",
            {"kind": "url", "stance": "neutral", "uri": parsed.source_uri or "<source_uri_or_local_note>", "title": "<source_title>", "idempotency_key": f"{prefix}-source-add"},
            creates="source_id",
            skip_when="source_id supplied",
        ),
        step(
            "thesis.add",
            "Capture the thesis being watched or rejected.",
            {"instrument_id": ph("instrument"), "side": "yes", "body": "<thesis_body>", "idempotency_key": f"{prefix}-thesis-add"},
            creates="thesis_id",
            uses=["instrument_id"],
            skip_when="thesis_id supplied",
        ),
        step(
            "source.attach_to_thesis",
            "Attach source to thesis using generic target_id.",
            {"source_id": ph("source"), "target_id": ph("thesis"), "idempotency_key": f"{prefix}-source-thesis"},
            uses=["source_id", "thesis_id"],
        ),
        step(
            "forecast.add",
            "Add an explicit forecast if the arc has a testable expectation.",
            {
                "thesis_id": ph("thesis"),
                "kind": "binary",
                "yes_label": "yes",
                "outcomes": [{"outcome_label": "yes", "probability": 0.5}, {"outcome_label": "no", "probability": 0.5}],
                "idempotency_key": f"{prefix}-forecast-add",
            },
            creates="forecast_id",
            uses=["thesis_id"],
            skip_when="forecast_id supplied",
        ),
        step(
            "source.attach_to_forecast",
            "Attach source to forecast using generic target_id.",
            {"source_id": ph("source"), "target_id": ph("forecast"), "idempotency_key": f"{prefix}-source-forecast"},
            uses=["source_id", "forecast_id"],
        ),
        step(
            "decision.add",
            (
                f"Record the {parsed.arc_type} decision; do not include quantity, price, fees, or slippage."
                if parsed.arc_type == "watch"
                else "Record the skip decision; do not include quantity, price, fees, slippage, or review_by."
            ),
            decision_args,
            creates="decision_id",
            uses=["instrument_id", "thesis_id", "snapshot_id", "forecast_id"],
            skip_when="decision_id supplied",
        ),
        step(
            "source.attach_to_decision",
            "Attach source to decision using generic target_id.",
            {"source_id": ph("source"), "target_id": ph("decision"), "idempotency_key": f"{prefix}-source-decision"},
            uses=["source_id", "decision_id"],
        ),
        step(
            "memory.reflect",
            "Reflect/retain the outcome-neutral learning note; if a memory_node_id already exists, carry it into journal.bundle.status.",
            {"target_kind": "decision", "target_id": ph("decision"), "body": "<reflection_body>", "idempotency_key": f"{prefix}-memory-reflect"},
            creates="memory_node_id",
            uses=["decision_id"],
            skip_when="memory_node_id supplied and no new reflection is needed",
        ),
        step(
            "journal.bundle.status",
            "Final read-only completeness check.",
            {"decision_id": ph("decision"), "forecast_id": ph("forecast"), "thesis_id": ph("thesis"), "instrument_id": ph("instrument"), "source_id": ph("source"), "memory_node_id": ph("memory_node")},
            uses=["decision_id", "forecast_id", "thesis_id", "instrument_id", "source_id", "memory_node_id"],
        ),
    ]

    return {
        "arc_type": parsed.arc_type,
        "plan_state": "plan_only",
        "no_advice_boundary": {"external_fetch_performed": False, "trade_execution_performed": False, "advice_generated": False},
        "ordered_calls": ordered_calls,
        "carry_forward_ids": {
            "venue_id": parsed.venue_id or "venue.add.data.id -> instrument.add.venue_id",
            "instrument_id": parsed.instrument_id or "instrument.add.data.id -> snapshot/thesis/decision.instrument_id",
            "snapshot_id": parsed.snapshot_id or "snapshot.add.data.id -> decision.add.snapshot_id",
            "source_id": parsed.source_id or "source.add.data.id -> source.attach_to_* source_id",
            "thesis_id": parsed.thesis_id or "thesis.add.data.id -> forecast.add.thesis_id and attach target_id",
            "forecast_id": parsed.forecast_id or "forecast.add.data.id -> decision.add.forecast_id and attach target_id",
            "decision_id": parsed.decision_id or "decision.add.data.id -> source.attach_to_decision target_id and final status",
            "memory_node_id": parsed.memory_node_id or "memory.reflect/retain output id -> final status memory_node_id",
        },
        "final_check": {"tool": "journal.bundle.status", "args": {"decision_id": ph("decision")}},
        "next_actions": [
            "Execute primitive calls in ordered_calls; journal.bundle.plan does not perform writes.",
            "On validation failure, inspect the step schema_call/tool.schema and adjust only that primitive call.",
            "Run journal.bundle.status after the primitives to verify the arc.",
        ],
    }


def register_journal_bundle_status(registry: ToolRegistry) -> None:
    registry.register(
        "journal.bundle.plan",
        _journal_bundle_plan,
        json_schema=_PLAN_SCHEMA,
        description="Read-only plan-only helper for watch/skip market journal arcs; no external fetch, advice, trades, or writes.",
        usage_summary="Plan primitive journal calls for a watch or skip arc without guessing schemas.",
        examples=("tt journal bundle plan --arc-type watch", "tt journal bundle plan --arc-type skip --instrument-id ins_..."),
        enum_notes={"arc_type": "watch records a watch decision; skip records a skip decision with a reason."},
        common_failures=("This helper is plan-only; execute the returned primitive tools yourself.",),
        next_actions=("Execute ordered_calls in order, using each schema_call if validation fails, then run journal.bundle.status.",),
    )
    registry.register(
        "journal.bundle.status",
        _journal_bundle_status,
        json_schema=_SCHEMA,
        description=(
            "Read-only guided checklist for partial market journal arcs. Returns "
            "missing or weak steps, relevant local ids, and suggested next tool "
            "calls without external market data, execution, or advice."
        ),
        usage_summary="Inspect a partial journal arc and return concrete completion guidance.",
        examples=("tt journal bundle status --decision-id dec_...",),
        common_failures=("journal must be initialized first with journal.init.",),
        next_actions=("Use returned next_calls to add or attach missing local journal rows.",),
    )
