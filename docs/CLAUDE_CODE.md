# Trade Trace MCP setup: Claude Code

Trade Trace runs as a local MCP stdio server. It does not expose an HTTP port and does not make network calls by default.

## Prerequisites

From the Trade Trace checkout or package environment, install the optional MCP extra and confirm the console script is on your PATH:

```bash
pip install -e '.[mcp]'
trade-trace-mcp
```

`trade-trace-mcp` is a stdio server, so the second command will wait for MCP JSON-RPC input. Press `Ctrl-C` after confirming the command starts without an import error.

Choose a local data directory and initialize the journal once:

```bash
export TRADE_TRACE_HOME="$HOME/.trade-trace"
tt journal init
```

Optional actor identity for tool calls:

```bash
export MCP_ACTOR_ID="agent:claude-code"
```

If `MCP_ACTOR_ID` is not set, Trade Trace uses `mcp:default`.

## Per-project setup

Run this from the project where you want Claude Code to use Trade Trace:

```bash
claude mcp add -e TRADE_TRACE_HOME="$HOME/.trade-trace" -e MCP_ACTOR_ID="agent:claude-code" trade-trace -- trade-trace-mcp
```

This registers a local stdio MCP server named `trade-trace` for the current Claude Code project. The command after `--` is the exact server process Claude Code launches.

If your Claude Code version requires an explicit scope flag, use the project/local scope offered by `claude mcp add --help` and keep the same server command:

```bash
claude mcp add --scope local -e TRADE_TRACE_HOME="$HOME/.trade-trace" -e MCP_ACTOR_ID="agent:claude-code" trade-trace -- trade-trace-mcp
```

## Global/user setup

Use user scope only if every Claude Code project on this machine should see the same Trade Trace journal:

```bash
claude mcp add --scope user -e TRADE_TRACE_HOME="$HOME/.trade-trace" -e MCP_ACTOR_ID="agent:claude-code" trade-trace -- trade-trace-mcp
```

Check the exact scopes supported by your installed CLI with:

```bash
claude mcp add --help
```

## Verify

List configured MCP servers:

```bash
claude mcp list
```

Then start Claude Code in the project and ask it to list MCP tools or call Trade Trace `journal.status`. The server should use the local `$TRADE_TRACE_HOME/trade-trace.sqlite` database.

## Notes

- Do not configure Trade Trace with an HTTP URL; use stdio only.
- Keep secrets out of MCP config. Trade Trace is not a broker connector and does not need API keys, seed phrases, wallet keys, or exchange credentials.
- If `trade-trace-mcp` is not found by Claude Code, use an absolute path from `command -v trade-trace-mcp` in the MCP command.
