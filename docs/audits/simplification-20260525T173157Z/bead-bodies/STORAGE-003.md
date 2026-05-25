Context:
Domain: storage-events-models. Affected surface: see evidence paths.

Current complexity:
Two overlapping registries can drift, but prior work shows some explicit duplication is intentional.

Evidence:
- src/trade_trace/exporter.py:_STATIC_EVENT_TOOL_MAP maps event types to replay tools; src/trade_trace/events/semantic_keys.py:TOOL_PRIMARY_EVENT_TYPE maps tools to event types; tests/contracts/test_event_type_registry_alignment.py acknowledges registry alignment but current subset/default behavior is intentionally explicit.

Why simplification is safe/desirable:
Finds safe derivation subset, if any, without forcing a broad registry rewrite.

Target simplification:
Investigation/design only: compare prior SIMP-004 findings, inventory aliases/source.attached/system events, and either propose exact follow-up or record intentional explicitness.

Non-goals:
Do not change public CLI/MCP/tool/report/API behavior.; Do not broaden the refactor beyond cited files.; Do not change storage schema, event semantics, security policy, or execution boundaries unless explicitly stated.

Behavior preservation:
SEMANTIC_KEYS remains canonical for writable event types; exporter map remains replayable subset; source.attached payload disambiguation and audit/system defaults must remain unchanged unless downstream plan proves safety. Characterize current behavior before editing. Preserve current response/envelope keys, error codes/messages/details, ordering, idempotency, and security constraints for the cited surface.

Risks / intentional complexity check:
Preserve explicitness where it encodes compatibility, public contract, security, audit, idempotency, or historical data semantics. Overlaps prior trade-trace-eijx SIMP-004; materialized as reconciliation/investigation only, not direct refactor.

Validation:
- python -m pytest tests/contracts/test_event_type_registry_alignment.py tests/integration/test_semantic_keys.py tests/integration/test_outbox_export.py -q

Acceptance criteria:
- Current behavior is characterized before refactor.
- Simplification is limited to the cited surface and no unrelated behavior changes are made.
- Listed validation passes or any gap is resolved before close.
- Implementation notes document why intentional complexity was preserved.

Provenance:
Discovered by repo-simplification-review candidate STORAGE-003 in domain storage-events-models. Matrix: docs/audits/simplification-20260525T173157Z/candidate-matrix.json
