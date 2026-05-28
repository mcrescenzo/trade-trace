"""Per-event-type semantic-equivalence registry per docs/architecture/persistence.md §5.2.1.

This is the seed implementation that backs trade-trace-kvn (which expands
test coverage). The registry encodes:

- `structural_fields`: the fields whose byte-equal canonical JSON is the
  comparison surface for idempotency.
- `free_text_fields`: fields ignored during comparison (LLM-rephrasing
  tolerance).
- `sort_keys`: array-valued structural fields are deterministically sorted
  by these keys before comparison.

The registry is **default-deny**: an event type not registered here cannot
be written. This guard surfaces silent contract drift immediately.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SemanticKeySpec:
    structural_fields: frozenset[str]
    free_text_fields: frozenset[str] = field(default_factory=frozenset)
    # For each array-valued structural field, the sort key to apply.
    # `None` means sort by the whole element (works for primitive arrays).
    sort_keys: dict[str, str | None] = field(default_factory=dict)


# The 15 event types enumerated in persistence.md §5.2.1.
# Server-filled fields (actor_id, created_at, request_id, event_id) are
# always excluded from comparison and are not listed here.
SEMANTIC_KEYS: dict[str, SemanticKeySpec] = {
    # M1 ledger entity-creation events. Structural fields are the smallest
    # set that defines logical identity; ids are deliberately excluded so
    # that an idempotency-key replay with a fresh server-generated id still
    # matches the original payload (the original id wins).
    "venue.created": SemanticKeySpec(
        structural_fields=frozenset({"name", "kind"}),
        free_text_fields=frozenset({"metadata_json"}),
    ),
    "market.bound": SemanticKeySpec(
        structural_fields=frozenset(
            {"source", "external_id", "state", "mechanism", "bound_via"}
        ),
        free_text_fields=frozenset(
            {
                "title",
                "question",
                "url",
                "resolution_source",
                "ambiguity_kind",
                "venue_metadata_json",
                "metadata_json",
            }
        ),
    ),
    "instrument.created": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "venue_id",
                "asset_class",
                "title",
                "external_id",
                "symbol",
                "currency_or_collateral",
                "expiration_or_resolution_at",
                "contract_multiplier",
            }
        ),
        free_text_fields=frozenset({"resolution_criteria_text", "metadata_json"}),
    ),
    "snapshot.added": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "instrument_id",
                "captured_at",
                "source",
                "price",
                "bid",
                "ask",
                "mid",
                "spread",
                "volume",
                "open_interest",
                "implied_probability",
            }
        ),
        free_text_fields=frozenset({"source_url", "liquidity_depth_json", "metadata_json"}),
    ),
    "thesis.created": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "instrument_id",
                "version",
                "parent_thesis_id",
                "side",
                "time_horizon_at",
                "confidence_label",
                "strategy_id",
                "valid_from",
                "valid_to",
            }
        ),
        free_text_fields=frozenset(
            {"body", "falsification_criteria", "exit_triggers", "risk_notes", "metadata_json"}
        ),
    ),
    "source.added": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "kind",
                "ref",
                "stance",
                "freshness_at",
                "content_hash",
                "captured_at",
                "uri",
                "media_type",
                "storage_kind",
                "retrieved_at",
                "source_author",
                "publisher",
                "hash_algorithm",
                "redaction_status",
                "license_or_terms_note",
            }
        ),
        free_text_fields=frozenset(
            {"title", "note", "excerpt", "extracted_text", "summary", "metadata_json"}
        ),
    ),
    "decision.created": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "instrument_id",
                "type",
                "thesis_id",
                "forecast_id",
                "snapshot_id",
                "side",
                "quantity",
                "price",
                "fees",
                "slippage",
                "playbook_version_id",
                "review_by",
                "strategy_id",
                "tags",
            }
        ),
        free_text_fields=frozenset({"reason"}),
        sort_keys={"tags": None},
    ),
    "outcome.recorded": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "instrument_id",
                "resolved_at",
                "outcome_label",
                "outcome_value",
                "status",
                "source",
                "confidence",
            }
        ),
        free_text_fields=frozenset({"metadata_json.note"}),
    ),
    "forecast.created": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "thesis_id",
                "kind",
                "resolution_at",
                "yes_label",
                "outcomes",
            }
        ),
        free_text_fields=frozenset({"resolution_rule_text"}),
        sort_keys={"outcomes": "outcome_label"},
    ),
    "forecast.scored": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "forecast_id",
                "outcome_id",
                "metric",
                "score",
                "scored_at",
                "failure_reason",
            }
        ),
    ),
    "forecast.anchored_to_snapshot": SemanticKeySpec(
        structural_fields=frozenset(
            {"forecast_id", "snapshot_id", "market_implied_probability", "created_at"}
        ),
    ),
    "forecast.superseded": SemanticKeySpec(
        structural_fields=frozenset({"prior_forecast_id", "new_forecast_id"}),
    ),
    "playbook.created": SemanticKeySpec(
        structural_fields=frozenset({"name", "status"}),
        free_text_fields=frozenset({"description", "metadata_json"}),
    ),
    "playbook.proposed_version": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "playbook_id",
                "version",
                "parent_version_id",
                "provenance_reflection_node_id",
            }
        ),
    ),
    "playbook_rule.followed": SemanticKeySpec(
        structural_fields=frozenset(
            {"decision_id", "playbook_version_id", "rule_node_id", "status"}
        ),
        free_text_fields=frozenset({"reason"}),
    ),
    "playbook_rule.overridden": SemanticKeySpec(
        structural_fields=frozenset(
            {"decision_id", "playbook_version_id", "rule_node_id", "status"}
        ),
        free_text_fields=frozenset({"reason"}),
    ),
    "memory_node.retained": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "node_type",
                "parent_node_id",
                "version",
                "confidence_base",
                "decay_rate_per_day",
                "importance",
                "valid_from",
                "valid_to",
                "tags",
                "meta_json",  # structural keys only; see canonicalize_payload
            }
        ),
        free_text_fields=frozenset({"title", "body"}),
        sort_keys={"tags": None},
    ),
    "memory_node.invalidated": SemanticKeySpec(
        structural_fields=frozenset({"memory_node_id", "invalidated_by", "invalidated_at"}),
    ),
    "edge.created": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "source_kind",
                "source_id",
                "target_kind",
                "target_id",
                "edge_type",
                "weight",
            }
        ),
    ),
    "source.attached": SemanticKeySpec(
        structural_fields=frozenset(
            {"source_id", "target_kind", "target_id", "edge_type"}
        ),
    ),
    "strategy.created": SemanticKeySpec(
        structural_fields=frozenset({"slug", "name", "status"}),
        free_text_fields=frozenset({"description", "hypothesis"}),
    ),
    "strategy.updated": SemanticKeySpec(
        structural_fields=frozenset({"strategy_id", "status"}),
        free_text_fields=frozenset({"description", "hypothesis"}),
    ),
    "signal.emitted": SemanticKeySpec(
        structural_fields=frozenset(
            {"kind", "severity", "actor_id", "related_refs_json", "expires_at"}
        ),
        free_text_fields=frozenset({"body", "meta_json.note"}),
        sort_keys={"related_refs_json": "kind"},
    ),
    "risk_policy_version.created": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "policy_key", "version", "policy_hash", "limits_json", "rules_json",
                "source", "provenance_json", "effective_from", "effective_to",
            }
        ),
    ),
    "risk_check_receipt.recorded": SemanticKeySpec(
        structural_fields=frozenset(
            {
                "receipt_hash", "policy_version_id", "status", "outcome",
                "intended_action", "proposed_intent_hash", "decision_id", "market_id",
                "instrument_id", "strategy_id", "snapshot_id", "exposure_input_ids_json",
                "evidence_input_ids_json", "input_provenance_json", "as_of", "waived_by",
                "rule_results",
            }
        ),
        free_text_fields=frozenset({"waiver_reason"}),
        sort_keys={"rule_results": "rule_id", "exposure_input_ids_json": None, "evidence_input_ids_json": None},
    ),
    # Importer writes are identity-only: see persistence.md §5.2 row 3.
    "import.row_committed": SemanticKeySpec(
        structural_fields=frozenset({"import_run_id", "source_row_number"}),
    ),
}


def _strip(payload: dict[str, Any], spec: SemanticKeySpec) -> dict[str, Any]:
    """Return a copy of `payload` containing only the structural fields, with
    arrays sorted deterministically per `spec.sort_keys`. Free-text fields
    are dropped entirely."""

    out: dict[str, Any] = {}
    for key in spec.structural_fields:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, list) and key in spec.sort_keys:
            sort_key = spec.sort_keys[key]
            if sort_key is None:
                value = sorted(value)
            else:
                value = sorted(value, key=lambda item: item.get(sort_key, ""))
        out[key] = value
    return out


def canonicalize_payload(event_type: str, payload: dict[str, Any]) -> str:
    """Produce the canonical JSON form used for idempotency comparison.

    Raises KeyError when `event_type` is not in SEMANTIC_KEYS — the
    default-deny guard.
    """

    spec = SEMANTIC_KEYS[event_type]
    stripped = _strip(payload, spec)
    return json.dumps(stripped, sort_keys=True, separators=(",", ":"), default=str)


# Per bead trade-trace-t7hi: every write tool whose semantic
# identity is well-defined by the existing SEMANTIC_KEYS registry
# gets an auto-derived idempotency_key when the agent omits one.
# Tools that emit per-row events (`import.*`), administrative
# capability invocations (`journal.backup`, `journal.restore`,
# `journal.fixture_seed`, `journal.config_set`, `keyring.revoke`,
# `model.*`, `memory.reindex`, `market.scan.promote`), and
# attachment helpers that emit two distinct events deliberately
# stay out of the table — they continue to require an explicit
# idempotency_key (or the `_allow_no_idempotency` opt-in) so the
# auto-derivation surface never silently smears across
# semantically distinct calls.
TOOL_PRIMARY_EVENT_TYPE: dict[str, str] = {
    # M1 ledger entity creation
    "venue.add":              "venue.created",
    "market.bind":            "market.bound",
    "instrument.add":         "instrument.created",
    "snapshot.add":           "snapshot.added",
    "thesis.add":             "thesis.created",
    "forecast.add":           "forecast.created",
    "forecast.supersede":     "forecast.superseded",
    "decision.add":           "decision.created",
    "resolution.add":         "outcome.recorded",
    "outcome.add":            "outcome.recorded",
    "resolve.record":         "outcome.recorded",  # alias of outcome.add
    "source.add":             "source.added",
    # Strategy
    "strategy.create":        "strategy.created",
    "strategy.update":        "strategy.updated",
    # Playbook
    "playbook.create":            "playbook.created",
    "playbook.propose_version":   "playbook.proposed_version",
    # decision.record_adherence emits `playbook_rule.followed` or
    # `playbook_rule.overridden` depending on status, but both event
    # types share the same structural_fields set, so either entry
    # produces the same canonical hash. Pick the `followed` row.
    "playbook.record_adherence":  "playbook_rule.followed",
    "decision.record_adherence":  "playbook_rule.followed",
    # Memory
    "memory.retain":          "memory_node.retained",
    # idea.capture is a thin wrapper on memory.retain (planned KILL
    # under the v0.0.2 catalog), so it shares the canonical-hash space.
    "idea.capture":           "memory_node.retained",
    # Risk audit surfaces
    "risk.policy_version_add": "risk_policy_version.created",
    "risk.check_record":      "risk_check_receipt.recorded",
}


def derive_idempotency_key(tool_name: str, payload: dict[str, Any]) -> str | None:
    """Return the deterministic auto-derived idempotency key for a
    write tool, or `None` when the tool is not in the auto-derivation
    registry (callers MUST pass `idempotency_key` explicitly for
    those tools — see `TOOL_PRIMARY_EVENT_TYPE` for the rationale).

    The key is `f"auto:{sha256(tool_name + canonical_json(structural))[:32]}"`.
    The `auto:` prefix lets the audit trail distinguish auto-derived
    keys from caller-supplied keys without an extra column.

    Per bead trade-trace-t7hi.
    """

    event_type = TOOL_PRIMARY_EVENT_TYPE.get(tool_name)
    if event_type is None:
        return None
    canonical = canonicalize_payload(event_type, payload)
    digest = hashlib.sha256(
        f"{tool_name}:{canonical}".encode(),
    ).hexdigest()
    return f"auto:{digest[:32]}"


def payloads_equivalent(
    event_type: str,
    old: dict[str, Any],
    new: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Compare two payloads under the per-event-type semantic equivalence.

    Returns `(equivalent, diff_summary)`. `diff_summary` is a structural diff
    with no raw payload text — so an IDEMPOTENCY_CONFLICT error envelope can
    surface the keys that changed without leaking sensitive content (per
    persistence.md §5.2)."""

    spec = SEMANTIC_KEYS[event_type]
    old_canonical = canonicalize_payload(event_type, old)
    new_canonical = canonicalize_payload(event_type, new)
    if old_canonical == new_canonical:
        return True, {"compared_keys": sorted(spec.structural_fields)}
    # Build a simple structural diff (which keys differ, no values).
    old_stripped = _strip(old, spec)
    new_stripped = _strip(new, spec)
    diff_keys: list[str] = []
    for key in spec.structural_fields:
        if old_stripped.get(key) != new_stripped.get(key):
            diff_keys.append(key)
    return False, {
        "compared_keys": sorted(spec.structural_fields),
        "diff_keys": sorted(diff_keys),
    }
