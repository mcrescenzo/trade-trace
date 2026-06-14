"""Rule-lineage report (bead trade-trace-a5dy).

Walks the VISION "trace any rule in its playbook back through the reflection
that proposed it to the trades that taught it" chain in a *single* read-only,
deterministic query path. The provenance the agent needs is split across three
heterogeneous mechanisms today:

* ``playbook_versions.provenance_reflection_node_id`` -- a COLUMN linking a
  rule-version to the reflection that motivated it (written by
  ``playbook.propose_version``).
* the typed ``edges`` table -- the reflection's outgoing ``about`` /
  ``derived_from`` / ``supports`` / ``contradicts`` / ``supersedes`` edges to
  decisions / theses / forecasts / outcomes / memory nodes, AND the
  consumer->memory edges (``decision``/``thesis``/``forecast``/``outcome``/
  ``review``/``playbook_version`` rows pointing at the reflection) that mark
  downstream *use* of that reflection (memory-layer.md s9.1).
* ``decision_playbook_rules`` -- the per-``(decision, version, rule)`` adherence
  rows. This table is ALSO the only place a ``playbook_rule`` memory node is
  associated with a ``playbook_version`` today: rule-node ``derived_from`` edges
  are not auto-written, so the report bridges rule -> version through the
  adherence rows (see the OPEN QUESTION note below).

This report assembles all three into one chain with the contributing
``record_ids`` at each hop and EXPLICIT ``gaps`` where a link is missing, so the
VISION "trace any rule" clause becomes a single query path instead of manual
cross-mechanism edge-following.

OPEN QUESTION (owner decision -- default = bridge version<->rule)
-----------------------------------------------------------------
Should the chain anchor at a ``playbook_rule`` node or a ``playbook_version``?
Rule-node ``derived_from`` edges are NOT auto-written today; only the version
carries ``provenance_reflection_node_id``. This report therefore accepts EITHER
anchor and bridges between them through ``decision_playbook_rules``:

* anchored at a rule node -> every version that ever evaluated that rule (via an
  adherence row) is walked;
* anchored at a version id -> that one version is walked, and the rules it
  evaluated are surfaced.

When a rule node has no adherence row on any version, the bridge is a declared
GAP (``rule_not_linked_to_any_version``) rather than a silent empty result.

Read-only, deterministic, local-only: no network, no writes, no advice, no
execution.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from trade_trace.reports._envelope import standard_report_result

# Reflection outgoing edge types we surface, in stable report order. These are
# the provenance/use links FROM a reflection memory node to ledger rows.
_REFLECTION_OUTGOING_EDGE_TYPES = (
    "about",
    "derived_from",
    "supports",
    "contradicts",
    "supersedes",
)

# Consumer kinds whose edges INTO a memory node mark downstream use of that
# reflection (memory-layer.md s9.1: the canonical use-link direction is always
# ``consumer row --edge_type--> memory_node``).
_CONSUMER_KINDS = (
    "decision",
    "thesis",
    "forecast",
    "outcome",
    "review",
    "playbook_version",
)

CAVEAT_CODES = (
    "RULE_LINEAGE_READ_ONLY",
    "LOCAL_EVIDENCE_ONLY",
    "VERSION_RULE_BRIDGE_VIA_ADHERENCE",
)


def report_rule_lineage(
    conn: sqlite3.Connection,
    *,
    rule_node_id: str | None = None,
    playbook_version_id: str | None = None,
) -> dict[str, Any]:
    """Walk playbook_rule/playbook_version -> reflection -> trades in one path.

    Exactly one of ``rule_node_id`` or ``playbook_version_id`` must be supplied.
    Returns a deterministic chain of per-version lineage links with the
    contributing record ids at each hop and explicit gaps where a link is
    missing.
    """

    if (rule_node_id is None) == (playbook_version_id is None):
        raise ValueError(
            "exactly one of rule_node_id or playbook_version_id is required"
        )

    if rule_node_id is not None:
        anchor = _anchor_from_rule(conn, rule_node_id)
    else:
        assert playbook_version_id is not None
        anchor = _anchor_from_version(conn, playbook_version_id)

    chains = [
        _chain_for_version(conn, version_id, anchor_rule_node_id=rule_node_id)
        for version_id in anchor["version_ids"]
    ]

    total_gaps = sorted(
        {gap["code"] for gap in anchor["gaps"]}
        | {gap["code"] for chain in chains for gap in chain["gaps"]}
    )
    groups = [_group_for_chain(chain) for chain in chains]

    caveats = set(CAVEAT_CODES)
    if not chains:
        caveats.add("NO_RULE_LINEAGE_FOUND")
    if total_gaps:
        caveats.add("RULE_LINEAGE_HAS_GAPS")

    summary = {
        "bucket": "rule_lineage",
        "anchor": anchor["anchor"],
        "sample_size": len(chains),
        "sample_warning": "no_rule_lineage" if not chains else None,
        "metrics": {
            "version_count": len(chains),
            "reflection_count": sum(
                1 for c in chains if c["reflection"] is not None
            ),
            "downstream_edge_count": sum(
                c["downstream_edge_count"] for c in chains
            ),
            "consumer_use_edge_count": sum(
                c["consumer_use_edge_count"] for c in chains
            ),
            "adherence_row_count": sum(
                c["adherence_row_count"] for c in chains
            ),
            "gap_count": len(total_gaps),
        },
        "gap_codes": total_gaps,
        "caveat_codes": sorted(caveats),
        "interpretation": (
            "Read-only local rule-lineage chain. Each chain walks one "
            "playbook_version -> its provenance reflection -> that reflection's "
            "typed edges to decisions/theses/forecasts/outcomes (the trades and "
            "judgments that taught the rule) + the consumer->memory use edges "
            "into the reflection + the decision_playbook_rules adherence rows. "
            "Missing links are declared in `gaps`, not silently dropped. The "
            "version<->rule bridge runs through decision_playbook_rules because "
            "rule-node provenance edges are not auto-written today."
        ),
    }
    return standard_report_result(
        summary=summary,
        groups=groups,
        extra={"chains": chains, "anchor_gaps": anchor["gaps"]},
    )


def _anchor_from_rule(
    conn: sqlite3.Connection, rule_node_id: str
) -> dict[str, Any]:
    """Resolve the version set for a ``playbook_rule`` anchor.

    The rule node must exist and be a ``playbook_rule``. Versions are bridged
    via ``decision_playbook_rules`` (rule-node provenance edges are not
    auto-written). A rule with no adherence row on any version yields a declared
    gap rather than an empty silent result.
    """
    row = conn.execute(
        "SELECT id, node_type, title, body FROM memory_nodes WHERE id = ?",
        (rule_node_id,),
    ).fetchone()
    gaps: list[dict[str, Any]] = []
    if row is None:
        raise ValueError(f"rule_node_id {rule_node_id!r} not found")
    if row[1] != "playbook_rule":
        raise ValueError(
            f"rule_node_id {rule_node_id!r} is node_type {row[1]!r}, "
            "expected 'playbook_rule'"
        )
    version_rows = conn.execute(
        "SELECT DISTINCT playbook_version_id FROM decision_playbook_rules "
        "WHERE rule_node_id = ? ORDER BY playbook_version_id",
        (rule_node_id,),
    ).fetchall()
    version_ids = [r[0] for r in version_rows]
    if not version_ids:
        gaps.append(
            {
                "code": "rule_not_linked_to_any_version",
                "detail": (
                    "no decision_playbook_rules row links this playbook_rule "
                    "to any playbook_version; rule-node provenance edges are "
                    "not auto-written, so no version bridge exists yet"
                ),
                "rule_node_id": rule_node_id,
            }
        )
    return {
        "anchor": {
            "kind": "playbook_rule",
            "rule_node_id": rule_node_id,
            "title": row[2],
            "body": row[3],
            "version_ids": version_ids,
        },
        "version_ids": version_ids,
        "gaps": gaps,
    }


def _anchor_from_version(
    conn: sqlite3.Connection, playbook_version_id: str
) -> dict[str, Any]:
    """Resolve the version set for a ``playbook_version`` anchor (one version)."""
    row = conn.execute(
        "SELECT id, playbook_id, version, provenance_reflection_node_id "
        "FROM playbook_versions WHERE id = ?",
        (playbook_version_id,),
    ).fetchone()
    if row is None:
        raise ValueError(
            f"playbook_version_id {playbook_version_id!r} not found"
        )
    return {
        "anchor": {
            "kind": "playbook_version",
            "playbook_version_id": row[0],
            "playbook_id": row[1],
            "version": row[2],
            "version_ids": [row[0]],
        },
        "version_ids": [row[0]],
        "gaps": [],
    }


def _chain_for_version(
    conn: sqlite3.Connection,
    version_id: str,
    *,
    anchor_rule_node_id: str | None,
) -> dict[str, Any]:
    """Assemble the full lineage chain for one playbook_version."""
    version_row = conn.execute(
        "SELECT id, playbook_id, version, parent_version_id, "
        "provenance_reflection_node_id, created_at "
        "FROM playbook_versions WHERE id = ?",
        (version_id,),
    ).fetchone()
    gaps: list[dict[str, Any]] = []
    if version_row is None:
        # Defensive: an adherence row referenced a version that does not exist.
        gaps.append(
            {
                "code": "version_not_found",
                "detail": "playbook_version row is missing for this id",
                "playbook_version_id": version_id,
            }
        )
        return {
            "playbook_version_id": version_id,
            "playbook_id": None,
            "version": None,
            "reflection": None,
            "downstream_edges": {},
            "downstream_edge_count": 0,
            "consumer_use_edges": [],
            "consumer_use_edge_count": 0,
            "adherence_rows": [],
            "adherence_row_count": 0,
            "rules": [],
            "gaps": gaps,
            "record_ids": {},
        }

    reflection_node_id = version_row[4]
    reflection = _reflection_node(conn, reflection_node_id)
    if reflection is None:
        gaps.append(
            {
                "code": "provenance_reflection_missing",
                "detail": (
                    "playbook_versions.provenance_reflection_node_id points at "
                    "a memory node that does not exist or is not a reflection"
                ),
                "provenance_reflection_node_id": reflection_node_id,
                "playbook_version_id": version_id,
            }
        )

    downstream = _reflection_outgoing_edges(conn, reflection_node_id)
    downstream_count = sum(len(v) for v in downstream.values())
    if reflection is not None and downstream_count == 0:
        gaps.append(
            {
                "code": "reflection_has_no_downstream_edges",
                "detail": (
                    "the provenance reflection has no outgoing typed edges to "
                    "decisions/theses/forecasts/outcomes; the trades it taught "
                    "are not linked"
                ),
                "reflection_node_id": reflection_node_id,
            }
        )

    consumer_use = _consumer_use_edges(conn, reflection_node_id)
    if reflection is not None and not consumer_use:
        gaps.append(
            {
                "code": "reflection_not_used_downstream",
                "detail": (
                    "no consumer->memory edge points at this reflection; no "
                    "decision/thesis/forecast/outcome recorded using it"
                ),
                "reflection_node_id": reflection_node_id,
            }
        )

    adherence_rows = _adherence_rows(
        conn, version_id, rule_node_id=anchor_rule_node_id
    )
    if not adherence_rows:
        gaps.append(
            {
                "code": "no_adherence_rows",
                "detail": (
                    "no decision_playbook_rules row records a decision "
                    "evaluating this version"
                    + (
                        f" for rule {anchor_rule_node_id!r}"
                        if anchor_rule_node_id is not None
                        else ""
                    )
                ),
                "playbook_version_id": version_id,
            }
        )

    rules = _rules_for_version(conn, version_id)

    record_ids = {
        "playbook_versions": [version_id],
        "reflection_nodes": [reflection_node_id]
        if reflection is not None
        else [],
        "decisions": sorted(
            {
                edge["target_id"]
                for edge in downstream.get("about", [])
                + downstream.get("derived_from", [])
                + downstream.get("supports", [])
                + downstream.get("contradicts", [])
                + downstream.get("supersedes", [])
                if edge["target_kind"] == "decision"
            }
            | {
                row["decision_id"] for row in adherence_rows
            }
            | {
                edge["source_id"]
                for edge in consumer_use
                if edge["source_kind"] == "decision"
            }
        ),
        "forecasts": sorted(
            {
                edge["target_id"]
                for edges in downstream.values()
                for edge in edges
                if edge["target_kind"] == "forecast"
            }
            | {
                edge["source_id"]
                for edge in consumer_use
                if edge["source_kind"] == "forecast"
            }
        ),
        "outcomes": sorted(
            {
                edge["target_id"]
                for edges in downstream.values()
                for edge in edges
                if edge["target_kind"] == "outcome"
            }
            | {
                edge["source_id"]
                for edge in consumer_use
                if edge["source_kind"] == "outcome"
            }
        ),
        "theses": sorted(
            {
                edge["target_id"]
                for edges in downstream.values()
                for edge in edges
                if edge["target_kind"] == "thesis"
            }
            | {
                edge["source_id"]
                for edge in consumer_use
                if edge["source_kind"] == "thesis"
            }
        ),
        "rule_nodes": [r["rule_node_id"] for r in rules],
        "adherence": [r["adherence_id"] for r in adherence_rows],
    }

    return {
        "playbook_version_id": version_id,
        "playbook_id": version_row[1],
        "version": version_row[2],
        "parent_version_id": version_row[3],
        "created_at": version_row[5],
        "reflection": reflection,
        "downstream_edges": downstream,
        "downstream_edge_count": downstream_count,
        "consumer_use_edges": consumer_use,
        "consumer_use_edge_count": len(consumer_use),
        "adherence_rows": adherence_rows,
        "adherence_row_count": len(adherence_rows),
        "rules": rules,
        "gaps": gaps,
        "record_ids": record_ids,
    }


def _reflection_node(
    conn: sqlite3.Connection, node_id: str | None
) -> dict[str, Any] | None:
    if node_id is None:
        return None
    row = conn.execute(
        "SELECT id, node_type, title, body, importance, confidence_base, "
        "valid_from, valid_to, invalidated_at, created_at "
        "FROM memory_nodes WHERE id = ? AND node_type = 'reflection'",
        (node_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "node_id": row[0],
        "node_type": row[1],
        "title": row[2],
        "body": row[3],
        "importance": row[4],
        "confidence_base": row[5],
        "valid_from": row[6],
        "valid_to": row[7],
        "invalidated_at": row[8],
        "created_at": row[9],
    }


def _reflection_outgoing_edges(
    conn: sqlite3.Connection, reflection_node_id: str | None
) -> dict[str, list[dict[str, Any]]]:
    """Outgoing typed edges FROM the reflection memory node, grouped by type.

    These are the provenance/use links the reflection wrote toward ledger rows
    (the ``about`` edge to its subject, plus any ``derived_from`` / ``supports``
    / ``contradicts`` / ``supersedes`` edges). Ordering is deterministic.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    if reflection_node_id is None:
        return grouped
    rows = conn.execute(
        "SELECT id, edge_type, target_kind, target_id, weight, created_at "
        "FROM edges "
        "WHERE source_kind = 'memory_node' AND source_id = ? "
        "ORDER BY edge_type, target_kind, target_id, id",
        (reflection_node_id,),
    ).fetchall()
    for edge_id, edge_type, target_kind, target_id, weight, created_at in rows:
        grouped.setdefault(edge_type, []).append(
            {
                "edge_id": edge_id,
                "edge_type": edge_type,
                "target_kind": target_kind,
                "target_id": target_id,
                "weight": weight,
                "created_at": created_at,
            }
        )
    return grouped


def _consumer_use_edges(
    conn: sqlite3.Connection, reflection_node_id: str | None
) -> list[dict[str, Any]]:
    """Consumer->memory edges pointing AT the reflection (downstream use).

    Per memory-layer.md s9.1 the canonical use-link direction is always
    ``consumer row --edge_type--> memory_node``; these prove a decision / thesis
    / forecast / outcome / review / playbook_version actually used the rule's
    reflection. Memory-node *outgoing* edges are provenance, not use, so they
    are excluded here.
    """
    if reflection_node_id is None:
        return []
    placeholders = ",".join("?" for _ in _CONSUMER_KINDS)
    rows = conn.execute(
        "SELECT id, source_kind, source_id, edge_type, weight, created_at "
        "FROM edges "
        "WHERE target_kind = 'memory_node' AND target_id = ? "
        f"AND source_kind IN ({placeholders}) "
        "ORDER BY source_kind, source_id, edge_type, id",
        (reflection_node_id, *_CONSUMER_KINDS),
    ).fetchall()
    return [
        {
            "edge_id": row[0],
            "source_kind": row[1],
            "source_id": row[2],
            "edge_type": row[3],
            "weight": row[4],
            "created_at": row[5],
        }
        for row in rows
    ]


def _adherence_rows(
    conn: sqlite3.Connection,
    version_id: str,
    *,
    rule_node_id: str | None,
) -> list[dict[str, Any]]:
    """``decision_playbook_rules`` rows for this version (optionally one rule)."""
    sql = (
        "SELECT id, decision_id, rule_node_id, status, reason, created_at "
        "FROM decision_playbook_rules WHERE playbook_version_id = ?"
    )
    params: list[Any] = [version_id]
    if rule_node_id is not None:
        sql += " AND rule_node_id = ?"
        params.append(rule_node_id)
    sql += " ORDER BY created_at, id"
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "adherence_id": row[0],
            "decision_id": row[1],
            "rule_node_id": row[2],
            "status": row[3],
            "reason": row[4],
            "created_at": row[5],
        }
        for row in rows
    ]


def _rules_for_version(
    conn: sqlite3.Connection, version_id: str
) -> list[dict[str, Any]]:
    """Distinct ``playbook_rule`` nodes evaluated against this version."""
    rows = conn.execute(
        "SELECT DISTINCT mn.id, mn.title, mn.body "
        "FROM decision_playbook_rules dpr "
        "JOIN memory_nodes mn ON mn.id = dpr.rule_node_id "
        "WHERE dpr.playbook_version_id = ? "
        "AND mn.node_type = 'playbook_rule' "
        "ORDER BY mn.created_at, mn.id",
        (version_id,),
    ).fetchall()
    return [
        {"rule_node_id": row[0], "title": row[1], "body": row[2]}
        for row in rows
    ]


def _group_for_chain(chain: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": chain["playbook_version_id"],
        "label": (
            f"Lineage for playbook_version {chain['playbook_version_id']}"
        ),
        "metrics": {
            "downstream_edge_count": chain["downstream_edge_count"],
            "consumer_use_edge_count": chain["consumer_use_edge_count"],
            "adherence_row_count": chain["adherence_row_count"],
            "rule_count": len(chain["rules"]),
            "gap_count": len(chain["gaps"]),
        },
        "record_ids": chain["record_ids"],
        "gap_codes": sorted({gap["code"] for gap in chain["gaps"]}),
        "sample_size": 1,
        "sample_warning": None,
        "truncated": False,
    }
