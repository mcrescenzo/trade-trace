# Trade Trace MCP setup: Claude Desktop

Trade Trace runs as a local MCP stdio server. Claude Desktop launches `trade-trace-mcp` directly; no HTTP URL or port is needed.

## Prerequisites

Install Trade Trace with the optional MCP dependency in the Python environment Claude Desktop can reach:

```bash
pip install -e '.[mcp]'
command -v trade-trace-mcp
```

Choose a local data directory and initialize the journal once:

```bash
export TRADE_TRACE_HOME="$HOME/.trade-trace"
tt journal init
```

Optional actor identity for MCP tool calls:

```bash
export MCP_ACTOR_ID="agent:claude-desktop"
```

If `MCP_ACTOR_ID` is not set, Trade Trace uses `mcp:default`.

## claude_desktop_config.json

Add this server entry to your Claude Desktop config file. The snippet is copy-paste-ready JSON:

```json
{
  "mcpServers": {
    "trade-trace": {
      "command": "trade-trace-mcp",
      "args": [],
      "env": {
        "TRADE_TRACE_HOME": "${HOME}/.trade-trace",
        "MCP_ACTOR_ID": "agent:claude-desktop"
      }
    }
  }
}
```

If Claude Desktop on your platform does not expand `${HOME}` inside MCP env values, replace it with an absolute path, for example:

```json
{
  "mcpServers": {
    "trade-trace": {
      "command": "trade-trace-mcp",
      "args": [],
      "env": {
        "TRADE_TRACE_HOME": "/Users/alice/.trade-trace",
        "MCP_ACTOR_ID": "agent:claude-desktop"
      }
    }
  }
}
```

If `trade-trace-mcp` is not on Claude Desktop's PATH, replace `command` with the absolute path returned by `command -v trade-trace-mcp`.

## Verify

Restart Claude Desktop after saving the config. In a new chat, ask Claude to list available MCP tools or call Trade Trace `journal.status`.

## Notes

- Use stdio only. Do not configure an HTTP or SSE server URL.
- Keep secrets out of this file. Trade Trace does not need broker credentials, API keys, wallet keys, or seed phrases.
- `TRADE_TRACE_HOME` controls where the local SQLite journal and exports live.
