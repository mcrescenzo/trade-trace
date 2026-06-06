# CLI/MCP Output Contract

> Status: **shipped**. Describes the CLI/MCP envelope and error codes that the live registry returns today.


**Implementation status (M0-M4 MVP):** every contract in this doc
ships in MVP — envelope shape, meta surface, error-code enum,
deterministic-replay meta fields, CLI/MCP parity tests. The only
known additive extension is `meta.preview_only` (bead trade-trace-2z7)
and `meta.dry_run` (bead 268), both backward-compatible.

Companion docs: [PRD.md](../PRD.md), [VISION.md](../VISION.md),
[scoring.md](scoring.md), [persistence.md](persistence.md),
[memory-layer.md](memory-layer.md),
[current-exposure-agent-contract.md](current-exposure-agent-contract.md),
and the agent-facing [AGENT_GUIDE.md](../AGENT_GUIDE.md).

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

- **Schema-equal**: every tool's input schema is exposed from the single
  registry used by both transports. Registered examples are auto-derived
  into JSON Schema when a tool does not supply an explicit schema.
- **Error-equal**: every error returns the same `code`, the same
  `message` text (modulo locale; we ship one locale in MVP), and the
  same `details` keys.
- **Envelope-equal**: success and error envelopes have the same shape on
  both transports.
- **NOT byte-identical**: MCP framing, stdio streaming, transport
  metadata, and CLI prose-on-stderr behavior all differ. Byte identity
  is explicitly out of scope.

### 2.1 Name mapping

MCP tool names use `subject.verb` dot notation (`decision.add`,
`memory.recall`, `report.calibration`). The CLI maps these mechanically:

- Replace each `.` with a single space.
- All other tokens are preserved.
- `args` keys become long-flag form `--key`; nested `args.foo.bar` becomes
  `--foo-bar` (kebab-cased). Arrays use repeated flags
  (`--node-types observation --node-types reflection`) — the CLI accumulates
  repeated occurrences into a list (trade-trace-pybt). Comma-separated values
  stay as a single string and are NOT split; pass `--<key>-json '<json>'`
  if you want explicit JSON shape (e.g., for object-valued fields or
  arrays whose individual values contain commas).

Examples:

| MCP tool | CLI invocation |
|---|---|
| `decision.add` | `trade-trace decision add` |
| `memory.recall` | `trade-trace memory recall` |
| `report.calibration` | `trade-trace report calibration` |
| `report.filter_schema` | `trade-trace report filter_schema` |
| `resolution.add` | `trade-trace resolution add` |
| `import.commit` | `trade-trace import commit` |
| `strategy.upsert` | `trade-trace strategy upsert` |
| `journal.init` | `trade-trace journal init` |
| `market.bind` | `trade-trace market bind` |

The default public registry exposes the consolidated v0.0.2 catalog. Renamed tools expose compatibility metadata such as `legacy_name` (for example `resolution.add` has legacy `outcome.add`; `playbook.record_adherence` has legacy `decision.record_adherence`; `playbook.upsert`/`strategy.upsert` replace `playbook.create`/`strategy.create`). `playbook.propose_version` stays catalog-visible — it is the only tool that mints a `playbook_version_id`, and `playbook.record_adherence` (which feeds `report.playbook_adherence`) hard-requires one, so folding the producer would leave the adherence report structurally unreachable from the MCP catalog (trade-trace-47tp). `tool.schema`/MCP metadata is the authoritative way for legacy callers to discover these hints and removed-tool guidance. For the public forecast/decision setup path, clients should call `market.bind` first and use its returned `instrument_id` for `snapshot.add`/`decision.add`; `forecast.add` can create the folded thesis prerequisite when supplied that `market_id` or `instrument_id` plus `rationale_body`.

The mapping is mechanical and irreversible-with-collisions: two MCP
tool names cannot map to the same CLI invocation.

**Collision detection (locked decision): enforced at registration time,
which runs both in test/CI and at every server/CLI process start.**
The tool registry (`src/trade_trace/contracts/tool_registry.py`,
`ToolRegistry.register` and `ToolRegistry.validate`) computes the CLI
invocation for every registered MCP name on construction and refuses to
load when two names map to the same invocation. The failure manifests as:

- **In CI / `pytest`**: a unit test (`tests/contracts/test_cli_name_uniqueness.py`)
  fails with an explicit "CLI invocation collision" assertion listing
  the conflicting tool names. The test gates CI; merging is blocked
  until resolved. Test cases cover: clean registry, injected duplicate
  invocation at register time, double registration, and full-CLI
  `STORAGE_ERROR` envelope emission.
- **At runtime startup**: `journal.init`, `journal.status`, and the MCP
  server entrypoint each call the same registry construction. A
  collision raises `trade_trace.contracts.tool_registry.CLINameCollisionError`
  which the CLI (`src/trade_trace/cli.py`) catches and translates to a
  fatal startup error (non-zero exit; `STORAGE_ERROR` envelope on stdout
  with `details.reason = "cli_name_collision"`, `details.conflict_kind`
  ∈ {`"duplicate_invocation"`, `"duplicate_name"`}, and
  `details.colliding[*]` carrying `{tool_a, tool_b, conflict_kind,
  suggested_rename}` per pair) before any tool call is accepted. This is
  defense in depth — the test gate is the primary line; the startup
  check exists so a forked/patched build with new tools cannot silently
  produce ambiguous CLI invocations.

Collisions cannot reach a released build that passed CI, and cannot
become a mid-call surprise at runtime.

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
- `idempotency_source`: set on write tools when idempotency enforcement
  applies. Value is `"auto"` when the dispatcher derived a deterministic
  `auto:` key from the tool name and structural payload fields, and
  `"caller"` when the agent supplied `idempotency_key` explicitly. See
  [persistence.md](persistence.md) §5.3.
- `contract_version`: the contract version string (`"1.0"` for MVP).
  Always set on success and error envelopes regardless of `--human`.
- `bin_policy`: set by `report.calibration` to identify the
  reliability-bin policy used (`"equal_width_0.1"` in MVP); see
  [scoring.md](scoring.md) §7.2.
- `budget_applied: true`: set by `memory.recall` when context-budget
  shaping (reducing `k`, switching to `compact`, dropping low-scoring
  rows) was applied.
- `sample_warning`: set by any report when the filtered sample size is
  below the configured minimum.
- `truncated: true` plus `next_cursor`: set by list/report tools when the
  result set was truncated. See [reports.md](reports.md) §3.
- `cli_human_hint`: a short human-readable description of what happened,
  rendered to stderr by the CLI when `--human` is passed. Never affects
  semantic content. The CLI also surfaces this field on `meta` so agents
  inspecting the envelope see the same string the human reader saw on
  stderr.
- `mcp_transport_hints`: MCP-specific framing or streaming hints. Opaque
  to the CLI; populated as a (possibly empty) dict on the MCP path so
  the structure is consistent across transports.
- `dry_run: true`: set by the dispatcher when a write tool was invoked
  with `--dry-run` (CLI) or `_dry_run: true` (MCP). The handler runs
  normally and returns the would-be IDs / payload, but the wrapping
  transaction rolls back; no events are appended and no projections are
  updated. Per bead trade-trace-268.

### 3.3 Considered-and-passed survivorship surfaces (trade-trace-s7nn)

The calibration integrity control `abstention_coverage`
(`report.calibration_integrity.diagnostics.abstention_coverage`, also
embedded in `report.calibration.data.integrity_diagnostics` and
`report.coach.integrity_diagnostics`) exists to make the calibration
denominator honest about survivorship bias: it surfaces the markets the
agent *considered and passed on*, which never enter the Brier/log-score
numbers.

There are **two** documented ways an agent records "I considered this
market and passed", and the control counts **both**:

1. **`abstention.record`** → a first-class `abstentions` row. This is the
   primary survivorship surface. Reported under `count` /
   `abstention_share_pct` (unchanged shape for existing consumers;
   `abstention_share_pct = abstentions / (forecasts + abstentions)`).
2. **`decision.add(type='skip')` with no linked forecast** → the
   material-non-action path advertised by the decision matrix
   (`x-material-non-action-taxonomy`). A skip that carries
   `forecast_id IS NULL` is a considered-and-passed-without-forecasting
   event that never enters calibration. Reported under the
   `skip_coverage` sub-block (`{count, sample_ids.decisions, truncated}`).

A skip that **does** link a forecast is intentionally *not* re-counted as
a pass here: the forecast already carries it into the calibration
denominator and into `forecast_coverage`. Such skips remain visible via
`report.forecast_diagnostics.decision_coverage` (which also carries a
`skip_survivorship_surface` signpost back to `abstention_coverage`).

**No double-counting.** A single market may carry both a skip *and* an
`abstention.record`. The two lines above stay distinct, and the
de-duplicated union is reported separately:

- `considered_passes_dedup` — abstentions plus forecast-less-skip
  *instruments* that are not already represented by an abstention (each
  passed market counted once).
- `considered_total_dedup` — `total_forecasts + considered_passes_dedup`.
- `considered_share_pct` — `considered_passes_dedup /
  considered_total_dedup`, the honest pass-surface share.

`report.coach` renders the de-duplicated union in its callout, breaking
out the abstention vs forecast-less-skip contributions, so a bot that
diligently records skips is never shown 0% coverage when it has in fact
documented its passes.

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
  Conventions (per bead trade-trace-268):
  - `VALIDATION_ERROR` on a timestamp field carries
    `details.field` + `details.expected_format` (e.g. `"UTC ISO 8601 with
    millisecond precision; operability.md §2.1"`).
  - `NOT_FOUND` carries `details.entity_kind` identifying the missing
    entity class (e.g. `"forecast"`, `"source"`, `"thesis"`, `"tool"`).
  - `IDEMPOTENCY_CONFLICT` carries `details.original_event_id` and
    `details.diff_summary` per persistence.md §5.2.
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
| `VALIDATION_ERROR` | Input failed schema validation (wrong type, missing required field, value out of range, forbidden field set per the decision required-field matrix in [PRD](../PRD.md) §3.1). |
| `NOT_FOUND` | The referenced entity doesn't exist. |
| `IDEMPOTENCY_CONFLICT` | A retry with the same `idempotency_key` carried a semantically different payload than the original write. See [persistence.md](persistence.md) §5.2 for the per-event-type comparison policy. |
| `UNSUPPORTED_CAPABILITY` | The call targets a capability the server doesn't support in this configuration (e.g. vector recall when `embeddings.provider = none`). |
| `STORAGE_ERROR` | A storage layer (SQLite) error escaped the transaction. `details.reason` is set when known: `single_writer_lock` for the multi-writer case ([operability.md](operability.md) §3), `wal_corruption` for WAL faults, etc. |
| `SCORING_UNSUPPORTED` | A forecast of this `kind` has `scoring_support = 'unsupported'`; scoring cannot be attempted. |
| `SCORING_NOT_READY` | Scoring was triggered but the prerequisites aren't met (no `resolved_final` outcome, ambiguous YES label, label mismatch). |
| `INVARIANT_VIOLATION` | A schema-level invariant was violated post-validation (e.g. binary forecast probabilities don't sum to 1, two outcomes have the same label). |
| `MARKET_NOT_RESOLVED` | Scoring or resolution was attempted on a forecast whose `resolution_at` hasn't passed and no outcome row exists. |
| `MARKET_AMBIGUOUS` | The most recent outcome row has `status ∈ ('ambiguous', 'disputed')`. |
| `ADAPTER_DISABLED` | An opt-in external adapter was called while disabled. The Polymarket adapter is disabled by default. |
| `ADAPTER_TIMEOUT` | An enabled external adapter exceeded its configured timeout while calling an upstream endpoint. |
| `ADAPTER_RATE_LIMITED` | An enabled external adapter received a rate-limit response from an upstream endpoint. |
| `ADAPTER_PROTOCOL_ERROR` | An enabled external adapter received a malformed or semantically invalid upstream response. |
| `EXTERNAL_API_ERROR` | An enabled external adapter received a non-rate-limit upstream API failure. |
| `RESOLUTION_NOT_AVAILABLE` | A requested market resolution is not yet available from the configured upstream or chain source. |
| `CONFIG_REQUIRED` | An opt-in adapter feature was called without required local configuration (for example a missing Polygon RPC URL). |
| `MARKET_NOT_BOUND` | A Trade Trace forecast or market reference has not been bound to the required upstream market identifier. |
| `MARKET_STATE_CONFLICT` | Local market state and upstream adapter state conflict and the caller must resolve the mismatch before continuing. |

Rate-limit semantics are adapter-specific. External adapters use `ADAPTER_RATE_LIMITED`; local/non-adapter throttling would require a future additive enum extension per §8.

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

#### Strategy-specific coverage (lands with M3)

- One success case for `strategy.upsert` and report/list coverage via `report.strategy_health`.
- One `VALIDATION_ERROR` case for `strategy.upsert` covering duplicate
  slug rejection (single-field uniqueness — see §5.1; `VALIDATION_ERROR`
  is the correct selection over `INVARIANT_VIOLATION`).
- One `VALIDATION_ERROR` case for `memory.link` / `memory.reflect`
  whose payload supplies an invalid edge endpoint kind. The test
  fixture's expected enum MUST list `strategy` (and `signal`) as valid
  kinds; the failing payload uses an unrecognized kind like
  `not_a_real_kind`. This pins the §3.2 endpoint enum to the contract.
- One success case for `decision.add` with `strategy_id` set and one
  with `strategy_slug` set (alias resolution); both envelopes must echo
  `strategy_id` in `data`.
- One success case for `memory.recall` with
  `context: {kind: "strategy", id: ...}` returning at least one row
  whose `meta.provenance` references the supplied strategy.

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
