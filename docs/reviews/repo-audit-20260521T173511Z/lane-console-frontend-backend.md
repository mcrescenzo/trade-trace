# Lane report: console-frontend-backend

Audit run: `repo-audit-20260521T173511Z`  
Scope fingerprint: `1901b8097953e720`  
Lane: `console-frontend-backend`  
Mode: read-only audit; only this report artifact was written.

## Coverage

Assigned manifest rows treated (30):

- `frontend/console/index.html`
- `frontend/console/src/api.ts`
- `frontend/console/src/main.tsx`
- `frontend/console/src/routeCatalog.json`
- `frontend/console/src/routeCatalog.ts`
- `frontend/console/src/styles.css`
- `frontend/console/src/test/setup.ts`
- `frontend/console/src/ui/ChartPanel.tsx`
- `frontend/console/src/ui/DataTable.test.tsx`
- `frontend/console/src/ui/DataTable.tsx`
- `frontend/console/src/ui/MetricCard.test.tsx`
- `frontend/console/src/ui/MetricCard.tsx`
- `frontend/console/src/ui/help.test.tsx`
- `frontend/console/src/ui/help.tsx`
- `frontend/console/tailwind.config.ts`
- `frontend/console/vitest.config.ts`
- `src/trade_trace/console/__init__.py`
- `src/trade_trace/console/endpoints.py`
- `src/trade_trace/console/logs.py`
- `src/trade_trace/console/pagination.py`
- `src/trade_trace/console/reporting/__init__.py`
- `src/trade_trace/console/reporting/adapter.py`
- `src/trade_trace/console/reporting/filter_state.py`
- `src/trade_trace/console/reporting/metric_glossary.py`
- `src/trade_trace/console/reporting/position_rows.py`
- `src/trade_trace/console/reporting/trade_rows.py`
- `src/trade_trace/console/route_catalog.json`
- `src/trade_trace/console/security.py`
- `src/trade_trace/console/serve.py`
- `src/trade_trace/console/static/favicon.svg`

Cross-reference scope also included console-related docs/tests and packaged static app provenance as supporting evidence, while excluding generated/cache assets from decisive source claims except via provenance hashes.

## Candidate CFB-20260521-001

- **Title:** Decisions page multi-select filter appends repeated `decision_type` params, but FastAPI/backend only accepts one scalar value.
- **Remediation track:** bughunt
- **Owner track:** console-frontend-backend
- **Affected paths/symbols:**
  - `frontend/console/src/main.tsx`: `FilterBar`, `DecisionsPage`, `tableFilterParams`
  - `frontend/console/src/api.ts`: `pageQuery`
  - `src/trade_trace/console/serve.py`: `/api/console/decisions` route
  - `src/trade_trace/console/endpoints.py`: `decisions_list`
- **Observed facts (file:line evidence):**
  - The shared filter UI renders Decision type as a multi-select and builds `decision_type` as an array of selected option values: `frontend/console/src/main.tsx:179-181`.
  - `pageQuery` serializes array values by appending the same query key once per selected item: `frontend/console/src/api.ts:189-199`.
  - `DecisionsPage` passes `decision_type` through `tableFilterParams(filter, ['instrument_id', 'decision_type'])` to `/api/console/decisions`: `frontend/console/src/main.tsx:1750-1754`.
  - The FastAPI decisions handler accepts `decision_type: str | None = None`, not `list[str]`: `src/trade_trace/console/serve.py:275-280`.
  - The pure backend function also accepts and applies only one `decision_type: str | None`, appending `type = ?` once: `src/trade_trace/console/endpoints.py:300-318`.
  - The adjacent Trades endpoint is explicitly multi-value aware (`decision_type: list[str] | None` in FastAPI and `str | Sequence[str] | None` in backend): `src/trade_trace/console/serve.py:295-314`; `src/trade_trace/console/reporting/trade_rows.py:222-264`.
- **Inferences:** When a user selects multiple decision types on the Decisions page, the frontend URL can contain repeated `decision_type` parameters, but the route/backend contract is scalar. FastAPI will not preserve the full selected set for the scalar handler, so the UI likely filters by only one selected value (or has framework-dependent behavior) instead of matching all selected values.
- **Assumptions:** The intended Decisions page behavior is consistent with the multi-select UI and with Trades multi-value filtering: selecting multiple decision types should return rows matching any selected type.
- **Open questions:** Should `/api/console/decisions` support repeated `decision_type` values, or should the Decisions page use a single-select control? Product wording says "Decision type distinguishes..." but the UI is shared and currently multi-select.
- **Validation command/gap:** Add/adjust a backend route/endpoint test that calls `/api/console/decisions?decision_type=actual_enter&decision_type=watch` (or equivalent seeded types) and asserts both types are represented. A lightweight frontend unit/integration test should assert `pageQuery` + Decisions filter contract. I did not execute mutating fixes.
- **Prior match status:** Partial historical overlap only. The inventory includes closed Console filter/routing work (`trade-trace-dzlh`, `trade-trace-3zwt` title "Console table filter forms use URL hash state...", and Console product-overhaul gates), but no open/current exact match for scalar Decisions `decision_type` multi-select mismatch was found in the provided inventory.
- **Duplicate/overlap notes:** Related to closed filter-contract work, but distinct affected endpoint (`/api/console/decisions`) and failure mode (multi-value parameter narrowed to scalar).
- **Recommended disposition:** Accept as a new low/medium-priority bug unless maintainers decide Decisions should be single-select; then fix UI to match backend.
- **Proposed Bead:**
  - **Title:** Align Decisions page multi-select `decision_type` filter with backend route contract
  - **Type:** bug
  - **Labels:** `bug`, `bughunt`, `console`, `frontend`, `api-contract`, `repo-audit-20260521`
  - **Acceptance criteria:**
    1. Either `/api/console/decisions` accepts repeated `decision_type` values and returns rows matching any selected type, or the frontend Decisions page presents a single-select control and serializes only one value.
    2. Pure endpoint and/or HTTP route tests cover repeated decision type query params or the single-select invariant.
    3. Frontend test or route-level smoke verifies the Decisions filter UI/query serialization matches the backend contract.

## Non-candidates / retained findings

- **Static app provenance is currently coherent.** `src/trade_trace/console/static/app/provenance.json:3-16` records source and asset hashes. A SHA-256 verification command over listed sources/assets produced no mismatches. The paired route catalog hashes for `frontend/console/src/routeCatalog.json` and `src/trade_trace/console/route_catalog.json` are identical in provenance (`8aad0...` at lines 7-8), and direct file reads showed matching JSON contents.
- **Read-only FastAPI posture is explicit and cross-referenced.** `serve.py` builds the app with docs disabled, mounts packaged assets, opens database handles via `open_database_readonly()`, and applies security middleware (`src/trade_trace/console/serve.py:124-132`, `154-162`). Security headers enforce self-only CSP/no inline/no eval and no-store responses (`src/trade_trace/console/security.py:26-57`).
- **Lazy-write denial remains documented in code.** The backend declares `LAZY_WRITE_DENY_SET` with `report.coach` and `signal.scan`, and comments tie it to docs-inspection tests (`src/trade_trace/console/endpoints.py:32-41`).
- **Route catalog duplication is controlled rather than currently stale.** Frontend imports `./routeCatalog.json` via `routeCatalog.ts` (`frontend/console/src/routeCatalog.ts:1-43`); backend `/api/console/catalog` reads packaged `route_catalog.json` (`src/trade_trace/console/serve.py:220-229`). The source copies are line-for-line equal in this checkout.
- **Packaged generated assets were not line-audited.** `src/trade_trace/console/static/app/assets/console.js`, `index.css`, and generated `index.html` were treated through provenance, per manifest caveat; decisive claims use source files plus hash verification.

## Commands/searches run

- Parsed `manifest-coverage-ledger.yaml` with Python to enumerate rows where `owner_lane == console-frontend-backend`.
- Read assigned source files under `frontend/console` and `src/trade_trace/console` with `read_file`/`search_files`.
- Searched console tests/docs references with `search_files` for `console`, route, static, provenance, and filter-contract terms.
- Read `existing-audit-family-inventory.json` and searched for Console/filter/static/route overlap.
- Verified packaged static provenance hashes with:

```bash
python - <<'PY'
import hashlib, json, pathlib
root=pathlib.Path('/home/hermes/code/trade-trace')
prov=json.load(open(root/'src/trade_trace/console/static/app/provenance.json'))
for p,h in prov['source_hashes'].items():
    pp=root/'frontend/console'/p
    if not pp.exists(): print('missing',p); continue
    got=hashlib.sha256(pp.read_bytes()).hexdigest()
    if got!=h: print('MISMATCH source',p,h,got)
for p,h in prov['asset_hashes'].items():
    pp=root/'src/trade_trace/console/static/app'/p
    got=hashlib.sha256(pp.read_bytes()).hexdigest()
    if got!=h: print('MISMATCH asset',p,h,got)
PY
```

No output indicated no mismatches.

## Caveats

- I did not run package-manager installs, frontend builds, formatters, Playwright/browser tests, or server processes, consistent with the read-only lane constraints.
- I did not create/update Beads.
- The only workspace modification by this subagent is this lane report artifact.
