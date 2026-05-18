"""Write-time secret-shape detection per bead trade-trace-sy1.

Four registered patterns × three guarded free-text fields = 12 negative
test slots. Plus log-redaction, extensibility-hook, and false-positive
corpus tests.

The write-time guard runs before any DB write so a secret never ends up
in a row at all (cf. the export-time scan in `tests/security/test_redacted_exports.py`,
which surfaces a *warning* on shipped events rather than blocking writes).
"""

from __future__ import annotations

import re
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


@pytest.mark.parametrize("pattern_kind,secret", list(SECRET_FIXTURES.items()))
def test_source_excerpt_rejects_secret(home, pattern_kind, secret):
    """source.excerpt containing a secret-shape → VALIDATION_ERROR."""

    env = _mcp(home, "source.add", {
        "kind": "note", "stance": "neutral",
        "excerpt": f"Pasted from clipboard: {secret}",
        "idempotency_key": f"00000000-0000-4000-8000-{pattern_kind:>012}"[:36],
    })
    assert env.ok is False, f"expected rejection on {pattern_kind}"
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "excerpt"
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
