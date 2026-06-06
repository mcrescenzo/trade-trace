"""Golden pin: on a truly empty journal, `report.bootstrap` surfaces a
first-run onboarding breadcrumb pointing at the entry sequence
(market.search -> market.bind -> snapshot.fetch -> forecast.add), and a
non-empty journal is left unchanged (trade-trace-xqjv).

Before this, a cold bot driving "bootstrap-first" got only
continuity/read suggested_process_calls (report.work_queue,
agent.next_actions, report.recall_receipts, strategy.show) — every one
of which returns empty on a fresh journal — so there was NO surfaced
path to BEGIN the loop and the bot had to read docs out-of-band. The
breadcrumb is a process-call hint, not a fetch or advice: the tools are
listed (never invoked), no market is named/ranked, and the boundary
caveats/hard_constraints are unchanged.
"""

from __future__ import annotations

import json

from tests.integration._bootstrap_helpers import conn_for as _conn
from tests.integration._bootstrap_helpers import seed_base as _seed_base
from trade_trace.reports.bootstrap import compose_bootstrap_packet

# The first-run entry sequence, in order, a brand-new agent follows to
# begin the forecasting loop. market.search is the discovery surface added
# by trade-trace-663l; this bead points bootstrap AT it.
_ENTRY_SEQUENCE = ("market.search", "market.bind", "snapshot.fetch", "forecast.add")

# Continuity/read calls bootstrap always emits; they precede the breadcrumb.
_CONTINUITY_CALLS = ("report.work_queue", "agent.next_actions", "report.recall_receipts", "strategy.show")


def _packet(conn):
    return compose_bootstrap_packet(conn, as_of="2026-01-20T00:00:00Z")


def test_cold_empty_journal_surfaces_first_run_entry_sequence(home):
    # `home` is an initialized-but-empty journal: schema migrated, zero rows.
    with _conn(home) as conn:
        packet = _packet(conn)

    assert packet["obligations"] == []
    calls = packet["suggested_process_calls"]
    tools = [c["tool"] for c in calls]

    # Continuity calls still lead; the breadcrumb follows them in order.
    assert tools[: len(_CONTINUITY_CALLS)] == list(_CONTINUITY_CALLS)
    breadcrumb = [c for c in calls if c["tool"] in _ENTRY_SEQUENCE]
    assert [c["tool"] for c in breadcrumb] == list(_ENTRY_SEQUENCE), tools

    # call_ids stay densely/uniquely numbered across the whole list.
    call_ids = [c["call_id"] for c in calls]
    assert len(set(call_ids)) == len(call_ids)
    assert call_ids == [f"call_{i:03d}" for i in range(1, len(calls) + 1)]

    # market.search is the FIRST forward action a cold agent can take.
    search_idx = tools.index("market.search")
    assert tools[search_idx] == "market.search"

    # Each breadcrumb call is a hint, not a fetch or advice.
    for call in breadcrumb:
        assert call["caveat_codes"] == ["not_trade_advice", "not_executed", "no_fetch_performed"]
        assert call["source_refs"] == [{"kind": "doc", "id": "docs/AGENT_GUIDE.md"}]


def test_cold_breadcrumb_does_not_break_no_fetch_or_advice_contract(home):
    with _conn(home) as conn:
        packet = _packet(conn)

    # The refusal-to-fetch / refusal-to-advise contract is untouched.
    assert packet["hard_constraints"]["no_market_data_fetch"] is True
    assert packet["hard_constraints"]["no_broker_or_exchange_fetch"] is True
    assert packet["hard_constraints"]["no_trade_execution"] is True
    assert packet["hard_constraints"]["no_financial_advice"] is True
    assert packet["metadata"]["side_effects"] == []

    serialized = json.dumps(packet).lower()
    # The breadcrumb names tools, never a concrete market, side, or advice.
    for forbidden in ("buy now", "sell now", "best trade", "profit ranking", "alpha ranking", "place_order"):
        assert forbidden not in serialized


def test_non_empty_journal_emits_no_first_run_breadcrumb(home):
    with _conn(home) as conn:
        _seed_base(conn)
        conn.commit()
        packet = _packet(conn)

    tools = [c["tool"] for c in packet["suggested_process_calls"]]
    # A populated journal has real obligations to act on; no onboarding hint.
    assert packet["obligations"], "seed_base should produce at least one obligation"
    for entry in _ENTRY_SEQUENCE:
        assert entry not in tools, f"non-empty journal unexpectedly surfaced {entry}: {tools}"


def test_cold_start_packet_is_deterministic(home):
    with _conn(home) as conn:
        first = _packet(conn)
        again = _packet(conn)
    assert first == again
