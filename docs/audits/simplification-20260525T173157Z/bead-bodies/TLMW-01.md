Context:
Domain: tools-ledger-memory-workflows. Affected surface: see evidence paths.

Current complexity:
Duplicated transactional write kernels can diverge on idempotency, events, or envelope details.

Evidence:
- src/trade_trace/tools/ledger/source.py has public _make_source_attacher(target_kind) workflow and internal _source_attach_to_memory_node_in_uow with parallel source lookup, target validation, edge-type derivation, idempotency replay, inline metadata append, event emission, and response shaping.

Why simplification is safe/desirable:
One private kernel makes public and internal attach behavior align by construction. Reduces risk left after registration metadata was centralized.

Target simplification:
Introduce _source_attach_in_uow(args, ctx, uow, *, target_kind) returning the current response shape; route public and memory-node internal paths through it without changing registration.

Non-goals:
Do not change public CLI/MCP/tool/report/API behavior.; Do not broaden the refactor beyond cited files.; Do not change storage schema, event semantics, security policy, or execution boundaries unless explicitly stated.

Behavior preservation:
All source.attach_to_* public tools and internal memory-node attach in a UnitOfWork must preserve NOT_FOUND/VALIDATION_ERROR envelopes, edge_type derivation, idempotency replay, inline metadata, source.attached event payload, response fields, and UnitOfWork boundary. Characterize current behavior before editing. Preserve current response/envelope keys, error codes/messages/details, ordering, idempotency, and security constraints for the cited surface.

Risks / intentional complexity check:
Preserve explicitness where it encodes compatibility, public contract, security, audit, idempotency, or historical data semantics. Prior trade-trace-4v31 centralized source.attach target metadata/registration only; it explicitly did not target the write kernel.

Validation:
- python -m pytest tests/contracts/test_tool_schema_runtime_parity.py tests/contracts/test_agent_ergonomics.py tests/integration/test_source_quality.py tests/integration/test_source_attach_to_memory_node.py -q

Acceptance criteria:
- Current behavior is characterized before refactor.
- Simplification is limited to the cited surface and no unrelated behavior changes are made.
- Listed validation passes or any gap is resolved before close.
- Implementation notes document why intentional complexity was preserved.

Provenance:
Discovered by repo-simplification-review candidate TLMW-01 in domain tools-ledger-memory-workflows. Matrix: docs/audits/simplification-20260525T173157Z/candidate-matrix.json
