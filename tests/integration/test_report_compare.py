"""report.compare (trade-trace-4md)."""

from __future__ import annotations

from pathlib import Path

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _env(home: Path, tool: str, args: dict):
    return mcp_call(tool, {"home": str(home), **args}, actor_id="agent:default").model_dump(
        mode="json", exclude_none=True
    )


def _seed_positions(home: Path) -> None:
    v = _env(home, "venue.add", {"name": "Compare PM", "kind": "prediction_market"})["data"]["id"]
    i1 = _env(home, "instrument.add", {"venue_id": v, "asset_class": "prediction_market", "title": "A"})["data"]["id"]
    i2 = _env(home, "instrument.add", {"venue_id": v, "asset_class": "prediction_market", "title": "B"})["data"]["id"]
    db = open_database(db_path(home))
    try:
        with db.transaction():
            for pos_id, instr, status, realized, unrealized in [
                ("pos_b", i1, "closed", 2.0, None),
                ("pos_a", i2, "closed", 1.0, None),
                ("pos_c", i2, "open", None, 0.5),
            ]:
                db.connection.execute(
                    "INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, closed_at, resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, updated_at) "
                    "VALUES (?, ?, 'paper', 'long', ?, '2026-05-18T00:00:00Z', NULL, NULL, ?, ?, 1.0, '2026-05-18T01:00:00Z')",
                    (pos_id, instr, status, realized, unrealized),
                )
    finally:
        db.close()


def test_compare_registered():
    names = default_registry().names()
    assert "report.compare" in names


def test_compare_pnl_grouping_stable_order_and_sample_warning(home):
    _seed_positions(home)
    first = _env(home, "report.compare", {"base_report": "pnl", "group_by": "status"})
    second = _env(home, "report.compare", {"base_report": "pnl", "group_by": "status"})
    assert first["ok"], first
    groups = first["data"]["groups"]
    assert [g["key"] for g in groups] == ["closed", "open"]
    assert [g["key"] for g in groups] == [g["key"] for g in second["data"]["groups"]]
    closed = groups[0]
    assert closed["metrics"]["closed_count"] == 2
    assert closed["sample_warning"] == "only 2 closed positions; pnl trend is unreliable below 5"
    assert first["data"]["summary"]["sample_warning"] == "one_or_more_groups_below_min_sample"


def test_compare_rejects_injected_group_by(home):
    env = _env(home, "report.compare", {"base_report": "pnl", "group_by": "status; DROP TABLE positions"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_compare_pnl_strategy_id_discoverable_and_runs(home):
    # trade-trace-1k5d: strategy_id group_by for pnl was functional but lived
    # only in a special-case branch, undiscoverable from the per-base allowlist.
    # It must now appear in SUPPORTED_GROUP_BY_BY_BASE_REPORT['pnl'] AND run.
    from trade_trace.reports.compare import (
        PNL_GROUP_SQL,
        SUPPORTED_GROUP_BY_BY_BASE_REPORT,
    )

    assert "strategy_id" in PNL_GROUP_SQL
    assert "strategy_id" in SUPPORTED_GROUP_BY_BY_BASE_REPORT["pnl"]
    _seed_positions(home)
    env = _env(home, "report.compare", {"base_report": "pnl", "group_by": "strategy_id"})
    assert env["ok"], env
    assert env["data"]["summary"]["group_by"] == "strategy_id"


def test_unsupported_group_by_error_lists_allowed_set(home):
    """AX-049: rejecting an unsupported group_by must name the allowed set
    for that base_report so an MCP-only bot can recover, instead of echoing
    only the offending value (the AX-004/005/032/035 self-documenting class).
    `tag` is in neither allowlist, so it is the canonical no-recovery case."""
    cal = _env(home, "report.compare", {"base_report": "calibration", "group_by": "tag"})
    assert cal["ok"] is False
    assert cal["error"]["code"] == "VALIDATION_ERROR"
    msg = cal["error"]["message"]
    # names the allowed set, not just the rejected value
    assert "allowed group_by values are" in msg
    assert "strategy_id" in msg and "instrument_id" in msg
    assert "'tag'" in msg  # still echoes the offending value

    pnl = _env(home, "report.compare", {"base_report": "pnl", "group_by": "tag"})
    assert pnl["ok"] is False
    pnl_msg = pnl["error"]["message"]
    assert "allowed group_by values are" in pnl_msg
    # pnl allowlist is the narrower one — must reflect the per-base set
    assert "instrument_id" in pnl_msg and "asset_class" in pnl_msg


def test_compare_schema_does_not_advertise_unsupported_tag_group_by():
    """AX-049: the advertised report.compare group_by description must not
    list `tag` as a usable value, since it is rejected for both base_reports
    (advertising-vs-runtime drift, the trade-trace-cs0r class)."""
    from trade_trace.reports.compare import CALIBRATION_GROUP_SQL, PNL_GROUP_SQL
    from trade_trace.reports.tool_schemas import _REPORT_SCHEMAS

    assert "tag" not in CALIBRATION_GROUP_SQL
    assert "tag" not in PNL_GROUP_SQL
    desc = _REPORT_SCHEMAS["report.compare"]["properties"]["group_by"]["description"]
    # every group_by the description names as supported must actually be in an allowlist
    allowed = set(CALIBRATION_GROUP_SQL) | set(PNL_GROUP_SQL)
    assert "tag" in desc and "not a supported" in desc  # explicitly corrects the prior claim
    for value in ("strategy_id", "instrument_id", "asset_class", "venue_id"):
        assert value in desc and value in allowed


def test_compare_schema_advertises_every_runtime_group_by():
    """AX-050: the advertised group_by description must name EVERY value the
    runtime allowlists accept — not just a sample. The AX-049 fix enumerated the
    allowlist into the description but missed `outcome_status` (a working alias of
    `status` in CALIBRATION_GROUP_SQL that the rejection error itself advertises),
    re-opening the same advertising-vs-runtime drift (trade-trace-cs0r class) on
    one value. A bot reading the schema must learn every group_by it could pass."""
    from trade_trace.reports.compare import (
        CALIBRATION_GROUP_SQL,
        PNL_GROUP_SQL,
        RISK_GROUP_KEYS,
    )
    from trade_trace.reports.tool_schemas import _REPORT_SCHEMAS

    desc = _REPORT_SCHEMAS["report.compare"]["properties"]["group_by"]["description"]
    for value in set(CALIBRATION_GROUP_SQL) | set(PNL_GROUP_SQL) | set(RISK_GROUP_KEYS):
        assert value in desc, f"group_by {value!r} is runtime-supported but unadvertised in the schema description"


# -- documented group_by matches runtime (trade-trace-cs0r) -----------


def test_documented_group_by_matches_runtime_support():
    """Per trade-trace-cs0r: `DOCUMENTED_GROUP_BY` must equal the union
    of the per-base-report runtime allowlists. Adding a value to the
    docs without wiring the SQL mapping silently breaks agents."""

    from trade_trace.reports.compare import (
        CALIBRATION_GROUP_SQL,
        DOCUMENTED_GROUP_BY,
        PNL_GROUP_SQL,
        RISK_GROUP_KEYS,
        SUPPORTED_GROUP_BY_BY_BASE_REPORT,
    )

    assert DOCUMENTED_GROUP_BY == (
        set(CALIBRATION_GROUP_SQL) | set(PNL_GROUP_SQL) | set(RISK_GROUP_KEYS)
    )
    assert SUPPORTED_GROUP_BY_BY_BASE_REPORT == {
        "calibration": set(CALIBRATION_GROUP_SQL),
        "pnl": set(PNL_GROUP_SQL),
        "risk": set(RISK_GROUP_KEYS),
    }


# -- decisions fan-out regression (trade-trace-v526) ------------------


def _seed_scored_forecast_with_strategy(home: Path, *, strategy_slug: str) -> tuple[str, str, str, str]:
    """Resolve one binary forecast end-to-end and tag its thesis with a
    strategy. Returns (thesis_id, forecast_id, instrument_id, strategy_id). The
    resolved outcome auto-scores the forecast so it appears in calibration
    compare."""

    strat = _env(home, "strategy.upsert", {
        "slug": strategy_slug, "name": f"Strat {strategy_slug}",
        "idempotency_key": f"strat-{strategy_slug}",
    })["data"]["id"]
    venue = _env(home, "venue.add", {"name": "Fanout PM", "kind": "prediction_market"})["data"]["id"]
    inst = _env(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": "Fanout X",
    })["data"]["id"]
    thesis = _env(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "fan-out thesis",
        "strategy_id": strat,
    })["data"]["id"]
    forecast = _env(home, "forecast.add", {
        "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })["data"]["id"]
    _env(home, "outcome.add", {
        "instrument_id": inst, "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes", "status": "resolved_final", "confidence": 0.99,
    })
    return thesis, forecast, inst, strat


def _insert_decision(
    home: Path, *, decision_id: str, instrument_id: str, thesis_id: str,
    forecast_id: str | None, dtype: str,
) -> None:
    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, thesis_id, forecast_id, type, "
                "created_at, actor_id) VALUES (?, ?, ?, ?, ?, '2026-06-01T00:00:00Z', 'agent:default')",
                (decision_id, instrument_id, thesis_id, forecast_id, dtype),
            )
    finally:
        db.close()


def test_calibration_single_valued_grouping_not_fanned_by_decisions(home):
    """trade-trace-v526: a single scored forecast whose thesis carries TWO
    decisions (paper_enter + review) must be counted exactly ONCE under a
    single-valued grouping (strategy_id). The old thesis-level
    `LEFT JOIN decisions d ON d.thesis_id = t.id` fanned the row out once per
    decision, inflating sample_size, Brier, ECE, and sharpness."""

    thesis, forecast, inst, strat = _seed_scored_forecast_with_strategy(home, strategy_slug="strat-x")
    _insert_decision(home, decision_id="dec_pe", instrument_id=inst, thesis_id=thesis,
                     forecast_id=forecast, dtype="paper_enter")
    _insert_decision(home, decision_id="dec_rv", instrument_id=inst, thesis_id=thesis,
                     forecast_id=forecast, dtype="review")

    env = _env(home, "report.compare", {
        "base_report": "calibration", "group_by": "strategy_id", "min_sample": 1,
    })
    assert env["ok"], env
    groups = {g["key"]: g for g in env["data"]["groups"]}
    assert strat in groups
    g = groups[strat]
    # exactly one scored forecast — not 2 (one per decision on the thesis)
    assert g["sample_size"] == 1
    assert g["record_ids"]["forecast_scores"] == sorted(set(g["record_ids"]["forecast_scores"]))
    assert len(g["record_ids"]["forecast_scores"]) == 1
    # p=0.6, y=1 -> Brier=0.16 (unaffected by the duplicate decision rows)
    assert g["metrics"]["brier"] == 0.16
    # summary total is the sum of group sample_sizes — must not be overcounted
    assert env["data"]["summary"]["sample_size"] == 1


def test_calibration_decision_type_grouping_maps_via_forecast_id(home):
    """trade-trace-v526: with group_by='decision_type', a scored forecast must
    land in the group of the decision linked to THAT forecast
    (decisions.forecast_id), not be fanned across every decision type attached
    to the thesis. Here the thesis has a paper_enter linked to the forecast and
    a review decision NOT linked to the forecast (forecast_id NULL)."""

    thesis, forecast, inst, _strat = _seed_scored_forecast_with_strategy(home, strategy_slug="strat-y")
    _insert_decision(home, decision_id="dec_pe2", instrument_id=inst, thesis_id=thesis,
                     forecast_id=forecast, dtype="paper_enter")
    # a review decision on the same thesis but NOT tied to this forecast
    _insert_decision(home, decision_id="dec_rv2", instrument_id=inst, thesis_id=thesis,
                     forecast_id=None, dtype="review")

    env = _env(home, "report.compare", {
        "base_report": "calibration", "group_by": "decision_type", "min_sample": 1,
    })
    assert env["ok"], env
    groups = {g["key"]: g for g in env["data"]["groups"]}
    # the forecast is linked to paper_enter only — it must NOT appear under review
    assert "paper_enter" in groups
    assert groups["paper_enter"]["sample_size"] == 1
    assert "review" not in groups
    # total across all decision_type groups is the single scored forecast, once
    assert env["data"]["summary"]["sample_size"] == 1


def test_pnl_instrument_grouping_not_fanned_by_multiple_closed_positions(home):
    """trade-trace-v526 (pnl side): an instrument with multiple closed positions
    must report each position once. Each position contributes a distinct row; the
    instrument group's sample_size equals the number of its positions, with no
    duplication from the decision/thesis join chain in the pnl compare path."""

    venue = _env(home, "venue.add", {"name": "PnL PM", "kind": "prediction_market"})["data"]["id"]
    inst = _env(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": "PnL X",
    })["data"]["id"]
    db = open_database(db_path(home))
    try:
        with db.transaction():
            for pos_id, realized in [("pos_x1", 2.0), ("pos_x2", 3.0), ("pos_x3", 1.0)]:
                db.connection.execute(
                    "INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, "
                    "closed_at, resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, updated_at) "
                    "VALUES (?, ?, 'paper', 'long', 'closed', '2026-05-18T00:00:00Z', NULL, NULL, ?, NULL, 1.0, '2026-05-18T01:00:00Z')",
                    (pos_id, inst, realized),
                )
    finally:
        db.close()

    env = _env(home, "report.compare", {
        "base_report": "pnl", "group_by": "instrument_id", "min_sample": 1,
    })
    assert env["ok"], env
    groups = {g["key"]: g for g in env["data"]["groups"]}
    assert inst in groups
    g = groups[inst]
    # three closed positions counted once each — no fan-out
    assert g["sample_size"] == 3
    assert sorted(g["record_ids"]["positions"]) == ["pos_x1", "pos_x2", "pos_x3"]
    assert g["metrics"]["closed_count"] == 3


# -- risk base_report: longitudinal / per-strategy expectancy (trade-trace-62fj) --


def _seed_risk_decision(
    home: Path,
    *,
    decision_id: str,
    realized_pnl: float | None,
    risk_amount: float | None,
    created_at: str,
    status: str = "closed",
    strategy_id: str | None = None,
    dtype: str = "add",
) -> str:
    """Seed an instrument + decision (with the given created_at / strategy /
    declared risk) and, when realized_pnl is provided, a closed position linked
    via a position_events open row (the production decision->position path that
    report.risk / the risk compare base both read — trade-trace-rtxy). Returns
    the instrument id."""

    venue = _env(home, "venue.add", {"name": f"Risk PM {decision_id}", "kind": "prediction_market"})["data"]["id"]
    inst = _env(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": f"Risk {decision_id}",
    })["data"]["id"]
    pos_id = f"pos_{decision_id}"
    db = open_database(db_path(home))
    try:
        with db.transaction():
            db.connection.execute(
                "INSERT INTO decisions(id, instrument_id, type, side, quantity, price, "
                "declared_risk_amount, strategy_id, created_at, actor_id) "
                "VALUES (?, ?, ?, 'long', 1, 1.0, ?, ?, ?, 'agent:default')",
                (decision_id, inst, dtype, risk_amount, strategy_id, created_at),
            )
            if realized_pnl is not None:
                db.connection.execute(
                    "INSERT INTO positions(id, instrument_id, kind, side, status, opened_at, "
                    "closed_at, resolved_at, realized_pnl, unrealized_pnl, avg_entry_price, updated_at) "
                    "VALUES (?, ?, 'paper', 'long', ?, ?, ?, NULL, ?, NULL, 0.4, ?)",
                    (pos_id, inst, status, created_at, created_at, realized_pnl, created_at),
                )
                db.connection.execute(
                    "INSERT INTO position_events(id, position_id, instrument_id, decision_id, "
                    "event_type, quantity_delta, price, fees, slippage, created_at, actor_id) "
                    "VALUES (?, ?, ?, ?, 'open', 1, 0.4, 0, 0, ?, 'agent:test')",
                    (f"pev_{decision_id}", pos_id, inst, decision_id, created_at),
                )
    finally:
        db.close()
    return inst


def test_compare_risk_registered_as_base_report():
    from trade_trace.reports.compare import SUPPORTED_BASE_REPORTS

    assert "risk" in SUPPORTED_BASE_REPORTS


def test_compare_risk_period_bucket_yields_over_time_expectancy_series(home):
    """trade-trace-62fj: base_report='risk', group_by='period' buckets resolved
    R-multiple expectancy by YYYY-MM month so an over-time series is observable —
    the longitudinal dimension report.risk (point-in-time) lacked."""

    # Two resolved decisions in 2026-04 (R = +2 and +1 -> expectancy 1.5) and one
    # in 2026-05 (R = -1).
    _seed_risk_decision(home, decision_id="d_apr1", realized_pnl=200.0, risk_amount=100.0, created_at="2026-04-03T00:00:00Z")
    _seed_risk_decision(home, decision_id="d_apr2", realized_pnl=100.0, risk_amount=100.0, created_at="2026-04-20T00:00:00Z")
    _seed_risk_decision(home, decision_id="d_may1", realized_pnl=-100.0, risk_amount=100.0, created_at="2026-05-09T00:00:00Z")

    env = _env(home, "report.compare", {
        "base_report": "risk", "group_by": "period", "min_sample": 1,
    })
    assert env["ok"], env
    groups = {g["key"]: g for g in env["data"]["groups"]}
    assert set(groups) == {"2026-04", "2026-05"}
    apr = groups["2026-04"]
    assert apr["sample_size"] == 2
    assert apr["metrics"]["expectancy_r"] == 1.5
    assert apr["metrics"]["mean_r"] == 1.5
    assert apr["coverage"]["included_count"] == 2
    assert apr["coverage"]["eligible_count"] == 2
    assert apr["coverage"]["coverage_pct"] == 100.0
    may = groups["2026-05"]
    assert may["sample_size"] == 1
    assert may["metrics"]["expectancy_r"] == -1.0
    # determinism: keys are sorted ascending
    assert [g["key"] for g in env["data"]["groups"]] == ["2026-04", "2026-05"]
    assert env["data"]["summary"]["base_report"] == "risk"
    assert env["data"]["summary"]["sample_size"] == 3


def test_compare_risk_strategy_bucket_separates_expectancy(home):
    """trade-trace-62fj: per-strategy expectancy series via group_by='strategy_id'."""

    strat_a = _env(home, "strategy.upsert", {"slug": "rstrat-a", "name": "A", "idempotency_key": "rs-a"})["data"]["id"]
    strat_b = _env(home, "strategy.upsert", {"slug": "rstrat-b", "name": "B", "idempotency_key": "rs-b"})["data"]["id"]
    _seed_risk_decision(home, decision_id="d_sa1", realized_pnl=300.0, risk_amount=100.0, created_at="2026-04-03T00:00:00Z", strategy_id=strat_a)
    _seed_risk_decision(home, decision_id="d_sb1", realized_pnl=-50.0, risk_amount=100.0, created_at="2026-04-04T00:00:00Z", strategy_id=strat_b)

    env = _env(home, "report.compare", {
        "base_report": "risk", "group_by": "strategy_id", "min_sample": 1,
    })
    assert env["ok"], env
    groups = {g["key"]: g for g in env["data"]["groups"]}
    assert strat_a in groups and strat_b in groups
    assert groups[strat_a]["metrics"]["expectancy_r"] == 3.0
    assert groups[strat_b]["metrics"]["expectancy_r"] == -0.5


def test_compare_risk_coverage_block_reports_declared_risk_denominator(home):
    """trade-trace-62fj: each risk-compare group carries a prominent coverage
    block — closed decisions with declared risk over all closed decisions — so a
    low-denominator bucket self-caveats instead of overstating expectancy."""

    # 2026-04: one decision WITH declared risk (resolved win) and one closed
    # decision in the same month WITHOUT declared risk -> coverage 1/2 = 50%.
    _seed_risk_decision(home, decision_id="d_cov1", realized_pnl=150.0, risk_amount=100.0, created_at="2026-04-10T00:00:00Z")
    _seed_risk_decision(home, decision_id="d_cov2", realized_pnl=40.0, risk_amount=None, created_at="2026-04-11T00:00:00Z")

    env = _env(home, "report.compare", {
        "base_report": "risk", "group_by": "period", "min_sample": 1,
    })
    assert env["ok"], env
    apr = {g["key"]: g for g in env["data"]["groups"]}["2026-04"]
    cov = apr["coverage"]
    assert cov["eligible_count"] == 2  # both closed decisions
    assert cov["included_count"] == 1  # only the declared-risk one
    assert cov["missing_count"] == 1
    assert cov["coverage_pct"] == 50.0
    assert cov["denominator_kind"] == "closed_decisions"
    # the metric is still computed on the declared-risk decision only
    assert apr["metrics"]["expectancy_r"] == 1.5
    assert apr["sample_size"] == 1


def test_compare_risk_rejects_unsupported_group_by_with_allowed_set(home):
    env = _env(home, "report.compare", {"base_report": "risk", "group_by": "venue_id"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    msg = env["error"]["message"]
    assert "allowed group_by values are" in msg
    assert "period" in msg and "strategy_id" in msg and "decision_type" in msg


def test_compare_risk_pending_decision_excluded_from_series(home):
    """A decision that declared risk but has no closed position must not enter the
    expectancy series (it is pending), mirroring report.risk's pending handling."""

    _seed_risk_decision(home, decision_id="d_done", realized_pnl=100.0, risk_amount=100.0, created_at="2026-04-01T00:00:00Z")
    _seed_risk_decision(home, decision_id="d_pend", realized_pnl=None, risk_amount=100.0, created_at="2026-04-02T00:00:00Z")

    env = _env(home, "report.compare", {
        "base_report": "risk", "group_by": "period", "min_sample": 1,
    })
    assert env["ok"], env
    apr = {g["key"]: g for g in env["data"]["groups"]}["2026-04"]
    # only the resolved decision contributes to the series
    assert apr["sample_size"] == 1
    assert apr["record_ids"]["decisions"] == ["d_done"]


# --- trade-trace-txjn: longitudinal calibration-over-time (per-period) ------


def _seed_scored_forecast_resolved_at(
    home: Path, *, title: str, resolved_at: str, probability: float, outcome_label: str,
) -> str:
    """Resolve one binary forecast end-to-end with a caller-chosen resolved_at so
    the scored row lands in a specific calendar period. Returns the forecast_id.

    The resolved outcome auto-scores the forecast, so it appears in
    report.compare(base_report='calibration') under the resolution_month /
    resolution_week buckets."""

    venue = _env(home, "venue.add", {"name": "Trend PM", "kind": "prediction_market"})["data"]["id"]
    inst = _env(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": title,
    })["data"]["id"]
    thesis = _env(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": f"trend thesis {title}",
    })["data"]["id"]
    forecast = _env(home, "forecast.add", {
        "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": probability},
            {"outcome_label": "no", "probability": round(1.0 - probability, 6)},
        ],
    })["data"]["id"]
    _env(home, "outcome.add", {
        "instrument_id": inst, "resolved_at": resolved_at,
        "outcome_label": outcome_label, "status": "resolved_final", "confidence": 0.99,
    })
    return forecast


def test_compare_calibration_resolution_month_buckets_scored_forecasts(home):
    """trade-trace-txjn: base_report='calibration', group_by='resolution_month'
    buckets scored forecasts by the calendar month they RESOLVED in (resolved_at
    basis), so 'is the calibration curve improving over months' is one call.

    April: p=0.6 resolved YES (Brier 0.16). May: p=0.6 resolved NO (Brier 0.36).
    The two months land in distinct buckets with their own per-period metrics."""

    f_apr = _seed_scored_forecast_resolved_at(
        home, title="apr-hit", resolved_at="2026-04-10T00:00:00Z",
        probability=0.6, outcome_label="yes",
    )
    f_may = _seed_scored_forecast_resolved_at(
        home, title="may-miss", resolved_at="2026-05-20T00:00:00Z",
        probability=0.6, outcome_label="no",
    )

    env = _env(home, "report.compare", {
        "base_report": "calibration", "group_by": "resolution_month", "min_sample": 1,
    })
    assert env["ok"], env
    groups = {g["key"]: g for g in env["data"]["groups"]}
    assert set(groups) == {"2026-04", "2026-05"}
    # deterministic ascending key order
    assert [g["key"] for g in env["data"]["groups"]] == ["2026-04", "2026-05"]

    apr = groups["2026-04"]
    assert apr["sample_size"] == 1
    assert apr["metrics"]["brier"] == 0.16  # p=0.6, y=1
    # contributing record_ids per period so the bucket is reproducible
    assert f_apr in apr["record_ids"]["forecasts"]
    assert len(apr["record_ids"]["forecast_scores"]) == 1

    may = groups["2026-05"]
    assert may["sample_size"] == 1
    assert may["metrics"]["brier"] == 0.36  # p=0.6, y=0
    assert f_may in may["record_ids"]["forecasts"]

    assert env["data"]["summary"]["base_report"] == "calibration"
    assert env["data"]["summary"]["group_by"] == "resolution_month"
    assert env["data"]["summary"]["sample_size"] == 2


def test_compare_calibration_period_low_n_caveat_and_insufficient_flag(home):
    """trade-trace-txjn: monthly buckets frequently fall below the N=20
    calibration floor, so each thin period flags itself (sample_warning +
    insufficient:true) and the summary carries the low-N-per-period policy
    caveat. A consumer gates on `insufficient` rather than re-deriving N<floor."""

    _seed_scored_forecast_resolved_at(
        home, title="thin-apr", resolved_at="2026-04-10T00:00:00Z",
        probability=0.55, outcome_label="yes",
    )

    env = _env(home, "report.compare", {
        "base_report": "calibration", "group_by": "resolution_month",
        # default min_sample (DEFAULT_MIN_SAMPLE=20) -> the single-forecast month
        # is below the floor
    })
    assert env["ok"], env
    apr = {g["key"]: g for g in env["data"]["groups"]}["2026-04"]
    assert apr["sample_size"] == 1
    assert apr["insufficient"] is True
    assert apr["sample_warning"] is not None and "below 20" in apr["sample_warning"]
    assert env["data"]["summary"]["sample_warning"] == "one_or_more_groups_below_min_sample"
    caveats = env["data"]["summary"]["caveats"]
    assert any("calibration floor" in c and "resolved_at" in c for c in caveats)


def test_compare_calibration_resolution_week_bucket_supported(home):
    """trade-trace-txjn: resolution_week is the finer (YYYY-Www) calendar bucket
    on the same resolved_at basis, for tighter trend resolution when N allows."""

    _seed_scored_forecast_resolved_at(
        home, title="wk", resolved_at="2026-04-03T00:00:00Z",
        probability=0.7, outcome_label="yes",
    )
    env = _env(home, "report.compare", {
        "base_report": "calibration", "group_by": "resolution_week", "min_sample": 1,
    })
    assert env["ok"], env
    groups = {g["key"]: g for g in env["data"]["groups"]}
    # 2026-04-03 falls in ISO-ish week 13 per SQLite strftime('%Y-W%W', ...)
    assert "2026-W13" in groups
    assert groups["2026-W13"]["sample_size"] == 1
    assert env["data"]["summary"]["group_by"] == "resolution_week"


def test_compare_calibration_period_keys_advertised_in_schema():
    """trade-trace-txjn: the new calendar-period group_by keys are runtime-
    supported, so they MUST appear in the report.compare schema description
    (the AX-050 advertising-vs-runtime-parity contract)."""
    from trade_trace.reports.compare import CALIBRATION_GROUP_SQL
    from trade_trace.reports.tool_schemas import _REPORT_SCHEMAS

    assert "resolution_month" in CALIBRATION_GROUP_SQL
    assert "resolution_week" in CALIBRATION_GROUP_SQL
    desc = _REPORT_SCHEMAS["report.compare"]["properties"]["group_by"]["description"]
    assert "resolution_month" in desc
    assert "resolution_week" in desc
