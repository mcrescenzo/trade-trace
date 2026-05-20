# Deadcode hunt 2026-05-20 final summary

Coverage:
- Mode: exhaustive tracked-file deadcode hunt with backlog materialization.
- Repo: `/home/hermes/code/trade-trace`.
- HEAD at discovery/materialization: `73aee82`.
- Tracked files in manifest: 283.
- Coverage ledger rows: 283.
- Domains reviewed: python-core-storage-security (43), tools-cli-mcp-reports (36), console-backend-frontend (32), tests-fixtures (120), docs-ci-config-audit (52).
- Discovery lanes run: 5 read-only delegated lanes.
- Reachability surfaces checked: pyproject scripts, CLI/MCP registry, report/tool registration, FastAPI console routes/static serving, Vite/React imports, package-data, pytest fixture discovery, GitHub workflows, root config/hooks, docs command contracts, public exports, dynamic/plugin caveats.
- Blind spots: no external downstream package-consumer scan; no full Python test suite; docs lane used targeted command/link searches rather than line-by-line reading of every docs paragraph; generated console bundles treated as package artifacts, not source.

Findings:
- Raw candidate rows: 11.
- New materialized cleanup/investigation beads: 4.
- Merged into existing open docs-QC bead: 2 matrix rows (`DC-20260520-003`, `DC-20260520-004` -> `trade-trace-r1mt`).
- Matrix-only kept / rejected: 5.
- Confirmed immediate-removal tasks: 1 (`DC-20260520-001`, unused frontend dependencies).
- Owner-confirmation cleanup/investigation tasks: 3 (`DC-20260520-002`, `DC-20260520-005`, `DC-20260520-006`).
- New standalone docs-truth bugs: 0, because the stale CLI docs findings were merged into the concurrent `trade-trace-r1mt` docs-QC bead instead of duplicated.

Beads:
- Epic: `trade-trace-frd0`.
- Final verification gate: `trade-trace-4hr9`.
- Membership model: relation-based epic navigation; `bd children trade-trace-frd0` is empty by design.
- Navigation: `bd dep list trade-trace-frd0`.
- Execution gate: `bd dep list trade-trace-4hr9`.
- New candidate beads:
  - `trade-trace-hdlx` — Remove unused Console frontend dependencies.
  - `trade-trace-0apb` — Decide canonical JSONL serialization path for EventRecord.to_jsonl_line.
  - `trade-trace-kq8y` — Decide whether Console trade_detail should be wired or removed.
  - `trade-trace-bh7q` — Decide whether security.keyring.delete_api_key needs a product path.
- Existing bead updated:
  - `trade-trace-r1mt` received appended notes with exact docs drift evidence for merged DC-20260520-003/DC-20260520-004.

Verification:
- `bd dep cycles`: no dependency cycles detected.
- `bd lint`: no template warnings found in checked open issues.
- `bd orphans`: no orphaned issues found.
- Duplicate scan at threshold 0.45: only unrelated mechanical overlaps in the concurrent agent-workbench program; no deadcode candidate duplicate remained open.
- Navigation/readback: `bd dep list trade-trace-frd0` shows the four candidates plus final gate via `relates-to`; `bd dep list trade-trace-4hr9` shows the four candidates as blocking dependencies.
- Body-integrity readback: passed for all four materialized candidates plus final gate; merged docs note verified on `trade-trace-r1mt`.
- Candidate matrix disposition check: materialized IDs and merged-existing IDs recorded in `candidate-matrix.json` and `materialized-id-map.json`.
- Beads persistence: local Beads DB readback passed. `bd dolt push` was run because this repo's closeout policy lists it; Beads reported no remote configured and skipped remote sync.

Git / artifact persistence:
- Artifact commit: `a0a9fc3` pushed to `origin/main`.
- Post-push status artifact: `post-push-status.txt`.
- Final live git status after push: `## main...origin/main` with no short-status entries.

Artifacts:
- Run directory: `docs/audits/deadcode-20260520T172715Z/`.
- Manifest: `tracked-manifest.json`.
- Coverage ledger: `coverage-ledger.jsonl`.
- Lane packets: `lane-packets.md`.
- Evidence snippets: `evidence-snippets.txt`.
- Candidate matrix: `candidate-matrix.json`.
- Advisor review: `advisor-review.md`.
- Mutation audit: `mutation-audit.md`.
- Materialized ID map: `materialized-id-map.json`.
- Body-integrity readback: `body-integrity-readback.json`.
- Final readback: `final-readback-raw.txt`.

Caveats:
- Cleanup/removal is not done; this phase produced and verified the backlog.
- `trade-trace-0apb`, `trade-trace-kq8y`, and `trade-trace-bh7q` require owner/product confirmation before deletion/removal because they touch public/exported or future-facing surfaces.
- The docs stale-command findings were not duplicated as deadcode beads because a concurrent open docs-QC bead already covers agent-facing docs/schema/example drift; the evidence was appended there instead.
- This is exhaustive over the current tracked manifest and reviewed surfaces, not a proof that no dead code remains.
