"""Read-only guided status for partial market journal arcs.

`journal.bundle.status` inspects already-local journal rows and returns an
audit-oriented checklist with concrete ids and suggested next tool calls. It is
intentionally conservative: no external market fetch, no trade execution, no
investment advice, and no new lifecycle table.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

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
        "decision": ("decisions", ["id", "instrument_id", "thesis_id", "forecast_id", "snapshot_id", "type", "reason", "review_by", "playbook_version_id", "created_at"]),
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
    checks.append(_entry("unresolved_forecasts", "weak" if unresolved else "ok", {"forecasts": unresolved}, "forecast.score or outcome.add when resolution is known"))

    reflected = _has_reflection(conn, [d["id"] for d in rows["decision"]])
    checks.append(_entry("reflection_attached", "ok" if reflected else "missing", {"decisions": [d["id"] for d in rows["decision"]]}, "memory.reflect / memory.link"))

    adherence_missing = [d["id"] for d in rows["decision"] if d.get("playbook_version_id") and not _has_playbook_rows(conn, d["id"])]
    checks.append(_entry("playbook_adherence_rows", "weak" if adherence_missing else "ok", {"decisions": adherence_missing}, "playbook.rule.record for playbook-scoped decisions"))
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


def register_journal_bundle_status(registry: ToolRegistry) -> None:
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
