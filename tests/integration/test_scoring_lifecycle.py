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


# -- pending → failed (writes a NULL-score row asserted on disk) ----------


def test_transition_pending_to_failed_yes_label_ambiguous_writes_score_row(home):
    """trade-trace-g4qu: the binary failure path that ACTUALLY reaches
    `_autoscore_pending_forecasts`. A binary forecast with no `yes_label`
    and labels the heuristic can't resolve (`blue`/`green`), resolved by a
    BINARY outcome label (`yes`, which `is_auto_scoreable_final` accepts),
    must (1) surface `failure_reason='yes_label_ambiguous'` with `score is
    None` on the result, (2) derive `scoring_state == 'failed'`, and (3)
    persist exactly one `forecast_scores` row with `score IS NULL` and
    `failure_reason` in `metadata_json`.

    The older `test_transition_pending_to_failed_yes_label_ambiguous`
    above uses a NON-binary outcome label (`purple`), so the outcome is
    not auto-scoreable and the failure_reason branch is never reached —
    this test closes that gap."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    # Binary, no yes_label, labels the §3.2 heuristic cannot resolve.
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "blue", "probability": 0.6},
            {"outcome_label": "green", "probability": 0.4},
        ],
    })
    forecast_id = f["data"]["id"]
    # Resolve with a BINARY label so is_auto_scoreable_final() is True and
    # the autoscorer actually runs (yet yes_norm stays unresolvable).
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
    assert scored[0]["forecast_id"] == forecast_id
    assert scored[0]["failure_reason"] == "yes_label_ambiguous"
    assert scored[0]["score"] is None

    outcome_id = out["data"]["id"]
    db = open_database(db_path(home))
    try:
        assert derive_scoring_state(db.connection, forecast_id) == "failed"
        rows = db.connection.execute(
            "SELECT score, metadata_json FROM forecast_scores "
            "WHERE forecast_id = ? AND outcome_id = ?",
            (forecast_id, outcome_id),
        ).fetchall()
        assert len(rows) == 1
        score, metadata_json = rows[0]
        assert score is None
        assert json.loads(metadata_json)["failure_reason"] == "yes_label_ambiguous"
    finally:
        db.close()


def test_transition_pending_to_failed_label_mismatch_writes_score_row(home):
    """trade-trace-g4qu: the canonical-probability `label_mismatch` failure
    branch (`_score_one_forecast` line ~230). A binary forecast whose
    `yes_label` resolves a canonical probability (`red`/`blue`, yes_label
    `red`) is resolved by a BINARY outcome label (`yes`) that is NOT one of
    the forecast's own outcome labels. The autoscorer runs (binary label =>
    auto_scoreable), computes `canonical_probability` is set but the
    resolved label is not in `{red, blue}`, and writes a NULL-score row
    flagged `label_mismatch`; `scoring_state` derives to `'failed'`.

    The older `test_transition_pending_to_failed_label_mismatch` above
    resolves with a NON-binary label (`maybe`), so the outcome is not
    auto-scoreable and this branch is never reached."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    # yes_label='red' makes _canonical_binary_probability set the forecast
    # row's `probability` column (canonical_probability is not None).
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "red",
        "outcomes": [
            {"outcome_label": "red", "probability": 0.6},
            {"outcome_label": "blue", "probability": 0.4},
        ],
    })
    forecast_id = f["data"]["id"]

    # Confirm the canonical probability column is populated, otherwise we'd
    # land in the yes_label_ambiguous branch instead of label_mismatch.
    db = open_database(db_path(home))
    try:
        canonical = db.connection.execute(
            "SELECT probability FROM forecasts WHERE id = ?", (forecast_id,),
        ).fetchone()[0]
        assert canonical is not None
    finally:
        db.close()

    # Resolve with a BINARY label ('yes') that is NOT in {red, blue}.
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
    assert scored[0]["forecast_id"] == forecast_id
    assert scored[0]["failure_reason"] == "label_mismatch"
    assert scored[0]["score"] is None

    outcome_id = out["data"]["id"]
    db = open_database(db_path(home))
    try:
        assert derive_scoring_state(db.connection, forecast_id) == "failed"
        rows = db.connection.execute(
            "SELECT score, metadata_json FROM forecast_scores "
            "WHERE forecast_id = ? AND outcome_id = ?",
            (forecast_id, outcome_id),
        ).fetchall()
        assert len(rows) == 1
        score, metadata_json = rows[0]
        assert score is None
        assert json.loads(metadata_json)["failure_reason"] == "label_mismatch"
    finally:
        db.close()


# -- pending → failed (legacy NULL outcome_label, legacy_has_null_label) --


def _null_one_forecast_outcome_label(home: Path, forecast_id: str) -> None:
    """Simulate historical/migration-drift corruption at the scoring layer:
    drop the append-only UPDATE trigger, relax the
    `forecast_outcomes.outcome_label NOT NULL` clause via `writable_schema`,
    and poke a NULL into one of this forecast's outcome rows. The test DB is
    throwaway, so neither the trigger nor the relaxed schema is restored."""

    db = open_database(db_path(home))
    try:
        conn = db.connection
        conn.execute("DROP TRIGGER IF EXISTS trg_forecast_outcomes_no_update")
        conn.execute("PRAGMA writable_schema = 1")
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='forecast_outcomes'",
        ).fetchone()
        assert row is not None, "forecast_outcomes table not found"
        relaxed = row[0].replace("outcome_label TEXT NOT NULL", "outcome_label TEXT")
        assert relaxed != row[0], "expected 'outcome_label TEXT NOT NULL' clause"
        conn.execute(
            "UPDATE sqlite_master SET sql=? WHERE type='table' AND name='forecast_outcomes'",
            (relaxed,),
        )
        conn.execute("PRAGMA writable_schema = 0")
        conn.commit()
    finally:
        db.close()

    # Fresh connection re-reads the relaxed schema, then write the NULL into
    # exactly one of this forecast's outcome rows.
    db = open_database(db_path(home))
    try:
        target = db.connection.execute(
            "SELECT id FROM forecast_outcomes WHERE forecast_id = ? "
            "ORDER BY id LIMIT 1",
            (forecast_id,),
        ).fetchone()
        assert target is not None, "no forecast_outcomes rows for forecast"
        db.connection.execute(
            "UPDATE forecast_outcomes SET outcome_label = NULL WHERE id = ?",
            (target[0],),
        )
        db.connection.commit()
    finally:
        db.close()


def test_legacy_null_outcome_label_scores_yes_label_ambiguous(home):
    """trade-trace-nyix: the `legacy_has_null_label` guard in
    `_score_one_forecast` (`_scoring.py:218,242`). A `forecast_outcomes`
    row with a NULL `outcome_label` (only reachable via legacy/corruption,
    since the column is NOT NULL) must drive the scorer down the
    `legacy_has_null_label` branch — `failure_reason='yes_label_ambiguous'`
    with `score is None` — rather than crashing on `.strip()` of None or
    silently computing a bogus Brier score.

    A well-formed binary forecast (`yes`/`no`, yes_label='yes') is seeded,
    then ONE of its outcome labels is NULLed on disk. When a binary outcome
    resolves the instrument, the autoscorer runs (binary label =>
    auto_scoreable) and must flag the corrupt forecast `yes_label_ambiguous`
    via the null-label guard, which takes priority over the otherwise-valid
    canonical-probability path."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    f = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.7},
            {"outcome_label": "no", "probability": 0.3},
        ],
    })
    forecast_id = f["data"]["id"]

    # Corrupt one outcome label to NULL on disk to reach the legacy guard.
    _null_one_forecast_outcome_label(home, forecast_id)

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
    assert scored[0]["forecast_id"] == forecast_id
    assert scored[0]["failure_reason"] == "yes_label_ambiguous"
    assert scored[0]["score"] is None

    outcome_id = out["data"]["id"]
    db = open_database(db_path(home))
    try:
        assert derive_scoring_state(db.connection, forecast_id) == "failed"
        rows = db.connection.execute(
            "SELECT score, metadata_json FROM forecast_scores "
            "WHERE forecast_id = ? AND outcome_id = ?",
            (forecast_id, outcome_id),
        ).fetchall()
        assert len(rows) == 1
        score, metadata_json = rows[0]
        assert score is None
        assert json.loads(metadata_json)["failure_reason"] == "yes_label_ambiguous"
    finally:
        db.close()


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


# -- superseded forecasts are never auto-scored (trade-trace-6g7v) -------


def test_superseded_forecast_not_autoscored_when_outcome_lands(home):
    """trade-trace-6g7v: when a forecast is superseded by a newer forecast
    and then an outcome resolves on the instrument, ONLY the replacement
    forecast is auto-scored. The prior (superseded) forecast must not get a
    score row — scoring it would pollute calibration (inflated N, distorted
    Brier/ECE/skill) and contradict its `superseded` logical state."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    prior = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    })
    prior_id = prior["data"]["id"]
    replacement = _envelope(home, "forecast.supersede", {
        "prior_forecast_id": prior_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.7},
            {"outcome_label": "no", "probability": 0.3},
        ],
    })
    assert replacement["ok"] is True
    replacement_id = replacement["data"]["id"]
    assert replacement_id != prior_id

    out = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.99,
    })
    assert out["ok"] is True
    scored = out["data"]["auto_scored_forecasts"]
    # Exactly one score row — for the replacement forecast only.
    assert len(scored) == 1
    assert scored[0]["forecast_id"] == replacement_id
    assert scored[0]["score"] == pytest.approx(0.09)  # (0.7 - 1)^2

    outcome_id = out["data"]["id"]
    db = open_database(db_path(home))
    try:
        # The superseded forecast has NO score row against this outcome.
        prior_scores = db.connection.execute(
            "SELECT COUNT(*) FROM forecast_scores "
            "WHERE forecast_id = ? AND outcome_id = ?",
            (prior_id, outcome_id),
        ).fetchone()[0]
        assert prior_scores == 0
        # And it has no score rows at all.
        assert db.connection.execute(
            "SELECT COUNT(*) FROM forecast_scores WHERE forecast_id = ?",
            (prior_id,),
        ).fetchone()[0] == 0
        assert derive_scoring_state(db.connection, prior_id) == "superseded"
        assert derive_scoring_state(db.connection, replacement_id) == "scored"
    finally:
        db.close()


def test_preexisting_superseded_forecast_score_excluded_from_calibration(home):
    """trade-trace-6g7v report mirror: even if a score row already exists
    for a superseded forecast (e.g. written by an older build before the
    auto-scorer guard landed), `report.calibration` must exclude it so N is
    not inflated and Brier/ECE/skill are not distorted. We inject the
    legacy score row directly to simulate that historical drift."""

    from trade_trace.tools._helpers import new_id as gen_id

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    prior = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    })
    prior_id = prior["data"]["id"]
    replacement = _envelope(home, "forecast.supersede", {
        "prior_forecast_id": prior_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.7},
            {"outcome_label": "no", "probability": 0.3},
        ],
    })
    assert replacement["ok"] is True

    out = _envelope(home, "outcome.add", {
        "instrument_id": instr_id,
        "resolved_at": "2026-06-30T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.99,
    })
    outcome_id = out["data"]["id"]

    # Simulate a legacy/pre-fix score row for the SUPERSEDED forecast.
    db = open_database(db_path(home))
    try:
        db.connection.execute(
            "INSERT INTO forecast_scores(id, forecast_id, outcome_id, metric, "
            "score, scored_at, actor_id, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                gen_id("fs"), prior_id, outcome_id, "brier_binary",
                0.2025,  # (0.55 - 1)^2
                "2026-06-30T00:00:00Z", "agent:default",
                json.dumps({"outcome_id": outcome_id}),
            ),
        )
        db.connection.commit()
        legacy_rows = db.connection.execute(
            "SELECT COUNT(*) FROM forecast_scores WHERE forecast_id = ?",
            (prior_id,),
        ).fetchone()[0]
        assert legacy_rows == 1  # the injected legacy score exists on disk
    finally:
        db.close()

    env = _envelope(home, "report.calibration", {})
    assert env["ok"] is True
    # Only the replacement forecast's score contributes; the superseded
    # forecast's (injected) score is filtered out → sample_size == 1.
    assert env["data"]["summary"]["sample_size"] == 1


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


# -- late_recorded_by_seconds is the REAL lag (trade-trace-d6rc) --------


def _insert_backdated_resolved_final_outcome(
    home: Path,
    *,
    instrument_id: str,
    outcome_label: str,
    created_at: str,
    resolved_at: str = "2026-01-01T00:00:00Z",
) -> str:
    """Insert a `resolved_final`, auto-scoreable outcome row directly with a
    controlled (backdated) `created_at`. The tool path stamps
    `created_at = now_iso()`, which would put the outcome and the late
    forecast microseconds apart and collapse the recording lag to ~0; this
    helper lets the regression assert a deterministic, large lag.

    The INSERT append-only trigger only forbids UPDATE/DELETE, so a
    backdated INSERT is permitted."""

    from trade_trace.tools._helpers import new_id as gen_id

    outcome_id = gen_id("out")
    db = open_database(db_path(home))
    try:
        db.connection.execute(
            "INSERT INTO outcomes(id, instrument_id, resolved_at, outcome_label, "
            "status, confidence, created_at, actor_id) "
            "VALUES (?, ?, ?, ?, 'resolved_final', 0.99, ?, 'agent:default')",
            (outcome_id, instrument_id, resolved_at, outcome_label, created_at),
        )
        db.connection.commit()
    finally:
        db.close()
    return outcome_id


def _epoch_seconds(ts: str) -> int:
    from datetime import datetime

    return int(
        datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    )


def test_late_forecast_add_records_real_late_by_seconds(home):
    """trade-trace-d6rc: the `forecast.add` late-trigger must compute
    `late_recorded_by_seconds` from the TRUE `outcomes.created_at`, not from
    `scored_at` (which equals the new forecast's `created_at`). When the
    outcome was recorded long before the forecast, the score row must carry
    a large, correct, non-zero lag — not 0.

    Before the fix, `scored_at` (== forecast.created_at) was passed as the
    outcome timestamp, so `forecast.created_at - outcome_created_at == 0`
    and the lag collapsed to 0 (unless `resolution_at` happened to be in
    the past). This asserts the recording lag equals
    `forecast.created_at - outcome.created_at`."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    outcome_created = "2026-01-01T00:00:00Z"
    # No resolution_at on the forecast => the lag is driven purely by the
    # outcome.created_at term, isolating the bug under test.
    outcome_id = _insert_backdated_resolved_final_outcome(
        home, instrument_id=instr_id, outcome_label="yes",
        created_at=outcome_created,
    )

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
    forecast_id = late["data"]["id"]
    assert late["data"]["auto_scored"]["late_recorded"] is True

    db = open_database(db_path(home))
    try:
        forecast_created = db.connection.execute(
            "SELECT created_at FROM forecasts WHERE id = ?", (forecast_id,)
        ).fetchone()[0]
        meta = db.connection.execute(
            "SELECT metadata_json FROM forecast_scores "
            "WHERE forecast_id = ? AND outcome_id = ?",
            (forecast_id, outcome_id),
        ).fetchone()[0]
    finally:
        db.close()

    expected = _epoch_seconds(forecast_created) - _epoch_seconds(outcome_created)
    assert expected > 0
    by_seconds = json.loads(meta)["late_recorded_by_seconds"]
    # The score row's lag must equal the real forecast-minus-outcome gap,
    # not 0. Allow ±1s of rounding slack from int(total_seconds()).
    assert abs(by_seconds - expected) <= 1
    assert by_seconds > 1000  # unambiguously non-zero, not the old bug value


def test_late_supersede_records_real_late_by_seconds(home):
    """trade-trace-d6rc: the `forecast.supersede` late-trigger has the same
    defect and the same fix — the replacement forecast scored against an
    already-resolved outcome must record the REAL recording lag from the
    outcome's `created_at`, not 0."""

    instr_id, thesis_id = _setup_venue_instr_thesis(home)
    # A prior forecast to supersede (written before any outcome exists).
    prior = _envelope(home, "forecast.add", {
        "thesis_id": thesis_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.55},
            {"outcome_label": "no", "probability": 0.45},
        ],
    })
    prior_id = prior["data"]["id"]

    outcome_created = "2026-01-01T00:00:00Z"
    outcome_id = _insert_backdated_resolved_final_outcome(
        home, instrument_id=instr_id, outcome_label="yes",
        created_at=outcome_created,
    )

    sup = _envelope(home, "forecast.supersede", {
        "prior_forecast_id": prior_id,
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.7},
            {"outcome_label": "no", "probability": 0.3},
        ],
    })
    assert sup["ok"] is True
    replacement_id = sup["data"]["id"]
    assert sup["data"]["auto_scored"]["late_recorded"] is True

    db = open_database(db_path(home))
    try:
        replacement_created = db.connection.execute(
            "SELECT created_at FROM forecasts WHERE id = ?", (replacement_id,)
        ).fetchone()[0]
        meta = db.connection.execute(
            "SELECT metadata_json FROM forecast_scores "
            "WHERE forecast_id = ? AND outcome_id = ?",
            (replacement_id, outcome_id),
        ).fetchone()[0]
    finally:
        db.close()

    expected = _epoch_seconds(replacement_created) - _epoch_seconds(outcome_created)
    assert expected > 0
    by_seconds = json.loads(meta)["late_recorded_by_seconds"]
    assert abs(by_seconds - expected) <= 1
    assert by_seconds > 1000


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
