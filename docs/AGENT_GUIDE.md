# Agent guide: driving the journal loop

## 1. Connect

Install MCP support locally with `pip install -e '.[mcp]'` from the repository, initialize a journal with `tt journal init`, then connect through either the MCP stdio server (`trade-trace-mcp`, configured for clients such as Claude Desktop, Cursor, Windsurf, and Cline) or the JSON-first CLI (`tt` / `trade-trace`). MCP tool names use dot notation, and the CLI maps dots to spaces; both transports share the same envelope shape and error semantics described in [docs/architecture/contracts.md](./architecture/contracts.md). Use an actor id such as `agent:research-bot` (`MCP_ACTOR_ID` for stdio MCP, `--actor-id` for CLI) and never submit broker/API credentials or secrets. For MCP setup details, start with [AI_AGENT_MCP_GETTING_STARTED.md](./AI_AGENT_MCP_GETTING_STARTED.md).

## 2. The journal loop

A minimal agent loop is ordered so every later record can point back to the evidence it used. Use `tool.schema` first if you need exact current fields for any call.

1. `venue.add` — create or identify the source venue.

```json
{"tool":"venue.add","args":{"name":"Polymarket","kind":"prediction_market","idempotency_key":"agent-run-42:venue:polymarket"}}
```

2. `instrument.add` — create or identify the market/instrument under that venue. Keep `resolution_criteria_text` explicit enough that future outcome resolution is auditable.

```json
{"tool":"instrument.add","args":{"venue_id":"ven_manual","asset_class":"prediction_market","title":"Will event X happen by 2026-06-30?","resolution_criteria_text":"Final result from named source by date.","idempotency_key":"agent-run-42:instrument:event-x"}}
```

3. `thesis.add` — record why the trade/skip is being considered, including falsification criteria and optional `strategy_id`.

```json
{"tool":"thesis.add","args":{"instrument_id":"ins_...","side":"yes","body":"Base rate and new evidence imply fair probability above market.","falsification_criteria":"Official source contradicts premise before resolution.","strategy_id":"str_...","idempotency_key":"agent-run-42:thesis:event-x"}}
```

4. `forecast.add` — commit the probability before the outcome is known. Late forecasts are accepted for auditability but marked; see pitfalls.

```json
{"tool":"forecast.add","args":{"thesis_id":"ths_...","kind":"binary","yes_label":"YES","outcomes":[{"outcome_label":"YES","probability":0.58},{"outcome_label":"NO","probability":0.42}],"idempotency_key":"agent-run-42:forecast:event-x:v1"}}
```

5. `decision.add` — record the actual action (`buy`, `sell`, `hold`, `skip`, etc. per schema), rationale, tags, and optional strategy linkage.

```json
{"tool":"decision.add","args":{"instrument_id":"ins_...","thesis_id":"ths_...","forecast_id":"fcst_...","type":"actual_enter","side":"yes","quantity":100,"price":0.62,"tags":["spread-discipline"],"idempotency_key":"agent-run-42:decision:event-x"}}
```

6. `outcome.add` — resolve the instrument when the result is known. This enables scoring and later review.

```json
{"tool":"outcome.add","args":{"instrument_id":"ins_...","outcome_label":"NO","outcome_value":0,"status":"resolved_final","resolved_at":"2026-06-30T00:00:00Z","idempotency_key":"agent-run-42:outcome:event-x"}}
```

7. `memory.recall` — before writing the next thesis, retrieve relevant reflections, observations, and playbook rules by instrument or strategy context.

```json
{"tool":"memory.recall","args":{"context":{"kind":"strategy","id":"str_..."},"node_types":["observation","reflection","playbook_rule"],"k":10,"max_chars":6000,"compact":true}}
```

8. `memory.reflect` — after the outcome, write the lesson and bind it to the row it is about. Prefer this safe helper over raw `memory.retain` for retrospective learning.

```json
{"tool":"memory.reflect","args":{"target":{"kind":"decision","id":"dec_..."},"body":"The skip was correct: quoted edge disappeared after fees and spread.","importance":7,"idempotency_key":"agent-run-42:reflection:event-x"}}
```

9. `playbook.propose_version` — when a reflection should change future procedure, propose a new playbook version anchored to the reflection node.

```json
{"tool":"playbook.propose_version","args":{"playbook_id":"pbk_...","provenance_reflection_node_id":"mem_...","description":"Require explicit spread-adjusted edge before acting.","idempotency_key":"agent-run-42:playbook:event-x"}}
```

## 3. Patterns

- Idempotency keys: provide `idempotency_key` on every write. A retry with the same semantic payload replays safely; a retry with the same key but different payload returns `IDEMPOTENCY_CONFLICT`. Use stable keys such as `<run-id>:<tool>:<external-market-id>:<version>`.
- `_dry_run`: set `"_dry_run": true` on supported write calls to validate and preview without committing. The envelope echoes meta dry_run.
- `_confirm`: use `"_confirm": true` only when a schema or tool description requires explicit confirmation for a risky path. If absent from a tool schema, do not invent it.
- Envelope handling: success has `data` plus `meta`; errors have code, message, details, and `meta`. See [contracts.md](./architecture/contracts.md) for the canonical shape.

Error code taxonomy, with one recovery example per code:

- `VALIDATION_ERROR`: field shape or enum is invalid; fix the payload, e.g. change an unsupported outcome `status` to a value from `tool.schema`.
- `NOT_FOUND`: referenced row/tool does not exist; recall/list/show the parent object or call `tool.schema` for tool discovery.
- `IDEMPOTENCY_CONFLICT`: same key, different payload; either retry the original payload or choose a new key for a new semantic event.
- `UNSUPPORTED_CAPABILITY`: requested feature is registered but intentionally deferred; fall back to the MVP manual loop.
- `STORAGE_ERROR`: local database or filesystem operation failed; stop and surface the journal path and envelope to the operator.
- `SCORING_UNSUPPORTED`: score kind is not implemented for the forecast/outcome shape; record the outcome but do not expect a score.
- `SCORING_NOT_READY`: score cannot be computed yet; wait until `outcome.add` or the required resolution fields are present.
- `INVARIANT_VIOLATION`: journal state violates an internal consistency rule; stop automated writes and ask for repair/audit.
- `MARKET_NOT_RESOLVED`: resolution was requested before final market outcome; defer `outcome.add` or use a non-final status allowed by schema.
- `MARKET_AMBIGUOUS`: supplied outcome criteria/result is ambiguous; add clearer source text or resolve manually before scoring.

## 4. Common pitfalls

- `late_recorded` forecasts: if `forecast.add` is recorded after an outcome/resolution timestamp, Trade Trace keeps it for audit but marks it as late. Do not use late forecasts as evidence of prospective calibration.
- Status enum gotchas: outcome and playbook/adherence statuses are closed enums. Always inspect `tool.schema` instead of guessing strings such as `resolved`, `done`, or `n/a`.
- `sample_warning` meaning: reports may include `sample_warning` when the sample is too small or filtered to support strong conclusions. Treat it as a caution label, not a failure.
- Tool arguments vs transport metadata: for stdio MCP, set `MCP_ACTOR_ID`; for CLI, use `--actor-id`. Do not assume putting `actor_id` inside every `args` object changes the envelope actor unless `tool.schema` explicitly includes that field.
- Reflection targeting: `memory.reflect` target kinds are constrained. Use row-backed targets such as `decision`, `forecast`, `outcome`, `instrument`, `strategy`, or `playbook_version` as accepted by schema.

## 5. Drilldown

Use `tool.schema` for self-discovery instead of relying on stale examples. Omit `tool` to list the catalog, or pass a registered tool name to get description, CLI invocation, examples, and metadata requirements.

```json
{"tool":"tool.schema","args":{}}
```

```json
{"tool":"tool.schema","args":{"tool":"forecast.add"}}
```

For validation, compare the loop against PRD §10 dogfood criteria: the agent should create a complete journal trail, resolve outcomes, review reports, write reflections, update a playbook when warranted, and recall those lessons before the next decision.
