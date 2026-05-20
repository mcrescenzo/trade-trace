"""Console reporting read model per trade-trace-bbww.

This subpackage provides read-only query helpers that surface trade /
position / decision rows in the canonical shape consumed by the new
reporting dashboards (trade-trace-3o4a EPIC). The contract is set in
[`docs/architecture/reporting-product.md`](../../../docs/architecture/reporting-product.md)
§2 (terminology) and §8 (read model).

Modules:

- `trade_rows`: paginated trades index + single-trade detail with
  evidence coverage and missing-data caveats.
- `position_rows`: single-position detail with lifecycle metrics +
  linked decision/instrument data.
"""

from __future__ import annotations

from trade_trace.console.reporting.adapter import (
    SAFE_REPORT_TOOLS,
    DashboardContext,
    DashboardGroup,
    ReportAdapterError,
    WidgetEvidence,
    run_report,
)
from trade_trace.console.reporting.filter_state import (
    FILTER_QUERY_PARAM,
    FilterStateError,
    decode_filter,
    encode_filter,
    summarize_filter,
)
from trade_trace.console.reporting.position_rows import (
    CAVEAT_OPEN_NO_MARK,
    PositionDetail,
    PositionEvent,
    position_detail,
)
from trade_trace.console.reporting.trade_rows import (
    TradeRow,
    list_trades,
    trade_detail,
)

__all__ = [
    "CAVEAT_OPEN_NO_MARK",
    "DashboardContext",
    "DashboardGroup",
    "FILTER_QUERY_PARAM",
    "FilterStateError",
    "PositionDetail",
    "PositionEvent",
    "ReportAdapterError",
    "SAFE_REPORT_TOOLS",
    "TradeRow",
    "WidgetEvidence",
    "decode_filter",
    "encode_filter",
    "list_trades",
    "position_detail",
    "run_report",
    "summarize_filter",
    "trade_detail",
]
