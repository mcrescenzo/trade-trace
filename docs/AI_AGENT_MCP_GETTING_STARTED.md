# AI agent MCP getting started

This is the short operating guide for AI agents connecting to Trade Trace over MCP.

Trade Trace is a local journal, memory, and calibration substrate for trading agents. It records decisions and outcomes; by default it performs no outbound market fetches. The optional Polymarket adapter is disabled until explicitly configured, and even then only explicit agent calls such as `market.refresh`, `snapshot.fetch`, and `outcome.fetch` perform network I/O. Trade Trace never executes trades, signs orders, holds broker credentials, or gives financial advice.

## 1. Install the MCP server

From a checkout:

```bash
python3 -m pip install -e .
export TRADE_TRACE_HOME="$HOME/.trade-trace"
tt journal init
```

From a package install after publication:

```bash
python3 -m pip install trade-trace
export TRADE_TRACE_HOME="$HOME/.trade-trace"
tt journal init
```

Requirements:

- Python 3.11+
- SQLite with FTS5
- MCP support is included in the base package; the `[mcp]` extra is a back-compat install alias with no additional dependencies.

## 2. Configure your MCP client

Trade Trace is stdio-only. Configure the client to launch `trade-trace-mcp` as a local command. Do not configure an HTTP, SSE, websocket, or TCP URL.

Generic MCP config shape:

```json
{
  "mcpServers": {
    "trade-trace": {
      "command": "trade-trace-mcp",
      "args": [],
      "env": {
        "TRADE_TRACE_HOME": "/absolute/path/to/.trade-trace",
        "MCP_ACTOR_ID": "agent:your-agent-name"
      }
    }
  }
}
```

Use an absolute `TRADE_TRACE_HOME` if the client does not expand `$HOME` or `${HOME}`.

If the client cannot find the command, replace `command` with the absolute path from:

```bash
command -v trade-trace-mcp
```

Client-specific walkthroughs:

- Claude Code: [`CLAUDE_CODE.md`](./CLAUDE_CODE.md)
- Claude Desktop: [`CLAUDE_DESKTOP.md`](./CLAUDE_DESKTOP.md)
- Cursor / Windsurf / Cline: [`IDE_MCP_SETUP.md`](./IDE_MCP_SETUP.md)

## 3. Stdio rules

- Stdout is reserved for MCP JSON-RPC. Do not wrap `trade-trace-mcp` with scripts that print banners, logs, progress bars, or diagnostics to stdout.
- If a wrapper is unavoidable, send diagnostics to stderr only.
- Trade Trace does not open a network listener for MCP.
- Keep secrets out of the MCP config. Trade Trace does not need API keys, seed phrases, private keys, exchange credentials, or broker tokens.

## 4. Actor identity

Set `MCP_ACTOR_ID` in the MCP server environment:

```bash
export MCP_ACTOR_ID="agent:research-bot"
```

Valid actor IDs match:

```text
(agent|cli|import|system):<name>
```

where `<name>` is 1-64 characters from letters, numbers, `.`, `_`, and `-`, starting with a letter or number.

For stdio MCP, actor identity comes from `MCP_ACTOR_ID`; do not put `actor_id` in ordinary tool arguments unless `tool.schema` for that tool explicitly includes it.

If `MCP_ACTOR_ID` is unset, the server uses `agent:mcp-default`.

## 5. First verification calls

After configuring the client, verify this sequence before journaling real decisions:

1. Ask the client to list MCP tools. You should see `trade-trace` tools such as `journal.status`, `tool.schema`, `market.bind`, `market.refresh`, `snapshot.add`, `snapshot.fetch`, `snapshot.fetch_series`, `forecast.add`, `decision.add`, `resolution.add`, `outcome.fetch`, `memory.recall`, and report tools. Do not rely on a fixed tool count: `tool.schema` is registry-generated and is the authoritative list of currently exposed tools.
2. Call `journal.status`.
3. Call `tool.schema` with no arguments to list the current registry.
4. Call `tool.schema` for the first write you intend to use, for example:

```json
{
  "tool": "forecast.add"
}
```

Use the returned JSON Schema and examples as the source of truth. Do not rely on memory or stale snippets for enum values, required fields, or payload shape.

## 6. Envelope contract

Every tool result is a Trade Trace envelope inside the MCP tool result's structured content.

Success:

```json
{
  "ok": true,
  "data": {},
  "meta": {
    "tool": "journal.status",
    "actor_id": "agent:research-bot",
    "request_id": "...",
    "contract_version": "1.0"
  }
}
```

Error:

```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "...",
    "details": {}
  },
  "meta": {
    "tool": "forecast.add",
    "actor_id": "agent:research-bot",
    "request_id": "...",
    "contract_version": "1.0"
  }
}
```

Branch on `error.code`, not `error.message`. See [`architecture/contracts.md`](./architecture/contracts.md) for the full contract.

Common recoveries:

- `VALIDATION_ERROR`: inspect `tool.schema`, fix field names/enums/types, retry with the same idempotency key only if the semantic event is unchanged.
- `NOT_FOUND`: create or recall the referenced parent row first.
- `IDEMPOTENCY_CONFLICT`: same idempotency key, different payload; retry the original payload or use a new key for a new semantic event.
- `INVARIANT_VIOLATION`: stop automated writes and surface the payload/envelope for review.
- `UNSUPPORTED_CAPABILITY`: the tool exists but this configuration does not support that path; use the manual MVP loop instead.

## 7. Safe write pattern

For every write tool:

1. Call `tool.schema` for that exact tool.
2. Build the payload from the schema and current IDs.
3. Include an `idempotency_key`.
4. Use `_dry_run: true` when you want validation and generated preview IDs without persistence.
5. Remove `_dry_run` only when ready to commit the event.
6. Parse the envelope and save returned IDs from `data` for later calls.

Idempotency rule:

- Same key + same semantic payload: safe replay, with `meta.idempotent_replay=true` when applicable.
- Same key + different semantic payload: `IDEMPOTENCY_CONFLICT`.

Suggested idempotency key shape:

```text
<agent-run-id>:<tool-name>:<external-market-id-or-local-subject>:<version>
```

Example:

```text
run-20260519-001:forecast.add:polymarket-event-123:v1
```

## 8. Minimal journal loop

A useful agent loop is ordered so later records point back to earlier evidence.

1. `journal.init` — initialize the local journal if not already initialized.
2. `market.bind` — create or identify the market metadata row.
3. Optional adapter loop, only when explicitly enabled/configured: `market.refresh`, `snapshot.fetch`, and `outcome.fetch`. Otherwise use manual `snapshot.add` / `resolution.add`.
4. `snapshot.add` — record caller-supplied market state when relevant.
5. `forecast.add` — commit binary probabilities before outcome resolution.
6. `decision.add` — record the actual trade/skip/hold decision and rationale.
7. `resolution.add` — record final outcome; scoring runs when prerequisites are met.
8. `report.work_queue`, `agent.next_actions`, and review/report tools — inspect incomplete local obligations and deterministic feedback.
9. `memory.reflect` — write an outcome-linked lesson.
10. `playbook.upsert` and `playbook.record_adherence` — maintain process rules and adherence rows.
11. `memory.recall` — before the next forecast/decision, retrieve relevant prior lessons.

For exact fields and examples, call `tool.schema` for each tool immediately before using it.

## 9. First dry-run example

This example validates a market binding write without persisting it:

```json
{
  "external_id": "paper-venue:event-123",
  "source": "manual",
  "state": "open",
  "mechanism": "clob",
  "title": "Paper market event",
  "idempotency_key": "run-20260519-001:market.bind:paper-event:v1",
  "_dry_run": true
}
```

Call it through MCP as tool `market.bind`. Expected envelope properties:

- `ok: true`
- `meta.tool: "market.bind"`
- `meta.actor_id` equals your `MCP_ACTOR_ID`
- `meta.dry_run: true`
- `data.id` contains the would-be market ID

Then repeat without `_dry_run` when you want to persist the event.

## 10. Security and scope boundaries

Agents must not send Trade Trace:

- broker credentials
- API keys
- wallet seeds or private keys
- exchange session tokens
- order-signing material
- raw `.env` files or credential stores

Trade Trace ignores credential-shaped write arguments and rejects credential-looking MCP schema exposure, but agents should still avoid sending secrets at all.

Trade Trace performs no outbound market fetches by default. Optional Polymarket adapter calls are fail-closed unless explicitly enabled and configured; when enabled, only explicit calls (`market.refresh`, `snapshot.fetch`, `outcome.fetch`) perform adapter I/O. There is no background fetch scheduler.

## 11. Troubleshooting

`trade-trace-mcp` not found:

- Run `command -v trade-trace-mcp` in the same environment the client uses.
- Use the absolute path in the MCP config.
- Confirm the package is installed (MCP is bundled by default): `python3 -m pip install -e .`.

Tool list works but calls fail with actor validation:

- Set `MCP_ACTOR_ID` to a valid value such as `agent:claude-code` or `agent:research-bot`.

Tool call returns `VALIDATION_ERROR`:

- Call `tool.schema` for that tool.
- Check field names. For binary forecasts, outcome entries use `outcome_label`, not `label`.
- Check timestamp format: use UTC ISO-8601, for example `2026-06-30T00:00:00Z`.

Nothing appears persisted:

- Confirm you removed `_dry_run`.
- Confirm every client is using the same absolute `TRADE_TRACE_HOME`.
- Run `journal.status` and inspect the reported home/database path.

Client hangs or protocol errors appear:

- Make sure no wrapper prints to stdout.
- Run `trade-trace-mcp` directly to confirm it starts and waits for JSON-RPC input.
- Send logs to stderr, not stdout.
