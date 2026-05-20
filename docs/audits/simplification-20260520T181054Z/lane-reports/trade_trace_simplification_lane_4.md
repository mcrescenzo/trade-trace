# Lane 4 status: completed

Read-only simplification review: console-backend-frontend

What I did
- Inspected in-scope Console backend, frontend source, packaged static app hooks, docs references, and Console tests under:
  - src/trade_trace/console/
  - frontend/console/src/
  - frontend/console/package.json
  - docs/CONSOLE.md and related architecture references
  - tests/contracts/test_console_*.py
  - tests/console_browser/
- Verified repository state is unchanged:
  - HEAD: ffcd97420bf44c846451bd5d39596d39437d6e3e
  - branch: main
  - git status --short: clean output / no tracked modifications shown

Files created or modified
- None. Read-only lane respected: no edits, no Beads writes, no memory/Hindsight, no push/publish/delete.

Candidate records

1. candidate: console-route-catalog-single-source
   domain: console-backend-frontend
   kind: behavior-preserving simplification
   paths:
   - src/trade_trace/console/serve.py
   - frontend/console/src/main.tsx
   - frontend/console/src/api.ts
   - docs/CONSOLE.md
   evidence:
   - Backend hard-codes route catalog in serve.py:209-220.
   - Frontend independently hard-codes navigation in main.tsx:75-89.
   - Frontend independently hard-codes route tree in main.tsx:380-427.
   - docs/CONSOLE.md lists API/page expectations separately.
   observation:
   - The Console has at least three route/page maps: backend catalog, frontend nav/route tree, and docs/tests. These can drift while preserving current behavior.
   simplification:
   - Introduce one local typed route/report definition source in frontend, and derive nav items plus TanStack route creation from it.
   - Optionally expose/validate backend catalog from the same conceptual list, or reduce backend catalog to API/report-tool metadata only if the frontend no longer consumes page route discovery.
   why_bounded:
   - No feature change needed. Current visible routes and report tools remain the same.
   - Main reduction is duplication and future route-drift surface.
   duplicate_check:
   - React Console overhaul epic trade-trace-29m9 likely owns route/product UX expansion. This candidate is narrower: route/catalog single-sourcing only. Recommend attaching as a simplification subtask or merging into that epic if a page-map task already exists.

2. candidate: console-static-source-drift-guard
   domain: console-backend-frontend
   kind: packaging/test simplification
   paths:
   - frontend/console/src/main.tsx
   - src/trade_trace/console/static/app/index.html
   - src/trade_trace/console/static/app/assets/console.js
   - tests/contracts/test_console_shell.py
   evidence:
   - Packaged app is committed separately from source under src/trade_trace/console/static/app/.
   - test_console_shell.py only asserts static assets exist and index references /assets/console.js; it does not prove the built asset corresponds to current frontend source.
   - serve.py serves only packaged assets at runtime, so source/static drift can pass source-level tests while shipping older UI.
   observation:
   - Static packaged app vs source app drift is a packaging risk. Existing checks are presence/security checks, not freshness/provenance checks.
   simplification:
   - Add a small build provenance stamp or manifest generated during frontend build, e.g. source git SHA/build timestamp/package version, and assert it exists in the packaged static app.
   - Alternatively document/release-gate a single command that rebuilds and fails on dirty static asset diff.
   why_bounded:
   - Preserves app behavior and packaging model.
   - Reduces review/test ambiguity around whether source or built asset is authoritative.
   duplicate_check:
   - Not the same as dead-code hunt or React Console product overhaul. This is packaging integrity only.

3. candidate: console-table-dependency-trim
   domain: console-backend-frontend
   kind: dependency/UI primitive simplification
   paths:
   - frontend/console/package.json
   - frontend/console/src/ui/DataTable.tsx
   - frontend/console/src/main.tsx
   evidence:
   - DataTable.tsx uses @tanstack/react-table only for static column rendering/core row model.
   - No sorting/filtering/selection/pagination table state is implemented.
   - frontend/console/src search found no cursor/next_cursor UI state usage except the Page type in api.ts.
   - @tanstack/react-virtual is declared in package.json but no source usage was found in frontend/console/src.
   - @radix-ui/react-tabs is declared but no source usage was found in frontend/console/src.
   observation:
   - Current table behavior can likely be implemented with a plain HTML table loop and the existing formatCell helper, eliminating TanStack Table complexity unless near-term overhaul tasks need advanced table state.
   simplification:
   - Replace current DataTable’s TanStack Table usage with direct rows/columns rendering.
   - Remove currently unused table/virtual/tabs dependencies only if not covered by the existing dead-code hunt and not intentionally reserved for the React Console overhaul.
   why_bounded:
   - Current visible table behavior is simple: render given rows/columns and empty state.
   - No behavior expansion required.
   duplicate_check:
   - Existing deadcode hunt covers unused deps, so dependency removal should probably merge there.
   - The distinct simplification is replacing current static table primitive with plain rendering if advanced table behavior is not yet used.

4. candidate: console-chart-primitive-scope-check
   domain: console-backend-frontend
   kind: dependency/UI primitive simplification
   paths:
   - frontend/console/package.json
   - frontend/console/src/ui/ChartPanel.tsx
   - frontend/console/src/main.tsx
   evidence:
   - ChartPanel.tsx uses ECharts for a single simple non-animated bar chart over up to 8 numeric metrics.
   - main.tsx:286-290 builds a basic name/value list from summary_metrics.
   observation:
   - ECharts is a large dependency for the current behavior if only one simple metric-profile bar chart is shipped.
   simplification:
   - Either keep ECharts explicitly because the reporting-product architecture requires richer bundled charts, or replace current ChartPanel with a lightweight CSS/SVG bar chart until richer chart interactions are implemented.
   why_bounded:
   - Current behavior is static metric visualization; a lightweight local chart could preserve the view.
   duplicate_check:
   - docs/architecture/reporting-product.md explicitly states charts use bundled Apache ECharts, so this may be an architectural decision rather than an immediate candidate.
   recommendation:
   - Do not file as standalone unless the parent simplification effort is allowed to challenge that architecture. Otherwise mark as covered by React Console overhaul/charting scope.

5. candidate: console-pagination-contract-unused-by-ui
   domain: console-backend-frontend
   kind: backend/frontend contract simplification
   paths:
   - src/trade_trace/console/endpoints.py
   - src/trade_trace/console/pagination.py
   - frontend/console/src/api.ts
   - frontend/console/src/main.tsx
   - tests/contracts/test_console_pagination.py
   evidence:
   - Backend list endpoints expose cursor pagination and Page.next_cursor.
   - Frontend Page type includes next_cursor in api.ts.
   - UI fetches fixed limit=100 for trades/events pages and does not use next_cursor/cursor state.
   observation:
   - There is a richer backend pagination contract than the current UI consumes. This is not necessarily wrong, but it creates test/contract surface without current UI value.
   simplification:
   - If near-term Console UX does not add pagination controls, centralize list fetching behind a helper that intentionally requests a bounded first page and hides cursor details from page components.
   - Alternatively add minimal pagination UI under the React Console overhaul and keep the backend contract.
   why_bounded:
   - The smallest behavior-preserving simplification is frontend-only: reduce repeated pageQuery/fixed-limit calls into a useConsolePage helper while leaving backend contracts intact.
   duplicate_check:
   - Pagination UI may belong to React Console overhaul. A helper-only reduction is distinct and low risk.

Coverage accounting

Reviewed / covered:
- Backend server and route wiring:
  - src/trade_trace/console/serve.py
  - src/trade_trace/console/endpoints.py
- Frontend source app:
  - frontend/console/src/main.tsx
  - frontend/console/src/api.ts
  - frontend/console/src/ui/DataTable.tsx
  - frontend/console/src/ui/ChartPanel.tsx
  - frontend/console/src/ui/MetricCard.tsx
- Packaging/static app presence:
  - src/trade_trace/console/static/app/index.html
  - src/trade_trace/console/static/app/assets/console.js
  - src/trade_trace/console/static/app/assets/index.css
- Package dependency surface:
  - frontend/console/package.json
- Tests:
  - tests/contracts/test_console_shell.py
  - tests/console_browser/conftest.py
  - tests/console_browser/test_overview_smoke.py
  - located the rest of tests/contracts/test_console_*.py
- Docs references:
  - docs/CONSOLE.md
  - relevant console/reporting architecture references from docs/architecture/

Not filed / intentionally avoided:
- Console trade_detail or unused deps as pure dead-code removals: likely owned by existing deadcode hunt.
- Product feature gaps like filters, detail pages, dashboards, responsive polish, safety gate: likely owned by React Console product overhaul epic trade-trace-29m9.
- Docs Status header issue and console-test recipe issues: likely covered by existing bughunt.
- Any implementation edits.

Issues encountered
- None blocking.
- Static bundle is minified, so review was limited to packaging/drift signals rather than source-equivalence proof.
- Existing architecture explicitly calls for ECharts, so chart dependency simplification may be a policy/product decision rather than a clear standalone simplification.
