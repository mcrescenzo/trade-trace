Context:
Domain: packaging-ci-docs
Affected surface: sqlite-vec/sentence-transformers package docs
Candidate: DOC-002A from exhaustive deadcode hunt epic trade-trace-5lx.

Dead-code claim:
Reconcile package/dependency docs with current pyproject embeddings posture

Evidence:
- Paths: README.md, docs/PRD.md, docs/architecture/memory-layer.md, docs/architecture/persistence.md, docs/architecture/operability.md, docs/architecture/dogfood-protocol.md, pyproject.toml
- pyproject.toml runtime dependencies contain only pydantic; README.md lines 80-83 and docs/PRD.md lines 112-113 say base wheel ships sqlite-vec/sentence-transformers once M3 lands while README status says M3 shipped. docs/architecture/memory-layer.md lines 231-235 says those deps land later with a4p.
- Evidence artifacts: docs/audits/deadcode-2026-05-18/candidate-matrix.json, lane-packets.md, advisor-review.md.

Reference search scope:
tracked docs/README/pyproject/source registry

Reference search commands / output summary:
read_file pyproject.toml; search docs for sqlite-vec|sentence-transformers; compare README/PRD/memory-layer lines

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
README.md and docs/PRD.md package dependency statements match pyproject.toml and memory-layer a4p posture; optional install/readme check confirms no untrue base-wheel vector dependency claim.

Duplicate check:
Compared against open Beads snapshot and duplicate scan captured in docs/audits/deadcode-2026-05-18/pre-mutation-snapshot.txt. Duplicate/related notes: duplicate_of=None; related_to=['trade-trace-89x', 'trade-trace-izh', 'trade-trace-heo', 'trade-trace-z6s']. This bead is materialized because coordinator disposition is confirmed and advisor review approved this class of materialization.

Acceptance criteria:
- README.md and docs/PRD.md no longer claim base wheel currently ships sqlite-vec/sentence-transformers unless pyproject is changed to match.
- Embedding dependency posture agrees with docs/architecture/memory-layer.md and open a4p/P1 beads.
- Validation cites pyproject dependency readback.

Provenance:
Discovered by repo-deadcode-hunt candidate DOC-002A in domain packaging-ci-docs. Labels expected: dead-code, deadcode-hunt, deadcode:exhaustive-20260518, domain:docs, bug, docs-truth, risk:stale-contract.

## Steps to Reproduce
1. Inspect the cited files/artifacts above.
2. Re-run the validation/readback command(s): README.md and docs/PRD.md package dependency statements match pyproject.toml and memory-layer a4p posture; optional install/readme check confirms no untrue base-wheel vector dependency claim.
3. Observe the stale/missing docs/tool/package contract described in the evidence section.

## Acceptance Criteria
- README.md and docs/PRD.md no longer claim base wheel currently ships sqlite-vec/sentence-transformers unless pyproject is changed to match.
- Embedding dependency posture agrees with docs/architecture/memory-layer.md and open a4p/P1 beads.
- Validation cites pyproject dependency readback.
