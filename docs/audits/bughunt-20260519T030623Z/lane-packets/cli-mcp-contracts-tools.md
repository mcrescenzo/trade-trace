# Lane packet: cli-mcp-contracts-tools

Inspected cli.py, mcp_server.py, contracts, tools, contract/golden/admin/CLI tests. Commands: targeted pytest 50 passed; temp CLI malformed JSON probe; temp config_set probe. Candidates: CLI malformed --*-json bypasses envelope; journal.config_set mutates without --confirm despite docs/help.

Side effects: no intentional repo edits; probes used temporary directories. See primary_evidence.txt for coordinator proof snippets.
