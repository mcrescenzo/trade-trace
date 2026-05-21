# Lane audit packet: `reports-memory-playbook`

Audit run: `repo-audit-20260521T173511Z`  
Scope fingerprint: `1901b8097953e720`  
Lane scope: reports, memory retain/recall/reflect, playbook, strategies, projections/positions.  
Mode: read-only lane audit; only this lane artifact was written.

## Inputs and searches

- Read governing artifacts: `manifest-coverage-ledger.yaml`, `existing-audit-family-inventory.json`, `audit-plan.md`.
- Extracted assigned manifest rows with:
  - `python - <<'PY' ... yaml.safe_load(...); if owner_lane == 'reports-memory-playbook' ... PY`
- Source/test searches:
  - `search_files` over `src/trade_trace` for `TODO|pass|NotImplemented|FIXME|unsupported|ReportFilter|json.loads|playbook_id|memory|strategy_id|position_id`.
  - `search_files` over `tests` for `playbook_adherence|memory_recall|memory.reflect|memory.retain|ReportFilter|position_id|strategy_id`.
  - `search_files` over repo for `MemoryNode|NodeType|models.memory`.
  - `search_files` over source for `process_filter(`, report envelope, projection rebuilders, memory/playbook/report registrations.
- Targeted validation command:
  - `python -m pytest -q tests/integration/test_memory_layer.py tests/integration/test_schema.py tests/contracts/test_json_schema_derivation.py`
  - Result: `65 passed in 1.13s`.

## Coverage treatment by assigned manifest row

| Manifest row | Treatment | Evidence / notes |
| --- | --- | --- |
| `src/trade_trace/contracts/report_filter.py` | opened + searched | Canonical `ReportFilter` schema has strict `extra="forbid"` fields at lines 25-152 and strategy sentinel semantics at lines 154-167. |
| `src/trade_trace/models/memory.py` | opened + searched | `MemoryNode`/`NodeType` public model exists at lines 17-41; stale module docstring noted as candidate RMP-001. |
| `src/trade_trace/projections.py` | opened + searched + targeted tests | Position projection rebuild kernel at lines 60-168; memory stats rebuild handles corrupt recall JSON with skip counter at lines 356-414. Reachability via `tools/ledger.py:22,1021`, `tools/journal.py:182-218`, `tools/fixture.py:524,699`. |
| `src/trade_trace/reports/__init__.py` | searched | Public report exports found by direct symbol search: `report_playbook_adherence` imported/exported at lines 39 and 78. |
| `src/trade_trace/reports/_envelope.py` | searched | Standard report result helper is imported by report modules; `standard_report_result` definition found at line 13 and usages across assigned reports. |
| `src/trade_trace/reports/_filter_support.py` | opened + searched | Per-report filter support registry at lines 46-95; enforcement and applied-view helper at lines 125-182. |
| `src/trade_trace/reports/audit_readiness.py` | searched | Included in report package; no lane-specific bug/deadcode candidate found in scoped searches. |
| `src/trade_trace/reports/buckets.py` | searched | Report helper surface; no decisive unused/stale finding from source-scoped searches. |
| `src/trade_trace/reports/calibration.py` | searched | Uses standard envelope and is tool-reachable through `tools/reports.py:28,262-289,670-682`; no additive issue found. |
| `src/trade_trace/reports/coach.py` | searched | Uses `process_filter` at `reports/coach.py:78`; no additive issue found. |
| `src/trade_trace/reports/compare.py` | searched | Uses standard envelope at lines 166 and 237; no additive issue found. |
| `src/trade_trace/reports/decision_velocity.py` | searched | Uses `process_filter` at line 38 and standard envelope at line 97; no additive issue found. |
| `src/trade_trace/reports/integrity.py` | searched | Report helper surface; no additive issue found. |
| `src/trade_trace/reports/opportunity.py` | searched | Uses `process_filter` at line 189; no additive issue found. |
| `src/trade_trace/reports/playbook_adherence.py` | opened + searched | Top-level `playbook_id` and `strategy_id` filters are applied in SQL at lines 61-66; empty `ReportFilter` enforcement at lines 49-50; tool wrapper reachability via `tools/reports.py:35,296-323,685-694` and `tools/playbook.py:704-722`. |
| `src/trade_trace/reports/pnl.py` | opened + searched | Uses `process_filter` at line 45 and positions projection at lines 46-50; open mark coverage logic at lines 56-64. |
| `src/trade_trace/reports/risk.py` | searched | Uses `process_filter` at line 90 and standard envelope at line 191; no additive issue found. |
| `src/trade_trace/reports/source_quality.py` | searched | Report surface inspected by scoped search; no additive issue found. |
| `src/trade_trace/reports/tag_aggregates.py` | searched | Uses `process_filter` at line 67 and standard envelope at line 139; no additive issue found. |
| `src/trade_trace/reports/unscored.py` | searched | Uses `process_filter` at line 29 and standard envelope at line 92; no additive issue found. |
| `src/trade_trace/reports/watchlist.py` | searched | Uses `process_filter` at line 38 and standard envelope at line 97; no additive issue found. |
| `src/trade_trace/storage/migrations/m006_memory_layer.py` | searched + covered by targeted tests | Memory schema indirectly validated by `tests/integration/test_memory_layer.py`; no migration deadcode/bug candidate found. |
| `src/trade_trace/storage/migrations/m008_playbooks.py` | searched + covered by targeted tests | Playbook schema indirectly validated by playbook/report tests and targeted schema suite; no additive issue found. |
| `src/trade_trace/storage/migrations/m010_strategy_id_new_row_triggers.py` | searched + targeted tests | Strategy-id new-row validation covered by `tests/integration/test_schema.py`; test command passed. |

## Accepted candidates

### RMP-001 — Refresh stale memory model module contract now that the memory layer is implemented

- **Title:** Refresh stale memory model module contract now that the memory layer is implemented
- **Remediation track:** technical-debt / simplification
- **Owner track:** reports-memory-playbook
- **Affected paths/symbols:** `src/trade_trace/models/memory.py` module docstring; `MemoryNode`, `NodeType` public model surface.
- **Observed facts with file:line evidence:**
  - `src/trade_trace/models/memory.py:1-6` still says "Memory layer model stubs", says M3 will "light these up with real validation and edge-endpoint checks", and says M0 ships only a stable import path.
  - Live memory implementation is no longer a stub: `src/trade_trace/tools/memory.py:1-18` documents and implements `memory.retain`, `memory.reflect`, `memory.link`, and `memory.recall`; `memory.reflect` writes a reflection plus `about` edge atomically at `src/trade_trace/tools/memory.py:462-540`; `memory.recall` ranks and writes recall events at `src/trade_trace/tools/memory.py:682-722` and `src/trade_trace/tools/memory.py:820-839`.
  - The model is a public surface: `src/trade_trace/models/__init__.py:28,35-36` exports `MemoryNode` and `NodeType`; `src/trade_trace/tools/journal.py:141` includes `MemoryNode` in schema export; tests import and instantiate the public model at `tests/test_smoke.py:19-20,47,67` and check schema export at `tests/integration/test_journal_init.py:122,127`.
- **Inferences:** The stale docstring is not a runtime bug, but it is a maintenance/contract footgun: readers of the model source are told memory is a future/stub surface even though the tools and tests treat it as live. Keeping the import-stability sentence is fine, but the M0/M3 stub language should be removed or replaced with a current contract summary.
- **Assumptions:** Public source docstrings are considered part of maintainability/docs-contract for this audit lane even when not rendered in user docs.
- **Open questions:** Should `MemoryNode.model_config = ConfigDict(extra="allow")` remain for forward-compatible schema export, or should the refreshed docstring explicitly justify extra fields? No behavior change is proposed without separate design review.
- **Validation command/gap:** Targeted tests passed: `python -m pytest -q tests/integration/test_memory_layer.py tests/integration/test_schema.py tests/contracts/test_json_schema_derivation.py` -> `65 passed`. No code-change validation was run because this lane is read-only.
- **Prior match status:** `new` / low-risk delta. Nearby closed prior issues cover memory atomicity, recall decomposition, meta-json validation, endpoint validation, and replay taxonomy (`trade-trace-1up`, `trade-trace-y0b2`, `trade-trace-pz23`, `trade-trace-arcx`, `trade-trace-40dz`, `trade-trace-dew2` in inventory), but none directly cover the stale `models/memory.py` module contract.
- **Duplicate/overlap notes:** Not a duplicate of closed memory bug/debt items; it is documentation/contract cleanup after those items landed. If parent prefers not to materialize source-docstring cleanups, this can be folded into general docs-contract hygiene rather than a Bead.
- **Recommended disposition:** Accept as a small technical-debt cleanup if the repo-audit backlog is materializing low-risk source-contract drift; otherwise reject as below Bead threshold and record as lane note.
- **Proposed Bead:**
  - **Type:** task
  - **Labels:** `repo-audit`, `audit-run:20260521T173511Z`, `track:maintenance`, `domain:reports-memory-playbook`, `tech-debt`, `docs-contract`
  - **Title:** Refresh stale memory model module contract now that the memory layer is implemented
  - **Acceptance:** Update `src/trade_trace/models/memory.py` docstring so it no longer describes the model as M0 stubs/future M3 work; describe the current public model/schema-export role and any intentional forward-compatibility such as `extra="allow"`; run smoke/schema tests that import/export `MemoryNode`.

## Rejected / non-additive findings

- **ReportFilter ignored-by-report concerns:** Closed inventory already contains `trade-trace-ke1` / `trade-trace-d4k` and simplification follow-ups. Current code has a centralized support registry and enforcement (`src/trade_trace/reports/_filter_support.py:46-95,125-182`), and representative reports call it (`playbook_adherence.py:49-50`, `pnl.py:44-45`, `decision_velocity.py:38`). No additive bug found.
- **Playbook adherence nonexistent playbook:** Closed inventory contains `trade-trace-pjzs`. Current report SQL honors top-level `playbook_id` by joining `playbook_versions` and filtering `pv.playbook_id = ?` (`src/trade_trace/reports/playbook_adherence.py:52-66`). No regression evidence in this lane.
- **Projection P&L sign / position replay:** Closed inventory contains `trade-trace-drt` and `trade-trace-7h2u`. Current projection code documents signed quantity conventions and rejects invalid reversals (`src/trade_trace/projections.py:83-93,257-305`). Targeted tests passed; no additive bug found.
- **Memory.retain/meta_json and endpoint validation:** Closed inventory contains `trade-trace-arcx` and `trade-trace-40dz`. Current memory code validates `meta_json` object shape at retain boundary (`src/trade_trace/tools/memory.py:79-112,237-243`) and includes `playbook_version` in endpoint table (`src/trade_trace/tools/memory.py:151-168`). No regression evidence found.

## Caveats

- This lane used direct file reads plus source-scoped searches; it did not run a full repo test suite, static type checker, or mutate Beads.
- Some implementation files central to memory/playbook/report tool registration are assigned to `cli-mcp-tooling` in the manifest. I used them only as cross-reference evidence for reachability/behavior, not as primary ownership claims.
- Generated assets, caches, and build artifacts were not used as decisive evidence.

## Side-effect declaration

- Created/modified only: `docs/reviews/repo-audit-20260521T173511Z/lane-reports-memory-playbook.md`.
- No Beads writes, source/product/test edits, destructive commands, package-manager cleanup/installers, pushes, publishes, formatters, or shared-service mutations were performed.
