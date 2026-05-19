"""Write-time secret-shape detection per bead trade-trace-sy1.

Registered secret patterns are checked across guarded write-time free-text
fields. Plus log-redaction, extensibility-hook, and false-positive corpus
tests.

The write-time guard runs before any DB write so a secret never ends up
in a row at all (cf. the export-time scan in `tests/security/test_redacted_exports.py`,
which surfaces a *warning* on shipped events rather than blocking writes).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.security import (
    list_patterns,
    redact_for_log,
    register,
    reset_patterns,
    scan_text,
)


@pytest.fixture(autouse=True)
def _restore_patterns():
    """Every test starts with the built-in registry restored, even if a
    previous test (or this test) registered a custom pattern. Belt and
    braces: the autouse fixture also runs on teardown."""

    reset_patterns()
    yield
    reset_patterns()


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}).ok
    return h


def _mcp(home: Path, tool: str, args: dict | None = None):
    payload = {"home": str(home), **(args or {})}
    return mcp_call(tool, payload, actor_id="agent:default")


def _seed_instrument(home: Path) -> tuple[str, str]:
    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    return venue, inst


# -- pattern fixtures ----------------------------------------------


SECRET_FIXTURES = {
    "api_key": "sk-ABCDEFGHIJKLMNOP12345678",  # sk- + 24 alphanum (>=20)
    "slack_token": "xoxb-123456789-987654321-ABCDEFG",
    "ethereum_address": "0x1234567890abcdef1234567890abcdef12345678",
    "jwt": (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        ".abcdef1234567890ABCDEF"
    ),
}


# -- 1. ≥1 negative test per (pattern × field) — 12 total -----------


@pytest.mark.parametrize("pattern_kind,secret", list(SECRET_FIXTURES.items()))
def test_thesis_body_rejects_secret(home, pattern_kind, secret):
    """thesis.body containing a secret-shape → VALIDATION_ERROR with
    pattern_kind + match_offset."""

    _venue, inst = _seed_instrument(home)
    body = f"My thesis: leaked {secret} from notes"
    env = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": body,
    })
    assert env.ok is False, f"expected rejection on {pattern_kind}"
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "body"
    assert env.error.details["pattern_kind"] == pattern_kind
    # match_offset points into the body string.
    offset = env.error.details["match_offset"]
    length = env.error.details["match_length"]
    assert body[offset : offset + length] == secret


@pytest.mark.parametrize("field", ["title", "note", "excerpt", "extracted_text", "summary"])
@pytest.mark.parametrize("pattern_kind,secret", list(SECRET_FIXTURES.items()))
def test_source_free_text_rejects_secret(home, field, pattern_kind, secret):
    """source free-text containing a secret-shape → VALIDATION_ERROR."""

    env = _mcp(home, "source.add", {
        "kind": "note", "stance": "neutral",
        field: f"Pasted from clipboard: {secret}",
        "idempotency_key": f"00000000-0000-4000-8000-{pattern_kind:>012}"[:36],
    })
    assert env.ok is False, f"expected rejection on {pattern_kind}"
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == field
    assert env.error.details["pattern_kind"] == pattern_kind


@pytest.mark.parametrize("pattern_kind,secret", list(SECRET_FIXTURES.items()))
def test_decision_reason_rejects_secret(home, pattern_kind, secret):
    """decision.reason containing a secret-shape → VALIDATION_ERROR."""

    _venue, inst = _seed_instrument(home)
    env = _mcp(home, "decision.add", {
        "type": "skip", "instrument_id": inst,
        "reason": f"skipping — leaked {secret} in my notes",
        "idempotency_key": f"00000000-0000-4000-8000-d{pattern_kind:>11}"[:36],
    })
    assert env.ok is False, f"expected rejection on {pattern_kind}"
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "reason"
    assert env.error.details["pattern_kind"] == pattern_kind


# -- per bead trade-trace-7j1l: extended free-text surfaces ---------
#
# Until this bead landed, the secret-pattern guard only covered
# thesis.body / decision.reason / source.{title,note,excerpt,
# extracted_text,summary} / memory_node.{body,title}. The audit lane
# 7 SEC-01 found several other long-form free-text columns that bypass
# the scan. The policy now scans every long-form free-text field
# below; narrow enum / id / label columns are documented exempt in
# docs/architecture/security.md §6.5.


@pytest.mark.parametrize(
    "field",
    ["falsification_criteria", "exit_triggers", "risk_notes",
     "invalidation_condition", "risk_unit_label"],
)
@pytest.mark.parametrize("pattern_kind,secret", list(SECRET_FIXTURES.items()))
def test_thesis_long_form_fields_reject_secrets(
    home, field, pattern_kind, secret,
):
    """Each long-form thesis free-text field rejects secret-shaped
    content per bead trade-trace-7j1l."""

    _venue, inst = _seed_instrument(home)
    env = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes",
        "body": "ordinary body — no secret here",
        field: f"contains {secret} in pasted notes",
    })
    assert env.ok is False, f"expected rejection on {field}/{pattern_kind}"
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == field
    assert env.error.details["pattern_kind"] == pattern_kind


def test_instrument_resolution_criteria_text_rejects_secret(home):
    """instrument.resolution_criteria_text is long-form free text per
    bead trade-trace-7j1l."""

    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    secret = SECRET_FIXTURES["api_key"]
    env = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market",
        "title": "X",
        "resolution_criteria_text": f"Settles when {secret} payload arrives",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "resolution_criteria_text"


def test_forecast_resolution_rule_text_rejects_secret(home):
    """forecast.resolution_rule_text is long-form free text per bead
    trade-trace-7j1l."""

    _venue, inst = _seed_instrument(home)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "...",
    }).data["id"]
    secret = SECRET_FIXTURES["slack_token"]
    env = _mcp(home, "forecast.add", {
        "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
        "resolution_rule_text": f"Trigger on {secret} payload",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "resolution_rule_text"


@pytest.mark.parametrize("field", ["description", "hypothesis"])
def test_strategy_long_form_fields_reject_secrets(home, field):
    """strategy.description and strategy.hypothesis are long-form free
    text per bead trade-trace-7j1l."""

    secret = SECRET_FIXTURES["api_key"]
    env = _mcp(home, "strategy.create", {
        "slug": "strat", "name": "Strat",
        field: f"includes {secret}",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == field


def test_strategy_update_description_rejects_secret(home):
    """strategy.update applies the same scan when description changes."""

    created = _mcp(home, "strategy.create", {
        "slug": "strat", "name": "Strat",
    })
    assert created.ok, created
    secret = SECRET_FIXTURES["jwt"]
    env = _mcp(home, "strategy.update", {
        "strategy_id": created.data["id"],
        "description": f"refined with {secret}",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "description"


def test_playbook_description_rejects_secret(home):
    """playbook.create.description is long-form free text per bead
    trade-trace-7j1l."""

    secret = SECRET_FIXTURES["api_key"]
    env = _mcp(home, "playbook.create", {
        "name": "PB",
        "description": f"playbook spec: {secret}",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "description"


def test_metadata_json_rejects_nested_secret_value(home):
    env = _mcp(home, "venue.add", {
        "name": "PM",
        "kind": "prediction_market",
        "metadata_json": {"notes": {"token": SECRET_FIXTURES["api_key"]}},
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "metadata_json"
    assert env.error.details["pattern_kind"] == "api_key"


def test_metadata_json_rejects_raw_json_secret_value(home):
    env = _mcp(home, "venue.add", {
        "name": "PM",
        "kind": "prediction_market",
        "metadata_json": '{"notes": ["leaked xoxb-1234567890-ABCDEF"]}',
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "metadata_json"
    assert env.error.details["pattern_kind"] == "slack_token"


# -- 2. log-output redaction ---------------------------------------


@pytest.mark.parametrize("pattern_kind,secret", list(SECRET_FIXTURES.items()))
def test_redact_for_log_replaces_secret_with_token(pattern_kind, secret):
    """`redact_for_log` strips the secret from a log-bound string,
    substituting `REDACTED-<pattern_kind>`. Used by the logging layer
    so log files never carry the original bytes."""

    text = f"prefix {secret} suffix"
    redacted = redact_for_log(text)
    assert secret not in redacted, (
        f"redact_for_log left {pattern_kind} secret in log output"
    )
    assert f"REDACTED-{pattern_kind}" in redacted


def test_redact_for_log_idempotent_on_clean_text():
    text = "no secrets here, just plain prose."
    assert redact_for_log(text) == text


# -- 3. extensibility hook ---------------------------------------


def test_register_adds_custom_pattern_and_blocks_write(home):
    """Acceptance: registering a new pattern at runtime takes effect
    without library changes."""

    register("custom_token", r"CUSTOMTOKEN-[A-Z0-9]{8,}")
    _venue, inst = _seed_instrument(home)
    env = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes",
        "body": "leaked CUSTOMTOKEN-ABCD1234EFGH from chat",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["pattern_kind"] == "custom_token"


def test_reset_patterns_restores_builtin_set():
    """After a custom register + reset, the registry holds only the
    four built-in patterns."""

    register("custom_token", r"CUSTOMTOKEN-[A-Z0-9]+")
    assert "custom_token" in list_patterns()
    reset_patterns()
    assert set(list_patterns()) == {
        "api_key", "slack_token", "ethereum_address", "jwt",
    }


def test_register_rejects_invalid_name():
    from trade_trace.security.patterns import SecretPatternError

    with pytest.raises(SecretPatternError):
        register("Capital-Names-Forbidden", r"abc")


def test_register_rejects_invalid_regex():
    from trade_trace.security.patterns import SecretPatternError

    with pytest.raises(SecretPatternError):
        register("bad_regex", r"unbalanced(")


# -- 4. false-positive guard (4 corpus tests) -------------------


BENIGN_CORPUS = [
    # 40-char hex digest that ISN'T an Ethereum address (no 0x prefix).
    ("hash_no_prefix",
     "sha1 hash: abcdef1234567890abcdef1234567890abcdef12"),
    # `sk-` followed by fewer than 20 chars (below api_key threshold).
    ("short_skdash",
     "instrument symbol sk-1234567"),
    # Three short dot-separated chunks (below jwt segment minimum).
    ("short_dotted",
     "file.name.txt is a path, not a token"),
    # A regular sentence with `xox` but no Slack token suffix.
    ("xox_substring",
     "the company's xoxo greeting is not a token"),
]


@pytest.mark.parametrize("name,benign_text", BENIGN_CORPUS)
def test_benign_text_does_not_trigger_any_pattern(name, benign_text):
    """The patterns must not over-fire on benign substrates documented
    in the bead acceptance (false-positive corpus)."""

    matches = scan_text(benign_text)
    assert matches == [], (
        f"benign fixture {name!r} unexpectedly matched: "
        f"{[(m.pattern_kind, m.match) for m in matches]}"
    )


# -- 5. happy path: clean text still writes successfully ---------


def test_clean_thesis_body_writes_normally(home):
    _venue, inst = _seed_instrument(home)
    env = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes",
        "body": "Earnings beat consensus on AI demand; no secrets here.",
    })
    assert env.ok, env


def test_clean_source_excerpt_writes_normally(home):
    env = _mcp(home, "source.add", {
        "kind": "note", "stance": "neutral",
        "excerpt": "A perfectly normal note about earnings.",
        "idempotency_key": "00000000-0000-4000-8000-clean-00000",
    })
    assert env.ok, env


def test_clean_decision_reason_writes_normally(home):
    _venue, inst = _seed_instrument(home)
    env = _mcp(home, "decision.add", {
        "type": "skip", "instrument_id": inst,
        "reason": "spread too wide vs expected edge",
        "idempotency_key": "00000000-0000-4000-8000-clean-decis",
    })
    assert env.ok, env
