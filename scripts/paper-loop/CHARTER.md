# Paper-Cycle Loop Charter

> Status: shipped — owner decisions of 2026-07-13 (epic trade-trace-x7w7s).
> Governs the session-driven self-improvement loop (`/loop 1h /paper-cycle`,
> skill at `.claude/skills/paper-cycle/SKILL.md`). The cron driver from the
> 2026-07-10 harness design is retired to a commented fallback.

## Goal

Autonomously exercise trade-trace end to end (paper trading against live
Polymarket data), review every run, and continuously fix and improve the
system. Improvement findings are the primary product; calibration
evidence keeps accruing but is secondary (methodology changes are allowed
and tracked via `conventions_version`).

## Ownership boundary

The orchestrator (Claude, main session) fixes **freely, immediately**:
playbook.md, conventions.md (with version bump), product code (with
ruff/mypy/targeted-pytest gates and tests for new behavior), test suite,
docs, and the loop's own assets (this charter, the skill, run.sh).

**Owner-only — never changed inline, always bead + explicit sign-off:**

1. **Contract invariants**: append-only storage, idempotency semantics,
   typed envelope contract, single-writer model
   (`docs/architecture/contracts.md`, `persistence.md`).
2. **Risk policy numeric values and the 0.05 edge gate**
   (`scripts/paper-loop/risk-policy-v1.json`, conventions trading rule).
   Policy changes only via a NEW `risk.policy_version_add` version after
   owner approval.
3. **Phase-gate thresholds** (`docs/architecture/phase-gates.md`) — by
   standing owner decision (trade-trace-cjgz2.5) these remain unset.

## Cadences

- **Cycle**: hourly (`/loop 1h /paper-cycle`); one trading pass + full
  review per cycle.
- **Deep sweep**: every 6th cycle — multi-agent status workflow replaces
  the quick triage.
- **Commits**: local, every cycle, bead-referenced.
- **Push**: batched, at deep-sweep cadence (~daily). Rationale: every
  main push auto-publishes a PyPI post-release; hourly pushes would spam
  the index. Local commits fully satisfy code freshness (editable
  install + fresh `tt` process per call).

## Durability & restart

The loop lives in a Claude Code session; it does NOT survive session
death (reboot, crash). That is accepted. Restart: open a session in this
repo and run `/loop 1h /paper-cycle`. The cycle ledger
(`~/.trade-trace-paper/cycle-ledger.md`) and bd carry all state — no
conversation memory is required to resume.

Fallback: the crontab still holds a **commented** headless entry
(`0 */6 ...paper-loop/run.sh`, scoped permissions). Re-enabling it is an
owner action; it must not run while the session loop is active (both
respect `$TRADE_TRACE_HOME/.run.lock`, but the courtesy rule is one
driver at a time).

## Pending owner decisions

- **Stale-forecast re-anchoring** — COST NOW QUANTIFIED (deep-sweep-1,
  cycle 6): the mandatory settle/edge sweep doubled in six runs (18→36
  markets, 36→72 adapter calls/run) as the book grew 22→40, and the same
  two stale edges (Sinner, BTC-65k) have been re-derived and re-abstained
  four consecutive runs. Related in-zone option awaiting the same
  decision: tier the settle sweep (full refresh only for markets with
  resolution_at within N days or open positions; complete sweep every Nth
  run) — affects resolution-detection latency, so bundled here rather
  than changed unilaterally. (Originally raised by run 2026-07-13-05,
  memory mem_utyqB5wm0Zsr5UXT): the loop's first-ever gate-clearing edge (Sinner
  US Open, +0.11) was a *staleness artifact* — a 3-day-old forecast
  against a market that moved on new information. The agent correctly
  abstained rather than trade a view it no longer holds. Question: should
  the loop re-anchor/supersede prior-run forecasts each pass (kills
  phantom edges, but erases forecast accountability and inflates forecast
  counts), refresh only when a stale forecast clears the gate (targeted
  supersede with lineage), or keep forecasts immutable and treat
  stale-edge abstention as the standing rule (status quo)? This
  interacts with the edge gate and scoring semantics — owner call.

- **Edge gate (0.05)**: with honest no-private-info forecasts tracking
  liquid venues within ~0.01–0.03, the loop is structurally zero-trade,
  so `paper_fill_coverage` stays 0 and the risk→intent→fill chain goes
  unexercised. Options when the owner is ready: keep 0.05 (abstention
  evidence only), lower it via risk-policy v2, or authorize a periodic
  minimum-size exercise trade. Until then: zero trades is correct
  behavior, not a defect.
- **Pre-v3 forecast backfill** (bead trade-trace-55ybn): the 18 forecasts
  made before conventions v3 lack forecast-level rule text; decide
  supersede / accept-as-legacy / criterion carve-out.

## Escalation

PushNotification to the owner on: any out-of-zone blocker, two
consecutive failed cycles, any non-empty reconciliation mismatch that
survives investigation, or any suspected contract-invariant violation.
