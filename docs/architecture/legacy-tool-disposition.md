# Legacy Tool Disposition Matrix

> Status: **shipped** as of 2026-07-09 for the pre-1.0 removal policy in
> [`contracts.md` §8.1](contracts.md#81-tool-removal-pre-10). Runtime source:
> `build_registry()` entries whose metadata has
> `catalog_visibility="legacy"`.

This record covers only currently registered legacy-visible tools. Current
runtime behavior for every row below: hidden from the default public catalog,
visible to explicit legacy inspection (plus admin inspection where marked
`admin`), metadata-described through `tool.schema` / MCP specs, and still
dispatchable by name.

Decision meanings:

- `keep`: retain as a back-compat alias or compatibility surface; removal would
  break active alias, import/replay, fixture, or documented compatibility use.
- `defer`: removal might still be appropriate before 1.0, but this review did
  not find enough unambiguous evidence to delete it safely without a coupled
  code, docs, tests, and release-note change.
- `remove`: approved for hard deletion in the same change that updates runtime,
  tests, docs, and release notes. No rows are `remove` in this pass.

Reviewed outcome: **no hard deletions are approved by this review**. The matrix
keeps clear compatibility aliases and defers all standalone legacy handlers or
semantically questionable redirects to owner-specific cleanup.

<!-- legacy-tool-disposition-matrix:start -->
| Tool | Decision | Key runtime metadata | Evidence and rationale | Removal condition |
|---|---|---|---|---|
| `agent.bootstrap` | keep | `redirect=report.bootstrap`; read; non-admin | Report registration defines it as the agent-facing alias for `report.bootstrap`; integration tests still assert schema/data parity for the alias. | Delete only with agent-continuity docs/test migration to `report.bootstrap` and a release-note entry. |
| `agent.next_actions` | keep | `redirect=report.work_queue`; read; non-admin | Report registration defines it as the safe projection/alias over `report.work_queue`; work-queue and golden tests still exercise the alias. | Delete only with all suggested-process-call/docs/tests moved to `report.work_queue` and a release-note entry. |
| `decision.record_adherence` | keep | `renamed_to=playbook.record_adherence`; write; non-admin | Core overlay keeps this dispatch-only legacy alias for historic JSONL/import replay while the public target remains `playbook.record_adherence`. | Delete only after replay/import compatibility is explicitly retired. |
| `forecast.supersede` | defer | `redirect=forecast.add`; write; non-admin | It has a distinct append-only supersede handler and shipped scoring docs still name it as the recovery path; existing dogfood notes flag the redirect as semantically unsafe to follow blindly. | Owner decision needed: unhide/fix replacement semantics or delete with corrected scoring docs and release note. |
| `idea.capture` | defer | `redirect=memory.retain`; write; non-admin | Legacy idea capture remains registered and is referenced by bundle-status promotion metadata; `memory.retain` is related but not proven as a drop-in replay replacement here. | Remove only after idea-capture replay/metadata paths are migrated or declared unsupported. |
| `import.csv_fills` | defer | `redirect=import.commit`; write; non-admin | CSV adapter still has a registered handler; deletion would require replacing CSV import docs/tests with JSONL-only `import.commit` flows. | Remove only with CSV-specific tests/docs deleted or redirected and release notes. |
| `import.validate` | defer | `redirect=import.commit`; read; non-admin | The validation handler remains registered as the dry-run/read side of the importer; this pass did not prove every caller can use `import.commit` dry-run instead. | Remove only with importer contract/docs/tests moved to the replacement mode. |
| `instrument.add` | defer | `redirect=market.bind`; write; non-admin | Legacy ledger writer is still used by fixtures, import/replay paths, market-scan planning, and CLI/MCP schema tests. | Remove only after all internal callers and replay fixtures stop requiring instrument rows directly. |
| `journal.bundle.plan` | defer | `removed_in=0.0.2`; read; non-admin | Bundle plan remains registered and is still referenced by market-scan orchestration/docs as a local primitive-plan surface. | Remove only with market-scan/bundle docs and tests migrated. |
| `journal.bundle.status` | defer | `removed_in=0.0.2`; read; non-admin | Bundle status remains a final-check surface for legacy bundle and market-scan flows. | Remove only with replacement status checks documented and tested. |
| `journal.rescan_scoring` | defer | `redirect=journal.rebuild_projections`; read; non-admin | Legacy scoring rescan remains a registered handler; `journal.rebuild_projections` is admin/maintenance-oriented, so replacement parity needs explicit review. | Remove only with scoring-rescan docs/tests moved to the admin rebuild path. |
| `market.scan.dry_run` | defer | `redirect=market.bind`; read; non-admin | Market-scan dry-run is orchestration sugar over multiple primitives, not just a simple bind alias. | Remove only when the market-scan contract is retired or rewritten around `market.bind`. |
| `market.scan.promote` | defer | `redirect=market.bind`; write; non-admin | Promote executes a planned primitive sequence; replacement with `market.bind` alone is not proven equivalent. | Remove only with market-scan promotion tests/docs retired or replaced. |
| `memory.reindex` | defer | `removed_in=0.0.2`; write; admin | Admin-gated legacy maintenance tool remains registered for defense-in-depth catalog filtering. | Remove only with explicit embeddings/reindex policy and release-note coverage. |
| `model.import` | defer | `removed_in=0.0.2`; write; admin | README still documents the admin-tier legacy model import command for pre-staged local embeddings assets. | Remove only after embeddings setup docs and admin tests no longer depend on it. |
| `model.warm` | defer | `removed_in=0.0.2`; read; non-admin | Legacy warm path remains registered without a canonical redirect; no safe deletion evidence in this review. | Remove only with embeddings warmup behavior declared unsupported or replaced. |
| `outcome.add` | keep | `renamed_to=resolution.add`; write; non-admin | Core overlay aliases the old outcome name to the canonical `resolution.add`; this is a straightforward v0.0.2 rename compatibility path. | Delete only after the rename compatibility window and release-note entry. |
| `playbook.adherence` | keep | `redirect=report.playbook_adherence`; read; non-admin | Legacy wrapper scopes the public report by playbook; report-catalog planning notes call out the shared compatibility surface. | Delete only with docs/tests moved to `report.playbook_adherence` and equivalent filter guidance. |
| `playbook.create` | keep | `redirect=playbook.upsert`; write; non-admin | Core overlay registers it as a hidden alias backed by `playbook.upsert`. | Delete only after alias compatibility is retired in release notes. |
| `playbook.list` | defer | `redirect=playbook.upsert`; read; non-admin | Direct read handler remains registered; `playbook.upsert` is primarily a write surface, so read-mode replacement needs explicit docs/tests. | Remove only after playbook read flows have a public replacement. |
| `playbook.list_versions` | defer | `redirect=playbook.upsert`; read; non-admin | Version listing is a distinct read handler used to inspect lineage; replacement via `playbook.upsert` is not established in this pass. | Remove only with a documented public lineage-read replacement. |
| `playbook.show` | defer | `redirect=playbook.upsert`; read; non-admin | Show returns row plus version history; deletion needs a replacement read path, not just the write upsert surface. | Remove only after playbook detail reads are moved to a public report/read tool. |
| `reflection.prompt_for_outcome` | defer | `removed_in=0.0.2`; read; non-admin | Prompt assembly was slated out of catalog, but the deterministic packet builder is still registered and no replacement was validated here. | Remove only with prompt-builder docs/tests retired or moved outside the registry. |
| `resolve.pending` | defer | `redirect=report.work_queue`; read; non-admin | Pending-resolution discovery has a mirrored query lineage; replacement with the broad work queue needs explicit result-shape migration. | Remove only after resolution-pending docs/tests use `report.work_queue`. |
| `resolve.record` | keep | `redirect=resolution.add`; write; non-admin | Core overlay aliases the legacy resolve write to `resolution.add`; replacement is canonical and public. | Delete only after the resolution rename compatibility window and release-note entry. |
| `source.add` | defer | `removed_in=0.0.2`; write; non-admin | Source freshness docs still call it a legacy-visible compatibility writer, and source-quality tests exercise source rows. | Remove only after embedded-source replacements cover diagnostics and tests. |
| `source.attach_to_decision` | defer | `redirect=decision.add`; write; non-admin | Attachment writes still back source-quality/replay compatibility; `decision.add` is not proven as a complete attach replacement here. | Remove only after source attachment data paths are migrated or retired. |
| `source.attach_to_forecast` | defer | `redirect=forecast.add`; write; non-admin | Legacy source-to-forecast edges remain a compatibility path for source-quality diagnostics and replay. | Remove only after forecast inline sources fully replace edge attachments. |
| `source.attach_to_instrument` | defer | `redirect=market.bind`; write; non-admin | Source-quality tests still attach sources to instruments; replacement through `market.bind` was not validated here. | Remove only after instrument source diagnostics are migrated. |
| `source.attach_to_memory_node` | defer | `redirect=memory.retain`; write; non-admin | Memory-node source attachments remain part of legacy source compatibility; inline memory sources need separate validation. | Remove only after memory source refs no longer require attach edges. |
| `source.attach_to_outcome` | defer | `redirect=resolution.add`; write; non-admin | Source-quality tests still attach sources to outcomes/resolutions; replacement through `resolution.add` was not validated here. | Remove only after outcome source diagnostics are migrated. |
| `source.attach_to_snapshot` | defer | `redirect=snapshot.add`; write; non-admin | Source-quality tests still attach sources to snapshots; replacement through `snapshot.add` was not validated here. | Remove only after snapshot source diagnostics are migrated. |
| `source.attach_to_thesis` | defer | `redirect=forecast.add`; write; non-admin | Thesis/source edge compatibility remains while thesis collapse cleanup is incomplete. | Remove only after thesis-source replay and diagnostics are retired or migrated. |
| `strategy.create` | keep | `redirect=strategy.upsert`; write; non-admin | Core overlay registers it as a hidden alias backed by the canonical `strategy.upsert`. | Delete only after alias compatibility is retired in release notes. |
| `strategy.list` | defer | `redirect=report.strategy_health`; read; non-admin | Direct list handler remains registered; broad health report is not a proven drop-in list replacement. | Remove only with strategy-list callers/docs moved to a public read/report surface. |
| `strategy.show` | defer | `redirect=report.strategy_health`; read; non-admin | Direct detail/health read remains registered and appears in continuity docs/golden tests. | Remove only after continuity suggestions and tests stop naming `strategy.show`. |
| `strategy.update` | defer | `redirect=strategy.upsert`; write; non-admin | Partial update semantics are distinct from create/upsert examples; replacement behavior needs explicit validation. | Remove only with update semantics folded into `strategy.upsert` docs/tests. |
| `thesis.add` | defer | `redirect=forecast.add`; write; non-admin | Legacy thesis writer is still used by fixtures, import/replay paths, and market-scan planning. | Remove only after thesis-collapse cleanup removes direct thesis dependencies. |
| `venue.add` | defer | `redirect=market.bind`; write; non-admin | Legacy venue writer is still used by fixtures, import/replay paths, and market-scan planning. | Remove only after venue/instrument compatibility rows are no longer required. |
<!-- legacy-tool-disposition-matrix:end -->

## Validation Notes

The matrix is intentionally derived from runtime registry metadata rather than
from the historical `V002_FOLDED_OR_REMOVED` table alone. That matters because
the runtime legacy set includes compatibility aliases registered outside the
core overlay, such as `agent.bootstrap`, `agent.next_actions`, and the complete
`source.attach_to_*` family.

Targeted validation for this record should include:

- runtime readback of all `catalog_visibility="legacy"` entries;
- `tool.schema` readback with and without `include_legacy` to confirm default
  catalog hiding still holds;
- the docs contract test that checks this table against `build_registry()`.
