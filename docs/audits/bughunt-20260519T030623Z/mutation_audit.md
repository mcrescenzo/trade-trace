# Mutation audit: exhaustive bughunt 2026-05-19
## Pre-mutation snapshots

```
git status -sb
## main...origin/main [ahead 1]
?? audits/
?? docs/audits/
git status --short
?? audits/
?? docs/audits/
bd status

📊 Issue Database Status

Summary:
  Total Issues:           117
  Open:                   32
  In Progress:            2
  Blocked:                13
  Closed:                 83
  Ready to Work:          19

For more details, use 'bd list' to see individual issues.

bd list open
● trade-trace-0m6 [● P2] [task] - Client config walkthroughs: Claude Code + Cursor/Windsurf/Cline + Claude Desktop (blocked by: trade-trace-46p, blocks: trade-trace-0r7, trade-trace-re2)
● trade-trace-0r7 [● P2] [task] - Test QC: agent-ready surface (parity, smoke, schema audit, embeddings) (blocked by: trade-trace-0m6, trade-trace-3u1, trade-trace-46p, trade-trace-59l, trade-trace-74b, trade-trace-89x, trade-trace-heo, trade-trace-izh, trade-trace-z6s, blocks: trade-trace-dhs)
○ trade-trace-1kr [● P0] [task] [ci publish rc0 release] - Recover prerelease publish after mypy-fix commit and failed v0.0.1rc0 tag runs (blocks: trade-trace-off)
○ trade-trace-2d3 [● P2] [epic] [bughunt bughunt:exhaustive-20260519] - EPIC: exhaustive repo bughunt 2026-05-19
○ trade-trace-3u1 [● P2] [task] - docs/AGENT_GUIDE.md: how to drive the journal loop from an LLM agent (blocks: trade-trace-0r7, trade-trace-re2)
○ trade-trace-46p [● P1] [feature] - stdio MCP server: wire mcp SDK into serve_stdio + entry point (blocks: trade-trace-0m6, trade-trace-0r7, trade-trace-59l, trade-trace-re2)
○ trade-trace-4md [● P2] [feature] [compare p1-core reports roadmap strategy] - Implement report.compare and decide report.strategy_performance wrapper (blocks: trade-trace-l4o)
○ trade-trace-4ng [● P3] [task] - Agent dogfood findings tracker (living bead)
● trade-trace-59l [● P2] [task] - CI smoke test: stdio server subprocess + tools/list + tools/call round-trip (blocked by: trade-trace-46p, trade-trace-74b, blocks: trade-trace-0r7)
● trade-trace-5qr [● P2] [feature] [csv import p1-core roadmap] - Implement CSV fills import adapter on top of JSONL import (blocked by: trade-trace-6k8, blocks: trade-trace-l4o)
○ trade-trace-6k8 [● P1] [feature] [import jsonl p1-core roadmap] - Implement import.validate/import.commit JSONL replay path (blocks: trade-trace-5qr, trade-trace-l4o)
○ trade-trace-6vd [● P2] [task] [dead-code deadcode-gate deadcode-hunt deadcode:exhaustive-20260518] - Final verification: exhaustive deadcode hunt 2026-05-18
○ trade-trace-6z5 [● P2] [feature] [opportunity p1-core reports roadmap] - Implement path-dependent report.opportunity (blocks: trade-trace-l4o)
○ trade-trace-74b [● P2] [feature] - Auto-derive inputSchema from example_minimal; populate ToolRegistration.json_schema (blocks: trade-trace-0r7, trade-trace-59l, trade-trace-re2)
○ trade-trace-7e2 [● P0] [bug] [export rc0 release security test-failure] - Fix exporter SECRET_PATTERNS compatibility alias for security tests (blocks: trade-trace-off)
● trade-trace-89x [● P2] [feature] - Embeddings opt-in: bge-small lazy download + tt model import air-gap path (blocked by: trade-trace-izh, blocks: trade-trace-0r7, trade-trace-heo)
○ trade-trace-8md [● P2] [task] [bughunt bughunt-gate bughunt:exhaustive-20260519 planning] - Run exhaustive bughunt lane synthesis before final verification (blocks: trade-trace-w9r)
○ trade-trace-8z2 [● P2] [feature] [p1-core reports risk roadmap] - Implement risk-unit write surface and report.risk (blocks: trade-trace-l4o)
○ trade-trace-alr [● P2] [task] [design p1-core roadmap sse subscribe transport] - Design HTTP/SSE transport and event-log subscribe API without violating local-only defaults (blocks: trade-trace-l4o)
● trade-trace-dhs [● P1] [task] - QC Gate: agent-ready (blocked by: trade-trace-0r7, trade-trace-re2, blocks: trade-trace-v0l)
○ trade-trace-dkm [● P2] [epic] [p1-core planning roadmap] - EPIC: P1 core roadmap — imports, review bundles, analytics, scoring, transports
○ trade-trace-gy1 [● P0] [bug] [rc0 release test-failure versioning] - Align smoke test version contract with rc0 prerelease policy (blocks: trade-trace-off)
● trade-trace-heo [● P2] [feature] - Embeddings opt-in: tt memory reindex --confirm (bead a4p-split-4) (blocked by: trade-trace-89x, trade-trace-izh, trade-trace-z6s, blocks: trade-trace-0r7, trade-trace-re2)
○ trade-trace-iuv [● P2] [feature] [p1-core rescan roadmap scoring] - Implement categorical/scalar scoring and journal.rescan_scoring (blocks: trade-trace-l4o)
○ trade-trace-izh [● P2] [feature] - Embeddings opt-in: sqlite-vec wiring + memory_node_embeddings storage (blocks: trade-trace-0r7, trade-trace-89x, trade-trace-heo, trade-trace-z6s)
● trade-trace-l4o [● P2] [task] [gate p1-core planning roadmap] - Final synthesis: P1 core roadmap readiness and sequencing gate (blocked by: trade-trace-4md, trade-trace-5qr, trade-trace-6k8, trade-trace-6z5, trade-trace-8z2, trade-trace-alr, trade-trace-iuv, trade-trace-pty, trade-trace-yai)
○ trade-trace-pty [● P2] [task] [forecastbench investigation p1-core roadmap] - Investigate ForecastBench compatibility and export feasibility (blocks: trade-trace-l4o)
● trade-trace-re2 [● P2] [task] - Docs QC: PRD MCP transport + AGENT_GUIDE.md truthfulness (blocked by: trade-trace-0m6, trade-trace-3u1, trade-trace-46p, trade-trace-74b, trade-trace-heo, blocks: trade-trace-dhs)
● trade-trace-v0l [● P1] [feature] - EPIC: Agent-ready — stdio MCP server, input schemas, agent guide, embeddings (blocked by: trade-trace-dhs)
● trade-trace-w9r [● P2] [task] [bughunt bughunt-gate bughunt:exhaustive-20260519] - Final verification: exhaustive repo bughunt 2026-05-19 (blocked by: trade-trace-8md)
○ trade-trace-yai [● P1] [feature] [p1-core review-bundle roadmap security] - Implement review.bundle with deterministic hash and source redaction (blocks: trade-trace-l4o)
● trade-trace-z6s [● P2] [feature] - Embeddings opt-in: API provider path + OS keyring (bead a4p-split-3) (blocked by: trade-trace-izh, blocks: trade-trace-0r7, trade-trace-heo)
bd list in_progress
◐ trade-trace-5lx [● P2] [epic] @Michael Crescenzo [dead-code deadcode-hunt deadcode:exhaustive-20260518 epic] - EPIC: exhaustive deadcode hunt 2026-05-18
◐ trade-trace-off [● P2] [task] @Michael Crescenzo - Cut pre-release v0.0.1rc0 to validate publish workflow (blocked by: trade-trace-1kr, trade-trace-7e2, trade-trace-gy1)
bd dep cycles

✓ No dependency cycles detected

bd dep list epic
  trade-trace-8md: Run exhaustive bughunt lane synthesis before final verification [P2] (open) via relates-to
  trade-trace-w9r: Final verification: exhaustive repo bughunt 2026-05-19 [P2] (open) via relates-to

bd duplicates pre
{
  "count": 1,
  "method": "mechanical",
  "pairs": [
    {
      "issue_a_id": "trade-trace-8md",
      "issue_a_title": "Run exhaustive bughunt lane synthesis before final verification",
      "issue_b_id": "trade-trace-w9r",
      "issue_b_title": "Final verification: exhaustive repo bughunt 2026-05-19",
      "method": "mechanical",
      "similarity": 0.46583751277532615
    }
  ],
  "schema_version": 1,
  "threshold": 0.45
}
```
## Planned mutation

- Create one bug bead for accepted candidates in candidate_matrix.json (11 total).
- Labels: bug, bughunt, bughunt:exhaustive-20260519, domain:*.
- Relation-based membership via `bd dep relate trade-trace-2d3 <bug-id>`.
- Keep root epic open; final gate will close after verification if graph/readbacks pass.

## Post-mutation snapshots
```
candidate_to_bead_map
{
  "CAND-001": "trade-trace-lum",
  "CAND-002": "trade-trace-b10",
  "CAND-003": "trade-trace-m8c",
  "CAND-004": "trade-trace-jky",
  "CAND-005": "trade-trace-re4",
  "CAND-006": "trade-trace-ke1",
  "CAND-007": "trade-trace-85i",
  "CAND-008": "trade-trace-e62",
  "CAND-011": "trade-trace-1zl",
  "CAND-012": "trade-trace-17p",
  "CAND-014": "trade-trace-vwa"
}
bd list bug findings open
○ trade-trace-17p [● P2] [bug] [bug bughunt bughunt:exhaustive-20260519 docs-truth domain:docs-ops] - Docs advertise nonexistent CLI commands: tt config set, tt init, and tt mcp
○ trade-trace-1zl [● P2] [bug] [bug bughunt bughunt:exhaustive-20260519 docs-truth domain:docs-ops] - README and architecture docs contain broken local links to PRD/VISION/docs paths
○ trade-trace-85i [● P2] [bug] [bug bughunt bughunt:exhaustive-20260519 data-integrity domain:memory] - memory.reflect documents atomic reflection+about edge but uses two transactions
○ trade-trace-b10 [● P2] [bug] [bug bughunt bughunt:exhaustive-20260519 domain:cli-contracts runtime] - journal.config_set mutates without --confirm despite confirm/preview contract
○ trade-trace-e62 [● P2] [bug] [bug bughunt bughunt:exhaustive-20260519 domain:memory idempotency] - memory.reflect idempotent retry without valid_from returns IDEMPOTENCY_CONFLICT
○ trade-trace-jky [● P1] [bug] [bug bughunt bughunt:exhaustive-20260519 domain:security security] - source.add persists secret-shaped title/note/summary free text unredacted
○ trade-trace-ke1 [● P1] [bug] [api-contract bug bughunt bughunt:exhaustive-20260519 domain:reports] - ReportFilter is echoed but ignored by multiple report implementations
○ trade-trace-lum [● P2] [bug] [api-contract bug bughunt bughunt:exhaustive-20260519 domain:cli-contracts] - Malformed CLI --*-json input bypasses JSON error-envelope contract
○ trade-trace-m8c [● P1] [bug] [bug bughunt bughunt:exhaustive-20260519 domain:security-ops test-failure] - exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection
○ trade-trace-re4 [● P2] [bug] [bug bughunt bughunt:exhaustive-20260519 data-integrity domain:storage-integrity] - forecast.supersede commits replacement forecast before supersedes edge/event
○ trade-trace-vwa [● P2] [bug] [bug bughunt bughunt:exhaustive-20260519 domain:tests test-failure] - Smoke/golden tests assert stale 0.0.1 while runtime/package version is 0.0.1rc0

bd dep list epic
  trade-trace-17p: Docs advertise nonexistent CLI commands: tt config set, tt init, and tt mcp [P2] (open) via relates-to
  trade-trace-1zl: README and architecture docs contain broken local links to PRD/VISION/docs paths [P2] (open) via relates-to
  trade-trace-85i: memory.reflect documents atomic reflection+about edge but uses two transactions [P2] (open) via relates-to
  trade-trace-8md: Run exhaustive bughunt lane synthesis before final verification [P2] (open) via relates-to
  trade-trace-b10: journal.config_set mutates without --confirm despite confirm/preview contract [P2] (open) via relates-to
  trade-trace-e62: memory.reflect idempotent retry without valid_from returns IDEMPOTENCY_CONFLICT [P2] (open) via relates-to
  trade-trace-jky: source.add persists secret-shaped title/note/summary free text unredacted [P1] (open) via relates-to
  trade-trace-ke1: ReportFilter is echoed but ignored by multiple report implementations [P1] (open) via relates-to
  trade-trace-lum: Malformed CLI --*-json input bypasses JSON error-envelope contract [P2] (open) via relates-to
  trade-trace-m8c: exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection [P1] (open) via relates-to
  trade-trace-re4: forecast.supersede commits replacement forecast before supersedes edge/event [P2] (open) via relates-to
  trade-trace-vwa: Smoke/golden tests assert stale 0.0.1 while runtime/package version is 0.0.1rc0 [P2] (open) via relates-to
  trade-trace-w9r: Final verification: exhaustive repo bughunt 2026-05-19 [P2] (open) via relates-to

bd graph epic

📊 Dependency graph for trade-trace-2d3:

  Status: ○ open  ◐ in_progress  ● blocked  ✓ closed  ❄ deferred

  LAYER 0 (ready)                    LAYER 1                      

  ┌───────────────────────────┐      ┌───────────────────────────┐
  │ ○ Docs advertise nonexis… │   ╭─▶│ ○ Final verification: ex… │
  │ trade-trace-17p P2        │   │  │ trade-trace-w9r P2        │
  └───────────────────────────┘   │  └───────────────────────────┘
                                  │
  ┌───────────────────────────┐   │
  │ ○ README and architectur… │   │
  │ trade-trace-1zl P2        │   │
  └───────────────────────────┘   │
                                  │
  ┌───────────────────────────┐   │
  │ ○ EPIC: exhaustive repo … │   │
  │ trade-trace-2d3 P2        │   │
  └───────────────────────────┘   │
                                  │
  ┌───────────────────────────┐   │
  │ ○ memory.reflect documen… │   │
  │ trade-trace-85i P2        │   │
  └───────────────────────────┘   │
                                  │
  ┌───────────────────────────┐   │
  │ ○ Run exhaustive bughunt… │───╯
  │ trade-trace-8md P2        │
  └───────────────────────────┘

  ┌───────────────────────────┐
  │ ○ journal.config_set mut… │
  │ trade-trace-b10 P2        │
  └───────────────────────────┘

  ┌───────────────────────────┐
  │ ○ memory.reflect idempot… │
  │ trade-trace-e62 P2        │
  └───────────────────────────┘

  ┌───────────────────────────┐
  │ ○ source.add persists se… │
  │ trade-trace-jky P1        │
  └───────────────────────────┘

  ┌───────────────────────────┐
  │ ○ ReportFilter is echoed… │
  │ trade-trace-ke1 P1        │
  └───────────────────────────┘

  ┌───────────────────────────┐
  │ ○ Malformed CLI --*-json… │
  │ trade-trace-lum P2        │
  └───────────────────────────┘

  ┌───────────────────────────┐
  │ ○ exporter.SECRET_PATTER… │
  │ trade-trace-m8c P1        │
  └───────────────────────────┘

  ┌───────────────────────────┐
  │ ○ forecast.supersede com… │
  │ trade-trace-re4 P2        │
  └───────────────────────────┘

  ┌───────────────────────────┐
  │ ○ Smoke/golden tests ass… │
  │ trade-trace-vwa P2        │
  └───────────────────────────┘

  Dependencies: 1 blocking relationships
  Total: 14 issues across 2 layers

bd children epic json
[]
bd dep cycles

✓ No dependency cycles detected

bd duplicates post
{
  "count": 34,
  "method": "mechanical",
  "pairs": [
    {
      "issue_a_id": "trade-trace-85i",
      "issue_a_title": "memory.reflect documents atomic reflection+about edge but uses two transactions",
      "issue_b_id": "trade-trace-re4",
      "issue_b_title": "forecast.supersede commits replacement forecast before supersedes edge/event",
      "method": "mechanical",
      "similarity": 0.6666598899910395
    },
    {
      "issue_a_id": "trade-trace-m8c",
      "issue_a_title": "exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection",
      "issue_b_id": "trade-trace-vwa",
      "issue_b_title": "Smoke/golden tests assert stale 0.0.1 while runtime/package version is 0.0.1rc0",
      "method": "mechanical",
      "similarity": 0.6321309586782036
    },
    {
      "issue_a_id": "trade-trace-m8c",
      "issue_a_title": "exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection",
      "issue_b_id": "trade-trace-lum",
      "issue_b_title": "Malformed CLI --*-json input bypasses JSON error-envelope contract",
      "method": "mechanical",
      "similarity": 0.5713966048595074
    },
    {
      "issue_a_id": "trade-trace-jky",
      "issue_a_title": "source.add persists secret-shaped title/note/summary free text unredacted",
      "issue_b_id": "trade-trace-m8c",
      "issue_b_title": "exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection",
      "method": "mechanical",
      "similarity": 0.549674733335335
    },
    {
      "issue_a_id": "trade-trace-jky",
      "issue_a_title": "source.add persists secret-shaped title/note/summary free text unredacted",
      "issue_b_id": "trade-trace-lum",
      "issue_b_title": "Malformed CLI --*-json input bypasses JSON error-envelope contract",
      "method": "mechanical",
      "similarity": 0.5422880034356343
    },
    {
      "issue_a_id": "trade-trace-ke1",
      "issue_a_title": "ReportFilter is echoed but ignored by multiple report implementations",
      "issue_b_id": "trade-trace-lum",
      "issue_b_title": "Malformed CLI --*-json input bypasses JSON error-envelope contract",
      "method": "mechanical",
      "similarity": 0.533268511568422
    },
    {
      "issue_a_id": "trade-trace-17p",
      "issue_a_title": "Docs advertise nonexistent CLI commands: tt config set, tt init, and tt mcp",
      "issue_b_id": "trade-trace-b10",
      "issue_b_title": "journal.config_set mutates without --confirm despite confirm/preview contract",
      "method": "mechanical",
      "similarity": 0.5299772194939868
    },
    {
      "issue_a_id": "trade-trace-e62",
      "issue_a_title": "memory.reflect idempotent retry without valid_from returns IDEMPOTENCY_CONFLICT",
      "issue_b_id": "trade-trace-85i",
      "issue_b_title": "memory.reflect documents atomic reflection+about edge but uses two transactions",
      "method": "mechanical",
      "similarity": 0.5253102067080877
    },
    {
      "issue_a_id": "trade-trace-m8c",
      "issue_a_title": "exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection",
      "issue_b_id": "trade-trace-re4",
      "issue_b_title": "forecast.supersede commits replacement forecast before supersedes edge/event",
      "method": "mechanical",
      "similarity": 0.5242440157242474
    },
    {
      "issue_a_id": "trade-trace-jky",
      "issue_a_title": "source.add persists secret-shaped title/note/summary free text unredacted",
      "issue_b_id": "trade-trace-re4",
      "issue_b_title": "forecast.supersede commits replacement forecast before supersedes edge/event",
      "method": "mechanical",
      "similarity": 0.5156094721508002
    },
    {
      "issue_a_id": "trade-trace-b10",
      "issue_a_title": "journal.config_set mutates without --confirm despite confirm/preview contract",
      "issue_b_id": "trade-trace-lum",
      "issue_b_title": "Malformed CLI --*-json input bypasses JSON error-envelope contract",
      "method": "mechanical",
      "similarity": 0.5053726572401017
    },
    {
      "issue_a_id": "trade-trace-17p",
      "issue_a_title": "Docs advertise nonexistent CLI commands: tt config set, tt init, and tt mcp",
      "issue_b_id": "trade-trace-1zl",
      "issue_b_title": "README and architecture docs contain broken local links to PRD/VISION/docs paths",
      "method": "mechanical",
      "similarity": 0.5053311557455662
    },
    {
      "issue_a_id": "trade-trace-m8c",
      "issue_a_title": "exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection",
      "issue_b_id": "trade-trace-b10",
      "issue_b_title": "journal.config_set mutates without --confirm despite confirm/preview contract",
      "method": "mechanical",
      "similarity": 0.5050480636316362
    },
    {
      "issue_a_id": "trade-trace-m8c",
      "issue_a_title": "exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection",
      "issue_b_id": "trade-trace-85i",
      "issue_b_title": "memory.reflect documents atomic reflection+about edge but uses two transactions",
      "method": "mechanical",
      "similarity": 0.49651399719880707
    },
    {
      "issue_a_id": "trade-trace-vwa",
      "issue_a_title": "Smoke/golden tests assert stale 0.0.1 while runtime/package version is 0.0.1rc0",
      "issue_b_id": "trade-trace-lum",
      "issue_b_title": "Malformed CLI --*-json input bypasses JSON error-envelope contract",
      "method": "mechanical",
      "similarity": 0.4939473344919644
    },
    {
      "issue_a_id": "trade-trace-ke1",
      "issue_a_title": "ReportFilter is echoed but ignored by multiple report implementations",
      "issue_b_id": "trade-trace-m8c",
      "issue_b_title": "exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection",
      "method": "mechanical",
      "similarity": 0.4928075812754707
    },
    {
      "issue_a_id": "trade-trace-ke1",
      "issue_a_title": "ReportFilter is echoed but ignored by multiple report implementations",
      "issue_b_id": "trade-trace-jky",
      "issue_b_title": "source.add persists secret-shaped title/note/summary free text unredacted",
      "method": "mechanical",
      "similarity": 0.49192648689204155
    },
    {
      "issue_a_id": "trade-trace-re4",
      "issue_a_title": "forecast.supersede commits replacement forecast before supersedes edge/event",
      "issue_b_id": "trade-trace-lum",
      "issue_b_title": "Malformed CLI --*-json input bypasses JSON error-envelope contract",
      "method": "mechanical",
      "similarity": 0.48531988260571124
    },
    {
      "issue_a_id": "trade-trace-vwa",
      "issue_a_title": "Smoke/golden tests assert stale 0.0.1 while runtime/package version is 0.0.1rc0",
      "issue_b_id": "trade-trace-re4",
      "issue_b_title": "forecast.supersede commits replacement forecast before supersedes edge/event",
      "method": "mechanical",
      "similarity": 0.48087836563958164
    },
    {
      "issue_a_id": "trade-trace-jky",
      "issue_a_title": "source.add persists secret-shaped title/note/summary free text unredacted",
      "issue_b_id": "trade-trace-vwa",
      "issue_b_title": "Smoke/golden tests assert stale 0.0.1 while runtime/package version is 0.0.1rc0",
      "method": "mechanical",
      "similarity": 0.47987394709335685
    },
    {
      "issue_a_id": "trade-trace-85i",
      "issue_a_title": "memory.reflect documents atomic reflection+about edge but uses two transactions",
      "issue_b_id": "trade-trace-lum",
      "issue_b_title": "Malformed CLI --*-json input bypasses JSON error-envelope contract",
      "method": "mechanical",
      "similarity": 0.47972017025021024
    },
    {
      "issue_a_id": "trade-trace-jky",
      "issue_a_title": "source.add persists secret-shaped title/note/summary free text unredacted",
      "issue_b_id": "trade-trace-b10",
      "issue_b_title": "journal.config_set mutates without --confirm despite confirm/preview contract",
      "method": "mechanical",
      "similarity": 0.47823022589983577
    },
    {
      "issue_a_id": "trade-trace-17p",
      "issue_a_title": "Docs advertise nonexistent CLI commands: tt config set, tt init, and tt mcp",
      "issue_b_id": "trade-trace-lum",
      "issue_b_title": "Malformed CLI --*-json input bypasses JSON error-envelope contract",
      "method": "mechanical",
      "similarity": 0.47773244159321615
    },
    {
      "issue_a_id": "trade-trace-vwa",
      "issue_a_title": "Smoke/golden tests assert stale 0.0.1 while runtime/package version is 0.0.1rc0",
      "issue_b_id": "trade-trace-b10",
      "issue_b_title": "journal.config_set mutates without --confirm despite confirm/preview contract",
      "method": "mechanical",
      "similarity": 0.47759803995644606
    },
    {
      "issue_a_id": "trade-trace-jky",
      "issue_a_title": "source.add persists secret-shaped title/note/summary free text unredacted",
      "issue_b_id": "trade-trace-85i",
      "issue_b_title": "memory.reflect documents atomic reflection+about edge but uses two transactions",
      "method": "mechanical",
      "similarity": 0.4754597305676618
    },
    {
      "issue_a_id": "trade-trace-m8c",
      "issue_a_title": "exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection",
      "issue_b_id": "trade-trace-17p",
      "issue_b_title": "Docs advertise nonexistent CLI commands: tt config set, tt init, and tt mcp",
      "method": "mechanical",
      "similarity": 0.4742507649835065
    },
    {
      "issue_a_id": "trade-trace-m8c",
      "issue_a_title": "exporter.SECRET_PATTERNS compatibility alias is missing and blocks pytest collection",
      "issue_b_id": "trade-trace-e62",
      "issue_b_title": "memory.reflect idempotent retry without valid_from returns IDEMPOTENCY_CONFLICT",
      "method": "mechanical",
      "similarity": 0.4732961060807582
    },
    {
      "issue_a_id": "trade-trace-8md",
      "issue_a_title": "Run exhaustive bughunt lane synthesis before final verification",
      "issue_b_id": "trade-trace-w9r",
      "issue_b_title": "Final verification: exhaustive repo bughunt 2026-05-19",
      "method": "mechanical",
      "similarity": 0.46583751277532615
    },
    {
      "issue_a_id": "trade-trace-jky",
      "issue_a_title": "source.add persists secret-shaped title/note/summary free text unredacted",
      "issue_b_id": "trade-trace-e62",
      "issue_b_title": "memory.reflect idempotent retry without valid_from returns IDEMPOTENCY_CONFLICT",
      "method": "mechanical",
      "similarity": 0.46501892574118164
    },
    {
      "issue_a_id": "trade-trace-e62",
      "issue_a_title": "memory.reflect idempotent retry without valid_from returns IDEMPOTENCY_CONFLICT",
      "issue_b_id": "trade-trace-lum",
      "issue_b_title": "Malformed CLI --*-json input bypasses JSON error-envelope contract",
      "method": "mechanical",
      "similarity": 0.4610089658264346
    },
    {
      "issue_a_id": "trade-trace-vwa",
      "issue_a_title": "Smoke/golden tests assert stale 0.0.1 while runtime/package version is 0.0.1rc0",
      "issue_b_id": "trade-trace-85i",
      "issue_b_title": "memory.reflect documents atomic reflection+about edge but uses two transactions",
      "method": "mechanical",
      "similarity": 0.45803614634636913
    },
    {
      "issue_a_id": "trade-trace-re4",
      "issue_a_title": "forecast.supersede commits replacement forecast before supersedes edge/event",
      "issue_b_id": "trade-trace-b10",
      "issue_b_title": "journal.config_set mutates without --confirm despite confirm/preview contract",
      "method": "mechanical",
      "similarity": 0.455835579561598
    },
    {
      "issue_a_id": "trade-trace-ke1",
      "issue_a_title": "ReportFilter is echoed but ignored by multiple report implementations",
      "issue_b_id": "trade-trace-vwa",
      "issue_b_title": "Smoke/golden tests assert stale 0.0.1 while runtime/package version is 0.0.1rc0",
      "method": "mechanical",
      "similarity": 0.45271126851520654
    },
    {
      "issue_a_id": "trade-trace-e62",
      "issue_a_title": "memory.reflect idempotent retry without valid_from returns IDEMPOTENCY_CONFLICT",
      "issue_b_id": "trade-trace-re4",
      "issue_b_title": "forecast.supersede commits replacement forecast before supersedes edge/event",
      "method": "mechanical",
      "similarity": 0.45037449130783164
    }
  ],
  "schema_version": 1,
  "threshold": 0.45
}
bd lint
✓ No template warnings found (43 issues checked)
bd orphans
✓ No orphaned issues found
bd status

📊 Issue Database Status

Summary:
  Total Issues:           128
  Open:                   43
  In Progress:            2
  Blocked:                13
  Closed:                 83
  Ready to Work:          30

For more details, use 'bd list' to see individual issues.

git status -sb
## main...origin/main [ahead 1]
?? audits/
?? docs/audits/
git status --short
?? audits/
?? docs/audits/
```
