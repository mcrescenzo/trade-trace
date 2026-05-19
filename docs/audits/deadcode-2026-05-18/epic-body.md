Context:
Exhaustive repo-wide deadcode hunt for /home/hermes/code/trade-trace on main.

Goal:
Find evidence-backed dead, unreachable, obsolete, stale, duplicate, unused, or misleading code/config/docs/tests/assets and materialize only safe cleanup/removal/deprecation follow-up work into Beads.

Scope:
- All 158 tracked files from git ls-files as of the initial preflight.
- Source, tests, docs, packaging, CI, Beads tracking metadata, and project agent instructions.
- Runtime reachability through pyproject scripts, CLI entrypoint, MCP in-process shim/stdio placeholder, default_registry tool registration, imports, tests, docs contracts, and CI.

Exclusions / non-goals:
- Do not remove or edit production code during discovery.
- Do not prune dependencies, run package-manager cleanup, delete files, publish, or change shared services during discovery.
- Generated/intermediate ignored artifacts outside git ls-files are out of exhaustive tracked-file coverage unless they affect tracked contract truth.

Dead-code definition:
Accepted candidates need concrete reachability evidence: unreachable current entrypoint path, unreferenced internal symbol after scoped reference/public/dynamic checks, stale config/workflow/docs path no longer invoked, obsolete compatibility shim, duplicate legacy path, intentionally dormant code with concrete risk, or stale docs/tests/fixtures that mislead safe operation.

Disposition model:
- confirmed: enough evidence for a cleanup/removal/deprecation task.
- cleanup-candidate: likely dead but needs validation before removal.
- needs-owner-confirmation: public/exported/manual surface or product intent uncertain.
- needs-more-evidence: dynamic/framework/generated/fixture linkage not ruled out.
- rejected/keep: durable false-positive disposition to avoid rediscovery.

Bug vs cleanup rule:
Use bug only when stale/dead code causes a concrete failure path, misleading operator contract, broken CI/package workflow, or security/privacy/maintenance risk. Ordinary unreachable code is task/cleanup, not bug.

Graph rule:
This epic is the narrative/root index, not the executable cleanup task. Labels and relates-to edges navigate the program. Real blockers sequence candidate cleanup and final verification. bd children may be empty because relation-based membership is preferred.

Canonical query:
bd list --status open --flat --limit 0 --sort id | grep 'deadcode:exhaustive-20260518'

Navigation:
- bd dep list <epic-id>
- bd graph <epic-id>
- bd list --status open --flat --limit 0 --sort id

Rule for adding candidates:
Each candidate must include evidence, reference-search scope/commands, entrypoint/public/dynamic caveats, safe-removal validation or explicit validation gap, duplicate check, matrix candidate ID, and relation to this epic.

Artifacts:
- docs/audits/deadcode-2026-05-18/tracked-manifest.json
- docs/audits/deadcode-2026-05-18/coverage-ledger.csv
- docs/audits/deadcode-2026-05-18/domain-map.md
- docs/audits/deadcode-2026-05-18/static-analysis.json
- lane packets, candidate matrix, advisor packet, mutation audit, and final verification summary will be added during the run.

Final verification / close rule:
The deadcode hunt is complete only after lane packets are preserved, matrix dispositions match materialization, advisor/substitute gate passes or objections are handled, materialized candidate beads pass body-integrity readback, dependency graph has no cycles, duplicate scan dispositions are recorded, audit artifacts are committed/pushed, and Beads/Git persistence are reported separately.
