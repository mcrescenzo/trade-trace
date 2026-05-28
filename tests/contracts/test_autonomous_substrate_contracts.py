from __future__ import annotations

from trade_trace.contracts.autonomous_substrate import (
    ALL_AUTONOMOUS_RECORD_FAMILIES,
    COMMON_FIELD_CONTRACTS,
    EVENT_TYPE_EXPECTATIONS,
    MIGRATION_CONTRACT_EXPECTATIONS,
    PUBLIC_NON_SECRET_FIELD_CLASSES,
    AutonomousRecordFamily,
    AutonomousSubstrateContractError,
    RedactionFieldClass,
    RedactionProfile,
    required_fields_for,
    scan_boundary_mapping,
    scan_boundary_text,
    validate_autonomous_record,
    validate_event_expectation,
    validate_required_common_fields,
)


def test_autonomous_record_families_and_common_fields_are_complete():
    assert {family.value for family in ALL_AUTONOMOUS_RECORD_FAMILIES} == {
        "execution_intent",
        "risk_check",
        "approval_waiver",
        "execution_import",
        "account_snapshot",
        "reconciliation_report",
        "incident_run_session",
        "audit_bundle",
        "replay_evaluation_artifact",
        "paper_fill",
    }
    common_names = {contract.name for contract in COMMON_FIELD_CONTRACTS}
    assert {
        "source_kind",
        "source_ref",
        "captured_at",
        "effective_at",
        "as_of",
        "retrieved_at",
        "imported_at",
        "schema_version",
        "source_precedence",
        "confidence",
        "staleness",
        "content_hash",
        "redacted_artifact_ref",
        "idempotency_key",
        "semantic_key",
        "supersedes_record_id",
        "provenance",
    }.issubset(common_names)
    for family in ALL_AUTONOMOUS_RECORD_FAMILIES:
        fields = required_fields_for(family)
        assert "source_kind" in fields
        assert "source_ref" in fields
        assert "schema_version" in fields
        assert "content_hash" in fields
        assert "idempotency_key" in fields
        assert "semantic_key" in fields


def test_redaction_profiles_and_field_classes_pin_public_polymarket_ids():
    assert {profile.value for profile in RedactionProfile} == {
        "public_summary",
        "internal_review",
        "audit_export",
        "replay_candidate",
        "evaluator_only",
    }
    assert {field.value for field in RedactionFieldClass} >= {
        "account_label",
        "public_address",
        "strategy_id",
        "source_text",
        "external_order_id",
        "raw_payload_ref",
        "public_polymarket_id",
    }
    assert RedactionFieldClass.PUBLIC_POLYMARKET_ID in PUBLIC_NON_SECRET_FIELD_CLASSES


def test_event_type_expectations_cover_each_family_with_semantic_keys():
    covered = {expectation.record_family for expectation in EVENT_TYPE_EXPECTATIONS}
    assert covered == set(ALL_AUTONOMOUS_RECORD_FAMILIES)
    for expectation in EVENT_TYPE_EXPECTATIONS:
        assert expectation.event_type.endswith(".recorded") or expectation.event_type.endswith(".imported")
        assert "semantic_key" in expectation.semantic_idempotency_fields
        assert expectation.semantic_idempotency_fields


def test_migration_contract_expectations_pin_schema_gates():
    joined = "\n".join(MIGRATION_CONTRACT_EXPECTATIONS)
    assert "forward-only" in joined
    assert "_MIGRATION_TABLES_CREATED" in joined
    assert "_MIGRATION_COLUMNS_ADDED" in joined
    assert "schema hash" in joined


def test_boundary_scanner_flags_credentials_executor_scheduler_and_advice_terms():
    payload = {
        "input_schema": {
            "properties": {
                "api_key": {"type": "string"},
                "signing_payload": {"type": "object"},
                "place_order": {"type": "boolean"},
            }
        },
        "description": "starts a background_fetch scheduler and gives buy this trading advice",
    }
    violations = scan_boundary_mapping(payload, path="tool.example")
    kinds = {violation.kind for violation in violations}
    assert {
        "credential_or_secret_field",
        "executor_action",
        "scheduler_or_default_fetch",
        "advice_alpha_profit_claim",
    }.issubset(kinds)


def test_boundary_scanner_does_not_classify_public_polymarket_ids_as_secrets():
    assert scan_boundary_text(
        "public_polymarket_id=polymarket_market_123abc token=pm_token_ABCDEF123456"
    ) == ()


def test_boundary_scanner_flags_bare_noun_space_executor_phrases():
    cases: tuple[tuple[str, object], ...] = (
        ("cancellation", {"cancellation": True}),
        ("redeem shares", "redeem shares"),
        ("settle market", "settle market"),
        ("move funds", "move funds"),
    )
    for name, value in cases:
        violations = scan_boundary_text(value) if isinstance(value, str) else scan_boundary_mapping(value)
        assert any(violation.kind == "executor_action" for violation in violations), name


def test_boundary_scanner_flags_bare_and_suffixed_executor_schema_keys():
    sign = "si" + "gn"
    approve = "ap" + "prove"
    snake_case_keys = (
        "deposit", "withdraw", approve, sign, "cancel", "redeem", "settle",
        "place", "submit", "move", "deposit_funds", f"{approve}_tokens",
        f"{sign}_payload", "cancel_order", "redeem_shares", "settle_market",
        "place_order", "submit_trade", "move_funds",
    )
    camel_case_keys = (
        "depositFunds", "withdrawFunds", f"{approve}Tokens", f"{sign}Payload",
        "cancelOrder", "redeemShares", "settleMarket", "placeOrder",
        "submitTrade", "moveFunds",
    )
    for key in snake_case_keys + camel_case_keys:
        violations = scan_boundary_mapping({"properties": {key: {"type": "boolean"}}})
        assert any(violation.kind == "executor_action" for violation in violations), key


def _minimal_record_for(family: AutonomousRecordFamily) -> dict[str, object]:
    record: dict[str, object] = {field: f"{field}-value" for field in required_fields_for(family)}
    record["supersedes_record_id"] = None
    record["provenance"] = {"actor": "contract-test"}
    return record


def test_common_required_field_validator_accepts_minimal_records_and_rejects_missing_fields():
    for family in ALL_AUTONOMOUS_RECORD_FAMILIES:
        record = _minimal_record_for(family)
        validate_required_common_fields(family, record)
        validate_autonomous_record(family, record)

        missing_source_kind = dict(record)
        missing_source_kind.pop("source_kind")
        try:
            validate_required_common_fields(family, missing_source_kind)
        except AutonomousSubstrateContractError as exc:
            assert "source_kind" in str(exc)
        else:  # pragma: no cover - defensive clarity for future validators
            raise AssertionError(f"missing source_kind passed for {family.value}")


def test_event_expectation_validator_and_semantic_fields_align_with_required_contracts():
    documented_family_specific_fields = {
        "policy_id", "policy_version", "intent_id", "risk_check_id", "expires_at",
        "event_type", "redaction_profile",
    }
    for expectation in EVENT_TYPE_EXPECTATIONS:
        required = required_fields_for(expectation.record_family)
        assert expectation.semantic_idempotency_fields <= required | documented_family_specific_fields

        record = _minimal_record_for(expectation.record_family)
        for field in expectation.semantic_idempotency_fields - set(record):
            record[field] = f"{field}-value"
        validate_event_expectation(expectation.event_type, record)

        missing_semantic = dict(record)
        missing_semantic.pop(next(iter(expectation.semantic_idempotency_fields)))
        try:
            validate_event_expectation(expectation.event_type, missing_semantic)
        except AutonomousSubstrateContractError:
            pass
        else:  # pragma: no cover - defensive clarity for future validators
            raise AssertionError(f"missing semantic idempotency field passed for {expectation.event_type}")
