Context:
Domain: packaging-ci-docs
Affected surface: config.set/export.drain/forecast.show/decision.show/edges.list/top-level backup/restore
Candidate: DOC-002B from exhaustive deadcode hunt epic trade-trace-5lx.

Dead-code claim:
Reconcile docs that advertise unregistered CLI/tool command surfaces

Evidence:
- Paths: README.md, docs/PRD.md, docs/architecture/memory-layer.md, docs/architecture/persistence.md, docs/architecture/operability.md, docs/architecture/dogfood-protocol.md, pyproject.toml
- registered-tools.txt from default_registry contains 61 current tools and lacks config.set, export.drain, forecast.show, decision.show, edges.list, and top-level backup/restore. README/docs mention tt config set, export.drain/config.toml, tt backup/tt restore, and forecast.show/decision.show/edges.list as current/protocol surfaces.
- Evidence artifacts: docs/audits/deadcode-2026-05-18/candidate-matrix.json, lane-packets.md, advisor-review.md.

Reference search scope:
tracked docs/README/pyproject/source registry

Reference search commands / output summary:
registered-tools.txt via PYTHONPATH=src python3 default_registry; search_files export.drain|tt backup|tt restore|forecast.show|decision.show|edges.list|tt config set

Entrypoint / public / dynamic checks:
- Dynamic-loading caveats: Some surfaces may be intended P1 future features; docs need current-vs-planned wording, not necessarily removal.
- Public/API surface: public docs/API contract and CLI command examples
- Generated/reflection risk: none

Why it may be falsely alive:
Docs may intentionally describe target architecture; but several sections are phrased as current shipped commands/dependencies.

Impact / risk of keeping:
Agents/users copy wrong commands, expect unavailable deps/tools, or fail dogfood protocol steps.

Recommended action:
document

Safe-removal validation:
registered-tools.txt/default_registry output confirms every docs command is either registered, explicitly marked planned/deferred, or rewritten as direct DB/pseudocode; docs no longer instruct unavailable current commands.

Duplicate check:
Compared against open Beads snapshot and duplicate scan captured in docs/audits/deadcode-2026-05-18/pre-mutation-snapshot.txt. Duplicate/related notes: duplicate_of=None; related_to=['trade-trace-46p', 'trade-trace-74b', 'trade-trace-re2', 'trade-trace-dkm', 'trade-trace-iuv', 'trade-trace-yai']. This bead is materialized because coordinator disposition is confirmed and advisor review approved this class of materialization.

Acceptance criteria:
- README and architecture docs no longer present unregistered current commands as shipped.
- Backup/restore docs use registered journal.backup/journal.restore command names or clearly name future aliases.
- Dogfood protocol unregistered read tools are replaced with existing surfaces or marked pseudocode/direct-DB assertions.
- Registry readback is used to verify cited command surfaces.

Provenance:
Discovered by repo-deadcode-hunt candidate DOC-002B in domain packaging-ci-docs. Labels expected: dead-code, deadcode-hunt, deadcode:exhaustive-20260518, domain:docs, bug, docs-truth, risk:stale-contract.

## Steps to Reproduce
1. Inspect the cited files/artifacts above.
2. Re-run the validation/readback command(s): registered-tools.txt/default_registry output confirms every docs command is either registered, explicitly marked planned/deferred, or rewritten as direct DB/pseudocode; docs no longer instruct unavailable current commands.
3. Observe the stale/missing docs/tool/package contract described in the evidence section.

## Acceptance Criteria
- README and architecture docs no longer present unregistered current commands as shipped.
- Backup/restore docs use registered journal.backup/journal.restore command names or clearly name future aliases.
- Dogfood protocol unregistered read tools are replaced with existing surfaces or marked pseudocode/direct-DB assertions.
- Registry readback is used to verify cited command surfaces.
