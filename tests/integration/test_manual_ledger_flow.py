"""End-to-end manual ledger flow + per-tool tests per trade-trace-kyr.

Exercises the M1 write surface: venue.add → instrument.add → snapshot.add
→ thesis.add → forecast.add → decision.add → outcome.add (resolved_final)
→ auto-scoring. Plus per-tool happy-path and VALIDATION_ERROR cases for
every M1 write tool.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.projections import rebuild_positions
from trade_trace.storage.paths import db_path


def _envelope(home: Path, tool: str, args: dict, **kwargs):
    payload = {"home": str(home), **args}
    return mcp_call(tool, payload, actor_id=kwargs.get("actor_id", "agent:default")).model_dump(
        mode="json", exclude_none=True
    )


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


# -- venue.add -----------------------------------------------------------


def test_venue_add_happy(home):
    env = _envelope(home, "venue.add", {"name": "Polymarket", "kind": "prediction_market"})
    assert env["ok"] is True
    assert env["data"]["name"] == "Polymarket"
    assert env["data"]["id"].startswith("ven_")


def test_venue_add_missing_name(home):
    env = _envelope(home, "venue.add", {"kind": "prediction_market"})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "name"


def test_venue_add_invalid_kind(home):
    env = _envelope(home, "venue.add", {"name": "X", "kind": "not_a_kind"})
    assert env["ok"] is False
    # SQLite CHECK constraint surfaces as STORAGE_ERROR via the UnitOfWork.
    # We accept either VALIDATION or STORAGE — the agent gets a typed error.
    assert env["error"]["code"] in ("VALIDATION_ERROR", "STORAGE_ERROR", "INVARIANT_VIOLATION")


# -- instrument.add ------------------------------------------------------


def test_instrument_add_happy(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    env = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Will X happen by 2026-06-30?",
        "currency_or_collateral": "USDC",
    })
    assert env["ok"] is True
    assert env["data"]["title"].startswith("Will X")


def test_instrument_add_missing_title(home):
    env = _envelope(home, "instrument.add", {"venue_id": "v_1", "asset_class": "equity"})
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "title"


# -- snapshot.add --------------------------------------------------------


def test_snapshot_add_happy(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    env = _envelope(home, "snapshot.add", {
        "instrument_id": inst["data"]["id"],
        "captured_at": "2026-05-18T14:00:00Z",
        "price": 0.37,
        "bid": 0.36,
        "ask": 0.39,
    })
    assert env["ok"] is True


def test_snapshot_add_rejects_naive_timestamp(home):
    env = _envelope(home, "snapshot.add", {
        "instrument_id": "i_1",
        "captured_at": "2026-05-18T14:00:00",  # no tz
    })
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "captured_at"


# -- thesis.add ----------------------------------------------------------


def test_thesis_add_happy(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    env = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "Edge in thin-liquidity prediction markets",
        "falsification_criteria": "volume > 100k for 3 consecutive days",
    })
    assert env["ok"] is True
    assert env["data"]["side"] == "yes"


# -- forecast.add (binary invariants) ------------------------------------


def _setup_thesis(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    return inst["data"]["id"], thesis["data"]["id"]


def test_forecast_add_binary_happy(home):
    _, thesis_id = _setup_thesis(home)
    env = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.48},
            {"outcome_label": "NO", "probability": 0.52},
        ],
    })
    assert env["ok"] is True


def test_forecast_add_binary_invariant_sum(home):
    _, thesis_id = _setup_thesis(home)
    env = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.4},  # sum 0.9, not 1.0
        ],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "INVARIANT_VIOLATION"
    assert "found_sum" in env["error"]["details"]


def test_forecast_add_binary_invariant_count(home):
    _, thesis_id = _setup_thesis(home)
    env = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [{"outcome_label": "YES", "probability": 1.0}],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "INVARIANT_VIOLATION"


def test_forecast_add_binary_invariant_distinct_labels(home):
    _, thesis_id = _setup_thesis(home)
    env = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "yes", "probability": 0.5},  # same after case-fold
        ],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "INVARIANT_VIOLATION"


def test_forecast_add_probability_out_of_range(home):
    _, thesis_id = _setup_thesis(home)
    env = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 1.5},
            {"outcome_label": "NO", "probability": -0.5},
        ],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "INVARIANT_VIOLATION"


# -- decision.add (required-field matrix) --------------------------------


def test_decision_add_skip_requires_reason(home):
    inst_id, _ = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "skip",
        # missing reason
    })
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "reason"


def test_decision_add_skip_forbids_quantity(home):
    inst_id, _ = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "skip",
        "reason": "spread too wide",
        "quantity": 100,
    })
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "quantity"
    assert env["error"]["details"]["decision_type"] == "skip"


def test_decision_add_paper_enter_full(home):
    inst_id, thesis_id = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "thesis_id": thesis_id,
        "type": "paper_enter",
        "side": "long",
        "quantity": 100,
        "price": 0.37,
        "tags": ["liquidity-ignored", "good-skip"],
    })
    assert env["ok"] is True
    assert env["data"]["tags"] == ["good-skip", "liquidity-ignored"]


# -- bead trade-trace-8u3s: tag sanitization at write time -----------


@pytest.mark.parametrize(
    "bad_tag",
    [
        "<script>alert(1)</script>",
        "<img src=x>",
        "ok>tag",
        "<plain",
    ],
)
def test_decision_add_rejects_html_like_tags(home, bad_tag):
    """Tags carrying `<` or `>` would render as live HTML if any future
    UI surface treats decision_tags as markup. Reject at ingestion (bead
    trade-trace-8u3s)."""

    inst_id, _ = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "skip",
        "reason": "boundary test",
        "tags": ["clean", bad_tag],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "tags"
    assert env["error"]["details"]["reason"] == "html_like_content"
    assert env["error"]["details"]["value"] == bad_tag


@pytest.mark.parametrize("bad_tag", ["", "   ", "\t", "\n"])
def test_decision_add_rejects_empty_or_whitespace_tags(home, bad_tag):
    """Previously empty/whitespace-only tags were silently dropped,
    masking malformed input. Reject explicitly so callers see the
    error (bead trade-trace-8u3s)."""

    inst_id, _ = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "skip",
        "reason": "boundary test",
        "tags": ["legit", bad_tag],
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "tags"
    assert env["error"]["details"]["reason"] == "empty_tag"


def test_decision_add_paper_enter_creates_position_event_and_live_projection(home):
    inst_id, thesis_id = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "thesis_id": thesis_id,
        "type": "paper_enter",
        "side": "no",
        "quantity": 7,
        "price": 0.42,
        "fees": 0.03,
        "slippage": 0.01,
    })
    assert env["ok"] is True, env
    assert env["data"]["position_id"].startswith("pos_")
    assert env["data"]["position_event_id"].startswith("pev_")

    with sqlite3.connect(db_path(home)) as conn:
        pe = conn.execute(
            "SELECT id, position_id, instrument_id, decision_id, event_type, "
            "quantity_delta, price, fees, slippage FROM position_events"
        ).fetchone()
        assert pe == (
            env["data"]["position_event_id"], env["data"]["position_id"],
            inst_id, env["data"]["id"], "open", -7.0, 0.42, 0.03, 0.01,
        )
        pos = conn.execute(
            "SELECT id, instrument_id, kind, side, status, avg_entry_price "
            "FROM positions WHERE id = ?", (env["data"]["position_id"],)
        ).fetchone()
        assert pos == (env["data"]["position_id"], inst_id, "paper", "no", "open", 0.42)


def test_decision_add_paper_enter_replay_is_idempotent_and_rebuild_parity(home):
    inst_id, thesis_id = _setup_thesis(home)
    key = "00000000-0000-4000-8000-00000000pe01"
    args = {
        "instrument_id": inst_id,
        "thesis_id": thesis_id,
        "type": "paper_enter",
        "side": "yes",
        "quantity": 5,
        "price": 0.2,
        "idempotency_key": key,
    }
    first = _envelope(home, "decision.add", args)
    second = _envelope(home, "decision.add", args)
    assert first["ok"] is True, first
    assert second["ok"] is True, second
    assert second["data"]["id"] == first["data"]["id"]
    assert second["data"]["position_id"] == first["data"]["position_id"]
    assert second["data"]["position_event_id"] == first["data"]["position_event_id"]
    assert second["meta"]["idempotent_replay"] is True

    with sqlite3.connect(db_path(home)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM position_events").fetchone()[0] == 1
        assert conn.execute("SELECT quantity_delta FROM position_events").fetchone()[0] == 5.0
        live = conn.execute("SELECT * FROM positions ORDER BY id").fetchall()
        rebuild_positions(conn)
        rebuilt = conn.execute("SELECT * FROM positions ORDER BY id").fetchall()
        assert rebuilt == live


def test_decision_add_review_requires_review_by(home):
    inst_id, _ = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "review",
    })
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "review_by"


def test_decision_add_unknown_type_rejected(home):
    inst_id, _ = _setup_thesis(home)
    env = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "not_a_type",
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"


def test_decision_add_replay_tolerates_rephrased_reason(home):
    """Per bead trade-trace-uu0b: `decision.reason` is a free-text
    field per semantic-key-policy §3 and `SEMANTIC_KEYS['decision.created']`.
    Replaying `decision.add` with the same idempotency_key and only a
    rephrased `reason` MUST return the original decision id with
    `meta.idempotent_replay=true`, NOT IDEMPOTENCY_CONFLICT.

    This pins the product contract: LLM agents that regenerate prose
    on retry stay replay-safe. Promoting `reason` to structural would
    be a backwards-incompatible contract change (semantic-key-policy.md
    §3 + §5).
    """

    inst_id, _ = _setup_thesis(home)
    key = "00000000-0000-4000-8000-decadebeef01"
    first = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "skip",
        "reason": "spread too wide",
        "idempotency_key": key,
    })
    assert first["ok"], first
    original_id = first["data"]["id"]

    replay = _envelope(home, "decision.add", {
        "instrument_id": inst_id,
        "type": "skip",
        "reason": "the spread was wider than the expected edge",
        "idempotency_key": key,
    })
    assert replay["ok"], replay
    assert replay["data"]["id"] == original_id
    assert replay["meta"].get("idempotent_replay") is True


# -- outcome.add / resolve.record alias ----------------------------------


def test_outcome_add_creates_row(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    env = _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "YES",
        "outcome_value": 1.0,
        "status": "resolved_final",
    })
    assert env["ok"] is True
    assert env["data"]["status"] == "resolved_final"


def test_resolve_record_is_alias_for_outcome_add(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    env = _envelope(home, "resolve.record", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "NO",
        "status": "void",
    })
    assert env["ok"] is True
    assert env["meta"]["tool"] == "resolve.record"


# -- source.add + source.attach_to_thesis --------------------------------


def test_source_add_and_attach(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    source = _envelope(home, "source.add", {
        "kind": "research_doc",
        "title": "Liquidity profile of thin PM markets",
        "stance": "supports",
        "summary": "ADV<$5K markets show 40bps wider spreads near resolution",
    })
    attach = _envelope(home, "source.attach_to_thesis", {
        "source_id": source["data"]["id"],
        "target_id": thesis["data"]["id"],
        "idempotency_key": "test:source-attach-to-thesis",
    })
    assert attach["ok"] is True
    assert attach["data"]["edge_type"] == "supports"


def test_source_attach_to_memory_node_m3_functional(home):
    """source.attach_to_memory_node became functional with M3 (bead s3f);
    the M1-era UNSUPPORTED_CAPABILITY stub was replaced by the shared
    attacher factory. With non-existent source + memory_node ids, the
    attacher returns NOT_FOUND (source validated first)."""

    env = _envelope(home, "source.attach_to_memory_node", {
        "source_id": "s_does_not_exist",
        "target_id": "mem_does_not_exist",
        "idempotency_key": "test:source-attach-to-memory-node-missing",
    })
    assert env["ok"] is False
    assert env["error"]["code"] == "NOT_FOUND"
    assert env["error"]["details"]["entity_kind"] == "source"


# -- resolve.pending -----------------------------------------------------


def test_resolve_pending_lists_unresolved(home):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"],
        "kind": "binary",
        "resolution_at": "2026-06-30T00:00:00Z",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.6},
            {"outcome_label": "NO", "probability": 0.4},
        ],
    })
    env = _envelope(home, "resolve.pending", {})
    assert env["ok"] is True
    assert env["data"]["count"] >= 1
    assert all("resolution_at" in item for item in env["data"]["items"])


def test_resolve_pending_limit_validation(home):
    env = _envelope(home, "resolve.pending", {"limit": 2000})
    assert env["ok"] is False
    assert env["error"]["details"]["field"] == "limit"


# -- forecast.supersede --------------------------------------------------


def test_forecast_supersede_writes_edge(home):
    _, thesis_id = _setup_thesis(home)
    first = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.5},
        ],
    })
    sup = _envelope(home, "forecast.supersede", {
        "prior_forecast_id": first["data"]["id"],
        "kind": "binary",
        "yes_label": "YES",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.7},
            {"outcome_label": "NO", "probability": 0.3},
        ],
    })
    assert sup["ok"] is True
    assert sup["data"]["supersedes_prior_forecast_id"] == first["data"]["id"]


def test_forecast_supersede_atomic_when_edge_insert_fails(home):
    """Per bead trade-trace-re4: if the supersedes-edge insert fails
    (here forced by pre-inserting the chosen edge id), the replacement
    forecast row must NOT survive the transaction. Before this bead the
    replacement forecast committed in one UoW and the edge committed
    in a separate UoW, so a crash between them left an orphan
    replacement without lineage."""

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    _, thesis_id = _setup_thesis(home)
    first = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.5},
        ],
    })
    prior_id = first["data"]["id"]

    # Pre-insert an edge that will collide with the supersede handler's
    # second edge.created if both attempted to use the same id. Easier
    # alternative: monkey-patch new_id("edg") to a duplicate value, but
    # the simpler approach is to insert an edge row with a fixed id and
    # then patch the helper.
    duplicate_edge_id = "edg_force_collision_re4"
    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, "
            "target_id, edge_type, created_at, actor_id) "
            "VALUES (?, 'forecast', ?, 'forecast', ?, 'supersedes', "
            "'2026-05-19T00:00:00Z', 'agent:default')",
            (duplicate_edge_id, prior_id, prior_id),
        )
        db.connection.commit()
    finally:
        db.close()

    import trade_trace.tools.ledger.forecast as forecast_mod

    original_new_id = forecast_mod.new_id

    def _new_id(prefix: str) -> str:
        if prefix == "edg":
            return duplicate_edge_id
        return original_new_id(prefix)

    pre_forecast_count = _count_table(home, "forecasts")

    try:
        forecast_mod.new_id = _new_id
        env = _envelope(home, "forecast.supersede", {
            "prior_forecast_id": prior_id,
            "kind": "binary",
            "yes_label": "YES",
            "outcomes": [
                {"outcome_label": "YES", "probability": 0.7},
                {"outcome_label": "NO", "probability": 0.3},
            ],
        })
    finally:
        forecast_mod.new_id = original_new_id

    assert env["ok"] is False, (
        "forecast.supersede must surface a typed error when the "
        "supersedes edge cannot be inserted; got success envelope"
    )

    # Atomicity: the replacement forecast row did NOT commit.
    post_forecast_count = _count_table(home, "forecasts")
    assert post_forecast_count == pre_forecast_count, (
        f"replacement forecast row leaked despite edge failure: "
        f"pre={pre_forecast_count} post={post_forecast_count}"
    )


def _count_table(home, table: str) -> int:
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        return db.connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
    finally:
        db.close()


# -- end-to-end manual flow ----------------------------------------------


def test_manual_end_to_end_auto_scores(home):
    """The full M1 vertical: instrument → snapshot → thesis → forecast →
    decision → outcome (resolved_final) → forecast_scores row appears."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Will X happen by 2026-06-30?",
    })
    snap = _envelope(home, "snapshot.add", {
        "instrument_id": inst["data"]["id"],
        "captured_at": "2026-05-18T14:00:00Z",
        "price": 0.37,
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "Edge in thin-liquidity PM",
    })
    forecast = _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"],
        "kind": "binary",
        "resolution_at": "2026-06-30T00:00:00Z",
        "yes_label": "YES",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.6},
            {"outcome_label": "NO", "probability": 0.4},
        ],
    })
    _envelope(home, "decision.add", {
        "instrument_id": inst["data"]["id"],
        "thesis_id": thesis["data"]["id"],
        "forecast_id": forecast["data"]["id"],
        "snapshot_id": snap["data"]["id"],
        "type": "paper_enter",
        "side": "yes",
        "quantity": 100,
        "price": 0.37,
    })
    outcome = _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "YES",
        "outcome_value": 1.0,
        "status": "resolved_final",
        "confidence": 0.99,
    })
    assert outcome["ok"] is True
    # Auto-scoring should have fired.
    scored = outcome["data"]["auto_scored_forecasts"]
    assert len(scored) == 1
    record = scored[0]
    assert record["forecast_id"] == forecast["data"]["id"]
    assert record["failure_reason"] is None
    # YES probability was 0.6, outcome resolved YES; brier = (0.6-1)^2 = 0.16
    assert abs(record["score"] - 0.16) < 1e-9


def test_outcome_provisional_does_not_autoscore(home):
    """Per scoring.md §5 hard invariant: status != 'resolved_final' must
    leave forecast pending."""

    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    _envelope(home, "forecast.add", {
        "thesis_id": thesis["data"]["id"],
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.5},
        ],
    })
    out = _envelope(home, "outcome.add", {
        "instrument_id": inst["data"]["id"],
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "YES",
        "status": "resolved_provisional",
    })
    assert out["ok"] is True
    assert out["data"]["auto_scored_forecasts"] == []


def test_no_credential_args_accepted(home):
    """No tool surface accepts trading credentials. Inserting credential-
    shaped fields into any write tool's args either silently ignores them
    or surfaces no error path that allows credential storage."""

    venue = _envelope(home, "venue.add", {
        "name": "PM",
        "kind": "prediction_market",
        "api_key": "sk-leaky-key-PLEASE-NEVER-PERSIST",
        "wallet_seed": "twelve word mnemonic that should be rejected",
        "broker_token": "live-trading-token",
    })
    # The write succeeds because none of these are real tool args; they're
    # silently ignored. The point is: no schema PATH accepts them.
    assert venue["ok"] is True
    # Confirm nothing crept into the DB metadata_json or any other column.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(home), create_parent=False)
    try:
        cur = db.connection.execute(
            "SELECT metadata_json FROM venues WHERE id = ?", (venue["data"]["id"],)
        )
        row = cur.fetchone()
        meta = json.loads(row[0])
        assert "api_key" not in meta
        assert "wallet_seed" not in meta
        assert "broker_token" not in meta
    finally:
        db.close()


def test_forecast_supersede_replay_returns_original_replacement(home):
    """Per trade-trace-ug7p: replaying forecast.supersede with the same
    idempotency_key must return the original replacement forecast id and
    must NOT create a second forecast row, second edge row, or any extra
    events. Prior to the fix, the handler INSERTed the new forecast BEFORE
    consulting the event-log replay check, so retries corrupted lineage."""

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    _, thesis_id = _setup_thesis(home)
    first = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.5},
        ],
    })
    key = "ug7p-supersede-replay-v1"
    args = {
        "prior_forecast_id": first["data"]["id"],
        "kind": "binary",
        "yes_label": "YES",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.7},
            {"outcome_label": "NO", "probability": 0.3},
        ],
        "idempotency_key": key,
    }
    first_env = _envelope(home, "forecast.supersede", args)
    assert first_env["ok"] is True
    new_id = first_env["data"]["id"]

    # Snapshot row counts after the first call
    db = open_database(db_path(home))
    try:
        forecasts_before = db.connection.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
        edges_before = db.connection.execute(
            "SELECT COUNT(*) FROM edges WHERE edge_type='supersedes'"
        ).fetchone()[0]
        events_before = db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        db.close()

    # Replay with the same key. The replay path must return the original
    # replacement id and must not produce new rows.
    replay_env = _envelope(home, "forecast.supersede", args)
    assert replay_env["ok"] is True
    assert replay_env["data"]["id"] == new_id, (
        f"replay returned a different replacement id "
        f"({replay_env['data']['id']} != {new_id})"
    )
    assert replay_env["data"]["supersedes_prior_forecast_id"] == first["data"]["id"]
    assert replay_env["meta"].get("idempotent_replay") is True

    db = open_database(db_path(home))
    try:
        forecasts_after = db.connection.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
        edges_after = db.connection.execute(
            "SELECT COUNT(*) FROM edges WHERE edge_type='supersedes'"
        ).fetchone()[0]
        events_after = db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        db.close()
    assert forecasts_after == forecasts_before, (
        "replay created a second forecast row "
        f"(was {forecasts_before}, now {forecasts_after})"
    )
    assert edges_after == edges_before, (
        "replay created a second supersedes edge "
        f"(was {edges_before}, now {edges_after})"
    )
    assert events_after == events_before, (
        "replay appended new event rows "
        f"(was {events_before}, now {events_after})"
    )


def test_forecast_supersede_auto_scores_against_existing_resolved_final(home):
    """Per trade-trace-ld6l: a `forecast.supersede` issued AFTER a
    resolved_final outcome already landed must run the late-score path
    so the replacement forecast surfaces in calibration reports
    instead of staying pending forever."""

    inst_id, thesis_id = _setup_thesis(home)
    first = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.5},
        ],
    })

    # Resolve the outcome on the original forecast first.
    _envelope(home, "outcome.add", {
        "instrument_id": inst_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "YES",
        "status": "resolved_final",
        "confidence": 0.99,
    })

    # Now supersede the (already-scored) forecast. The new forecast
    # should auto-score against the existing outcome with
    # late_recorded=true.
    sup = _envelope(home, "forecast.supersede", {
        "prior_forecast_id": first["data"]["id"],
        "kind": "binary",
        "yes_label": "YES",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.8},
            {"outcome_label": "NO", "probability": 0.2},
        ],
    })
    assert sup["ok"] is True, sup
    assert "auto_scored" in sup["data"], (
        f"expected auto_scored in supersede result; got {sup['data']}"
    )
    score = sup["data"]["auto_scored"]
    # The score is computed against the YES probability; Brier
    # |1 - 0.8|^2 = 0.04.
    assert score["score"] == pytest.approx(0.04, abs=1e-6), score
    # Late-recorded flag is set (the outcome predates this forecast).
    assert score.get("late_recorded") is True, score


def test_forecast_supersede_event_order_with_late_auto_score(home):
    """Pin supersede event ordering including optional late forecast.scored."""

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    inst_id, thesis_id = _setup_thesis(home)
    first = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.5},
            {"outcome_label": "NO", "probability": 0.5},
        ],
    })
    _envelope(home, "outcome.add", {
        "instrument_id": inst_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "YES",
        "status": "resolved_final",
        "confidence": 0.99,
    })

    sup = _envelope(home, "forecast.supersede", {
        "prior_forecast_id": first["data"]["id"],
        "kind": "binary",
        "yes_label": "YES",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.8},
            {"outcome_label": "NO", "probability": 0.2},
        ],
    })
    assert sup["ok"] is True, sup
    assert "auto_scored" in sup["data"], sup
    replacement_id = sup["data"]["id"]

    db = open_database(db_path(home))
    try:
        rows = db.connection.execute(
            """
            SELECT event_type
            FROM events
            WHERE subject_id = ?
               OR (event_type = 'edge.created'
                   AND json_extract(payload_json, '$.source_id') = ?)
            ORDER BY id
            """,
            (replacement_id, replacement_id),
        ).fetchall()
    finally:
        db.close()

    assert [row[0] for row in rows] == [
        "forecast.created",
        "edge.created",
        "forecast.superseded",
        "forecast.scored",
    ]


def test_source_add_tool_schema_example_succeeds(home):
    """Per trade-trace-2ya5: `tool.schema --tool source.add` advertises
    an example payload that must succeed against the actual handler.
    Previously the example used `kind="news"` which the storage CHECK
    constraint rejected; the schema also did not enumerate the allowed
    kinds/stances, so the agent couldn't pick a valid value from the
    schema."""

    schema_env = _envelope(home, "tool.schema", {"tool": "source.add"})
    assert schema_env["ok"] is True, schema_env
    example = schema_env["data"]["example_minimal"]

    # The schema-advertised example must succeed against the journal as-is
    # (apart from the home arg the helper supplies).
    env = _envelope(home, "source.add", example)
    assert env["ok"] is True, (
        f"tool.schema example_minimal payload should succeed but got {env}"
    )

    # And the json_schema must enumerate the storage-pinned values for
    # `kind` so an agent can pick a valid choice without re-reading the
    # SQLite CHECK constraint.
    json_schema = schema_env["data"]["json_schema"]
    kind_enum = json_schema["properties"]["kind"].get("enum")
    assert kind_enum is not None
    assert set(kind_enum) >= {
        "news_article", "research_doc", "url", "note", "other",
    }
    stance_enum = json_schema["properties"]["stance"].get("enum")
    assert set(stance_enum) == {
        "supports", "contradicts", "neutral", "context", "resolution_rule",
        "official_source", "stale", "missing", "redacted", "sensitive",
    }
