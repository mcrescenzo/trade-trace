"""`review.bundle` per PRD §4.2 + reports.md §5 (bead trade-trace-yai).

Bounded, deterministic external-review package. Selects decisions
matching the supported ReportFilter subset, walks out to attached
sources / reflections / playbook versions, applies the redaction rules
from reports.md §5.3 + security.md §8, and returns a canonical-JSON
bundle whose `bundle_hash` (sha-256 of the canonical bytes of `data`
minus the hash itself) is stable across runs for an identical DB state
plus identical input.

The output explicitly omits LLM-generated commentary and trade
recommendations per reports.md §5.4 — the system emits data, not
opinion.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.report_filter import STRATEGY_NONE_SENTINEL, ReportFilter
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.reports._filter_support import (
    UnsupportedFilterError,
    applied_filter_view,
    enforce_supported_filter,
)
from trade_trace.reports.calibration import report_calibration
from trade_trace.reports.recall_receipts import (
    ATTRIBUTION_CONVENTIONS,
    report_recall_receipts,
)
from trade_trace.security.patterns import redact_for_log
from trade_trace.tools._helpers import open_db_for_args
from trade_trace.tools._report_filter_errors import (
    report_filter_validation_to_tool_error,
    unsupported_filter_to_tool_error,
)
from trade_trace.tools.errors import ToolError

REVIEW_BUNDLE_REPORT = "review.bundle"
CONTRACT_VERSION = "1.0"
RECALL_RECEIPTS_MAX_BLOCKS = 50

_SOURCE_REDACTED_DROPPED_FIELDS = ("body", "extracted_text", "excerpt",
                                   "summary", "note")
"""Per reports.md §5.3: content-bearing columns dropped when a source
is `redaction_status='redacted'`. `body` is listed for forward
compatibility with the documented field; the M1 sources schema does
not currently have a `body` column but the doc references it for the
contract."""


class ReviewBundleInput(BaseModel):
    """Input contract for review.bundle (reports.md §5.1)."""

    model_config = ConfigDict(extra="forbid")

    filter: dict[str, Any] = Field(default_factory=dict,
                                   description="ReportFilter (reports.md §2)")
    max_records: int = Field(default=25, ge=1, le=200)
    include_sources: bool = True
    include_reflections: bool = True
    include_playbook: bool = True
    include_recall_receipts: bool = True
    max_examples_per_record: int = Field(default=3, ge=0, le=20)
    home: str | None = None  # forwarded to open_db_for_args


class ReviewBundleOutput(BaseModel):
    """Output contract for review.bundle (reports.md §5.2)."""

    model_config = ConfigDict(extra="forbid")

    filter: dict[str, Any]
    selected: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    reflections: list[dict[str, Any]] = Field(default_factory=list)
    playbook_versions: list[dict[str, Any]] = Field(default_factory=list)
    report_summaries: dict[str, Any] = Field(default_factory=dict)
    recall_receipts: dict[str, Any] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)
    suggested_prompts: list[str] = Field(default_factory=list)
    bundle_hash: str
    contract_version: str = CONTRACT_VERSION


# -- selection ----------------------------------------------------------


def _select_decision_ids(
    conn: sqlite3.Connection, rf: ReportFilter, *, max_records: int,
) -> list[str]:
    """Return up to `max_records` decision ids matching `rf`, ordered by
    `(created_at ASC, id ASC)` so the same DB + same filter yields the
    same bundle."""

    where: list[str] = []
    params: list[Any] = []
    if rf.time_window.decision_at_gte is not None:
        where.append("d.created_at >= ?")
        params.append(rf.time_window.decision_at_gte)
    if rf.time_window.decision_at_lt is not None:
        where.append("d.created_at < ?")
        params.append(rf.time_window.decision_at_lt)
    if rf.actors.actor_id:
        where.append(f"d.actor_id IN ({_placeholders(len(rf.actors.actor_id))})")
        params.extend(rf.actors.actor_id)
    if rf.instrument.venue_id:
        where.append(
            f"i.venue_id IN ({_placeholders(len(rf.instrument.venue_id))})"
        )
        params.extend(rf.instrument.venue_id)
    if rf.strategy.strategy_id is not None:
        if rf.strategy.strategy_id == STRATEGY_NONE_SENTINEL:
            where.append("d.strategy_id IS NULL")
        else:
            where.append("d.strategy_id = ?")
            params.append(rf.strategy.strategy_id)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = (
        f"SELECT d.id FROM decisions d "
        f"JOIN instruments i ON i.id = d.instrument_id "
        f"{where_sql} "
        f"ORDER BY d.created_at ASC, d.id ASC LIMIT ?"
    )
    return [row[0] for row in conn.execute(sql, [*params, max_records])]


def _placeholders(n: int) -> str:
    return ", ".join("?" for _ in range(n))


# -- row fetchers --------------------------------------------------------
#
# Each helper returns a list of plain dicts with deterministic key
# ordering and stable row ordering so the canonical JSON above hashes
# stably across runs.


def _decision_rows(
    conn: sqlite3.Connection, decision_ids: list[str],
) -> list[dict[str, Any]]:
    if not decision_ids:
        return []
    placeholders = _placeholders(len(decision_ids))
    sql = (
        "SELECT id, instrument_id, thesis_id, forecast_id, snapshot_id, "
        "type, side, quantity, price, fees, slippage, reason, "
        "playbook_version_id, review_by, strategy_id, agent_id, model_id, "
        "environment, run_id, metadata_json, created_at, actor_id "
        f"FROM decisions WHERE id IN ({placeholders}) "
        "ORDER BY created_at ASC, id ASC"
    )
    cols = [
        "id", "instrument_id", "thesis_id", "forecast_id", "snapshot_id",
        "type", "side", "quantity", "price", "fees", "slippage", "reason",
        "playbook_version_id", "review_by", "strategy_id", "agent_id",
        "model_id", "environment", "run_id", "metadata_json", "created_at",
        "actor_id",
    ]
    rows = conn.execute(sql, decision_ids).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def _fetch_by_ids(
    conn: sqlite3.Connection, table: str, ids: list[str], cols: list[str],
) -> list[dict[str, Any]]:
    if not ids:
        return []
    placeholders = _placeholders(len(ids))
    select = ", ".join(cols)
    rows = conn.execute(
        f"SELECT {select} FROM {table} WHERE id IN ({placeholders}) "
        f"ORDER BY {cols[0]}",
        ids,
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


_THESIS_COLS = ["id", "instrument_id", "side", "body", "confidence_label",
                "strategy_id", "risk_unit_label", "max_loss_budget",
                "invalidation_condition", "valid_from", "valid_to",
                "created_at", "actor_id"]
_FORECAST_COLS = ["id", "thesis_id", "kind", "yes_label", "scoring_state",
                  "scoring_support", "resolution_at", "metadata_json",
                  "created_at", "actor_id"]
_OUTCOME_COLS = ["id", "instrument_id", "resolved_at", "outcome_label",
                 "outcome_value", "status", "metadata_json", "created_at",
                 "actor_id"]
_POSITION_COLS = ["id", "instrument_id", "kind", "side", "status",
                  "opened_at", "closed_at", "resolved_at", "realized_pnl",
                  "unrealized_pnl", "avg_entry_price", "updated_at"]


def _related_record_rows(
    conn: sqlite3.Connection, decisions: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Walk from decisions to theses / forecasts / outcomes / positions.

    Outcomes and positions are joined via instrument_id so the reviewer
    sees the full context behind each selected decision.
    """

    instrument_ids = sorted({d["instrument_id"] for d in decisions
                             if d["instrument_id"]})
    thesis_ids = sorted({d["thesis_id"] for d in decisions if d["thesis_id"]})
    forecast_ids = sorted({d["forecast_id"] for d in decisions
                           if d["forecast_id"]})

    theses = _fetch_by_ids(conn, "theses", thesis_ids, _THESIS_COLS)
    forecasts = _fetch_by_ids(conn, "forecasts", forecast_ids, _FORECAST_COLS)

    outcomes: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    if instrument_ids:
        placeholders = _placeholders(len(instrument_ids))
        outcome_rows = conn.execute(
            f"SELECT {', '.join(_OUTCOME_COLS)} FROM outcomes "
            f"WHERE instrument_id IN ({placeholders}) "
            "ORDER BY resolved_at ASC, id ASC",
            instrument_ids,
        ).fetchall()
        outcomes = [
            dict(zip(_OUTCOME_COLS, row, strict=True)) for row in outcome_rows
        ]
        position_rows = conn.execute(
            f"SELECT {', '.join(_POSITION_COLS)} FROM positions "
            f"WHERE instrument_id IN ({placeholders}) "
            "ORDER BY id ASC",
            instrument_ids,
        ).fetchall()
        positions = [
            dict(zip(_POSITION_COLS, row, strict=True))
            for row in position_rows
        ]

    return {
        "decisions": decisions,
        "theses": theses,
        "forecasts": forecasts,
        "outcomes": outcomes,
        "positions": positions,
    }


# -- sources, reflections, playbooks ------------------------------------


_SOURCE_COLS = [
    "id", "kind", "ref", "title", "note", "stance", "freshness_at",
    "content_hash", "captured_at", "uri", "media_type", "storage_kind",
    "retrieved_at", "source_author", "publisher", "excerpt",
    "extracted_text", "summary", "hash_algorithm", "redaction_status",
    "license_or_terms_note", "metadata_json", "created_at", "actor_id",
]


def _gather_attached_sources(
    conn: sqlite3.Connection, *, target_kinds: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Return the deduped list of sources attached to any of the given
    `target_kind→target_ids` groups via `edges` with source_kind='source'.

    Applies the §5.3 redaction rules:
    - `sensitive` rows are omitted entirely; the omitted count is
      returned for the caller's caveat list.
    - `redacted` rows are included but their content-bearing columns
      (`body`/`extracted_text`/`excerpt`/`summary`/`note`) are nulled
      out; the redacted count is returned alongside.
    - `none` rows pass through untouched.
    """

    edge_filters: list[str] = []
    params: list[Any] = []
    for kind, ids in target_kinds.items():
        if not ids:
            continue
        edge_filters.append(
            f"(e.target_kind = ? AND e.target_id IN ({_placeholders(len(ids))}))"
        )
        params.append(kind)
        params.extend(ids)
    if not edge_filters:
        return [], 0, 0

    sql = (
        "SELECT DISTINCT e.source_id FROM edges e "
        "WHERE e.source_kind = 'source' AND ("
        + " OR ".join(edge_filters)
        + ")"
    )
    source_ids = sorted({row[0] for row in conn.execute(sql, params)})
    if not source_ids:
        return [], 0, 0

    sources = _fetch_by_ids(conn, "sources", source_ids, _SOURCE_COLS)

    included: list[dict[str, Any]] = []
    omitted_sensitive = 0
    redacted_count = 0
    for src in sources:
        status = src.get("redaction_status") or "none"
        if status == "sensitive":
            omitted_sensitive += 1
            continue
        if status == "redacted":
            for field in _SOURCE_REDACTED_DROPPED_FIELDS:
                if field in src:
                    src[field] = None
            redacted_count += 1
        included.append(src)
    return included, omitted_sensitive, redacted_count


_REFLECTION_COLS = ["id", "node_type", "body", "title", "importance",
                    "confidence_base", "valid_from", "valid_to",
                    "metadata_json", "created_at", "actor_id"]


def _gather_reflections(
    conn: sqlite3.Connection, *, target_kinds: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Return memory_node rows of type='reflection' attached via an
    `about` edge to any selected target."""

    edge_filters: list[str] = []
    params: list[Any] = []
    for kind, ids in target_kinds.items():
        if not ids:
            continue
        edge_filters.append(
            f"(e.target_kind = ? AND e.target_id IN ({_placeholders(len(ids))}))"
        )
        params.append(kind)
        params.extend(ids)
    if not edge_filters:
        return []

    sql = (
        "SELECT m.id, m.node_type, m.body, m.title, m.importance, "
        "m.confidence_base, m.valid_from, m.valid_to, m.meta_json, "
        "m.created_at, m.actor_id "
        "FROM memory_nodes m JOIN edges e ON e.source_id = m.id "
        "WHERE e.source_kind = 'memory_node' AND m.node_type = 'reflection' "
        "AND e.edge_type = 'about' AND ("
        + " OR ".join(edge_filters)
        + ") ORDER BY m.created_at ASC, m.id ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        node_id = row[0]
        if node_id in deduped:
            continue
        deduped[node_id] = dict(zip(
            ["id", "node_type", "body", "title", "importance",
             "confidence_base", "valid_from", "valid_to", "metadata_json",
             "created_at", "actor_id"],
            row, strict=True,
        ))
    return list(deduped.values())


def _gather_playbook_versions(
    conn: sqlite3.Connection, decision_ids: list[str],
) -> list[dict[str, Any]]:
    if not decision_ids:
        return []
    placeholders = _placeholders(len(decision_ids))
    cols = ["id", "playbook_id", "version", "parent_version_id",
            "provenance_reflection_node_id", "description",
            "metadata_json", "created_at", "actor_id"]
    sql = (
        "SELECT DISTINCT pv.id, pv.playbook_id, pv.version, "
        "pv.parent_version_id, pv.provenance_reflection_node_id, "
        "pv.description, pv.metadata_json, pv.created_at, pv.actor_id "
        "FROM playbook_versions pv "
        "JOIN decision_playbook_rules dpr "
        "  ON dpr.playbook_version_id = pv.id "
        f"WHERE dpr.decision_id IN ({placeholders}) "
        "ORDER BY pv.created_at ASC, pv.id ASC"
    )
    rows = conn.execute(sql, decision_ids).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


# -- redaction sweep ---------------------------------------------------


def _redact_strings_in_place(value: Any, *, counter: dict[str, int]) -> Any:
    """Recursively walk `value`, replacing any secret-shaped substring in
    a string with `REDACTED-<pattern_kind>` via `redact_for_log`. The
    counter tracks how many strings were actually modified so the
    bundle's `caveats` can surface the number.

    Defense in depth: write-time scanning already rejects secret-shaped
    free text, but the bundle runs the pass anyway per security.md §8.
    """

    if isinstance(value, str):
        redacted = redact_for_log(value)
        if redacted != value:
            counter["replacements"] += 1
        return redacted
    if isinstance(value, list):
        return [_redact_strings_in_place(item, counter=counter)
                for item in value]
    if isinstance(value, dict):
        return {k: _redact_strings_in_place(v, counter=counter)
                for k, v in value.items()}
    return value


# -- bundle hash -------------------------------------------------------


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str).encode("utf-8")


def _bundle_hash(payload: dict[str, Any]) -> str:
    """Return the canonical sha-256 hash of `payload` (without the
    `bundle_hash` field itself)."""

    body = {k: v for k, v in payload.items() if k != "bundle_hash"}
    digest = hashlib.sha256(_canonical_json(body)).hexdigest()
    return f"sha256:{digest}"


# -- main handler ------------------------------------------------------


def _prepare_bundle_filter(
    args: dict[str, Any],
) -> tuple[ReviewBundleInput, ReportFilter, dict[str, Any]]:
    try:
        parsed = ReviewBundleInput.model_validate(args)
    except ValidationError as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"review.bundle input validation failed: {exc.errors()}",
            details={"validation_errors": exc.errors()},
        ) from exc

    try:
        rf = ReportFilter.model_validate(parsed.filter)
    except ValidationError as exc:
        raise report_filter_validation_to_tool_error(exc) from exc

    try:
        enforce_supported_filter(rf, report=REVIEW_BUNDLE_REPORT)
    except UnsupportedFilterError as exc:
        raise unsupported_filter_to_tool_error(exc) from exc
    filter_view = applied_filter_view(rf, report=REVIEW_BUNDLE_REPORT)

    return parsed, rf, filter_view


def _gather_selected_context(
    conn: sqlite3.Connection, rf: ReportFilter, *, max_records: int,
) -> tuple[list[str], dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    decision_ids = _select_decision_ids(
        conn, rf, max_records=max_records,
    )
    decisions = _decision_rows(conn, decision_ids)
    selected = _related_record_rows(conn, decisions)

    target_kinds = {
        "decision": [d["id"] for d in selected["decisions"]],
        "thesis": [t["id"] for t in selected["theses"]],
        "forecast": [f["id"] for f in selected["forecasts"]],
        "outcome": [o["id"] for o in selected["outcomes"]],
    }

    return decision_ids, selected, target_kinds


def _gather_optional_attachments(
    conn: sqlite3.Connection,
    parsed: ReviewBundleInput,
    *,
    decision_ids: list[str],
    target_kinds: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], int, int,
           list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    omitted_sensitive = 0
    redacted_sources = 0
    if parsed.include_sources:
        sources, omitted_sensitive, redacted_sources = (
            _gather_attached_sources(conn, target_kinds=target_kinds)
        )

    reflections: list[dict[str, Any]] = []
    if parsed.include_reflections:
        reflections = _gather_reflections(conn, target_kinds=target_kinds)

    playbook_versions: list[dict[str, Any]] = []
    if parsed.include_playbook:
        playbook_versions = _gather_playbook_versions(
            conn, decision_ids=decision_ids,
        )

    return (sources, omitted_sensitive, redacted_sources, reflections,
            playbook_versions)


def _report_summaries(
    conn: sqlite3.Connection, *, filter_view: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        calibration = report_calibration(conn, raw_filter=filter_view)
        calibration_summary = calibration["summary"]
    except Exception:  # noqa: BLE001 - bundle continues with empty summary
        calibration_summary = {"sample_size": 0, "sample_warning": None}

    report_summaries = {"calibration": calibration_summary}
    return report_summaries, calibration_summary


def _gather_recall_receipt_blocks(
    conn: sqlite3.Connection,
    *,
    decision_ids: list[str],
    include_recall_receipts: bool,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "included",
        "consumer_scope": "selected_decisions",
        "receipt_refs": [],
        "blocks": [],
        "caveat_codes": [],
        "omissions": [],
        "truncated": False,
        "attribution_conventions": ATTRIBUTION_CONVENTIONS,
    }
    if not include_recall_receipts:
        return {**base, "status": "omitted", "omissions": ["omitted_by_input_flag"]}
    if not decision_ids:
        return {**base, "status": "omitted", "omissions": ["omitted_no_selected_consumers"]}

    blocks_by_receipt_id: dict[str, dict[str, Any]] = {}
    caveat_codes: set[str] = set()
    truncated = False
    for decision_id in decision_ids:
        remaining = RECALL_RECEIPTS_MAX_BLOCKS - len(blocks_by_receipt_id)
        if remaining <= 0:
            truncated = True
            break
        report = report_recall_receipts(
            conn,
            consumer_kind="decision",
            consumer_id=decision_id,
            limit=remaining + 1,
        )
        receipts = report.get("recall_receipts", [])
        if len(receipts) > remaining:
            truncated = True
            receipts = receipts[:remaining]
        for receipt in receipts:
            block = _recall_receipt_block(receipt, consumer_id=decision_id)
            blocks_by_receipt_id.setdefault(block["receipt_id"], block)
            caveat_codes.update(block["caveat_codes"])

    blocks = [blocks_by_receipt_id[key] for key in sorted(blocks_by_receipt_id)]
    omissions: list[str] = []
    if not blocks:
        omissions.append("no_recall_receipts")
    if truncated:
        omissions.append("truncated")
        caveat_codes.add("RECALL_RECEIPTS_TRUNCATED")
    return {
        **base,
        "status": "included" if blocks else "omitted",
        "receipt_refs": [
            {"receipt_id": block["receipt_id"], "recall_id": block["recall_id"]}
            for block in blocks
        ],
        "blocks": blocks,
        "caveat_codes": sorted(caveat_codes),
        "omissions": omissions,
        "truncated": truncated,
    }


def _recall_receipt_block(receipt: dict[str, Any], *, consumer_id: str) -> dict[str, Any]:
    item_caveats = sorted({
        code
        for item in receipt.get("items", [])
        for code in item.get("caveat_codes", [])
    })
    caveats = sorted(set(receipt.get("caveat_codes", [])) | set(item_caveats))
    return {
        "receipt_id": receipt["receipt_id"],
        "recall_id": receipt["recall_id"],
        "consumer": {"kind": "decision", "id": consumer_id},
        "node_ids_returned": receipt.get("node_ids_returned", []),
        "node_ids_used": receipt.get("node_ids_used", []),
        "node_ids_ignored_or_unattributed": receipt.get("node_ids_ignored_or_unattributed", []),
        "caveat_codes": caveats,
        "item_caveats": [
            {
                "node_id": item.get("id"),
                "status": item.get("status"),
                "attribution_status": item.get("attribution_status"),
                "caveat_codes": item.get("caveat_codes", []),
            }
            for item in receipt.get("items", [])
            if item.get("caveat_codes")
        ],
        "source_refs": receipt.get("source_refs", []),
    }


def _build_caveats(
    *,
    calibration_summary: dict[str, Any],
    omitted_sensitive: int,
    redacted_sources: int,
) -> list[str]:
    caveats: list[str] = []
    sample_warning = (calibration_summary or {}).get("sample_warning")
    if sample_warning:
        caveats.append(sample_warning)
    if omitted_sensitive:
        caveats.append(
            f"{omitted_sensitive} source(s) omitted (redaction_status=sensitive)"
        )
    if redacted_sources:
        caveats.append(
            f"{redacted_sources} source(s) included with content stripped "
            f"(redaction_status=redacted)"
        )
    return caveats


def _apply_redaction_sweep(
    *,
    selected: dict[str, list[dict[str, Any]]],
    sources: list[dict[str, Any]],
    reflections: list[dict[str, Any]],
    playbook_versions: list[dict[str, Any]],
    recall_receipts: dict[str, Any],
    caveats: list[str],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]],
           list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    secret_counter = {"replacements": 0}
    selected = _redact_strings_in_place(selected, counter=secret_counter)
    sources = _redact_strings_in_place(sources, counter=secret_counter)
    reflections = _redact_strings_in_place(reflections, counter=secret_counter)
    playbook_versions = _redact_strings_in_place(
        playbook_versions, counter=secret_counter
    )
    recall_receipts = _redact_strings_in_place(
        recall_receipts, counter=secret_counter
    )
    if secret_counter["replacements"]:
        caveats.append(
            f"{secret_counter['replacements']} secret-shaped value(s) "
            f"replaced with REDACTED-* tokens (security.md §8)"
        )

    return selected, sources, reflections, playbook_versions, recall_receipts


def _assemble_bundle(
    *,
    filter_view: dict[str, Any],
    selected: dict[str, list[dict[str, Any]]],
    sources: list[dict[str, Any]],
    reflections: list[dict[str, Any]],
    playbook_versions: list[dict[str, Any]],
    report_summaries: dict[str, Any],
    recall_receipts: dict[str, Any],
    caveats: list[str],
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "filter": filter_view,
        "selected": selected,
        "sources": sources,
        "reflections": reflections,
        "playbook_versions": playbook_versions,
        "report_summaries": report_summaries,
        "recall_receipts": recall_receipts,
        "caveats": caveats,
        "suggested_prompts": _suggested_prompts(selected),
        "contract_version": CONTRACT_VERSION,
    }
    data["bundle_hash"] = _bundle_hash(data)
    return data


def _review_bundle_handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    parsed, rf, filter_view = _prepare_bundle_filter(args)

    db = open_db_for_args(args)
    try:
        conn = db.connection
        decision_ids, selected, target_kinds = _gather_selected_context(
            conn, rf, max_records=parsed.max_records,
        )
        (sources, omitted_sensitive, redacted_sources, reflections,
         playbook_versions) = _gather_optional_attachments(
            conn, parsed, decision_ids=decision_ids, target_kinds=target_kinds,
        )
        report_summaries, calibration_summary = _report_summaries(
            conn, filter_view=filter_view,
        )
        recall_receipts = _gather_recall_receipt_blocks(
            conn,
            decision_ids=decision_ids,
            include_recall_receipts=parsed.include_recall_receipts,
        )
    finally:
        db.close()

    caveats = _build_caveats(
        calibration_summary=calibration_summary,
        omitted_sensitive=omitted_sensitive,
        redacted_sources=redacted_sources,
    )
    selected, sources, reflections, playbook_versions, recall_receipts = _apply_redaction_sweep(
        selected=selected,
        sources=sources,
        reflections=reflections,
        playbook_versions=playbook_versions,
        recall_receipts=recall_receipts,
        caveats=caveats,
    )
    data = _assemble_bundle(
        filter_view=filter_view,
        selected=selected,
        sources=sources,
        reflections=reflections,
        playbook_versions=playbook_versions,
        report_summaries=report_summaries,
        recall_receipts=recall_receipts,
        caveats=caveats,
    )

    ctx.meta_hints["bundle_hash"] = data["bundle_hash"]
    ctx.meta_hints["contract_version"] = CONTRACT_VERSION
    return data


def _suggested_prompts(selected: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Static, deterministic prompt suggestions per reports.md §5.2.

    The bundle is NOT an LLM call; these are template prompts the
    reviewer's own model can pick up. Order is fixed so the bundle hash
    stays stable.
    """

    if not selected.get("decisions"):
        return []
    return [
        "Which decisions reflect the same root-cause mistake?",
        "Is the agent over-using any single tag?",
        "What sources tend to anchor over-confident forecasts?",
    ]


def register_review_bundle(registry: ToolRegistry) -> None:
    registry.register(
        "review.bundle",
        _review_bundle_handler,
        description=(
            "Bundle a bounded case set (decisions + theses + forecasts + "
            "outcomes + positions + attached sources/reflections/playbook "
            "versions) as deterministic JSON for an external reviewer per "
            "reports.md §5. Applies the security.md §8 redaction rules: "
            "sensitive sources are omitted with a caveat, redacted sources "
            "are included with content stripped. The output's "
            "bundle_hash is sha-256 over the canonical JSON of `data` "
            "(minus the hash itself) so the same DB state + same input "
            "yields the same hash."
        ),
    )
