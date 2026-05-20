# Deadcode hunt 2026-05-20 preflight
- Mode: exhaustive backlog-materialization candidate discovery, starting read-only; Beads mutation only after matrix + advisor gate.
- Repo: `/home/hermes/code/trade-trace`
- HEAD: `73aee82b3cb5de934e10835c5f26425a6483813c`
- Branch status: `## main...origin/main`
- Tracked files: 283
- Existing same-family programs: closed `trade-trace-5lx` (2026-05-18 exhaustive) and `trade-trace-ldru` (2026-05-19 refresh). New full pass is justified because current HEAD contains major console/frontend/docs/migration changes and current manifest differs materially from prior manifests.
- Open Beads at preflight are 3 unrelated beta/product feature requests; no open deadcode backlog remains.

## Domain map
### python-core-storage-security
- Files: 43
- Paths/globs: src/trade_trace/__init__.py, src/trade_trace/clock.py, src/trade_trace/contracts, src/trade_trace/core.py, src/trade_trace/events, src/trade_trace/exporter.py, src/trade_trace/logging.py, src/trade_trace/models, src/trade_trace/projections.py, src/trade_trace/security, src/trade_trace/storage, src/trade_trace/timestamps.py, src/trade_trace/version.py
- Coverage priority: exhaustive direct/probed inspection, reference search, entrypoint/public/dynamic/docs/tests validation.
### tools-cli-mcp-reports
- Files: 36
- Paths/globs: src/trade_trace/cli.py, src/trade_trace/mcp_server.py, src/trade_trace/reports, src/trade_trace/tools
- Coverage priority: exhaustive direct/probed inspection, reference search, entrypoint/public/dynamic/docs/tests validation.
### console-backend-frontend
- Files: 32
- Paths/globs: frontend/console, src/trade_trace/console
- Coverage priority: exhaustive direct/probed inspection, reference search, entrypoint/public/dynamic/docs/tests validation.
### tests-fixtures
- Files: 120
- Paths/globs: tests
- Coverage priority: exhaustive direct/probed inspection, reference search, entrypoint/public/dynamic/docs/tests validation.
### docs-ci-config-audit
- Files: 52
- Paths/globs: .claude, .codex, .github, .gitignore, AGENTS.md, CLAUDE.md, LICENSE, README.md, SECURITY.md, docs, pyproject.toml
- Coverage priority: exhaustive direct/probed inspection, reference search, entrypoint/public/dynamic/docs/tests validation.
