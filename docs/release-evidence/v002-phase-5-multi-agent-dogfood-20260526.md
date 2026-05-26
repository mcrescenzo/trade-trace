# v0.0.2 Phase 5 multi-agent Claude Code dogfood evidence — 2026-05-26

## Scope

Bead `trade-trace-2gyc`: two-session Phase 5 multi-agent contract-mode dogfood through Claude Code + `trade-trace-mcp` against one fresh shared throwaway journal.

Sanitization: this artifact intentionally omits raw RPC URLs, endpoint slugs/keys, bearer tokens, raw response bodies, credential file contents, wallet/private data, and secrets. `.env.gate7.local` was read only in memory to configure the throwaway journal. Temporary MCP configs under `/tmp` contained only `TRADE_TRACE_HOME` and `MCP_ACTOR_ID`; live endpoint values were persisted only in the throwaway journal config table and are not copied here.

## Preflight findings

- Repo/worktree at start: commit `7c849c53ec17116e54646b6de1f3ac73a66b1c91`; dirty tree contained unrelated untracked `docs/architecture/autonomous-trader-substrate.md`, left untouched.
- Claude Code CLI: `2.1.150 (Claude Code)`.
- Files inspected:
  - `docs/LIVE_TEST_CHARTER.md`
  - `docs/release-evidence/v002-phase-5-single-agent-dogfood-20260526.md`
  - tool schemas for `memory.retain`, `memory.recall`, `forecast.add`, `decision.add`, `market.bind`, `snapshot.fetch`
- MCP server/tool path under test: project script `trade-trace-mcp = "trade_trace.mcp_server:serve_stdio_main"` via Claude strict MCP config.
- Public market input: Gamma id `540844`, conditionId `0xbb57ccf5853a85487bc3d83d04d669310d28c6c810758953b9d9b91d1aee89d2`, question `Will bitcoin hit $1m before GTA VI?`.

## Throwaway setup

- Shared throwaway `TRADE_TRACE_HOME`: `/home/hermes/.hermes/profiles/primary/home/.trade-trace-gate7-preflight-v002/multi-agent-20260526T192838Z`.
- Temporary Claude MCP configs:
  - Actor A: `/tmp/trade-trace-p5-multi-A-20260526T192838Z.json`
  - Actor B: `/tmp/trade-trace-p5-multi-B-20260526T192838Z.json`
- MCP actors:
  - `agent:p5multiA`
  - `agent:p5multiB`
- Preconfigured journal steps (sanitized):
  - `journal.init` -> ok
  - `journal.config_set network.polymarket.enabled=true` -> ok, idempotency key `p5-multi-20260526T192838Z-config-enabled`
  - `journal.config_set network.polymarket.gamma_base_url=<omitted>` -> ok, idempotency key `p5-multi-20260526T192838Z-config-gamma`
  - `journal.config_set network.polymarket.polygon_rpc_url=<omitted>` -> ok, idempotency key `p5-multi-20260526T192838Z-config-rpc`

## Claude Code session invocations

Both sessions were launched as concurrent background processes sharing the same throwaway journal:

- Actor A shape: `claude -p <sanitized Actor A prompt> --mcp-config /tmp/trade-trace-p5-multi-A-20260526T192838Z.json --strict-mcp-config --max-turns 40 > /tmp/trade-trace-p5-multi-A-20260526T192838Z.out 2> /tmp/trade-trace-p5-multi-A-20260526T192838Z.err`
- Actor B shape: `claude -p <sanitized Actor B prompt> --mcp-config /tmp/trade-trace-p5-multi-B-20260526T192838Z.json --strict-mcp-config --max-turns 40 > /tmp/trade-trace-p5-multi-B-20260526T192838Z.out 2> /tmp/trade-trace-p5-multi-B-20260526T192838Z.err`
- Exit status: Actor A `0`; Actor B `0`.
- Stderr captures: Actor A empty; Actor B empty.

## Scenario results

| Step | Actor A | Actor B |
|---|---|---|
| `journal.status` start/mid/final | PASS, stable package `0.0.2`, schema `15`, outbound on | PASS, stable package `0.0.2`, schema `15`, outbound on |
| `market.bind` | PASS, market `mkt_VYClGlUR3YE-Ta1Y`; requested caller key not surfaced by schema; event used auto idempotency | PASS, same market `mkt_VYClGlUR3YE-Ta1Y`; requested caller key not surfaced by schema; event used same auto idempotency |
| `snapshot.fetch` | NOT EXECUTED SUCCESSFULLY through Actor A; Claude reported MCP schema did not expose required `idempotency_key`/allow-no-idempotency properties | PASS after validation retries; snapshot `snp_8R98XW99oYUPrC2s`, public market mid/implied probability approx. `0.4925`; raw response omitted |
| `forecast.add` | PASS, forecast `fc_XgHMnUyDpjOSljZX`, thesis `th_Too0TZRV3TWYwcAR`, key `p5-multi-a-forecast-20260526T192838Z` | PASS, forecast `fc_uH0eP9cPJZ5TcwNs`, thesis `th_GmdSUlo_eT_wMltR`, key `p5-multi-b-forecast-20260526T192838Z` |
| `decision.add` | PASS, watch decision `dec_UuJgiaYj7hkkQtLN`, key `p5-multi-a-decision-20260526T192838Z` | PASS, watch decision `dec_1XuEKD3XZvFLEoVb`, key `p5-multi-b-decision-20260526T192838Z` |
| `memory.retain` | PASS, memory `mem_YnoUtK78z0dhNQ6N`, key `p5-multi-a-memory-20260526T192838Z`, phrase `PHASE5-CROSS-SESSION-A-ORCHID` | PASS, memory `mem_1VXJrVu8NtQG0ao2`, key `p5-multi-b-memory-20260526T192838Z`, phrase `PHASE5-CROSS-SESSION-B-TOPAZ` |
| `memory.recall` / recall.search | PASS for cross-session visibility: recall `rcl_mh-4cQiQURXU1oph` returned Actor B memory `mem_1VXJrVu8NtQG0ao2` and Actor A memory `mem_YnoUtK78z0dhNQ6N` | PARTIAL: two early recall events for Actor A's phrase occurred before Actor A memory was discoverable and returned only Actor B's own observation |
| `signal.scan` checkpoint | Direct CLI checkpoint on same journal after both sessions: PASS, `emitted_count=0` | Direct CLI checkpoint on same journal after both sessions: PASS, `emitted_count=0` |

The public market remains open; no outcome/resolution was fabricated.

## Independent journal inspection after both Claude sessions

Direct sanitized checks against the same throwaway home:

- `TRADE_TRACE_HOME=<throwaway> tt --actor-id cli:p5-verify journal status` -> `ok=True`, `schema_version=15`, `package_version=0.0.2`, `outbound_network_active=True`, Polymarket adapter enabled and endpoints configured as booleans only.
- `TRADE_TRACE_HOME=<throwaway> tt --actor-id cli:p5-verify signal scan` -> `ok=True`, `emitted_count=0`, `kinds_scanned=["unscored_forecast"]`.
- SQLite count inspection (no secrets printed): `events=12`, `markets=1`, `forecasts=2`, `decisions=2`, `memory_nodes=2`, `memory_recall_events=3`.
- Error string scan across textual SQLite columns: `single_writer_lock`, `STORAGE_ERROR`, and `ADAPTER_PROTOCOL_ERROR` hits all `0`.
- Memory phrase proof:
  - `PHASE5-CROSS-SESSION-A-ORCHID` -> `mem_YnoUtK78z0dhNQ6N`, actor `agent:p5multiA`.
  - `PHASE5-CROSS-SESSION-B-TOPAZ` -> `mem_1VXJrVu8NtQG0ao2`, actor `agent:p5multiB`; Actor A's memory also referenced the B phrase after recall.
- Recall event proof:
  - Actor B created two early recall events querying `PHASE5-CROSS-SESSION-A-ORCHID`.
  - Actor A created recall event querying both cross-session phrases; Claude summary reports returned Actor B memory `mem_1VXJrVu8NtQG0ao2` plus Actor A memory `mem_YnoUtK78z0dhNQ6N`.

## Idempotency key summary

Caller-supplied scenario keys observed in `events` were unique:

- `p5-multi-a-forecast-20260526T192838Z`
- `p5-multi-a-decision-20260526T192838Z`
- `p5-multi-a-memory-20260526T192838Z`
- `p5-multi-b-snapshot-20260526T192838Z`
- `p5-multi-b-forecast-20260526T192838Z`
- `p5-multi-b-decision-20260526T192838Z`
- `p5-multi-b-memory-20260526T192838Z`

However, `market.bind` did not expose/surface caller idempotency through the MCP schema in this run, and both sessions wrote/shared the same auto-derived idempotency key for the same public market bind:

- `auto:6469596ff344915ef55d92c16a08ca12` count `2`

This is treated as **NOT MET** for the strict Phase 5 criterion “Idempotency keys uncollided across concurrent sessions,” even though the durable market row converged to one market and the caller-supplied forecast/decision/memory keys did not collide.

## Observed errors/signals

- `single_writer_lock` emissions: `0` observed. No retry was needed; no lock contention was induced or claimed.
- Non-`single_writer_lock` `STORAGE_ERROR`: `0` observed in Claude stdout/stderr and independent SQLite text scan.
- `ADAPTER_PROTOCOL_ERROR`: `0` observed in Claude stdout/stderr and independent SQLite text scan.
- Claude-reported validation errors:
  - Actor B initial `snapshot.fetch` missing `idempotency_key`, then unsupported non-`now` timestamp; recovered by supplying the key and using `at=now`.
  - Actor A reported `snapshot.fetch` could not be made successful because the advertised MCP schema did not expose required idempotency controls; Actor A continued with unanchored forecast.
- Final direct `signal.scan`: ok; `emitted_count=0`.

## Acceptance mapping

| Phase 5 criterion | Result | Evidence |
|---|---:|---|
| 1. Every `single_writer_lock` emission recovers within ONE documented retry | PASS / N/A | `0` `single_writer_lock` emissions observed; no recovery path needed. |
| 2. Zero non-`single_writer_lock` `STORAGE_ERROR` | PASS | No `STORAGE_ERROR` observed in Claude stdout/stderr or independent SQLite text scan. |
| 3. Zero `ADAPTER_PROTOCOL_ERROR` | PASS | No `ADAPTER_PROTOCOL_ERROR` observed in Claude stdout/stderr or independent SQLite text scan. |
| 4. Idempotency keys uncollided across concurrent sessions | **NOT MET** | Caller scenario keys for forecast/decision/memory/snapshot were unique, but `market.bind` produced duplicate auto-derived key `auto:6469596ff344915ef55d92c16a08ca12` count `2` across the two sessions. |
| 5. `recall.search` / `memory.recall` returns cross-session results | PASS | Actor A recall `rcl_mh-4cQiQURXU1oph` returned Actor B memory `mem_1VXJrVu8NtQG0ao2` plus Actor A memory. |
| 6. Final `tt journal status` reports a clean state | PASS | Direct final `journal.status` returned `ok=True`, schema `15`, package `0.0.2`, outbound active, adapter configured. |

## Outcome

Phase 5 multi-agent dogfood is **BLOCKED / NOT MET** under the exact LIVE_TEST_CHARTER criteria because idempotency keys were not fully uncollided across concurrent sessions. The concrete observed issue is limited to `market.bind` through the Claude MCP path: caller idempotency was requested in the prompts but not surfaced by the advertised schema, resulting in duplicate auto-derived keys for the shared public market bind.

## Proposed follow-ups for parent/controller

- Create/wire a follow-up for MCP schema/idempotency coverage: ensure every retryable write exposed to Claude Code, including `market.bind` and `snapshot.fetch`, advertises and accepts `idempotency_key` (and/or documented allow-no-idempotency controls where appropriate) so concurrent sessions can prove uncollided caller-supplied keys end to end.
- If duplicate auto-derived idempotency for idempotent `market.bind` on the same external market is intended, update the Phase 5 charter/evidence rule or the event projection to distinguish intentional idempotent convergence from key collision. Until then, this run records the criterion as NOT MET.

## Validation commands run

- `git status --short && git rev-parse HEAD`
- `claude --version`
- `tt tool schema --tool <tool>` for `memory.retain`, `memory.recall`, `forecast.add`, `decision.add`, `market.bind`, `snapshot.fetch`
- Python preconfiguration script reading `.env.gate7.local` in memory without printing values
- Two concurrent Claude invocations shown above
- `TRADE_TRACE_HOME=<throwaway> tt --actor-id cli:p5-verify journal status`
- `TRADE_TRACE_HOME=<throwaway> tt --actor-id cli:p5-verify signal scan`
- SQLite count/idempotency/error-string inspection with no raw config values printed

## Caveats

- This is failure/blocker evidence, not Phase 5 pass evidence.
- No Beads were mutated, and no commit/push was performed by this subagent.
- Unrelated untracked `docs/architecture/autonomous-trader-substrate.md` was left untouched.
