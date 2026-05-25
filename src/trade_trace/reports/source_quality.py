"""Source-quality / provenance report per bead trade-trace-l9q.

PRD §4.5 ships the source-attach surface; this module turns the resulting
edges into a reportable, coach-visible quality signal. The diagnostics
are hygiene warnings — they identify decisions/theses with thin or
contradictory provenance, not bad trades. No external fetching, no
credibility scoring (that's P1+).

Diagnostics:
    (a) missing_sources_on_actual_enter — decisions with type='actual_enter'
        whose linked thesis has zero attached sources.
    (b) stale_sources — sources whose freshness_at is older than the linked
        decision.created_at by more than the configured threshold.
    (c) contradictory_sources — theses with both `supports` and `contradicts`
        edges from sources of the same `kind` (sign of unresolved evidence).
    (d) duplicated_sources — sources with the same `content_hash` attached
        to the same target more than once.
    (e) sensitive_sources — sources with `redaction_status='sensitive'` that
        appear in attached edges; the report.bundle path must strip these
        per reports.md §5.3.

Each diagnostic surfaces record-linked `sample_ids` so the agent can
drill into the originating decision/thesis/source rows.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from trade_trace.timestamps import to_utc_iso8601

STALE_SOURCE_THRESHOLD_DAYS = 7
"""Per acceptance: a source is *stale* relative to a decision if its
`freshness_at` is more than 7 days older than the decision's `created_at`.
Configurable via `config.report.source_quality.stale_threshold_days` in
P1; pinned here for MVP reproducibility."""


MAX_SAMPLE_IDS = 100


def report_source_quality(
    conn: sqlite3.Connection,
    *,
    stale_threshold_days: int = STALE_SOURCE_THRESHOLD_DAYS,
) -> dict[str, Any]:
    """Compute the five provenance diagnostics. Returns the `data` portion
    of the report envelope; the dispatcher wraps it with meta. The report
    is intentionally global (no ReportFilter input): provenance hygiene
    is a journal-level signal, not a per-strategy slice."""

    missing = _missing_sources_on_actual_enter(conn)
    stale = _stale_sources(conn, stale_threshold_days=stale_threshold_days)
    contradictory = _contradictory_sources(conn)
    duplicated = _duplicated_sources(conn)
    sensitive = _sensitive_sources(conn)

    inline_attachments = _inline_source_attachments(conn)
    inline_source_ids = {att["id"] for att in inline_attachments if att.get("id")}
    legacy_source_ids = {
        str(row[0]) for row in conn.execute("SELECT id FROM sources").fetchall()
    }
    total_sources = len(inline_source_ids | legacy_source_ids)

    inline_attachment_keys = {
        (att.get("id"), att.get("target_kind"), att.get("target_id"))
        for att in inline_attachments
    }
    legacy_attachment_keys = {
        (str(source_id), str(target_kind), str(target_id))
        for source_id, target_kind, target_id in conn.execute(
            """
            SELECT source_id, target_kind, target_id
            FROM edges
            WHERE source_kind = 'source'
            """
        ).fetchall()
    }
    total_attachments = len(inline_attachment_keys | legacy_attachment_keys)
    sample_warning = "no_data" if total_sources == 0 else None

    return {
        "summary": {
            "total_sources": total_sources,
            "total_source_attachments": total_attachments,
            "stale_threshold_days": stale_threshold_days,
            "sample_warning": sample_warning,
        },
        "diagnostics": {
            "missing_sources_on_actual_enter": missing,
            "stale_sources": stale,
            "contradictory_sources": contradictory,
            "duplicated_sources": duplicated,
            "sensitive_sources": sensitive,
        },
    }


# -- helpers ----------------------------------------------------------


def _count(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row else 0


def _safe_metadata(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _inline_source_attachments(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    for table, kind in (("forecasts", "forecast"), ("decisions", "decision"), ("memory_nodes", "memory_node")):
        for target_id, metadata_json in conn.execute(f"SELECT id, metadata_json FROM {table}").fetchall():
            sources = _safe_metadata(metadata_json).get("sources")
            if not isinstance(sources, list):
                continue
            for idx, source in enumerate(sources):
                if not isinstance(source, dict):
                    continue
                source_id = source.get("id") or source.get("source_id") or f"inline:{kind}:{target_id}:{idx}"
                stance = source.get("stance") or source.get("edge_type") or "about"
                attachments.append({
                    **source,
                    "id": str(source_id),
                    "target_kind": kind,
                    "target_id": target_id,
                    "stance": stance if stance in ("supports", "contradicts", "about") else "about",
                    "freshness_at": source.get("freshness_at") or source.get("captured_at"),
                    "content_hash": source.get("content_hash") or source.get("hash"),
                    "redaction_status": source.get("redaction_status"),
                })
    return attachments


def _bundle(
    *, diagnostic: str, items: list[dict[str, Any]], sample_kind: str,
) -> dict[str, Any]:
    """Capture the true total before truncating samples.

    Per bead trade-trace-iyt: the count must reflect the real number of
    matches even when the sample list is capped at MAX_SAMPLE_IDS so
    operators don't undercount large hygiene problems. The capped
    sample_ids / samples list is for agent drill-down only.
    """

    total_count = len(items)
    truncated = total_count > MAX_SAMPLE_IDS
    if truncated:
        items = items[:MAX_SAMPLE_IDS]
    return {
        "diagnostic": diagnostic,
        "count": total_count,
        "sample_ids": {sample_kind: [it["id"] for it in items]},
        "samples": items,
        "truncated": truncated,
    }


# -- (a) missing_sources_on_actual_enter ----------------------------


def _missing_sources_on_actual_enter(conn: sqlite3.Connection) -> dict[str, Any]:
    """Decisions of type=actual_enter whose linked thesis has zero
    `source.attached` edges. The decision-without-thesis case is excluded
    (decision.thesis_id IS NULL means the agent declared no provenance to
    check; the existing ledger validation handles missing-required-thesis).
    """

    cur = conn.execute(
        """
        SELECT d.id, d.thesis_id
        FROM decisions d
        WHERE d.type = 'actual_enter'
          AND d.thesis_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM edges e
            WHERE e.source_kind = 'source'
              AND e.target_kind = 'thesis'
              AND e.target_id = d.thesis_id
          )
        ORDER BY d.created_at, d.id
        """
    )
    items = [{"id": d_id, "thesis_id": t_id} for d_id, t_id in cur.fetchall()]
    return _bundle(
        diagnostic="missing_sources_on_actual_enter",
        items=items, sample_kind="decisions",
    )


# -- (b) stale_sources ---------------------------------------------


def _stale_sources(
    conn: sqlite3.Connection, *, stale_threshold_days: int,
) -> dict[str, Any]:
    """Sources whose `freshness_at` predates a linked decision by more than
    the threshold, whether attached through the decision's thesis or attached
    directly to the decision. The acceptance criterion's
    phrasing — 'freshness_at > 7 days before decision.created_at' —
    operationalizes as `(decision.created_at - source.freshness_at) > 7d`.
    """

    cur = conn.execute(
        """
        SELECT s.id, d.id AS decision_id, s.freshness_at, d.created_at
        FROM edges e
        JOIN sources s ON s.id = e.source_id
        JOIN decisions d ON d.thesis_id = e.target_id
        WHERE e.source_kind = 'source'
          AND e.target_kind = 'thesis'
          AND s.freshness_at IS NOT NULL
        UNION
        SELECT s.id, d.id AS decision_id, s.freshness_at, d.created_at
        FROM edges e
        JOIN sources s ON s.id = e.source_id
        JOIN decisions d ON d.id = e.target_id
        WHERE e.source_kind = 'source'
          AND e.target_kind = 'decision'
          AND s.freshness_at IS NOT NULL
        ORDER BY s.id, d.created_at
        """
    )
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for s_id, d_id, fresh, d_ts in cur.fetchall():
        if (s_id, d_id) in seen:
            continue
        seen.add((s_id, d_id))
        try:
            fresh_iso = to_utc_iso8601(fresh)
            d_ts_iso = to_utc_iso8601(d_ts)
        except Exception:
            continue
        fresh_dt = datetime.fromisoformat(fresh_iso.replace("Z", "+00:00"))
        d_dt = datetime.fromisoformat(d_ts_iso.replace("Z", "+00:00"))
        if d_dt - fresh_dt > timedelta(days=stale_threshold_days):
            items.append({
                "id": s_id, "decision_id": d_id,
                "freshness_at": fresh_iso, "decision_at": d_ts_iso,
                "staleness_days": (d_dt - fresh_dt).days,
            })
    for att in _inline_source_attachments(conn):
        if att.get("target_kind") != "decision" or not att.get("freshness_at"):
            continue
        s_id = str(att.get("id"))
        d_id = str(att.get("target_id"))
        if (s_id, d_id) in seen:
            continue
        d_row = conn.execute("SELECT created_at FROM decisions WHERE id = ?", (d_id,)).fetchone()
        if d_row is None:
            continue
        seen.add((s_id, d_id))
        try:
            fresh_iso = to_utc_iso8601(str(att.get("freshness_at")))
            d_ts_iso = to_utc_iso8601(d_row[0])
        except Exception:
            continue
        fresh_dt = datetime.fromisoformat(fresh_iso.replace("Z", "+00:00"))
        d_dt = datetime.fromisoformat(d_ts_iso.replace("Z", "+00:00"))
        if d_dt - fresh_dt > timedelta(days=stale_threshold_days):
            items.append({
                "id": s_id, "decision_id": d_id,
                "freshness_at": fresh_iso, "decision_at": d_ts_iso,
                "staleness_days": (d_dt - fresh_dt).days,
            })
    return _bundle(
        diagnostic="stale_sources",
        items=items, sample_kind="sources",
    )


# -- (c) contradictory_sources --------------------------------------


def _contradictory_sources(conn: sqlite3.Connection) -> dict[str, Any]:
    """Theses with both `supports` and `contradicts` edges from sources of
    the same `kind`. Such theses have unresolved evidence: two news
    articles, say, that disagree. The diagnostic surfaces the thesis id
    plus the two source ids and their shared kind."""

    cur = conn.execute(
        """
        SELECT e_sup.target_id      AS thesis_id,
               s_sup.kind           AS kind,
               s_sup.id             AS source_supports_id,
               s_con.id             AS source_contradicts_id
        FROM edges e_sup
        JOIN sources s_sup ON s_sup.id = e_sup.source_id
        JOIN edges e_con ON e_con.source_kind = 'source'
                        AND e_con.target_kind = 'thesis'
                        AND e_con.target_id = e_sup.target_id
                        AND e_con.edge_type = 'contradicts'
        JOIN sources s_con ON s_con.id = e_con.source_id
        WHERE e_sup.source_kind = 'source'
          AND e_sup.target_kind = 'thesis'
          AND e_sup.edge_type = 'supports'
          AND s_sup.kind = s_con.kind
        ORDER BY e_sup.target_id, s_sup.kind
        """
    )
    rows = cur.fetchall()
    by_thesis: dict[str, dict[str, Any]] = {}
    for thesis_id, kind, sup_id, con_id in rows:
        key = thesis_id
        item = by_thesis.setdefault(key, {
            "id": thesis_id, "thesis_id": thesis_id,
            "kind": kind, "supports": [], "contradicts": [],
        })
        if sup_id not in item["supports"]:
            item["supports"].append(sup_id)
        if con_id not in item["contradicts"]:
            item["contradicts"].append(con_id)
    items = sorted(by_thesis.values(), key=lambda r: r["thesis_id"])
    return _bundle(
        diagnostic="contradictory_sources",
        items=items, sample_kind="theses",
    )


# -- (d) duplicated_sources -----------------------------------------


def _duplicated_sources(conn: sqlite3.Connection) -> dict[str, Any]:
    """Source rows with the same `content_hash` attached to the same target
    more than once. The MVP de-duplication signal — agents that paste the
    same article twice see this fire and consolidate before it pollutes
    the supports/contradicts counts."""

    cur = conn.execute(
        """
        SELECT s.content_hash, e.target_kind, e.target_id, COUNT(*) AS n,
               GROUP_CONCAT(s.id) AS source_ids
        FROM edges e
        JOIN sources s ON s.id = e.source_id
        WHERE e.source_kind = 'source'
          AND s.content_hash IS NOT NULL
        GROUP BY s.content_hash, e.target_kind, e.target_id
        HAVING COUNT(*) > 1
        ORDER BY n DESC, s.content_hash
        """
    )
    items = [
        {
            "id": content_hash,  # used by _bundle as the canonical key
            "content_hash": content_hash,
            "target_kind": target_kind,
            "target_id": target_id,
            "count": n,
            "source_ids": source_ids.split(",") if source_ids else [],
        }
        for content_hash, target_kind, target_id, n, source_ids in cur.fetchall()
    ]
    return _bundle(
        diagnostic="duplicated_sources",
        items=items, sample_kind="content_hashes",
    )


# -- (e) sensitive_sources ------------------------------------------


def _sensitive_sources(conn: sqlite3.Connection) -> dict[str, Any]:
    """Sources with `redaction_status='sensitive'` that show up in attached
    edges. report.bundle (reports.md §5.3) unconditionally strips these;
    the diagnostic surfaces them so the agent knows which edges are
    operating against a bundle blank-out."""

    cur = conn.execute(
        """
        SELECT DISTINCT s.id, s.redaction_status, e.target_kind, e.target_id
        FROM edges e
        JOIN sources s ON s.id = e.source_id
        WHERE e.source_kind = 'source'
          AND s.redaction_status = 'sensitive'
        ORDER BY s.id
        """
    )
    items = [
        {
            "id": s_id, "redaction_status": status,
            "target_kind": target_kind, "target_id": target_id,
        }
        for s_id, status, target_kind, target_id in cur.fetchall()
    ]
    seen = {(it["id"], it["target_kind"], it["target_id"]) for it in items}
    for att in _inline_source_attachments(conn):
        if att.get("redaction_status") != "sensitive":
            continue
        key = (att["id"], att["target_kind"], att["target_id"])
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "id": att["id"], "redaction_status": "sensitive",
            "target_kind": att["target_kind"], "target_id": att["target_id"],
        })
    return _bundle(
        diagnostic="sensitive_sources",
        items=items, sample_kind="sources",
    )


__all__ = [
    "MAX_SAMPLE_IDS",
    "STALE_SOURCE_THRESHOLD_DAYS",
    "report_source_quality",
]
