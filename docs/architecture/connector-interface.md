# Connector Interface — Architecture Note

**Date:** 2026-05-18
**Status:** Refined draft
**Parent:** [`../../PRD.md`](../../PRD.md) §8 & §2.5

This note details the venue connector plugin contract: the ABC every connector implements, capability flags, lifecycle, registration, and the manual fallback path.

## 1. Goals

A connector exists for two reasons:

1. **Snapshot enrichment** — fetch the current market state for an instrument so the agent doesn't have to type it in.
2. **Outcome resolution** — fetch the final settlement value when a market resolves, so calibration auto-scoring can fire.

That's it. Connectors are **read-only** (in every version of the product). They do not execute trades. They do not handle wallet keys. They do not write to the ledger directly — they return values that the core ledger writes.

## 2. The `Connector` protocol

Connectors implement a single Python protocol:

```python
from typing import Protocol, runtime_checkable
from datetime import datetime
from pydantic import BaseModel

class InstrumentRef(BaseModel):
    """How a connector identifies a tradable thing.

    Connectors define their own validation; the core treats this opaquely
    aside from passing it back to the connector that produced it.
    """
    venue: str                  # connector.name
    external_id: str | None     # native venue ID
    url: str | None             # canonical market URL
    metadata: dict | None       # connector-specific routing info

class SnapshotResult(BaseModel):
    captured_at: datetime
    price: float | None
    bid: float | None
    ask: float | None
    mid: float | None
    spread: float | None
    volume: float | None
    open_interest: float | None
    implied_probability: float | None
    liquidity_depth: dict | None
    source_url: str | None
    metadata: dict | None

class OutcomeResult(BaseModel):
    resolved_at: datetime
    outcome_label: str
    outcome_value: float
    confidence: float           # 1.0 = unambiguous
    source: str
    metadata: dict | None

class ConnectorCapabilities(BaseModel):
    supports_resolution: bool
    supports_multi_outcome: bool
    supports_websocket: bool
    supports_search: bool
    requires_api_key: bool
    read_only: bool = True       # MUST be true; runtime asserted

@runtime_checkable
class Connector(Protocol):
    name: str
    venue_kind: str            # "prediction_market" | "equity" | "options" | "crypto" | "event_market" | "other"
    capabilities: ConnectorCapabilities

    def snapshot(self, instrument_ref: InstrumentRef) -> SnapshotResult: ...

    def resolve(self, instrument_ref: InstrumentRef) -> OutcomeResult | None:
        """Return None if the market has not yet resolved or resolution is ambiguous."""
        ...

    def search(self, query: str, *, limit: int = 20) -> list[InstrumentRef]:
        """Optional — return [] if capabilities.supports_search is False."""
        ...
```

Three required methods (`snapshot`, `resolve`, `search`), two optional behaviors gated on capabilities flags. `read_only=True` is asserted at registration time; a connector that returns `False` is rejected.

## 3. Capability flags

Capabilities tell the core what the connector can and can't do without inspecting the implementation:

- `supports_resolution`: connector can return `OutcomeResult`. For some venues (e.g., generic equities), we derive outcomes from price snapshots rather than calling the connector. Default `True` for prediction markets, `False` for price-only venues.
- `supports_multi_outcome`: connector can return outcomes labeled with multi-class values. Most prediction markets are binary; Manifold's MULTIPLE_CHOICE markets aren't. Affects auto-scoring path.
- `supports_websocket`: connector exposes a streaming API. P1 / P2 feature; MVP polls only.
- `supports_search`: `search()` is implemented. yfinance, for example, doesn't really search; it expects a ticker.
- `requires_api_key`: connector needs an API key via env var. Documented in the connector's README. The core never asks for or stores keys.
- `read_only`: must be `True`. Asserted at registration.

## 4. Entry-point registration

Connectors register via the `trade_trace.connectors` entry point group in `pyproject.toml`:

```toml
# In a hypothetical third-party connector's pyproject.toml
[project.entry-points."trade_trace.connectors"]
kalshi = "trade_trace_kalshi:KalshiConnector"
```

At startup the core enumerates this entry point group, instantiates each connector with its config (read from `$TRADE_TRACE_HOME/config.toml`), runs the `read_only=True` assertion, and registers the connector by `name`. First-party connectors ship under `trade_trace.connectors.{polymarket,manifold,yfinance}` and are registered via the trade-trace package's own entry points (gated on the appropriate extra: `trade-trace[polymarket]`).

The `venues` table's `connector_name` column joins to the live registry. If a venue's connector_name doesn't match any installed connector, the venue still works for manual entries — the connector is simply unavailable for snapshot/resolve operations.

## 5. Manual fallback path

Every connector capability has a manual analog:

| Connector op | Manual analog |
|--------------|---------------|
| `snapshot()` | `snapshot.add INSTRUMENT_ID --price ... --bid ... --ask ...` |
| `resolve()` | `outcome.add INSTRUMENT_ID --outcome-label YES --outcome-value 1.0 --resolved-at ...` |
| `search()` | `instrument.add` with explicit fields |

Manual entries write to the same ledger tables connector entries write to. The `source` column distinguishes them (`manual` vs `connector:polymarket`). This means: an instrument can have a mix of manual snapshots and connector snapshots over its lifetime — useful when a connector goes down or when historical data must be back-filled.

The implication: **no venue is ever blocked on connector availability**. An agent can journal trades on an unsupported venue using manual entries, and a connector can be added later without migration.

## 6. First-party connectors (MVP)

### 6.1 Polymarket (Gamma read-only)

- `name`: `polymarket`
- `venue_kind`: `prediction_market`
- `capabilities`: `supports_resolution=True`, `supports_multi_outcome=False` (MVP — Gamma binary markets only), `supports_search=True`, `requires_api_key=False`
- Backed by Polymarket's Gamma API. ~60 req/min unauthenticated. Read-only by construction (Gamma does not expose order signing).
- Resolution endpoint is reliable for unambiguous markets; the connector returns `OutcomeResult.confidence < 1.0` when the market is in a dispute window.

### 6.2 Manifold

- `name`: `manifold`
- `venue_kind`: `prediction_market`
- `capabilities`: `supports_resolution=True`, `supports_multi_outcome=True`, `supports_search=True`, `requires_api_key=False`
- Backed by Manifold's public API. 500 req/min, no auth needed for read.
- Supports BINARY, MULTIPLE_CHOICE, NUMERIC, PSEUDO_NUMERIC, FREE_RESPONSE market types — but the MVP only auto-scores BINARY. Other types are recorded but not scored until P1's multi-class scoring lands.

### 6.3 yfinance

- `name`: `yfinance`
- `venue_kind`: `equity`
- `capabilities`: `supports_resolution=False` (resolution is derived from forward returns, not from the connector), `supports_multi_outcome=False`, `supports_search=False`, `requires_api_key=False`
- Used for equities, ETFs, indexes, crypto pairs. Resolution is computed by the core from forward price data, not from the connector.
- Brittle (scraping-based); the connector wraps yfinance error modes and returns structured errors to the core so callers can fall back to manual entry.

## 7. Configuration

Connectors are configured in `config.toml`:

```toml
[connectors.polymarket]
enabled = true
rate_limit_per_minute = 50

[connectors.manifold]
enabled = true

[connectors.yfinance]
enabled = true
```

A connector can be `enabled = false` to keep it installed but not registered. Future connector-specific config (proxies, custom endpoints, API keys via env var indirection) lives in this section.

## 8. Errors

Connectors return structured errors with stable codes:

- `CONNECTOR_NOT_FOUND` — connector_name on the venue doesn't match any installed connector
- `INSTRUMENT_NOT_FOUND` — venue does not recognize the instrument_ref
- `MARKET_NOT_RESOLVED` — `resolve()` called before resolution
- `MARKET_AMBIGUOUS` — resolution is in dispute / pending official confirmation
- `RATE_LIMITED` — venue rate limit hit; retry-after included
- `CONNECTOR_ERROR` — opaque venue error (message included verbatim)

All connector errors propagate as structured JSON; agents handle them by falling back to manual entry or retrying.

## 9. Security model

- Connectors run in-process. There is no sandboxing.
- Connectors are loaded only from explicitly-configured entry point packages. Unknown connectors are not loaded.
- Connectors that need API keys read them only from environment variables. The core never persists keys, never logs them, and never accepts them via CLI args (which would leave them in shell history).
- Connector code that attempts to write to the ledger directly is blocked at the API boundary — connectors receive read-only handles, not the ledger writer.
- Future: opt-in capability-based loading (e.g., `--allow-network-connector polymarket`) is under consideration for P2.

## 10. Open questions

1. **Failure isolation**: if a connector hangs, does it block the core? MVP probably runs connectors with a timeout (e.g., 30s default). Async connector calls are P1.
2. **Cache layer**: should the core cache `snapshot()` results for some TTL to avoid hammering rate limits? Probably yes — TTL configurable per connector, default 0 (no cache). Add in M4.
3. **Backfill semantics**: if I add a connector for a venue I've been logging manually, can I retroactively enrich older instruments? Probably yes via a one-off `connector.backfill` command in P1.
4. **Connector-agnostic search**: a "search across all installed connectors" tool that fans out — useful, but does it belong in MVP? Probably no; agents can call each connector's `search` explicitly. Revisit in P1 if cross-venue search becomes a pattern.
