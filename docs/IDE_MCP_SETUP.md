# Trade Trace MCP setup: Cursor, Windsurf, and Cline

Trade Trace runs as a local MCP stdio server. IDE clients should launch `trade-trace-mcp` as a command, not connect to an HTTP URL.

## Prerequisites

Install Trade Trace with the optional MCP dependency in the Python environment your IDE can reach:

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
export MCP_ACTOR_ID="agent:ide"
```

If `MCP_ACTOR_ID` is not set, Trade Trace uses `mcp:default`.

## Generic stdio MCP config

Most IDE MCP clients use the same shape as Claude Desktop. Add a server named `trade-trace` with this copy-paste-ready JSON:

```json
{
  "mcpServers": {
    "trade-trace": {
      "command": "trade-trace-mcp",
      "args": [],
      "env": {
        "TRADE_TRACE_HOME": "${HOME}/.trade-trace",
        "MCP_ACTOR_ID": "agent:ide"
      }
    }
  }
}
```

If your client does not expand `${HOME}`, use an absolute path:

```json
{
  "mcpServers": {
    "trade-trace": {
      "command": "trade-trace-mcp",
      "args": [],
      "env": {
        "TRADE_TRACE_HOME": "/home/alice/.trade-trace",
        "MCP_ACTOR_ID": "agent:ide"
      }
    }
  }
}
```

If the IDE cannot find `trade-trace-mcp`, replace `command` with the absolute path returned by:

```bash
command -v trade-trace-mcp
```

## Client notes

- Cursor: add the JSON in Cursor's MCP settings for the workspace or user profile, depending on whether you want Trade Trace available only for one repo or for all Cursor projects.
- Windsurf: add the same stdio server object in Windsurf MCP settings. Prefer workspace scope when experimenting.
- Cline: add the same server under Cline's MCP server settings. Restart/reload Cline after saving.

## Verify

Reload the IDE window or MCP client. Ask the assistant to list MCP tools or call Trade Trace `journal.status`. The server should read/write the local database under `TRADE_TRACE_HOME`.

## Notes

- Use stdio only. Do not configure an HTTP/SSE URL or a network listener.
- Keep secrets out of MCP config. Trade Trace does not need broker credentials, API keys, wallet keys, or seed phrases.
- Trade Trace never executes trades; it records and reviews decisions supplied by the calling agent.
