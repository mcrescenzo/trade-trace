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
            "thesis_id": "thes_THESIS_ID_HERE",
            "kind": "binary",
            "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.65},
                {"outcome_label": "no", "probability": 0.35},
            ],
            "idempotency_key": _IDEM,
        },
        "rich": {
            "thesis_id": "thes_THESIS_ID_HERE",
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
            "thesis_id": "thes_THESIS_ID_HERE",
            "forecast_id": "fcst_FORECAST_ID_HERE",
            "side": "yes",
            "quantity": 100,
            "price": 0.62,
            "idempotency_key": _IDEM,
        },
        "rich": {
            "type": "actual_enter",
            "instrument_id": "ins_INSTRUMENT_ID_HERE",
            "thesis_id": "thes_THESIS_ID_HERE",
            "forecast_id": "fcst_FORECAST_ID_HERE",
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
            "idempotency_key": _IDEM,
        },
    },
    "forecast.supersede": {
        "minimal": {
            "prior_forecast_id": "fcst_PRIOR_FORECAST_ID_HERE",
            "kind": "binary",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.7},
                {"outcome_label": "no", "probability": 0.3},
            ],
            "idempotency_key": _IDEM,
        },
        "rich": {
            "prior_forecast_id": "fcst_PRIOR_FORECAST_ID_HERE",
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
            "target_id": "thes_THESIS_ID_HERE",
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
            "target_id": "fcst_FORECAST_ID_HERE",
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
            "target_id": "thes_THESIS_ID_HERE",
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
            "description": "Buy ahead of earnings beats >= 2σ.",
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
            "src": "/tmp/models/bge-small-en-v1.5",
            "idempotency_key": _IDEM,
        },
    },
}
"""Per-tool example payloads. Keys are MCP tool names (`subject.verb`)."""


__all__ = ["WRITE_TOOL_EXAMPLES"]
