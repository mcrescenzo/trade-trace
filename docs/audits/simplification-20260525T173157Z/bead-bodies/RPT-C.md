Context:
Domain: reports-reporting. Affected surface: see evidence paths.

Current complexity:
Repeated temporal validation risks drift between exposure report handlers.

Evidence:
- src/trade_trace/reports/tool_handlers/portfolio_exposure.py:_report_open_positions lines 79-97 and _report_exposure_anomalies lines 185-203 repeat stale_mark_threshold_days validation, as_of parsing/defaulting, and stale_cutoff computation; _report_current_exposure composes both and may parse the same args twice.

Why simplification is safe/desirable:
Shared helper makes temporal validation consistent. Small localized reduction in handler ceremony.

Target simplification:
Add private helper returning as_of, stale_mark_threshold_days, stale_cutoff; use in open positions/anomalies; only normalize current_exposure echo if characterized and covered.

Non-goals:
Do not change public CLI/MCP/tool/report/API behavior.; Do not broaden the refactor beyond cited files.; Do not change storage schema, event semantics, security policy, or execution boundaries unless explicitly stated.

Behavior preservation:
Validation errors, details, default datetime.now(UTC) behavior, lower-level report composition, summary filters, and stale caveat semantics must remain unchanged. Characterize current behavior before editing. Preserve current response/envelope keys, error codes/messages/details, ordering, idempotency, and security constraints for the cited surface.

Risks / intentional complexity check:
Preserve explicitness where it encodes compatibility, public contract, security, audit, idempotency, or historical data semantics.

Validation:
- python -m pytest tests/integration/test_report_current_exposure.py tests/contracts/test_report_envelope_completeness.py -q

Acceptance criteria:
- Current behavior is characterized before refactor.
- Simplification is limited to the cited surface and no unrelated behavior changes are made.
- Listed validation passes or any gap is resolved before close.
- Implementation notes document why intentional complexity was preserved.

Provenance:
Discovered by repo-simplification-review candidate RPT-C in domain reports-reporting. Matrix: docs/audits/simplification-20260525T173157Z/candidate-matrix.json
