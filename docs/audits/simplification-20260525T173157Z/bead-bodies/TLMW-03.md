Context:
Domain: tools-ledger-memory-workflows. Affected surface: see evidence paths.

Current complexity:
A duplicated DB query obscures the exact single-decision-row contract and adds avoidable evaluator ceremony.

Evidence:
- src/trade_trace/playbook_predicates.py:evaluate_predicate executes SELECT * FROM decisions WHERE id = ? to fetch rows and repeats the same execute only to read cursor.description for dict construction.

Why simplification is safe/desirable:
One named loader makes exact-one-row handling testable and easier to scan.

Target simplification:
Introduce _load_decision_for_predicate or narrower helper using one cursor for rows and description; keep all PredicateEvaluation outcomes unchanged.

Non-goals:
Do not change public CLI/MCP/tool/report/API behavior.; Do not broaden the refactor beyond cited files.; Do not change storage schema, event semantics, security policy, or execution boundaries unless explicitly stated.

Behavior preservation:
Predicate evaluation must preserve missing-decision not_computable, multiple-row ambiguous, one-row decision dict contents, scope checks, and predicate semantics. Characterize current behavior before editing. Preserve current response/envelope keys, error codes/messages/details, ordering, idempotency, and security constraints for the cited surface.

Risks / intentional complexity check:
Preserve explicitness where it encodes compatibility, public contract, security, audit, idempotency, or historical data semantics.

Validation:
- python -m pytest tests/integration/test_playbook_predicates.py tests/integration/test_playbook.py -q

Acceptance criteria:
- Current behavior is characterized before refactor.
- Simplification is limited to the cited surface and no unrelated behavior changes are made.
- Listed validation passes or any gap is resolved before close.
- Implementation notes document why intentional complexity was preserved.

Provenance:
Discovered by repo-simplification-review candidate TLMW-03 in domain tools-ledger-memory-workflows. Matrix: docs/audits/simplification-20260525T173157Z/candidate-matrix.json
