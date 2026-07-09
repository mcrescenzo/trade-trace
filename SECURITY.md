# Security policy

Trade Trace is in early pre-release (`0.0.x`). This document describes
the security posture during this phase and how to report
vulnerabilities responsibly.

## Supported versions

Only the most recent pre-release on PyPI receives security fixes. The
project does not maintain branches for older `0.0.x` versions; upgrade
to the current pre-release to receive fixes.

| Version | Supported |
|---------|-----------|
| `0.0.x` (latest pre-release) | yes |
| anything older | no |

## Reporting a vulnerability

Please report vulnerabilities **privately** via GitHub Security
Advisories on this repository:

  https://github.com/mcrescenzo/trade-trace/security/advisories/new

Do **not** open a public issue for a suspected vulnerability — that
publishes the report before maintainers can ship a fix.

When reporting, include:

- a minimal reproduction (repo state, commands, expected vs observed
  behavior),
- the affected version (`tt journal status | python3 -c "import json, sys; print(json.load(sys.stdin)['data']['package_version'])"`, `pip show trade-trace | grep Version`, or the git SHA), and
- the impact you believe a real attacker could achieve.

We aim to acknowledge new reports within seven days while the project
remains in pre-release. Coordinated disclosure timelines are agreed
case by case.

## Scope

In scope:

- the published `trade-trace` package on PyPI and code in this
  repository,
- the documented CLI (`tt`) and MCP stdio server
  (`trade-trace-mcp`) surfaces,
- data integrity / append-only / idempotency contracts documented in
  `docs/architecture/`.

Out of scope:

- third-party MCP clients (Claude Desktop, Cursor, Windsurf, etc.) —
  report those to their respective maintainers,
- the local SQLite database when accessed by code outside the
  documented tool surface,
- denial-of-service from intentionally malformed inputs to local-only
  binaries running with the operator's own credentials.

## Network and telemetry posture

By default, Trade Trace is local-first and does not send telemetry. Fresh
`journal.init`, local journal operations, and MCP stdio
startup are expected to make no outbound network calls; the repository keeps
security tests for those default boundaries.

Outbound network is in scope as a vulnerability when it happens without an
explicit operator request. The optional embeddings path is local-only in
v0.0.2: operators may install the `[embeddings]` extra and manually import
trusted, pre-staged ONNX/tokenizer assets, but Trade Trace does not download
model files from configuration and does not support remote/API embedding
providers or keyring-backed embedding credentials.

The v0.0.2 Polymarket adapter is opt-in and fail-closed:
`network.polymarket.enabled` must be true before adapter-backed market,
snapshot, or resolution tools can open a socket. Configured adapter endpoints
must use HTTPS, are checked against the adapter host policy before an HTTP
client is used, and error/log details scrub URL scheme, credentials, query
strings, and fragments. Adapter operational logs include method, scrubbed
endpoint, status, and latency only; response bodies are never logged.
