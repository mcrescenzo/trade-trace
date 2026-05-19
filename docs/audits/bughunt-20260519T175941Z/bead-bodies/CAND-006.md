Context:
reports-memory-strategy-playbook — src/trade_trace/tools/reflection.py, docs/architecture/memory-layer.md

Observed behavior:
Packet selects earliest forecast/thesis on instrument, not the forecast scored by the requested outcome.

Expected behavior:
Packet selects forecast via forecast_scores/outcome relation and thesis via forecast.thesis_id.

Evidence:
primary_evidence.txt reflection_static_snippet: reflection selects earliest forecast/thesis by instrument_id, while docs promise original forecast/thesis resolved by outcome.

Failure mode / impact:
Agents reflect on the wrong trade/forecast and compute wrong calibration delta.

## Steps to Reproduce
TRADE_TRACE_HOME=$(mktemp -d) pytest -q tests/integration -k "reflection or prompt_for_outcome"

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: none.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
TRADE_TRACE_HOME=$(mktemp -d) pytest -q tests/integration -k "reflection or prompt_for_outcome"

Acceptance criteria:
- Packet forecast id is linked to requested outcome via forecast_scores/canonical relation
- Packet thesis id equals returned forecast.thesis_id
- Regression covers two forecasts on one instrument

Provenance:
Discovered by repo-bughunt candidate CAND-006 in domain reports-memory-strategy-playbook.