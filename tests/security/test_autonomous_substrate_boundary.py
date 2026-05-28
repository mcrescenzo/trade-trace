from __future__ import annotations

import json
from pathlib import Path

from trade_trace.contracts.autonomous_substrate import (
    assert_no_boundary_violations,
    scan_boundary_text,
)
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_tool_specs

ROOT = Path(__file__).resolve().parents[2]


AUDITED_DOCS: tuple[Path, ...] = (
    ROOT / "docs" / "architecture" / "autonomous-trader-substrate.md",
)


def test_autonomous_substrate_tool_schemas_and_mcp_specs_respect_boundary():
    registry = default_registry()
    items: list[tuple[str, object]] = []
    for registration in registry.public_registrations(include_admin=True, include_legacy=True):
        items.append((f"tool.{registration.name}.description", registration.description))
        if registration.json_schema is not None:
            items.append((f"tool.{registration.name}.json_schema", registration.json_schema))
        items.append((f"tool.{registration.name}.metadata", registration.metadata()))
    for spec in mcp_tool_specs(registry, include_admin=True, include_legacy=True):
        items.append((f"mcp.{spec['name']}", spec))
    assert_no_boundary_violations(items)


def test_autonomous_substrate_docs_examples_exports_and_replay_gate_is_available():
    # This pins the documented gate over the contract doc itself and over
    # representative export/replay shapes downstream beads will extend.
    items: list[tuple[str, object]] = []
    for path in AUDITED_DOCS:
        text = path.read_text(encoding="utf-8")
        items.append((str(path.relative_to(ROOT)), text))
    items.append((
        "example.export.redacted",
        {
            "tool": "audit.bundle.recorded",
            "args": {
                "source_kind": "external_reconciler",
                "source_ref": "polymarket_market_123abc",
                "schema_version": "autonomous-substrate.v1",
                "content_hash": "sha256:abc123",
                "redacted_artifact_ref": "artifact://redacted/audit/abc123",
            },
        },
    ))
    items.append((
        "example.replay.bundle",
        json.dumps({
            "candidate_visible": {"market_id": "pm_market_PUBLIC123"},
            "evaluator_only": {"outcome_label": "YES"},
            "redaction_profile": "replay_candidate",
        }),
    ))
    assert_no_boundary_violations(items)


def test_public_polymarket_ids_are_not_secret_boundary_violations():
    assert scan_boundary_text("pm_market_PUBLIC123 polymarket_condition_123456abcdef") == ()


def test_autonomous_substrate_boundary_negative_fixtures_fail_without_policy_prose_false_positive():
    policy_prose = (
        "Trade Trace must not store API secrets and must not perform order placement, "
        "cancellation, redeem shares, settle market, or move funds."
    )
    assert scan_boundary_text(policy_prose) == ()

    negative_fixtures = (
        ("schema.credential_fields", {"properties": {"apiSecret": {"type": "string"}, "privateKey": {"type": "string"}}}),
        ("example.raw_private_payload", {"record": {"private_payload": {"redacted": False}}}),
        ("log.executor_action", "example tool: placeOrder then cancelOrder; action=withdraw_funds"),
        ("export.advice_claim", {"summary": "alpha signal with guaranteed profit"}),
        ("review_bundle.executor_key", {"review": {"signTransaction": False}}),
        ("replay_bundle.private_payload_ref", {"candidate": {"raw_private_payload": "artifact://not-allowed"}}),
        ("mcp.tool_description", {"description": "submitTrade method for testing"}),
    )

    for name, item in negative_fixtures:
        try:
            assert_no_boundary_violations([(name, item)])
        except AssertionError:
            pass
        else:  # pragma: no cover - defensive clarity for future scanners
            raise AssertionError(f"negative fixture did not fail boundary gate: {name}")
