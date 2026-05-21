"""Read-only reporting read models.

This package contains non-UI report/query helpers used by CLI, MCP,
library, and reporting consumers. Keep UI routing, HTTP, and static-asset
code out of this namespace.
"""

from __future__ import annotations

from trade_trace.reporting.metric_glossary import (
    CAVEAT_GLOSSARY,
    METRIC_GLOSSARY,
    PAGE_EXPLANATIONS,
    CaveatEntry,
    MetricEntry,
    caveat_copy,
    metric_help,
    page_explanation,
)
from trade_trace.reporting.position_rows import (
    CAVEAT_OPEN_NO_MARK,
    PositionDetail,
    PositionEvent,
    PositionRow,
    RiskRollup,
    SourceSummary,
    StrategySummary,
    TagSummary,
    ThesisSummary,
    list_positions,
    position_detail,
)
from trade_trace.reporting.trade_rows import (
    TradeRow,
    list_trades,
    trade_detail,
)

__all__ = [
    "CAVEAT_GLOSSARY",
    "CAVEAT_OPEN_NO_MARK",
    "CaveatEntry",
    "METRIC_GLOSSARY",
    "MetricEntry",
    "PAGE_EXPLANATIONS",
    "PositionDetail",
    "PositionEvent",
    "PositionRow",
    "RiskRollup",
    "SourceSummary",
    "StrategySummary",
    "TagSummary",
    "ThesisSummary",
    "TradeRow",
    "caveat_copy",
    "list_positions",
    "list_trades",
    "metric_help",
    "page_explanation",
    "position_detail",
    "trade_detail",
]
