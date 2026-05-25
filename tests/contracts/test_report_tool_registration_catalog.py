"""Characterization tests for report tool registration catalog behavior."""

from __future__ import annotations

from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.reports.tool_handlers.registration import (
    _REPORT_TOOL_REGISTRATIONS,
    register_report_tools,
)


def test_report_tool_registration_descriptors_match_registered_order_and_metadata():
    descriptor_names = [descriptor.name for descriptor in _REPORT_TOOL_REGISTRATIONS]
    assert len(descriptor_names) == len(set(descriptor_names))

    registry = ToolRegistry()
    register_report_tools(registry)

    assert list(registry.by_name) == descriptor_names
    assert descriptor_names[:5] == [
        "report.bootstrap",
        "agent.bootstrap",
        "replay.case_bundle",
        "replay.evaluate_output",
        "report.filter_schema",
    ]
    assert descriptor_names[-3:] == [
        "report.exposure_anomalies",
        "report.current_exposure",
        "report.coach",
    ]

    for descriptor in _REPORT_TOOL_REGISTRATIONS:
        registered = registry.get(descriptor.name)
        assert registered.handler is descriptor.handler
        assert registered.description == descriptor.description
        assert registered.example_minimal == descriptor.example_minimal
        assert registered.example_rich == descriptor.example_rich
        assert registered.json_schema == descriptor.json_schema
        assert registered.usage_summary == descriptor.usage_summary
        assert registered.examples == list(descriptor.examples or ())
        assert registered.enum_notes == dict(descriptor.enum_notes or {})
        assert registered.common_failures == list(descriptor.common_failures or ())
        assert registered.next_actions == list(descriptor.next_actions or ())
