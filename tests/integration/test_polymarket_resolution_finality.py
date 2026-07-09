from __future__ import annotations

from pathlib import Path

from trade_trace.contracts.envelope import SuccessEnvelope
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _mcp(home: str, tool: str, args: dict[str, object]) -> SuccessEnvelope:
    env = mcp_call(tool, {"home": home, **args}, actor_id="agent:test")
    assert isinstance(env, SuccessEnvelope), env
    return env


def _seed_pm_market(home: str, external_id: str = "pm-finality-1") -> str:
    market = _mcp(home, "market.bind", {
        "source": "polymarket",
        "external_id": external_id,
        "title": "Will finality modeling work?",
        "question": "Will finality modeling work?",
        "state": "closed_for_trading",
        "mechanism": "clob",
        "bound_via": "manual",
        "close_at": "2020-01-01T00:00:00Z",
        "resolution_rule": {"text": "Official rules decide YES.", "provenance": "caller_supplied"},
        "condition_id": f"0x{external_id}",
        "outcome_ids_by_label": {"yes": "1", "no": "2"},
    }).data
    return str(market["instrument_id"])


def _seed_binary_forecast(home: str, instrument_id: str) -> str:
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": instrument_id,
        "side": "yes",
        "body": "local calibration thesis",
    }).data
    forecast = _mcp(home, "forecast.add", {
        "thesis_id": thesis["id"],
        "kind": "binary",
        "yes_label": "yes",
        "resolution_at": "2020-01-02T00:00:00Z",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    }).data
    return str(forecast["id"])


def test_polymarket_finality_statuses_are_local_evidence_and_reported(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    instrument_id = _seed_pm_market(home)

    provisional = _mcp(home, "resolution.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-02T00:00:00Z",
        "outcome_label": "yes",
        "status": "proposed",
        "source": "polymarket_import",
        "confidence": 0.8,
        "metadata_json": {
            "as_of": "2020-01-02T00:00:00Z",
            "retrieved_at": "2020-01-02T00:01:00Z",
            "imported_at": "2020-01-02T00:02:00Z",
            "provenance": {"kind": "official_rule", "ref": "pm-finality-1"},
        },
    }).data
    assert provisional["finality_uncertain"] is True
    assert provisional["auto_scored_forecasts"] == []
    assert provisional["auto_scoreable"] is False

    imported = _mcp(home, "resolution.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-03T00:00:00Z",
        "outcome_label": "yes",
        "status": "imported_settled",
        "source": "local_import",
        "confidence": 0.95,
        "metadata_json": {"imported_at": "2020-01-03T00:01:00Z", "evidence_only": True},
    }).data
    assert imported["finality_uncertain"] is True
    assert imported["auto_scoreable"] is False

def test_resolved_final_requires_explicit_high_confidence_to_auto_score(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    instrument_id = _seed_pm_market(home, "pm-finality-confidence")
    forecast_id = _seed_binary_forecast(home, instrument_id)

    missing_conf = _mcp(home, "resolution.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-02T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "idempotency_key": "missing-confidence",
    }).data
    assert missing_conf["auto_scoreable"] is False
    assert missing_conf["finality_uncertain"] is True
    assert missing_conf["auto_scored_forecasts"] == []
    # The missing-confidence trap must self-diagnose at the point of failure
    # rather than silently writing no score (AX-030).
    assert "confidence is missing" in missing_conf["auto_score_skipped_reason"]
    pending = _mcp(home, "resolve.pending", {}).data
    assert forecast_id in {item["forecast_id"] for item in pending["items"]}

    low_conf = _mcp(home, "resolution.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-03T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.89,
    }).data
    assert low_conf["auto_scoreable"] is False
    assert low_conf["finality_uncertain"] is True
    assert low_conf["auto_scored_forecasts"] == []
    assert "below the 0.9 auto-score threshold" in low_conf["auto_score_skipped_reason"]

    high_conf = _mcp(home, "resolution.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-04T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": "0.90",
    }).data
    assert high_conf["auto_scoreable"] is True
    assert high_conf["finality_uncertain"] is False
    assert high_conf["auto_score_skipped_reason"] is None
    assert [score["forecast_id"] for score in high_conf["auto_scored_forecasts"]] == [forecast_id]


def test_malformed_confidence_resolved_final_does_not_score_or_hide_pending(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    instrument_id = _seed_pm_market(home, "pm-finality-malformed-confidence")
    forecast_id = _seed_binary_forecast(home, instrument_id)

    db = open_database(db_path(Path(home)))
    try:
        db.connection.execute(
            """
            INSERT INTO outcomes(
                id, instrument_id, resolved_at, outcome_label, outcome_value,
                status, source, confidence, metadata_json, created_at, actor_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "out_malformed_confidence",
                instrument_id,
                "2020-01-02T00:00:00Z",
                "yes",
                None,
                "resolved_final",
                "test",
                "0.95abc",
                "{}",
                "2020-01-02T00:01:00Z",
                "agent:test",
            ),
        )
        db.connection.commit()
    finally:
        db.close()

    late_forecast = _seed_binary_forecast(home, instrument_id)
    pending = _mcp(home, "resolve.pending", {}).data
    pending_ids = {item["forecast_id"] for item in pending["items"]}
    assert forecast_id in pending_ids
    assert late_forecast in pending_ids

def test_resolve_pending_excludes_already_scored_forecast(tmp_path):
    """Regression for trade-trace-2b0z: a forecast that already has a real
    `forecast_scores` row (non-NULL score against a non-superseded outcome)
    must NOT reappear in `resolve.pending`.

    Before the fix, `_resolve_pending` filtered on
    `f.scoring_state = 'pending'`, which is a no-op because the append-only
    trigger keeps the persisted column at 'pending' forever; the only real
    exclusion was a Python instrument-level check for an *auto-scoreable*
    resolved_final outcome. So a forecast scored against an outcome that is
    not auto-scoreable (e.g. an `imported_settled` evidence outcome, or a
    sub-threshold-confidence resolution) reappeared as if unscored. The
    accurate NOT EXISTS over `forecast_scores` now excludes it, while a
    sibling forecast that has no score still surfaces.
    """

    def _seed_distinct_forecast(body: str, prob: float) -> str:
        thesis = _mcp(home, "thesis.add", {
            "instrument_id": instrument_id, "side": "yes", "body": body,
        }).data
        forecast = _mcp(home, "forecast.add", {
            "thesis_id": thesis["id"], "kind": "binary", "yes_label": "yes",
            "resolution_at": "2020-01-02T00:00:00Z",
            "outcomes": [
                {"outcome_label": "yes", "probability": prob},
                {"outcome_label": "no", "probability": round(1.0 - prob, 4)},
            ],
        }).data
        return str(forecast["id"])

    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    instrument_id = _seed_pm_market(home, "pm-finality-already-scored")
    # Two distinct forecasts (different theses + probabilities) so their
    # content-derived IDs differ — otherwise idempotent seeding collapses
    # them to one row.
    scored_forecast = _seed_distinct_forecast("scored thesis", 0.6)
    unscored_forecast = _seed_distinct_forecast("unscored thesis", 0.7)
    assert scored_forecast != unscored_forecast

    # An evidence-only, non-auto-scoreable resolved outcome: the Python
    # instrument-level guard in _resolve_pending will NOT exclude either
    # forecast on its own.
    outcome = _mcp(home, "resolution.add", {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-03T00:00:00Z",
        "outcome_label": "yes",
        "status": "imported_settled",
        "source": "local_import",
        "confidence": 0.95,
        "metadata_json": {"imported_at": "2020-01-03T00:01:00Z", "evidence_only": True},
    }).data
    assert outcome["auto_scoreable"] is False
    assert outcome["auto_scored_forecasts"] == []

    # Directly append a real score row for ONE forecast (as a prior scorer
    # run would have). Append-only path: a single INSERT, no UPDATE.
    db = open_database(db_path(Path(home)))
    try:
        db.connection.execute(
            """
            INSERT INTO forecast_scores(
                id, forecast_id, outcome_id, metric, score, scored_at,
                actor_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "fs_already_scored",
                scored_forecast,
                outcome["id"],
                "brier",
                0.16,
                "2020-01-03T00:02:00Z",
                "agent:test",
                "{}",
            ),
        )
        db.connection.commit()
    finally:
        db.close()

    pending = _mcp(home, "resolve.pending", {}).data
    pending_ids = {item["forecast_id"] for item in pending["items"]}
    # The scored forecast is excluded; the unscored sibling still surfaces.
    assert scored_forecast not in pending_ids
    assert unscored_forecast in pending_ids


def test_outcome_add_idempotent_replay_preserves_finality_shape(tmp_path):
    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok
    instrument_id = _seed_pm_market(home, "pm-finality-replay")
    args = {
        "instrument_id": instrument_id,
        "resolved_at": "2020-01-02T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.99,
        "idempotency_key": "finality-replay",
    }

    first = _mcp(home, "resolution.add", args).data
    replay = _mcp(home, "resolution.add", args).data
    assert replay["id"] == first["id"]
    assert replay["auto_scoreable"] == first["auto_scoreable"] is True
    assert replay["finality_uncertain"] == first["finality_uncertain"] is False
    assert set(first) == set(replay)


def _seed_unscored_forecast(home: str, instrument_id: str, forecast_id: str) -> str:
    """Insert a forecast that auto-scoring will NEVER touch — a binary
    `scoring_support='unsupported'` row (excluded by the
    `f.scoring_support = 'supported'` filter in
    `_autoscore_pending_forecasts`, _scoring.py:125). It has a
    `resolution_at` so `resolve.pending`'s SQL surfaces it, but no
    `forecast_scores` row is ever written for it, so the SQL
    `NOT EXISTS (... forecast_scores ...)` exclusion (outcome.py:217-231)
    cannot suppress it. Only the Python instrument-level guard
    (outcome.py:245-249) can.
    """

    thesis = _mcp(home, "thesis.add", {
        "instrument_id": instrument_id,
        "side": "yes",
        "body": "unsupported-forecast thesis (never auto-scored)",
    }).data
    db = open_database(db_path(Path(home)))
    try:
        db.connection.execute(
            """
            INSERT INTO forecasts (
                id, thesis_id, kind, resolution_at, yes_label,
                resolution_rule_text, scoring_support, scoring_state,
                metadata_json, created_at, actor_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                forecast_id,
                str(thesis["id"]),
                "binary",
                "2020-01-02T00:00:00Z",
                "yes",
                "caller supplies outcome",
                "unsupported",
                "pending",
                "{}",
                "2020-01-01T00:02:00Z",
                "agent:test",
            ),
        )
        db.connection.commit()
    finally:
        db.close()
    return forecast_id


def test_resolve_pending_suppresses_auto_scoreable_final_outcome(tmp_path):
    """Dedicated coverage for the instrument-level suppression filter in
    `_resolve_pending` (src/trade_trace/tools/ledger/outcome.py:245-249):
    a forecast whose instrument has an *auto-scoreable* `resolved_final`
    outcome (status=resolved_final, confidence>=0.9, binary label) must be
    suppressed from `resolve.pending`, while a forecast under a
    *low-confidence* (sub-threshold) resolved outcome must still surface.

    Case 1 (the suppression assertion) MUST isolate the Python guard, not
    the SQL `forecast_scores` exclusion path (bead trade-trace-e9yf). An
    auto-*supported* high-confidence forecast would be scored by
    `_autoscore_pending_forecasts` the moment the outcome lands, so
    `resolve.pending`'s `NOT EXISTS (... forecast_scores ...)` SQL clause
    would already exclude it BEFORE the Python loop runs — leaving the
    filter with zero coverage (a mutation of its `continue`→`pass` would
    stay green). We instead point Case 1 at a `scoring_support='unsupported'`
    forecast that auto-scoring never touches (so no `forecast_scores` row
    exists), meaning ONLY the Python `_is_auto_scoreable_final` guard can
    keep it out of `resolve.pending`. Turning the `continue` at
    outcome.py:249 into `pass` therefore makes this test FAIL.

    Each case uses a separate instrument so the high-confidence outcome on
    the first cannot mask the low-confidence forecast on the second
    (the filter keys on `t.instrument_id`). bead trade-trace-0qau / -e9yf.
    """

    home = str(tmp_path / "home")
    assert mcp_call("journal.init", {"home": home}, actor_id="agent:test").ok

    # Case 1: high-confidence (>=0.9) resolved_final auto-scoreable outcome
    # → an UNSCORED forecast on that instrument is suppressed from
    # resolve.pending purely by the Python instrument-level guard.
    high_instrument = _seed_pm_market(home, "pm-finality-suppress-high")
    # A normal supported forecast (gets auto-scored → excluded by SQL) and a
    # never-scored unsupported forecast (only the Python guard can hide it).
    high_supported = _seed_binary_forecast(home, high_instrument)
    high_unscored = _seed_unscored_forecast(
        home, high_instrument, "fc_suppress_unscored",
    )
    pending_before = _mcp(home, "resolve.pending", {}).data
    pending_before_ids = {item["forecast_id"] for item in pending_before["items"]}
    # Both forecasts are pending before the outcome lands.
    assert high_supported in pending_before_ids
    assert high_unscored in pending_before_ids

    high_outcome = _mcp(home, "resolution.add", {
        "instrument_id": high_instrument,
        "resolved_at": "2020-01-02T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.95,
        "idempotency_key": "suppress-high-confidence",
    }).data
    assert high_outcome["auto_scoreable"] is True
    # Only the supported forecast was auto-scored; the unsupported one is
    # NOT in forecast_scores, so its later absence proves the Python guard.
    assert [s["forecast_id"] for s in high_outcome["auto_scored_forecasts"]] == [
        high_supported
    ]
    db = open_database(db_path(Path(home)))
    try:
        scored_ids = {
            r[0]
            for r in db.connection.execute(
                "SELECT forecast_id FROM forecast_scores"
            ).fetchall()
        }
    finally:
        db.close()
    assert high_unscored not in scored_ids

    # Case 2: low-confidence (< 0.9) resolved_final outcome on a *separate*
    # instrument → that forecast still appears in resolve.pending.
    low_instrument = _seed_pm_market(home, "pm-finality-suppress-low")
    low_forecast = _seed_binary_forecast(home, low_instrument)
    low_outcome = _mcp(home, "resolution.add", {
        "instrument_id": low_instrument,
        "resolved_at": "2020-01-02T00:00:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "confidence": 0.5,
        "idempotency_key": "suppress-low-confidence",
    }).data
    assert low_outcome["auto_scoreable"] is False

    pending = _mcp(home, "resolve.pending", {}).data
    pending_ids = {item["forecast_id"] for item in pending["items"]}
    # Case 1 assertion (isolates the Python guard): the unscored forecast on
    # the auto-scoreable instrument is gone, even though it has NO score row.
    # If outcome.py:249 `continue` becomes `pass`, this forecast reappears
    # and the assertion fails — exactly the mutation the bead requires.
    assert high_unscored not in pending_ids
    # The supported sibling is also gone (via the SQL forecast_scores path).
    assert high_supported not in pending_ids
    # Case 2 assertion: the low-confidence instrument's forecast remains.
    assert low_forecast in pending_ids
