"""Characterization tests for report tool registration catalog behavior."""

from __future__ import annotations

from trade_trace.contracts.tool_registry import ToolRegistry
from trade_trace.core import build_registry
from trade_trace.reports.tool_handlers.registration import (
    _REPORT_TOOL_REGISTRATIONS,
    register_report_tools,
)

REMOVED_PUBLIC_REPORTS = {
    "report.compare",
    "report.calibration_integrity",
    "report.filter_schema",
    "report.lifecycle",
    "report.market_lifecycle",
    "report.memory_usefulness",
    "report.mistake_tripwire",
    "report.policy_candidates",
    "report.resolution_misreads",
    "report.resolution_quality",
    "report.source_quality",
    "report.strengths",
}


def test_report_tool_registration_descriptors_match_registered_order_and_metadata():
    descriptor_names = [descriptor.name for descriptor in _REPORT_TOOL_REGISTRATIONS]
    assert len(descriptor_names) == len(set(descriptor_names))

    registry = ToolRegistry()
    register_report_tools(registry)

    assert list(registry.by_name) == descriptor_names
    assert descriptor_names[:4] == [
        "report.bootstrap",
        "agent.bootstrap",
        "replay.case_bundle",
        "replay.evaluate_output",
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


def test_removed_report_cull_targets_are_absent_from_public_catalog():
    registry = build_registry()
    public = set(registry.public_names())
    public_reports = {name for name in public if name.startswith("report.")}

    assert len(public) == 82
    assert len(public_reports) == 23
    assert REMOVED_PUBLIC_REPORTS.isdisjoint(public)
    assert REMOVED_PUBLIC_REPORTS.isdisjoint(registry.names())
