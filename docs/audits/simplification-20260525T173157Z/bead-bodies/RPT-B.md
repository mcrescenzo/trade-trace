Context:
Domain: reports-reporting. Affected surface: see evidence paths.

Current complexity:
Pagination mechanics are duplicated despite an existing helper, creating cursor drift risk.

Evidence:
- src/trade_trace/reporting/pagination.py has paginate_created_at_id_query for composite keyset pagination; src/trade_trace/reporting/trade_rows.py:list_trades and position_rows.py:list_positions manually duplicate limit clamp, cursor decode, lexicographic predicate, order, limit+1, and next_cursor encoding for d.created_at/d.id and p.opened_at/p.id.

Why simplification is safe/desirable:
One helper extension improves cursor consistency. Reduces future pagination bug surface.

Target simplification:
Generalize pagination helper to accept qualified timestamp/id columns or a builder, preserve defaults, and route trade/position read-models through it after characterization.

Non-goals:
Do not change public CLI/MCP/tool/report/API behavior.; Do not broaden the refactor beyond cited files.; Do not change storage schema, event semantics, security policy, or execution boundaries unless explicitly stated.

Behavior preservation:
Cursor token shape [timestamp,id], descending order, limit clamping, invalid cursor behavior, filter semantics, and next_cursor behavior must remain unchanged for list_trades/list_positions. Characterize current behavior before editing. Preserve current response/envelope keys, error codes/messages/details, ordering, idempotency, and security constraints for the cited surface.

Risks / intentional complexity check:
Preserve explicitness where it encodes compatibility, public contract, security, audit, idempotency, or historical data semantics.

Validation:
- python -m pytest tests/contracts/test_reporting_pagination.py tests/integration/test_reporting_read_model.py tests/integration/test_reporting_pagination_perf_baseline.py -q

Acceptance criteria:
- Current behavior is characterized before refactor.
- Simplification is limited to the cited surface and no unrelated behavior changes are made.
- Listed validation passes or any gap is resolved before close.
- Implementation notes document why intentional complexity was preserved.

Provenance:
Discovered by repo-simplification-review candidate RPT-B in domain reports-reporting. Matrix: docs/audits/simplification-20260525T173157Z/candidate-matrix.json
