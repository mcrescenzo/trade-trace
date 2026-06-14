"""M1/M3 model-constraint pass + migration-policy enum sync (trade-trace-w251).

The M0 ledger/memory model stubs shipped with ``extra='allow'`` and no
constraint enforcement, deferring enforcement to the write-tool boundary. This
suite locks in the M1/M3 tightening:

- ``extra='forbid'`` rejects unknown top-level fields (required-field-matrix).
- Bi-temporal validity: ``valid_to`` must not precede ``valid_from``.
- Enum exhaustion: ``StrEnum`` fields reject out-of-set values.

It also pins the migration-policy guard: ``CLOSED_ENUMS['outcomes.status']`` must
stay in lockstep with the ``OutcomeStatus`` enum and the m025 DB CHECK
constraint, closing the guard gap where the four
PROPOSED/PROVISIONAL/IMPORTED_REDEEMED/IMPORTED_SETTLED statuses were accepted by
the live schema but invisible to the policy layer.
"""

from __future__ import annotations

from datetime import datetime, timedelta

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
    Source,
    Strategy,
    Thesis,
)
from trade_trace.models.memory import MemoryNode, NodeType
from trade_trace.storage.migrations.m025_polymarket_resolution_finality import (
    _OUTCOME_STATUSES,
)
from trade_trace.storage.policy import CLOSED_ENUMS

_T0 = datetime(2026, 1, 1, 0, 0, 0)
_T1 = _T0 + timedelta(days=1)


# -- 1. extra='forbid' (required-field-matrix enforcement) ----------------


def test_ledger_row_models_forbid_unknown_fields():
    """Every ledger model rejects undeclared top-level fields."""

    with pytest.raises(ValidationError):
        Decision(instrument_id="i_1", type=DecisionType.SKIP, not_a_column=1)
    with pytest.raises(ValidationError):
        Thesis(instrument_id="i_1", side="yes", body="b", bogus="x")
    with pytest.raises(ValidationError):
        Forecast(thesis_id="t_1", unexpected=True)
    with pytest.raises(ValidationError):
        Outcome(
            instrument_id="i_1",
            resolved_at=_T0,
            outcome_label="yes",
            status=OutcomeStatus.RESOLVED_FINAL,
            stray=1,
        )
    with pytest.raises(ValidationError):
        Snapshot(instrument_id="i_1", captured_at=_T0, junk=1)
    with pytest.raises(ValidationError):
        Source(kind="article", junk=1)
    with pytest.raises(ValidationError):
        Strategy(name="n", slug="s", junk=1)
    with pytest.raises(ValidationError):
        ForecastOutcome(outcome_label="yes", probability=0.6, junk=1)


def test_memory_node_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        MemoryNode(node_type=NodeType.OBSERVATION, body="x", not_a_column=1)


def test_forbid_does_not_block_structured_json_payloads():
    """``extra='forbid'`` only forbids unknown *top-level* fields; the explicit
    JSON dict fields still accept arbitrary nested structure."""

    dec = Decision(
        instrument_id="i_1",
        type=DecisionType.SKIP,
        metadata_json={"free": "form", "nested": {"k": [1, 2, 3]}},
    )
    assert dec.metadata_json["nested"]["k"] == [1, 2, 3]

    node = MemoryNode(
        node_type=NodeType.REFLECTION,
        body="b",
        meta_json={"scope": {"instrument_id": "i_1"}},
    )
    assert node.meta_json["scope"]["instrument_id"] == "i_1"


# -- 2. Bi-temporal validity ----------------------------------------------


@pytest.mark.parametrize(
    "factory",
    [
        lambda vf, vt: Thesis(
            instrument_id="i_1", side="yes", body="b", valid_from=vf, valid_to=vt
        ),
        lambda vf, vt: Forecast(thesis_id="t_1", valid_from=vf, valid_to=vt),
        lambda vf, vt: MemoryNode(
            node_type=NodeType.OBSERVATION, body="b", valid_from=vf, valid_to=vt
        ),
    ],
)
def test_inverted_bitemporal_interval_rejected(factory):
    """``valid_to`` strictly before ``valid_from`` is rejected on every
    belief-shaped model carrying the bi-temporal pair."""

    with pytest.raises(ValidationError, match="bi-temporal"):
        factory(_T1, _T0)


@pytest.mark.parametrize(
    "factory",
    [
        lambda vf, vt: Thesis(
            instrument_id="i_1", side="yes", body="b", valid_from=vf, valid_to=vt
        ),
        lambda vf, vt: Forecast(thesis_id="t_1", valid_from=vf, valid_to=vt),
        lambda vf, vt: MemoryNode(
            node_type=NodeType.OBSERVATION, body="b", valid_from=vf, valid_to=vt
        ),
    ],
)
def test_valid_bitemporal_intervals_accepted(factory):
    """An ordered interval, an instantaneous (equal) interval, and an open-ended
    (``valid_to`` omitted) interval are all accepted."""

    factory(_T0, _T1)  # ordered
    factory(_T0, _T0)  # half-open empty interval is permitted
    factory(_T0, None)  # open-ended validity


# -- 3. Enum exhaustion ---------------------------------------------------


def test_decision_type_enum_exhaustion():
    with pytest.raises(ValidationError):
        Decision(instrument_id="i_1", type="not_a_decision_type")


def test_outcome_status_enum_exhaustion():
    with pytest.raises(ValidationError):
        Outcome(
            instrument_id="i_1",
            resolved_at=_T0,
            outcome_label="yes",
            status="not_a_status",
        )


def test_node_type_enum_exhaustion():
    with pytest.raises(ValidationError):
        MemoryNode(node_type="not_a_node_type", body="b")


def test_every_outcome_status_value_is_constructable():
    for status in OutcomeStatus:
        Outcome(
            instrument_id="i_1",
            resolved_at=_T0,
            outcome_label="yes",
            status=status,
        )


# -- 4. Migration-policy enum sync (the guard-gap close) ------------------


def test_closed_enum_outcomes_status_matches_model_enum():
    """``CLOSED_ENUMS['outcomes.status']`` must equal the ``OutcomeStatus``
    enum value set — otherwise the migration-policy guard is blind to statuses
    the model and schema already accept."""

    assert CLOSED_ENUMS["outcomes.status"] == {s.value for s in OutcomeStatus}


def test_closed_enum_outcomes_status_matches_m025_check_constraint():
    """The policy constant must match the DB CHECK constraint the m025 migration
    builds; the four finality statuses added by m025 must be present here too."""

    assert CLOSED_ENUMS["outcomes.status"] == set(_OUTCOME_STATUSES)
    for added in ("proposed", "provisional", "imported_redeemed", "imported_settled"):
        assert added in CLOSED_ENUMS["outcomes.status"]
