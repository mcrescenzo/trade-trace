from __future__ import annotations

from pathlib import Path

from trade_trace.adapters.polymarket.client import PolymarketClient
from trade_trace.adapters.polymarket.config import PolymarketConfig
from trade_trace.adapters.polymarket.errors import AdapterError
from trade_trace.mcp_server import mcp_call


def test_enabled_adapter_missing_rpc_returns_config_required():
    client = PolymarketClient(PolymarketConfig(enabled=True, gamma_base_url="https://gamma.example.test"))
    try:
        client.check_resolution_available()
    except AdapterError as exc:
        assert exc.code.value == "CONFIG_REQUIRED"
        assert exc.details == {"config_key": "network.polymarket.polygon_rpc_url"}
    else:  # pragma: no cover
        raise AssertionError("expected missing RPC config error")


def test_status_enabled_without_rpc_reports_config_booleans_and_network_active(tmp_path: Path):
    home = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(home)}).ok
    assert mcp_call(
        "journal.config_set",
        {"home": str(home), "key": "network.polymarket.enabled", "value": "true", "_confirm": True, "idempotency_key": "test-legacy:pm-enabled"},
    ).ok
    assert mcp_call(
        "journal.config_set",
        {
            "home": str(home),
            "key": "network.polymarket.gamma_base_url",
            "value": "https://gamma.example.test?secret=not-returned",
            "_confirm": True,
            "idempotency_key": "test-legacy:pm-gamma-url",
        },
    ).ok
    env = mcp_call("journal.status", {"home": str(home)})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    data = body["data"]
    assert data["outbound_network_active"] is True
    assert data["adapter_state"]["polymarket"]["enabled"] is True
    assert data["adapter_state"]["polymarket"]["configured_endpoints"] == {
        "gamma_base_url": True,
        "polygon_rpc_url": False,
    }
    assert "gamma.example" not in repr(data["adapter_state"])
