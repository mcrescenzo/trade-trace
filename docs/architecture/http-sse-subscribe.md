# HTTP/SSE Event-Log Subscribe Design

> Status: **design — not implemented**. The MVP transport is stdio MCP + the CLI; HTTP/SSE is listed in PRD §P1+ work and has no implementation in the live registry.

Status: proposed design artifact for bead `trade-trace-alr`; design-only, not implemented.
Parent bead `trade-trace-alr` closed as Fixed meaning the design artifact itself was completed, not that an implementation was shipped.
Date: 2026-05-19.

Companion docs: [PRD.md](../PRD.md), [persistence.md](persistence.md), [contracts.md](contracts.md), [operability.md](operability.md), [security.md](security.md).

## 1. Recommendation, status, and non-goals

Recommendation: add an optional, explicitly started local HTTP transport with a Server-Sent Events (SSE) `events.subscribe` endpoint as a P1 feature after this design is accepted. The endpoint should stream committed rows from the existing SQLite `events` table and should use `events.id` as the authoritative cursor.

Status:

- This document specifies the intended API and safety posture only.
- No production code is introduced by this bead.
- Follow-up implementation beads must not be created until design acceptance by the controller, unless the feature is explicitly deferred.

Non-goals:

- No remote sync service, telemetry, webhooks, broker/market-data integration, or cloud relay.
- No websocket transport in this design; SSE is sufficient for one-way event-log delivery.
- No mutation API beyond the already existing tool surfaces.
- No new source of truth. The SQLite `events` table remains authoritative; JSONL/outbox remain export mechanisms, not subscribe state.
- No guarantee of indefinite replay retention beyond the local SQLite event log and documented compaction policy if one is later added.
- No implementation commitment to a specific Python web framework.

## 2. Local-only/no-remote-by-default posture

HTTP/SSE must preserve Trade Trace's local, air-gappable default posture:

- A default install and normal `journal.init`, CLI use, MCP stdio use, and in-process tests must not open listening sockets.
- The existing MCP server remains stdio-only by default. Stdio does not bind a port and does not perform network discovery.
- The HTTP/SSE server starts only when the operator runs an explicit future command such as `trade-trace serve http` or passes an explicit equivalent config/flag. Merely importing the package or initializing a journal must never start a server.
- The default bind address for the HTTP server must be loopback only: `127.0.0.1` for IPv4 and/or `::1` for IPv6. Prefer a single default of `127.0.0.1` unless dual-stack behavior is explicitly tested.
- Binding to `0.0.0.0`, `::`, a LAN IP, or a public interface is remote exposure and must require an explicit opt-in flag such as `--bind 0.0.0.0` plus a warning that local journal payloads may be exposed to the network.
- No outbound network is required for subscribe. SSE is an inbound listener only after explicit opt-in. It must not fetch external data, call webhooks, phone home, or perform telemetry.
- Any future discovery mechanism such as mDNS, UPnP, tunnel setup, reverse proxy, or public relay is out of scope and must be separately designed with explicit opt-in.

Suggested startup examples for the future implementation:

```bash
# Local-only listener; explicit server start, safe default bind.
trade-trace serve http --home ~/.trade-trace --bind 127.0.0.1 --port 8765

# Remote exposure; must warn and should require auth before becoming supported.
trade-trace serve http --home ~/.trade-trace --bind 0.0.0.0 --port 8765 --auth-token-env TRADE_TRACE_HTTP_TOKEN
```

## 3. Auth stance

Local default mode:

- Loopback-only HTTP may support no authentication in the initial local mode, matching the local CLI/MCP trust model, but this must be documented as local-process/user-boundary trust rather than network security.
- Even in local no-auth mode, the server must not expose credential-shaped transport hints or secrets in schema/listing metadata.
- Local no-auth is acceptable only while the bind address is loopback and the operator explicitly started the listener.

Remote future mode:

- Non-loopback binding must not be treated as equivalent to local mode.
- Recommendation: require authentication for remote binding before declaring the mode supported. Minimum acceptable future mechanism is a bearer token sourced from an environment variable or OS keyring, never persisted in the journal database or plaintext config.
- Remote mode should also consider TLS termination guidance, CORS default-deny, request-size caps, structured access logs that avoid payload bodies, and clear warnings that event payloads can contain trading theses, rationales, source text, and redacted fields.
- If auth is not implemented at the time HTTP/SSE lands, remote binding should be rejected or marked unsupported rather than silently served unauthenticated.

## 4. Subscribe API shape

Endpoint:

- `GET /events/subscribe`
- Response: `text/event-stream; charset=utf-8`
- Method is read-only from the domain perspective. It may keep a SQLite read connection open briefly/poll repeatedly, but it must not append events.

Query parameters:

- `cursor`: optional integer event id. Semantics: deliver events with `events.id > cursor`. Omitted means start at the current high-water mark unless `replay` is supplied.
- `replay`: optional enum. Suggested values:
  - `none` (default): start after the current high-water mark; only future events are streamed.
  - `from_cursor`: require `cursor`; replay `id > cursor` up to the current high-water mark, then follow new events.
  - `from_beginning`: replay from the first retained event. Useful for local tools, but may be expensive.
- `limit`: optional positive integer cap for replay catch-up before follow mode. Default should be bounded, e.g. 1000. The server may reject excessive values with a typed error event before closing.
- `event_type`: optional repeatable filter. If present, stream only matching event types. Filtering does not change cursor semantics: cursor still refers to global `events.id`, so clients can resume without per-filter sequence ambiguity.
- `subject_kind` / `subject_id`: optional filters for scoped local viewers. Same global cursor rule applies.
- `heartbeat_ms`: optional bounded heartbeat interval; server enforces min/max.

SSE frame mapping:

```text
id: 123
event: trade_trace.event
data: {"contract_version":"1.0","event_id":123,...}

```

Heartbeat frame:

```text
event: trade_trace.heartbeat
data: {"contract_version":"1.0","last_event_id":123,"server_time":"2026-05-19T00:00:00.000Z"}

```

Error/status frame before disconnect when possible:

```text
event: trade_trace.error
data: {"contract_version":"1.0","code":"CURSOR_GONE","message":"cursor is older than the retained replay window","details":{"oldest_event_id":42,"requested_cursor":1}}

```

## 5. Cursor semantics and replay window

Cursor authority:

- `events.id` is the only subscribe cursor for P1. It is monotonic, database-local, and already the event-log authority.
- The SSE `id:` field must equal the decimal `events.id` value. Browser/EventSource clients can then use `Last-Event-ID` for automatic resume.
- If both `Last-Event-ID` header and `cursor` query parameter are present, the query parameter should win only if explicitly documented; recommendation: reject the ambiguous request with a typed error unless the values match.
- Resume means at-least-once delivery. Clients must deduplicate by `event_id`.

Replay window:

- Initial implementation should define the replay window as all retained rows in the local `events` table.
- If future compaction is added, the server must expose `oldest_event_id` and `latest_event_id` in a status endpoint or initial control event.
- If a requested cursor is older than retained history, return `CURSOR_GONE` with `oldest_event_id`, `latest_event_id`, and `requested_cursor`, then close. Do not silently start from the oldest retained event.
- If a requested cursor is greater than the current high-water mark, return `CURSOR_AHEAD` or hold only if explicitly allowed. Recommendation: reject by default because it likely indicates the wrong journal/home.

Catch-up then follow:

1. On connect, read current high-water mark.
2. If replay is requested, stream rows with `id > cursor` up to the high-water mark in ascending `id` order, subject to `limit` and backpressure rules.
3. Emit an optional `trade_trace.caught_up` control event containing `last_event_id`.
4. Poll or otherwise wait for new commits and continue streaming rows with `id > last_sent_id`.

## 6. Event envelope

Each data event should be a transport envelope around an `events` row, not a CLI/MCP success envelope. Proposed JSON object:

```json
{
  "contract_version": "1.0",
  "event_id": 123,
  "event_type": "decision.created",
  "subject": {"kind": "decision", "id": "dec_..."},
  "created_at": "2026-05-19T00:00:00.000Z",
  "actor_id": "agent:default",
  "idempotency_key": "...",
  "request_id": "...",
  "agent_id": "agent:polymarket-scout",
  "model_id": "...",
  "environment": "paper",
  "run_id": "...",
  "payload": {"...": "validated event payload"},
  "meta": {
    "source": "events",
    "cursor": "123",
    "redaction_applied": false
  }
}
```

Notes:

- `payload` maps from `events.payload_json` and may include sensitive journal text. See privacy caveats below.
- `idempotency_key` is operational metadata and may be useful for consumers, but exposing it remotely increases correlation risk. Future remote mode may need an option to omit or hash it.
- `contract_version` should match the existing envelope version line unless event-stream versioning later diverges.
- Unknown additive fields are allowed; removing or renaming fields requires a contract bump.

## 7. Ordering and deduplication

Ordering:

- Stream order is ascending `events.id` within a single SQLite database.
- This order is commit order as represented by the event log, not necessarily wall-clock order if client-supplied timestamps differ.
- Filters must preserve global order among delivered events.

Deduplication:

- Delivery is at-least-once across disconnect/resume.
- Clients must treat `event_id` as the deduplication key.
- Server-side idempotency keys prevent duplicate writes for retryable write tools; subscribe dedup is still necessary because transport reconnects can replay the last event.

No gap hiding:

- The server must not skip unavailable rows silently.
- If it detects that the requested replay cannot be satisfied, it emits/reports a typed cursor error rather than pretending continuity.

## 8. Backpressure, slow consumers, and disconnect behavior

Backpressure:

- The server should keep bounded per-connection buffers. Suggested default: a small event count or byte budget, configurable only within safe bounds.
- If a client cannot receive fast enough, prefer disconnecting with a `SLOW_CONSUMER` error event rather than unbounded memory growth.
- Replay catch-up should batch database reads but write SSE frames incrementally. Do not materialize unbounded replay sets in memory.
- Payload size caps from operability/security docs should apply; oversized events should either already be impossible at write time or produce a typed stream error if encountered.

Disconnect behavior:

- Normal client disconnect has no domain side effect and appends no event.
- On reconnect, clients resume with `Last-Event-ID` or `cursor=<last_event_id>` and receive `id > last_event_id`.
- The server should emit heartbeats while idle so clients and proxies can detect half-open connections.
- The server should close idle/broken connections promptly and release SQLite resources.

Concurrency:

- Subscribe should not block writers for long periods. Use short read transactions or polling queries that release locks between batches.
- SQLite WAL mode supports concurrent readers, but implementation tests must verify subscribe does not violate the single-writer assumptions documented in operability/persistence.

## 9. Privacy and security caveats

- Event payloads are local journal records. They may include trading theses, decision rationale, source excerpts, model/run identifiers, strategy hypotheses, and fields that were accepted after credential redaction. Treat the stream as sensitive.
- Existing credential-shaped write arguments are ignored/not persisted by write tools, but redaction is not a guarantee that all business-sensitive text is absent. Free text can still contain private strategy information.
- No outbound network is allowed by default. Starting HTTP/SSE is an explicit inbound listener action; it must not introduce telemetry or external fetches.
- Binding beyond loopback can expose the journal to other machines, containers, browser contexts, or hostile networks. Remote binding requires explicit opt-in and should require auth before support.
- CORS should default to disabled or same-origin/local-only. A local browser viewer must not imply arbitrary website access to `localhost` data without deliberate CORS design.
- Access logs should not include full event payloads by default. Log event ids, request ids, status, and disconnect reasons instead.

## 10. Implementation sketch

Design-only sketch for a future bead:

1. Add a transport module separate from `mcp_server.py`, e.g. `http_server.py`, to avoid weakening stdio-only MCP defaults.
2. Add an explicit CLI entrypoint such as `trade-trace serve http` with required/visible `--home`, default `--bind 127.0.0.1`, and default port.
3. At startup, validate bind policy:
   - Loopback bind allowed without auth after explicit command.
   - Non-loopback bind rejected unless remote mode/auth design has been accepted and implemented.
4. Implement `GET /events/subscribe` as a read-only event-log streamer over SQLite WAL.
5. Use `events.id` as SSE `id` and stream event envelopes in ascending id order.
6. Implement bounded replay batches, heartbeat frames, and bounded per-client output buffering.
7. Add typed stream errors for `CURSOR_GONE`, `CURSOR_AHEAD`, invalid parameters, and `SLOW_CONSUMER`.
8. Keep HTTP transport metadata out of core event payloads. The event writer remains transport-agnostic.

## 11. Tests and verification matrix

| Requirement | Proposed verification |
|---|---|
| Default use opens no sockets | Extend existing no-network tests to cover default import, `journal.init`, `journal.status`, CLI/MCP representative flow, and assert no listening socket is created. |
| HTTP server not started implicitly | Test that importing `trade_trace`, constructing the tool registry, and running MCP stdio helpers do not bind ports. |
| Explicit local bind only | Start future HTTP command with defaults and assert listener is on `127.0.0.1` or `::1` only. |
| Non-loopback requires opt-in | Attempt `--bind 0.0.0.0` without remote/auth opt-in and assert startup fails with a typed error/warning. |
| No outbound network by default | Keep/extend monkeypatch tests for `socket.connect`/`getaddrinfo`; for HTTP tests, distinguish explicit local `bind/listen` from outbound `connect`. |
| Cursor resume | Create events 1..N, subscribe from cursor K, assert first delivered id is K+1 and order is ascending. Disconnect after event M, reconnect with `Last-Event-ID: M`, assert M+1 is first and duplicates are client-dedupable if replayed. |
| Replay from beginning | With retained events, request `replay=from_beginning`; assert ascending complete delivery up to high-water mark then caught-up/follow behavior. |
| Cursor gone | Simulate retention floor or fixture with oldest id > requested cursor; assert `CURSOR_GONE` includes `oldest_event_id` and closes without silent truncation. |
| Cursor ahead | Request cursor greater than latest id; assert typed rejection unless a later accepted design chooses hold-open semantics. |
| Event envelope | Assert SSE `id` equals `data.event_id`; required envelope fields exist; payload parses from `events.payload_json`; no CLI/MCP success envelope confusion. |
| Ordering/dedup | Write events from multiple actors/types and assert global id order under filters; clients dedup by event_id. |
| Backpressure | Use a slow client/fake writer and assert bounded buffer plus `SLOW_CONSUMER` disconnect rather than memory growth. |
| Disconnect cleanup | Open and close subscriptions repeatedly; assert no leaked tasks/connections and subsequent writers proceed. |
| Privacy posture | Assert access logs omit payload bodies; schema/tool metadata does not expose secret/transport hint keys. |
| Auth stance | For local no-auth mode, assert loopback-only. For future remote mode, assert missing/invalid bearer token fails and token is not stored in DB/config/logs. |

## 12. Follow-up policy

No implementation beads should be created from this document until the design is accepted by the controller for `trade-trace-alr`. If the controller decides not to accept the design now, explicitly defer HTTP/SSE subscribe and leave PRD/persistence references as P1/out-of-MVP rather than partially implementing transport code.
