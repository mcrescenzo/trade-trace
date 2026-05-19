# trade-trace-yv9z — Decide disposition for stale exported DOCUMENTED_GROUP_BY metadata

Status: closed
Type: task
Priority: P3
Labels: dead-code, deadcode-hunt, deadcode:refresh-20260519, domain:reports, needs-owner-confirmation, public-api, stale-contract

## Description

Context:
Domain: reports/public API truth.
Candidate: DC-REFRESH-003.

Dead-code / stale-contract claim:
`src/trade_trace/reports/compare.py` exports `DOCUMENTED_GROUP_BY`, but the constant is internally unused and stale relative to runtime-supported group_by allowlists.

Evidence:
- `src/trade_trace/reports/compare.py:50` defines `DOCUMENTED_GROUP_BY`.
- `src/trade_trace/reports/compare.py:289` includes it in `__all__`.
- Excluding audits, reference search finds no internal consumers.
- Runtime validation uses `CALIBRATION_GROUP_SQL` and `PNL_GROUP_SQL`, not `DOCUMENTED_GROUP_BY`.
- The exported constant lists `playbook_version_id`, `liquidity_bucket`, and `confidence_bucket`; current validation rejects unsupported values not present in the runtime allowlists.

Reference search scope:
Tracked `src`, `tests`, active docs, README, pyproject, excluding audit artifacts.

Reference search commands / output summary:
- `git grep -n DOCUMENTED_GROUP_BY -- ':!docs/audits/**' ':!audits/**'` -> definition and `__all__` export only.
- Source readback of `compare.py` validators confirms runtime allowlists.

Why it may be falsely alive:
It is exported in `__all__`; downstream users may import it, or it may be intended planned metadata rather than runtime support metadata.

Impact / risk of keeping:
Stale public-ish metadata can mislead callers about `report.compare` supported `group_by` values.

Recommended action:
Owner decides whether to remove/deprecate it, rename it as planned-only metadata, or replace it with a tested constant derived from actual allowlists.

Safe-removal validation:
- `python3 -m pytest tests/integration/test_report_compare.py tests/security/test_report_sql_filters.py tests/golden/test_cli_mcp_parity.py -q`
- Ruff check for `compare.py` and report tooling.

Duplicate check:
No open duplicate found. Related to closed `trade-trace-4md` report.compare implementation, but distinct as stale exported metadata cleanup.

Acceptance criteria:
- Owner disposition recorded for `DOCUMENTED_GROUP_BY`.
- If retained/replaced, tests prove it matches runtime support or is clearly named as planned-only.
- If removed/deprecated, exports/docs/tests are updated safely and report.compare validation behavior is unchanged unless intentionally changed.

Provenance:
Discovered by repo-deadcode-hunt candidate DC-REFRESH-003 in docs/audits/deadcode-20260519T180524Z/candidate-matrix.json.


## Notes



## Acceptance

Owner disposition recorded; exports/docs/tests align with runtime group_by support; report.compare validation unchanged unless intentional.
