"""Unit-level field-validation and construction tests for ledger models
(trade-trace-1kuf).

Before this suite the only model coverage was ``test_smoke.py`` (one
``Decision`` construct + import references) and the integration-level
``test_model_constraints_w251.py`` (extra='forbid', bi-temporal, enum
exhaustion, policy enum-sync). This unit suite closes the remaining
field-level gaps that neither covered:

- required-field enforcement (missing required column -> ``ValidationError``);
- the extra-field contract on ``_Row`` subclasses (NOTE: the M1 ``w251`` pass
  flipped ``_Row`` from ``extra='allow'`` to ``extra='forbid'``, so the
  meaningful contract is now *rejection* of unknown top-level keys while the
  explicit ``metadata_json`` dict still round-trips arbitrary structure);
- ``ForecastOutcome`` probability boundary values (0.0 and 1.0);
- non-binary ``Forecast.kind`` stored verbatim as a string;
- ``OutcomeStatus`` coercion from a raw string value;
- ``DecisionType`` exhaustiveness vs. ``allowed_decision_types()`` so a drift
  between the ``StrEnum`` and the runtime decision matrix is caught.

These are pure-Pydantic unit tests; no DB fixture is required.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from trade_trace.models.ledger import (
    Decision,
    DecisionType,
    Forecast,
    ForecastOutcome,
    Outcome,
    OutcomeStatus,
    Snapshot,
    Thesis,
)
from trade_trace.tools.decision_matrix import allowed_decision_types

_T0 = datetime(2026, 1, 1, 0, 0, 0)


# -- 1. Required-field enforcement ----------------------------------------


def test_snapshot_requires_instrument_id_and_captured_at():
    """``Snapshot`` declares ``instrument_id`` and ``captured_at`` with no
    default, so omitting either is a ``ValidationError`` naming the field."""

    with pytest.raises(ValidationError) as missing_instrument:
        Snapshot(captured_at=_T0)
    assert "instrument_id" in str(missing_instrument.value)

    with pytest.raises(ValidationError) as missing_captured:
        Snapshot(instrument_id="i_1")
    assert "captured_at" in str(missing_captured.value)


def test_thesis_requires_side_and_body():
    with pytest.raises(ValidationError) as exc:
        Thesis(instrument_id="i_1")
    message = str(exc.value)
    assert "side" in message
    assert "body" in message


def test_outcome_requires_status():
    with pytest.raises(ValidationError) as exc:
        Outcome(instrument_id="i_1", resolved_at=_T0, outcome_label="yes")
    assert "status" in str(exc.value)


def test_required_fields_present_construct_cleanly():
    """The required-field matrix is satisfied by the minimal declared set."""

    snap = Snapshot(instrument_id="i_1", captured_at=_T0)
    assert snap.instrument_id == "i_1"
    thesis = Thesis(instrument_id="i_1", side="yes", body="thesis body")
    assert thesis.side == "yes"


# -- 2. Extra-field contract on _Row (w251: extra='forbid') ---------------


def test_row_subclass_rejects_unknown_top_level_field():
    """``_Row`` is ``extra='forbid'`` since the w251 constraint pass, so an
    undeclared top-level key is rejected rather than silently retained."""

    with pytest.raises(ValidationError) as exc:
        Decision(instrument_id="i_1", type=DecisionType.SKIP, not_a_column="x")
    assert "not_a_column" in str(exc.value)


def test_metadata_json_round_trips_arbitrary_structure():
    """``extra='forbid'`` only forbids unknown *top-level* fields; the explicit
    ``metadata_json`` dict still round-trips arbitrary nested structure via
    ``model_dump`` (the structured-payload escape hatch)."""

    payload = {"free": "form", "nested": {"k": [1, 2, 3]}}
    dec = Decision(
        instrument_id="i_1", type=DecisionType.SKIP, metadata_json=payload
    )
    dumped = dec.model_dump()
    assert dumped["metadata_json"] == payload
    # full round-trip through a re-validated model preserves the payload
    assert Decision(**dumped).metadata_json["nested"]["k"] == [1, 2, 3]


# -- 3. ForecastOutcome probability boundaries ----------------------------


@pytest.mark.parametrize("probability", [0.0, 1.0])
def test_forecast_outcome_accepts_probability_boundaries(probability):
    """The closed ``[0.0, 1.0]`` boundary values are valid probabilities."""

    outcome = ForecastOutcome(outcome_label="yes", probability=probability)
    assert outcome.probability == probability


def test_forecast_outcome_round_trips_optional_bounds():
    outcome = ForecastOutcome(
        outcome_label="yes", probability=0.5, lower_bound=0.4, upper_bound=0.6
    )
    dumped = outcome.model_dump()
    assert dumped["lower_bound"] == 0.4
    assert dumped["upper_bound"] == 0.6


# -- 4. Non-binary Forecast.kind stored as string -------------------------


def test_forecast_kind_defaults_to_binary():
    assert Forecast(thesis_id="t_1").kind == "binary"


def test_forecast_non_binary_kind_stored_verbatim():
    """``kind`` is a free string field, not an enum, so a non-binary kind such
    as ``"scalar"`` is stored verbatim (the categorical/scalar surface)."""

    forecast = Forecast(thesis_id="t_1", kind="scalar")
    assert forecast.kind == "scalar"
    assert forecast.model_dump()["kind"] == "scalar"


# -- 5. OutcomeStatus coercion from raw string ----------------------------


def test_outcome_status_coerces_from_raw_string():
    """A raw string matching an ``OutcomeStatus`` member coerces to the enum."""

    outcome = Outcome(
        instrument_id="i_1",
        resolved_at=_T0,
        outcome_label="yes",
        status="resolved_final",
    )
    assert outcome.status is OutcomeStatus.RESOLVED_FINAL
    assert outcome.status == "resolved_final"


def test_outcome_status_rejects_unknown_raw_string():
    with pytest.raises(ValidationError):
        Outcome(
            instrument_id="i_1",
            resolved_at=_T0,
            outcome_label="yes",
            status="not_a_status",
        )


# -- 6. DecisionType exhaustiveness vs allowed_decision_types() ------------


def test_decision_type_enum_matches_allowed_decision_types():
    """The ``DecisionType`` ``StrEnum`` and the runtime decision matrix must
    expose exactly the same set of decision types — a drift between the two
    (a type accepted by the model but absent from the matrix, or vice versa)
    would otherwise go undetected."""

    assert {member.value for member in DecisionType} == set(allowed_decision_types())


def test_every_allowed_decision_type_constructs():
    """Every type the runtime matrix advertises is constructable on a
    ``Decision`` and coerces to its enum member."""

    for decision_type in allowed_decision_types():
        decision = Decision(instrument_id="i_1", type=decision_type)
        assert decision.type == decision_type
        assert decision.type is DecisionType(decision_type)
