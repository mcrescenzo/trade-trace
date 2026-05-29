# Trade Trace

<p align="center">
  <strong>Local calibration journal for LLM prediction-market trading agents.</strong><br>
  Trade Trace is a continuity and evaluation layer for an agent's prediction-market process. It is not a trader.
</p>

<p align="center">
  <a href="https://github.com/mcrescenzo/trade-trace"><img alt="Status: pre-release" src="https://img.shields.io/badge/status-pre--release-orange"></a>
  <a href="./LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <a href="./docs/AI_AGENT_MCP_GETTING_STARTED.md"><img alt="MCP stdio" src="https://img.shields.io/badge/MCP-stdio-55d6be"></a>
  <a href="./docs/architecture/contracts.md"><img alt="JSON first" src="https://img.shields.io/badge/contracts-JSON--first-7aa7ff"></a>
  <a href="./SECURITY.md"><img alt="Local first" src="https://img.shields.io/badge/default-local--first-10243b"></a>
</p>

Trade Trace helps an LLM prediction-market agent keep an auditable local record of market context, probability forecasts, decisions, resolutions, and lessons that should carry into the next session.

It stores a local SQLite journal, scores binary prediction-market forecasts when resolutions are supplied, produces deterministic retrospective reports, and gives the agent a typed memory graph for observations, reflections, and playbook rules. Agents can use it through MCP stdio, a JSON-first CLI, and Python report/read-model functions.

Trade Trace never places trades, stores broker or wallet credentials, phones home, or gives financial advice. Its Polymarket adapter is opt-in, agent-triggered, disabled by default, and requires caller-supplied configuration; there is no default RPC endpoint.

## Why it exists

LLM trading agents can research markets and write reasoning, but process memory is fragile when it lives only in transcripts. Trade Trace makes that process inspectable:

| Agent problem | Trade Trace surface |
|---|---|
| Forecasts disappear into chat history | Forecasts become scored, queryable journal rows |
| Outcomes are remembered anecdotally | Supported binary forecasts get Brier and calibration diagnostics |
| Mistakes are free-text and hard to audit | Reports return metrics with drill-down record IDs |
| New sessions repeat old reasoning | Recall returns relevant observations, reflections, and playbook rules |
| Lessons smear across unrelated trades | Strategies scope decisions, reports, recall, and reflection |
| Retry loops duplicate writes | Idempotency keys make writes replay-safe |

The product question is simple: can an agent become more auditable, calibratable, and process-aware over time without giving the journal execution power?

## How it works

The loop is intentionally narrow:

1. The agent binds or records a prediction market and captures snapshots.
2. The agent records binary probability forecasts and optional decisions.
3. The caller supplies or explicitly fetches resolutions when they are known.
4. Trade Trace scores supported forecasts and produces deterministic reports.
5. The agent writes reflections/playbook updates; the next session recalls relevant lessons.

Trade Trace supplies the storage, contracts, scoring, and reporting substrate. The calling agent supplies judgment, market data, outcomes, and any trading action outside this project.

## What it includes

- **Agent-native PM journal:** markets, snapshots, binary forecasts, optional decisions, resolutions/outcomes, reflections, playbooks, strategies, and tags.
- **Forecast scoring:** supported binary forecasts can be scored against final outcomes, including Brier and calibration diagnostics.
- **Deterministic reports:** calibration, forecast diagnostics, source quality, audit readiness, risk/opportunity diagnostics, P&L where local projection data exists, strategy health/performance, recall receipts, review bundles, lifecycle, and work-queue views.
- **Typed memory graph:** retain, recall, and reflect over observations, reflections, and playbook rules, with typed links back to journal rows.
- **Strategies and playbooks:** group related market decisions under named strategies and version process rules without turning either into trading recommendations.
- **Agent continuity:** `report.work_queue`, `report.lifecycle`, and `report.bootstrap` expose local process obligations for fresh sessions. They do not schedule work, assign tasks, fetch data, or recommend trades.
- **MCP and CLI parity:** the same tool registry, JSON envelopes, validation semantics, stable error codes, schemas, and dry-run/idempotency contracts back both transports.
- **Local-first storage:** one SQLite database, append-only/auditable events, JSONL export/import surfaces, and SHA-256-verified backup/restore.

## What it is not

- **Not a trade executor:** no order placement, routing, signing, broker keys, wallet keys, seed phrases, or private keys.
- **Not a default market-data fetcher:** no background venue queries, scheduler, broker state, order books, or webhooks. The Polymarket adapter is explicit opt-in and agent-triggered.
- **Not a dashboard:** the former human Console UI was removed. Supported surfaces are MCP stdio, CLI, and Python/reporting APIs.
- **Not financial advice:** reports are retrospective diagnostics and process review, not trade recommendations or edge claims.
- **Not a generic memory framework, backtester, scheduler, tax tool, or social platform:** the schema is prediction-market-shaped and local.

## Install from source

Trade Trace is pre-release. The current source is being prepared for the v0.0.2 prediction-market pivot; no stable public release has been cut yet. Until a public release artifact is available, install from a checkout:

```bash
python3 -m pip install -e .
export TRADE_TRACE_HOME="$HOME/.trade-trace"
tt journal init
```

Requirements: Python 3.11+ and SQLite with FTS5. MCP support is bundled in the base package.

Optional vector recall support is available from source with:

```bash
python3 -m pip install -e '.[embeddings]'
```

The embeddings extra adds the optional local ONNX/tokenizers runtime. It does not enable vectors, download model weights, or send memory text to an API provider. In v0.0.2 the supported provider enum is `none|local`; local model assets must be imported explicitly with `tt --confirm model import --src <pre-staged-dir> --idempotency-key <key>`, and remote/API embedding providers are unsupported.

Intel Mac note: current `onnxruntime` releases do not ship macOS x86_64 wheels. Intel Mac users should either use BM25 recall or manually pin a compatible older `onnxruntime` (for example 1.19) in their local environment.

## Connect an agent over MCP

Start the local stdio MCP server:

```bash
trade-trace-mcp
```

Configure your MCP host to launch that command locally. Do not configure HTTP, SSE, websocket, or TCP transport.

```json
{
  "mcpServers": {
    "trade-trace": {
      "command": "trade-trace-mcp",
      "args": [],
      "env": {
        "TRADE_TRACE_HOME": "/absolute/path/to/.trade-trace",
        "MCP_ACTOR_ID": "agent:research-bot"
      }
    }
  }
}
```

Then verify the connection:

1. list MCP tools;
2. call `journal.status`;
3. call `tool.schema` with no arguments;
4. call `tool.schema` for the first write you intend to use;
5. dry-run writes with `_dry_run: true` before committing.

See [`docs/AI_AGENT_MCP_GETTING_STARTED.md`](./docs/AI_AGENT_MCP_GETTING_STARTED.md) for the full MCP setup guide.

## Use the CLI

The CLI mirrors the MCP catalog by replacing dots in MCP tool names with spaces (for example, `market.bind` becomes `tt market bind`). It emits JSON by default; streaming list/read paths use NDJSON envelopes. The current default public catalog contains 69 registry-generated tools (the scope-reignin freeze/cut landed it at 56, then 13 decision-time tools were added). A further 40 Product-B tools (autonomous-ops, reconciliation/execution-truth, and the anchored-calibration unit) are frozen behind an experimental tier — hidden from the default catalog but still dispatchable via `MCP_INCLUDE_EXPERIMENTAL=1` or `tool.schema {"include_experimental": true}`. `tool.schema` is the source of truth and includes compatibility metadata such as `legacy_name` for renamed tools and hints for removed legacy callers.

```bash
tt journal init
tt tool schema
tt tool schema --tool forecast.add
tt market bind --external-id polymarket:event-123 --source manual --mechanism clob --state open
```

Use `tool.schema` as the source of truth for exact fields, enums, examples, dry-run support, and required metadata. For a complete agent loop, read [`docs/AGENT_GUIDE.md`](./docs/AGENT_GUIDE.md).

## Safety and privacy

- **Local by default:** SQLite at `$TRADE_TRACE_HOME/trade-trace.sqlite`.
- **No default outbound network:** fresh local journal use and MCP stdio startup are tested to make no outbound calls.
- **No telemetry:** no analytics, phone-home, auto-update, or background sync.
- **No credential persistence:** credential-shaped inputs are dropped or rejected; secret-looking free text is scanned before insertion.
- **Append-only audit posture:** source/event tables are immutable; corrections append new rows/events instead of overwriting history.
- **Replay-safe writes:** retryable writes use idempotency keys. For supported write tools, the server auto-derives a deterministic `auto:` key when callers omit one; callers may still pass an explicit key to control the dedupe domain. Safe replays return the original event; semantic conflicts return `IDEMPOTENCY_CONFLICT`.
- **Verified backups:** backup manifests use SHA-256 verification before restore.

Read [`SECURITY.md`](./SECURITY.md) for vulnerability reporting and supported-version policy.

## Docs map

| Start here | For |
|---|---|
| [`docs/AI_AGENT_MCP_GETTING_STARTED.md`](./docs/AI_AGENT_MCP_GETTING_STARTED.md) | First MCP connection and safe write loop. |
| [`docs/AGENT_GUIDE.md`](./docs/AGENT_GUIDE.md) | Full agent journal loop, continuity surfaces, patterns, and pitfalls. |
| [`docs/CLAUDE_CODE.md`](./docs/CLAUDE_CODE.md), [`docs/CLAUDE_DESKTOP.md`](./docs/CLAUDE_DESKTOP.md), [`docs/IDE_MCP_SETUP.md`](./docs/IDE_MCP_SETUP.md) | Client setup recipes. |
| [`docs/VISION.md`](./docs/VISION.md) | Product north star and non-goals. |
| [`docs/PRD.md`](./docs/PRD.md) | Working product requirements and milestone scope. |
| [`docs/architecture/contracts.md`](./docs/architecture/contracts.md) | CLI/MCP JSON envelope, parity, error codes, and schemas. |
| [`docs/architecture/persistence.md`](./docs/architecture/persistence.md) | SQLite, events, outbox, idempotency, and append-only invariants. |
| [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md) | Memory graph, recall, embeddings posture, and typed edges. |
| [`docs/architecture/reports.md`](./docs/architecture/reports.md) | Report filters, drill-down, review bundles, and work queue. |
| [`docs/architecture/scoring.md`](./docs/architecture/scoring.md) | Forecast scoring, Brier/calibration metrics, and lifecycle caveats. |

## License

MIT. See [`LICENSE`](./LICENSE).
