Context:
Domain: storage-events-models. Affected surface: see evidence paths.

Current complexity:
Two positional event-row hydration paths can diverge when metadata fields change.

Evidence:
- src/trade_trace/events/log.py:_find_existing selects and manually constructs EventRecord from events row; src/trade_trace/exporter.py:_load_event repeats the same events column list and EventRecord construction; fresh write construction separately spells the same field order.

Why simplification is safe/desirable:
One row-hydration contract for EventRecord. Lower risk when event metadata columns evolve.

Target simplification:
Add EVENT_RECORD_SELECT_COLUMNS and EventRecord.from_row() or private equivalent; use it for _find_existing and exporter _load_event; leave fresh write semantics unchanged unless covered.

Non-goals:
Do not change public CLI/MCP/tool/report/API behavior.; Do not broaden the refactor beyond cited files.; Do not change storage schema, event semantics, security policy, or execution boundaries unless explicitly stated.

Behavior preservation:
EventWriter idempotency replay and exporter/outbox JSONL drain must preserve event metadata fields, event row values, and JSONL output shape. Characterize current behavior before editing. Preserve current response/envelope keys, error codes/messages/details, ordering, idempotency, and security constraints for the cited surface.

Risks / intentional complexity check:
Preserve explicitness where it encodes compatibility, public contract, security, audit, idempotency, or historical data semantics. Prior trade-trace-0apb decided canonical JSONL serialization; this is additive row-hydration alignment, not serialization-path choice.

Validation:
- python -m pytest tests/integration/test_idempotency.py tests/integration/test_outbox_export.py tests/integration/test_semantic_keys.py -q

Acceptance criteria:
- Current behavior is characterized before refactor.
- Simplification is limited to the cited surface and no unrelated behavior changes are made.
- Listed validation passes or any gap is resolved before close.
- Implementation notes document why intentional complexity was preserved.

Provenance:
Discovered by repo-simplification-review candidate STORAGE-001 in domain storage-events-models. Matrix: docs/audits/simplification-20260525T173157Z/candidate-matrix.json
