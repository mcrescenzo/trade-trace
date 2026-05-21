from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path

from trade_trace.mcp_server import mcp_call
from trade_trace.security import keyring as tt_keyring
from trade_trace.tools.memory import _float32_blob

SERVICE = "trade-trace:embeddings:openai"
KNOWN_SECRET = "s" + "k" + "-" + "tradetracez6sKnownSecret000001"


class FakeKeyring(types.SimpleNamespace):
    trade_trace_test_secure_backend = True

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_keyring(self):
        return self

    def set_password(self, service: str, username: str, value: str) -> None:
        self.store[(service, username)] = value

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.store.pop((service, username), None)


def _install_fake_keyring(monkeypatch) -> FakeKeyring:
    fake = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "sqlite_vec", types.SimpleNamespace(load=lambda conn: None))
    return fake


def _init_home(home: Path) -> None:
    env = mcp_call("journal.init", {"home": str(home)})
    assert env.ok, env


def _home_contains(home: Path, needle: str) -> list[Path]:
    hits: list[Path] = []
    encoded = needle.encode("utf-8")
    for path in home.rglob("*"):
        if path.is_file() and encoded in path.read_bytes():
            hits.append(path)
    return hits


def test_embeddings_api_keyring_round_trip_store_load_delete(monkeypatch):
    _install_fake_keyring(monkeypatch)

    tt_keyring.store_api_key(SERVICE, KNOWN_SECRET)
    assert tt_keyring.load_api_key(SERVICE) == KNOWN_SECRET

    tt_keyring.delete_api_key(SERVICE)
    assert tt_keyring.load_api_key(SERVICE) is None

    # Absent deletes are idempotent for callers.
    tt_keyring.delete_api_key(SERVICE)
    assert tt_keyring.load_api_key(SERVICE) is None


def test_keyring_revoke_tool_previews_and_deletes_stored_embeddings_key(monkeypatch, tmp_path):
    fake = _install_fake_keyring(monkeypatch)
    home = tmp_path / "home"
    _init_home(home)
    fake.set_password(SERVICE, "api_key", KNOWN_SECRET)

    preview = mcp_call("keyring.revoke", {"home": str(home)})
    assert preview.ok, preview
    assert preview.data == {
        "preview_only": True,
        "would_revoke": {"provider": "api:openai", "credential_storage": "os_keyring"},
    }
    assert preview.meta.preview_only is True
    assert fake.get_password(SERVICE, "api_key") == KNOWN_SECRET

    revoked = mcp_call("keyring.revoke", {"home": str(home), "_confirm": True})
    assert revoked.ok, revoked
    assert revoked.data == {
        "preview_only": False,
        "provider": "api:openai",
        "credential_storage": "os_keyring",
        "revoked": True,
    }
    assert fake.get_password(SERVICE, "api_key") is None


def test_keyring_revoke_tool_confirm_is_idempotent_when_absent(monkeypatch, tmp_path):
    fake = _install_fake_keyring(monkeypatch)
    home = tmp_path / "home"
    _init_home(home)

    env = mcp_call("keyring.revoke", {"home": str(home), "_confirm": True})
    assert env.ok, env
    assert env.data["revoked"] is True
    assert fake.get_password(SERVICE, "api_key") is None


def test_keyring_revoke_tool_schema_is_narrow_and_secret_free():
    env = mcp_call("tool.schema", {"tool": "keyring.revoke"})
    assert env.ok, env
    schema = env.data["json_schema"]
    assert schema is not None
    assert "api_key" not in json.dumps(env.model_dump(mode="json"), sort_keys=True)
    assert set(schema.get("properties", {})) >= {"_confirm", "idempotency_key"}
    assert "service" not in schema.get("properties", {})


def test_embeddings_api_keyring_rejects_insecure_plaintext_backend(monkeypatch):
    secret = "s" + "k" + "-" + "insecurebackendsecret0001"

    class PlaintextKeyring:
        __module__ = "keyrings.alt.file"
        priority = 1

        def set_password(self, service: str, username: str, value: str) -> None:
            raise AssertionError("insecure backend must not receive secret")

    backend = PlaintextKeyring()
    fake = types.SimpleNamespace(
        get_keyring=lambda: backend,
        set_password=backend.set_password,
        get_password=lambda service, username: None,
        delete_password=lambda service, username: None,
    )
    monkeypatch.setitem(sys.modules, "keyring", fake)

    try:
        tt_keyring.store_api_key(SERVICE, secret)
    except Exception as exc:
        serialized = str(exc) + json.dumps(getattr(exc, "details", {}), default=str)
        assert secret not in serialized
    else:  # pragma: no cover - assertion guard
        raise AssertionError("insecure keyring backend was accepted")


def test_embeddings_api_keyring_rejects_null_fail_backend(monkeypatch):
    class NullKeyring:
        __module__ = "keyring.backends.null"
        priority = -1

    backend = NullKeyring()
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        types.SimpleNamespace(
            get_keyring=lambda: backend,
            get_password=lambda service, username: None,
            set_password=lambda service, username, value: None,
            delete_password=lambda service, username: None,
        ),
    )

    try:
        tt_keyring.load_api_key(SERVICE)
    except Exception as exc:
        assert KNOWN_SECRET not in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("null/fail keyring backend was accepted")


def test_embeddings_api_keyring_backend_failure_does_not_echo_secret(monkeypatch):
    secret = "s" + "k" + "-" + "backendfailuresecret0001"

    class FailingSecureKeyring(FakeKeyring):
        def set_password(self, service: str, username: str, value: str) -> None:
            raise RuntimeError(f"backend refused value length {len(value)}")

    fake = FailingSecureKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)

    try:
        tt_keyring.store_api_key(SERVICE, secret)
    except Exception as exc:
        serialized = str(exc) + json.dumps(getattr(exc, "details", {}), default=str)
        assert secret not in serialized
    else:  # pragma: no cover - assertion guard
        raise AssertionError("backend failure unexpectedly succeeded")


def test_embeddings_api_provider_switch_grep_audit_finds_zero_plaintext_secret(monkeypatch, tmp_path):
    fake = _install_fake_keyring(monkeypatch)
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
        },
        actor_id="agent:security-test",
    )
    assert env.ok, env
    assert env.data == {
        "preview_only": False,
        "key": "embeddings.provider",
        "value": "api:openai",
        "api_key_storage": "os_keyring",
    }
    assert fake.get_password(SERVICE, "api_key") == KNOWN_SECRET

    hits = _home_contains(home, KNOWN_SECRET)
    assert hits == []

    with sqlite3.connect(home / "trade-trace.sqlite") as conn:
        config_rows = conn.execute("SELECT key, value FROM config").fetchall()
        event_rows = conn.execute("SELECT * FROM events").fetchall()
        outbox_rows = conn.execute("SELECT * FROM outbox").fetchall()
    assert ("embeddings.provider", "api:openai") in config_rows
    persisted_audit = json.dumps(
        {"config": config_rows, "events": event_rows, "outbox": outbox_rows},
        default=str,
        sort_keys=True,
    )
    assert KNOWN_SECRET not in persisted_audit
    assert "api_key" not in persisted_audit


def test_memory_recall_api_key_resolved_at_call_time_and_not_returned(monkeypatch, tmp_path):
    fake = _install_fake_keyring(monkeypatch)
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
        },
    )
    assert env.ok, env

    retain = mcp_call(
        "memory.retain",
        {
            "home": str(home),
            "id": "mem-api-key-test",
            "node_type": "observation",
            "body": "rotation risk increases into illiquid closes",
            "source_refs": [],
        },
    )
    assert retain.ok, retain
    with sqlite3.connect(home / "trade-trace.sqlite") as conn:
        conn.execute(
            "INSERT INTO memory_node_embeddings(node_id, provider, model_id, dim, embedding, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "mem-api-key-test",
                "api:openai",
                "text-embedding-3-small",
                2,
                _float32_blob([1.0, 0.0]),
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()

    assert fake.get_password(SERVICE, "api_key") == KNOWN_SECRET
    recall = mcp_call(
        "memory.recall",
        {"home": str(home), "query": "illiquid close", "strategies": ["semantic"], "k": 1},
    )
    assert recall.ok, recall
    assert "semantic" in recall.data["strategies_used"]
    assert recall.data["items"][0]["id"] == "mem-api-key-test"
    assert "semantic" in recall.data["items"][0]["strategy_provenance"]
    serialized = json.dumps(recall.model_dump(mode="json", exclude_none=True), sort_keys=True)
    assert KNOWN_SECRET not in serialized
    assert "api_key" not in serialized
