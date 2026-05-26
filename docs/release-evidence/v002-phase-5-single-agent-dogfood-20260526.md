# v0.0.2 Phase 5 single-agent Claude Code dogfood evidence — 2026-05-26

## Scope

Bead `trade-trace-39dt`: attempted the approved single-agent Phase 5 live dogfood scenario through one Claude Code session against the `trade-trace-mcp` stdio server.

Sanitization: this artifact intentionally omits raw RPC URLs, endpoint keys/slugs, bearer tokens, raw response bodies, credential file contents, wallet/private data, and secrets. `.env.gate7.local` was read only in memory to configure the throwaway journal. The MCP config written under `/tmp` contained only `TRADE_TRACE_HOME` and `MCP_ACTOR_ID`; the raw RPC URL was persisted only in the throwaway journal config table required for the live adapter and is not copied here.

## Preflight findings

- Repo/worktree at start: clean at commit `a59235715dcd6dc8248b30b5b2b756a578443aab`.
- Claude Code CLI: `2.1.150 (Claude Code)`.
- Files inspected:
  - `docs/LIVE_TEST_CHARTER.md`
  - `docs/release-evidence/v002-gate-7-live-20260526.md`
  - `docs/release-evidence/v002-gate-7-sanitization-sweep-20260526.md`
  - `src/trade_trace/mcp_server.py`
  - `pyproject.toml`
  - tool schemas via `tt tool schema --tool ...`
- MCP server/tool path under test: project script `trade-trace-mcp = "trade_trace.mcp_server:serve_stdio_main"`.
- Public market input: Gamma id `540844`, conditionId `0xbb57ccf5853a85487bc3d83d04d669310d28c6c810758953b9d9b91d1aee89d2`, question `Will bitcoin hit $1m before GTA VI?`.

## Throwaway setup

- Throwaway `TRADE_TRACE_HOME`: `/home/hermes/.hermes/profiles/primary/home/.trade-trace-gate7-preflight-v002/single-agent-20260526T175408Z`.
- Temporary Claude MCP config: `/tmp/trade-trace-p5-mcp-20260526T175408Z.json`.
- Preconfigured journal steps (sanitized):
  - `journal.init` -> ok
  - `journal.config_set network.polymarket.enabled=true` -> ok, idempotency key `p5-20260526T175408Z-config-enabled`
  - `journal.config_set network.polymarket.gamma_base_url=<omitted>` -> ok, idempotency key `p5-20260526T175408Z-config-gamma`
  - `journal.config_set network.polymarket.polygon_rpc_url=<omitted>` -> ok, idempotency key `p5-20260526T175408Z-config-rpc`

## Claude Code session result

Attempted exactly one Claude Code print-mode session with:

- `claude -p <sanitized prompt> --mcp-config /tmp/trade-trace-p5-mcp-20260526T175408Z.json --strict-mcp-config --max-turns 20`
- stdout capture: `/tmp/trade-trace-p5-claude-20260526T175408Z.out`
- stderr capture: `/tmp/trade-trace-p5-claude-20260526T175408Z.err`

Result: **BLOCKED / NOT MET** before any scenario MCP tool call executed.

Sanitized Claude Code error:

```text
API Error: 400 tools.12.custom.input_schema: input_schema does not support oneOf, allOf, or anyOf at the top level
```

The stderr capture was empty. The stdout capture contained only the sanitized API error above. This appears to be a Claude Code/tool-schema compatibility failure when registering the `trade-trace-mcp` tool catalog; `forecast.add` advertises a top-level `anyOf` schema branch in the registry-derived MCP schema. No raw endpoint/config values or live adapter response bodies were printed.

Because the Claude Code MCP session failed during tool registration, the required realistic scenario (`journal.status` start/mid/end, `signal.scan`, `market.bind`, `snapshot.fetch`, `forecast.add`, `decision.add`, `memory.recall`) did **not** run through Claude Code. Per stop rules, the bead acceptance is not satisfied by this attempt.

## Independent post-attempt checks

The throwaway journal was inspected directly after the failed Claude Code session to confirm scope and cleanliness.

- `TRADE_TRACE_HOME=<throwaway> tt journal status` -> ok
  - `db_exists=true`
  - `schema_version=15`
  - `package_version=0.0.2`
  - `outbound_network_active=true`
  - adapter state: Polymarket enabled; Gamma and Polygon endpoints configured as booleans only; `cached_markets_count=0`; `last_successful_fetch_at=null`
- `TRADE_TRACE_HOME=<throwaway> tt signal scan` -> ok
  - `emitted_count=0`
  - `kinds_scanned=["unscored_forecast"]`

No scenario writes were made beyond the preconfiguration writes above.

## Observed errors/signals

- Claude Code/MCP catalog registration error: one sanitized API error, shown above.
- `single_writer_lock` emissions: `0` observed.
- Non-`single_writer_lock` `STORAGE_ERROR`: `0` observed in captured outputs.
- `ADAPTER_PROTOCOL_ERROR`: `0` observed in captured outputs.
- `signal.scan` emitted signals after failed session: `0`.

## Idempotency key summary

Used only during safe preconfiguration:

- `p5-20260526T175408Z-config-enabled`
- `p5-20260526T175408Z-config-gamma`
- `p5-20260526T175408Z-config-rpc`

The scenario keys requested for Claude (`p5-20260526T175408Z-claude-*`) were not used because the Claude Code session failed during MCP tool registration.

## Recall proof

NOT MET. `memory.recall` / recall.search proof from the Claude-run scenario could not be produced because no Claude MCP scenario tool calls executed.

## Outcome/resolution caveat

The public market `540844` is open. The intended scenario would not force a false resolution; it would either skip `outcome.fetch` for the unresolved market or record a safe local/manual path only if supported. This was not reached due to the MCP schema registration blocker.

## Acceptance mapping

| Criterion | Result | Evidence |
|---|---:|---|
| Boot one Claude Code session against `trade-trace-mcp` pointed at fresh `TRADE_TRACE_HOME` | NOT MET | Session invoked with strict MCP config and fresh home, but Claude Code failed before tool use with `input_schema does not support oneOf, allOf, or anyOf at the top level`. |
| Run realistic scenario: forecast -> decision -> memory/recall against market `540844` | NOT MET | No scenario MCP calls executed. |
| Journal status start/mid/end through scenario | NOT MET | Direct post-attempt `journal.status` passed; Claude-run start/mid/end did not execute. |
| Periodic `signal.scan` or equivalent | NOT MET | Direct post-attempt `signal.scan` passed; Claude-run checkpoint did not execute. |
| `single_writer_lock` emissions recover within one documented retry | N/A for this single-agent failed setup | `0` emissions observed; scenario did not run. |
| Zero non-`single_writer_lock` `STORAGE_ERROR` | PASS for captured attempt | No `STORAGE_ERROR` observed in captured outputs. |
| Zero `ADAPTER_PROTOCOL_ERROR` | PASS for captured attempt | No `ADAPTER_PROTOCOL_ERROR` observed in captured outputs. |
| Idempotency keys unique within session | PASS for preconfiguration only; NOT MET for scenario | Three preconfiguration keys were unique; Claude scenario keys were not used. |
| `memory.recall` returns evidence from this session | NOT MET | No memory write/recall occurred. |
| Final journal status clean | PASS for post-attempt journal; NOT MET for scenario completion | Direct status ok after failed session; scenario completion did not occur. |
| Sanitized evidence only | PASS | Evidence omits raw RPC URL, keys/slugs, env contents, credentials, and raw response bodies. |

## Follow-up proposed for parent/controller

Create/wire a follow-up bug for Claude Code MCP schema compatibility: the registry-derived MCP catalog includes at least one tool with a top-level `anyOf` JSON schema (`forecast.add`), and Claude Code 2.1.150 rejects MCP tools whose `custom.input_schema` contains top-level `oneOf`, `allOf`, or `anyOf`. A safe fix could be either to flatten/wrap MCP-exposed schemas for Claude-compatible clients or provide a documented MCP catalog compatibility mode that preserves runtime validation while advertising a Claude-acceptable input schema.

## Validation commands run

- `git status --short && git rev-parse HEAD && claude --version`
- `tt tool schema --tool <tool>` for `journal.init`, `journal.status`, `journal.config_set`, `market.bind`, `snapshot.fetch`, `forecast.add`, `thesis.add`, `decision.add`, `memory.retain`, `memory.recall`, `signal.scan`, `outcome.add`, `outcome.fetch`
- Python preconfiguration script reading `.env.gate7.local` in memory without printing values
- `claude -p <sanitized prompt> --mcp-config /tmp/trade-trace-p5-mcp-20260526T175408Z.json --strict-mcp-config --max-turns 20 > /tmp/trade-trace-p5-claude-20260526T175408Z.out 2> /tmp/trade-trace-p5-claude-20260526T175408Z.err`
- `TRADE_TRACE_HOME=<throwaway> tt journal status`
- `TRADE_TRACE_HOME=<throwaway> tt signal scan`
- Secret/sanitization scan over tracked files using raw RPC URL and endpoint slug derived in memory from `.env.gate7.local` -> exact raw RPC URL hits `0`; endpoint slug hits `0`. A simple token-assignment string count over all tracked files returned pre-existing documentation/test false positives; this evidence file specifically had exact raw RPC URL hits `0`, endpoint slug hits `0`, raw `http://`/`https://` URL count `0`, and no credential value copied.
- `git diff --check` -> pass (no output).
- `git status --short` -> only `?? docs/release-evidence/v002-phase-5-single-agent-dogfood-20260526.md`.

## Caveats

- This is failure/blocker evidence, not Phase 5 pass evidence.
- No Beads were mutated, and no commit/push was performed by this subagent.


---

## Rerun after MCP schema compatibility fix — 2026-05-26T19:20:34Z

### Rerun commit/SHA and dirty state

- Commit under test: `a59235715dcd6dc8248b30b5b2b756a578443aab`.
- Worktree context at rerun start was intentionally dirty with the controller-provided MCP schema fix files still uncommitted: `M src/trade_trace/mcp_server.py`, `?? tests/contracts/test_mcp_schema_compat.py`, this evidence artifact untracked, and unrelated `?? docs/architecture/autonomous-trader-substrate.md` left untouched.
- No Beads were mutated, and no commit/push was performed.

### Throwaway setup

- Fresh `TRADE_TRACE_HOME`: `/home/hermes/.hermes/profiles/primary/home/.trade-trace-gate7-preflight-v002/single-agent-rerun-20260526T192034Z`.
- Temporary Claude MCP config: `/tmp/trade-trace-p5-mcp-rerun-20260526T192034Z.json`.
- MCP server/tool path under test: `trade-trace-mcp` (`trade_trace.mcp_server:serve_stdio_main`), started by Claude Code via strict MCP config.
- MCP config contained only `TRADE_TRACE_HOME` and `MCP_ACTOR_ID`; live endpoint values were configured only into the throwaway journal from `.env.gate7.local` read in memory and are omitted here.
- Public market: Gamma id `540844`, conditionId `0xbb57ccf5853a85487bc3d83d04d669310d28c6c810758953b9d9b91d1aee89d2`.

### Claude Code/session evidence

- Claude Code: `2.1.150 (Claude Code)`.
- Invocation shape: `claude -p <sanitized prompt> --mcp-config /tmp/trade-trace-p5-mcp-rerun-20260526T192034Z.json --strict-mcp-config --max-turns 30 > /tmp/trade-trace-p5-claude-rerun-20260526T192034Z.out 2> /tmp/trade-trace-p5-claude-rerun-20260526T192034Z.err`.
- Claude exit: `0`.
- Stderr capture: empty.
- Schema compatibility blocker from the prior attempt did not recur; Claude registered the MCP catalog and executed tool calls.

### Scenario steps/results from Claude summary

| Step | Tool/action | Result | Sanitized evidence |
|---|---|---:|---|
| 1 | `journal.status` start | PASS | package `0.0.2`, schema `15`, outbound on, Polymarket adapter enabled |
| 2 | `signal.scan` start through MCP | CAVEAT | Claude reported `signal.scan` was not present in this MCP catalog; direct CLI checkpoint after the session passed with emissions `0` |
| 3 | `market.bind` | PASS | market id `mkt_2P4OCFQrwSKB-yhz`; state `open`; adapter-bound; public conditionId matched |
| 4 | `snapshot.fetch` | PASS after validation retries | final snapshot id `snp_5vTiFdpIUitlaiz3`; implied probability approximately `0.4925`; raw response body omitted |
| 5 | `forecast.add` | PASS | forecast id `fc_SdoFTarINtT3VQ_o`; thesis id `th__z9YRYRAuLbHrFkT`; anchor id `fsa_W_rbw4bhqpJJhwCs`; key `p5-rerun-live-forecast-1` |
| 6 | `decision.add` | PASS | decision id `dec_n7oPXX8gS8fcs_PF`; position id `pos_jdSaNcY5GdZ9C4NA`; event id `pev_kXVX60hPaw9Dp-H1`; key `p5-rerun-live-decision-1` |
| 7 | `memory.retain` | PASS | memory id `mem_s5j48eq4QXi-FlDy`; key `p5-rerun-live-memory-1` |
| 8 | `memory.recall` | PASS | recall id `rcl_C1BaaofZLeII2tbp`; returned the in-session memory node `mem_s5j48eq4QXi-FlDy` for query terms about BTC / GTA VI / Polymarket |
| 9 | `journal.status` mid | PASS | unchanged/clean per Claude summary |
| 10 | `signal.scan` mid through MCP | CAVEAT | same MCP catalog gap as start; direct CLI checkpoint after the session passed with emissions `0` |
| 11 | `journal.status` final | PASS | unchanged/clean per Claude summary |

The public market remains open; no outcome/resolution was fabricated.

### Idempotency key summary

Scenario idempotency keys observed in the throwaway journal were unique:

- `p5-rerun-live-snapshot-1`
- `p5-rerun-live-forecast-1`
- `p5-rerun-live-decision-1`
- `p5-rerun-live-memory-1`
- one auto-derived event key for `market.bind`

Preconfiguration keys were unique and scoped to this rerun timestamp:

- `p5-20260526T192034Z-config-enabled`
- `p5-20260526T192034Z-config-gamma`
- `p5-20260526T192034Z-config-rpc`

### Observed errors/signals

- `single_writer_lock` emissions: `0` observed.
- Non-`single_writer_lock` `STORAGE_ERROR`: `0` observed.
- `ADAPTER_PROTOCOL_ERROR`: `0` observed.
- Claude-reported validation errors: two `snapshot.fetch` validation handshakes before the successful call (`idempotency_key` missing, then unsupported non-`now` timestamp). These were not storage/adapter protocol errors and recovered inside the same Claude session.
- Direct post-session `tt signal scan`: ok; `emitted_count=0`; `kinds_scanned=["unscored_forecast"]`.

### Recall proof

Claude-run `memory.recall` returned recall id `rcl_C1BaaofZLeII2tbp` with the in-session memory id `mem_s5j48eq4QXi-FlDy`, written by the same Claude session via `memory.retain` under key `p5-rerun-live-memory-1`. The recall summary reported one in-scope hit with BM25/graph/temporal strategies.

### Independent journal inspection after Claude

Direct sanitized checks against the same throwaway home:

- `TRADE_TRACE_HOME=<throwaway> tt --actor-id agent:phase5-verify journal status` -> `ok=True`, `schema_version=15`, `package_version=0.0.2`, `outbound_network_active=True`, Polymarket adapter enabled.
- `TRADE_TRACE_HOME=<throwaway> tt --actor-id agent:phase5-verify signal scan` -> `ok=True`, `emitted_count=0`, `kinds_scanned=["unscored_forecast"]`.
- SQLite count inspection (no secrets printed): `events=7`, `markets=1`, `snapshots=1`, `forecasts=1`, `decisions=1`, `memory_nodes=1`, `memory_recall_events=1`.
- Idempotency keys in events were unique: `auto:6469596ff344915ef55d92c16a08ca12`, `p5-rerun-live-decision-1`, `p5-rerun-live-forecast-1`, `p5-rerun-live-memory-1`, `p5-rerun-live-snapshot-1`.

### Acceptance mapping for rerun

| Criterion | Result | Evidence |
|---|---:|---|
| Boot one Claude Code session against `trade-trace-mcp` pointed at fresh `TRADE_TRACE_HOME` | PASS | Claude strict MCP session exited `0` using fresh throwaway home and temporary config. |
| Run realistic single-agent scenario: forecast -> decision -> memory/recall against market `540844` | PASS | `market.bind`, `snapshot.fetch`, `forecast.add`, `decision.add`, `memory.retain`, and `memory.recall` succeeded. |
| Journal status at start/mid/end | PASS | Claude summary recorded start/mid/final `journal.status` success and clean final state. |
| Periodic `signal.scan` or closest canonical checkpoint | PARTIAL/CAVEAT | Claude reported `signal.scan` absent from the MCP catalog; direct post-session CLI `signal.scan` on the same journal passed with emissions `0`. |
| Every `single_writer_lock` emission recovers within one documented retry | N/A/PASS | Single-agent run observed `0` `single_writer_lock` emissions. |
| Zero non-`single_writer_lock` `STORAGE_ERROR` | PASS | None observed in Claude stdout/stderr or direct checks. |
| Zero `ADAPTER_PROTOCOL_ERROR` | PASS | None observed. |
| Idempotency keys unique within session | PASS | Event idempotency key list contained no duplicates. |
| `memory.recall` returns evidence from this session | PASS | Recall id `rcl_C1BaaofZLeII2tbp` returned memory id `mem_s5j48eq4QXi-FlDy` written in this session. |
| Final journal status clean | PASS | Claude final status clean; direct final status `ok=True`, schema `15`, package `0.0.2`. |
| Sanitized evidence only | PASS | No raw RPC URL, endpoint key/slug, bearer token, credential value, env contents, wallet/private data, or raw response bodies are included. |

### Caveats/follow-up for parent/controller

- MCP schema compatibility fix is effective for Claude Code registration and tool execution.
- `signal.scan` was available via CLI but not exposed in the Claude MCP catalog used in this run. The scenario still met the core Phase 5 storage/adapter/idempotency/recall criteria; parent should decide whether to create/wire a follow-up to expose `signal.scan` through MCP or explicitly accept `journal.status`/direct CLI `signal.scan` as the closest canonical checkpoint for this single-agent rerun.
