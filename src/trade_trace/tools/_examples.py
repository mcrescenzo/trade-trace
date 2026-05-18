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
            "kind": "news",
            "stance": "supports",
            "uri": "https://example.com/article",
            "idempotency_key": _IDEM,
        },
        "rich": {
            "kind": "news",
            "stance": "supports",
            "uri": "https://example.com/article",
            "title": "AI demand drives chip sales",
            "freshness_at": "2026-05-20T14:00:00Z",
            "summary": "Cites three independent supply-chain sources.",
            "redaction_status": "none",
            "idempotency_key": _IDEM,
        },
    },
}
"""Per-tool example payloads. Keys are MCP tool names (`subject.verb`)."""


__all__ = ["WRITE_TOOL_EXAMPLES"]
