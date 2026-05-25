Context:
Domain: reports-reporting. Affected surface: see evidence paths.

Current complexity:
Timestamp parsing duplication is real, but local semantics differ and may encode historical compatibility.

Evidence:
- Report modules repeat timestamp parsing with differing semantics: reports/pm_native.py and opportunity.py local _parse_ts return None on invalid; lifecycle.py matches strategy_health and treats naive timestamps as UTC; decision_velocity.py parses inline; source_quality.py normalizes through to_utc_iso8601 then reparses.

Why simplification is safe/desirable:
Characterize modes before consolidating. Avoids accidental strictness changes on historical journal data.

Target simplification:
Investigation/design first: inventory timestamp parse semantics/tests, define helper modes only where equivalent, and create downstream narrow implementation beads if safe.

Non-goals:
Do not change public CLI/MCP/tool/report/API behavior.; Do not broaden the refactor beyond cited files.; Do not change storage schema, event semantics, security policy, or execution boundaries unless explicitly stated.

Behavior preservation:
Historical report behavior for invalid, missing, timezone-aware, Z-suffixed, and naive timestamps must remain unchanged per module unless a downstream contract change is approved. Characterize current behavior before editing. Preserve current response/envelope keys, error codes/messages/details, ordering, idempotency, and security constraints for the cited surface.

Risks / intentional complexity check:
Preserve explicitness where it encodes compatibility, public contract, security, audit, idempotency, or historical data semantics.

Validation:
- python -m pytest tests/integration/test_report_opportunity.py tests/integration/test_report_unscored_velocity.py tests/integration/test_reporting_read_model.py -q

Acceptance criteria:
- Current behavior is characterized before refactor.
- Simplification is limited to the cited surface and no unrelated behavior changes are made.
- Listed validation passes or any gap is resolved before close.
- Implementation notes document why intentional complexity was preserved.

Provenance:
Discovered by repo-simplification-review candidate RPT-D in domain reports-reporting. Matrix: docs/audits/simplification-20260525T173157Z/candidate-matrix.json
