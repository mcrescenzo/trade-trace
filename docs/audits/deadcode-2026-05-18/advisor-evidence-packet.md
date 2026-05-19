# Advisor evidence packet — deadcode hunt 2026-05-18

Repo: /home/hermes/code/trade-trace
Epic: trade-trace-5lx; Final gate: trade-trace-6vd
Mode: exhaustive tracked-file deadcode/stale-surface hunt.
Tracked files: 158. Lanes: core-runtime, tools-transports, reports-memory, tests-fixtures, packaging-ci-docs/beads/misc.

Markdown link checker missing_count: 113 (see markdown-link-check.json).
Registered tools count: 61. See registered-tools.txt.

## Proposed materialization
- CRT-001 needs-owner-confirmation / create owner-confirmation task: Decide disposition for unused process-global clock accessors — evidence: src/trade_trace/clock.py:49-60 defines _DEFAULT_CLOCK/default_clock/set_default_clock. Repo search finds only definitions; runtime deterministic clock path uses trade_trace.tools._helpers.CLOCK_OVERRIDE. FixedClock/SystemClock are test-used and not candidates.
- CRT-002 needs-owner-confirmation / create owner-confirmation task: Decide disposition for unused events.write_event wrapper — evidence: src/trade_trace/events/log.py:311-332 defines write_event wrapper; events/__init__.py re-exports it. Repo search for write_event( finds only definition; active write paths use EventWriter/UnitOfWork.
- TST-001 confirmed / create cleanup task: Remove unused _all_columns helper from credential security tests — evidence: tests/security/test_no_credentials.py:55-61 defines _all_columns; same file uses inline PRAGMA scan at lines 67-80; search finds only definition plus generated audit artifacts.
- TST-002 merge / no new bead; optionally note/relate existing: Fix missing exporter.SECRET_PATTERNS compatibility alias — evidence: python3 -m pytest --collect-only -q tests/security/test_redacted_exports.py fails with ImportError. Existing bead trade-trace-7e2 already describes and tracks it.
- DOC-001 confirmed / create bug: Fix broken local markdown links after docs path moves — evidence: markdown-link-check.json found missing local targets: README links ./VISION.md/./PRD.md though actual files are docs/VISION.md/docs/PRD.md; docs/PRD.md links ./docs/architecture/... resolving to docs/docs/...; docs/architecture links ../../PRD.md/../../VISION.md resolving to repo root.
- DOC-002 confirmed / create bug: Reconcile stale docs for current package dependencies and tool command surfaces — evidence: pyproject runtime deps only pydantic; registry lacks config.set/export.drain/forecast.show/decision.show/edges.list/top-level backup/restore; README/PRD/architecture docs present those as current or planned inconsistently. Registered-tools.txt records current tool catalog.
- DOC-003 keep / matrix-only keep_no_bead: Tighten duplicated/generic agent instructions — evidence: AGENTS.md duplicates Beads sections; CLAUDE.md includes generic npm placeholders; both mandate pushes. However project AGENTS.md explicitly states mandatory git/bd push policy, so push text is current repo policy even if unsuitable for delegated read-only lanes.
- DOC-004 keep / matrix-only keep_no_bead: Replace generic .beads README or keep upstream boilerplate — evidence: .beads/README.md is generic Beads bootstrap in an initialized repo, but it is upstream/tooling docs and not part of product/runtime contract.

Known duplicate: TST-002 duplicates existing open P0 bug trade-trace-7e2; no new bead planned.
Known caveats: CRT-001 and CRT-002 are public/importable surfaces; materialize only as owner-confirmation tasks, not removal tasks. DOC-003/DOC-004 are matrix-only keep/no-bead due low confidence/tooling-generated/policy caveats.