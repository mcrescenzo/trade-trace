# CLI/MCP Parity and Schema Extension Guide

> Status: **shipped** foundation audit for agent-continuity roadmap.

## Purpose

Agent-continuity features must be discoverable and callable by a stateless LLM through either CLI or MCP without reading source code. This note pins where new tools, schemas, envelopes, tests, and docs must be updated.

## Live registry paths

| Concern | Canonical path | Notes |
|---|---|---|
| Tool registration | `src/trade_trace/core.py` calls `register_*_tools(...)` | New public tools must be registered through a domain module, not ad-hoc in transports. |
| Tool metadata/schema | `src/trade_trace/contracts/tool_registry.py` | `ToolRegistry.register(...)` owns `description`, `is_write`, `json_schema`, examples, optional keys, next actions, and CLI invocation metadata. |
| Write examples / derived schemas | `src/trade_trace/tools/_examples.py` | Existing write tools derive JSON Schema from `example_minimal`/`example_rich` when no explicit schema is supplied. Optional fields that runtime persists must appear in rich examples. |
| Report schemas | `src/trade_trace/tools/reports.py` `_REPORT_SCHEMAS` | Report tools use explicit JSON Schemas because report inputs are not simple write examples. |
| MCP transport | `src/trade_trace/mcp_server.py` | MCP delegates to the same registry/dispatch path as CLI. Do not fork business logic in MCP. |
| CLI transport | `src/trade_trace/cli.py` | CLI commands should call the same registry handlers and expose equivalent flags for advertised tool fields. |
| Envelope contract | `src/trade_trace/contracts/envelope.py` and `docs/architecture/contracts.md` | Success/error envelopes must stay stable and include typed errors. |
| Report filter contract | `src/trade_trace/contracts/report_filter.py`, `src/trade_trace/reports/_filter_support.py` | Reports must reject unsupported non-empty filters rather than echoing unapplied filters. |
| Migration registry | `src/trade_trace/storage/migrations/__init__.py` | Add forward-only migrations; update schema hash tests for intentional DDL changes. |

## Parity expectations

1. **One handler per tool**: CLI and MCP must route to the same registry handler.
2. **Schema truthfulness**: if a schema advertises a field, runtime must persist/use it or explicitly reject it with `VALIDATION_ERROR`.
3. **Examples are contract-bearing**: `example_minimal` should be the smallest valid call; `example_rich` should cover optional fields important to agents, including run/session provenance where supported.
4. **No silent filter broadening**: report tools may only accept non-default `ReportFilter` fields registered in `_filter_support.SUPPORTED_FILTER_FIELDS` and actually wired into SQL.
5. **Envelope parity**: CLI and MCP should return equivalent `ok/data/error/meta` semantics. Transport-specific metadata may differ only where documented.
6. **Agent-only ergonomics**: all new surfaces need machine-readable schema, precise typed errors, and deterministic examples. Do not rely on prose docs as the only interface contract.

## Current foundation audit findings resolved in Epic A

- `snapshot.add` and `source.add` now persist the common provenance fields (`agent_id`, `model_id`, `environment`, `run_id`) instead of advertising `_Row` metadata that runtime discarded.
- `report.calibration` now supports actor/run filters for `actor_id`, `agent_id`, `model_id`, `environment`, and `run_id`; `report.compare` can group calibration by `actor_id`, `agent_id`, `model_id`, `environment`, and `run_id`.
- `strategy.list` accepts both historical `status='both'` and documented `status='all'` as all-status aliases.
- `strategy.show` is documented as row-focused in the PRD until richer strategy summaries land in the strategy diagnostics epic.

## Required checks when adding or changing a public surface

Run targeted checks first, then the full relevant suite:

```bash
pytest tests/contracts/test_tool_schema_runtime_parity.py
pytest tests/golden/test_cli_mcp_parity.py
pytest tests/security/test_no_network_default.py
pytest tests/security/test_mvp_boundary_audit.py
pytest tests/integration/test_migrations_schema_hash.py
```

For new reports, also add tests that prove unsupported filters are rejected and supported filters change the SQL result, not only the echoed `summary.filter`.

## Follow-on implementation rule

Future agent-continuity tools (`agent.bootstrap`, derived work queue, replay cases, recall receipts) should be added by extending the registry and schema tests first. If a feature cannot be expressed as a deterministic CLI/MCP JSON contract, it is not ready for implementation.
