"""`report.process_quality` — bet-sizing / process scoring decoupled from
outcome (trade-trace-4kec.11).

Scores the agent's declared SIZE against its declared EDGE (Kelly-consistency)
and direction, using ONLY the forecast probability and the decision's recorded
price/quantity. Resolution/outcome is never consulted — this is *process*
quality, so the agent does not learn the wrong lesson from variance.

For an entry on `side`, with forecast YES-probability `p` and the decision's
recorded fill `price` (the price of the chosen side):

- win probability  w = p (YES) or 1 - p (NO)
- stated_edge      = w - price
- kelly_fraction   = max(0, (w - price) / (1 - price))   [the Kelly-optimal
  fraction of bankroll for a unit-payout binary at that price]

Sizing alignment is bankroll-free: each decision's share of total quantity is
compared to its share of total Kelly fraction across the set, so a sizing
schedule proportional to edge scores 1.0.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from trade_trace.reports._envelope import standard_report_result

DEFAULT_PROCESS_MIN_SAMPLE = 5
_ENTRY_TYPES = ("paper_enter", "actual_enter", "add")


def _win_probability(side: str | None, p_yes: float) -> float:
    return (1.0 - p_yes) if (side or "").lower() == "no" else p_yes


def report_process_quality(
    conn: sqlite3.Connection,
    *,
    instrument_id: str | None = None,
    min_sample: int = DEFAULT_PROCESS_MIN_SAMPLE,
) -> dict[str, Any]:
    where = [
        "d.forecast_id IS NOT NULL",
        "d.quantity IS NOT NULL",
        "d.price IS NOT NULL",
        "f.probability IS NOT NULL",
        f"d.type IN ({', '.join('?' for _ in _ENTRY_TYPES)})",
    ]
    params: list[Any] = list(_ENTRY_TYPES)
    if instrument_id is not None:
        where.append("d.instrument_id = ?")
        params.append(instrument_id)
    rows = conn.execute(
        f"""
        SELECT d.id, d.side, d.quantity, d.price, f.probability
        FROM decisions d
        JOIN forecasts f ON f.id = d.forecast_id
        WHERE {' AND '.join(where)}
        ORDER BY d.created_at, d.id
        """,
        params,
    ).fetchall()

    per_decision: list[dict[str, Any]] = []
    for decision_id, side, quantity, price, p_yes in rows:
        price_f = float(price)
        win = _win_probability(side, float(p_yes))
        stated_edge = win - price_f
        if 0.0 < price_f < 1.0 and stated_edge > 0:
            kelly = stated_edge / (1.0 - price_f)
        else:
            kelly = 0.0
        per_decision.append({
            "decision_id": decision_id,
            "side": side,
            "quantity": float(quantity),
            "price": price_f,
            "win_probability": round(win, 6),
            "stated_edge": round(stated_edge, 6),
            "kelly_fraction": round(kelly, 6),
            "direction_consistent": stated_edge > 0,
        })

    sample_size = len(per_decision)
    total_qty = sum(d["quantity"] for d in per_decision)
    total_kelly = sum(d["kelly_fraction"] for d in per_decision)
    # Bankroll-free sizing alignment: L1 distance between the size schedule and
    # the edge (Kelly) schedule, mapped to [0, 1]. 1.0 = size tracks edge.
    if sample_size and total_qty > 0 and total_kelly > 0:
        l1 = sum(
            abs(d["quantity"] / total_qty - d["kelly_fraction"] / total_kelly)
            for d in per_decision
        )
        kelly_alignment: float | None = round(1.0 - 0.5 * l1, 6)
    else:
        kelly_alignment = None
    direction_rate: float | None = (
        round(sum(1 for d in per_decision if d["direction_consistent"]) / sample_size, 6)
        if sample_size else None
    )

    groups = [
        {
            "key": d["decision_id"],
            "label": f"Decision {d['decision_id']} sizing vs edge",
            "metrics": {
                "quantity": d["quantity"],
                "price": d["price"],
                "win_probability": d["win_probability"],
                "stated_edge": d["stated_edge"],
                "kelly_fraction": d["kelly_fraction"],
                "direction_consistent": d["direction_consistent"],
            },
            "record_ids": {"decisions": [d["decision_id"]]},
            "examples": [],
            "sample_size": 1,
            "sample_warning": None,
            "truncated": False,
        }
        for d in per_decision
    ]

    sample_warning = (
        f"only {sample_size} sized decisions; process score is unreliable below {min_sample}"
        if sample_size and sample_size < min_sample
        else (None if sample_size else "no sized decisions with a linked forecast probability")
    )
    summary = {
        "sample_size": sample_size,
        "kelly_alignment": kelly_alignment,
        "direction_consistency_rate": direction_rate,
        "instrument_id": instrument_id,
        "sample_warning": sample_warning,
        "metrics": {"quality_kind": "process_not_outcome"},
        "caveats": [
            "Process quality only: this scores declared size against declared "
            "edge (Kelly-consistency) and direction, computed WITHOUT consulting "
            "any resolution/outcome, so a lucky or unlucky result cannot move it. "
            "It is not trade advice, a signal, or an edge/profit claim.",
        ],
    }
    return standard_report_result(summary=summary, groups=groups)


__all__ = ["report_process_quality", "DEFAULT_PROCESS_MIN_SAMPLE"]
