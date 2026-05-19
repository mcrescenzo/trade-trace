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
KNOWN_SECRET = "sk-tradetracez6sKnownSecret000001"


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


def test_embeddings_api_keyring_rejects_insecure_plaintext_backend(monkeypatch):
    secret = "sk-insecurebackendsecret0001"

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
    secret = "sk-backendfailuresecret0001"

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
    assert ("embeddings.provider", "api:openai") in config_rows
    assert all(KNOWN_SECRET not in json.dumps(row) for row in config_rows)


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
    serialized = json.dumps(recall.model_dump(mode="json", exclude_none=True), sort_keys=True)
    assert KNOWN_SECRET not in serialized
    assert "api_key" not in serialized
