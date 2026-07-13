---
name: paper-cycle
description: One full cycle of the trade-trace self-improvement loop — spawn a background trading agent for one paper-trading pass, then exhaustively review its output, fix in-zone issues immediately, file beads for the rest, commit, and log the cycle. Designed to be driven hourly via `/loop 1h /paper-cycle`. Use when the user starts or resumes the paper-cycle loop, or asks for a single supervised cycle.
---

# Paper-Cycle: trade → review → improve

You are the ORCHESTRATOR of the trade-trace self-improvement loop
(design: `docs/superpowers/specs/2026-07-13-paper-cycle-loop-design.md`,
epic trade-trace-x7w7s). Each invocation = exactly one cycle. Read
`scripts/paper-loop/CHARTER.md` before your first cycle in a session —
it defines your ownership boundary and the owner-only carve-outs.

State lives in: `~/.trade-trace-paper/` (journal, logs, run reports,
`cycle-ledger.md`). The repo checkout is `/home/hermes/code/trade-trace`.

## Step 1 — Orient

- `tail -5 ~/.trade-trace-paper/cycle-ledger.md` (create the file with a
  header line if missing). Determine this CYCLE_N = last cycle + 1.
- `bd ready` — note open `paper-loop`-labeled beads; pick up to 2 as this
  cycle's improve-phase candidates (prefer ones blocking the loop itself).
- If the previous ledger line records an unresolved BLOCKER, address it
  before trading.

## Step 2 — Trade (background agent)

Spawn ONE background agent (Agent tool, `model: opus`) with this prompt
shape (adapt bracketed parts only):

> You are the trading agent for ONE pass of the Trade Trace paper-loop.
> Execute /home/hermes/code/trade-trace/scripts/paper-loop/playbook.md
> end to end, exactly. Read it and
> scripts/paper-loop/conventions.md FIRST. Transport: the `tt` CLI with
> `TRADE_TRACE_HOME=$HOME/.trade-trace-paper` and
> `TRADE_TRACE_DISPATCH_TRACE=1` exported on every call (fresh
> process per call — this is required so current repo code is always
> exercised; do NOT use an MCP server even if one is connected).
> `--actor-id agent:paper-loop` on every call. Known state: risk policy
> policy_key=paper-loop version=1; conventions_version per
> conventions.md. NO git commands, NO code edits, NO pushes; `bd create`
> (label paper-loop) only if something blocks the run. Return: RUN_ID,
> counts (forecasts/intents/fills/abstentions/settlements),
> reconciliation codes, run-summary path, friction list, PASS/CONCERNS
> self-assessment.

While it runs, do Step 3 prep (read open bead details for the
improve-phase candidates).

## Step 3 — Review (every cycle, no skipping)

When the agent completes, verify its claims — the report is a claim, the
journal is the proof:

1. Read the run summary it names (`~/.trade-trace-paper/reports/<RUN_ID>.md`) end to end.
2. `grep -iE "error|denied|permission|skipping|traceback" ~/.trade-trace-paper/logs/run-$(date -u +%F).log` — anything new needs an explanation.
3. `TRADE_TRACE_HOME=$HOME/.trade-trace-paper tt report reconciliation_mismatches` — mismatch codes must be `[]`; any code = investigate NOW.
4. `TRADE_TRACE_HOME=$HOME/.trade-trace-paper tt report audit_readiness` — blocking_count must NOT have grown (post-v3 forecasts must carry `resolution_rule_text`/`resolution_at`; if a new forecast is blocking, the playbook contract regressed).
5. Collect every friction item from the summary + the agent's return.

## Step 4 — Triage & fix

For each issue (from Step 3 or the improve-phase bead candidates):

- **In-zone** (playbook, conventions [bump `conventions_version`],
  product code, tests, docs, loop assets): fix NOW. Product-code changes
  require `ruff check src tests && mypy src` and targeted `pytest`
  (relevant test files) green before commit; new behavior gets a test.
- **Out-of-zone** (see CHARTER: contract invariants, risk-policy values +
  edge gate, phase-gate thresholds): file/annotate a bead, flag for the
  owner in the ledger, do NOT change it.
- Discovered work you won't do this cycle: `bd create` with
  `--deps discovered-from:<bead>` and label `paper-loop`.
- bd hygiene: claim before working, close with a reason when done.

## Step 5 — Record

- Commit locally (NO push — push policy is in CHARTER.md): one commit per
  logical fix, message referencing the bead id. Local commits are what
  the next cycle's `tt` processes execute — freshness needs nothing more.
- Append ONE ledger line to `~/.trade-trace-paper/cycle-ledger.md`:
  `cycle <N> | <UTC timestamp> | run <RUN_ID> <PASS/FAIL> | f<forecasts> t<trades> a<abstentions> | recon <codes|clean> | fixed: <commits/beads or none> | filed: <beads or none> | notes: <blockers/owner-flags or ->`

## Step 6 — Deep sweep (every 6th cycle) and push

If CYCLE_N % 6 == 0:
- Run the deep status sweep instead of stopping at Step 3: a Workflow
  with three read-only Sonnet lanes (run summaries since last sweep;
  journal reports via tt — calibration/exposure/reconciliation/
  audit_readiness/phase_gate_readiness; bd + journal-memory inventory),
  then triage its findings through Step 4. VALIDATE each lane's payload
  before trusting it — a lane that returns placeholder/degenerate
  content ("test", generic facts, no ids) did not do the work: re-run
  that lane directly and note it in the ledger (sweep-1 precedent: the
  runs lane returned junk that schema validation could not catch).
- Batch push: `git pull --rebase && git push` (this is the ~daily PyPI
  publication moment; skip if the owner said hold).

## Failure handling

- Trading agent fails/errors: diagnose from its output + logs. In-zone
  cause → fix and note; otherwise bead + ledger BLOCKER. One retry of the
  trading pass is allowed per cycle if the cause was fixed.
- Anything requiring an owner decision, or a second consecutive failed
  cycle: PushNotification to the owner and record BLOCKER in the ledger.
- Never fabricate journal evidence. Zero-trade cycles are normal and
  expected (efficient markets + owner-held 0.05 edge gate).

## Loop mechanics

This skill does ONE cycle. Hourly cadence comes from invoking it as
`/loop 1h /paper-cycle` — the loop machinery handles the wake-ups. After
Step 5/6, end the cycle; do not self-schedule here. Restart after any
session death: `/loop 1h /paper-cycle` in a fresh session (see
CHARTER.md).
