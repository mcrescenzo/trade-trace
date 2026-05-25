Context:
Domain: contracts-cli-mcp. Affected surface: see evidence paths.

Current complexity:
Transport validation policy is split across two entrypoints, so schema constraints can drift and parity tests become special-case patches.

Evidence:
- src/trade_trace/cli.py:436-475 validates JSON Schema only for numeric-bound validators before handler fallback; src/trade_trace/mcp_server.py:197-214 validates full schema at stdio boundary; tests/contracts/test_min_sample_validation_parity.py pins numeric-bound parity.

Why simplification is safe/desirable:
Single helper/policy module makes CLI-vs-MCP validation rules explicit. Reduces future schema drift without flattening intentional transport differences.

Target simplification:
Extract a shared validation helper with explicit policy knobs such as CLI_NUMERIC_BOUNDS_ONLY vs MCP_STDIO_FULL_SCHEMA; reuse from cli.py and mcp_server.py while preserving current envelope details.

Non-goals:
Do not change public CLI/MCP/tool/report/API behavior.; Do not broaden the refactor beyond cited files.; Do not change storage schema, event semantics, security policy, or execution boundaries unless explicitly stated.

Behavior preservation:
CLI must keep its narrowed numeric-bound prevalidation and handler-owned friendly required/type/enum errors; MCP stdio must keep full schema rejection; mcp_call shim behavior remains unchanged unless explicitly characterized. Characterize current behavior before editing. Preserve current response/envelope keys, error codes/messages/details, ordering, idempotency, and security constraints for the cited surface.

Risks / intentional complexity check:
Preserve explicitness where it encodes compatibility, public contract, security, audit, idempotency, or historical data semantics.

Validation:
- python -m pytest tests/contracts/test_min_sample_validation_parity.py tests/contracts/test_tool_schema_runtime_parity.py tests/golden/test_cli_mcp_parity.py -q

Acceptance criteria:
- Current behavior is characterized before refactor.
- Simplification is limited to the cited surface and no unrelated behavior changes are made.
- Listed validation passes or any gap is resolved before close.
- Implementation notes document why intentional complexity was preserved.

Provenance:
Discovered by repo-simplification-review candidate CLCM-001 in domain contracts-cli-mcp. Matrix: docs/audits/simplification-20260525T173157Z/candidate-matrix.json
