# Central simplification matrix — 20260520T181054Z

Repo: `/home/hermes/code/trade-trace` at `ffcd97420bf44c846451bd5d39596d39437d6e3e`.
Epic: `trade-trace-w3vs` / label `simplification:20260520`.

Disposition rule: candidates were accepted only when they were not already covered by the closed `simplification:20260519-exhaustive` backlog or current open deadcode/bughunt/console/agent-ergonomics epics. Existing closed simplification beads are treated as historical coverage; residual or potentially incomplete prior work is routed through one reconciliation bead rather than many duplicate implementation beads.

## Counts

- Raw candidates: 32
- Accepted direct simplification tasks: 8 candidates materialized into 8 task beads
- Investigation/design-first tasks: 4 beads
- Merged/folded into existing open/closed/reconciliation work: 15 candidates
- Rejected/deferred below threshold or intentional complexity: 5 candidates

## Materialized ID map

- SIMP20-004 -> `trade-trace-fxxm`
- SIMP20-005 -> `trade-trace-d2jv`
- SIMP20-009 -> `trade-trace-m29q` (investigation/design-first)
- SIMP20-011 -> `trade-trace-lu6g`
- SIMP20-012 -> `trade-trace-4v31`
- SIMP20-017 -> `trade-trace-y0b2` (investigation/design-first)
- SIMP20-019 -> `trade-trace-9gp0`
- SIMP20-020 -> `trade-trace-lsi5` (investigation/design-first)
- SIMP20-021 -> `trade-trace-7v2i`
- SIMP20-022 + SIMP20-023 -> `trade-trace-10x6`
- SIMP20-029 -> `trade-trace-gis0`
- SIMP20-014 + SIMP20-015 + SIMP20-016 + SIMP20-027 + SIMP20-028 -> `trade-trace-2drt` (residual reconciliation investigation)
- Final verification -> `trade-trace-z5bd`

## Matrix

| ID | Source lane | Title / root issue | Paths / evidence summary | Disposition | Materialization / merge |
|---|---|---|---|---|---|
| SIMP20-001 | cli-mcp-contracts | Centralize repeated tool example lookup helper | `_examples_for` duplicated in 8 tool modules; see lane_0 lines 26-152 and evidence probe. | merge | Merge into open agent-ergonomics/schema work (`trade-trace-evwe`/`3i77`/`r1mt`) rather than new simplification bead. |
| SIMP20-002 | cli-mcp-contracts | Share registry catalog projection between MCP list-tools and `tool.schema` | `mcp_server.py:mcp_tool_specs` and `tools/journal.py:_tool_schema` project ToolRegistry differently; lane_0 lines 155-313. | merge | Merge into open `trade-trace-evwe`/schema contract work. |
| SIMP20-003 | cli-mcp-contracts | Centralize CLI exit-code mapping | `_emit_cli_error` and main post-dispatch path duplicate error-code mapping; lane_0 lines 316-436. | merge | Merge/defer under open error/actionability contract work; no standalone bead. |
| SIMP20-004 | storage-events-security | Centralize POSIX file/dir permission helpers | `storage/database.py`, `tools/admin.py`, `exporter.py` each implement chmod 0600/0700 variants; lane_1 lines 27-67. | accept | New task. |
| SIMP20-005 | storage-events-security | Extract generic safe-relative-path / resolve-under-root helpers | `tools/admin.py` model-specific `_safe_model_relpath` reused by restore with wrapped errors; lane_1 lines 69-109. | accept | New task with characterization tests first. |
| SIMP20-006 | storage-events-security | Migration registry/fingerprint metadata alignment | Three parallel migration structures; lane_1 lines 111-149. | merge/defer | Covered by closed `6x3j` + `y5pj` + `58ic`; no new bead unless future migration work reopens metadata-spec question. |
| SIMP20-007 | storage-events-security | JSONL envelope shape duplication | `EventRecord.to_jsonl_line` and exporter envelope builder overlap; lane_1 lines 151-179. | merge | Merge into open deadcode/serialization owner `trade-trace-0apb`. |
| SIMP20-008 | storage-events-security | Remove tiny `events.unit_of_work.transaction()` wrapper | Single test-only wrapper; lane_1 lines 182-204. | reject | Below threshold / API-surface cleanup not worth a new simplification bead. |
| SIMP20-009 | ledger-tools-projections | Shared forecast write kernel for `forecast.add` and `forecast.supersede` | Duplicate row/outcome/payload/auto-score mechanics in `tools/ledger.py`; stale comment indicates drift; lane_2 lines 47-71. | investigation | New investigation/design-first bead because idempotency/atomicity is load-bearing. |
| SIMP20-010 | ledger-tools-projections | Generic simple-ledger idempotent insert helper | Repeated skeleton in venue/instrument/snapshot/thesis/source.attach; lane_2 lines 72-104. | defer | Too likely to become shallow framework; revisit after narrower helpers land. |
| SIMP20-011 | ledger-tools-projections | Named row access for positions projection replay | `projections.py` uses numeric tuple indexes across 13 selected columns; lane_2 lines 129-154. | accept | New task. |
| SIMP20-012 | ledger-tools-projections | Source.attach target metadata mapping | Target table mapping and registration are separate; lane_2 lines 155-172. | accept | New task. |
| SIMP20-013 | ledger-tools-projections | Rename stale memory_node_stats projection no-op comments/tests | Tests still describe deferred/no-op behavior though implementation rebuilds stats; lane_2 lines 105-128. | folded | Fold into SIMP20-011 acceptance as a small test-comment cleanup, not standalone. |
| SIMP20-014 | reports-memory-playbook | Report tool adapter boilerplate | 9 report wrappers repeat open_db/close/error/meta propagation; lane_3 lines 29-80. | reconciliation | Do not create duplicate of closed `qnxt`; route through residual reconciliation bead. |
| SIMP20-015 | reports-memory-playbook | Centralize report envelope construction | 8+ report modules hand-build summary/groups/truncated/next_cursor; lane_3 lines 82-120. | reconciliation | Reconcile against closed `qnxt`; future follow-up only if acceptance was materially incomplete. |
| SIMP20-016 | reports-memory-playbook | Unify report filter validation/support with review.bundle | `reports.py` and `review_bundle.py` duplicate filter error conversion; lane_3 lines 122-156. | reconciliation | Reconcile against closed `x0po` and current review_bundle contracts. |
| SIMP20-017 | reports-memory-playbook | Split `memory.recall` orchestration into helpers | `_memory_recall` is 237 lines with parse/rank/format/log/meta phases; lane_3 lines 158-200. | investigation | New investigation/design-first bead due ranking/budget/logging sensitivity. |
| SIMP20-018 | reports-memory-playbook | Write-tool idempotency helper across strategy/playbook/memory | Replay/response patterns repeated; lane_3 lines 201-242. | defer | Needs sharper grouping and replay assertions; no new bead now. |
| SIMP20-019 | reports-memory-playbook | Normalize memory-local `meta_json` object parsing | `memory.retain` and `memory.reflect` duplicate parsing/object validation; lane_3 lines 243-275. | accept | New task limited to memory.py; cross-tool behavior changes out of scope. |
| SIMP20-020 | reports-memory-playbook | Decompose `review.bundle` while preserving bundle hash | Handler mixes filter, fetch, reports, redaction, hash/meta; lane_3 lines 277-312. | investigation | New investigation/design-first bead due hash/order/redaction sensitivity. |
| SIMP20-021 | reports-memory-playbook | Centralize strategy create/update response construction | `_strategy_row_to_dict` exists but create/update/replay manually build same shape; lane_3 lines 314-345. | accept | New small task. |
| SIMP20-022 | console-backend-frontend | Single-source Console route/page catalog | Backend route catalog, frontend nav, frontend route tree, docs diverge; lane_4 lines 23-45. | accept | New task combined with SIMP20-023. |
| SIMP20-023 | console-backend-frontend | Static source/build drift guard | Packaged static app is committed separately; tests assert presence not freshness; lane_4 lines 47-68. | accept | New task combined with SIMP20-022. |
| SIMP20-024 | console-backend-frontend | Simplify current DataTable / dependency usage | TanStack Table used for static rendering; unused deps; lane_4 lines 70-93. | merge | Merge into open `trade-trace-nlp0`/`trade-trace-hdlx`; no standalone bead. |
| SIMP20-025 | console-backend-frontend | Replace/justify ECharts for simple ChartPanel | ECharts used for one simple bar chart; docs explicitly choose ECharts; lane_4 lines 95-114. | reject/defer | Intentional architecture/product decision unless user wants chart-dependency policy review. |
| SIMP20-026 | console-backend-frontend | Hide unused pagination cursor details behind frontend helper | Backend cursor contract exists; UI first-page only; lane_4 lines 116-137. | merge/defer | Covered by closed `1kkv.14` and open Console overhaul; no standalone row. |
| SIMP20-027 | tests-docs-build | Remove residual per-file `home` alias fixtures | Current AST still finds 37 `home` helpers after prior qs5v close; lane_5 lines 34-79. | reconciliation | Route through residual reconciliation bead with qs5v readback. |
| SIMP20-028 | tests-docs-build | Consolidate repeated MCP/envelope dispatch helpers | Current AST finds 20 `_mcp`, 11 `_envelope`, 8 `_db`; lane_5 lines 80-125. | reconciliation | Route through residual reconciliation bead with qs5v readback. |
| SIMP20-029 | tests-docs-build | Split `journal.fixture_seed` into builder profiles | `tools/fixture.py` 687 lines mixes deterministic IDs, base seed, rich overlays, reporting/browser fixtures; lane_5 lines 126-182. | accept | New task; distinct from qs5v test-helper cleanup. |
| SIMP20-030 | tests-docs-build | Fix release workflow dynamic version check | Workflow reads removed `project.version`; lane_5 lines 184-234. | merge | Merge into open bug `trade-trace-nkfz` / prior release-gate work `42vr`. |
| SIMP20-031 | tests-docs-build | Extract docs markdown validation helpers | Docs tests mix link/status/version checks; current docs tests fail due known kz0h issue; lane_5 lines 236-281. | merge/defer | Merge into open `trade-trace-kz0h` or prior `ensw`; no new bead until status bug fixed. |
| SIMP20-032 | tests-docs-build | Remove tracked/generated pycache artifacts | On-disk pycache noise; `git ls-files` count is 0. | reject | Not tracked; local/review noise only, not repo simplification backlog. |

## Advisor reconciliation

Advisor gate agreed with the reduced materialization shape: avoid bulk-materializing all 32, create only uncovered work, merge CLI/MCP/JSONL/release/docs/console-dependency findings into existing work, and use one reconciliation bead for residual prior simplification overlap.
