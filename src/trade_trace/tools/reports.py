"""Compatibility surface for `report.*` tool registration.

Report tool handlers now live in family-oriented modules under
:mod:`trade_trace.reports.tool_handlers`. This module preserves the historic
import path for registration and selected private handler names used by tests.
"""
# ruff: noqa: F401,F403,F405,I001
from __future__ import annotations

from trade_trace.reports.tool_handlers.registration import register_report_tools
from trade_trace.reports.tool_handlers.audit_quality import *  # noqa: F401,F403
from trade_trace.reports.tool_handlers.calibration_diagnostics import *  # noqa: F401,F403
from trade_trace.reports.tool_handlers.common import *  # noqa: F401,F403
from trade_trace.reports.tool_handlers.compare_policy_coach import *  # noqa: F401,F403
from trade_trace.reports.tool_handlers.lifecycle_agent import *  # noqa: F401,F403
from trade_trace.reports.tool_handlers.memory_recall import *  # noqa: F401,F403
from trade_trace.reports.tool_handlers.portfolio_exposure import *  # noqa: F401,F403
from trade_trace.reports.tool_handlers.replay import *  # noqa: F401,F403

__all__ = [name for name in globals() if name == "register_report_tools" or name.startswith("_report_") or name.startswith("_replay_") or name == "_agent_next_actions"]
