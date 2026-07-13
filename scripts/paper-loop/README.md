# Paper-Loop Evidence Harness

Cron-driven headless-Claude harness that runs the full Phase-2
paper-trading chain against live Polymarket data and accumulates
calibration + paper-P&L evidence in `~/.trade-trace-paper`.

Spec: `docs/superpowers/specs/2026-07-10-paper-loop-evidence-harness-design.md`
Bead: trade-trace-jbn3m · Conventions: `conventions.md` · Procedure: `playbook.md`

## One-time setup

```bash
bash scripts/paper-loop/setup.sh   # idempotent; safe to re-run
```

Initializes the journal home, enables Gamma (this home only), seeds risk
policy v1 (`risk-policy-v1.json` — the loop's constitution; change limits
only by adding a NEW policy version file + version bump).

## Running

- **Primary (since 2026-07-13): the self-improvement loop** — in a
  Claude Code session in this repo run `/loop 1h /paper-cycle`. Each
  hourly cycle spawns a background trading agent (playbook via `tt` CLI),
  then the orchestrator reviews the run, fixes issues, and logs to
  `~/.trade-trace-paper/cycle-ledger.md`. Governance:
  `scripts/paper-loop/CHARTER.md`; procedure:
  `.claude/skills/paper-cycle/SKILL.md`. Restart after session death:
  the same one line in a fresh session.
- Supervised single pass (headless wrapper): `bash scripts/paper-loop/run.sh`
  (watch: `tail -f ~/.trade-trace-paper/logs/run-$(date -u +%F).log`)
- Interactive pass: `/paper-trade` in a Claude Code session in this repo.
- Sanity check without running: `bash scripts/paper-loop/run.sh --dry-run`

## Fallback: headless cron (retired 2026-07-13, kept commented)

The crontab holds a commented entry running `run.sh` every 6 hours with
scoped permissions. Re-enabling it is an owner action (uncomment via
`crontab -e`) and it must not run concurrently with the session loop —
one driver at a time. The prepared entry:

```
0 */6 * * * bash -lc '/home/hermes/code/trade-trace/scripts/paper-loop/run.sh' >> /home/hermes/.trade-trace-paper/logs/cron.log 2>&1
```

## Pause protocol

Pause the cron (comment the line) before running any long autonomous
Workflow/drain job in this repo — see bd memory
`drain-workflow-vs-ax-cron-collision`. This loop is git-free so the old
branch-collision failure cannot recur, but two concurrent Claude
processes still contend for attention and tokens.

## Where things live

- Journal (SQLite, append-only evidence): `~/.trade-trace-paper/trade-trace.sqlite`
- Run summaries: `~/.trade-trace-paper/reports/<RUN_ID>.md`
- Logs: `~/.trade-trace-paper/logs/` (per-day run log + cron.log)
- Evidence read-back: `report.calibration`, `report.paper_exposure`,
  `report.current_exposure`, `report.reconciliation_mismatches`,
  `report.phase_gate_readiness` (thresholds owner-unset by design)

## Boundaries

Paper only — no live-execution code path exists in this repository (owner
decision 2026-07-10, `docs/architecture/phase-gates.md`). The loop never
runs git, never edits code, and files friction to beads (label
`paper-loop`).

Headless runs use a scoped permission allowlist
(`headless-settings.json`: trade-trace MCP tools, journal-home reads/writes,
`bd create`; git/gh/crontab/web explicitly denied) — NOT
`--dangerously-skip-permissions` (owner decision 2026-07-12,
trade-trace-99vch). If a run logs a permission denial for something the
playbook legitimately needs, extend the allowlist deliberately rather than
reaching for the dangerous flag.
