from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "architecture" / "policy-evidence-bundles.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_policy_evidence_bundle_contract_pins_required_boundaries() -> None:
    text = _text()

    required_fragments = [
        "automatic global policy promotion mechanism",
        "does not ship a CLI/MCP command",
        "Bundle status alone is not durable policy",
        "No bundle may silently widen scope",
        "Contradictory evidence must be included when known",
        "A single outcome or single reflection may create a candidate",
        "must not create a durable general rule by default",
        "single_case_critical_risk",
        "eligible_for_promotion",
        "promoted",
        "rejected",
        "superseded",
        "no_global_auto_promotion",
        "promote_narrow",
        "single_case_exception",
        "Requires a separate playbook/process write",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in text]
    assert missing == []


def test_policy_evidence_bundle_contract_covers_required_evidence_classes() -> None:
    text = _text()

    required_fragments = [
        "reflection_ids",
        "candidate_id",
        "rule_node_ids",
        "playbook_version_id",
        "actor_id",
        "agent_id",
        "model_id",
        "environment",
        "run_id",
        "decisions and non-actions",
        "Forecasts, outcomes, and scores",
        "Source references and source caveats",
        "Recall receipts",
        "Playbook adherence, overrides, and failure cases",
        "Replay examples",
        "support_case_count",
        "contradiction_case_count",
        "low_n",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in text]
    assert missing == []


def test_policy_evidence_bundle_contract_does_not_claim_future_report_exists() -> None:
    text = _text()

    forbidden_claims = [
        "`report.policy_candidates` is shipped",
        "report.policy_candidates is shipped",
        "run `report.policy_candidates`",
        "tt report policy_candidates",
    ]
    matches = [claim for claim in forbidden_claims if claim in text]
    assert matches == []
