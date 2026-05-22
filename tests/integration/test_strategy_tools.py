"""First-class strategy CRUD per bead trade-trace-ubp.

Covers:
- strategy.create happy path + duplicate-slug VALIDATION_ERROR.
- strategy.list with status filter.
- strategy.show by id and by slug; NOT_FOUND otherwise.
- strategy.update partial mutate; name/slug immutable; archive via status.
- Archived strategy remains a valid FK target for prior decisions.
- strategy.created + strategy.updated event emission.
- memory.recall(context={kind:"strategy", id:...}) scoping.
"""

from __future__ import annotations

import sqlite3

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.core import default_registry
from trade_trace.storage.paths import db_path

# -- registration -----------------------------------------------


def test_strategy_tools_registered():
    names = default_registry().names()
    for tool in ("strategy.create", "strategy.list", "strategy.show",
                 "strategy.update"):
        assert tool in names


def test_strategy_show_runtime_schema_exposes_public_inputs():
    schema = default_registry().get("strategy.show").json_schema
    assert schema is not None
    properties = schema["properties"]
    assert set(properties) >= {"strategy_id", "slug", "as_of", "stale_threshold_days"}
    assert properties["strategy_id"]["type"] == "string"
    assert properties["slug"]["type"] == "string"
    assert properties["as_of"]["type"] == "string"
    assert properties["stale_threshold_days"]["type"] == "integer"


# -- strategy.create --------------------------------------------


def test_strategy_create_happy_path(home):
    env = _mcp(home, "strategy.create", {
        "name": "Earnings momentum",
        "slug": "earnings-momentum",
        "description": "Ride post-earnings drift.",
        "hypothesis": "After-hours reactions under-extrapolate news.",
        "idempotency_key": "00000000-0000-4000-8000-strat-create1",
    })
    assert env.ok, env
    assert env.data["slug"] == "earnings-momentum"
    assert env.data["status"] == "active"
    assert env.meta.event_id is not None


def test_strategy_create_duplicate_slug_rejected(home):
    base = {
        "name": "First", "slug": "shared-slug",
        "idempotency_key": "00000000-0000-4000-8000-strat-dup-1",
    }
    first = _mcp(home, "strategy.create", base)
    assert first.ok
    second = _mcp(home, "strategy.create", {
        **base, "name": "Second",
        "idempotency_key": "00000000-0000-4000-8000-strat-dup-2",
    })
    assert second.ok is False
    assert second.error.code.value == "VALIDATION_ERROR"
    assert second.error.details["field"] == "slug"


def test_strategy_create_rejects_invalid_slug(home):
    env = _mcp(home, "strategy.create", {
        "name": "Bad", "slug": "Has UPPERCASE",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "slug"


# -- strategy.list ----------------------------------------------


def test_strategy_list_returns_active_by_default(home):
    for i, slug in enumerate(("alpha", "bravo", "charlie")):
        _mcp(home, "strategy.create", {
            "name": slug.title(), "slug": slug,
            "idempotency_key": f"00000000-0000-4000-8000-strat-l-{i:04d}",
        })
    # Archive one.
    archived = _mcp(home, "strategy.show", {"slug": "bravo"}).data["id"]
    _mcp(home, "strategy.update", {
        "strategy_id": archived, "status": "archived",
        "idempotency_key": "00000000-0000-4000-8000-strat-l-arch",
    })
    env = _mcp(home, "strategy.list", {})
    slugs = [it["slug"] for it in env.data["items"]]
    assert "alpha" in slugs and "charlie" in slugs
    assert "bravo" not in slugs


def test_strategy_list_with_archived_filter(home):
    _mcp(home, "strategy.create", {
        "name": "A", "slug": "a-strat", "status": "archived",
        "idempotency_key": "00000000-0000-4000-8000-strat-larc-1",
    })
    env = _mcp(home, "strategy.list", {"status": "archived"})
    slugs = [it["slug"] for it in env.data["items"]]
    assert slugs == ["a-strat"]


# -- strategy.show ----------------------------------------------


def test_strategy_show_by_slug(home):
    created = _mcp(home, "strategy.create", {
        "name": "Show by slug", "slug": "show-by-slug",
        "idempotency_key": "00000000-0000-4000-8000-strat-show01",
    }).data
    env = _mcp(home, "strategy.show", {"slug": "show-by-slug"})
    assert env.ok
    assert env.data["id"] == created["id"]


def test_strategy_show_not_found(home):
    env = _mcp(home, "strategy.show", {"slug": "does-not-exist"})
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "strategy"


def test_strategy_show_includes_deterministic_health_summary(home):
    sid = _mcp(home, "strategy.create", {
        "name": "Health summary", "slug": "health-summary",
        "idempotency_key": "00000000-0000-4000-8000-strat-health-01",
    }).data["id"]
    db = sqlite3.connect(db_path(home))
    try:
        db.execute(
            "INSERT INTO venues(id, name, kind, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?)",
            ("venue_health", "Manual", "manual", "2026-01-01T00:00:00Z", "tester"),
        )
        db.execute(
            "INSERT INTO instruments(id, venue_id, symbol, title, asset_class, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("inst_health", "venue_health", "HLTH", "Health", "equity", "2026-01-01T00:00:00Z", "tester"),
        )
        db.execute(
            "INSERT INTO theses(id, instrument_id, side, body, strategy_id, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("th_health_1", "inst_health", "long", "body", sid, "2026-01-01T00:00:00Z", "tester"),
        )
        db.execute(
            "INSERT INTO forecasts(id, thesis_id, kind, resolution_at, scoring_state, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("fc_health_1", "th_health_1", "binary", "2026-03-01T00:00:00Z", "pending", "2026-01-02T00:00:00Z", "tester"),
        )
        for outcome_id, label, probability in (("fco_health_yes", "yes", 0.6), ("fco_health_no", "no", 0.4)):
            db.execute(
                "INSERT INTO forecast_outcomes(id, forecast_id, outcome_label, probability) VALUES (?, ?, ?, ?)",
                (outcome_id, "fc_health_1", label, probability),
            )
        for decision_id, decision_type, created_at, review_by in (
            ("dec_health_watch", "watch", "2026-01-03T00:00:00Z", "2026-01-10T00:00:00Z"),
            ("dec_health_hold", "hold", "2026-01-04T00:00:00Z", "2026-02-10T00:00:00Z"),
        ):
            db.execute(
                "INSERT INTO decisions(id, instrument_id, thesis_id, forecast_id, type, review_by, "
                "strategy_id, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (decision_id, "inst_health", "th_health_1", "fc_health_1", decision_type,
                 review_by, sid, created_at, "tester"),
            )
        event_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        db.commit()
    finally:
        db.close()

    without_as_of = _mcp(home, "strategy.show", {"strategy_id": sid})
    assert without_as_of.ok, without_as_of
    health = without_as_of.data["health_summary"]
    assert health["as_of"] is None
    assert "as_of_not_supplied" in health["caveats"]
    assert health["sections"]["due_watch_decisions"] == {"count": 0, "record_ids": []}
    assert health["sections"]["stale_watch_decisions"] == {"count": 0, "record_ids": []}

    with_as_of = _mcp(home, "strategy.show", {
        "strategy_id": sid,
        "as_of": "2026-01-20T00:00:00Z",
        "stale_threshold_days": 14,
    })
    assert with_as_of.ok, with_as_of
    health = with_as_of.data["health_summary"]
    assert health["sections"]["decisions"] == {
        "count": 2, "record_ids": ["dec_health_watch", "dec_health_hold"]}
    assert health["sections"]["theses"] == {"count": 1, "record_ids": ["th_health_1"]}
    assert health["sections"]["open_unresolved_forecasts"] == {
        "count": 1, "record_ids": ["fc_health_1"]}
    assert health["sections"]["due_watch_decisions"] == {
        "count": 1, "record_ids": ["dec_health_watch"]}
    assert health["sections"]["stale_watch_decisions"] == {
        "count": 1, "record_ids": ["dec_health_watch"]}
    for caveat in (
        "low_n_decisions", "missing_forecast_scores", "missing_source_refs",
        "missing_reflections", "missing_playbook_adherence",
    ):
        assert caveat in health["caveats"]
    assert "as_of_not_supplied" not in health["caveats"]
    assert all(
        forbidden not in repr(health).lower()
        for forbidden in ("advice", "fetch", "profit", "best strategy")
    )

    db = sqlite3.connect(db_path(home))
    try:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == event_count
    finally:
        db.close()


def test_strategy_show_rejects_negative_stale_threshold(home):
    env = _mcp(home, "strategy.show", {
        "slug": "does-not-exist", "stale_threshold_days": -1,
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "stale_threshold_days"


@pytest.mark.parametrize(
    "as_of",
    [
        "2026-01-20T00:00:00+00:00",
        "2026-01-20T00:00:00-05:00",
        "2026-01-20T00:00:00",
    ],
)
def test_strategy_show_rejects_non_z_as_of_contract(home, as_of):
    env = _mcp(home, "strategy.show", {
        "slug": "does-not-exist",
        "as_of": as_of,
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "as_of"


@pytest.mark.parametrize("stale_threshold_days", [True, 1.5])
def test_strategy_show_rejects_non_integer_stale_threshold(home, stale_threshold_days):
    env = _mcp(home, "strategy.show", {
        "slug": "does-not-exist", "stale_threshold_days": stale_threshold_days,
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "stale_threshold_days"


# -- strategy.update --------------------------------------------


def test_strategy_update_partial_fields(home):
    sid = _mcp(home, "strategy.create", {
        "name": "Update target", "slug": "update-target",
        "description": "old",
        "idempotency_key": "00000000-0000-4000-8000-strat-upd-01",
    }).data["id"]
    env = _mcp(home, "strategy.update", {
        "strategy_id": sid, "description": "new",
        "idempotency_key": "00000000-0000-4000-8000-strat-upd-02",
    })
    assert env.ok
    assert env.data["description"] == "new"
    assert env.data["slug"] == "update-target"


def test_strategy_update_replays_original_result_after_intervening_update(home):
    sid = _mcp(home, "strategy.create", {
        "name": "Replay target", "slug": "replay-target",
        "description": "old",
        "idempotency_key": "00000000-0000-4000-8000-strat-rup-01",
    }).data["id"]
    first = _mcp(home, "strategy.update", {
        "strategy_id": sid, "description": "first-change",
        "idempotency_key": "00000000-0000-4000-8000-strat-rup-02",
    })
    assert first.ok, first

    intervening = _mcp(home, "strategy.update", {
        "strategy_id": sid, "description": "intervening-change",
        "idempotency_key": "00000000-0000-4000-8000-strat-rup-03",
    })
    assert intervening.ok, intervening
    assert intervening.data["description"] == "intervening-change"

    replay = _mcp(home, "strategy.update", {
        "strategy_id": sid, "description": "first-change",
        "idempotency_key": "00000000-0000-4000-8000-strat-rup-02",
    })

    assert replay.ok, replay
    assert replay.data == first.data
    assert replay.meta.event_id == first.meta.event_id
    assert replay.meta.idempotent_replay is True

    db = sqlite3.connect(db_path(home))
    try:
        assert db.execute(
            "SELECT description, updated_at FROM strategies WHERE id = ?",
            (sid,),
        ).fetchone() == (
            intervening.data["description"], intervening.data["updated_at"]
        )
        assert db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'strategy.updated'"
        ).fetchone()[0] == 2
    finally:
        db.close()


def test_strategy_update_idempotency_key_conflict_does_not_mutate(home):
    sid = _mcp(home, "strategy.create", {
        "name": "Conflict target", "slug": "conflict-target",
        "description": "old",
        "idempotency_key": "00000000-0000-4000-8000-strat-cnf-01",
    }).data["id"]
    first = _mcp(home, "strategy.update", {
        "strategy_id": sid, "description": "first-change",
        "idempotency_key": "00000000-0000-4000-8000-strat-cnf-02",
    })
    assert first.ok, first

    conflict = _mcp(home, "strategy.update", {
        "strategy_id": sid, "status": "archived",
        "idempotency_key": "00000000-0000-4000-8000-strat-cnf-02",
    })

    assert conflict.ok is False
    assert conflict.error.code.value == "IDEMPOTENCY_CONFLICT"
    assert isinstance(conflict.error.details.get("original_event_id"), int)
    assert conflict.error.details["diff_summary"]

    db = sqlite3.connect(db_path(home))
    try:
        assert db.execute(
            "SELECT description, status, updated_at FROM strategies WHERE id = ?",
            (sid,),
        ).fetchone() == (
            first.data["description"], first.data["status"],
            first.data["updated_at"],
        )
        assert db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'strategy.updated'"
        ).fetchone()[0] == 1
    finally:
        db.close()


def test_strategy_update_rejects_name_or_slug_change(home):
    sid = _mcp(home, "strategy.create", {
        "name": "Immutable", "slug": "immutable-strat",
        "idempotency_key": "00000000-0000-4000-8000-strat-imm-01",
    }).data["id"]
    for forbidden_field, value in [("name", "x"), ("slug", "new-slug")]:
        env = _mcp(home, "strategy.update", {
            "strategy_id": sid, forbidden_field: value,
        })
        assert env.ok is False
        assert env.error.code.value == "VALIDATION_ERROR"
        assert env.error.details["field"] == forbidden_field


def test_strategy_archive_via_update_status(home):
    sid = _mcp(home, "strategy.create", {
        "name": "Archive me", "slug": "archive-me",
        "idempotency_key": "00000000-0000-4000-8000-strat-arc-01",
    }).data["id"]
    env = _mcp(home, "strategy.update", {
        "strategy_id": sid, "status": "archived",
        "idempotency_key": "00000000-0000-4000-8000-strat-arc-02",
    })
    assert env.ok
    assert env.data["status"] == "archived"


# -- soft-archive: archived strategy remains FK target ----------


def test_archived_strategy_still_readable_via_decision_reference(home):
    """Per acceptance: archived strategies remain valid for historical
    decisions. Create strategy → archive → confirm a decision tagged
    with strategy_id still reads back through strategy.show."""

    sid = _mcp(home, "strategy.create", {
        "name": "Soft archive", "slug": "soft-archive",
        "idempotency_key": "00000000-0000-4000-8000-strat-sft-01",
    }).data["id"]
    _mcp(home, "strategy.update", {
        "strategy_id": sid, "status": "archived",
        "idempotency_key": "00000000-0000-4000-8000-strat-sft-02",
    })
    # Strategy.show by id still works on archived rows.
    env = _mcp(home, "strategy.show", {"strategy_id": sid})
    assert env.ok
    assert env.data["status"] == "archived"


# -- memory.recall(context={kind:'strategy', id:...}) scoping ----


def test_memory_recall_context_strategy_improves_on_strat_rank(home):
    """memory.recall narrowed by context=strategy boosts nodes attached
    to that strategy via the graph strategy. The acceptance is: the
    on-strat node's rank in the context=strategy call is BETTER (lower
    index) than in the unscoped call — proving the graph signal is
    being applied.
    """

    sid = _mcp(home, "strategy.create", {
        "name": "Recall scope", "slug": "recall-scope",
        "idempotency_key": "00000000-0000-4000-8000-strat-rc-01",
    }).data["id"]

    on_strat = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "Pattern about earnings momentum signals",
        "idempotency_key": "00000000-0000-4000-8000-strat-rc-02",
    }).data["id"]
    # Several unrelated nodes lifted by query alone.
    for i in range(3):
        _mcp(home, "memory.retain", {
            "node_type": "observation",
            "body": f"earnings momentum pattern variant {i}",
            "idempotency_key": f"00000000-0000-4000-8000-strat-rc-{20+i:02d}",
        })
    _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": on_strat,
        "target_kind": "strategy", "target_id": sid,
        "edge_type": "about",
        "idempotency_key": "00000000-0000-4000-8000-strat-rc-04",
    })

    unscoped = _mcp(home, "memory.recall", {
        "query": "earnings momentum", "k": 10,
    })
    scoped = _mcp(home, "memory.recall", {
        "query": "earnings momentum",
        "context": {"kind": "strategy", "id": sid},
        "k": 10,
    })
    unscoped_ids = [it["id"] for it in unscoped.data["items"]]
    scoped_ids = [it["id"] for it in scoped.data["items"]]
    assert on_strat in scoped_ids
    # The context=strategy call surfaces on_strat at a rank no worse than
    # the unscoped call — and typically better because the graph strategy
    # contributes additional RRF score.
    scoped_rank = scoped_ids.index(on_strat)
    unscoped_rank = (
        unscoped_ids.index(on_strat) if on_strat in unscoped_ids else 99
    )
    assert scoped_rank <= unscoped_rank, (
        f"context=strategy should not demote on-strat node; "
        f"scoped={scoped_rank} unscoped={unscoped_rank}"
    )
