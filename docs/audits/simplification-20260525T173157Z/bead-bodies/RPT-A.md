Context:
Domain: reports-reporting. Affected surface: see evidence paths.

Current complexity:
Long repeated registration calls make metadata changes high-churn and increase copy/paste drift risk in public tool schemas.

Evidence:
- src/trade_trace/reports/tool_handlers/registration.py register_report_tools is a ~560-line function with repeated registry.register blocks carrying name, handler, description, examples, optional_keys, json_schema, usage_summary, enum_notes, failures, and next_actions.

Why simplification is safe/desirable:
Descriptor table lowers churn while preserving explicit metadata. Makes registration completeness easier to audit.

Target simplification:
Create typed descriptor/dataclass/table for report registrations; loop over descriptors calling registry.register with the exact existing values and order.

Non-goals:
Do not change public CLI/MCP/tool/report/API behavior.; Do not broaden the refactor beyond cited files.; Do not change storage schema, event semantics, security policy, or execution boundaries unless explicitly stated.

Behavior preservation:
All report tool names, handlers, registration order, descriptions, examples, schemas, enum notes, common failures, next_actions, and discoverability metadata must remain byte/field equivalent where tests inspect them. Characterize current behavior before editing. Preserve current response/envelope keys, error codes/messages/details, ordering, idempotency, and security constraints for the cited surface.

Risks / intentional complexity check:
Preserve explicitness where it encodes compatibility, public contract, security, audit, idempotency, or historical data semantics. Prior trade-trace-73w6/qnxt handled report row/envelope/tool adapter boilerplate; this candidate is narrower registration metadata sprawl.

Validation:
- python -m pytest tests/contracts/test_tool_schema_runtime_parity.py tests/contracts/test_report_envelope_completeness.py tests/integration/test_report_filter.py -q

Acceptance criteria:
- Current behavior is characterized before refactor.
- Simplification is limited to the cited surface and no unrelated behavior changes are made.
- Listed validation passes or any gap is resolved before close.
- Implementation notes document why intentional complexity was preserved.

Provenance:
Discovered by repo-simplification-review candidate RPT-A in domain reports-reporting. Matrix: docs/audits/simplification-20260525T173157Z/candidate-matrix.json
