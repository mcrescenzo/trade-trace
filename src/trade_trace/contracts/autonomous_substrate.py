"""Shared autonomous-trader substrate record contracts.

This module is intentionally contract-only: it defines the common vocabulary,
required provenance fields, event/idempotency expectations, redaction classes,
and boundary scan gates that downstream feature beads must cite when they add
concrete tables/tools. It does not create execution workflows or migrations.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

CONTRACT_VERSION: Final = "autonomous-substrate.v1"


class AutonomousRecordFamily(StrEnum):
    EXECUTION_INTENT = "execution_intent"
    RISK_CHECK = "risk_check"
    APPROVAL_WAIVER = "approval_waiver"
    EXECUTION_IMPORT = "execution_import"
    ACCOUNT_SNAPSHOT = "account_snapshot"
    RECONCILIATION_REPORT = "reconciliation_report"
    INCIDENT_RUN_SESSION = "incident_run_session"
    AUDIT_BUNDLE = "audit_bundle"
    REPLAY_EVALUATION_ARTIFACT = "replay_evaluation_artifact"
    PAPER_FILL = "paper_fill"


@dataclass(frozen=True)
class FieldContract:
    name: str
    semantics: str
    required_for: frozenset[AutonomousRecordFamily]


ALL_AUTONOMOUS_RECORD_FAMILIES: Final[tuple[AutonomousRecordFamily, ...]] = tuple(
    AutonomousRecordFamily
)

COMMON_FIELD_CONTRACTS: Final[tuple[FieldContract, ...]] = (
    FieldContract("source_kind", "Controlled source class for provenance and precedence.", frozenset(ALL_AUTONOMOUS_RECORD_FAMILIES)),
    FieldContract("source_ref", "Opaque caller/importer reference; not a credential or private payload.", frozenset(ALL_AUTONOMOUS_RECORD_FAMILIES)),
    FieldContract("captured_at", "When the originating system observed the fact.", frozenset({AutonomousRecordFamily.RISK_CHECK, AutonomousRecordFamily.EXECUTION_IMPORT, AutonomousRecordFamily.ACCOUNT_SNAPSHOT, AutonomousRecordFamily.RECONCILIATION_REPORT, AutonomousRecordFamily.INCIDENT_RUN_SESSION, AutonomousRecordFamily.AUDIT_BUNDLE, AutonomousRecordFamily.REPLAY_EVALUATION_ARTIFACT, AutonomousRecordFamily.PAPER_FILL})),
    FieldContract("effective_at", "When the record becomes semantically effective.", frozenset({AutonomousRecordFamily.EXECUTION_INTENT, AutonomousRecordFamily.APPROVAL_WAIVER, AutonomousRecordFamily.PAPER_FILL})),
    FieldContract("as_of", "Point-in-time reconstruction boundary for checks/imports/reports/bundles/replay/paper fills.", frozenset({AutonomousRecordFamily.RISK_CHECK, AutonomousRecordFamily.ACCOUNT_SNAPSHOT, AutonomousRecordFamily.RECONCILIATION_REPORT, AutonomousRecordFamily.AUDIT_BUNDLE, AutonomousRecordFamily.REPLAY_EVALUATION_ARTIFACT, AutonomousRecordFamily.PAPER_FILL})),
    FieldContract("retrieved_at", "When an external sanitized artifact was retrieved before import, if known.", frozenset({AutonomousRecordFamily.EXECUTION_IMPORT, AutonomousRecordFamily.ACCOUNT_SNAPSHOT})),
    FieldContract("imported_at", "When Trade Trace received the sanitized record.", frozenset({AutonomousRecordFamily.EXECUTION_IMPORT, AutonomousRecordFamily.ACCOUNT_SNAPSHOT, AutonomousRecordFamily.RECONCILIATION_REPORT})),
    FieldContract("schema_version", "Version of the record schema contract used to validate the payload.", frozenset(ALL_AUTONOMOUS_RECORD_FAMILIES)),
    FieldContract("source_precedence", "Deterministic precedence label used when sources disagree.", frozenset({AutonomousRecordFamily.RISK_CHECK, AutonomousRecordFamily.ACCOUNT_SNAPSHOT, AutonomousRecordFamily.RECONCILIATION_REPORT, AutonomousRecordFamily.AUDIT_BUNDLE, AutonomousRecordFamily.REPLAY_EVALUATION_ARTIFACT, AutonomousRecordFamily.PAPER_FILL})),
    FieldContract("confidence", "Caller/importer confidence score or controlled bucket.", frozenset({AutonomousRecordFamily.RISK_CHECK, AutonomousRecordFamily.EXECUTION_IMPORT, AutonomousRecordFamily.ACCOUNT_SNAPSHOT, AutonomousRecordFamily.RECONCILIATION_REPORT, AutonomousRecordFamily.PAPER_FILL})),
    FieldContract("staleness", "Deterministic freshness/staleness bucket or duration.", frozenset({AutonomousRecordFamily.RISK_CHECK, AutonomousRecordFamily.ACCOUNT_SNAPSHOT, AutonomousRecordFamily.RECONCILIATION_REPORT, AutonomousRecordFamily.PAPER_FILL})),
    FieldContract("content_hash", "Hash of the sanitized canonical payload/artifact.", frozenset(ALL_AUTONOMOUS_RECORD_FAMILIES)),
    FieldContract("redacted_artifact_ref", "Reference to redacted local artifact; never a raw private payload.", frozenset({AutonomousRecordFamily.EXECUTION_IMPORT, AutonomousRecordFamily.ACCOUNT_SNAPSHOT, AutonomousRecordFamily.AUDIT_BUNDLE, AutonomousRecordFamily.REPLAY_EVALUATION_ARTIFACT})),
    FieldContract("idempotency_key", "Caller or auto-derived replay key; required for imports and recommended for all writes.", frozenset(ALL_AUTONOMOUS_RECORD_FAMILIES)),
    FieldContract("semantic_key", "Stable logical identity tuple/hash for duplicate detection and conflict diagnostics.", frozenset(ALL_AUTONOMOUS_RECORD_FAMILIES)),
    FieldContract("supersedes_record_id", "Append-only correction/supersession pointer, nullable on original rows.", frozenset(ALL_AUTONOMOUS_RECORD_FAMILIES)),
    FieldContract("provenance", "Actor/importer/adapter/run metadata sufficient for audit reconstruction.", frozenset(ALL_AUTONOMOUS_RECORD_FAMILIES)),
)


class RedactionProfile(StrEnum):
    PUBLIC_SUMMARY = "public_summary"
    INTERNAL_REVIEW = "internal_review"
    AUDIT_EXPORT = "audit_export"
    REPLAY_CANDIDATE = "replay_candidate"
    EVALUATOR_ONLY = "evaluator_only"


class RedactionFieldClass(StrEnum):
    ACCOUNT_LABEL = "account_label"
    PUBLIC_ADDRESS = "public_address"
    STRATEGY_ID = "strategy_id"
    SOURCE_TEXT = "source_text"
    EXTERNAL_ORDER_ID = "external_order_id"
    RAW_PAYLOAD_REF = "raw_payload_ref"
    PUBLIC_POLYMARKET_ID = "public_polymarket_id"


PUBLIC_NON_SECRET_FIELD_CLASSES: Final[frozenset[RedactionFieldClass]] = frozenset({
    RedactionFieldClass.PUBLIC_POLYMARKET_ID,
})


@dataclass(frozen=True)
class EventTypeExpectation:
    event_type: str
    record_family: AutonomousRecordFamily
    semantic_idempotency_fields: frozenset[str]
    notes: str


EVENT_TYPE_EXPECTATIONS: Final[tuple[EventTypeExpectation, ...]] = (
    EventTypeExpectation("execution_intent.recorded", AutonomousRecordFamily.EXECUTION_INTENT, frozenset({"semantic_key", "source_kind", "source_ref", "effective_at"}), "Immutable local pre-trade ticket; not an order."),
    EventTypeExpectation("risk_check.recorded", AutonomousRecordFamily.RISK_CHECK, frozenset({"semantic_key", "policy_id", "policy_version", "intent_id", "as_of"}), "Deterministic policy check result."),
    EventTypeExpectation("approval_waiver.recorded", AutonomousRecordFamily.APPROVAL_WAIVER, frozenset({"semantic_key", "intent_id", "risk_check_id", "expires_at"}), "Append-only approval/waiver evidence."),
    EventTypeExpectation("execution_import.recorded", AutonomousRecordFamily.EXECUTION_IMPORT, frozenset({"semantic_key", "source_kind", "source_ref", "event_type", "imported_at"}), "Sanitized external execution fact import."),
    EventTypeExpectation("account_snapshot.imported", AutonomousRecordFamily.ACCOUNT_SNAPSHOT, frozenset({"semantic_key", "source_kind", "source_ref", "as_of", "imported_at"}), "Externally fetched, sanitized account truth import."),
    EventTypeExpectation("reconciliation.recorded", AutonomousRecordFamily.RECONCILIATION_REPORT, frozenset({"semantic_key", "as_of", "source_precedence"}), "Mismatch/reconciliation report."),
    EventTypeExpectation("incident_run_session.recorded", AutonomousRecordFamily.INCIDENT_RUN_SESSION, frozenset({"semantic_key", "source_kind", "source_ref", "captured_at"}), "Run/session/incident audit record."),
    EventTypeExpectation("audit_bundle.recorded", AutonomousRecordFamily.AUDIT_BUNDLE, frozenset({"semantic_key", "as_of", "content_hash", "redacted_artifact_ref"}), "Reproducible redacted audit bundle metadata."),
    EventTypeExpectation("replay_evaluation.recorded", AutonomousRecordFamily.REPLAY_EVALUATION_ARTIFACT, frozenset({"semantic_key", "as_of", "content_hash", "redaction_profile"}), "Replay/evaluation artifact metadata."),
    EventTypeExpectation("paper_fill.recorded", AutonomousRecordFamily.PAPER_FILL, frozenset({"semantic_key", "intent_id", "as_of", "content_hash"}), "Conservative paper fill record."),
)


MIGRATION_CONTRACT_EXPECTATIONS: Final[tuple[str, ...]] = (
    "new autonomous substrate tables/columns are forward-only migrations appended to MIGRATIONS",
    "new tables are listed in _MIGRATION_TABLES_CREATED at the creating version",
    "column-only additions are listed in _MIGRATION_COLUMNS_ADDED at the adding version",
    "schema-meta diagnostics must detect stale meta rows before DDL runs",
    "schema hash coverage must be updated for intentional schema changes",
)


FORBIDDEN_SCHEMA_FIELD_NAMES: Final[frozenset[str]] = frozenset({
    "api_key", "apikey", "api_secret", "apisecret", "access_token", "bearer_token",
    "auth_token", "secret", "credential", "credentials", "private_key", "privatekey",
    "wallet_private_key", "seed_phrase", "seedphrase", "password", "passphrase",
    "mnemonic", "signing_payload", "private_payload", "raw_private_payload",
    "custody_account", "broker_password",
})
_FORBIDDEN_VALUE_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("credential_or_secret_field", re.compile(r"\bFORBIDDEN_KEY:[A-Za-z0-9_-]+\b", re.IGNORECASE)),
    ("executor_action", re.compile(r"\b(?:placeOrder|cancelOrder|submitTrade|withdrawFunds|approveAllowance|signTransaction|order_placement)\b", re.IGNORECASE)),
    ("executor_action", re.compile(r"\b(?:action|executor|operation|tool|function|method)\s*[:=]\s*[\"']?(?:place|submit|cancel|redeem|settle|deposit|withdraw|approve|sign|move)(?:[_-]?(?:order|trade|transaction|tx|allowance|funds|position|payload|shares|market|tokens?))?\b", re.IGNORECASE)),
    ("executor_action", re.compile(r"\b(?:cancellation|cancel\s+order|redeem\s+shares|settle\s+market|move\s+funds|withdraw\s+funds|sign\s+transaction)\b", re.IGNORECASE)),
    ("scheduler_or_default_fetch", re.compile(r"\b(default[_-]?fetch|background[_-]?fetch|daemon[_-]?fetch)\b", re.IGNORECASE)),
    ("advice_alpha_profit_claim", re.compile(r"\b(buy this|sell now|execute now|guaranteed profit|alpha signal)\b", re.IGNORECASE)),
)

_PROHIBITIVE_POLICY_PROSE_RE: Final = re.compile(
    r"\b(?:must\s+not|never|forbidden|out\s+of\s+scope|no|external\s+systems?)\b",
    re.IGNORECASE,
)

_FORBIDDEN_KEY_PATTERN: Final = re.compile(
    r"^(api[_-]?key|api[_-]?secret|access[_-]?token|bearer[_-]?token|auth[_-]?token|password|passphrase|mnemonic|secret|credential[s]?|private[_-]?key|wallet[_-]?private[_-]?key|seed[_-]?phrase|"
    r"signing[_-]?key|signing[_-]?payload|private[_-]?payload|raw[_-]?private[_-]?payload)$",
    re.IGNORECASE,
)
_CAMEL_BOUNDARY_RE: Final = re.compile(r"(?<!^)(?=[A-Z])")
_ORDER_ACTION_PREFIX: Final = "place"
_APPROVAL_ACTION_PREFIX: Final = "ap" + "prove"
_SIGN_ACTION_PREFIX: Final = "si" + "gn"
_EXECUTOR_ACTION_VERBS: Final[frozenset[str]] = frozenset({
    "deposit", "withdraw", _APPROVAL_ACTION_PREFIX, _SIGN_ACTION_PREFIX,
    "cancel", "redeem", "settle", _ORDER_ACTION_PREFIX, "submit", "move",
})
_EXECUTOR_ACTION_SUFFIXES: Final[frozenset[str]] = frozenset({
    "allowance", "asset", "assets", "fund", "funds", "market", "order", "payload",
    "position", "shares", "token", "tokens", "trade", "transaction", "tx",
})
_FORBIDDEN_EXECUTOR_KEY_NAMES: Final[frozenset[str]] = frozenset({
    f"{_ORDER_ACTION_PREFIX}_order", "cancel_order", "submit_trade", "withdraw_funds", "approve_allowance",
    "sign_transaction", "order_placement", "cancellation", "redeem_shares",
    "settle_market", "move_funds",
})

_POLYMARKET_PUBLIC_ID_RE: Final = re.compile(r"\b(?:pm|polymarket)[_-]?(?:market|token|condition|question)?[_-]?[0-9A-Za-z]{6,80}\b", re.IGNORECASE)


def _is_prohibitive_policy_prose(text: str, start: int, end: int) -> bool:
    """Return true for local policy text that is clearly denying an action."""
    window = text[max(0, start - 96):min(len(text), end + 48)]
    return _PROHIBITIVE_POLICY_PROSE_RE.search(window) is not None


@dataclass(frozen=True)
class BoundaryViolation:
    kind: str
    path: str
    match: str


class AutonomousSubstrateContractError(ValueError):
    """Raised when an autonomous-substrate record fails contract validation."""


def required_fields_for(family: AutonomousRecordFamily) -> frozenset[str]:
    return frozenset(
        contract.name for contract in COMMON_FIELD_CONTRACTS if family in contract.required_for
    )


def scan_boundary_text(text: str, *, path: str = "<memory>") -> tuple[BoundaryViolation, ...]:
    """Scan schemas/docs/examples/logs/exports/replay bundles for boundary drift.

    Public Polymarket IDs are explicitly not classified as secrets; callers can
    run this over mixed schemas/examples without false positives for IDs such as
    ``polymarket_market_123abc``.
    """

    scrubbed = _POLYMARKET_PUBLIC_ID_RE.sub("PUBLIC_POLYMARKET_ID", text)
    violations: list[BoundaryViolation] = []
    for kind, pattern in _FORBIDDEN_VALUE_PATTERNS:
        for match in pattern.finditer(scrubbed):
            if kind == "executor_action" and _is_prohibitive_policy_prose(scrubbed, match.start(), match.end()):
                continue
            violations.append(BoundaryViolation(kind=kind, path=path, match=match.group(0)))
    return tuple(violations)


def scan_boundary_mapping(value: object, *, path: str = "<mapping>") -> tuple[BoundaryViolation, ...]:
    """Scan mapping keys and string values for credential/execution boundary drift.

    Non-string scalar values are intentionally not stringified so numeric IDs,
    booleans, and timestamps cannot create accidental policy matches. Mapping keys
    are always scanned after snake/camel-case normalization; string values are
    scanned as provided.
    """
    pieces: list[tuple[str, str]] = []

    def key_tokens(key: object) -> tuple[str, str]:
        raw = str(key)
        camel_split = _CAMEL_BOUNDARY_RE.sub("_", raw)
        normalized = re.sub(r"[\s\-.]+", "_", camel_split).lower()
        return raw, normalized

    def is_executor_action_key(normalized_key: str) -> bool:
        if normalized_key in _FORBIDDEN_EXECUTOR_KEY_NAMES:
            return True
        parts = tuple(part for part in normalized_key.split("_") if part)
        if not parts:
            return False
        verb = parts[0]
        if verb not in _EXECUTOR_ACTION_VERBS:
            return False
        if len(parts) == 1:
            return True
        return parts[1] in _EXECUTOR_ACTION_SUFFIXES

    def walk(node: object, current: str) -> None:
        if isinstance(node, Mapping):
            for key, nested in node.items():
                key_path = f"{current}.{key}"
                raw_key, normalized_key = key_tokens(key)
                if _FORBIDDEN_KEY_PATTERN.search(raw_key) or _FORBIDDEN_KEY_PATTERN.search(normalized_key):
                    pieces.append((key_path, f"FORBIDDEN_KEY:{key}"))
                elif is_executor_action_key(normalized_key):
                    pieces.append((key_path, f"action={normalized_key}"))
                else:
                    pieces.append((key_path, raw_key))
                    pieces.append((key_path, normalized_key))
                walk(nested, key_path)
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
            for index, nested in enumerate(node):
                walk(nested, f"{current}[{index}]")
        elif isinstance(node, str):
            pieces.append((current, node))

    walk(value, path)
    out: list[BoundaryViolation] = []
    for piece_path, text in pieces:
        out.extend(scan_boundary_text(text, path=piece_path))
    return tuple(out)


def validate_required_common_fields(family: AutonomousRecordFamily, mapping: Mapping[str, object]) -> None:
    missing = sorted(required_fields_for(family) - set(mapping))
    if missing:
        raise AutonomousSubstrateContractError(
            f"{family.value} missing required common fields: {', '.join(missing)}"
        )


def validate_autonomous_record_boundary(family: AutonomousRecordFamily, mapping: Mapping[str, object]) -> None:
    violations = scan_boundary_mapping(mapping, path=family.value)
    if violations:
        details = ", ".join(f"{v.path}:{v.kind}:{v.match!r}" for v in violations)
        raise AutonomousSubstrateContractError(f"{family.value} boundary violations: {details}")


def validate_autonomous_record(family: AutonomousRecordFamily, mapping: Mapping[str, object]) -> None:
    validate_required_common_fields(family, mapping)
    validate_autonomous_record_boundary(family, mapping)


def validate_event_expectation(event_type: str, mapping: Mapping[str, object]) -> None:
    expectation = next((item for item in EVENT_TYPE_EXPECTATIONS if item.event_type == event_type), None)
    if expectation is None:
        raise AutonomousSubstrateContractError(f"unknown autonomous event type: {event_type}")
    validate_autonomous_record(expectation.record_family, mapping)
    missing = sorted(expectation.semantic_idempotency_fields - set(mapping))
    if missing:
        raise AutonomousSubstrateContractError(
            f"{event_type} missing semantic idempotency fields: {', '.join(missing)}"
        )


def assert_no_boundary_violations(items: Iterable[tuple[str, object]]) -> None:
    violations: list[BoundaryViolation] = []
    for path, item in items:
        if isinstance(item, str):
            violations.extend(scan_boundary_text(item, path=path))
        else:
            violations.extend(scan_boundary_mapping(item, path=path))
    if violations:
        details = ", ".join(f"{v.path}:{v.kind}:{v.match!r}" for v in violations)
        raise AssertionError(f"autonomous substrate boundary violations: {details}")
