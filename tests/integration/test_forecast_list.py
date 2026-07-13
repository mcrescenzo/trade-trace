"""`forecast.list` — public read-only forecast enumeration (bead trade-trace-6oob8).

Before this tool, the only read surface that touched forecasts was
`review.bundle`, which walks `decisions.forecast_id` — a forecast with no
linked decision was invisible to any read-only tool. `forecast.list` reads
`forecasts` directly, so enumerating unlinked forecasts is the primary
regression this file guards (test A). It also covers the documented filters
(scoring_state, instrument_id, resolution_before/after) and cursor
pagination, following the `pretrade_intent.list` / `paper_fill.list` test
style (dispatch-based, one DB per test via `tmp_path`).
"""

from __future__ import annotations

import pytest

from trade_trace.core import dispatch


def _call(tool: str, args: dict, *, actor_id: str = "agent:forecast-list"):
    return dispatch(tool, args, actor_id=actor_id)


def _bind_market(home, *, external_id: str, idempotency_key: str) -> str:
    env = _call("market.bind", {
        "home": str(home),
        "source": "polymarket",
        "external_id": external_id,
        "title": f"Will {external_id} happen?",
        "question": f"Will {external_id} happen?",
        "state": "open",
        "mechanism": "clob",
        "bound_via": "manual",
        "idempotency_key": idempotency_key,
    })
    assert env.ok, env
    return env.data["id"]


def _add_forecast(
    home, *, market_id: str, idempotency_key: str,
    resolution_at: str | None = None, p_yes: float = 0.6,
) -> dict:
    args = {
        "home": str(home),
        "market_id": market_id,
        "rationale_body": "Because the local fixture says so.",
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": p_yes},
            {"outcome_label": "no", "probability": 1.0 - p_yes},
        ],
        "idempotency_key": idempotency_key,
    }
    if resolution_at is not None:
        args["resolution_at"] = resolution_at
    env = _call("forecast.add", args)
    assert env.ok, env
    return env.data


def _link_decision(home, *, market_id: str, forecast_id: str, idempotency_key: str) -> str:
    env = _call("decision.add", {
        "home": str(home),
        "type": "watch",
        "instrument_id": market_id,
        "forecast_id": forecast_id,
        "idempotency_key": idempotency_key,
    })
    assert env.ok, env
    return env.data["id"]


def _resolve_final(home, *, market_id: str, resolved_at: str, idempotency_key: str, outcome_label: str = "yes") -> None:
    env = _call("resolution.add", {
        "home": str(home),
        "instrument_id": market_id,
        "resolved_at": resolved_at,
        "outcome_label": outcome_label,
        "status": "resolved_final",
        "confidence": 0.99,
        "idempotency_key": idempotency_key,
    })
    assert env.ok, env


def test_forecast_list_enumerates_forecasts_with_and_without_linked_decisions(tmp_path):
    """The whole point of this tool: an unlinked forecast must be enumerable."""

    home = tmp_path / "home"
    assert _call("journal.init", {"home": str(home)}).ok

    market_linked = _bind_market(home, external_id="ext-linked", idempotency_key="bind-linked")
    forecast_linked = _add_forecast(home, market_id=market_linked, idempotency_key="fc-linked")["id"]
    _link_decision(home, market_id=market_linked, forecast_id=forecast_linked, idempotency_key="dec-linked")

    market_unlinked = _bind_market(home, external_id="ext-unlinked", idempotency_key="bind-unlinked")
    forecast_unlinked = _add_forecast(home, market_id=market_unlinked, idempotency_key="fc-unlinked")["id"]

    listed = _call("forecast.list", {"home": str(home)})
    assert listed.ok, listed
    by_id = {item["id"]: item for item in listed.data["items"]}
    assert listed.data["count"] == 2
    assert {forecast_linked, forecast_unlinked} == set(by_id)

    linked_row = by_id[forecast_linked]
    assert linked_row["linked_decision_count"] == 1
    assert linked_row["has_linked_decision"] is True
    assert linked_row["market_id"] == market_linked
    assert linked_row["instrument_id"] == market_linked
    assert linked_row["scoring_state"] == "pending"

    unlinked_row = by_id[forecast_unlinked]
    assert unlinked_row["linked_decision_count"] == 0
    assert unlinked_row["has_linked_decision"] is False
    assert unlinked_row["snapshot_anchor_id"] is None


def test_forecast_list_is_public_read_only_and_not_frozen():
    from trade_trace.core import (
        EXPERIMENTAL_AUTONOMOUS_OPS,
        EXPERIMENTAL_FROZEN_TOOLS,
        build_registry,
    )

    reg = build_registry()
    entry = reg.get("forecast.list")
    assert entry.is_write is False
    assert entry.catalog_visibility == "public"
    assert "forecast.list" in set(reg.public_names())
    assert "forecast.list" not in EXPERIMENTAL_AUTONOMOUS_OPS
    assert "forecast.list" not in EXPERIMENTAL_FROZEN_TOOLS


def test_forecast_list_instrument_id_filter(tmp_path):
    home = tmp_path / "home"
    assert _call("journal.init", {"home": str(home)}).ok

    market_a = _bind_market(home, external_id="ext-a", idempotency_key="bind-a")
    forecast_a = _add_forecast(home, market_id=market_a, idempotency_key="fc-a")["id"]
    market_b = _bind_market(home, external_id="ext-b", idempotency_key="bind-b")
    _add_forecast(home, market_id=market_b, idempotency_key="fc-b")

    listed = _call("forecast.list", {"home": str(home), "instrument_id": market_a})
    assert listed.ok, listed
    assert [item["id"] for item in listed.data["items"]] == [forecast_a]

    # market_id is an accepted alias for instrument_id.
    listed_alias = _call("forecast.list", {"home": str(home), "market_id": market_a})
    assert listed_alias.ok, listed_alias
    assert [item["id"] for item in listed_alias.data["items"]] == [forecast_a]


def test_forecast_list_resolution_window_filters(tmp_path):
    home = tmp_path / "home"
    assert _call("journal.init", {"home": str(home)}).ok

    market_early = _bind_market(home, external_id="ext-early", idempotency_key="bind-early")
    forecast_early = _add_forecast(
        home, market_id=market_early, idempotency_key="fc-early",
        resolution_at="2026-08-01T00:00:00.000Z",
    )["id"]
    market_late = _bind_market(home, external_id="ext-late", idempotency_key="bind-late")
    forecast_late = _add_forecast(
        home, market_id=market_late, idempotency_key="fc-late",
        resolution_at="2026-09-01T00:00:00.000Z",
    )["id"]

    before = _call("forecast.list", {"home": str(home), "resolution_before": "2026-08-15T00:00:00Z"})
    assert before.ok, before
    assert [item["id"] for item in before.data["items"]] == [forecast_early]

    after = _call("forecast.list", {"home": str(home), "resolution_after": "2026-08-15T00:00:00Z"})
    assert after.ok, after
    assert [item["id"] for item in after.data["items"]] == [forecast_late]


def test_forecast_list_scoring_state_filter_reflects_derived_state_not_raw_column(tmp_path):
    """`forecasts.scoring_state` is append-only and stays 'pending' on disk
    forever; the filter must match the read-time derived state (scored),
    not the stale persisted column."""

    home = tmp_path / "home"
    assert _call("journal.init", {"home": str(home)}).ok

    market_scored = _bind_market(home, external_id="ext-scored", idempotency_key="bind-scored")
    forecast_scored = _add_forecast(home, market_id=market_scored, idempotency_key="fc-scored", p_yes=0.6)["id"]
    _resolve_final(home, market_id=market_scored, resolved_at="2026-07-01T00:00:00Z", idempotency_key="res-scored")

    market_pending = _bind_market(home, external_id="ext-pending", idempotency_key="bind-pending")
    forecast_pending = _add_forecast(home, market_id=market_pending, idempotency_key="fc-pending")["id"]

    scored = _call("forecast.list", {"home": str(home), "scoring_state": "scored"})
    assert scored.ok, scored
    assert [item["id"] for item in scored.data["items"]] == [forecast_scored]
    assert scored.data["items"][0]["scoring_state"] == "scored"

    pending = _call("forecast.list", {"home": str(home), "scoring_state": "pending"})
    assert pending.ok, pending
    assert [item["id"] for item in pending.data["items"]] == [forecast_pending]


def test_forecast_list_rejects_unknown_scoring_state(tmp_path):
    home = tmp_path / "home"
    assert _call("journal.init", {"home": str(home)}).ok
    bad = _call("forecast.list", {"home": str(home), "scoring_state": "not-a-real-state"})
    assert not bad.ok
    assert bad.error.code == "VALIDATION_ERROR"
    assert bad.error.details["field"] == "scoring_state"


def test_forecast_list_rejects_malformed_cursor(tmp_path):
    home = tmp_path / "home"
    assert _call("journal.init", {"home": str(home)}).ok
    bad = _call("forecast.list", {"home": str(home), "cursor": "not-a-valid-cursor!!"})
    assert not bad.ok
    assert bad.error.code == "VALIDATION_ERROR"
    assert bad.error.details["field"] == "cursor"


def test_forecast_list_items_carry_outcome_probabilities(tmp_path):
    """Bead trade-trace-mymh7: items must carry an `outcomes` array so a
    caller can compute forecast-vs-market edge without a second per-forecast
    query."""

    home = tmp_path / "home"
    assert _call("journal.init", {"home": str(home)}).ok

    market_id = _bind_market(home, external_id="ext-outcomes", idempotency_key="bind-outcomes")
    forecast_id = _add_forecast(
        home, market_id=market_id, idempotency_key="fc-outcomes", p_yes=0.62,
    )["id"]

    listed = _call("forecast.list", {"home": str(home)})
    assert listed.ok, listed
    item = listed.data["items"][0]
    assert item["id"] == forecast_id

    outcomes = item["outcomes"]
    by_label = {o["outcome_label"]: o["probability"] for o in outcomes}
    assert set(by_label) == {"yes", "no"}
    assert by_label["yes"] == pytest.approx(0.62)
    assert by_label["no"] == pytest.approx(0.38)
    assert sum(by_label.values()) == pytest.approx(1.0)


def test_forecast_list_outcomes_correct_across_pagination_pages(tmp_path):
    """Each item's `outcomes` must resolve to its own forecast's rows even
    when the batch fetch is scoped per-page (bead trade-trace-mymh7) —
    a forecast on page 2 must not pick up page 1's outcomes or vice versa."""

    home = tmp_path / "home"
    assert _call("journal.init", {"home": str(home)}).ok

    expected_by_id: dict[str, dict[str, float]] = {}
    for i in range(5):
        market_id = _bind_market(home, external_id=f"ext-outcomes-page-{i}", idempotency_key=f"bind-outcomes-page-{i}")
        p_yes = 0.5 + (i * 0.05)
        forecast_id = _add_forecast(
            home, market_id=market_id, idempotency_key=f"fc-outcomes-page-{i}", p_yes=p_yes,
        )["id"]
        expected_by_id[forecast_id] = {"yes": p_yes, "no": 1.0 - p_yes}

    seen_by_id: dict[str, dict[str, float]] = {}
    cursor = None
    pages = 0
    while True:
        args = {"home": str(home), "limit": 2}
        if cursor is not None:
            args["cursor"] = cursor
        page = _call("forecast.list", args)
        assert page.ok, page
        pages += 1
        for item in page.data["items"]:
            outcomes = item["outcomes"]
            assert len(outcomes) == 2
            by_label = {o["outcome_label"]: o["probability"] for o in outcomes}
            assert sum(by_label.values()) == pytest.approx(1.0)
            seen_by_id[item["id"]] = by_label
        cursor = page.data["next_cursor"]
        if not page.data["truncated"]:
            break
        assert pages < 10, "pagination did not terminate"

    assert set(seen_by_id) == set(expected_by_id)
    for forecast_id, expected in expected_by_id.items():
        assert seen_by_id[forecast_id]["yes"] == pytest.approx(expected["yes"])
        assert seen_by_id[forecast_id]["no"] == pytest.approx(expected["no"])


def test_forecast_list_cursor_pagination_walks_every_forecast_without_duplicates(tmp_path):
    home = tmp_path / "home"
    assert _call("journal.init", {"home": str(home)}).ok

    expected_ids = set()
    for i in range(5):
        market_id = _bind_market(home, external_id=f"ext-page-{i}", idempotency_key=f"bind-page-{i}")
        forecast_id = _add_forecast(home, market_id=market_id, idempotency_key=f"fc-page-{i}")["id"]
        expected_ids.add(forecast_id)

    seen_ids: list[str] = []
    cursor = None
    pages = 0
    while True:
        args = {"home": str(home), "limit": 2}
        if cursor is not None:
            args["cursor"] = cursor
        page = _call("forecast.list", args)
        assert page.ok, page
        pages += 1
        assert len(page.data["items"]) <= 2
        seen_ids.extend(item["id"] for item in page.data["items"])
        cursor = page.data["next_cursor"]
        if not page.data["truncated"]:
            assert cursor is None
            break
        assert cursor is not None
        assert pages < 10, "pagination did not terminate"

    assert pages == 3  # 5 items at limit=2 -> pages of 2, 2, 1
    assert len(seen_ids) == len(set(seen_ids)), "cursor pagination must not repeat rows"
    assert set(seen_ids) == expected_ids
