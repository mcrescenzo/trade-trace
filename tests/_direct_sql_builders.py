"""Composable direct-SQL test seed helpers per trade-trace-24ia (SIMP-009).

Three integration tests historically duplicated a `_seed_minimal(conn)`
helper that inlined the same `INSERT INTO venues / instruments /
theses / …` SQL with slightly different column subsets and string
values. Each test wanted a slightly different subgraph, so a single
"seed everything" builder was too coarse — but the per-table column
lists, the canonical id constants (`v_1`, `i_1`, …), and the canonical
timestamp were stable across them all.

This module exposes small, composable inserters keyed on the same ids
the original seeders used. Each helper accepts the connection plus
optional overrides on the discriminating columns (so a test that
needs `body = "thesis body"` instead of `body = "..."` doesn't have
to reach into SQL).
"""

from __future__ import annotations

import sqlite3

DEFAULT_TS = "2026-05-18T14:00:00Z"
DEFAULT_ACTOR = "agent:default"


def insert_venue(
    conn: sqlite3.Connection,
    *,
    venue_id: str = "v_1",
    name: str = "manual",
    kind: str = "manual",
    created_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    conn.execute(
        "INSERT INTO venues(id, name, kind, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (venue_id, name, kind, created_at, actor_id),
    )


def insert_instrument(
    conn: sqlite3.Connection,
    *,
    instrument_id: str = "i_1",
    venue_id: str = "v_1",
    title: str = "Test",
    asset_class: str = "prediction_market",
    created_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    conn.execute(
        "INSERT INTO instruments(id, venue_id, title, asset_class, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (instrument_id, venue_id, title, asset_class, created_at, actor_id),
    )


def insert_thesis(
    conn: sqlite3.Connection,
    *,
    thesis_id: str = "t_1",
    instrument_id: str = "i_1",
    side: str = "yes",
    body: str = "...",
    created_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    conn.execute(
        "INSERT INTO theses(id, instrument_id, side, body, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (thesis_id, instrument_id, side, body, created_at, actor_id),
    )


def insert_forecast(
    conn: sqlite3.Connection,
    *,
    forecast_id: str = "f_1",
    thesis_id: str = "t_1",
    kind: str = "binary",
    created_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    conn.execute(
        "INSERT INTO forecasts(id, thesis_id, kind, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (forecast_id, thesis_id, kind, created_at, actor_id),
    )


def insert_forecast_outcome(
    conn: sqlite3.Connection,
    *,
    fo_id: str = "fo_1",
    forecast_id: str = "f_1",
    outcome_label: str = "YES",
    probability: float = 0.6,
) -> None:
    conn.execute(
        "INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability) "
        "VALUES (?, ?, ?, ?)",
        (fo_id, forecast_id, outcome_label, probability),
    )


def insert_snapshot(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str = "snap_1",
    instrument_id: str = "i_1",
    captured_at: str = DEFAULT_TS,
    created_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    conn.execute(
        "INSERT INTO snapshots(id, instrument_id, captured_at, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (snapshot_id, instrument_id, captured_at, created_at, actor_id),
    )


def insert_decision(
    conn: sqlite3.Connection,
    *,
    decision_id: str = "d_1",
    instrument_id: str = "i_1",
    type: str = "skip",
    created_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    conn.execute(
        "INSERT INTO decisions(id, instrument_id, type, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (decision_id, instrument_id, type, created_at, actor_id),
    )


def insert_decision_tag(
    conn: sqlite3.Connection, *, decision_id: str = "d_1", tag: str = "liquidity-ignored",
) -> None:
    conn.execute(
        "INSERT INTO decision_tags(decision_id, tag) VALUES (?, ?)",
        (decision_id, tag),
    )


def insert_outcome(
    conn: sqlite3.Connection,
    *,
    outcome_id: str = "o_1",
    instrument_id: str = "i_1",
    resolved_at: str = DEFAULT_TS,
    outcome_label: str = "YES",
    status: str = "resolved_final",
    created_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    conn.execute(
        "INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, "
        "status, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (outcome_id, instrument_id, resolved_at, outcome_label, status,
         created_at, actor_id),
    )


def insert_source(
    conn: sqlite3.Connection,
    *,
    source_id: str = "s_1",
    kind: str = "note",
    stance: str | None = None,
    created_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    if stance is None:
        conn.execute(
            "INSERT INTO sources(id, kind, created_at, actor_id) "
            "VALUES (?, ?, ?, ?)",
            (source_id, kind, created_at, actor_id),
        )
    else:
        conn.execute(
            "INSERT INTO sources(id, kind, stance, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_id, kind, stance, created_at, actor_id),
        )


def insert_edge(
    conn: sqlite3.Connection,
    *,
    edge_id: str = "e_1",
    source_kind: str = "source",
    source_id: str = "s_1",
    target_kind: str = "thesis",
    target_id: str = "t_1",
    edge_type: str = "about",
    created_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    conn.execute(
        "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
        "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (edge_id, source_kind, source_id, target_kind, target_id, edge_type,
         created_at, actor_id),
    )


def insert_position_event(
    conn: sqlite3.Connection,
    *,
    pe_id: str = "pe_1",
    position_id: str = "p_1",
    instrument_id: str = "i_1",
    event_type: str = "open",
    created_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    conn.execute(
        "INSERT INTO position_events(id, position_id, instrument_id, "
        "event_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?)",
        (pe_id, position_id, instrument_id, event_type, created_at, actor_id),
    )


def insert_forecast_score(
    conn: sqlite3.Connection,
    *,
    fs_id: str = "fs_1",
    forecast_id: str = "f_1",
    outcome_id: str = "o_1",
    metric: str = "brier_binary",
    score: float = 0.16,
    scored_at: str = DEFAULT_TS,
    actor_id: str = DEFAULT_ACTOR,
) -> None:
    conn.execute(
        "INSERT INTO forecast_scores(id, forecast_id, outcome_id, metric, "
        "score, scored_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fs_id, forecast_id, outcome_id, metric, score, scored_at, actor_id),
    )


def insert_signal(
    conn: sqlite3.Connection,
    *,
    signal_id: str = "sig_1",
    kind: str = "sample_size_warning",
    severity: str = "warn",
    created_at: str = DEFAULT_TS,
    actor_id: str = "system:report.coach",
) -> None:
    conn.execute(
        "INSERT INTO signals(id, kind, severity, created_at, actor_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (signal_id, kind, severity, created_at, actor_id),
    )


def insert_audit_event(
    conn: sqlite3.Connection,
    *,
    event_type: str = "audit.seeded",
    subject_kind: str = "instrument",
    subject_id: str = "i_1",
    payload_json: str = "{}",
    actor_id: str = DEFAULT_ACTOR,
    created_at: str = DEFAULT_TS,
) -> None:
    conn.execute(
        "INSERT INTO events(event_type, subject_kind, subject_id, "
        "payload_json, actor_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (event_type, subject_kind, subject_id, payload_json, actor_id,
         created_at),
    )


def seed_full_append_only_graph(conn: sqlite3.Connection) -> None:
    """Seed one row in every append-only ledger table with canonical
    constants (used by `tests/integration/test_append_only.py`)."""

    insert_venue(conn)
    insert_instrument(conn)
    insert_audit_event(conn)
    insert_thesis(conn)
    insert_forecast(conn)
    insert_forecast_outcome(conn)
    insert_snapshot(conn)
    insert_decision(conn)
    insert_decision_tag(conn)
    insert_outcome(conn)
    insert_source(conn)
    insert_edge(conn)
    insert_position_event(conn)
    insert_forecast_score(conn)
    insert_signal(conn)
