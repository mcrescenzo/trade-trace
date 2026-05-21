## Context
Repo-audit refresh `repo-audit-20260521T191125Z` found a current-exposure filtering bug in `report.current_exposure`.

## Bug claim
`report.current_exposure` echoes filters in `summary.filter`, but `watchlist`, `projection_anomalies`, and `recent_trade_activity` are not scoped consistently.

## Evidence
- `src/trade_trace/tools/reports.py:1221-1229` filter forwarding mismatch.
- Coordinator repro returned unrelated recent activity under a filtered packet.

## Steps to Reproduce
1. Seed two instruments/strategies with recent/watch/anomaly rows.
2. Call `report.current_exposure` with one `instrument_id`/`strategy_id`.
3. Observe out-of-scope child bucket rows despite `summary.filter`.

## Acceptance Criteria
- Packet-level filter semantics are truthful for all buckets.
- Regression tests cover out-of-scope recent/watch/anomaly rows.
