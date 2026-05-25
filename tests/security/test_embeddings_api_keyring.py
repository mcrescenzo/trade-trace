from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from trade_trace.mcp_server import mcp_call

KNOWN_SECRET = "s" + "k" + "-" + "tradetracez6sKnownSecret000001"


class ExplodingKeyring(types.SimpleNamespace):
    def get_keyring(self):
        raise AssertionError("remote embeddings are unsupported; keyring must not be inspected")

    def set_password(self, service: str, username: str, value: str) -> None:
        raise AssertionError("remote embeddings are unsupported; keyring must not store secrets")

    def get_password(self, service: str, username: str):
        raise AssertionError("remote embeddings are unsupported; keyring must not read secrets")

    def delete_password(self, service: str, username: str) -> None:
        raise AssertionError("remote embeddings are unsupported; keyring must not delete secrets")


def _init_home(home: Path) -> None:
    env = mcp_call("journal.init", {"home": str(home)})
    assert env.ok, env


def test_api_embeddings_provider_is_rejected_without_keyring(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "keyring", ExplodingKeyring())
    home = tmp_path / "home"
    _init_home(home)

    env = mcp_call(
        "journal.config_set",
        {
            "home": str(home),
            "key": "embeddings.provider",
            "value": "api:openai",
            "api_key": KNOWN_SECRET,
            "_confirm": True,
            "idempotency_key": "00000000-0000-4000-8000-api-rejected01",
        },
    )

    assert not env.ok
    assert env.error is not None
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["allowed"] == ["local", "none"]
    serialized = json.dumps(env.model_dump(mode="json"), sort_keys=True)
    assert KNOWN_SECRET not in serialized


def test_keyring_revoke_is_legacy_noop_and_secret_free(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "keyring", ExplodingKeyring())
    home = tmp_path / "home"
    _init_home(home)

    preview = mcp_call("keyring.revoke", {"home": str(home)})
    assert preview.ok, preview
    assert preview.data == {
        "preview_only": True,
        "would_revoke": {"provider": "none", "credential_storage": "unsupported"},
    }
    assert preview.meta.preview_only is True

    confirmed = mcp_call(
        "keyring.revoke",
        {
            "home": str(home),
            "_confirm": True,
            "idempotency_key": "00000000-0000-4000-8000-keyring-noop1",
        },
    )
    assert confirmed.ok, confirmed
    assert confirmed.data == {
        "preview_only": False,
        "provider": "none",
        "credential_storage": "unsupported",
        "revoked": False,
    }
    assert "api_key" not in json.dumps(confirmed.model_dump(mode="json"), sort_keys=True)


def test_keyring_revoke_tool_schema_stays_narrow_and_secret_free():
    env = mcp_call("tool.schema", {"tool": "keyring.revoke"})
    assert env.ok, env
    schema = env.data["json_schema"]
    assert schema is not None
    assert "api_key" not in json.dumps(env.model_dump(mode="json"), sort_keys=True)
    assert set(schema.get("properties", {})) >= {"_confirm", "idempotency_key"}
    assert "service" not in schema.get("properties", {})
