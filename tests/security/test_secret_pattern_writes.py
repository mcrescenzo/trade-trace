"""Write-time secret-shape detection per bead trade-trace-sy1.

Registered secret patterns are checked across guarded write-time free-text
fields. Plus log-redaction, extensibility-hook, and false-positive corpus
tests.

The write-time guard runs before any DB write so a secret never ends up
in a row at all (cf. the export-time scan in `tests/security/test_redacted_exports.py`,
which surfaces a *warning* on shipped events rather than blocking writes).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import trade_trace
from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.core import build_registry
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



def _seed_instrument(home: Path) -> tuple[str, str]:
    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    return venue, inst


# -- pattern fixtures ----------------------------------------------


# Dummy secrets per bead trade-trace-awxq: built from non-contiguous
# parts so public secret scanners (gitleaks, GitHub secret scanning,
# etc.) cannot flag the source file. The runtime value still satisfies
# the trade_trace regex in `src/trade_trace/security/patterns.py`.
_SK = "s" + "k" + "-"
_XOXB = "xo" + "xb" + "-"
_ZERO_X = "0" + "x"
_EYJ = "ey" + "J"

SECRET_FIXTURES = {
    "api_key": _SK + ("FAKEKEY" * 4)[:24],
    "slack_token": _XOXB + "0" * 9 + "-" + "1" * 9 + "-" + "FAKETKN",
    "ethereum_address": _ZERO_X + "abcdef0123" * 4,
    "jwt": (
        _EYJ + "hbGciOiJIUzI1NiIsInR5cCI6IktKV1RGSVgifQ"
        "." + _EYJ + "zdWJfZml4dHVyZSI6IjFmaXh0dXJlIn0"
        "." + "fixture" + "1234567890ABCDEFGHIJ"
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


@pytest.mark.parametrize(
    "field",
    ["rationale_body", "falsification_criteria", "exit_triggers", "risk_notes"],
)
def test_forecast_folded_thesis_free_text_rejects_secret(home, field):
    """forecast.add can create the folded thesis prerequisite; those persisted
    thesis free-text fields need the same scan as thesis.add."""

    _venue, inst = _seed_instrument(home)
    args = {
        "instrument_id": inst,
        "kind": "binary",
        "rationale_body": "clean rationale",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
        "idempotency_key": f"folded-{field}",
    }
    args[field] = f"folded path leaked {SECRET_FIXTURES['api_key']}"

    env = _mcp(home, "forecast.add", args)

    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == field
    assert env.error.details["pattern_kind"] == "api_key"


@pytest.mark.parametrize("field", ["description", "hypothesis"])
def test_strategy_long_form_fields_reject_secrets(home, field):
    """strategy.description and strategy.hypothesis are long-form free
    text per bead trade-trace-7j1l."""

    secret = SECRET_FIXTURES["api_key"]
    env = _mcp(home, "strategy.upsert", {
        "slug": "strat", "name": "Strat",
        field: f"includes {secret}",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == field


def test_strategy_update_description_rejects_secret(home):
    """strategy.update applies the same scan when description changes."""

    created = _mcp(home, "strategy.upsert", {
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
    env = _mcp(home, "playbook.upsert", {
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
        "metadata_json": '{"notes": ["leaked ' + _XOXB + '1234567890-ABCDEF"]}',
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "metadata_json"
    assert env.error.details["pattern_kind"] == "slack_token"


# -- bead trade-trace-21q4: strategy + playbook metadata bypass --


def test_strategy_create_meta_json_rejects_secret(home):
    """strategy.create.meta_json must run the same dual-layer guard as
    ledger metadata_json (bead trade-trace-21q4)."""

    env = _mcp(home, "strategy.upsert", {
        "name": "Range Trader", "slug": "range-trader",
        "meta_json": {"notes": SECRET_FIXTURES["api_key"]},
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "meta_json"
    assert env.error.details["pattern_kind"] == "api_key"


def test_strategy_create_meta_json_rejects_credential_key(home):
    env = _mcp(home, "strategy.upsert", {
        "name": "Range Trader", "slug": "range-trader",
        "meta_json": {"broker": {"api_key": "anything"}},
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "meta_json"
    assert env.error.details["credential_key"] == "api_key"


def test_strategy_update_meta_json_rejects_secret(home):
    created = _mcp(home, "strategy.upsert", {
        "name": "S", "slug": "s-1",
    })
    assert created.ok, created
    env = _mcp(home, "strategy.update", {
        "strategy_id": created.data["id"],
        "meta_json": {"notes": SECRET_FIXTURES["slack_token"]},
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "meta_json"
    assert env.error.details["pattern_kind"] == "slack_token"


def test_playbook_create_metadata_json_rejects_secret(home):
    env = _mcp(home, "playbook.upsert", {
        "name": "PB",
        "metadata_json": {"deep": {"creds": SECRET_FIXTURES["jwt"]}},
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "metadata_json"
    assert env.error.details["pattern_kind"] == "jwt"


def test_playbook_create_metadata_json_rejects_credential_key(home):
    env = _mcp(home, "playbook.upsert", {
        "name": "PB",
        "metadata_json": {"private_key": "not-stored"},
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "metadata_json"
    assert env.error.details["credential_key"] == "private_key"


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


# -- bead trade-trace-14iy ReDoS guards ----------------------------


def test_register_rejects_overlong_regex_source_per_redos_guard():
    """Per bead trade-trace-14iy / DEBT-041: register() caps the
    source length of a caller-supplied regex at MAX_REGEX_SOURCE_LENGTH
    so a pathological pattern can't be smuggled through the
    extension point."""

    from trade_trace.security.patterns import (
        MAX_REGEX_SOURCE_LENGTH,
        SecretPatternError,
    )

    # One character over the cap, syntactically valid (a long
    # character class). This would otherwise compile fine.
    overlong = "[a-z]" + "z" * MAX_REGEX_SOURCE_LENGTH
    assert len(overlong) > MAX_REGEX_SOURCE_LENGTH
    with pytest.raises(SecretPatternError) as exc:
        register("overlong", overlong)
    msg = str(exc.value)
    assert "MAX_REGEX_SOURCE_LENGTH" in msg
    assert "trade-trace-14iy" in msg


def test_register_rejects_overlong_compiled_regex_source_per_redos_guard():
    """The same source-length cap applies when callers pass an already
    compiled regex; compiled patterns still expose their original
    `.pattern` source and are part of the runtime registration surface."""

    from trade_trace.security.patterns import (
        MAX_REGEX_SOURCE_LENGTH,
        SecretPatternError,
    )

    overlong = re.compile("[a-z]" + "z" * MAX_REGEX_SOURCE_LENGTH)
    assert len(overlong.pattern) > MAX_REGEX_SOURCE_LENGTH
    with pytest.raises(SecretPatternError) as exc:
        register("overlong_compiled", overlong)
    msg = str(exc.value)
    assert "MAX_REGEX_SOURCE_LENGTH" in msg
    assert "trade-trace-14iy" in msg


def test_register_rejects_nested_quantifier_per_redos_guard():
    """Per bead trade-trace-14iy / DEBT-041: register() rejects patterns
    with nested quantifiers (e.g. (a+)+) that can cause catastrophic
    backtracking."""

    from trade_trace.security.patterns import SecretPatternError

    with pytest.raises(SecretPatternError) as exc:
        register("nested_plus", r"(a+)+")
    assert "nested quantifier" in str(exc.value).lower() or "backtracking" in str(exc.value).lower()
    assert "trade-trace-14iy" in str(exc.value)


def test_register_rejects_backreference_per_redos_guard():
    """Backreferences can also cause pathological backtracking and are
    rejected by the structural guard."""

    from trade_trace.security.patterns import SecretPatternError

    with pytest.raises(SecretPatternError) as exc:
        register("backref", r"(abc)\1")
    assert "backreference" in str(exc.value).lower() or "backtracking" in str(exc.value).lower()
    assert "trade-trace-14iy" in str(exc.value)


@pytest.mark.parametrize(
    "pattern",
    [
        r"(a{2,})+",      # {n,} inside a quantified group — the bead repro
        r"(a{2,3})+",     # {n,m}
        r"(a{2})+",       # {n}
        r"(ab{2,}c)*",    # curly quantifier mid-group, outer *
    ],
)
def test_register_rejects_curly_brace_nested_quantifier_per_redos_guard(pattern):
    """Per bead trade-trace-9o2t: the nested-quantifier guard previously
    only looked for the symbolic quantifiers (*, +, ?) inside a quantified
    group, so curly-brace counted forms like ``(a{2,})+`` slipped through.
    ``(a{2,})+`` is a classic catastrophic-backtracking shape (the outer
    ``+`` interacts exponentially with the ``{2,}`` repeat). register()
    must now refuse it via the same structural ReDoS guard."""

    from trade_trace.security.patterns import (
        _REDOS_STRUCTURE_RE,
        SecretPatternError,
    )

    # The structural guard itself now matches the curly-brace form.
    assert _REDOS_STRUCTURE_RE.search(pattern) is not None, (
        f"guard regex should flag nested curly-brace quantifier {pattern!r}"
    )

    with pytest.raises(SecretPatternError) as exc:
        register("nested_curly", pattern)
    msg = str(exc.value).lower()
    assert "nested quantifier" in msg or "backtracking" in msg
    assert "trade-trace-14iy" in str(exc.value)


@pytest.mark.parametrize(
    "pattern",
    [
        r"(a+){3}",       # outer {n} count over a quantified group — the bead repro
        r"(a{2,}){2,}",   # outer {n,} over an inner-curly quantified group
        r"(a+){2,}",      # outer {n,} over a +-quantified group
        r"(a*){5}",       # outer {n} over a *-quantified group
        r"(a?){10,20}",   # outer {n,m} over a ?-quantified group
    ],
)
def test_register_rejects_outer_curly_brace_quantifier_per_redos_guard(pattern):
    """Per bead trade-trace-rpcj: the nested-quantifier guard previously
    only allowed the symbolic quantifiers (*, +, ?) as the OUTER quantifier
    on a group, so a group quantified by a curly count like ``(a+){3}`` or
    ``(a{2,}){2,}`` slipped through. These are catastrophic-backtracking
    shapes too (a bounded/unbounded outer repeat over a quantified group).
    register() must now refuse them via the same structural ReDoS guard."""

    from trade_trace.security.patterns import (
        _REDOS_STRUCTURE_RE,
        SecretPatternError,
    )

    # The structural guard itself now matches the outer curly-brace form.
    assert _REDOS_STRUCTURE_RE.search(pattern) is not None, (
        f"guard regex should flag outer curly-brace quantifier {pattern!r}"
    )

    with pytest.raises(SecretPatternError) as exc:
        register("outer_curly", pattern)
    msg = str(exc.value).lower()
    assert "nested quantifier" in msg or "backtracking" in msg
    assert "trade-trace-14iy" in str(exc.value)


@pytest.mark.parametrize(
    "pattern",
    [
        r"a{2,5}",                  # bounded repeat, no enclosing quantified group
        r"(abc){2,5}",             # quantified group, but no inner quantifier
        r"(abc){3}",               # outer {n} over a group with NO inner quantifier
        r"[A-Z0-9]{8,}",           # character-class count, not a nested group
        r"CUSTOMTOKEN-[A-Z0-9]{8}",  # realistic secret pattern
    ],
)
def test_register_allows_benign_curly_quantifier(home, pattern):
    """The curly-brace extension must stay surgical: ordinary bounded
    repeats and quantified groups *without* an inner quantifier remain
    accepted (no over-rejection of legitimate secret patterns). The
    ``(abc){3}`` case guards the outer-curly extension (bead
    trade-trace-rpcj): an outer curly count over a group is only rejected
    when the group *also* carries an inner quantifier."""

    from trade_trace.security.patterns import _REDOS_STRUCTURE_RE

    assert _REDOS_STRUCTURE_RE.search(pattern) is None, (
        f"guard regex should NOT flag benign pattern {pattern!r}"
    )
    register("benign_curly", pattern)  # must not raise


def test_register_accepts_normal_custom_regex_and_scan_text_matches():
    """The ReDoS guard is scoped: normal custom secret patterns remain
    supported and take effect in scan_text()."""

    register("custom_scan_token", r"CUSTOMSCAN-[A-Z0-9]{8}")

    matches = scan_text("prefix CUSTOMSCAN-ABCD1234 suffix")

    assert [m.pattern_kind for m in matches] == ["custom_scan_token"]
    assert matches[0].match == "CUSTOMSCAN-ABCD1234"


def test_scan_text_truncates_pathological_input_per_redos_guard(monkeypatch):
    """Per bead trade-trace-14iy / DEBT-041: scan_text caps input
    length at MAX_SCAN_INPUT_BYTES so a multi-megabyte blob can't
    dominate CPU. Secrets in the truncated tail go unscanned by
    design — the write-time blob caps in operability.md §8 are the
    user-facing bound; this is defense-in-depth."""

    from trade_trace.security import patterns

    monkeypatch.setattr(patterns, "MAX_SCAN_INPUT_BYTES", 16)
    register("tail_only_token", r"TAILSECRET")

    # Keep the test allocation tiny while exercising the same policy:
    # the match starts just past the monkeypatched truncation boundary.
    body = "x" * patterns.MAX_SCAN_INPUT_BYTES + "TAILSECRET"
    assert len(body) > patterns.MAX_SCAN_INPUT_BYTES

    matches = scan_text(body)
    # The custom token in the truncated tail is not seen.
    assert all(m.pattern_kind != "tail_only_token" for m in matches), (
        "scan_text should have truncated before the secret in the tail"
    )

    # And the same token in the head IS still detected, confirming
    # the cap doesn't disable the scanner entirely.
    body_head = "TAILSECRET" + "y" * patterns.MAX_SCAN_INPUT_BYTES
    head_matches = scan_text(body_head)
    assert any(m.pattern_kind == "tail_only_token" for m in head_matches)


# -- 4. false-positive guard (4 corpus tests) -------------------


BENIGN_CORPUS = [
    # 40-char hex digest that ISN'T an Ethereum address (no 0x prefix).
    ("hash_no_prefix",
     "sha1 hash: abcdef1234567890abcdef1234567890abcdef12"),
    # `sk-` followed by fewer than 20 chars (below api_key threshold).
    ("short_skdash",
     "instrument symbol " + _SK + "1234567"),
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


# -- Polymarket condition ID false positives (trade-trace-aqpf) ----------


def test_polymarket_condition_id_is_not_flagged_as_ethereum_address(home: Path):
    """Polymarket conditionId is `0x` + 64 hex (32 bytes), longer than an
    Ethereum address (`0x` + 40 hex / 20 bytes). The ethereum_address
    pattern must use a word boundary so it does not falsely match the
    longer condition-id prefix (trade-trace-aqpf)."""

    from trade_trace.security import scan_text

    condition_id = "0" + "x" + "5caf6459052e0fcc736c368f97b5ea98e6bf264507f2e94ac8d69fcc441b1bae"
    matches = scan_text(condition_id)
    assert not any(m.pattern_kind == "ethereum_address" for m in matches), (
        f"condition id falsely matched ethereum_address: {matches}"
    )


def test_real_ethereum_address_still_flagged():
    """The fix must not weaken detection of a real 40-hex Ethereum address
    embedded in free text."""

    from trade_trace.security import scan_text

    text = "send to " + "0" + "x" + "1234567890abcdef" * 2 + "12345678 by EOD"
    matches = scan_text(text)
    assert any(m.pattern_kind == "ethereum_address" for m in matches)


def test_instrument_metadata_with_polymarket_condition_id_succeeds(home: Path):
    """instrument.add with Polymarket conditionId in metadata_json must
    succeed; previously the ethereum_address false positive blocked it
    (trade-trace-aqpf)."""

    venue = _mcp(home, "venue.add", {
        "name": "Polymarket", "kind": "prediction_market",
        "idempotency_key": "aqpf-venue",
    }).model_dump(mode="json", exclude_none=True)
    env = _mcp(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Ukraine NATO accession before 2027",
        "external_id": "polymarket:ukraine-nato:2027",
        "metadata_json": {
            "polymarket_slug": "ukraine-agrees-not-to-join-nato-before-2027",
            "condition_id": "0" + "x" + "5caf6459052e0fcc736c368f97b5ea98e6bf264507f2e94ac8d69fcc441b1bae",
        },
        "idempotency_key": "aqpf-inst",
    }).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is True, env


# -- redact_for_log fails closed past MAX_SCAN_INPUT_BYTES (trade-trace-8n98) --


def test_redact_for_log_truncates_overlong_input_to_prevent_tail_leak(monkeypatch):
    """Per trade-trace-8n98: scan_text truncates over-cap input as a
    CPU-bound defense for write-time validation, but redact_for_log is a
    last-resort safety boundary for logs. The redacted output must NOT
    contain original bytes past the cap; otherwise a secret in the tail
    would leak verbatim into a 'redacted' log."""

    from trade_trace.security import patterns

    monkeypatch.setattr(patterns, "MAX_SCAN_INPUT_BYTES", 16)
    register("tail_only_token", r"TAILSECRET")

    body = "x" * patterns.MAX_SCAN_INPUT_BYTES + "TAILSECRET"
    redacted = redact_for_log(body)
    assert "TAILSECRET" not in redacted, (
        "redact_for_log must not return tail bytes that the scanner did "
        "not see; either redact or truncate the tail."
    )


def test_redact_for_log_preserves_scanned_prefix_redactions(monkeypatch):
    """The hardening must not weaken in-prefix redaction. A secret in
    the scanned prefix is still replaced with REDACTED-<kind>."""

    from trade_trace.security import patterns

    monkeypatch.setattr(patterns, "MAX_SCAN_INPUT_BYTES", 64)
    register("head_token_8n98", r"HEADSECRET")

    body = "HEADSECRET" + " " * 100
    redacted = redact_for_log(body)
    assert "REDACTED-head_token_8n98" in redacted
    assert "HEADSECRET" not in redacted


# -- bead trade-trace-jm14: extend write-time scan to all free-text fields --
#
# The systemic gap consolidated under jm14 (INV-6): several is_write tools
# persisted long-form free-text fields that never passed the write-time
# secret scanner. Each test below fires the tool with a credential-shaped
# value in the named field and asserts a VALIDATION_ERROR before any DB
# write. memory.retain.{body,title} and decision.record_adherence.reason were
# already scanned in code but had no coverage here; jm14 adds it.


def _seed_forecast(home: Path) -> str:
    """Return a forecast_id usable as the interpret_resolution target."""

    _venue, inst = _seed_instrument(home)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "thesis body",
    }).data["id"]
    return _mcp(home, "forecast.add", {
        "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    }).data["id"]


@pytest.mark.parametrize("pattern_kind,secret", list(SECRET_FIXTURES.items()))
def test_abstention_reason_rejects_secret(home, pattern_kind, secret):
    """abstention.record.reason is long-form free text → VALIDATION_ERROR."""

    _venue, inst = _seed_instrument(home)
    env = _mcp(home, "abstention.record", {
        "instrument_id": inst,
        "reason": f"passed because {secret} leaked into my notes",
        "as_of": "2027-01-05T00:00:00Z",
    })
    assert env.ok is False, f"expected rejection on {pattern_kind}"
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "reason"
    assert env.error.details["pattern_kind"] == pattern_kind


@pytest.mark.parametrize("pattern_kind,secret", list(SECRET_FIXTURES.items()))
def test_resolution_interpretation_yes_condition_rejects_secret(
    home, pattern_kind, secret,
):
    """forecast.interpret_resolution.interpreted_yes_condition is long-form
    free text → VALIDATION_ERROR."""

    forecast_id = _seed_forecast(home)
    env = _mcp(home, "forecast.interpret_resolution", {
        "forecast_id": forecast_id,
        "interpreted_yes_condition": f"YES when {secret} appears",
        "as_of": "2027-01-02T00:00:00Z",
    })
    assert env.ok is False, f"expected rejection on {pattern_kind}"
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "interpreted_yes_condition"
    assert env.error.details["pattern_kind"] == pattern_kind


def test_pretrade_intent_semantic_key_rejects_secret(home):
    """pretrade_intent.record.semantic_key is required free text and is
    hashed into the material packet → must be scanned (jm14)."""

    _venue, inst = _seed_instrument(home)
    secret = SECRET_FIXTURES["api_key"]
    env = _mcp(home, "pretrade_intent.record", {
        "instrument_id": inst,
        "semantic_key": f"pm:{secret}:yes",
        "proposed_shape": {"side": "yes", "limit_price": "0.42"},
        "as_of": "2027-01-02T00:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-pti000000jm14",
    })
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "semantic_key"
    assert env.error.details["pattern_kind"] == "api_key"


@pytest.mark.parametrize("field", ["title", "question", "resolution_rule_text"])
def test_market_bind_free_text_rejects_secret(home, field):
    """market.bind persists title/question/resolution_rule_text verbatim;
    each is scanned before the row is written (jm14)."""

    _venue, inst = _seed_instrument(home)
    secret = SECRET_FIXTURES["slack_token"]
    args = {
        "id": inst,
        "source": "polymarket",
        "external_id": f"ext-{field}",
        "state": "open",
        "mechanism": "clob",
        "bound_via": "manual",
        "title": "Clean title",
        "question": "Clean question?",
        field: f"contains {secret} pasted in",
    }
    env = _mcp(home, "market.bind", args)
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == field
    assert env.error.details["pattern_kind"] == "slack_token"


def test_market_bind_nested_resolution_rule_text_rejects_secret(home):
    """The nested resolution_rule.text form is scanned the same as the flat
    resolution_rule_text field (jm14)."""

    _venue, inst = _seed_instrument(home)
    secret = SECRET_FIXTURES["jwt"]
    env = _mcp(home, "market.bind", {
        "id": inst,
        "source": "polymarket",
        "external_id": "ext-nested-rule",
        "state": "open",
        "mechanism": "clob",
        "bound_via": "manual",
        "resolution_rule": {"text": f"Settles when {secret} arrives"},
    })
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "resolution_rule_text"
    assert env.error.details["pattern_kind"] == "jwt"


def test_market_bind_clean_flat_text_with_secret_nested_object_rejected(home):
    """BYPASS (1) — clean flat resolution_rule_text + nested
    resolution_rule={text:'<SECRET>'}.

    The extracted-text projection prefers the clean flat value, so a
    projection-only scan never sees the secret-bearing nested object. But the
    whole `resolution_rule` object is persisted verbatim into metadata_json
    (events + markets tables). The serialized-payload scan rejects it
    (trade-trace-cmpy / jm14 / INV-6). Before the fix this returned a
    SuccessEnvelope and leaked the jwt into both tables."""

    secret = SECRET_FIXTURES["jwt"]
    env = _mcp(home, "market.bind", {
        "source": "polymarket",
        "external_id": "ext-cmpy-bypass-1",
        "state": "open",
        "mechanism": "clob",
        "bound_via": "manual",
        "resolution_rule_text": "Resolve per public market rules.",
        "resolution_rule": {"text": f"Settles when {secret} arrives"},
    })
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "resolution_rule"
    assert env.error.details["pattern_kind"] == "jwt"


def test_market_bind_resolution_rule_sibling_key_secret_rejected(home):
    """BYPASS (2) — resolution_rule={text:'clean', notes:'<SECRET>'}.

    Only `.text` is projected for the extracted-text scan; sibling keys
    (notes/source/anything) are persisted unscanned in the verbatim object.
    The serialized-payload scan over the merged metadata block rejects the
    secret in `notes` (trade-trace-cmpy / jm14 / INV-6). Before the fix this
    returned a SuccessEnvelope and leaked the api_key into both tables."""

    secret = SECRET_FIXTURES["api_key"]
    env = _mcp(home, "market.bind", {
        "source": "polymarket",
        "external_id": "ext-cmpy-bypass-2",
        "state": "open",
        "mechanism": "clob",
        "bound_via": "manual",
        "resolution_rule": {"text": "clean", "notes": f"embedded {secret} here"},
    })
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "resolution_rule"
    assert env.error.details["pattern_kind"] == "api_key"


def test_market_bind_clean_polymarket_metadata_writes_normally(home):
    """A polymarket bind whose merged metadata block carries no secret-shaped
    substring still writes (guards against the serialized-payload scan
    over-rejecting clean rows — trade-trace-cmpy)."""

    env = _mcp(home, "market.bind", {
        "source": "polymarket",
        "external_id": "ext-cmpy-clean",
        "state": "open",
        "mechanism": "clob",
        "bound_via": "manual",
        "resolution_rule": {
            "text": "Resolve per public market rules.",
            "source": "market_contract",
            "provenance": "caller_supplied",
        },
    })
    assert env.ok is True, env


def test_memory_link_metadata_json_rejects_secret(home):
    """memory.link.metadata_json now routes through store_metadata_json, so
    a nested secret value is rejected (jm14)."""

    a = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "node a body", "title": "A",
    }).data["id"]
    b = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "node b body", "title": "B",
    }).data["id"]
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "memory_node", "target_id": b,
        "edge_type": "about",
        "metadata_json": {"notes": {"token": SECRET_FIXTURES["api_key"]}},
    })
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "metadata_json"
    assert env.error.details["pattern_kind"] == "api_key"


def test_memory_link_metadata_json_rejects_credential_key(home):
    """memory.link.metadata_json also gets the credential-key rejection layer
    via store_metadata_json (jm14)."""

    a = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "node a body", "title": "A",
    }).data["id"]
    b = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "node b body", "title": "B",
    }).data["id"]
    env = _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "memory_node", "target_id": b,
        "edge_type": "about",
        "metadata_json": {"broker": {"private_key": "nope"}},
    })
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "metadata_json"
    assert env.error.details["credential_key"] == "private_key"


@pytest.mark.parametrize("field", ["body", "title"])
def test_memory_retain_free_text_rejects_secret(home, field):
    """memory.retain.{body,title} scanning (already wired in code) now has
    explicit coverage (jm14)."""

    args = {"node_type": "observation", "body": "clean body", "title": "Clean"}
    args[field] = f"holds {SECRET_FIXTURES['slack_token']} secret"
    env = _mcp(home, "memory.retain", args)
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == field
    assert env.error.details["pattern_kind"] == "slack_token"


@pytest.mark.parametrize("field", ["thought", "title"])
def test_idea_capture_free_text_rejects_secret(home, field):
    """idea.capture.{thought,title} are scanned before persistence (jm14)."""

    args = {"thought": "clean thought"}
    args[field] = f"idea leaked {SECRET_FIXTURES['api_key']}"
    env = _mcp(home, "idea.capture", args)
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == field
    assert env.error.details["pattern_kind"] == "api_key"


def test_decision_record_adherence_reason_rejects_secret(home):
    """decision.record_adherence.reason scanning (already wired in code) now
    has explicit coverage (jm14). The scan runs before any ref/status
    validation, so dummy refs suffice to exercise it."""

    env = _mcp(home, "decision.record_adherence", {
        "decision_id": "dec_missing",
        "playbook_version_id": "pbv_missing",
        "rule_node_id": "node_missing",
        "status": "overridden",
        "reason": f"overrode because {SECRET_FIXTURES['jwt']} said so",
    })
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "reason"
    assert env.error.details["pattern_kind"] == "jwt"


# -- replay.case_bundle security-gate budget keys are not caller-overridable --
#
# A caller must not be able to flip include_sensitive_sources (or the body
# inclusion flags) on via the budgets dict; _validate_request strips those
# keys so the fixed DEFAULT_BUDGETS redaction posture always wins (jm14,
# parity with security.md §8 / review.bundle).


@pytest.mark.parametrize(
    "gate_key",
    ["include_sensitive_sources", "include_source_bodies", "include_memory_bodies"],
)
def test_replay_validate_request_strips_security_gate_budget_overrides(gate_key):
    from trade_trace.reports.replay import DEFAULT_BUDGETS, _validate_request

    _as_of, _selection, _task, budgets = _validate_request(
        {"as_of": "2027-01-01T00:00:00Z", "budgets": {gate_key: True}}
    )
    assert budgets[gate_key] is DEFAULT_BUDGETS[gate_key] is False, (
        f"caller override of {gate_key} must be stripped, not honored"
    )


def test_replay_validate_request_still_honors_non_security_budgets():
    """The strip must be surgical: ordinary budget knobs still pass through."""

    from trade_trace.reports.replay import _validate_request

    _as_of, _selection, _task, budgets = _validate_request(
        {"as_of": "2027-01-01T00:00:00Z", "budgets": {"max_chars_total": 999}}
    )
    assert budgets["max_chars_total"] == 999


# -- static enforcement: §6.5 scan-table completeness (jm14) --------
#
# Parse the markdown scan table in docs/architecture/security.md §6.5 and
# assert every listed (tool, field) pair is actually scanned by
# reject_if_contains_secrets (or routed through store_metadata_json for the
# metadata_json catch-all) somewhere in src/. A refactor that drops a scan
# call, or a table row added without wiring the field, breaks this test.

_SRC_ROOT = Path(trade_trace.__file__).resolve().parent
_SECURITY_MD = _SRC_ROOT.parent.parent / "docs" / "architecture" / "security.md"

# Tools whose free-text field lives in a specific handler module. The static
# check confirms the field is wired to a scan call in that module's source.
_TOOL_SOURCE: dict[str, str] = {
    "account_snapshot.import": "tools/account_snapshots.py",
    "approval.record": "tools/approval.py",
    "thesis.add": "tools/ledger/thesis.py",
    "decision.add": "tools/ledger/decision.py",
    "decision.record_adherence": "tools/playbook.py",
    "external_receipt.import": "tools/external_receipts.py",
    "instrument.add": "tools/ledger/instrument.py",
    "forecast.add": "tools/ledger/forecast.py",
    "source.add": "tools/ledger/source.py",
    "strategy.create": "tools/strategy.py",
    "strategy.upsert": "tools/strategy.py",
    "strategy.update": "tools/strategy.py",
    "playbook.create": "tools/playbook.py",
    "playbook.upsert": "tools/playbook.py",
    "playbook.propose_version": "tools/playbook.py",
    "playbook.record_adherence": "tools/playbook.py",
    "memory.retain": "tools/memory.py",
    "memory.reflect": "tools/memory.py",
    "abstention.record": "tools/abstention.py",
    "forecast.interpret_resolution": "tools/resolution_interpretation.py",
    "pretrade_intent.record": "tools/pretrade_intent.py",
    "idea.capture": "tools/ideas.py",
    "market.bind": "tools/market_bind.py",
    "risk.check_record": "tools/risk.py",
}

_SCAN_HELPER_NAMES = {
    "reject_if_contains_secrets",
    "_guard_text",
    "_safe_text",
    "_text_arg",
}


def _scanned_fields_in_source(path: Path) -> set[str]:
    """Return the set of field names passed to reject_if_contains_secrets in
    a source module, resolving both literal `field=` kwargs and the
    `for field in (...): reject_if_contains_secrets(..., field=field)` loop
    form used by thesis.add."""

    tree = ast.parse(path.read_text())
    fields: set[str] = set()

    def _call_field_literal(call: ast.Call) -> str | None:
        for kw in call.keywords:
            if kw.arg == "field" and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                return kw.value.value
        if isinstance(call.func, ast.Name) and call.func.id in {"_safe_text", "_text_arg"} \
                and len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) \
                and isinstance(call.args[1].value, str):
            return call.args[1].value
        return None

    def _is_scan_call(call: ast.Call) -> bool:
        return isinstance(call.func, ast.Name) and call.func.id in _SCAN_HELPER_NAMES

    def _literal_strings(node: ast.AST) -> set[str]:
        if not isinstance(node, (ast.Tuple, ast.List)):
            return set()
        return {
            elt.value for elt in node.elts
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        }

    def _scan_comprehension_fields(node: ast.AST) -> set[str]:
        fields: set[str] = set()
        if not isinstance(node, (ast.DictComp, ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return fields
        if isinstance(node, ast.DictComp):
            scan_calls = [
                c for c in ast.walk(node.key)
                if isinstance(c, ast.Call) and _is_scan_call(c)
            ]
            scan_calls.extend(
                c for c in ast.walk(node.value)
                if isinstance(c, ast.Call) and _is_scan_call(c)
            )
        else:
            scan_calls = [
                c for c in ast.walk(node.elt)
                if isinstance(c, ast.Call) and _is_scan_call(c)
            ]
        for gen in node.generators:
            if not isinstance(gen.target, ast.Name):
                continue
            target = gen.target.id
            iter_fields = _literal_strings(gen.iter)
            if not iter_fields:
                continue
            for call in scan_calls:
                uses_target = any(
                    isinstance(arg, ast.Name) and arg.id == target
                    for arg in call.args
                ) or any(
                    kw.arg == "field" and isinstance(kw.value, ast.Name) and kw.value.id == target
                    for kw in call.keywords
                )
                if uses_target:
                    fields.update(iter_fields)
        return fields

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_scan_call(node):
            literal = _call_field_literal(node)
            if literal is not None:
                fields.add(literal)
        # Loop form: `for field in (<literals>): reject_if_contains_secrets(...)`
        if isinstance(node, ast.For):
            has_scan = any(
                isinstance(c, ast.Call) and _is_scan_call(c)
                for c in ast.walk(node)
            )
            if has_scan:
                fields.update(_literal_strings(node.iter))
        fields.update(_scan_comprehension_fields(node))
    return fields


def _parse_scan_table() -> list[tuple[str, str]]:
    """Yield (tool, field) pairs from the §6.5 scan table, skipping the
    metadata_json catch-all row and exempt-by-design content."""

    text = _SECURITY_MD.read_text()
    section = text.split("### 6.5", 1)[1].split("Exempt by design", 1)[0]
    pairs: list[tuple[str, str]] = []
    for line in section.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 2:
            continue
        tool_cell, field_cell = cells
        if tool_cell.startswith("Tool") or set(tool_cell) <= set("-: "):
            continue
        if "Every write tool" in tool_cell:
            continue
        # A cell may list several tools (split on "/") and several fields.
        tools = [re.sub(r"`", "", t).strip() for t in tool_cell.split("/")]
        for raw_field in field_cell.split(","):
            # Strip backticks and any parenthetical note (e.g. "(flat or ...)").
            field = re.sub(r"`", "", raw_field)
            field = re.sub(r"\(.*?\)", "", field).strip()
            if not field:
                continue
            for tool in tools:
                pairs.append((tool, field))
    return pairs


def test_scan_table_completeness():
    """Every (tool, field) row in security.md §6.5 is backed by a real
    reject_if_contains_secrets call in the tool's handler source (jm14)."""

    pairs = _parse_scan_table()
    assert pairs, "failed to parse any rows from the §6.5 scan table"

    cache: dict[str, set[str]] = {}
    missing: list[str] = []
    for tool, field in pairs:
        rel = _TOOL_SOURCE.get(tool)
        assert rel is not None, (
            f"§6.5 lists tool {tool!r} but the test has no source mapping; "
            "add it to _TOOL_SOURCE."
        )
        if rel not in cache:
            cache[rel] = _scanned_fields_in_source(_SRC_ROOT / rel)
        if field not in cache[rel]:
            missing.append(f"{tool}.{field} (expected scan in src/trade_trace/{rel})")

    assert not missing, (
        "scan-table fields without a backing reject_if_contains_secrets call:\n  "
        + "\n  ".join(missing)
    )


def test_scan_table_lists_jm14_fields():
    """Guard the jm14 additions explicitly so a future table edit cannot
    silently drop them."""

    pairs = set(_parse_scan_table())
    for expected in [
        ("abstention.record", "reason"),
        ("forecast.interpret_resolution", "interpreted_yes_condition"),
        ("pretrade_intent.record", "semantic_key"),
        ("idea.capture", "thought"),
        ("idea.capture", "title"),
        ("market.bind", "title"),
        ("market.bind", "question"),
        ("market.bind", "resolution_rule_text"),
    ]:
        assert expected in pairs, f"§6.5 table no longer lists {expected}"


_FREE_TEXT_NAME_TOKENS = (
    "body", "reason", "description", "hypothesis", "note", "excerpt",
    "text", "summary", "title", "question", "thought", "criteria",
    "triggers", "condition",
)

_EXEMPT_FIELD_NAMES = {
    "asset_class", "actor_id", "actor_id_recorded", "agent_id", "ambiguity_kind",
    "approval_ref_id", "approval_state", "artifact_hash", "at", "bound_via",
    "close_at", "closed_for_trading_at", "confidence_label", "condition_id",
    "content_hash", "currency_or_collateral", "current_time", "decision",
    "decision_actor_id", "depth_provenance", "diff_severity", "environment",
    "environment_label", "event_slug", "evidence_mode", "evidence_state",
    "external_event_ref", "external_event_type", "external_fill_ref",
    "external_id", "external_order_ref", "fill_status", "from",
    "gamma_event_id", "gamma_market_id", "hash_algorithm", "home", "id",
    "idempotency_key", "incident_type", "kind", "lifecycle_state", "mark_as_of",
    "mark_source", "market_slug", "material_hash", "media_type", "mechanism",
    "mode", "model_id", "node_type", "opened_at", "outcome_label",
    "outcome_side", "policy_hash", "policy_key", "policy_version",
    "policy_version_id", "provider_id", "publish_status", "record_type",
    "redacted_artifact_ref", "redaction_profile", "redaction_status", "ref",
    "request_id", "resolution_source", "resolution_source_url", "resolution_status",
    "resolved_at", "resolving_at", "retrieved_at", "review_by", "run_id",
    "run_status", "schema_version", "scoring_state", "scoring_support", "session_id",
    "severity", "side", "slug", "source", "source_author", "source_run_id",
    "source_system", "stance", "state", "status", "storage_kind", "strategy_version",
    "symbol", "time_horizon_at", "to", "type", "uri", "url", "valid_from",
    "valid_to", "version", "voided_at", "waiver_class", "waived_by", "yes_label",
}


def _schema_types(schema: object) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    raw = schema.get("type")
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {value for value in raw if isinstance(value, str)}
    return set()


def _looks_like_free_text(field: str, schema: object) -> bool:
    if field.startswith("_") or field in _EXEMPT_FIELD_NAMES:
        return False
    if field.endswith("_id") or field.endswith("_ids") or field.endswith("_at"):
        return False
    if field.endswith("_ref") or field.endswith("_refs") or field.endswith("_hash"):
        return False
    if "string" not in _schema_types(schema):
        return False
    description = ""
    if isinstance(schema, dict):
        description = str(schema.get("description") or "").lower()
    return "free-text" in description or "free text" in description \
        or any(token in field for token in _FREE_TEXT_NAME_TOKENS)


def test_write_tool_free_text_schema_fields_are_registered_in_security_policy():
    """Every registered write-tool free-text schema field is listed in §6.5.

    `test_scan_table_completeness` checks the table has backing code. This
    inverse check catches a new schema field that would otherwise be exposed
    without a scan-table row or an explicit exemption.
    """

    pairs = set(_parse_scan_table())
    missing: list[str] = []
    for tool, entry in sorted(build_registry().by_name.items()):
        if not entry.is_write or not isinstance(entry.json_schema, dict):
            continue
        properties = entry.json_schema.get("properties")
        if not isinstance(properties, dict):
            continue
        for field, schema in sorted(properties.items()):
            if _looks_like_free_text(field, schema) and (tool, field) not in pairs:
                missing.append(f"{tool}.{field}")

    assert not missing, (
        "write-tool free-text schema fields missing from security.md §6.5 "
        "scan policy or exemption text:\n  " + "\n  ".join(missing)
    )
