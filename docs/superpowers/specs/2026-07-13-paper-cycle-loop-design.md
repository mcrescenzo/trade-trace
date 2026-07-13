# Paper-Cycle Self-Improvement Loop — Design

> Status: design — approved by owner 2026-07-13, implementation same day
> Epic: trade-trace-x7w7s. Supersedes the cron schedule from
> `2026-07-10-paper-loop-evidence-harness-design.md` (harness itself is
> retained; only the driver changes).

## Goal shift

The loop's primary goal changes from **evidence accumulation** (stable
methodology, cron-driven, nobody reads the runs) to **autonomous
self-improvement** (every run is reviewed by an orchestrator with edit
rights who fixes what it surfaces). Paper trading remains the workload;
bugs, friction, and improvements become the primary product. Calibration
evidence keeps accruing but is secondary; methodology changes are
tolerated and tracked via `conventions_version` bumps.

## Owner decisions (2026-07-13)

| Decision | Choice |
|---|---|
| Driver | Claude Code session loop: `/loop 1h /paper-cycle` — orchestrator (main session) drives; ScheduleWakeup paces hourly |
| Trading pass | Background Opus subagent executing `scripts/paper-loop/playbook.md` via **tt CLI** (never MCP — see Freshness) |
| Review | Every cycle: exhaustive read of run summary, logs, journal deltas; deep multi-agent sweep every 6th cycle |
| Ownership | Orchestrator fixes freely: playbook, conventions (version bump), product code (gates), tests, docs. **Owner-only:** contract invariants (append-only/idempotency/typed envelope/single-writer), risk-policy numeric values + the 0.05 edge gate, phase-gate thresholds |
| Durability | Cron entry kept **commented** as manual fallback; restart = `/loop 1h /paper-cycle` in any session |
| Push cadence | Commit locally every cycle; push batched ~daily (main pushes auto-publish PyPI post-releases) |
| Edge gate | Stays 0.05 — **pending owner decision** recorded in CHARTER.md (loop stays zero-trade until changed; paper_fill_coverage stays 0) |

## Freshness guarantee (the load-bearing design fact)

trade-trace is an editable install; the `tt` CLI spawns a fresh process
per call, so product-code fixes landed in cycle N are live in cycle N+1
with no reinstall. The MCP server is the opposite — a long-lived process
that caches stale code for its whole session (documented June trap).
Therefore the trading agent MUST use the tt CLI. Playbook/conventions
are re-read from disk each pass; the cycle skill is re-read each wake.
Local commits are sufficient for freshness; pushing is a publication
concern only.

## Components

- `.claude/skills/paper-cycle/SKILL.md` (repo-tracked; `.gitignore`
  amended to admit `.claude/skills/`) — the one-cycle procedure.
- `scripts/paper-loop/CHARTER.md` — ownership boundary, cadences,
  restart/fallback procedure, pending owner decisions.
- `scripts/paper-loop/playbook.md` — unchanged role (trading-agent
  contract); Phase-0 fix adds `resolution_rule_text` + `resolution_at`
  to every `forecast.add`.
- `scripts/paper-loop/conventions.md` v3 — thin-book rule: a near-empty
  book's midpoint is meaningless; anchor to last trade and caveat it.
- Cycle ledger: `~/.trade-trace-paper/cycle-ledger.md` (journal home,
  out of git) — one line per cycle.

## Cycle anatomy

1. **Trade** — spawn background Opus agent: one playbook pass via tt CLI
   against `~/.trade-trace-paper`.
2. **Review** (every cycle) — run summary end to end; day-log grep for
   ERROR/denial/skip; `report.reconciliation_mismatches` (codes must stay
   empty); `report.audit_readiness` (blocking count must not grow);
   friction items.
3. **Triage & fix** — in-zone: fix now (product code requires
   ruff/mypy/targeted pytest before commit). Out-of-zone: bead + owner
   flag. Discovered work: bead with `discovered-from`.
4. **Record** — local commit (bead refs); ledger line.
5. **Deep sweep** (every 6th cycle) — multi-agent status workflow
   (runs/journal/issues lanes) instead of quick triage; batch push
   happens here.
6. **Sleep** — hourly wake via `/loop`.

Failure handling: trading-agent failure → diagnose; fix in-zone or bead;
PushNotification to owner on anything blocking. Never fabricate journal
evidence; zero-trade cycles are normal.

## Phase plan

- **Phase 0** (trade-trace-x7w7s.1): playbook forecast fixes
  (`resolution_rule_text`, `resolution_at`), conventions v3 thin-book
  rule, finding beads (forecast.list read gap; pre-fix forecast backfill
  decision).
- **Phase 1** (x7w7s.2): skill + charter + README updates.
- **Phase 2** (x7w7s.3): comment out cron, batch push, start
  `/loop 1h /paper-cycle`; cycle 1 works beads trade-trace-ismzy and
  trade-trace-0c7cn as its improve-phase.
