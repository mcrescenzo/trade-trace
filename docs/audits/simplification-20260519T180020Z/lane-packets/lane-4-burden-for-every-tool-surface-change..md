What I did:
- Read the docs-contracts-packaging-ci domain map entry and inspected all 28 assigned files at /home/hermes/code/trade-trace.
- Verified repository HEAD is the requested commit:
  6f62a5f7a83cec823302bbe80892172b1e6936cb
- Stayed read-only: no file edits, no Beads changes, no public/shared/destructive actions.
- Checked the existing docs validation surface: tests/docs/test_markdown_links.py currently verifies relative Markdown file targets, but not anchors or doc/source-of-truth drift.

Repository state encountered:
- Pre-existing dirty/untracked state was present before this lane’s work:
  - M tests/contracts/test_grammar.py
  - ?? audits/no-tech-debt-20260519T180002Z/
  - ?? docs/audits/bughunt-20260519T175941Z/
  - ?? docs/audits/simplification-20260519T180020Z/
- I did not modify anything.

Coverage accounting:
- Domain: docs-contracts-packaging-ci
- Assigned files inspected: 28 / 28
- Files:
  - .claude/settings.json
  - .github/workflows/ci.yml
  - .github/workflows/workflow.yml
  - .gitignore
  - AGENTS.md
  - CLAUDE.md
  - README.md
  - docs/AGENT_GUIDE.md
  - docs/AI_AGENT_MCP_GETTING_STARTED.md
  - docs/CLAUDE_CODE.md
  - docs/CLAUDE_DESKTOP.md
  - docs/IDE_MCP_SETUP.md
  - docs/PRD.md
  - docs/VISION.md
  - docs/architecture/contracts.md
  - docs/architecture/dogfood-protocol.md
  - docs/architecture/forecastbench-compatibility.md
  - docs/architecture/http-sse-subscribe.md
  - docs/architecture/imports.md
  - docs/architecture/memory-layer.md
  - docs/architecture/operability.md
  - docs/architecture/opportunity-analysis.md
  - docs/architecture/persistence.md
  - docs/architecture/reports.md
  - docs/architecture/risk-units.md
  - docs/architecture/scoring.md
  - docs/architecture/security.md
  - pyproject.toml

Candidates:

Candidate DOCSIM-001
Title: Collapse repeated MCP setup instructions into one canonical setup include/page
Domain: docs-contracts-packaging-ci
Type: behavior-preserving docs simplification
Primary files:
- README.md
- docs/AI_AGENT_MCP_GETTING_STARTED.md
- docs/CLAUDE_CODE.md
- docs/CLAUDE_DESKTOP.md
- docs/IDE_MCP_SETUP.md
- docs/AGENT_GUIDE.md
Evidence:
- README.md lines 1-21 introduces MCP install/startup and links client walkthroughs before the project title/intro.
- README.md lines 94-126 repeats install, optional extras, TRADE_TRACE_HOME, journal init, and embedding posture.
- docs/AI_AGENT_MCP_GETTING_STARTED.md lines 7-64 repeats installation, TRADE_TRACE_HOME, journal init, generic MCP config, command path fallback, and client links.
- docs/CLAUDE_CODE.md lines 5-29 repeats pip install, trade-trace-mcp startup behavior, TRADE_TRACE_HOME, journal init, MCP_ACTOR_ID default.
- docs/CLAUDE_DESKTOP.md lines 5-27 repeats the same install/init/actor instructions.
- docs/IDE_MCP_SETUP.md lines 5-27 repeats the same install/init/actor instructions.
- docs/AGENT_GUIDE.md line 5 embeds a dense one-paragraph setup summary that overlaps with the getting-started guide.
Simplification:
- Make docs/AI_AGENT_MCP_GETTING_STARTED.md the canonical MCP setup source.
- Reduce README.md to a short “MCP server quickstart” plus links.
- Reduce client-specific docs to client-specific config deltas only:
  - Claude Code CLI command/scope behavior
  - Claude Desktop config path/snippet
  - generic IDE location notes
- Keep only one authoritative copy of:
  - install command
  - TRADE_TRACE_HOME guidance
  - MCP_ACTOR_ID default/format
  - stdio/no HTTP warning
  - command -v trade-trace-mcp fallback
Maintenance reduction:
- Eliminates four to six near-identical setup sequences.
- Reduces future drift when install command, actor rules, or server command changes.
Validation:
- pytest tests/docs -q
- Manual readback of README.md and each MCP client doc.
- Optionally add/extend a docs test that ensures client docs link to the canonical getting-started page rather than duplicating full setup blocks.
Risk:
- Low. Pure docs refactor if examples are preserved where client-specific.
Overlap notes:
- Distinct from closed trade-trace-9zy because this is not about read-only/no-push scoping; it is about duplicated MCP setup instructions.

Candidate DOCSIM-002
Title: Remove duplicated Beads session-protocol blocks and stale placeholders between AGENTS.md and CLAUDE.md
Domain: docs-contracts-packaging-ci
Type: behavior-preserving agent-doc simplification
Primary files:
- AGENTS.md
- CLAUDE.md
Evidence:
- AGENTS.md lines 3-13 has a Beads quick reference.
- AGENTS.md lines 39-111 includes a generated Beads integration block that repeats the Beads quick reference and session completion rules.
- CLAUDE.md lines 5-86 contains a similar Beads integration block with largely the same session completion semantics.
- CLAUDE.md lines 89-105 still contain placeholders:
  - “_Add your build and test commands here_”
  - npm example commands for a Python project
  - “_Add a brief overview of your project architecture_”
  - “_Add your project-specific conventions here_”
Simplification:
- Keep one authoritative project-agent instruction source and make the other a thin pointer, or define a deliberately minimal delta:
  - AGENTS.md: general agent rules / Beads integration
  - CLAUDE.md: Claude-specific deltas only
- Remove duplicate non-generated quick reference outside the Beads block or replace with a one-line pointer to `bd prime`.
- Replace placeholder build/test sections with actual Python commands or remove them.
Maintenance reduction:
- Avoids two files drifting on mandatory workflow/read-only exemptions.
- Removes misleading npm placeholders from a Python package.
Validation:
- Manual readback of both files.
- If the Beads integration block is managed by a generator, rerun/verify the generator or document that the block remains untouched.
Risk:
- Medium-low because agent instruction files affect workflow behavior; keep generated hash block semantics intact unless the Beads tool owns regeneration.
Overlap notes:
- Avoid re-litigating the trade-trace-9zy read-only/no-push policy itself. The simplification is about duplicate placement and stale placeholders, not changing the policy.

Candidate DOCSIM-003
Title: Avoid maintaining a hand-written complete tool registry list in README.md
Domain: docs-contracts-packaging-ci
Type: docs/source-of-truth simplification
Primary files:
- README.md
Neighbor files for validation/source:
- src/trade_trace/contracts/tool_registry.py
- src/trade_trace/tools/*
- tests/contracts/test_cli_name_uniqueness.py
Evidence:
- README.md lines 224-246 hand-lists every current registered tool.
- The same paragraph says the shipped registry is discoverable with `tt tool schema` and is the source of truth for exact arguments.
- This creates a guaranteed drift point whenever a tool is added, renamed, or removed.
Simplification:
- Replace the full hand-maintained registry enumeration with:
  - a short representative category list, and
  - a command example: `tt tool schema`
- Optionally generate a registry snapshot during docs build/test if a static list is truly needed.
Maintenance reduction:
- Removes a high-churn docs section that duplicates runtime registry state.
- Reduces review burden for every tool-surface change.
Validation:
- pytest tests/docs -q
- pytest tests/contracts/test_cli_name_uniqueness.py -q
- Manual run/readback of `tt tool schema` in a dev environment if docs text references exact output.
Risk:
- Low. The runtime command remains canonical.
Overlap notes:
- This is framed as simplification of a duplicated source of truth, not as a stale-doc bug. It should avoid overlap with prior deadcode/docs-truth findings unless parent wants to merge it into existing docs-truth work.

Candidate DOCSIM-004
Title: De-duplicate CI quality gate steps between CI and PyPI publish workflows
Domain: docs-contracts-packaging-ci
Type: packaging/CI simplification
Primary files:
- .github/workflows/ci.yml
- .github/workflows/workflow.yml
Evidence:
- .github/workflows/ci.yml lines 24-52 defines a Python 3.11/3.12/3.13 matrix with identical install, ruff, mypy, pytest steps.
- .github/workflows/workflow.yml lines 11-39 repeats the same matrix and identical install/lint/type/test steps before build/publish.
- ci.yml lines 3-9 explicitly notes the duplication: publish keeps its own internal test gate as a safety net.
Simplification options:
- Use a reusable workflow for the quality gate and call it from both CI and publish.
- Or make publish depend on/build from a required successful CI run for the tag, while keeping a minimal smoke/build check in publish.
- Or factor common commands into a script such as `python -m pip install -e ".[dev]" && ruff check src tests && mypy src && pytest`, then both workflows call the same script.
Maintenance reduction:
- One place to update Python versions, dev install, lint/type/test commands.
- Reduces risk that tag publish and PR CI diverge.
Validation:
- GitHub Actions workflow syntax validation.
- Run equivalent local commands:
  - pip install -e ".[dev]"
  - ruff check src tests
  - mypy src
  - pytest
- For workflow-only changes, use a branch/PR dry run or actionlint if available.
Risk:
- Medium. Publish safety is intentionally duplicated; preserve a tag-time gate or reusable workflow dependency so a tag cannot publish untested artifacts.
Overlap notes:
- Not a code simplification; this is CI ceremony/source duplication.

Candidate DOCSIM-005
Title: Single-source package version instead of manually synchronizing pyproject.toml and version.py
Domain: docs-contracts-packaging-ci
Type: packaging simplification
Primary files:
- pyproject.toml
Neighbor files:
- src/trade_trace/version.py
- .github/workflows/workflow.yml
Evidence:
- pyproject.toml line 7 has `version = "0.0.1rc2"`.
- src/trade_trace/version.py line 1 has `__version__ = "0.0.1rc2"`.
- .github/workflows/workflow.yml lines 52-64 has a custom shell check requiring the Git tag, pyproject version, and module version to all match.
Simplification:
- Use setuptools dynamic version from `src/trade_trace/version.py`, or invert the source and derive runtime version from package metadata.
- Then publish workflow only verifies tag == single package version.
Maintenance reduction:
- Removes one manually edited version constant.
- Simplifies release workflow version check.
Validation:
- python -m build --sdist --wheel
- Inspect wheel metadata version.
- Verify `trade_trace.__version__` or equivalent runtime version still reports correctly.
- Run publish workflow version-check logic locally or via CI dry run.
Risk:
- Medium. Packaging metadata/version handling is release-sensitive and must be validated with both sdist and wheel.

Candidate DOCSIM-006
Title: Replace stale milestone/status prose with generated or runtime-discoverable capability summaries
Domain: docs-contracts-packaging-ci
Type: docs-contract drift / source-of-truth simplification
Primary files:
- README.md
- docs/PRD.md
- docs/architecture/reports.md
- docs/architecture/imports.md
- docs/architecture/security.md
Evidence:
- README.md lines 47-62 says M0-M4 + agent-ready shipped, including imports, reports, review.bundle, optional embeddings.
- README.md lines 211-222 lists optional/limited surfaces that are currently registered.
- README.md line 142 still says JSONL/CSV import implementations, report.compare, report.risk, report.opportunity, review.bundle, and semantic recall are deferred/optional after the manual loop, while other README sections say many of these are shipped/registered.
- docs/PRD.md lines 428-437 says import.validate/import.commit may land in early P1 and MVP does not require shipping them.
- docs/architecture/imports.md line 144 labels CSV fills import as P1.
- docs/architecture/reports.md lines 9-11 says report.risk/report.opportunity are deferred and review.bundle is contract-only stub.
- docs/architecture/security.md lines 186-201 says review.bundle implementation lands in P1.
Simplification:
- Introduce a short canonical “capability status” page or generated snapshot from the runtime registry, with statuses like shipped / registered-limited / design-only.
- In PRD and architecture docs, avoid duplicating volatile shipped-vs-P1 status prose; link to the canonical status page.
- Keep design docs focused on contracts and invariants, not live implementation status.
Maintenance reduction:
- Prevents milestone prose from becoming a parallel product tracker.
- Makes it clear which docs are historical/design intent versus current runtime behavior.
Validation:
- pytest tests/docs -q
- Manual cross-read of README status, PRD milestones, and architecture docs.
- Optional stronger docs test: registered tool names in “current capabilities” docs must match `tool.schema`; design-only docs must carry explicit “design-only/not implemented” front matter.
Risk:
- Medium. Some differences may be intentional historical context; edits should preserve design intent while removing volatile current-status claims.
Overlap notes:
- There is prior docs-truth/deadcode work around unregistered command surfaces. To avoid duplicate scope, this candidate should be scoped to source-of-truth simplification and status-prose consolidation, not filing individual stale-tool bugs.

Candidate DOCSIM-007
Title: Split or archive design-only P1 transport/design docs from current user-facing docs navigation
Domain: docs-contracts-packaging-ci
Type: docs maintenance simplification
Primary files:
- docs/architecture/http-sse-subscribe.md
- README.md
- docs/PRD.md
Possibly related:
- docs/architecture/forecastbench-compatibility.md
- docs/architecture/risk-units.md
- docs/architecture/opportunity-analysis.md
Evidence:
- docs/architecture/http-sse-subscribe.md lines 1-16 states it is a proposed design artifact only, not implemented, and follow-up beads must wait for controller acceptance.
- The same file is 252 lines of detailed future API/security/test design.
- README.md and MCP setup docs repeatedly tell users stdio-only/no HTTP/SSE.
- PRD.md lines 520-521 lists HTTP/SSE transport and subscribe API as P1.
Simplification:
- Move explicitly design-only docs under a clearly marked `docs/design/` or `docs/archive/design/` namespace, or add front matter/status badges and keep them out of primary user navigation.
- Keep current user docs focused on shipped stdio MCP and CLI.
Maintenance reduction:
- Reduces user confusion and accidental maintenance of unimplemented API details as if they were current contract.
- Keeps architecture docs from mixing current contracts with speculative designs.
Validation:
- pytest tests/docs -q
- Manual link/readback from README and PRD.
- If paths change, verify all relative links.
Risk:
- Low to medium. Moving docs requires link updates; preserving the design artifact is important for future P1 work.

Candidate DOCSIM-008
Title: Add docs validation for anchors and canonical-doc drift, not just existing file paths
Domain: docs-contracts-packaging-ci
Type: docs validation simplification/enabler
Primary files:
- tests/docs/test_markdown_links.py
Neighbor docs:
- README.md
- docs/**/*.md
Evidence:
- tests/docs/test_markdown_links.py lines 1-11 documents a lightweight link checker.
- tests/docs/test_markdown_links.py lines 36-42 strips anchors and only asserts the target file exists.
- Several docs rely on section references, e.g. README and PRD references to architecture doc sections.
- Current simplification candidates involve moving/consolidating docs, which needs stronger validation than file existence.
Simplification:
- Extend the docs test to validate Markdown anchors for relative links where practical.
- Optionally add a small allowlist for intentionally external or generated anchors.
- Add simple canonical-source tests for volatile generated facts if retained:
  - README current tool list, if any, matches runtime registry.
  - package version docs, if any, match pyproject/runtime.
Maintenance reduction:
- Catches broken section refs during future docs consolidation.
- Reduces manual review burden for docs refactors.
Validation:
- pytest tests/docs -q
Risk:
- Medium-low. Anchor slug generation can differ by renderer; keep implementation conservative or allowlisted.

Non-candidates / intentionally not filed:
- I did not propose changing the substance of the AGENTS/CLAUDE read-only/no-push exemption policy, to avoid overlap with closed trade-trace-9zy.
- I did not propose removing prior audit artifacts or Beads metadata, which are explicitly excluded by the domain map.
- I did not file stale-doc bugs for every implemented-vs-P1 mismatch individually because prior deadcode/docs-truth artifacts already touched that class. I framed the relevant finding as a broader source-of-truth simplification candidate.
- I did not propose simplifying runtime code in CLI/MCP, storage, reports, or tests beyond docs/CI/packaging validation hooks, because those belong to neighboring lanes.

Files created or modified:
- None.

Issues encountered:
- `python` was not available; `python3` worked for read-only inspection scripts.
- The working tree had pre-existing modified/untracked files, listed above. I left them untouched.