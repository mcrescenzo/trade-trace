## Context
Repo-audit refresh `repo-audit-20260521T191125Z` found a machine-readable contract mismatch in `report.current_exposure`.

## Bug claim
The report advertises `projection_anomalies`, but the top-level payload key is `anomalies`.

## Evidence
- `docs/architecture/current-exposure-agent-contract.md` names `projection_anomalies`.
- `src/trade_trace/tools/reports.py:1240` lists `projection_anomalies` in summary.
- `src/trade_trace/tools/reports.py:1261` returns top-level `anomalies`.

## Steps to Reproduce
1. Call `report.current_exposure`.
2. Compare `summary.buckets` with top-level payload keys.
3. Observe `projection_anomalies` vs `anomalies` mismatch.

## Acceptance Criteria
- Payload, summary.buckets, docs, schema/help, and tests agree on one anomaly bucket key.
