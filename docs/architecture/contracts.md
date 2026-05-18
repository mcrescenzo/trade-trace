# CLI/MCP Output Contract

Status: clean planning draft. Date: 2026-05-18.

Companion docs: [PRD.md](../../PRD.md), [VISION.md](../../VISION.md),
[scoring.md](scoring.md), [persistence.md](persistence.md),
[memory-layer.md](memory-layer.md).

## 1. Purpose

Trade Trace ships a single internal core API surfaced through two
transports: a Python MCP server and a Python CLI. PRD §6 requires that
these two surfaces produce **semantically equivalent** results — same
schemas, same error codes, same `data` shapes — after normalizing for
transport framing.

This doc defines the exact result/error envelope and the stable error
code list, and pins down the golden test plan that verifies CLI/MCP
parity.

The contract is designed for LLM agents. Agents consume JSON; they need
predictable shapes for retries, parsing, and error recovery.

## 2. Parity Goals

- **Schema-equal**: every tool's `data` payload is described by a single
  Pydantic model used by both transports.
- **Error-equal**: every error returns the same `code`, the same
  `message` text (modulo locale; we ship one locale in MVP), and the
  same `details` keys.
- **Envelope-equal**: success and error envelopes have the same shape on
  both transports.
- **NOT byte-identical**: MCP framing, stdio streaming, transport
  metadata, and CLI prose-on-stderr behavior all differ. Byte identity
  is explicitly out of scope.

## 3. Success Envelope

```json
{
  "ok": true,
  "data": { ... },
  "meta": { ... }
}
```

### 3.1 `data`

The tool-specific result payload. Schema is defined per tool in the
implementation. For list-returning tools, `data` is `{ "items": [...] }`
rather than a bare array, so adding pagination fields is non-breaking.

### 3.2 `meta`

Always-present fields:

- `tool`: the tool name as registered (e.g. `decision.create`).
- `actor_id`: echoed from the request (or the server's default actor).
- `request_id`: a server-generated ID for the call; useful for log
  correlation. Always returned, even if the client didn't supply one.

Sometimes-present fields:

- `event_id`: when the tool wrote at least one event, the primary
  event's `events.id`.
- `idempotent_replay: true`: when the call was a successful replay of a
  prior write with the same `idempotency_key` (see
  [persistence.md](persistence.md) §5).
- `cli_human_hint`: a short human-readable description of what happened,
  rendered to stderr by the CLI when `--human` is passed. Never affects
  semantic content.
- `mcp_transport_hints`: MCP-specific framing or streaming hints. Opaque
  to the CLI.

## 4. Error Envelope

```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "forecast_outcomes must sum to 1.0",
    "details": { "found_sum": 0.97 }
  },
  "meta": { ... }
}
```

- `error.code` is a stable enum (§5).
- `error.message` is a single human-readable sentence. Stable enough for
  use in tests but not a contract surface — callers should branch on
  `code`, not on `message`.
- `error.details` is a tool-specific object; documented per error code.
- `meta` has the same shape as the success envelope's `meta`. Even on
  error, `tool`, `actor_id`, and `request_id` are always set.

The HTTP/MCP transport status field (or equivalent) follows the envelope.
A successful envelope rides on a successful transport response; an error
envelope rides on whatever the transport considers an error response
(MCP error frame, non-zero CLI exit code).

## 5. Stable Error Codes

The MVP error code list. The list is closed; adding new codes is a
contract change requiring a version bump.

| Code | When |
|---|---|
| `VALIDATION_ERROR` | Input failed schema validation (wrong type, missing required field, value out of range). |
| `NOT_FOUND` | The referenced entity doesn't exist. |
| `IDEMPOTENCY_CONFLICT` | A retry with the same `idempotency_key` carried a semantically different payload than the original write. |
| `UNSUPPORTED_CAPABILITY` | The call targets a capability the server doesn't support in this configuration (e.g. vector recall when `sqlite-vec` is disabled). |
| `STORAGE_ERROR` | A storage layer (SQLite) error escaped the transaction. |
| `SCORING_UNSUPPORTED` | A forecast of this `kind` has `scoring_support = 'unsupported'`; scoring cannot be attempted. |
| `SCORING_NOT_READY` | Scoring was triggered but the prerequisites aren't met (no `resolved_final` outcome, ambiguous YES label, label mismatch). |
| `INVARIANT_VIOLATION` | A schema-level invariant was violated post-validation (e.g. binary forecast probabilities don't sum to 1, two outcomes have the same label). |
| `MARKET_NOT_RESOLVED` | Scoring or resolution was attempted on a forecast whose `resolution_at` hasn't passed and no outcome row exists. |
| `MARKET_AMBIGUOUS` | The most recent outcome row has `status ∈ ('ambiguous', 'disputed')`. |
| `RATE_LIMITED` | Reserved. Unused in MVP (no external API surface). Will be re-used if a future ingestion path needs it. |

### 5.1 Code selection guidance

When two codes could plausibly fit a failure, pick the more specific one:

- `INVARIANT_VIOLATION` > `VALIDATION_ERROR` when the schema passed but a
  cross-field constraint fired.
- `SCORING_NOT_READY` > `MARKET_NOT_RESOLVED` when the outcome row exists
  but isn't `resolved_final`.
- `IDEMPOTENCY_CONFLICT` > `VALIDATION_ERROR` when the new payload would
  have been valid in isolation but conflicts with a prior write under
  the same idempotency key.

## 6. NDJSON Streaming

CLI list tools emit NDJSON to stdout: one envelope per line. Each line is
a complete, parseable JSON object. The last line carries the success
envelope summarizing the stream (`data.items` may be empty if the stream
already contained all items; `data` carries `count`, `truncated`, etc.).

MCP streaming tools use the MCP-native streaming primitive. The agent
SDK can subscribe to the stream; each stream message is one envelope.

Both transports guarantee that an interrupted stream's final envelope is
either a complete success envelope or an error envelope. There is no
"stream just ends silently" state.

## 7. Golden Test Plan

The CLI and MCP parity contract is verified by a set of golden tests
that exercise the same fixture inputs against both transports and assert
envelope equivalence.

### 7.1 Test structure

For each tool:

1. A fixture file defines an input payload.
2. The test invokes the tool via the in-process MCP server and records
   the envelope.
3. The test invokes the same tool via the CLI subprocess and records
   the envelope.
4. Both envelopes are normalized: MCP transport hints stripped, CLI
   prose stripped, timestamps replaced with placeholders, `request_id`
   replaced with a placeholder.
5. The two normalized envelopes must be deep-equal.

### 7.2 Required coverage

- One success case per write tool.
- One success case per read tool.
- One `VALIDATION_ERROR` case per write tool.
- One `INVARIANT_VIOLATION` case per write tool that has a cross-field
  invariant (e.g. binary forecasts, normalized playbook adherence).
- One `IDEMPOTENCY_CONFLICT` case (single test exercising the
  idempotency contract across both transports).
- One `NOT_FOUND` case (single test).

PRD §9 lists this as a verification requirement.

## 8. Versioning

The envelope shape is part of the public contract. Backwards-compatible
extensions (adding optional fields to `meta`, adding new error codes to
the closed list as a minor version bump) are allowed. Breaking changes
(renaming `data` to something else, removing a `meta` field, changing
the type of an error code's `details` key) require a major version bump
and a deprecation window.

For MVP, the contract version is `1.0`. The version is surfaced via
`journal.status` and as a `meta.contract_version` field on every
envelope.

## 9. Open Questions

1. **Localized error messages.** Should `error.message` be localized in
   the future? Likely no — agents don't need locale. The flag is a
   per-call header in case dogfooders want it.
2. **Trace context.** When called from a hosting LLM that has its own
   request ID, do we accept and echo it (`X-Request-ID`-style)? Likely
   yes; cheap to add. Reserved field on `meta`.
3. **Streaming progress events.** For long-running tools (rebuilds,
   bulk imports), do we surface progress as in-stream envelope messages
   with `meta.progress` set? Out of MVP; design when the first
   long-running tool ships.
