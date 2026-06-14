# Guided market-scan dry-run/promote contract

> Status: **legacy** — `market.scan.dry_run` and `market.scan.promote` were folded into `market.bind` in the v0.0.2 PM pivot (trade-trace-4kec). Callers should use `market.bind`; these names are kept as dispatchable aliases for backward compatibility only (see `V002_FOLDED_OR_REMOVED` in `src/trade_trace/core.py`). This document specifies the original public contract and the Polymarket-style caller-supplied mapping/workflow that informed the consolidated `market.bind` surface.

## 1. Purpose and public surface

Trade Trace should let an agent turn a caller-supplied market snapshot plus research/source inputs into a complete, auditable journal arc without fetching venue data, giving trading advice, or executing trades.

The additive public surface is:

- `market.scan.dry_run` — read-only validator/planner. It validates and normalizes a proposed market-scan bundle, returns an ordered primitive call plan, checks/warnings, deterministic child idempotency keys, missing fields, and a promote payload hint/hash. It performs no database writes.
- `market.scan.promote` — write-capable materializer. It executes the previously dry-run plan or an equivalent payload, reuses idempotent rows when the same child keys already exist, and returns created/reused IDs plus final bundle status. Promote is replay-safe through deterministic child idempotency keys; it should be treated as logical idempotent materialization, not as a guarantee that every primitive side effect can be physically rolled back after a later primitive fails.

These tools are orchestration sugar over existing primitives such as `venue.add`, `instrument.add`, `snapshot.add`, `source.add`, `source.attach_to_thesis`, `source.attach_to_forecast`, `source.attach_to_decision`, `thesis.add`, `forecast.add`, `decision.add`, `memory.reflect` when requested, and `journal.bundle.status`. They do not create a second storage model.

## 2. Safety boundaries

`market.scan.*` MUST preserve existing Trade Trace boundaries:

- No external venue, broker, market-data, order-book, outcome, URL, or file fetches. The caller supplies all market snapshot fields, research text, URLs, venue identifiers, and resolution information.
- No advice or recommendation. Trade Trace does not provide investment advice. The caller supplies the final `decision.action`; Trade Trace may report validation checks and audit warnings but must not choose `watch`, `skip`, or `paper_enter` for the caller.
- No trade execution. Trade Trace does not execute trades. `paper_enter` means the existing `decision.add(type="paper_enter")` journal behavior only: it creates a paper decision, appends the automatic linked `position_events.open` row, refreshes the `positions` projection, and returns `position_id` / `position_event_id`. It does not place, route, sign, or cancel any order.
- No credentials. Payloads must not include broker/API keys, wallet seeds, private keys, or execution tokens.

## 3. Input model

Both tools accept the same normalized bundle shape. `market.scan.dry_run` requires the bundle plus a parent idempotency key; `market.scan.promote` requires either the same bundle and `promote_hash` or the dry-run result's `promote_payload_hint`.

```json
{
  "actor_id": "agent:research-bot",
  "idempotency_key": "run-20260521-001:market-scan:polymarket:slug-x:v1",
  "agent_id": "agent:polymarket-scout",
  "model_id": "model-family-or-runner",
  "environment": "paper",
  "run_id": "run-20260521-001",
  "venue": {
    "name": "Polymarket",
    "kind": "prediction_market",
    "external_id": "polymarket",
    "metadata_json": {"caller_supplied": true}
  },
  "instrument": {
    "asset_class": "prediction_market",
    "external_id": "0x...or-market-slug",
    "symbol": "optional-short-label",
    "title": "Will event X happen by 2026-06-30?",
    "currency_or_collateral": "USDC",
    "expiration_or_resolution_at": "2026-06-30T23:59:59Z",
    "resolution_criteria_text": "Caller-supplied resolution rule text.",
    "metadata_json": {"venue_slug": "event-x"}
  },
  "snapshot": {
    "captured_at": "2026-05-21T12:00:00Z",
    "source": "manual",
    "source_url": "https://example.invalid/market/event-x",
    "price": 0.52,
    "bid": 0.50,
    "ask": 0.54,
    "mid": 0.52,
    "spread": 0.04,
    "volume": 10000,
    "open_interest": 25000,
    "implied_probability": 0.52,
    "liquidity_depth_json": {"caller_supplied_depth": []},
    "metadata_json": {"snapshot_source_note": "supplied by caller"}
  },
  "sources": [
    {
      "kind": "url",
      "stance": "supports",
      "uri": "https://example.invalid/source",
      "title": "Primary evidence",
      "freshness_at": "2026-05-21T11:30:00Z",
      "summary": "Caller-supplied summary.",
      "storage_kind": "url"
    }
  ],
  "thesis": {
    "side": "yes",
    "body": "Caller-authored thesis text.",
    "falsification_criteria": "What would disprove the thesis.",
    "exit_triggers": "What would cause reassessment.",
    "risk_notes": "Process/risk notes, not advice.",
    "time_horizon_at": "2026-06-30T23:59:59Z",
    "confidence_label": "medium",
    "strategy_id": "str_optional"
  },
  "forecast": {
    "kind": "binary",
    "yes_label": "YES",
    "resolution_at": "2026-06-30T23:59:59Z",
    "resolution_rule_text": "Same/compatible with instrument criteria.",
    "outcomes": [
      {"outcome_label": "YES", "probability": 0.57},
      {"outcome_label": "NO", "probability": 0.43}
    ]
  },
  "decision": {
    "action": "watch",
    "side": "yes",
    "reason": "Caller-selected action rationale.",
    "review_by": "2026-05-28T12:00:00Z",
    "tags": ["market-scan", "prediction-market"],
    "playbook_version_id": "pbv_optional",
    "strategy_id": "str_optional"
  },
  "attachments": {
    "attach_sources_to": ["thesis", "forecast", "decision"],
    "reflection": {
      "enabled": false,
      "body": "Optional process note after promoting the bundle."
    }
  }
}
```

Notes:

- `decision.action` maps to existing `decision.add.type` and is limited to `watch`, `skip`, and `paper_enter` in this contract.
- Existing segmentation fields (`agent_id`, `model_id`, `environment`, `run_id`) are copied to primitives that support them.
- Existing strategy/playbook/tag fields remain optional and must use current primitive names (`strategy_id`, `playbook_version_id`, `tags`).
- `actor_id` is transport metadata for MCP/CLI in the live system; if a transport does not accept it inside `args`, the tool context's actor remains authoritative.

### 3.1 JSON-schema-like input contract

The normalized bundle is intentionally shaped around existing primitive argument names. Future implementations may express this as JSON Schema, Pydantic, or CLI flags, but the public semantics are:

```text
MarketScanRequest {
  actor_id?: string                 # transport/context metadata; not a persisted primitive arg when context supplies actor
  idempotency_key: string           # parent key; all child idempotency_key values derive from this
  promote_hash?: string             # required by promote when caller wants dry-run hash verification
  agent_id?: string                 # copied to thesis.add / forecast.add / decision.add when supplied
  model_id?: string                 # copied to thesis.add / forecast.add / decision.add when supplied
  environment?: string              # copied to thesis.add / forecast.add / decision.add when supplied
  run_id?: string                   # copied to thesis.add / forecast.add / decision.add when supplied

  venue?: VenueCreate | ExistingVenueRef
  instrument: InstrumentCreate | ExistingInstrumentRef
  snapshot?: SnapshotCreate | ExistingSnapshotRef
  sources?: SourceCreateOrRef[]
  thesis?: ThesisCreate | ExistingThesisRef
  forecast?: ForecastCreate | ExistingForecastRef
  decision: DecisionIntent
  attachments?: AttachmentPolicy
}
```

Required/optional behavior:

| Field | Required? | Contract |
|---|---:|---|
| `idempotency_key` | yes | Stable caller-chosen parent key. Dry-run derives child keys such as `<parent>:decision:watch`; promote uses the same keys for idempotent create/reuse behavior. |
| `venue` | optional when `instrument.venue_id` exists; otherwise required | New venue uses existing `venue.add` args: `name`, `kind`, optional `metadata_json`. Existing ref uses `venue_id`. |
| `instrument` | yes | Either `instrument_id` or existing `instrument.add` args: `venue_id`/created venue, `asset_class`, `title`, optional `external_id`, `symbol`, `currency_or_collateral`, `expiration_or_resolution_at`, `resolution_criteria_text`, `contract_multiplier`, `metadata_json`. |
| `snapshot` | optional | Either `snapshot_id` or existing `snapshot.add` args: `instrument_id`, `captured_at`, `source`, `source_url`, `price`, `bid`, `ask`, `mid`, `spread`, `volume`, `open_interest`, `implied_probability`, `liquidity_depth_json`, `metadata_json`. |
| `sources[]` | optional | Each item is either `source_id` or existing `source.add` args (`kind`, `stance`, `uri`, `title`, `freshness_at`, `summary`, `excerpt`, `extracted_text`, `storage_kind`, etc.). URLs are stored only; they are not fetched. |
| `thesis` | required for `paper_enter`; optional for `watch`/`skip` | Either `thesis_id` or existing `thesis.add` args: `instrument_id`, `side`, `body`, optional `falsification_criteria`, `exit_triggers`, `risk_notes`, `time_horizon_at`, `confidence_label`, `strategy_id`, `metadata_json`. |
| `forecast` | optional | Either `forecast_id` or existing `forecast.add` args: `thesis_id`, `kind`, `yes_label`, `resolution_at`, `resolution_rule_text`, `outcomes`. |
| `decision` | yes | `action` is normalized to existing `decision.add.type`. All other keys must already be accepted by `decision.add`: `instrument_id`, `thesis_id`, `forecast_id`, `snapshot_id`, `side`, `quantity`, `price`, `fees`, `slippage`, `reason`, `review_by`, `playbook_version_id`, `strategy_id`, `tags`, segmentation fields, `metadata_json`. |
| `attachments.attach_sources_to` | optional | Default is implementation-defined but must only materialize explicit existing tools: `source.attach_to_thesis`, `source.attach_to_forecast`, `source.attach_to_decision` with `source_id`, `target_id`, `idempotency_key`. |
| `attachments.reflection` | optional | If enabled, promote may call existing memory tools after decision creation; dry-run only plans them. |

Existing-ID refs are always caller supplied. If `instrument_id`, `snapshot_id`, `thesis_id`, `forecast_id`, or `source_id` is present, dry-run must treat it as an ID to carry forward, not as authorization to fetch or infer missing venue data.

### 3.2 Decision payload fragments

The fragments below are the exact existing `decision.add` argument names generated inside `ordered_calls[*].args` after bundle IDs are resolved. They obey the current `decision.add` matrix.

`watch` (no `quantity`, `price`, `fees`, or `slippage`):

```json
{
  "type": "watch",
  "instrument_id": "ins_from_instrument_add_or_existing",
  "thesis_id": "th_from_thesis_add_or_existing",
  "forecast_id": "fc_from_forecast_add_or_existing",
  "snapshot_id": "snp_from_snapshot_add_or_existing",
  "side": "yes",
  "reason": "Caller wants this on a watchlist pending a fresher snapshot.",
  "review_by": "2026-05-28T12:00:00Z",
  "tags": ["market-scan", "prediction-market"],
  "idempotency_key": "run-42:market-scan:pm:event-x:v1:decision:watch"
}
```

`skip` (requires `reason`; no `quantity`, `price`, `fees`, `slippage`, or `review_by`):

```json
{
  "type": "skip",
  "instrument_id": "ins_from_instrument_add_or_existing",
  "thesis_id": "th_from_thesis_add_or_existing",
  "forecast_id": "fc_from_forecast_add_or_existing",
  "snapshot_id": "snp_from_snapshot_add_or_existing",
  "side": "yes",
  "reason": "Caller-selected skip rationale: resolution criteria are too ambiguous for this run.",
  "tags": ["market-scan", "prediction-market"],
  "idempotency_key": "run-42:market-scan:pm:event-x:v1:decision:skip"
}
```

`paper_enter` (requires `instrument_id`, `thesis_id`, `side`, `quantity`, and `price`; no `review_by`):

```json
{
  "type": "paper_enter",
  "instrument_id": "ins_from_instrument_add_or_existing",
  "thesis_id": "th_from_thesis_add_or_existing",
  "forecast_id": "fc_from_forecast_add_or_existing",
  "snapshot_id": "snp_from_snapshot_add_or_existing",
  "side": "yes",
  "quantity": 10,
  "price": 0.52,
  "fees": 0,
  "slippage": 0.01,
  "reason": "Caller-selected paper journal entry for later calibration; not an executed order.",
  "tags": ["market-scan", "prediction-market", "paper"],
  "idempotency_key": "run-42:market-scan:pm:event-x:v1:decision:paper_enter"
}
```

## 4. Dry-run semantics

`market.scan.dry_run` is read-only. It MUST NOT call write handlers with committed transactions and MUST NOT append events, edges, sources, position events, or projection rows. It may validate against current schemas, normalize timestamps/tags/numbers, compute a deterministic plan, and optionally query existing rows only when needed to check supplied IDs.

A successful dry-run returns:

```json
{
  "ok": true,
  "data": {
    "plan_state": "dry_run",
    "bundle_status": "ready_to_promote",
    "normalized_action": "watch",
    "ordered_calls": [
      {
        "tool": "venue.add",
        "purpose": "Create/reuse caller-supplied venue row.",
        "args": {"name": "Polymarket", "kind": "prediction_market", "idempotency_key": "<parent>:venue"},
        "creates": "venue_id",
        "child_idempotency_key": "<parent>:venue"
      },
      {
        "tool": "instrument.add",
        "purpose": "Create/reuse caller-supplied instrument row.",
        "args": {"venue_id": "<venue_id>", "asset_class": "prediction_market", "title": "Will event X happen?", "idempotency_key": "<parent>:instrument"},
        "creates": "instrument_id",
        "child_idempotency_key": "<parent>:instrument"
      },
      {
        "tool": "snapshot.add",
        "purpose": "Record caller-supplied snapshot; no venue fetch is performed.",
        "args": {"instrument_id": "<instrument_id>", "captured_at": "2026-05-21T12:00:00Z", "price": 0.52, "bid": 0.50, "ask": 0.54, "idempotency_key": "<parent>:snapshot"},
        "creates": "snapshot_id",
        "child_idempotency_key": "<parent>:snapshot"
      },
      {
        "tool": "source.add",
        "purpose": "Store caller-supplied source metadata/content only.",
        "args": {"kind": "url", "stance": "supports", "uri": "https://example.invalid/source", "title": "Primary evidence", "summary": "Caller-supplied summary.", "idempotency_key": "<parent>:source:0"},
        "creates": "source_id",
        "child_idempotency_key": "<parent>:source:0"
      },
      {
        "tool": "thesis.add",
        "purpose": "Create/reuse caller-authored thesis.",
        "args": {"instrument_id": "<instrument_id>", "side": "yes", "body": "Caller-authored thesis text.", "idempotency_key": "<parent>:thesis"},
        "creates": "thesis_id",
        "child_idempotency_key": "<parent>:thesis"
      },
      {
        "tool": "source.attach_to_thesis",
        "purpose": "Attach source to thesis.",
        "args": {"source_id": "<source_id>", "target_id": "<thesis_id>", "idempotency_key": "<parent>:source:0:attach:thesis"},
        "creates": "edge_id",
        "child_idempotency_key": "<parent>:source:0:attach:thesis"
      },
      {
        "tool": "forecast.add",
        "purpose": "Create/reuse caller-supplied forecast.",
        "args": {"thesis_id": "<thesis_id>", "kind": "binary", "yes_label": "YES", "outcomes": [{"outcome_label": "YES", "probability": 0.57}, {"outcome_label": "NO", "probability": 0.43}], "idempotency_key": "<parent>:forecast"},
        "creates": "forecast_id",
        "child_idempotency_key": "<parent>:forecast"
      },
      {
        "tool": "source.attach_to_forecast",
        "purpose": "Attach source to forecast.",
        "args": {"source_id": "<source_id>", "target_id": "<forecast_id>", "idempotency_key": "<parent>:source:0:attach:forecast"},
        "creates": "edge_id",
        "child_idempotency_key": "<parent>:source:0:attach:forecast"
      },
      {
        "tool": "decision.add",
        "purpose": "Record caller-selected watch decision using existing decision.add matrix.",
        "args": {"type": "watch", "instrument_id": "<instrument_id>", "thesis_id": "<thesis_id>", "forecast_id": "<forecast_id>", "snapshot_id": "<snapshot_id>", "side": "yes", "reason": "Caller-selected action rationale.", "review_by": "2026-05-28T12:00:00Z", "idempotency_key": "<parent>:decision:watch"},
        "creates": "decision_id",
        "child_idempotency_key": "<parent>:decision:watch"
      },
      {
        "tool": "source.attach_to_decision",
        "purpose": "Attach source to decision.",
        "args": {"source_id": "<source_id>", "target_id": "<decision_id>", "idempotency_key": "<parent>:source:0:attach:decision"},
        "creates": "edge_id",
        "child_idempotency_key": "<parent>:source:0:attach:decision"
      }
    ],
    "checks": [
      {"severity": "info", "code": "caller_supplied_data_only", "message": "All market/source fields are caller supplied and unverified.", "field": "venue"},
      {"severity": "warning", "code": "wide_spread", "message": "Snapshot spread is high relative to mid.", "field": "snapshot.spread"}
    ],
    "missing_fields": [],
    "child_idempotency_keys": {
      "venue": "<parent>:venue",
      "instrument": "<parent>:instrument",
      "snapshot": "<parent>:snapshot",
      "source:0": "<parent>:source:0",
      "source_attach:0:thesis": "<parent>:source:0:attach:thesis",
      "thesis": "<parent>:thesis",
      "forecast": "<parent>:forecast",
      "decision:watch": "<parent>:decision:watch"
    },
    "promote_payload_hint": {"idempotency_key": "<parent>", "plan_hash": "sha256:...", "bundle": "<normalized bundle>"},
    "promote_hash": "sha256:..."
  },
  "meta": {
    "tool": "market.scan.dry_run",
    "dry_run": true,
    "contract_version": "1.0",
    "read_only": true,
    "external_fetch_performed": false,
    "trade_execution_performed": false,
    "advice_generated": false
  }
}
```

Dry-run must classify the result as:

- `ready_to_promote` when there are no blocking checks; warnings/info may still be present and must remain visible to the caller.
- `blocked` when required fields, enum values, timestamp formats, decision-matrix requirements, or unresolved ID references fail.
- `needs_review` only when a warning policy requires explicit caller acknowledgement before promote; after acknowledgement the payload can become `ready_to_promote` without changing caller-supplied market data.

`promote_hash` is a stable digest of the normalized bundle, ordered primitive call plan, and child idempotency keys. It is not a market-data hash and must not imply Trade Trace verified external facts.

## 5. Promote semantics

`market.scan.promote` is write-capable and MUST rerun validation immediately before materialization. Because current primitive write tools commit their own events, the implemented transaction contract is logical replay-safe materialization through deterministic child idempotency keys, not physical all-or-nothing rollback after a later primitive fails. Validation must be rerun at promote time; stale dry-run output is only a hint.

Promote behavior:

1. Verify the provided `promote_hash` if present. A hash mismatch is a blocking `VALIDATION_ERROR` with a corrected dry-run hint.
2. Execute primitive calls in the same logical order as dry-run. Existing primitive validation remains authoritative.
3. Use deterministic child idempotency keys. Safe replays return reused IDs; semantic conflicts surface as `IDEMPOTENCY_CONFLICT` with the conflicting child step.
4. Use logical replay-safe child idempotency. Promote validates before writes and should use a database transaction where practical, but callers must not rely on physical rollback of every primitive side effect after a later primitive fails. If a partial failure is reported, retry the same payload/idempotency keys after correcting the problem; existing successful child rows are reused and conflicts are surfaced as `IDEMPOTENCY_CONFLICT`.
5. Preserve existing primitive side effects. In particular, `paper_enter` invokes `decision.add(type="paper_enter")`, which creates the linked `position_events.open` and refreshes `positions` exactly as the primitive already does.

A successful promote returns:

```json
{
  "ok": true,
  "data": {
    "bundle_status": "needs_enrichment",
    "created_ids": {
      "venue_id": "ven_...",
      "instrument_id": "ins_...",
      "snapshot_id": "snap_...",
      "source_ids": ["src_..."],
      "thesis_id": "ths_...",
      "forecast_id": "fcst_...",
      "decision_id": "dec_..."
    },
    "reused_ids": {},
    "primitive_results": [
      {"tool": "venue.add", "status": "created", "id": "ven_..."},
      {"tool": "decision.add", "status": "created", "id": "dec_..."}
    ],
    "final_check": {
      "tool": "journal.bundle.status",
      "result": {
        "status": "needs_enrichment",
        "input_ids": {"decision": "dec_..."},
        "checklist": [
          {"step": "decision_recorded", "status": "ok", "record_ids": {"decisions": ["dec_..."]}, "next_call": "decision.add"},
          {"step": "reflection_attached", "status": "missing", "record_ids": {"decisions": ["dec_..."]}, "next_call": "memory.reflect / memory.link"}
        ]
      }
    }
  },
  "meta": {"tool": "market.scan.promote", "contract_version": "1.0"}
}
```

`bundle_status` is copied from the raw `journal.bundle.status.result.status`; common values are the existing `complete_enough`, `needs_enrichment`, and `has_weak_steps`. If all child writes replay, `bundle_status` remains the same as the first successful promote, `created_ids` may be empty, `reused_ids` carries the prior row IDs, and `primitive_results[*].status` is `reused`.
For `paper_enter`, the `decision.add` primitive result and top-level ID maps also include the existing `position_id` and `position_event_id` returned by that primitive.

### 5.1 Promote response examples

Plain `watch` / `skip` promote responses have the same shape. Only the `decision.add` primitive args and child key differ by action. The `final_check.result` is the raw `journal.bundle.status` shape: `status`, `contract_version`, `input_ids`, `relevant_ids`, `checklist`, `next_calls`, `idea_capture_provenance`, and `no_advice_boundary`.

```json
{
  "ok": true,
  "data": {
    "bundle_status": "needs_enrichment",
    "created_ids": {
      "venue_id": "ven_123",
      "instrument_id": "ins_123",
      "snapshot_id": "snp_123",
      "source_ids": ["src_123"],
      "source_edge_ids": ["edg_src_thesis", "edg_src_forecast", "edg_src_decision"],
      "thesis_id": "th_123",
      "forecast_id": "fc_123",
      "decision_id": "dec_123"
    },
    "reused_ids": {},
    "primitive_results": [
      {"tool": "venue.add", "status": "created", "id": "ven_123", "child_idempotency_key": "<parent>:venue"},
      {"tool": "decision.add", "status": "created", "id": "dec_123", "child_idempotency_key": "<parent>:decision:skip"}
    ],
    "final_check": {
      "tool": "journal.bundle.status",
      "args": {"decision_id": "dec_123", "forecast_id": "fc_123", "thesis_id": "th_123", "instrument_id": "ins_123", "source_id": "src_123"},
      "result": {
        "status": "needs_enrichment",
        "contract_version": "1.0",
        "input_ids": {"decision": "dec_123", "forecast": "fc_123", "thesis": "th_123", "instrument": "ins_123", "source": "src_123"},
        "relevant_ids": {"venue": ["ven_123"], "instrument": ["ins_123"], "snapshot": ["snp_123"], "thesis": ["th_123"], "forecast": ["fc_123"], "decision": ["dec_123"], "source": ["src_123"], "memory_node": []},
        "checklist": [
          {"step": "venue_recorded", "status": "ok", "record_ids": {"venues": ["ven_123"]}, "next_call": "venue.add"},
          {"step": "decision_recorded", "status": "ok", "record_ids": {"decisions": ["dec_123"]}, "next_call": "decision.add"},
          {"step": "reflection_attached", "status": "missing", "record_ids": {"decisions": ["dec_123"]}, "next_call": "memory.reflect / memory.link"}
        ],
        "next_calls": [{"for_step": "reflection_attached", "tool": "memory.reflect / memory.link", "carry_forward_ids": {"decision_ids": ["dec_123"]}}],
        "idea_capture_provenance": {"present": false, "records": []},
        "no_advice_boundary": {"external_fetch_performed": false, "trade_execution_performed": false, "advice_generated": false}
      }
    }
  },
  "meta": {"tool": "market.scan.promote", "contract_version": "1.0"}
}
```

Safe replay response example: `created_ids` is empty, `reused_ids` carries the prior row IDs, and primitive statuses are `reused`.

```json
{
  "ok": true,
  "data": {
    "bundle_status": "needs_enrichment",
    "created_ids": {},
    "reused_ids": {"venue_id": "ven_123", "instrument_id": "ins_123", "snapshot_id": "snp_123", "source_ids": ["src_123"], "thesis_id": "th_123", "forecast_id": "fc_123", "decision_id": "dec_123"},
    "primitive_results": [{"tool": "decision.add", "status": "reused", "id": "dec_123", "child_idempotency_key": "<parent>:decision:watch"}],
    "final_check": {"tool": "journal.bundle.status", "result": {"status": "needs_enrichment", "contract_version": "1.0", "input_ids": {"decision": "dec_123"}, "relevant_ids": {"decision": ["dec_123"], "memory_node": []}, "checklist": [{"step": "decision_recorded", "status": "ok", "record_ids": {"decisions": ["dec_123"]}, "next_call": "decision.add"}, {"step": "reflection_attached", "status": "missing", "record_ids": {"decisions": ["dec_123"]}, "next_call": "memory.reflect / memory.link"}], "next_calls": [{"for_step": "reflection_attached", "tool": "memory.reflect / memory.link", "carry_forward_ids": {"decision_ids": ["dec_123"]}}], "idea_capture_provenance": {"present": false, "records": []}, "no_advice_boundary": {"external_fetch_performed": false, "trade_execution_performed": false, "advice_generated": false}}}
  }
}
```

`paper_enter` promote preserves existing `decision.add(type="paper_enter")` outputs and reports the paper position artifacts; it still does not execute a broker trade:

```json
{
  "ok": true,
  "data": {
    "bundle_status": "needs_enrichment",
    "created_ids": {"decision_id": "dec_paper_123", "position_id": "pos_123", "position_event_id": "pev_123"},
    "reused_ids": {},
    "primitive_results": [
      {"tool": "decision.add", "status": "created", "id": "dec_paper_123", "position_id": "pos_123", "position_event_id": "pev_123", "child_idempotency_key": "<parent>:decision:paper_enter"}
    ],
    "final_check": {
      "tool": "journal.bundle.status",
      "result": {
        "status": "needs_enrichment",
        "contract_version": "1.0",
        "input_ids": {"decision": "dec_paper_123"},
        "relevant_ids": {"decision": ["dec_paper_123"], "instrument": ["ins_123"], "thesis": ["th_123"], "forecast": ["fc_123"], "source": ["src_123"], "snapshot": ["snp_123"], "venue": ["ven_123"], "memory_node": []},
        "checklist": [
          {"step": "decision_recorded", "status": "ok", "record_ids": {"decisions": ["dec_paper_123"]}, "next_call": "decision.add"},
          {"step": "reflection_attached", "status": "missing", "record_ids": {"decisions": ["dec_paper_123"]}, "next_call": "memory.reflect / memory.link"}
        ],
        "next_calls": [{"for_step": "reflection_attached", "tool": "memory.reflect / memory.link", "carry_forward_ids": {"decision_ids": ["dec_paper_123"]}}],
        "idea_capture_provenance": {"present": false, "records": []},
        "no_advice_boundary": {"external_fetch_performed": false, "trade_execution_performed": false, "advice_generated": false}
      }
    }
  },
  "meta": {"tool": "market.scan.promote", "contract_version": "1.0", "trade_execution_performed": false}
}
```

## 6. Materialization mapping by action

The decision action is caller-supplied and maps to existing primitives as follows.

### `watch`

- `decision.add.type = "watch"`.
- Required by current matrix: `instrument_id`.
- Optional: `thesis_id`, `forecast_id`, `snapshot_id`, `side`, `reason`, `review_by`, `strategy_id`, `playbook_version_id`, `tags`, segmentation fields.
- Forbidden: `quantity`, `price`, `fees`, `slippage`.
- A `review_by` deadline is encouraged for watchlist auditability but is not required by the current primitive.

### `skip`

- `decision.add.type = "skip"`.
- Required by current matrix: `instrument_id`, `reason`.
- Optional: `thesis_id`, `forecast_id`, `snapshot_id`, `side`, `strategy_id`, `playbook_version_id`, `tags`, segmentation fields.
- Forbidden: `quantity`, `price`, `fees`, `slippage`, `review_by`.

### `paper_enter`

- `decision.add.type = "paper_enter"`.
- Required by current matrix: `instrument_id`, `thesis_id`, `side`, `quantity`, `price`.
- Optional: `forecast_id`, `snapshot_id`, `fees`, `slippage`, `reason`, `strategy_id`, `playbook_version_id`, `tags`, segmentation fields.
- Forbidden: `review_by`.
- Promote MUST not invent broker execution. It delegates to `decision.add`, preserving the existing automatic paper position event/projection behavior and returning the primitive's `position_id` and `position_event_id`.

## 7. Child idempotency keys

Child idempotency keys are deterministic, stable across retries, and scoped under the parent `idempotency_key`. Recommended scheme:

```text
<parent>:venue
<parent>:instrument
<parent>:snapshot
<parent>:source:<zero-based-index>
<parent>:source:<zero-based-index>:attach:thesis
<parent>:source:<zero-based-index>:attach:forecast
<parent>:source:<zero-based-index>:attach:decision
<parent>:thesis
<parent>:forecast
<parent>:decision:watch
<parent>:decision:skip
<parent>:decision:paper_enter
<parent>:reflection
```

Examples for parent `run-42:market-scan:pm:event-x:v1`:

- `run-42:market-scan:pm:event-x:v1:venue`
- `run-42:market-scan:pm:event-x:v1:instrument`
- `run-42:market-scan:pm:event-x:v1:snapshot`
- `run-42:market-scan:pm:event-x:v1:source:0`
- `run-42:market-scan:pm:event-x:v1:source:0:attach:decision`
- `run-42:market-scan:pm:event-x:v1:thesis`
- `run-42:market-scan:pm:event-x:v1:forecast`
- `run-42:market-scan:pm:event-x:v1:decision:paper_enter`

If a caller supplies an existing `venue_id`, `instrument_id`, `snapshot_id`, `source_id`, `thesis_id`, `forecast_id`, or `decision_id`, the dry-run plan marks the corresponding create step as skipped and still uses child keys for any remaining new rows/attachments.

## 8. Checks and warnings taxonomy

Checks are returned by dry-run and rerun by promote. Shape:

```json
{"severity":"blocking|warning|info","code":"...","field":"...","message":"...","recovery":"..."}
```

Blocking checks include:

- `missing_required_field` — primitive-required field absent, such as `decision.reason` for `skip` or `decision.quantity` for `paper_enter`.
- `invalid_enum` — action not one of `watch`, `skip`, `paper_enter`, or primitive enum mismatch.
- `decision_matrix_violation` — forbidden field supplied for the chosen action.
- `invalid_timestamp` — non-UTC or unparsable `captured_at`, `resolution_at`, `review_by`, or source freshness timestamp.
- `ambiguous_action` — multiple actions supplied or action cannot be normalized exactly.
- `invalid_probability_sum` — binary forecast probabilities do not sum to 1 within primitive tolerance.
- `missing_resolution_criteria` — no `instrument.resolution_criteria_text` and no `forecast.resolution_rule_text` for an auditable forecast.
- `idempotency_conflict` — child key exists for a different semantic payload.

Warning checks include:

- `wide_spread` — `snapshot.spread` or `ask - bid` is large relative to `mid`/price; Trade Trace reports only an audit warning, not a recommendation.
- `stale_snapshot` — `snapshot.captured_at` is older than the configured or default freshness threshold.
- `missing_source` — no source/research attachment supplied.
- `missing_revisit_deadline` — `watch` lacks `review_by`.
- `weak_resolution_criteria` — resolution text exists but is short or missing the deciding authority/date.
- `scoring_support_caveat` — forecast kind is non-binary or otherwise unsupported by the current scorer; record-only behavior should be explicit.
- `missing_bid_ask` — snapshot has only a price and no bid/ask/spread/liquidity fields.

Info checks include:

- `caller_supplied_data_only` — reminder that all venue/snapshot/source fields are unverified caller inputs.
- `paper_enter_is_journal_only` — reminder that `paper_enter` creates only a paper journal position.
- `source_url_not_fetched` — URLs are stored as metadata/provenance only.

## 9. Polymarket caller-supplied mapping example

Polymarket is only an example venue mapping. Trade Trace MUST NOT fetch Polymarket Gamma/CLOB data, inspect order books, resolve markets, or call URLs. The caller supplies known fields and Trade Trace stores them.

Caller-known Polymarket-ish fields can map as:

| Caller-supplied field | Trade Trace target |
|---|---|
| `question` | `instrument.title` |
| `slug` / market id / condition id | `instrument.external_id`, `instrument.metadata_json.polymarket.slug`, `instrument.metadata_json.polymarket.condition_id` |
| YES/NO token IDs | `instrument.metadata_json.polymarket.tokens` |
| resolution deadline / end date | `instrument.expiration_or_resolution_at`, `forecast.resolution_at` |
| resolution rules text | `instrument.resolution_criteria_text`, `forecast.resolution_rule_text` |
| best bid / best ask | `snapshot.bid`, `snapshot.ask` |
| midpoint / last / mark | `snapshot.mid`, `snapshot.price`, `snapshot.implied_probability` |
| spread | `snapshot.spread` |
| volume / liquidity | `snapshot.volume`, `snapshot.open_interest`, `snapshot.liquidity_depth_json` |
| market page URL / rules URL / evidence URL | `snapshot.source_url`, `source.uri` |
| research/source summaries | `source.summary`, `source.excerpt`, `source.extracted_text` when caller supplies inline content |

### 9.1 Complete Polymarket-style caller-supplied example

This example is intentionally concrete but not factual advice. The caller has already copied the market page URL, rules, prices, depth, source URLs, thesis, forecast, and selected decision action. Trade Trace stores and audits those inputs; it does not verify the title, URL, prices, liquidity, depth, source summaries, resolution criteria, or forecast.

Example bundle fragment:

```json
{
  "venue": {"name": "Polymarket", "kind": "prediction_market"},
  "instrument": {
    "asset_class": "prediction_market",
    "external_id": "https://polymarket.com/event/fed-cut-june-2026",
    "symbol": "PM:FED-CUT-JUN2026:YES",
    "title": "Will the Federal Reserve cut rates by the June 2026 FOMC meeting?",
    "currency_or_collateral": "USDC",
    "expiration_or_resolution_at": "2026-06-30T23:59:59Z",
    "resolution_criteria_text": "Caller-copied rules: market resolves YES if the target federal funds range is lowered at or before the June 2026 FOMC decision, according to the official Federal Reserve statement; otherwise NO. Edge cases and source of truth are the caller-copied Polymarket rules.",
    "metadata_json": {
      "polymarket": {
        "slug": "fed-cut-june-2026",
        "market_url": "https://polymarket.com/event/fed-cut-june-2026",
        "condition_id": "0xabc123...caller-supplied",
        "tokens": {"YES": "1234567890", "NO": "9876543210"}
      }
    }
  },
  "snapshot": {
    "captured_at": "2026-05-21T12:00:00Z",
    "source": "manual",
    "source_url": "https://polymarket.com/event/fed-cut-june-2026",
    "price": 0.48,
    "bid": 0.47,
    "ask": 0.50,
    "mid": 0.485,
    "spread": 0.03,
    "volume": 1250000,
    "open_interest": 315000,
    "implied_probability": 0.485,
    "liquidity_depth_json": {
      "best_bid_size": 4200,
      "best_ask_size": 3700,
      "depth_levels": [
        {"side": "bid", "price": 0.47, "size": 4200},
        {"side": "bid", "price": 0.46, "size": 9800},
        {"side": "ask", "price": 0.50, "size": 3700},
        {"side": "ask", "price": 0.51, "size": 11200}
      ],
      "depth_source": "caller-copied order-book snapshot"
    },
    "metadata_json": {"liquidity_note": "Caller-supplied; not fetched or verified by Trade Trace."}
  },
  "sources": [
    {
      "kind": "url",
      "stance": "supports",
      "uri": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
      "title": "Federal Reserve FOMC calendars",
      "freshness_at": "2026-05-21T11:30:00Z",
      "summary": "Caller summary: official calendar identifies the relevant June 2026 FOMC date.",
      "storage_kind": "url"
    },
    {
      "kind": "url",
      "stance": "neutral",
      "uri": "https://polymarket.com/event/fed-cut-june-2026",
      "title": "Polymarket market page and rules",
      "freshness_at": "2026-05-21T11:45:00Z",
      "summary": "Caller summary: copied title, condition ID, token IDs, bid/ask, depth, and rules from market page.",
      "storage_kind": "url"
    }
  ],
  "thesis": {
    "side": "yes",
    "body": "Caller-authored thesis: market mid is below the caller's 56% binary forecast because recent inflation prints and policy communication make one pre-June cut more likely than the current mid implies.",
    "falsification_criteria": "Caller-authored: hotter inflation data or explicit Fed guidance ruling out near-term cuts would falsify the setup.",
    "exit_triggers": "Reassess after the next CPI release, FOMC minutes, or if spread widens above 8 cents.",
    "risk_notes": "Prediction-market liquidity can vanish; resolution text may have edge cases; this is journaling, not advice.",
    "time_horizon_at": "2026-06-30T23:59:59Z",
    "confidence_label": "medium"
  },
  "forecast": {
    "kind": "binary",
    "yes_label": "YES",
    "resolution_at": "2026-06-30T23:59:59Z",
    "resolution_rule_text": "Same caller-copied Polymarket/Fed statement rule as instrument.resolution_criteria_text.",
    "outcomes": [
      {"outcome_label": "YES", "probability": 0.56},
      {"outcome_label": "NO", "probability": 0.44}
    ]
  },
  "decision": {
    "action": "watch",
    "side": "yes",
    "reason": "Caller-selected watch: monitor until CPI data updates thesis or spread tightens.",
    "review_by": "2026-06-12T16:00:00Z",
    "tags": ["market-scan", "prediction-market", "polymarket", "rates"]
  }
}
```

Decision substitutions for the same caller-supplied bundle:

- `watch`: keep `decision.action = "watch"`, omit `quantity`/`price`, and include `review_by`, for example `reason = "Caller-selected watch: wait for tighter spread or new CPI data."`.
- `skip`: set `decision.action = "skip"`, omit `quantity`/`price`/`review_by`, and include a reason, for example `reason = "Caller-selected skip: resolution wording and spread are too ambiguous for this run."`.
- `paper_enter`: set `decision.action = "paper_enter"`, include `quantity` and `price`, omit `review_by`, for example `quantity = 25`, `price = 0.50`, `fees = 0`, `slippage = 0.01`, `reason = "Caller-selected paper entry for calibration only; no broker or market order is sent."`.

### 9.2 Guided CLI/MCP workflow

Use dry-run first, inspect the returned checks/plan/hash, then promote only if the caller accepts the plan. CLI names are derived from dotted tool names and nested values are passed as JSON flags where needed.

```bash
# 1. Dry-run: validates and plans only; no writes, no URL fetches, no advice, no trades.
tt market scan dry_run \
  --idempotency-key run-20260521-001:market-scan:polymarket:fed-cut-june-2026:v1 \
  --venue-json '{"name":"Polymarket","kind":"prediction_market","external_id":"polymarket"}' \
  --instrument-json '{"asset_class":"prediction_market","external_id":"https://polymarket.com/event/fed-cut-june-2026","title":"Will the Federal Reserve cut rates by the June 2026 FOMC meeting?","currency_or_collateral":"USDC","expiration_or_resolution_at":"2026-06-30T23:59:59Z","resolution_criteria_text":"Caller-copied Polymarket resolution criteria."}' \
  --snapshot-json '{"captured_at":"2026-05-21T12:00:00Z","source":"manual","source_url":"https://polymarket.com/event/fed-cut-june-2026","price":0.48,"bid":0.47,"ask":0.50,"mid":0.485,"spread":0.03,"volume":1250000,"open_interest":315000,"implied_probability":0.485,"liquidity_depth_json":{"best_bid_size":4200,"best_ask_size":3700}}' \
  --sources-json '[{"kind":"url","stance":"neutral","uri":"https://polymarket.com/event/fed-cut-june-2026","title":"Polymarket market page and rules","summary":"Caller-supplied market/rules summary.","storage_kind":"url"}]' \
  --thesis-json '{"side":"yes","body":"Caller-authored thesis text.","risk_notes":"Journaling only; not advice.","time_horizon_at":"2026-06-30T23:59:59Z","confidence_label":"medium"}' \
  --forecast-json '{"kind":"binary","yes_label":"YES","resolution_at":"2026-06-30T23:59:59Z","resolution_rule_text":"Caller-copied rules.","outcomes":[{"outcome_label":"YES","probability":0.56},{"outcome_label":"NO","probability":0.44}]}' \
  --decision-json '{"action":"watch","side":"yes","reason":"Caller-selected watch.","review_by":"2026-06-12T16:00:00Z","tags":["market-scan","polymarket"]}'

# 2. Promote: pass the accepted dry-run promote_hash/promote_payload_hint or equivalent bundle.
tt market scan promote \
  --idempotency-key run-20260521-001:market-scan:polymarket:fed-cut-june-2026:v1 \
  --promote-hash sha256:<value-from-dry-run> \
  --promote-payload-hint-json '<promote_payload_hint-from-dry-run>'
```

MCP callers use the same sequence: call `market.scan.dry_run` with the JSON bundle, require `data.bundle_status == "ready_to_promote"` or explicit caller acknowledgement of non-blocking warnings, then call `market.scan.promote` with the accepted payload/hash. After promote, verify `data.final_check.tool == "journal.bundle.status"` and read `data.final_check.result.status`; that final journal `bundle.status` is the authoritative completion/enrichment status for the recorded arc.

Boundary recap for agents: Trade Trace does not fetch URLs, provide investment advice, execute trades, or verify market facts. Every market title, external ID/URL, resolution criterion, bid/ask/mid/spread, liquidity/depth value, source URL/summary, thesis, forecast, and decision action is caller supplied.

## 10. Downstream implementation bead sequencing

Keep implementation beads narrow and sequenced:

- `.2` — formalize schemas/examples for `market.scan.dry_run` / `market.scan.promote` inputs and result payloads, including `action` enum, child idempotency-key derivation, and caller-supplied Polymarket examples.
- `.3` — implement `market.scan.dry_run` as read-only validation/plan generation with checks/warnings and promote hash/hint; no DB writes.
- `.4` — implement `market.scan.promote` transactional execution for the dry-run plan, idempotent created/reused ID reporting, rollback behavior, and final `journal.bundle.status` check.
- `.5` — extend bundle status and plan guidance so `paper_enter` arcs include the existing paper position event/projection outputs and warnings.
- `.6` — document the Polymarket caller-supplied mapping and guided workflow, explicitly proving there is no fetcher or external data dependency.
- `.7` — add focused e2e tests for CLI/MCP dry-run/promote parity, idempotency, rollback/no-network behavior, and `watch`/`skip`/`paper_enter` bundle outcomes.

## 11. Non-goals

This contract does not add a Polymarket adapter, broker connector, recommendation engine, market scanner, background scheduler, order executor, outcome resolver, or new scoring model. It defines only a guided journaling bundle over caller-supplied data and existing Trade Trace primitives.
