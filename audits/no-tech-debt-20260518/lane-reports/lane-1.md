Read-only docs/contract truth review completed for /home/hermes/code/trade-trace at commit a33e676ec9d22d6ec268686424521a3d2586f9dd.

What I did:
- Confirmed repository commit and noted pre-existing uncommitted changes; made no edits.
- Reviewed in-scope docs/contracts:
  - README.md
  - docs/PRD.md
  - docs/VISION.md
  - docs/architecture/*.md
  - AGENTS.md
  - CLAUDE.md
- Compared claims against practical code/manifests where useful:
  - pyproject.toml scripts/dependencies
  - src/trade_trace/core.py registry composition
  - src/trade_trace/cli.py indirectly through registry CLI invocations
  - src/trade_trace/mcp_server.py presence
  - src/trade_trace/tools/ledger.py registrations
  - src/trade_trace/storage/migrations.py schema enums
- Ran/read commands and searches:
  - `git rev-parse HEAD && git status --short`
  - attempted `python` read of pyproject, failed because `python` not installed; retried with `python3` later
  - read_file on README.md, docs/PRD.md, docs/VISION.md, AGENTS.md, CLAUDE.md, pyproject.toml
  - search_files for docs/architecture/*.md, src/trade_trace/*.py, registry/tool references, SQL files
  - `PYTHONPATH=src python3` registry introspection via `trade_trace.core.build_registry()`
  - markdown-link checker script over in-scope markdown files
  - targeted reads/searches of migrations/tool source where contract/schema evidence was needed

Files created or modified:
- None.

Issues encountered:
- `python` executable was unavailable; used `python3`.
- Working tree already had unrelated modified/untracked files before my review:
  - modified files under src/trade_trace/events and src/trade_trace/reports
  - untracked audits/ and docs/audits/
  I did not inspect/modify those beyond `git status`.

Candidates found:

candidate 1
id: docs-contract-truth-001
title: Relative links in top-level and architecture docs point to nonexistent PRD/VISION/architecture paths
domain: docs-contract-truth
debt class: docs-contract-drift
track: docs
evidence:
- README.md lines 23, 58, 59, and 93 link to `./VISION.md` and `./PRD.md`, but the actual files are `docs/VISION.md` and `docs/PRD.md`.
- docs/PRD.md is located under `docs/`, but repeatedly links to `./docs/architecture/...`, which resolves to `docs/docs/architecture/...`; actual files are `docs/architecture/...`.
- docs/architecture/*.md companion links commonly use `../../PRD.md` and/or `../../VISION.md`, which resolve to repository-root PRD.md/VISION.md; actual files are `docs/PRD.md` and `docs/VISION.md`.
- Link checker output included:
  - `README.md:23: broken ./VISION.md -> /home/hermes/code/trade-trace/VISION.md`
  - `README.md:23: broken ./PRD.md -> /home/hermes/code/trade-trace/PRD.md`
  - `docs/PRD.md:5: broken ./docs/architecture/memory-layer.md -> /home/hermes/code/trade-trace/docs/docs/architecture/memory-layer.md`
  - repeated broken PRD architecture links across docs/PRD.md
  - `docs/architecture/reports.md:15: broken ../../PRD.md -> /home/hermes/code/trade-trace/PRD.md`
  - similar broken links across scoring.md, contracts.md, persistence.md, operability.md, imports.md, dogfood-protocol.md, risk-units.md, opportunity-analysis.md, memory-layer.md.
carrying cost/risk:
- New users and agents following README/PRD/architecture references hit dead links at the exact points where the docs claim to define canonical contracts.
- Contract drift becomes harder to audit because the PRD’s references to scoring, persistence, contracts, reports, imports, and operability specs are not navigable from rendered markdown.
- Maintainers may duplicate or misread specs if they cannot follow companion-doc links from the PRD or architecture pages.
bounded action:
- Fix relative markdown links only:
  - README.md: `./VISION.md` -> `./docs/VISION.md`, `./PRD.md` -> `./docs/PRD.md`.
  - docs/PRD.md: `./docs/architecture/...` -> `./architecture/...`.
  - docs/architecture/*.md: `../../PRD.md` -> `../PRD.md`, `../../VISION.md` -> `../VISION.md`.
- Add or run a lightweight markdown-link check in docs QC if desired.
non-goals:
- Do not rewrite doc content or change product scope.
- Do not touch external URLs.
- Do not alter architecture claims beyond broken relative paths.
validation:
- Re-run the same markdown-link checker over README.md, docs/PRD.md, docs/VISION.md, docs/architecture/*.md, AGENTS.md, CLAUDE.md.
- Expected: no broken local links for existing markdown files.
risk:
- Low implementation risk; path-only doc edits.
- Main risk is accidentally changing anchor fragments; keep fragments intact.
priority: high
confidence: high
route justification:
- This is docs-contract debt, not code behavior: the underlying files exist, but in-scope docs point to wrong relative locations.
why not style/speculation:
- Broken local links are mechanically reproducible and affect contract navigation, not wording preference.
false-positive check:
- Confirmed actual files exist at docs/PRD.md, docs/VISION.md, docs/architecture/*.md.
- The checker resolved links relative to each markdown file’s own directory, which is how GitHub/renderers treat relative links.
duplicate notes:
- Not a duplicate of the stated existing open themes about agent-ready MCP stdio/input schemas/AGENT_GUIDE/embeddings or pre-release publish workflow.
proposed bead title:
- Fix broken relative links across README, PRD, and architecture docs
proposed bead body:
- Multiple in-scope markdown files link to nonexistent local paths after PRD/VISION live under docs/. README links to root PRD/VISION; docs/PRD.md links to docs/docs/architecture; architecture docs link up to root PRD/VISION. This breaks navigation to canonical contracts and increases setup/maintenance confusion. Update only relative links and preserve anchors/content.
proposed acceptance:
- README links to docs/PRD.md and docs/VISION.md resolve locally.
- docs/PRD.md links to architecture/*.md resolve locally.
- docs/architecture/*.md links to ../PRD.md and ../VISION.md resolve locally.
- A local markdown-link check over in-scope docs reports zero missing local markdown targets.
disposition recommendation:
- Materialize as a docs debt bead.

candidate 2
id: docs-contract-truth-002
title: AGENTS.md and CLAUDE.md impose unconditional push/session-close rules that conflict with read-only and delegated workflows
domain: docs-contract-truth
debt class: agent-contract-drift
track: docs / agent contract
evidence:
- AGENTS.md lines 61-83 state that when ending a work session, work is not complete until `git push` succeeds; mandatory workflow includes filing issues, updating status, `bd dolt push`, `git push`; critical rules say “NEVER stop before pushing”.
- CLAUDE.md lines 25-49 repeats the same unconditional mandatory session completion/push workflow.
- The current delegated lane explicitly says read-only: do not edit files, do not create/update Beads, no pushes. This is an example of a legitimate repo workflow where following AGENTS.md/CLAUDE.md literally would violate task constraints.
- AGENTS.md/CLAUDE.md also say to file issues for remaining work and use bd remember; current lane forbids creating/updating Beads and memory/Hindsight retain.
carrying cost/risk:
- Agents that obey repository agent docs literally may push unexpectedly from read-only audits, delegated review lanes, or local investigation sessions.
- The unconditional instructions can cause scope violations, stray bead updates, or attempts to mutate shared state when the task is explicitly read-only.
- Future maintainers have to rely on external parent prompts to override repo-local contracts instead of the repo contract encoding safe exceptions.
bounded action:
- Amend AGENTS.md and CLAUDE.md to scope mandatory push/bead updates to sessions that actually made authorized changes and are not explicitly read-only/delegated/no-push.
- Add an explicit precedence/exception note: task-specific constraints such as read-only, no-Beads, no-push, or delegated audit lanes override the generic session-close checklist.
- Keep the Beads workflow for normal implementation sessions.
non-goals:
- Do not remove Beads guidance entirely.
- Do not change actual bd workflow or project issue-tracker choice.
- Do not introduce new tooling.
validation:
- Read AGENTS.md and CLAUDE.md and confirm they distinguish normal mutating work from read-only/no-push sessions.
- Simulate interpretation for two cases:
  1. code-changing task: still requires tests/status/push as applicable.
  2. read-only audit: explicitly permits final report without bead mutation or push.
risk:
- Low doc-change risk.
- Main risk is weakening the normal push discipline too much; wording should preserve mandatory push when authorized changes were made.
priority: medium-high
confidence: high
route justification:
- This is a user/agent contract drift issue in explicitly in-scope files; it affects how agents operate the repo, not application runtime behavior.
why not style/speculation:
- The conflict is concrete: AGENTS.md/CLAUDE.md command pushes and bead updates unconditionally, while legitimate delegated tasks can prohibit both.
false-positive check:
- The files are intentionally in scope only insofar as user/agent contracts; this candidate is exactly about conflicting operational contract semantics.
duplicate notes:
- Not a duplicate of existing open themes about AGENT_GUIDE/MCP schemas/embeddings. This is about existing AGENTS.md/CLAUDE.md push and mutation rules.
proposed bead title:
- Scope AGENTS/CLAUDE session-close rules for read-only and no-push workflows
proposed bead body:
- AGENTS.md and CLAUDE.md currently require filing issues, bd updates, bd dolt push, git push, and “never stop before pushing” for every session. That conflicts with delegated read-only/no-Beads/no-push lanes and can cause agents to mutate shared state against task scope. Update the agent contract to preserve mandatory closeout for authorized mutating work while explicitly exempting read-only/no-push/delegated audit sessions.
proposed acceptance:
- AGENTS.md and CLAUDE.md state task-specific read-only/no-push/no-Beads constraints override the generic closeout checklist.
- Normal authorized code-changing sessions still require appropriate gates, issue updates, and push.
- Read-only audit sessions can end with a report and no repository/bead mutation.
disposition recommendation:
- Materialize as an agent-contract docs debt bead.

candidate 3
id: docs-contract-truth-003
title: Public docs describe packaging/runtime dependency posture that no longer matches pyproject after M3/M4 shipped
domain: docs-contract-truth
debt class: config-drift / integration-provider-drift
track: docs + packaging contract
evidence:
- README.md status lines 27-39 says M0/M1/M2/M3/M4 shipped.
- README.md install lines 80-83 still says the published package ships once MVP M1-M4 write surface lands and that the base wheel will ship `sqlite-vec` and `sentence-transformers` as runtime dependencies once M3 lands.
- pyproject.toml lines 13-18 show current base dependencies only include `pydantic>=2.7,<3`; optional dependency group `mcp = ["mcp>=1.0"]`; no `sqlite-vec` or `sentence-transformers` runtime dependency.
- PRD.md line 113 similarly states “The base wheel ships `sqlite-vec` and `sentence-transformers` as runtime dependencies but never auto-downloads model weights.”
- Registry introspection shows embeddings/model import/reindex are currently stubs/deferred:
  - `journal.config_set` description: embeddings.provider non-none returns `UNSUPPORTED_CAPABILITY` pointing at bead trade-trace-a4p.
  - `model.import`, `model.warm`, `memory.reindex` descriptions are deferred stubs.
carrying cost/risk:
- Users/operators may expect vector dependencies to be installed with the base package after seeing “M3 shipped” and “base wheel ships sqlite-vec/sentence-transformers”.
- Maintainers may accidentally make packaging/release decisions from stale docs rather than pyproject.
- Integration providers/air-gap users get unclear guidance about whether local embedding support is available, optional, or deferred.
bounded action:
- Reconcile README.md and docs/PRD.md packaging statements with pyproject and current registry behavior:
  - either update pyproject to include the promised runtime dependencies if that is now intended, or
  - update docs to say embeddings/vector dependencies remain deferred/optional under trade-trace-a4p and are not in the base runtime today.
- Keep default-off/no-network guarantees intact.
non-goals:
- Do not implement embeddings.
- Do not change MCP/package publishing workflow.
- Do not reopen the already-tracked embeddings implementation bead; only align docs/package contract.
validation:
- Check pyproject dependencies and tool.schema/registry descriptions for embeddings-related commands.
- Confirm README/PRD no longer claim base wheel includes unavailable vector runtime dependencies unless pyproject actually does.
risk:
- Medium because wording touches release/dependency contract and could overlap with planned packaging decisions.
priority: medium
confidence: medium-high
route justification:
- This is docs/config/provider contract drift: docs make dependency availability claims inconsistent with the manifest and current tool registry.
why not style/speculation:
- The mismatch is concrete: docs name specific dependencies as base runtime packages; pyproject does not include them; registry says non-none embeddings are unsupported/deferred.
false-positive check:
- Existing open theme includes embeddings; I am flagging only the docs/package truth mismatch, not the embeddings implementation itself. If the existing embeddings bead already includes docs/packaging reconciliation, this should be attached there rather than duplicated.
duplicate notes:
- Potential overlap with existing open “embeddings” theme/trade-trace-a4p. Avoid creating a separate bead if a4p already covers dependency/doc reconciliation; otherwise add as a docs/config subtask linked to a4p.
proposed bead title:
- Reconcile README/PRD vector dependency claims with pyproject and deferred embeddings posture
proposed bead body:
- README and PRD say M3/M4 shipped and that the base wheel ships sqlite-vec and sentence-transformers once M3 lands, but pyproject only has pydantic as a base dependency and registry descriptions mark embeddings/model import/reindex as deferred/UNSUPPORTED_CAPABILITY under trade-trace-a4p. Align docs and packaging so users know whether vector deps are actually in the base package today.
proposed acceptance:
- pyproject and README/PRD agree on whether sqlite-vec/sentence-transformers are base, optional, or deferred dependencies.
- Embeddings config/model import/reindex docs match current registry behavior.
- Default no-network guarantee remains explicit.
disposition recommendation:
- Do not create a duplicate bead if trade-trace-a4p already owns this; otherwise materialize as a docs/config-drift subtask linked to a4p.

Coverage accounting:
- README.md: reviewed fully; compared install/status/quickstart/CLI claims against pyproject and registry where practical.
- docs/PRD.md: reviewed main scope, API/storage/testing/milestone sections; link checker covered full file.
- docs/VISION.md: reviewed safety/product contract sections; link checker covered full file.
- docs/architecture/*.md: enumerated all 11 files and link-checked all for local path truth. I did not do a line-by-line semantic audit of every architecture page due size, but sampled contract-critical areas through PRD references and code/schema checks.
- AGENTS.md and CLAUDE.md: reviewed as user/agent contracts; found one concrete contract-risk candidate.
- Code/manifests checked:
  - pyproject.toml dependency/scripts truth.
  - src/trade_trace/core.py registry composition via import.
  - tool registry output for actual tool names, CLI invocations, and deferred embeddings/import/review behavior.
  - src/trade_trace/storage/migrations.py source enum spot-check.
- No files changed; no beads created/updated; no pushes; no installs.