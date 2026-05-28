"""Auto-derived idempotency keys for retryable writes per bead
trade-trace-t7hi.

The dispatcher now accepts `idempotency_key` as optional on every
write tool whose semantic identity is well-defined by the existing
`SEMANTIC_KEYS` registry. When omitted, the server computes a
deterministic `auto:` key from
`sha256(tool_name + canonical_json(structural_fields))` and surfaces
the origin on `meta.idempotency_source`. Tools intentionally outside
the auto-derivation registry (administrative capabilities, per-row
batch importers, attachment helpers that emit two distinct events)
keep the strict cpz2 rejection path.

These tests are intentionally allowed to use normal project-wide pytest
configuration: conftest must not inject test-only keys that mask production
auto-derivation.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from trade_trace import core as _core_module
from trade_trace.events.semantic_keys import (
    SEMANTIC_KEYS,
    TOOL_PRIMARY_EVENT_TYPE,
    derive_idempotency_key,
)
from trade_trace.storage.paths import db_path


def _init_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    init = _core_module.dispatch(
        "journal.init", {"home": str(home)}, actor_id="agent:default",
    )
    assert init.ok is True
    return home


@pytest.mark.strict_idempotency
def test_auto_derived_key_matches_manual_canonical_hash(tmp_path):
    """Recompute the auto-derived key by hand and assert dispatcher
    selects the same value."""

    home = _init_home(tmp_path)
    payload = {"home": str(home), "name": "PolymarketAuto", "kind": "prediction_market"}

    expected = derive_idempotency_key("venue.add", payload)
    assert expected is not None
    assert expected.startswith("auto:")
    assert len(expected) == len("auto:") + 32

    env = _core_module.dispatch(
        "venue.add", dict(payload), actor_id="agent:default",
    )
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["meta"]["idempotency_source"] == "auto"

    # The canonical hash must depend only on the structural fields of
    # venue.created (`name`, `kind`); changing `home` (server-side
    # path) must NOT shift the key.
    altered = dict(payload)
    altered["home"] = str(home) + "-x"
    assert derive_idempotency_key("venue.add", altered) == expected


def test_default_pytest_dispatch_uses_production_auto_key_not_test_auto(tmp_path):
    """Ordinary tests must see production `auto:` keys, not the former
    global `test-auto:` injector."""

    home = _init_home(tmp_path)
    payload = {"home": str(home), "name": "DefaultAuto", "kind": "manual"}
    expected = derive_idempotency_key("venue.add", payload)
    assert expected is not None and expected.startswith("auto:")

    body = _core_module.dispatch(
        "venue.add", dict(payload), actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["meta"]["idempotency_source"] == "auto"

    with sqlite3.connect(db_path(home)) as conn:
        stored_key = conn.execute(
            "SELECT idempotency_key FROM events WHERE event_type = ?",
            ("venue.created",),
        ).fetchone()[0]
    assert stored_key == expected
    assert stored_key.startswith("auto:")
    assert not stored_key.startswith("test-auto:")


@pytest.mark.strict_idempotency
def test_explicit_key_overrides_auto_derivation(tmp_path):
    """When the caller passes `idempotency_key`, the server records
    the caller-supplied value and reports `meta.idempotency_source ==
    'caller'`, regardless of what the canonical hash would have been."""

    home = _init_home(tmp_path)
    payload = {
        "home": str(home),
        "name": "ExplicitOverride",
        "kind": "manual",
        "idempotency_key": "caller-chosen-key-9999",
    }
    env = _core_module.dispatch(
        "venue.add", payload, actor_id="agent:default",
    )
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["meta"]["idempotency_source"] == "caller"


@pytest.mark.strict_idempotency
def test_replay_of_identical_input_returns_idempotent_replay_with_auto_key(tmp_path):
    """A second dispatch with the same structural fields and an omitted
    key derives the same auto key and short-circuits via the existing
    idempotency-replay path. No double-write."""

    home = _init_home(tmp_path)
    payload = {"home": str(home), "name": "ReplayMe", "kind": "manual"}

    first = _core_module.dispatch(
        "venue.add", dict(payload), actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert first["ok"] is True
    first_id = first["data"]["id"]

    second = _core_module.dispatch(
        "venue.add", dict(payload), actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert second["ok"] is True
    # Same row id — proves the journal saw a replay, not a fresh insert.
    assert second["data"]["id"] == first_id
    assert second["meta"]["idempotency_source"] == "auto"
    # The dispatcher surfaces idempotent_replay=true through the same
    # meta_hint the explicit-key replay path uses.
    assert second["meta"].get("idempotent_replay") is True


@pytest.mark.strict_idempotency
def test_auto_derivation_collision_overridable_with_explicit_key(tmp_path):
    """Two semantically distinct calls that happen to share structural
    fields would collide under auto-derivation; the caller can break
    the tie by passing an explicit `idempotency_key`. The collision
    itself surfaces through the existing IDEMPOTENCY_CONFLICT path
    when the structural fields actually match the prior write."""

    home = _init_home(tmp_path)

    first = _core_module.dispatch(
        "venue.add",
        {"home": str(home), "name": "CollideMe", "kind": "manual"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert first["ok"] is True

    # Explicit key under the same structural payload bypasses the
    # auto-derived hash and gets a fresh row — caller has full
    # control over the dedup space.
    explicit = _core_module.dispatch(
        "venue.add",
        {
            "home": str(home), "name": "CollideMe", "kind": "manual",
            "idempotency_key": "caller-disambiguator-1",
        },
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert explicit["ok"] is True
    assert explicit["data"]["id"] != first["data"]["id"]
    assert explicit["meta"]["idempotency_source"] == "caller"


@pytest.mark.strict_idempotency
def test_administrative_tool_still_requires_explicit_key(tmp_path):
    """`journal.backup` is intentionally not in the auto-derivation
    registry — its semantic identity is the *destination path plus
    journal contents*, which the structural-fields canonicalizer
    cannot capture. The strict cpz2 rejection therefore still applies."""

    home = _init_home(tmp_path)
    env = _core_module.dispatch(
        "journal.backup",
        {"home": str(home), "dest": str(tmp_path / "backup"), "_confirm": True},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "idempotency_key"
    assert env["error"]["details"]["auto_derivation_available"] is False


@pytest.mark.strict_idempotency
def test_canonical_hash_format_is_stable(tmp_path):
    """Document the byte-level shape of the auto-derived key so a
    future refactor cannot silently change it. The hash is a 32-char
    sha256 prefix of `tool_name:canonical_payload_json`."""

    payload = {"name": "DocumentedShape", "kind": "manual"}
    canonical = json.dumps(
        {"name": "DocumentedShape", "kind": "manual"},
        sort_keys=True, separators=(",", ":"),
    )
    expected_digest = hashlib.sha256(
        f"venue.add:{canonical}".encode(),
    ).hexdigest()
    derived = derive_idempotency_key("venue.add", payload)
    assert derived == f"auto:{expected_digest[:32]}"


def test_every_tool_in_registry_resolves_to_a_known_event_type():
    """Schema audit: every entry in `TOOL_PRIMARY_EVENT_TYPE` must
    point at an event type the canonicalizer can resolve. Catches
    typos / drift between the two registries on every test run."""

    for tool, event_type in TOOL_PRIMARY_EVENT_TYPE.items():
        assert event_type in SEMANTIC_KEYS, (
            f"TOOL_PRIMARY_EVENT_TYPE[{tool!r}]={event_type!r} is not a "
            "registered semantic-key event type"
        )


def test_risk_check_auto_idempotency_includes_public_input_linkage_fields(tmp_path):
    base = {
        "policy_version_id": "rpv_1",
        "status": "pass",
        "outcome": "pass",
        "instrument_id": "ins_1",
        "as_of": "2026-05-28T12:00:00Z",
        "rule_results": [{
            "rule_id": "limit",
            "reason_code": "WITHIN_LIMIT",
            "severity": "info",
            "observed_value": {"usd": 10},
            "threshold": {"max_usd": 100},
            "contributing_record_ids": ["pos_1"],
            "waiver_required": False,
        }],
    }
    with_inputs = {
        **base,
        "exposure_input_ids_json": ["pos_1"],
        "evidence_input_ids_json": ["src_1"],
        "input_provenance_json": {"snapshot": "a"},
    }
    changed_inputs = {
        **base,
        "exposure_input_ids_json": ["pos_2"],
        "evidence_input_ids_json": ["src_2"],
        "input_provenance_json": {"snapshot": "b"},
    }
    assert derive_idempotency_key("risk.check_record", with_inputs) != derive_idempotency_key("risk.check_record", changed_inputs)
