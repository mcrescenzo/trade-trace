Context:
storage-events-integrity — src/trade_trace/tools/ledger.py, docs/architecture/scoring.md

Observed behavior:
Supersede-created replacement forecast remains unscored after an existing resolved_final outcome.

Expected behavior:
Supersede-created forecast triggers same late scoring path as forecast.add or contract/docs explicitly exclude it.

Evidence:
primary_evidence.txt forecast_supersede_static_snippet: forecast.add late trigger calls _score_one_forecast; supersede docstring says auto-scoring intentionally not replicated; scoring docs require forecast.created trigger.

Failure mode / impact:
Calibration/report substrates omit corrected replacement forecasts until manual repair.

## Steps to Reproduce
pytest tests/integration/test_scoring_lifecycle.py tests/integration/test_ledger_event_emission.py tests/integration/test_report_calibration.py -q

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: trade-trace-re4.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
pytest tests/integration/test_scoring_lifecycle.py tests/integration/test_ledger_event_emission.py tests/integration/test_report_calibration.py -q

Acceptance criteria:
- Supersede after resolved_final writes forecast_scores row for replacement
- forecast.scored event emitted in same transaction
- Regression covers ambiguous yes_label recovery via supersede

Provenance:
Discovered by repo-bughunt candidate CAND-005 in domain storage-events-integrity.