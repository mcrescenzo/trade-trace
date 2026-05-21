# Repo audit delta refresh closeout — repo-audit-20260521T173511Z

## Live state

- Original audit planning commit: `a1023ea4f2d498e916acbcbe25eecc0570d873bf`.
- Current closeout HEAD: `4d2a46268f0de8392aa62321be0b20e5162b347a`.
- Current branch status at artifact generation: `## main...origin/main [ahead 7]
 M docs/reviews/repo-audit-20260521T173511Z/candidate-matrix.json
 M docs/reviews/repo-audit-20260521T173511Z/candidate-matrix.yaml
 M docs/reviews/repo-audit-20260521T173511Z/manifest-coverage-ledger.yaml
?? docs/reviews/repo-audit-20260521T173511Z/observation-register.md`.
- Original audited product scope: 372 tracked files, scope fingerprint `1901b8097953e720`.
- Current tracked-file count includes repo-audit closeout artifacts; those artifacts are not treated as new product surfaces for this audit run.

## Scope drift treatment

The commits after the original planning commit are primarily: repo-audit artifacts, five audited finding fixes, a Console Vitest runtime fix, release-ruff cleanup, and a public-release docs network-wording fix (`trade-trace-gyg3`). The final coverage ledger remains tied to the original 372-row product scope, while this delta record names changed surfaces and their treatment before closeout.

### Product/code/docs files changed since original planning commit

```text
M	README.md
M	SECURITY.md
M	docs/PRD.md
M	docs/RELEASE_CHECKLIST.md
M	docs/RELEASE_FINAL_GATE.md
M	docs/architecture/memory-layer.md
M	frontend/console/package.json
M	src/trade_trace/console/endpoints.py
M	src/trade_trace/console/reporting/trade_rows.py
M	src/trade_trace/console/serve.py
M	src/trade_trace/console/static/app/provenance.json
M	src/trade_trace/storage/database.py
M	src/trade_trace/tools/market_scan.py
M	tests/console_browser/test_overview_smoke.py
M	tests/contracts/test_console_http_routes.py
M	tests/contracts/test_tool_schema_runtime_parity.py
M	tests/integration/test_market_scan_dry_run.py
M	tests/integration/test_market_scan_guided_e2e.py
M	tests/security/test_readonly_database.py
```

Treatment:

- `docs/RELEASE_FINAL_GATE.md`, `src/trade_trace/storage/database.py`, `tests/security/test_readonly_database.py`, `tests/contracts/test_tool_schema_runtime_parity.py`, `src/trade_trace/console/endpoints.py`, `src/trade_trace/console/serve.py`, `tests/contracts/test_console_http_routes.py`, and `tests/console_browser/test_overview_smoke.py` are direct implementations/validations for the five materialized repo-audit findings and are covered by closed Beads `trade-trace-dlk6`, `trade-trace-rtl6`, `trade-trace-bn02`, `trade-trace-beqe`, and `trade-trace-efkg`.
- `frontend/console/package.json` and `src/trade_trace/console/static/app/provenance.json` changed as part of Console test/build/runtime validation; current frontend tests/build and full Python gates passed during closeout.
- `src/trade_trace/console/reporting/trade_rows.py`, `src/trade_trace/tools/market_scan.py`, and related market-scan tests are release-ruff cleanup surfaces validated by full `ruff`, `mypy`, and `pytest -q` closeout gates.
- `README.md`, `SECURITY.md`, `docs/PRD.md`, and `docs/architecture/memory-layer.md` changed under closed Bead `trade-trace-gyg3`; they are outside this repo-audit's five finding rows but included in final quality-gate proof.

### Repo-audit artifacts added since original planning commit

```text
A	docs/reviews/repo-audit-20260521T173511Z/audit-plan.md
A	docs/reviews/repo-audit-20260521T173511Z/bd-list-all-raw.json
A	docs/reviews/repo-audit-20260521T173511Z/bead-bodies/CFB-20260521-001.md
A	docs/reviews/repo-audit-20260521T173511Z/bead-bodies/CSS-20260521-001.md
A	docs/reviews/repo-audit-20260521T173511Z/bead-bodies/DCR-20260521-001.md
A	docs/reviews/repo-audit-20260521T173511Z/bead-bodies/THC-20260521-001.md
A	docs/reviews/repo-audit-20260521T173511Z/bead-bodies/THC-20260521-002.md
A	docs/reviews/repo-audit-20260521T173511Z/bead-bodies/epic-repo-audit-20260521.md
A	docs/reviews/repo-audit-20260521T173511Z/bead-bodies/gate-repo-audit-20260521-closeout.md
A	docs/reviews/repo-audit-20260521T173511Z/candidate-matrix.json
A	docs/reviews/repo-audit-20260521T173511Z/candidate-matrix.yaml
A	docs/reviews/repo-audit-20260521T173511Z/existing-audit-family-inventory.json
A	docs/reviews/repo-audit-20260521T173511Z/lane-build-package-ci-prior-audit-reconciliation.md
A	docs/reviews/repo-audit-20260521T173511Z/lane-cli-mcp-tooling.md
A	docs/reviews/repo-audit-20260521T173511Z/lane-console-frontend-backend.md
A	docs/reviews/repo-audit-20260521T173511Z/lane-core-storage-security.md
A	docs/reviews/repo-audit-20260521T173511Z/lane-docs-contract-release.md
A	docs/reviews/repo-audit-20260521T173511Z/lane-reports-memory-playbook.md
A	docs/reviews/repo-audit-20260521T173511Z/lane-tests-harness-contracts.md
A	docs/reviews/repo-audit-20260521T173511Z/manifest-coverage-ledger.yaml
A	docs/reviews/repo-audit-20260521T173511Z/materialization-crosswalk.json
A	docs/reviews/repo-audit-20260521T173511Z/mutation-audit.md
A	docs/reviews/repo-audit-20260521T173511Z/preflight-summary.json
```

Treatment: current-run audit artifacts/crosswalks/lanes/readbacks. They are excluded from the original product-surface audit scope, but are parsed/read back for closeout integrity.

## Final coverage artifact repair

- Rewrote `manifest-coverage-ledger.yaml` from assignment-state rows to final treatments: opened, searched, contract-checked, and grouped-with-rationale.
- Added `observation-register.md` to preserve weak signals, no-finding lane summaries, rejected/covered observations, and the 11-row funnel.
- Updated `candidate-matrix.json` and JSON-shaped `candidate-matrix.yaml` with promotion triggers for deferred rows and concrete proof notes for covered/rejected rows.
