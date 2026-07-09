from __future__ import annotations

import json
import sqlite3

import pytest

from trade_trace.contracts.tool_registry import ToolContext
from trade_trace.reports.lifecycle import derive_lifecycle_cases
from trade_trace.reports.tool_handlers.lifecycle_agent import _report_lifecycle
from trade_trace.storage.paths import db_path
from trade_trace.tools.errors import ToolError


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
        # The playbook_version chain referenced by the adherence decisions
        # must exist before those decisions are inserted (a non-NULL
        # decisions.playbook_version_id is FK-enforced at insert time by
        # migration 030 / trg_decisions_playbook_version_id_exists).
        conn.execute(
            "INSERT INTO playbooks VALUES (?,?,?,?,?,?,?)",
            ("pb", "pb", None, None, "{}", "2026-01-01T00:00:00Z", "test"),
        )
        conn.execute(
            "INSERT INTO memory_nodes (id,node_type,body,meta_json,valid_from,created_at,actor_id) VALUES (?,?,?,?,?,?,?)",
            ("rule", "playbook_rule", "rule", "{}", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "test"),
        )
        conn.execute(
            "INSERT INTO memory_nodes (id,node_type,body,meta_json,valid_from,created_at,actor_id) VALUES (?,?,?,?,?,?,?)",
            ("refl", "reflection", "reflected", "{}", "2026-01-12T00:00:00Z", "2026-01-12T00:00:00Z", "test"),
        )
        conn.execute(
            "INSERT INTO playbook_versions VALUES (?,?,?,?,?,?,?,?,?)",
            ("pv", "pb", 1, None, "refl", None, "{}", "2026-01-01T00:00:00Z", "test"),
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
        conn.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?,?,?,?)", ("e-refl", "memory_node", "refl", "decision", "d-reflected", "about", None, "{}", "2026-01-12T00:01:00Z", "test"))
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


def _insert_market(conn: sqlite3.Connection, market_id: str, close_at: str | None, state: str) -> None:
    # markets.id is the instrument_id.
    conn.execute(
        """
        INSERT INTO markets (id, source, external_id, title, question, url, state, mechanism,
                             bound_via, opened_at, close_at, venue_metadata_json, metadata_json,
                             created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (market_id, "polymarket", market_id, "m", "m?", "http://x", state, "clob", "adapter",
         "2026-01-01T00:00:00Z", close_at, "{}", "{}", "2026-01-01T00:00:00Z", "test"),
    )


def _insert_null_resolution_forecast(conn: sqlite3.Connection, forecast_id: str) -> None:
    conn.execute(
        """
        INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text,
                               scoring_support, scoring_state, metadata_json, created_at, actor_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (forecast_id, "th", "binary", None, "yes", "caller supplies outcome", "supported", "pending", "{}", "2026-01-01T00:03:00Z", "test"),
    )


def test_null_resolution_at_forecast_stays_open_on_demonstrably_live_market(home):
    # trade-trace-fe2f: resolution_at IS NULL alone must not force pending_review
    # when the linked market is still trading (state='open', close_at in the
    # future). The forecast stays 'open' so no spurious resolve obligation fires.
    with _conn(home) as conn:
        _seed_base(conn)
        _insert_market(conn, "inst", close_at="2026-07-31T00:00:00Z", state="open")
        _insert_null_resolution_forecast(conn, "fc-live")
        cases = derive_lifecycle_cases(conn, as_of="2026-01-20T00:00:00Z")

    case = _case(cases, "derived:forecast:fc-live:lifecycle")
    assert case["state"] == "open"
    assert "resolution_at_missing" not in case["reason_codes"]


def test_null_resolution_at_forecast_is_pending_review_when_market_not_live(home):
    # Boundary cases that MUST keep the missing-horizon review obligation
    # (preserving trade-trace-ptyi): no market row, a past close_at, and a
    # non-open state each leave resolution_at_missing -> pending_review intact.
    with _conn(home) as conn:
        _seed_base(conn)
        _insert_null_resolution_forecast(conn, "fc-no-market")  # inst has no market row here

        # Separate instruments/theses for the other two boundary forecasts.
        conn.execute("INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)", ("inst-past", "ven", "I", "equity", "{}", "2026-01-01T00:00:00Z", "test"))
        conn.execute("INSERT INTO theses (id, instrument_id, side, body, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)", ("th-past", "inst-past", "long", "b", "{}", "2026-01-01T00:01:00Z", "test"))
        _insert_market(conn, "inst-past", close_at="2026-01-05T00:00:00Z", state="open")  # close_at in the past
        conn.execute("INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text, scoring_support, scoring_state, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("fc-past", "th-past", "binary", None, "yes", "r", "supported", "pending", "{}", "2026-01-01T00:03:00Z", "test"))

        conn.execute("INSERT INTO instruments (id, venue_id, title, asset_class, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)", ("inst-res", "ven", "I", "equity", "{}", "2026-01-01T00:00:00Z", "test"))
        conn.execute("INSERT INTO theses (id, instrument_id, side, body, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?)", ("th-res", "inst-res", "long", "b", "{}", "2026-01-01T00:01:00Z", "test"))
        _insert_market(conn, "inst-res", close_at="2026-07-31T00:00:00Z", state="resolving")  # not open
        conn.execute("INSERT INTO forecasts (id, thesis_id, kind, resolution_at, yes_label, resolution_rule_text, scoring_support, scoring_state, metadata_json, created_at, actor_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("fc-res", "th-res", "binary", None, "yes", "r", "supported", "pending", "{}", "2026-01-01T00:03:00Z", "test"))

        cases = derive_lifecycle_cases(conn, as_of="2026-01-20T00:00:00Z")

    for fid in ("fc-no-market", "fc-past", "fc-res"):
        case = _case(cases, f"derived:forecast:{fid}:lifecycle")
        assert case["state"] == "pending_review", fid
        assert "resolution_at_missing" in case["reason_codes"], fid


def _report_env(home, args):
    payload = {"home": str(home), **args}
    ctx = ToolContext(
        tool="internal.lifecycle",
        actor_id="agent:test",
        request_id="internal-lifecycle-test",
        raw_args=payload,
    )
    try:
        return {"ok": True, "data": _report_lifecycle(payload, ctx), "meta_hints": ctx.meta_hints}
    except ToolError as exc:
        return {
            "ok": False,
            "error": {
                "code": exc.code.value,
                "message": exc.message,
                "details": exc.details,
            },
        }


def _report(home, args):
    env = _report_env(home, args)
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


def test_report_lifecycle_paginates_with_limit_and_stable_cursor(home):
    """trade-trace-hv19: report.lifecycle must page (limit + cursor + next_cursor,
    mirroring report.open_positions) so a populated journal stays under the MCP
    token cap, while summary metrics report full-set totals."""
    with _conn(home) as conn:
        _seed_base(conn)
        for i in range(5):
            _insert_decision(conn, f"d-{i}", "hold", f"2026-01-01T00:0{i}:00Z")

    # Six total cases: 5 decisions + the seeded forecast `fc`.
    first = _report(home, {"as_of": "2026-01-20T00:00:00Z", "limit": 2})
    assert first["summary"]["metrics"]["case_count"] == 6  # full-set total, not page
    assert first["summary"]["metrics"]["returned_count"] == 2
    assert len(first["lifecycle_cases"]) == 2
    assert len(first["groups"]) == 2
    assert first["truncated"] is True
    assert first["next_cursor"]

    # groups no longer echoes the full per-group filter (the double-serialization
    # bloat hv19 flagged); the normalized filter lives once in summary.filter.
    assert "filter" not in first["groups"][0]
    assert "filter" in first["summary"]

    # Walk the cursor: each page is disjoint and stable; the union covers all.
    seen = [c["case_id"] for c in first["lifecycle_cases"]]
    cursor = first["next_cursor"]
    pages = 1
    while cursor:
        nxt = _report(home, {"as_of": "2026-01-20T00:00:00Z", "limit": 2, "cursor": cursor})
        page_ids = [c["case_id"] for c in nxt["lifecycle_cases"]]
        assert not set(page_ids) & set(seen)  # no overlap across pages
        seen.extend(page_ids)
        cursor = nxt["next_cursor"]
        pages += 1
        assert pages <= 6  # guard against cursor non-advance
    assert len(seen) == 6
    # The cursor walk reproduces the report's own stable emission order exactly
    # (a single large-limit pull returns the same sequence the pages concatenate
    # to), i.e. paging is order-stable and lossless.
    whole = _report(home, {"as_of": "2026-01-20T00:00:00Z", "limit": 500})
    assert [c["case_id"] for c in whole["lifecycle_cases"]] == seen


def test_report_lifecycle_rejects_invalid_limit_and_cursor(home):
    with _conn(home) as conn:
        _seed_base(conn)

    bad_limit = _report_env(home, {"limit": 0})
    assert bad_limit["ok"] is False
    assert "limit" in bad_limit["error"]["message"]

    bad_cursor = _report_env(home, {"cursor": "!!not-base64!!"})
    assert bad_cursor["ok"] is False


@pytest.mark.parametrize("bad_value", [-1, True, 1.5])
def test_report_lifecycle_rejects_invalid_stale_threshold(home, bad_value):
    """trade-trace-upl2: stale_threshold_days must be a non-negative *integer*.
    A negative int (-1), a bool (True — `isinstance(True, int)` is True in
    Python, so the guard must exclude bool explicitly or it silently coerces to
    1), and a non-integer float (1.5) must each raise VALIDATION_ERROR rather
    than being accepted, so an agent passing a malformed threshold gets a clear
    error instead of a silently wrong staleness window."""
    with _conn(home) as conn:
        _seed_base(conn)

    env = _report_env(home, {"stale_threshold_days": bad_value})

    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR", env["error"]
    assert env["error"]["details"]["field"] == "stale_threshold_days", env["error"]


def test_report_lifecycle_status_alias(home):
    with _conn(home) as conn:
        _seed_base(conn)
        _insert_decision(conn, "d-stale", "hold", "2026-01-01T00:04:00Z")

    data = _report(home, {"as_of": "2026-01-20T00:00:00Z", "status": "stale", "stale_threshold_days": 14})
    assert [case["state"] for case in data["lifecycle_cases"]] == ["stale"]

def test_report_lifecycle_invalid_state_error_lists_allowed_values(home):
    """An unsupported `states` value must surface the allowed set, not just echo
    the bad value (AX dogfood: enum-rejection errors should be self-documenting
    so a bot need not guess valid values by trial-and-error)."""
    with _conn(home) as conn:
        _seed_base(conn)

    env = _report_env(home, {"states": ["active"]})

    assert env["ok"] is False
    message = env["error"]["message"]
    assert "active" in message
    # The allowed enum members must appear so the caller can self-correct.
    for allowed in ("open", "pending_review", "scored", "closed"):
        assert allowed in message


def test_report_lifecycle_due_count_excludes_future_due_at(home):
    """AX dogfood (AX-036): summary.metrics.due_count must count only cases that
    are actually due as of the read boundary (due_at <= as_of), not every case
    that merely *has* a due_at. A forecast whose resolution_at is still in the
    future is pending, not due — counting it as "due" misreads as an actionable
    obligation hours early, and is the inverse of report.work_queue (which omits
    future-due forecasts entirely). Mirrors watchlist.overdue_count semantics."""
    with _conn(home) as conn:
        _seed_base(conn)  # forecast fc: resolution_at=2026-01-10, scoring pending

    # as_of BEFORE the forecast's resolution_at: the case exists but is not yet due.
    before_due = _report(home, {
        "as_of": "2026-01-05T00:00:00Z",
        "filter": {"instrument": {"instrument_id": ["inst"]}},
    })
    fc_case = next(c for c in before_due["lifecycle_cases"] if "fc" in c["record_ids"].get("forecasts", []))
    assert fc_case["due_at"] == "2026-01-10T00:00:00Z"  # future relative to as_of
    assert before_due["summary"]["metrics"]["due_count"] == 0

    # as_of AFTER the resolution_at: the same case is now genuinely due.
    after_due = _report(home, {
        "as_of": "2026-01-20T00:00:00Z",
        "filter": {"instrument": {"instrument_id": ["inst"]}},
    })
    assert after_due["summary"]["metrics"]["due_count"] == 1


def test_parse_ts_treats_naive_iso_as_utc_not_local():
    """trade-trace-nq8x: a naive ISO string used to pass through
    `astimezone(UTC)`, which on Python 3.11+ first interprets naive
    datetimes as the server's local time. The lifecycle parser must
    treat naive inputs as UTC, matching strategy_health._parse_ts."""
    from datetime import UTC, datetime

    from trade_trace.reports.lifecycle import _parse_ts

    naive = _parse_ts("2026-01-15T12:00:00")
    expected = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    assert naive == expected, naive
    assert _parse_ts("2026-01-15T12:00:00Z") == expected
    assert _parse_ts("2026-01-15T07:00:00-05:00") == expected
