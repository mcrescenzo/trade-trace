"""`report.resolution_misreads` — contract-misread error class (trade-trace-4kec.12).

Compares the agent's recorded resolution-criteria interpretation (the source it
believed would resolve a market) against the actual resolution source recorded
on the market once it resolves. A mismatch is a *contract misread*: a distinct
error class from calibration error — the agent can be well-calibrated about the
world yet wrong about which contract/source decides the question.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from trade_trace.reports._envelope import standard_report_result


def _norm(value: str | None) -> str | None:
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def report_resolution_misreads(
    conn: sqlite3.Connection,
    *,
    instrument_id: str | None = None,
) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []
    if instrument_id is not None:
        where.append("ri.instrument_id = ?")
        params.append(instrument_id)
    rows = conn.execute(
        f"""
        SELECT ri.forecast_id, ri.instrument_id, ri.interpreted_resolution_source,
               ri.expected_outcome_label,
               m.resolution_source,
               o.outcome_label, o.status
        FROM resolution_interpretations ri
        LEFT JOIN markets m ON m.id = ri.instrument_id
        LEFT JOIN outcomes o
          ON o.instrument_id = ri.instrument_id
          AND o.status = 'resolved_final'
        WHERE {' AND '.join(where)}
        ORDER BY ri.created_at, ri.forecast_id
        """,
        params,
    ).fetchall()

    groups: list[dict[str, Any]] = []
    counts = {"contract_misread": 0, "aligned": 0, "unresolved": 0}
    for forecast_id, inst_id, interp_source, expected_label, actual_source, outcome_label, status in rows:
        resolved = status == "resolved_final"
        interp_n = _norm(interp_source)
        actual_n = _norm(actual_source)
        label_mismatch = (
            _norm(expected_label) is not None
            and _norm(outcome_label) is not None
            and _norm(expected_label) != _norm(outcome_label)
        )
        if not resolved:
            classification = "unresolved"
        elif interp_n is not None and actual_n is not None and interp_n != actual_n:
            classification = "contract_misread"
        else:
            classification = "aligned"
        counts[classification] += 1
        groups.append({
            "key": forecast_id,
            "label": f"Resolution interpretation for forecast {forecast_id}",
            "metrics": {
                "classification": classification,
                "interpreted_resolution_source": interp_source,
                "actual_resolution_source": actual_source,
                "expected_outcome_label": expected_label,
                "actual_outcome_label": outcome_label,
                "outcome_label_mismatch": label_mismatch,
            },
            "record_ids": {"forecasts": [forecast_id], "instruments": [inst_id]},
            "examples": [],
            "sample_size": 1,
            "sample_warning": None,
            "truncated": False,
        })

    # contract_misread is the headline error class; order it first.
    order = {"contract_misread": 0, "unresolved": 1, "aligned": 2}
    groups.sort(key=lambda g: order.get(g["metrics"]["classification"], 3))

    summary = {
        "sample_size": len(groups),
        "instrument_id": instrument_id,
        "contract_misread_count": counts["contract_misread"],
        "aligned_count": counts["aligned"],
        "unresolved_count": counts["unresolved"],
        "sample_warning": None if groups else "no resolution interpretations recorded",
        "metrics": {"error_class": "contract_misread"},
        "caveats": [
            "A contract_misread means the agent's interpreted resolution source "
            "differs from the market's actual resolution source — a distinct error "
            "class from calibration error (right about the world, wrong about the "
            "contract). This is diagnostic, not trade advice.",
        ],
    }
    return standard_report_result(summary=summary, groups=groups)


__all__ = ["report_resolution_misreads"]
