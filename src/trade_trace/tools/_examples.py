"""Per-tool schema examples surfaced via `tool.schema` per bead trade-trace-268.

Each write tool exposes a minimal valid example (the smallest payload that
will succeed for that tool) and, where it adds substantive value, a richer
example that also exercises the optional metadata. Agents can pull these
through `tool.schema` to bootstrap their first call without re-reading the
PRD or contracts.md.

Conventions:
- Examples assume `$TRADE_TRACE_HOME` is already initialized (`journal.init`).
- IDs in examples are illustrative; servers generate them when omitted.
- Idempotency keys follow the contracts.md grammar (UUIDv4 string).
"""

from __future__ import annotations

from typing import Any

_IDEM = "00000000-0000-4000-8000-000000000000"


WRITE_TOOL_EXAMPLES: dict[str, dict[str, Any]] = {
    "autonomous_run.record": {
        "minimal": {
            "semantic_key": "autonomous-run:profile-a:2026-05-28T00:00Z",
            "mode": "autonomous",
            "run_status": "started",
            "run_id": "run-redacted-001",
            "started_at": "2026-05-28T00:00:00Z",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "semantic_key": "autonomous-run:profile-a:2026-05-28T00:00Z",
            "mode": "autonomous",
            "run_status": "completed",
            "run_id": "run-redacted-001",
            "session_id": "session-redacted-001",
            "actor_id_recorded": "agent:local-profile",
            "model_id": "model-redacted",
            "provider_id": "provider-redacted",
            "environment_label": "local-profile",
            "policy_version": "policy-v1",
            "started_at": "2026-05-28T00:00:00Z",
            "ended_at": "2026-05-28T00:10:00Z",
            "config_json": {"cycle_mode": "review_only"},
            "provenance_json": {"source": "caller_supplied_local_run_log"},
            "idempotency_key": _IDEM,
        },
    },
    "autonomous_incident.record": {
        "minimal": {
            "semantic_key": "autonomous-incident:blocked-action:2026-05-28T00:05Z",
            "incident_type": "blocked_action",
            "occurred_at": "2026-05-28T00:05:00Z",
            "summary": "External system reported a policy-blocked action; Trade Trace records the fact only.",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "semantic_key": "autonomous-incident:blocked-action:2026-05-28T00:05Z",
            "incident_type": "blocked_action",
            "severity": "critical",
            "resolution_status": "unresolved",
            "run_id": "run-redacted-001",
            "session_id": "session-redacted-001",
            "occurred_at": "2026-05-28T00:05:00Z",
            "summary": "External system reported a policy-blocked action; Trade Trace records the fact only.",
            "evidence_state": "sparse",
            "link_ids": {"pretrade_intent_ids": ["pti_..."], "policy_ids": ["policy-v1"]},
            "evidence_refs": [{"kind": "local_artifact", "ref": "sha256://redacted"}],
            "provenance_json": {"source": "caller_supplied_operator_note"},
            "idempotency_key": _IDEM,
        },
    },
    "paper_fill.record": {
        "minimal": {
            "semantic_key": "paper_fill:local-paper:market-123:run-001",
            "account_label": "local-paper",
            "side": "buy",
            "outcome_side": "yes",
            "requested_quantity": 10,
            "limit_price": 0.55,
            "order_as_of": "2026-05-28T00:00:10Z",
            "book_levels": [{"price": 0.52, "quantity": 10}],
            "idempotency_key": _IDEM,
        },
        "rich": {
            "semantic_key": "paper_fill:local-paper:market-123:run-001",
            "account_label": "local-paper",
            "market_id": "mkt_MARKET_ID_HERE",
            "side": "buy",
            "outcome_side": "yes",
            "requested_quantity": 10,
            "limit_price": 0.55,
            "reference_mid_price": 0.50,
            "slippage_cap_bps": 500,
            "fee_amount": 0.02,
            "quote_id": "quote-001",
            "book_id": "book-001",
            "snapshot_id": "snap-001",
            "snapshot_as_of": "2026-05-28T00:00:00Z",
            "order_as_of": "2026-05-28T00:00:10Z",
            "book_levels": [{"price": 0.52, "quantity": 6}, {"price": 0.53, "quantity": 4}],
            "provenance_json": {"source": "caller_supplied_paper_depth"},
            "idempotency_key": _IDEM,
        },
    },
    "idea.capture": {
        "minimal": {
            "thought": "Rough market idea to investigate later; needs venue, instrument, snapshot, thesis, and forecast enrichment.",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "title": "Draft CPI surprise idea",
            "thought": "Investigate whether CPI surprise could move short-dated rate-cut prediction markets; no decision yet.",
            "captured_at": "2026-05-20T14:00:00Z",
            "tags": ["macro", "draft", "needs_enrichment"],
            "importance": 6,
            "confidence_base": 0.4,
            "metadata_json": {"user_context": "quick capture before research"},
            "idempotency_key": _IDEM,
        },
    },
    "venue.add": {
        "minimal": {
            "name": "Kalshi",
            "kind": "prediction_market",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "name": "Kalshi",
            "kind": "prediction_market",
            "metadata_json": {"region": "us", "tier": "regulated"},
            "idempotency_key": _IDEM,
        },
    },
    "instrument.add": {
        "minimal": {
            "venue_id": "ven_VENUE_ID_HERE",
            "asset_class": "prediction_market",
            "title": "NVDA earnings beat 2026Q1",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "venue_id": "ven_VENUE_ID_HERE",
            "asset_class": "prediction_market",
            "title": "NVDA earnings beat 2026Q1",
            "symbol": "NVDA-26Q1",
            "external_id": "kalshi:NVDA-26Q1",
            "currency_or_collateral": "USD",
            "expiration_or_resolution_at": "2026-05-22T20:00:00Z",
            "resolution_criteria_text": "Resolves YES if reported revenue exceeds consensus.",
            "contract_multiplier": 1.0,
            "metadata_json": {"event_type": "earnings"},
            "idempotency_key": _IDEM,
        },
    },
    "thesis.add": {
        "minimal": {
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "side": "yes",
            "body": "Consensus underestimates AI demand; revenue should beat by 5%+.",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "side": "yes",
            "body": "Consensus underestimates AI demand; revenue should beat by 5%+.",
            "confidence_label": "high",
            "tags": ["earnings", "ai-tailwind"],
            "metadata_json": {"author_notes": "first-pass thesis"},
            "agent_id": "agent:research-bot",
            "model_id": "claude-opus-4-7",
            "environment": "paper",
            "run_id": "run_2026Q1_earnings",
            "idempotency_key": _IDEM,
        },
    },
    "forecast.add": {
        "minimal": {
            "market_id": "mkt_MARKET_ID_FROM_MARKET_BIND",
            "rationale_body": "Why this forecast probability is justified.",
            "kind": "binary",
            "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.65},
                {"outcome_label": "no", "probability": 0.35},
            ],
            "idempotency_key": _IDEM,
        },
        "rich": {
            "market_id": "mkt_MARKET_ID_FROM_MARKET_BIND",
            "instrument_id": "mkt_SAME_ID_RETURNED_AS_INSTRUMENT_ID_BY_MARKET_BIND",
            "rationale_body": "Why this forecast probability is justified.",
            "kind": "binary",
            "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.65},
                {"outcome_label": "no", "probability": 0.35},
            ],
            "resolution_at": "2026-05-22T20:00:00Z",
            "resolution_rule_text": "Resolves on official earnings press release.",
            "scoring_support": "supported",
            "metadata_json": {"prior_belief": 0.55},
            "idempotency_key": _IDEM,
        },
    },
    "decision.add": {
        "minimal": {
            "type": "actual_enter",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "thesis_id": "th_THESIS_ID_HERE",
            "forecast_id": "fc_FORECAST_ID_HERE",
            "side": "yes",
            "quantity": 100,
            "price": 0.62,
            "idempotency_key": _IDEM,
        },
        "rich": {
            "type": "actual_enter",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "thesis_id": "th_THESIS_ID_HERE",
            "forecast_id": "fc_FORECAST_ID_HERE",
            "snapshot_id": "snp_SNAPSHOT_ID_HERE",
            "side": "yes",
            "quantity": 100,
            "price": 0.62,
            "tags": ["pre-earnings", "high-conviction"],
            "metadata_json": {"venue_fees_estimate": 1.50},
            "agent_id": "agent:research-bot",
            "model_id": "claude-opus-4-7",
            "environment": "paper",
            "idempotency_key": _IDEM,
        },
    },
    "outcome.add": {
        "minimal": {
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "resolved_at": "2026-05-22T20:30:00Z",
            "outcome_label": "yes",
            "status": "resolved_final",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "resolved_at": "2026-05-22T20:30:00Z",
            "outcome_label": "yes",
            "status": "resolved_final",
            # confidence is REQUIRED for a resolved_final outcome to auto-score a
            # pending binary forecast (>=0.9 + a binary label); omitting it makes
            # the write succeed but score nothing. See auto_score_skipped_reason
            # on the result for the point-of-failure hint.
            "confidence": 0.99,
            "settlement_price": 1.0,
            "resolution_source_url": "https://example.com/press",
            "metadata_json": {"reporter": "nvidia"},
            "idempotency_key": _IDEM,
        },
    },
    "source.add": {
        "minimal": {
            "kind": "news_article",
            "stance": "supports",
            "uri": "https://example.com/article",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "kind": "news_article",
            "stance": "supports",
            "uri": "https://example.com/article",
            "title": "AI demand drives chip sales",
            "freshness_at": "2026-05-20T14:00:00Z",
            "retrieved_at": "2026-05-20T14:05:00Z",
            "summary": "Cites three independent supply-chain sources.",
            "redaction_status": "none",
            "agent_id": "agent:research-bot",
            "model_id": "claude-opus-4-7",
            "environment": "paper",
            "run_id": "run_2026Q1_earnings",
            "idempotency_key": _IDEM,
        },
    },
    "snapshot.add": {
        "minimal": {
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "captured_at": "2026-05-22T14:30:00.000Z",
            "price": 0.62,
            "source": "manual",
            "source_url": "https://example.com/market/contract",
            "bid": 0.61,
            "ask": 0.63,
            "mid": 0.62,
            "spread": 0.02,
            "volume": 1250.0,
            "open_interest": 4200.0,
            "implied_probability": 0.62,
            "liquidity_depth_json": {"yes": [[0.61, 100]], "no": [[0.39, 80]]},
            "metadata_json": {"feed": "manual"},
            "idempotency_key": _IDEM,
        },
        "rich": {
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "captured_at": "2026-05-22T14:30:00.000Z",
            "price": 0.62,
            "source": "kalshi",
            "source_url": "https://example.com/market/contract",
            "bid": 0.61,
            "ask": 0.63,
            "mid": 0.62,
            "spread": 0.02,
            "volume": 1250.0,
            "open_interest": 4200.0,
            "implied_probability": 0.62,
            "liquidity_depth_json": {"yes": [[0.61, 100]], "no": [[0.39, 80]]},
            "metadata_json": {"feed": "kalshi-rest"},
            "agent_id": "agent:research-bot",
            "model_id": "claude-opus-4-7",
            "environment": "paper",
            "run_id": "run_2026Q1_earnings",
            "idempotency_key": _IDEM,
        },
    },
    "forecast.supersede": {
        "minimal": {
            "prior_forecast_id": "fc_PRIOR_FORECAST_ID_HERE",
            "kind": "binary",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.7},
                {"outcome_label": "no", "probability": 0.3},
            ],
            "idempotency_key": _IDEM,
        },
        "rich": {
            "prior_forecast_id": "fc_PRIOR_FORECAST_ID_HERE",
            "kind": "binary",
            "yes_label": "yes",
            "resolution_at": "2026-05-22T20:30:00Z",
            "resolution_rule_text": "Official close price > strike",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.7},
                {"outcome_label": "no", "probability": 0.3},
            ],
            "idempotency_key": _IDEM,
        },
    },
    "source.attach_to_thesis": {
        "minimal": {
            "source_id": "src_SOURCE_ID_HERE",
            "target_id": "th_THESIS_ID_HERE",
            "idempotency_key": _IDEM,
        },
    },
    "source.attach_to_decision": {
        "minimal": {
            "source_id": "src_SOURCE_ID_HERE",
            "target_id": "dec_DECISION_ID_HERE",
            "idempotency_key": _IDEM,
        },
    },
    "source.attach_to_forecast": {
        "minimal": {
            "source_id": "src_SOURCE_ID_HERE",
            "target_id": "fc_FORECAST_ID_HERE",
            "idempotency_key": _IDEM,
        },
    },
    "source.attach_to_memory_node": {
        "minimal": {
            "source_id": "src_SOURCE_ID_HERE",
            "target_id": "mem_MEMORY_NODE_ID_HERE",
            "idempotency_key": _IDEM,
        },
    },
    "source.attach_to_outcome": {
        "minimal": {
            "source_id": "src_SOURCE_ID_HERE",
            "target_id": "out_OUTCOME_ID_HERE",
            "idempotency_key": _IDEM,
        },
    },
    "source.attach_to_snapshot": {
        "minimal": {
            "source_id": "src_SOURCE_ID_HERE",
            "target_id": "snp_SNAPSHOT_ID_HERE",
            "idempotency_key": _IDEM,
        },
    },
    "source.attach_to_instrument": {
        "minimal": {
            "source_id": "src_SOURCE_ID_HERE",
            "target_id": "ins_INSTRUMENT_ID_HERE",
            "idempotency_key": _IDEM,
        },
    },
    "memory.retain": {
        "minimal": {
            "node_type": "observation",
            "body": "Liquidity tightened ahead of earnings.",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "node_type": "reflection",
            "body": "Should have weighed liquidity profile more heavily.",
            "importance": 7,
            "valid_from": "2026-05-22T14:00:00Z",
            "meta_json": {"tags": ["liquidity-ignored"]},
            "idempotency_key": _IDEM,
        },
    },
    "memory.reflect": {
        "minimal": {
            "target_kind": "thesis",
            "target_id": "th_THESIS_ID_HERE",
            "body": "Falsifying evidence emerged when liquidity dried up.",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "target": {"kind": "decision", "id": "dec_DECISION_ID_HERE"},
            "insight": "I over-weighted headline momentum and under-weighted spread quality.",
            "strength_tags": ["thesis-check"],
            "weakness_tags": ["liquidity-ignored"],
            "importance": 7,
            "meta_json": {"review": "2026-Q1"},
            "idempotency_key": _IDEM,
        },
    },
    "memory.link": {
        "minimal": {
            "source_kind": "memory_node",
            "source_id": "mem_FROM_NODE_HERE",
            "target_kind": "memory_node",
            "target_id": "mem_TO_NODE_HERE",
            "edge_type": "supports",
            "idempotency_key": _IDEM,
        },
    },
    "playbook.create": {
        "minimal": {
            "name": "earnings-momentum",
            "description": "Buy ahead of earnings beats >= 2σ.",
            "idempotency_key": _IDEM,
        },
    },
    "playbook.propose_version": {
        "minimal": {
            "playbook_id": "pbk_PLAYBOOK_ID_HERE",
            "provenance_reflection_node_id": "mem_REFLECTION_NODE_HERE",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "playbook_id": "pbk_PLAYBOOK_ID_HERE",
            "provenance_reflection_node_id": "mem_REFLECTION_NODE_HERE",
            "parent_version_id": "pbv_PRIOR_VERSION_HERE",
            "description": "Tighten spread guard after Q1 review.",
            "metadata_json": {"review": "2026-Q1"},
            "idempotency_key": _IDEM,
        },
    },
    "decision.record_adherence": {
        "minimal": {
            "decision_id": "dec_DECISION_ID_HERE",
            "playbook_version_id": "pbv_PLAYBOOK_VERSION_HERE",
            "rule_node_id": "mem_RULE_NODE_HERE",
            "status": "followed",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "decision_id": "dec_DECISION_ID_HERE",
            "playbook_version_id": "pbv_PLAYBOOK_VERSION_HERE",
            "rule_node_id": "mem_RULE_NODE_HERE",
            "status": "overridden",
            "reason": "Earnings beat materially overrode the spread guard.",
            "metadata_json": {"override_review": "pending"},
            "idempotency_key": _IDEM,
        },
    },
    "strategy.create": {
        "minimal": {
            "name": "earnings-momentum",
            "slug": "earnings-momentum",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "name": "earnings-momentum",
            "slug": "earnings-momentum",
            "description": "Buy ahead of earnings beats >= 2σ.",
            "hypothesis": "Post-earnings drift compresses faster on consensus beats.",
            "status": "active",
            "meta_json": {"sizing": "fixed"},
            "idempotency_key": _IDEM,
        },
    },
    "strategy.update": {
        "minimal": {
            "strategy_id": "stg_STRATEGY_ID_HERE",
            "description": "Updated thesis: also requires CPI beat.",
            "idempotency_key": _IDEM,
        },
    },
    "risk.policy_version_add": {
        "minimal": {
            "policy_key": "default-pretrade-risk",
            "version": "2026-05-22.1",
            "limits_json": {"max_position_notional": 1000},
            "rules_json": [{"id": "max_position_notional", "severity": "hard_block"}],
            "source": "external-profile-risk-layer",
            "effective_from": "2026-05-22T00:00:00Z",
            "idempotency_key": _IDEM,
        },
    },
    "risk.check_record": {
        "minimal": {
            "policy_version_id": "rpv_POLICY_VERSION_ID_HERE",
            "status": "pass",
            "outcome": "pass",
            "as_of": "2026-05-22T14:30:00Z",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "exposure_input_ids_json": ["pos_POSITION_ID_HERE"],
            "evidence_input_ids_json": ["src_SOURCE_ID_HERE"],
            "input_provenance_json": {"risk_layer": "external-profile-risk-layer", "version": "2026-05-22.1"},
            "rule_results": [
                {
                    "rule_id": "max_position_notional",
                    "reason_code": "within_limit",
                    "severity": "info",
                    "observed_value": {"notional": 100},
                    "threshold": {"max_notional": 1000},
                    "contributing_record_ids": ["pos_POSITION_ID_HERE"],
                    "waiver_required": False,
                }
            ],
            "idempotency_key": _IDEM,
        },
    },
    "pretrade_intent.record": {
        "minimal": {
            "semantic_key": "pti_example_market_review_2026_05_22T143000Z",
            "market_id": "mkt_MARKET_ID_HERE",
            "proposed_shape": {
                "side": "yes",
                "quantity": 10,
                "limit_price": 0.62,
                "intent_type": "limit_review",
            },
            "risk_budget": {
                "max_notional": 100,
                "max_loss": 100,
                "currency": "USD",
            },
            "evidence_refs": [
                {"kind": "note", "ref": "internal-research-summary-2026-05-22"}
            ],
            "source_ids": ["src_SOURCE_ID_HERE"],
            "as_of": "2026-05-22T14:30:00Z",
            "idempotency_key": _IDEM,
        },
    },
    "approval.record": {
        "minimal": {
            "semantic_key": "awr_example_local_approval_2026_05_22T143000Z",
            "record_type": "approval",
            "decision": "approved",
            "actor_mode": "human_review",
            "decision_actor_id": "local-reviewer",
            "decision_at": "2026-05-22T14:30:00Z",
            "reason": "Local audit note that an external review approved this proposed activity; Trade Trace records evidence only and does not grant live permission or execute activity.",
            "idempotency_key": _IDEM,
        },
    },
    "external_receipt.import": {
        "minimal": {
            "semantic_key": "external_receipt_example_order_accepted_2026_05_22T143000Z",
            "lifecycle_state": "accepted",
            "external_event_type": "order",
            "source_system": "sanitized-external-log",
            "as_of": "2026-05-22T14:30:00Z",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "semantic_key": "external_receipt_example_fill_partial_2026_05_22T143500Z",
            "lifecycle_state": "partial_fill",
            "external_event_type": "fill",
            "source_system": "sanitized-external-log",
            "source_run_id": "external-run-20260522-a",
            "market_id": "mkt_MARKET_ID_HERE",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "external_order_ref": "order_ref_redacted_001",
            "external_fill_ref": "fill_ref_redacted_001",
            "retrieved_at": "2026-05-22T14:36:00Z",
            "as_of": "2026-05-22T14:35:00Z",
            "artifact_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            "redacted_artifact_ref": "local://sanitized/external-receipts/fill-001.json",
            "sanitized_facts": {"filled_quantity": 25, "remaining_quantity": 75},
            "caveats": [{"code": "sanitized_import", "message": "Caller supplied sanitized evidence only."}],
            "provenance_json": {"imported_by": "local-agent"},
            "idempotency_key": _IDEM,
        },
    },
    "account_snapshot.import": {
        "minimal": {
            "semantic_key": "account_snapshot_example_local_2026_05_22T143000Z",
            "source_system": "sanitized-account-export",
            "captured_at": "2026-05-22T14:30:00Z",
            "as_of": "2026-05-22T14:30:00Z",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "semantic_key": "account_snapshot_example_recon_2026_05_22T143500Z",
            "source_system": "sanitized-account-export",
            "source_run_id": "account-export-20260522-a",
            "source_precedence": 10,
            "confidence_label": "high",
            "staleness_status": "fresh",
            "environment_label": "paper",
            "account_label": "acct-redacted-001",
            "venue_label": "venue-redacted",
            "captured_at": "2026-05-22T14:35:00Z",
            "effective_at": "2026-05-22T14:35:00Z",
            "retrieved_at": "2026-05-22T14:36:00Z",
            "as_of": "2026-05-22T14:35:00Z",
            "artifact_hash": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
            "redacted_artifact_ref": "local://sanitized/account-snapshots/recon-001.json",
            "balances": [{"asset": "USD", "total": "100.00", "available": "75.00"}],
            "collateral": {"available": "75.00", "committed": "25.00", "currency": "USD"},
            "open_orders": [{"ref": "order_ref_redacted_001", "side": "yes", "quantity": "10"}],
            "positions": [{"instrument_ref": "ins_REDACTED", "quantity": "15"}],
            "fills_trades": [{"ref": "fill_ref_redacted_001", "quantity": "5"}],
            "unsettled_claims": [{"claim_ref": "claim_ref_redacted_001", "amount": "2.00"}],
            "public_allowance_facts": [{"asset": "USDC", "allowance": "0", "source": "caller-supplied-public-fact"}],
            "caveats": [{"code": "sanitized_import", "message": "Caller supplied sanitized evidence only."}],
            "provenance_json": {"imported_by": "local-agent"},
            "idempotency_key": _IDEM,
        },
    },
    "import.validate": {
        "minimal": {
            "path": "/tmp/trade-trace-import/bundle.jsonl",
            "idempotency_key": _IDEM,
        },
    },
    "import.commit": {
        "minimal": {
            "path": "/tmp/trade-trace-import/bundle.jsonl",
            "transaction_mode": "single",
            "idempotency_key": _IDEM,
        },
    },
    "import.csv_fills": {
        "minimal": {
            "path": "/tmp/trade-trace-import/fills.csv",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "idempotency_key": _IDEM,
        },
    },
    "replay_artifact.record": {
        "minimal": {
            "semantic_key": "replay-eval:strategy-a:v1:dataset-a",
            "dataset_hash": "sha256:dataset-a",
            "strategy_version": "v1",
            "as_of": "2026-05-28T00:00:00Z",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "semantic_key": "replay-eval:strategy-a:v1:dataset-a",
            "artifact_type": "historical_simulation",
            "evidence_mode": "historical_simulation",
            "dataset_hash": "sha256:dataset-a",
            "strategy_id": "strat_a",
            "strategy_version": "v1",
            "parameters": {"lookback_days": 30},
            "assumptions": {"source": "caller_supplied_external_result"},
            "fill_model": {"kind": "external_metadata_only"},
            "slippage_model": {"kind": "caller_supplied_bps", "bps": 5},
            "result_summary": {"sample_size": 25},
            "sample_size": 25,
            "source_links": [{"label": "redacted local report", "uri": "file://redacted/replay-eval.json"}],
            "provenance": {"imported_from": "caller_supplied_local_artifact"},
            "caveats": [{"code": "external_result", "message": "Trade Trace did not run this evaluation."}],
            "redaction_profile": "metadata_only",
            "redacted_artifact_ref": "artifact://redacted/replay-eval-a",
            "as_of": "2026-05-28T00:00:00Z",
            "evaluated_at": "2026-05-28T01:00:00Z",
            "idempotency_key": _IDEM,
        },
    },
    "journal.fixture_seed": {
        "minimal": {
            "target": "mvp-eval",
            "idempotency_key": _IDEM,
        },
    },
    "journal.backup": {
        "minimal": {
            "dest": "/tmp/trade-trace-backup-2026-05-22",
            "_confirm": True,
            "idempotency_key": _IDEM,
        },
    },
    "journal.restore": {
        "minimal": {
            "src": "/tmp/trade-trace-backup-2026-05-22",
            "_confirm": True,
            "idempotency_key": _IDEM,
        },
    },
    "journal.config_set": {
        "minimal": {
            "key": "embeddings.provider",
            "value": "local",
            "_confirm": True,
            "idempotency_key": _IDEM,
        },
    },
    "memory.reindex": {
        "minimal": {
            "_confirm": True,
            "idempotency_key": _IDEM,
        },
    },
    "keyring.revoke": {
        "minimal": {
            "_confirm": True,
            "idempotency_key": _IDEM,
        },
    },
    "model.import": {
        "minimal": {
            "path": "/tmp/models/bge-small-en-v1.5",
            "idempotency_key": _IDEM,
        },
    },
}
"""Per-tool example payloads. Keys are MCP tool names (`subject.verb`)."""


__all__ = ["WRITE_TOOL_EXAMPLES"]
