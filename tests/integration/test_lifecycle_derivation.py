from __future__ import annotations

import json
import sqlite3

from trade_trace.core import default_registry, dispatch
from trade_trace.reports.lifecycle import derive_lifecycle_cases
from trade_trace.storage.paths import db_path


def _conn(home):
    return sqlite3.connect(db_path(home))


def _seed_base(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO venues VALUES (?,?,?,?,?,?)", ("ven", "Venue", "manual", "{}", "2026-01-01T00:00:00Z", "test"))
    conn.execute(
        "INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)",
        ("inst", "ven", "Instrument", "equity", "{}", "2026-01-01T00:00:00Z", "test"),
    )
    conn.execute(
        """
        INSERT INTO theses (id, instrument_id, side, body, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?)
        """,
        ("th", "inst", "long", "body", "{}", "2026-01-01T00:01:00Z", "test"),
    )
    conn.execute(
        """
        INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text,
                               scoring_support, scoring_state, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "fc",
            "th",
            "binary",
            "2026-01-10T00:00:00Z",
            "yes",
            "caller supplies outcome",
            "supported",
            "pending",
            "{}",
            "2026-01-01T00:02:00Z",
            "test",
        ),
    )


def _insert_decision(
    conn: sqlite3.Connection,
    decision_id: str,
    decision_type: str,
    created_at: str,
    *,
    review_by: str | None = None,
    forecast_id: str | None = None,
    thesis_id: str | None = "th",
    playbook_version_id: str | None = None,
    metadata: dict | None = None,
    strategy_id: str | None = None,
    run_id: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO decisions (id, instrument_id, thesis_id, forecast_id, type, reason,
                               playbook_version_id, review_by, strategy_id, run_id, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            decision_id,
            "inst",
            thesis_id,
            forecast_id,
            decision_type,
            "because",
            playbook_version_id,
            review_by,
            strategy_id,
            run_id,
            json.dumps(metadata or {}),
            created_at,
            "test",
        ),
    )


def _case(cases: list[dict], case_id: str) -> dict:
    return next(c for c in cases if c["case_id"] == case_id)


def test_lifecycle_derives_pending_stale_closed_superseded_and_stable_order(home):
    with _conn(home) as conn:
        _seed_base(conn)
        _insert_decision(conn, "d-watch-due", "watch", "2026-01-01T00:03:00Z", review_by="2026-01-05T00:00:00Z")
        _insert_decision(conn, "d-hold-stale", "hold", "2026-01-01T00:04:00Z")
        _insert_decision(conn, "d-skip", "skip", "2026-01-20T00:00:00Z")
        _insert_decision(conn, "d-watch-super", "watch", "2026-01-21T00:00:00Z")
        conn.execute(
            "INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "e-super",
                "decision",
                "d-new",
                "decision",
                "d-watch-super",
                "supersedes",
                None,
                "{}",
                "2026-01-22T00:00:00Z",
                "test",
            ),
        )

        cases = derive_lifecycle_cases(conn, as_of="2026-01-20T00:00:00Z", stale_threshold_days=14)

    assert [c["case_id"] for c in cases] == sorted([c["case_id"] for c in cases], key=lambda cid: _case(cases, cid)["timestamps"]["created_at"])
    assert _case(cases, "derived:decision:d-watch-due:lifecycle")["state"] == "pending_review"
    assert _case(cases, "derived:decision:d-hold-stale:lifecycle")["state"] == "stale"
    assert _case(cases, "derived:decision:d-skip:lifecycle")["state"] == "closed"
    assert _case(cases, "derived:decision:d-watch-super:lifecycle")["state"] == "superseded"


def test_lifecycle_derives_outcome_score_reflection_and_adherence_states(home):
    with _conn(home) as conn:
        _seed_base(conn)
        conn.execute(
            """
            INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text,
                                   scoring_support, scoring_state, metadata_json, created_at, actor_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "fc-outcome",
                "th",
                "binary",
                "2026-01-10T00:00:00Z",
                "yes",
                "caller supplies outcome",
                "supported",
                "pending",
                "{}",
                "2026-01-01T00:02:30Z",
                "test",
            ),
        )
        _insert_decision(conn, "d-outcome", "watch", "2026-01-02T00:00:00Z")
        _insert_decision(conn, "d-score", "watch", "2026-01-02T00:01:00Z", forecast_id="fc")
        _insert_decision(conn, "d-reflected", "hold", "2026-01-02T00:02:00Z")
        _insert_decision(conn, "d-reflection-due", "review", "2026-01-02T00:02:30Z", review_by="2026-01-03T00:00:00Z")
        _insert_decision(conn, "d-adh-due", "watch", "2026-01-02T00:03:00Z", playbook_version_id="pv")
        _insert_decision(conn, "d-adh-recorded", "watch", "2026-01-02T00:04:00Z", playbook_version_id="pv")
        conn.execute(
            "INSERT INTO outcomes (id, instrument_id, resolved_at, outcome_label, status, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?)",
            ("out", "inst", "2026-01-11T00:00:00Z", "yes", "resolved_final", "{}", "2026-01-11T00:01:00Z", "test"),
        )
        conn.execute("INSERT INTO forecast_scores VALUES (?,?,?,?,?,?,?,?)", ("score", "fc", "out", "brier", 0.1, "2026-01-11T00:02:00Z", "test", "{}"))
        conn.execute(
            "INSERT INTO memory_nodes (id,node_type,body,meta_json,valid_from,created_at,actor_id) VALUES (?,?,?,?,?,?,?)",
            ("refl", "reflection", "reflected", "{}", "2026-01-12T00:00:00Z", "2026-01-12T00:00:00Z", "test"),
        )
        conn.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)", ("e-refl", "memory_node", "refl", "decision", "d-reflected", "about", None, "{}", "2026-01-12T00:01:00Z", "test"))
        conn.execute(
            "INSERT INTO playbooks VALUES (?,?,?,?,?,?,?)",
            ("pb", "pb", None, None, "{}", "2026-01-01T00:00:00Z", "test"),
        )
        conn.execute(
            "INSERT INTO memory_nodes (id,node_type,body,meta_json,valid_from,created_at,actor_id) VALUES (?,?,?,?,?,?,?)",
            ("rule", "playbook_rule", "rule", "{}", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "test"),
        )
        conn.execute(
            "INSERT INTO playbook_versions VALUES (?,?,?,?,?,?,?,?,?)",
            ("pv", "pb", 1, None, "refl", None, "{}", "2026-01-01T00:00:00Z", "test"),
        )
        conn.execute(
            "INSERT INTO decision_playbook_rules VALUES (?,?,?,?,?,?,?,?,?)",
            ("dpr", "d-adh-recorded", "pv", "rule", "followed", "ok", "{}", "2026-01-02T00:05:00Z", "test"),
        )

        cases = derive_lifecycle_cases(conn, as_of="2026-01-13T00:00:00Z")

    assert _case(cases, "derived:decision:d-outcome:lifecycle")["state"] == "outcome_recorded"
    assert {"kind": "outcome", "id": "out"} in _case(cases, "derived:decision:d-outcome:lifecycle")["source_refs"]
    assert _case(cases, "derived:decision:d-score:lifecycle")["state"] == "scored"
    assert {"kind": "forecast_score", "id": "score"} in _case(cases, "derived:decision:d-score:lifecycle")["source_refs"]
    assert {"kind": "outcome", "id": "out"} in _case(cases, "derived:decision:d-score:lifecycle")["source_refs"]
    assert _case(cases, "derived:decision:d-reflected:lifecycle")["state"] == "reflected"
    assert _case(cases, "derived:decision:d-reflection-due:lifecycle")["state"] == "reflection_due"
    assert _case(cases, "derived:decision:d-adh-due:lifecycle")["state"] == "adherence_due"
    assert _case(cases, "derived:decision:d-adh-recorded:lifecycle")["state"] == "adherence_recorded"
    assert _case(cases, "derived:forecast:fc:lifecycle")["state"] == "scored"
    assert {"kind": "forecast_score", "id": "score"} in _case(cases, "derived:forecast:fc:lifecycle")["source_refs"]
    assert {"kind": "outcome", "id": "out"} in _case(cases, "derived:forecast:fc:lifecycle")["source_refs"]
    assert _case(cases, "derived:forecast:fc-outcome:lifecycle")["state"] == "outcome_recorded"
    assert {"kind": "outcome", "id": "out"} in _case(cases, "derived:forecast:fc-outcome:lifecycle")["source_refs"]


def test_material_non_action_marker_and_missing_source_caveat(home):
    marker = {"category": "defer", "materiality_reason": "waiting_for_resolution"}
    with _conn(home) as conn:
        _seed_base(conn)
        _insert_decision(
            conn,
            "d-defer",
            "watch",
            "2026-01-02T00:00:00Z",
            review_by="2026-01-03T00:00:00Z",
            metadata={"material_non_action": marker},
        )
        conn.execute(
            "INSERT INTO sources (id,kind,title,stance,metadata_json,created_at,actor_id) VALUES (?,?,?,?,?,?,?)",
            ("src", "note", "src", "supports", "{}", "2026-01-02T00:00:00Z", "test"),
        )
        conn.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)", ("e-src", "source", "src", "decision", "d-defer", "supports", None, "{}", "2026-01-02T00:01:00Z", "test"))

        cases = derive_lifecycle_cases(conn, as_of="2026-01-02T12:00:00Z")

    case = _case(cases, "derived:decision:d-defer:lifecycle")
    assert case["state"] == "open"
    assert case["material_non_action"] == marker
    assert {tuple(ref.items()) for ref in case["source_refs"]} >= {
        (("kind", "source"), ("id", "src")),
        (("kind", "decision"), ("id", "d-defer")),
    }
    assert "missing_source_ref" not in case["caveat_codes"]


def _report(home, args):
    env = dispatch("report.lifecycle", {"home": str(home), **args}, actor_id="agent:test", registry=default_registry()).model_dump(mode="json")
    assert env["ok"], env
    return env["data"]


def test_report_lifecycle_surface_filters_and_links_without_writes(home):
    with _conn(home) as conn:
        _seed_base(conn)
        conn.execute("INSERT INTO strategies(id, name, slug, status, created_at, updated_at, actor_id) VALUES (?,?,?,?,?,?,?)", ("strat-a", "Strategy A", "strat-a", "active", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "test"))
        conn.execute("INSERT INTO strategies(id, name, slug, status, created_at, updated_at, actor_id) VALUES (?,?,?,?,?,?,?)", ("strat-b", "Strategy B", "strat-b", "active", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "test"))
        _insert_decision(conn, "d-a", "watch", "2026-01-01T00:03:00Z", review_by="2026-01-05T00:00:00Z", strategy_id="strat-a", run_id="run-a")
        _insert_decision(conn, "d-b", "hold", "2026-01-02T00:03:00Z", strategy_id="strat-b", run_id="run-b")
        before = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("decisions", "forecasts", "edges", "memory_nodes")}

    data = _report(home, {
        "as_of": "2026-01-20T00:00:00Z",
        "stale_threshold_days": 14,
        "states": ["pending_review"],
        "filter": {
            "strategy": {"strategy_id": "strat-a"},
            "instrument": {"instrument_id": ["inst"]},
            "actors": {"run_id": ["run-a"]},
            "time_window": {"created_at_gte": "2026-01-01T00:00:00Z", "created_at_lt": "2026-01-02T00:00:00Z"},
        },
    })

    assert data["as_of"] == "2026-01-20T00:00:00Z"
    assert data["summary"]["metrics"]["case_count"] == 1
    case = data["lifecycle_cases"][0]
    assert case["case_id"] == "derived:decision:d-a:lifecycle"
    assert case["state"] == case["status"] == "pending_review"
    assert {"kind": "decision", "id": "d-a"} in case["source_refs"]
    assert {"kind": "run", "id": "run-a"} in case["source_refs"]
    assert case["record_ids"]["decisions"] == ["d-a"]
    assert case["record_ids"]["instruments"] == ["inst"]
    assert data["groups"][0]["record_ids"]["decisions"] == ["d-a"]

    data_again = _report(home, {
        "as_of": "2026-01-20T00:00:00Z",
        "stale_threshold_days": 14,
        "states": ["pending_review"],
        "filter": {"strategy": {"strategy_id": "strat-a"}, "instrument": {"instrument_id": ["inst"]}, "actors": {"run_id": ["run-a"]}},
    })
    assert data_again["lifecycle_cases"][0] == case

    with _conn(home) as conn:
        after = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in before}
    assert after == before


def test_report_lifecycle_status_alias_and_schema(home):
    with _conn(home) as conn:
        _seed_base(conn)
        _insert_decision(conn, "d-stale", "hold", "2026-01-01T00:04:00Z")

    data = _report(home, {"as_of": "2026-01-20T00:00:00Z", "status": "stale", "stale_threshold_days": 14})
    assert [case["state"] for case in data["lifecycle_cases"]] == ["stale"]

    schema_env = dispatch("tool.schema", {"tool": "report.lifecycle"}, actor_id="agent:test", registry=default_registry()).model_dump(mode="json")
    assert schema_env["ok"], schema_env
    props = schema_env["data"]["json_schema"]["properties"]
    for key in ("filter", "states", "status", "as_of", "stale_threshold_days"):
        assert key in props
