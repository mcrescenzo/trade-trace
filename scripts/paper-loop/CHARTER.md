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

## Loop status

PAUSED by owner 2026-07-14 after cycle 12 (backlog burned to zero the
same day — all paper-loop beads closed, suite 2802 green, pushed).
Restart (either harness — the skill is harness-shared per
trade-trace-dhvmi): Claude Code: `/loop 1h /paper-cycle` in a session in
this repo. opencode: `bash scripts/paper-loop/opencode-loop.sh` (hourly
wrapper) or `/paper-cycle` in the TUI per cycle. One driver at a time —
all drivers share `$TRADE_TRACE_HOME/.run.lock` or the cycle ledger as
the coordination point; check the ledger tail before starting a second
driver.
The held exercise position (20 YES @ 0.65, Fed no-change July) and 46
pending forecasts remain in the journal; the first resumed cycle should
settle-sweep them per conventions (several resolutions may be overdue
depending on pause length).

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

## Owner decisions — recorded 2026-07-13 (evening)

All four pending decisions were made by the owner after an adversarial
analysis pass (workflow wf_961e4deb-300; two draft recommendations were
reversed by it before presentation):

1. **Exercise trades authorized** — ~1 minimum-size ($10–20) labeled
   trade/day (`intent_type=exercise`, most-liquid qualifying market, full
   risk→intent→fill→receipt→reconcile→settle chain). The 0.05 conviction
   gate and the stale-edge abstention rule are UNCHANGED. Mandatory
   companion (trade-trace-u9u1c): phase_gate_readiness + audit_readiness
   segregate exercise from conviction activity so plumbing evidence can
   never read as earned skill. Convention details: conventions v9.
2. **Forecasts stay immutable; sweep tiered** — no supersession for
   staleness (source-verified: superseded rows never score → any
   movement-conditioned supersession biases Brier). Settle sweep
   fresh-tier: markets with `resolution_at` ≤7d OR `resolution_at=null`
   OR open positions; full sweep on runs where NN%6==1. Standing
   stale-edge abstentions carry forward in run summaries and are only
   re-derived if price moves a further 0.03.
3. **snapshot.fetch replay conflict is working-as-designed**
   (trade-trace-pzyvq closed) — fetch-class idempotency keys carry a
   per-attempt component; a same-key conflict means reuse the first
   snapshot, never mint a "fresh" replay of a stale price.
4. **audit_readiness legacy bucket authorized** (trade-trace-15i4q) —
   pre-v3 rows (created < 2026-07-13T15:00Z) report as
   `legacy_missing_rule_count` alongside; `blocking_count` reflects
   post-v3 discipline. Both counts always surfaced; phase-gates.md
   records this authorization.

Still owner-only, unchanged: contract invariants; risk-policy numeric
values and the 0.05 conviction edge gate; phase-gate thresholds
(remain unset).

## Escalation

PushNotification to the owner on: any out-of-zone blocker, two
consecutive failed cycles, any non-empty reconciliation mismatch that
survives investigation, or any suspected contract-invariant violation.
