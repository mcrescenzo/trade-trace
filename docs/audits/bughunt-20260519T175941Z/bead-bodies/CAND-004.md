Context:
storage-events-integrity — src/trade_trace/tools/ledger.py, src/trade_trace/events/log.py, docs/architecture/persistence.md

Observed behavior:
Same idempotency key replay can create a different replacement forecast and duplicate supersedes edges/events.

Expected behavior:
Replay returns original replacement forecast without any new rows/events; conflicting payload fails before writes.

Evidence:
lane-packets/lane-1.md dynamic temp-journal proof plus primary_evidence.txt ledger snippet: _forecast_supersede inserts rows before any replay check; EventWriter replay can occur after relational inserts.

Failure mode / impact:
Retry after timeout corrupts forecast lineage and breaks event-log/relational consistency.

## Steps to Reproduce
pytest tests/integration/test_ledger_event_emission.py tests/integration/test_idempotency.py -q

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: trade-trace-cpz2, trade-trace-re4.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
pytest tests/integration/test_ledger_event_emission.py tests/integration/test_idempotency.py -q

Acceptance criteria:
- Exact forecast.supersede replay returns original replacement id with idempotent_replay=true
- No forecast/outcome/edge/event/outbox counts increase on replay
- Conflicting payload fails before relational writes

Provenance:
Discovered by repo-bughunt candidate CAND-004 in domain storage-events-integrity.