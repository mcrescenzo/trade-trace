"""Smoke test: the package is importable and exposes the expected surface."""

from __future__ import annotations


def test_package_importable():
    import trade_trace

    assert isinstance(trade_trace.__version__, str)
    assert trade_trace.__version__ == "0.0.2"


def test_models_importable():
    from trade_trace.models import (
        Decision,
        DecisionType,
        Forecast,
        ForecastOutcome,
        MemoryNode,
        NodeType,
        Outcome,
        OutcomeStatus,
        Snapshot,
        Source,
        Strategy,
        Thesis,
    )

    # all 13 decision types from PRD §3.1 must be present
    assert {member.value for member in DecisionType} == {
        "watch",
        "skip",
        "paper_enter",
        "paper_exit",
        "actual_enter",
        "actual_exit",
        "add",
        "reduce",
        "hold",
        "invalidate_thesis",
        "update_thesis",
        "resolved",
        "review",
    }

    # all 3 memory node types from PRD §3.2 must be present
    assert {member.value for member in NodeType} == {
        "observation",
        "reflection",
        "playbook_rule",
    }

    # all 6 outcome statuses from scoring.md §5 must be present
    assert {member.value for member in OutcomeStatus} == {
        "resolved_final",
        "resolved_provisional",
        "ambiguous",
        "disputed",
        "void",
        "cancelled",
    }

    # smoke check that round-trips work
    dec = Decision(instrument_id="i_1", type=DecisionType.SKIP, reason="spread too wide")
    assert dec.type == DecisionType.SKIP

    node = MemoryNode(node_type=NodeType.OBSERVATION, body="NVDA gaps fade")
    assert node.body == "NVDA gaps fade"
    assert node.importance == 5

    # silence unused-import warnings for the classes we don't construct above
    _ = (
        Forecast,
        ForecastOutcome,
        Outcome,
        Snapshot,
        Source,
        Strategy,
        Thesis,
    )
