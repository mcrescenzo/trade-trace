# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**Scope (bead trade-trace-9zy / DEBT-005)**: this protocol applies to
**mutating, authorized work sessions** — sessions that intentionally
modify code, tests, docs, or Beads state. Sessions that are explicitly
read-only or no-push are exempt as documented under "When NOT to push"
below. The default for a Claude session that produces commits is to
follow the full mandatory workflow.

**When ending a mutating work session**, you MUST complete ALL steps
below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW (mutating sessions only):**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES (mutating sessions only):**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

**When NOT to push (exempt session lanes):**

The mandatory workflow does NOT apply to these explicitly read-only
or no-push lanes:

- **Read-only audit / investigation sessions** where the user
  explicitly instructed "do not modify anything", "audit only",
  "read-only review", "investigate but do not push", or similar. In
  these lanes, file issues only if the user asked for them; never
  open Beads with `bd update --claim` or `bd close`; never commit
  or push.
- **Delegated/coordinator subagent runs** where the parent agent
  retains commit/push authority. The subagent reports findings and
  does NOT push, even if it commits locally — the parent decides
  what lands on `main`.
- **Sessions where the user typed an explicit "don't push" / "no
  push" / "stop before push" directive**. The user's instructions
  override the mandatory rule.
- **Failed pre-flight gates**: if tests, linters, or `bd doctor`
  surface a pre-existing failure unrelated to the session's work,
  STOP and ask before pushing the unrelated state forward.

In all exempt cases the session ends with a written handoff
(committed locally if appropriate) describing what was found, what
was changed (if anything), and the explicit reason the push step
was skipped. Do not silently skip the push step in a mutating
session — that's a workflow violation, not an exemption.
<!-- END BEADS INTEGRATION -->


## Build & Test

Trade Trace is a Python package; quality gates run via `ruff`, `mypy`,
and `pytest`. The dev install:

```bash
pip install -e ".[dev]"
ruff check src tests
mypy src
pytest -q
```

See [`docs/RELEASE_CHECKLIST.md`](./docs/RELEASE_CHECKLIST.md) for
the pre-publish gate sequence.

## Architecture Overview

A local-only journal + memory + calibration substrate for LLM trading
agents. The surface is a JSON-first CLI (`tt`) and an MCP stdio
server (`trade-trace-mcp`), both dispatching through the shared
registry in `src/trade_trace/core.py`. Storage is SQLite (WAL +
FTS5); events are append-only with idempotency. See
[`docs/architecture/`](./docs/architecture/) for the per-surface
specs (each file's `Status:` header marks shipped vs design content
per trade-trace-qea7).

## Conventions & Patterns

- Tool handlers return `dict`; the dispatcher wraps them in the typed
  envelope contract in `docs/architecture/contracts.md`.
- Writes are append-only; every retryable write requires an
  `idempotency_key` (per trade-trace-cpz2).
- Free-text fields are scanned for embedded secrets at write time
  (`tests/security/test_secret_pattern_writes.py`).
- Tests live under `tests/{contracts,integration,security,golden,docs}`.
  Architecture and decision docs live under `docs/architecture/`; the
  taxonomy is documented in
  [`docs/architecture/docs-taxonomy.md`](./docs/architecture/docs-taxonomy.md).
