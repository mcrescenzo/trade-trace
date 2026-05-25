Context:
Domain: tools-ledger-memory-workflows. Affected surface: see evidence paths.

Current complexity:
Repeated validation boilerplate increases drift risk in future playbook handlers.

Evidence:
- src/trade_trace/tools/playbook.py repeats playbook, playbook_version, decision, and memory_node type existence checks across _playbook_propose_version, _decision_record_adherence, and _playbook_adherence with repeated ToolError envelope construction.

Why simplification is safe/desirable:
Named helpers clarify endpoint preconditions. Keeps error-envelope behavior consistent.

Target simplification:
Add domain-specific _require_playbook/_require_playbook_version/_require_decision/_require_memory_node_type helpers or equivalent; call from existing handlers without changing business logic.

Non-goals:
Do not change public CLI/MCP/tool/report/API behavior.; Do not broaden the refactor beyond cited files.; Do not change storage schema, event semantics, security policy, or execution boundaries unless explicitly stated.

Behavior preservation:
Unknown playbook/version/decision/node and wrong node-type errors must preserve ErrorCode, message, details, and validation order for playbook workflow tools. Characterize current behavior before editing. Preserve current response/envelope keys, error codes/messages/details, ordering, idempotency, and security constraints for the cited surface.

Risks / intentional complexity check:
Preserve explicitness where it encodes compatibility, public contract, security, audit, idempotency, or historical data semantics.

Validation:
- python -m pytest tests/integration/test_playbook.py tests/contracts/test_tool_schema_runtime_parity.py -q

Acceptance criteria:
- Current behavior is characterized before refactor.
- Simplification is limited to the cited surface and no unrelated behavior changes are made.
- Listed validation passes or any gap is resolved before close.
- Implementation notes document why intentional complexity was preserved.

Provenance:
Discovered by repo-simplification-review candidate TLMW-02 in domain tools-ledger-memory-workflows. Matrix: docs/audits/simplification-20260525T173157Z/candidate-matrix.json
