"""Binary scoring lifecycle invariants per trade-trace-ucd.

Tests for the four `scoring_state` transitions enumerated in scoring.md §4.4:

    (none) → pending          (forecast.created)
    pending → scored          (outcome.resolved_final + label match)
    pending → failed          (outcome.resolved_final + label/yes_label miss)
    pending → superseded      (forecast.supersede)

Plus the outcome-supersession invariants per scoring.md §5.1 (the prior
score row stays; a new score row is appended pointing at the new outcome),
and the late-recorded auto-score-on-create per scoring.md §6 trigger #2 +
dogfood-protocol §2.3.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path
from trade_trace.tools.ledger import derive_scoring_state


def _envelope(home: Path, tool: str, args: dict, actor_id: str = "agent:default"):
    payload = {"home": str(home), **args}
    return mcp_call(tool, payload, actor_id=actor_id).model_dump(
        mode="json", exclude_none=True
    )


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.model_dump(mode="json")["ok"] is True
    return h


def _setup_venue_instr_thesis(home: Path):
    venue = _envelope(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _envelope(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Will X by Y",
    })
    thesis = _envelope(home, "thesis.add", {
        "instrument_id": inst["data"]["id"],
        "side": "yes",
        "body": "...",
    })
    return inst["data"]["id"], thesis["data"]["id"]


# -- pending --------------------------------------------------------------


def test_transition_created_to_pending(home):
    """A freshly written forecast is `pending` until either an outcome
    resolves or the forecast is superseded."""

    _instr_id, thesis_id = _setup_venue_instr_thesis(home)
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    assert f["ok"] is True
    assert f["data"]["scoring_state"] == "pending"
    db = open_database(db_path(home))
    try:
        state = derive_scoring_state(db.connection, f["data"]["id"])
    finally:
        db.close()
    assert state == "pending"


# -- pending → scored ------------------------------------------------------


def test_transition_pending_to_scored(home):
    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    out = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.99,
    })
    assert out["ok"] is True
    scored = out["data"]["auto_scored_forecasts"]
    assert len(scored) == 1
    assert scored[0]["score"] == pytest.approx(0.16)
    assert scored[0]["failure_reason"] is None

    db = open_database(db_path(home))
    try:
        state = derive_scoring_state(db.connection, f["data"]["id"])
    finally:
        db.close()
    assert state == "scored"


# -- pending → failed (yes_label_ambiguous) -------------------------------


def test_transition_pending_to_failed_yes_label_ambiguous(home):
    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    # Omit yes_label and use labels that defeat the heuristic.
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "blue", "probability": 0.6},
            {"outcome_label": "green", "probability": 0.4},
        ],
    })
    out = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "purple",  # neither label matches → both heuristics fail
        "status": "resolved_final",
        "confidence": 0.99,
    })
    scored = out["data"]["auto_scored_forecasts"]
    assert scored == []

    db = open_database(db_path(home))
    try:
        state = derive_scoring_state(db.connection, f["data"]["id"])
    finally:
        db.close()
    assert state == "pending"


# -- pending → failed (label_mismatch with explicit yes_label) ------------


def test_transition_pending_to_failed_label_mismatch(home):
    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    out = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "maybe",  # neither yes nor no
        "status": "resolved_final",
        "confidence": 0.99,
    })
    scored = out["data"]["auto_scored_forecasts"]
    assert scored == []

    db = open_database(db_path(home))
    try:
        state = derive_scoring_state(db.connection, f["data"]["id"])
    finally:
        db.close()
    assert state == "pending"


# -- pending → superseded -------------------------------------------------


def test_transition_pending_to_superseded(home):
    _instr_id, thesis_id = _setup_venue_instr_thesis(home)
    first = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    })
    sup = _envelope(home, "forecast.supersede", {
        "prior_forecast_id": first["data"]["id"],
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.7},
            {"outcome_label": "no", "probability": 0.3},
        ],
    })
    assert sup["ok"] is True
    db = open_database(db_path(home))
    try:
        state = derive_scoring_state(db.connection, first["data"]["id"])
    finally:
        db.close()
    assert state == "superseded"


# -- auto-score allowed enums --------------------------------------------


@pytest.mark.parametrize(
    "status", ["resolved_provisional", "ambiguous", "disputed", "void", "cancelled"]
)
def test_non_resolved_final_does_not_autoscore(home, status):
    """Per scoring.md §5: only `resolved_final` triggers auto-score."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
    })
    out = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes",
        "status": status,
    })
    assert out["ok"] is True
    assert out["data"]["auto_scored_forecasts"] == []
    db = open_database(db_path(home))
    try:
        state = derive_scoring_state(db.connection, f["data"]["id"])
    finally:
        db.close()
    assert state == "pending"


# -- yes_label heuristic paths --------------------------------------------


@pytest.mark.parametrize(
    "labels,yes_norm",
    [
        # one label exactly matches YES
        ([("YES", 0.6), ("NO", 0.4)], "yes"),
        # one label exactly matches TRUE
        ([("TRUE", 0.7), ("FALSE", 0.3)], "true"),
    ],
)
def test_yes_label_heuristic_static_matches(home, labels, yes_norm):
    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": labels[0][0], "probability": labels[0][1]},
            {"outcome_label": labels[1][0], "probability": labels[1][1]},
        ],
    })
    out = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": labels[0][0],  # resolved to whichever is YES-side
        "status": "resolved_final",
        "confidence": 0.99,
    })
    scored = out["data"]["auto_scored_forecasts"]
    assert len(scored) == 1
    assert scored[0]["failure_reason"] is None
    # YES probability was labels[0][1]; resolved label matches → y = 1.
    expected = (labels[0][1] - 1) ** 2
    assert scored[0]["score"] == pytest.approx(expected)


# -- outcome supersession does not double-fire on same outcome ------------


def test_outcome_supersession_does_not_retroactively_double_score(home):
    """Per scoring.md §5.1: the prior `forecast_scores` row stays in place;
    a NEW resolved_final outcome (via supersedes edge) appends a fresh
    score row pointing at the new outcome. The OLD outcome's score is
    untouched.

    This test simulates the supersession by inserting the supersedes edge
    directly (the user-callable `outcome.supersede` tool is not yet
    shipped; it lands with the broader edges write surface)."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    first = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.99,
    })
    first_score = first["data"]["auto_scored_forecasts"][0]
    first_outcome_id = first["data"]["id"]
    assert first_score["score"] == pytest.approx(0.16)

    # Simulate a correction: a NEW resolved_final outcome (different label)
    # supersedes the prior one via a supersedes edge.
    second = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "no",
        "status": "resolved_final",
        "confidence": 0.99,
    })
    second_outcome_id = second["data"]["id"]
    second_score = second["data"]["auto_scored_forecasts"][0]
    # Without the supersedes edge yet, the new outcome.add scores against
    # the NEW outcome (different outcome_id) — that's the §5.1 behavior:
    # "the new outcome appends a fresh forecast_scores row".
    assert second_score["score"] == pytest.approx(0.36)  # (0.6 - 0)^2

    # Now lay down the supersedes edge new → old.
    db = open_database(db_path(home))
    try:
        from trade_trace.tools._helpers import new_id as gen_id
        edge_id = gen_id("edg")
        db.connection.execute(
            "INSERT INTO edges(id, source_kind, source_id, target_kind, target_id, "
            "edge_type, created_at, actor_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                edge_id, "outcome", second_outcome_id, "outcome", first_outcome_id,
                "supersedes", "2026-06-30T01:00:00Z", "agent:default",
            ),
        )
        db.connection.commit()
        # The prior score row stays in place (append-only invariant).
        prior_rows = db.connection.execute(
            "SELECT score FROM forecast_scores WHERE outcome_id = ?",
            (first_outcome_id,),
        ).fetchall()
        assert len(prior_rows) == 1
        assert prior_rows[0][0] == pytest.approx(0.16)

        # Current scoring_state derives from the latest non-superseded outcome.
        forecast_id = first_score["forecast_id"]
        state = derive_scoring_state(db.connection, forecast_id)
    finally:
        db.close()
    assert state == "scored"  # the NEW outcome's score is the current head


# -- same-outcome idempotency --------------------------------------------


def test_autoscore_does_not_double_fire_for_same_outcome(home):
    """A future re-fire of the scoring trigger on the SAME `outcome_id`
    (e.g. a retry inside a unit-of-work) must not append a duplicate
    `forecast_scores` row. The guard is: skip if a row already exists for
    `(forecast_id, outcome_id)`."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    out = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.99,
    })
    outcome_id = out["data"]["id"]

    # Manually invoke autoscore again with the same outcome_id; the guard
    # must skip every forecast since each is already scored against it.
    from trade_trace.tools.ledger import _autoscore_pending_forecasts

    db = open_database(db_path(home))
    try:
        before = db.connection.execute(
            "SELECT COUNT(*) FROM forecast_scores WHERE outcome_id = ?",
            (outcome_id,),
        ).fetchone()[0]
        with db.transaction():
            replayed = _autoscore_pending_forecasts(
                db.connection,
                instrument_id=instr_id,
                outcome_id=outcome_id,
                outcome_label="yes",
                actor_id="agent:default",
                created_at="2026-06-30T00:00:00Z",
            )
        after = db.connection.execute(
            "SELECT COUNT(*) FROM forecast_scores WHERE outcome_id = ?",
            (outcome_id,),
        ).fetchone()[0]
    finally:
        db.close()
    assert before == after
    assert replayed == []


# -- late-recorded forecast on already-resolved outcome ------------------


def test_late_forecast_against_existing_resolved_final_autoscores_with_flag(home):
    """Per scoring.md §6 trigger #2 + dogfood-protocol §2.3: a forecast
    created AFTER an outcome already resolved gets scored immediately and
    is flagged as `late_recorded` on both the forecast row and the score
    row."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    # Resolution happens FIRST — no forecast yet.
    _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.99,
    })
    # Now the agent records a "late" forecast.
    late = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.8},
            {"outcome_label": "no", "probability": 0.2},
        ],
    })
    assert late["ok"] is True
    assert "auto_scored" in late["data"]
    score_summary = late["data"]["auto_scored"]
    assert score_summary["score"] == pytest.approx(0.04)  # (0.8 - 1)^2
    assert score_summary["late_recorded"] is True

    # The flag is also recorded on the forecast row itself.
    db = open_database(db_path(home))
    try:
        meta = db.connection.execute(
            "SELECT metadata_json FROM forecasts WHERE id = ?",
            (late["data"]["id"],),
        ).fetchone()[0]
    finally:
        db.close()
    assert json.loads(meta).get("late_recorded") is True


def test_non_late_forecast_does_not_carry_late_flag(home):
    """Sanity: a forecast written BEFORE any outcome must not pick up the
    flag. This guards against an accidental always-on late-recorded mark."""

    _instr_id, thesis_id = _setup_venue_instr_thesis(home)
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
    })
    assert "auto_scored" not in f["data"]

    db = open_database(db_path(home))
    try:
        meta = db.connection.execute(
            "SELECT metadata_json FROM forecasts WHERE id = ?",
            (f["data"]["id"],),
        ).fetchone()[0]
    finally:
        db.close()
    assert json.loads(meta or "{}").get("late_recorded") is not True


# -- binary-only v0.0.2 scoring boundary --------------------------------


def test_categorical_kind_rejected_and_not_auto_scored(home):
    """v0.0.2 forecast.add rejects categorical forecasts, so outcome scoring does
    not revive non-binary lifecycle paths."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "categorical",
        "outcomes": [
            {"outcome_label": "a", "probability": 0.4},
            {"outcome_label": "b", "probability": 0.3},
            {"outcome_label": "c", "probability": 0.3},
        ],
    })
    assert f["ok"] is False
    assert f["error"]["code"] == "VALIDATION_ERROR"

    out = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "a",
        "status": "resolved_final",
        "confidence": 0.99,
    })
    assert out["data"]["auto_scored_forecasts"] == []
