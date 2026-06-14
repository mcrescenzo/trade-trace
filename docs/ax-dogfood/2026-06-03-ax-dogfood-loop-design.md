# AX Dogfood Loop — Design Spec

> Status: **design (awaiting owner review)**. Authored 2026-06-03.
> This spec defines a recurring, cron-scheduled Claude agent that *uses*
> Trade Trace as a live trading bot would, discovers experience friction,
> fixes what it can directly, and files larger work to Beads. It is the
> contract the implementation plan must satisfy. No code yet.

## 1. Purpose & north star

Build a **recurring Agent-Experience (AX) dogfooding + improvement loop**: a
single Claude agent that, on each cron firing, *becomes a live trading bot*
using Trade Trace through its native MCP surface, honestly logs every point of
friction (discoverability, clarity, ergonomics, bugs), then switches hats and
**improves the system** — fixing bugs/friction directly in the repo and filing
genuinely new features / major reworks to Beads for the owner.

The north star is **lived experience quality**, not invariant verification.
The engine of the design is a deliberate hat-switch:

- **As a user (cold):** drive the system with only its public affordances
  (tool schemas, docs, bootstrap packets). The agent's confusion *is the
  signal*. It must not pre-read source in this phase.
- **As an engineer (informed):** take the friction log and improve the system.

## 2. Relationship to existing infrastructure (what this is NOT)

This loop deliberately does not duplicate prior work; it sits in a clean gap.

- **tracelab** (`docs/tracelab-design.md`, epic `trade-trace-04is`, closed):
  a heavyweight harness proving *substrate correctness* — data-loss,
  single-writer-lock recovery, scorecards, multi-agent invariants. It proves
  "the system holds." This loop *consumes* that validated substrate and
  evaluates "did using it feel good / make sense."
- **`docs/architecture/dogfood-protocol.md`** (shipped): pins *loop-usefulness*
  acceptance criteria deterministically against a synthetic journal. This loop
  is exploratory and qualitative, not a deterministic gate.
- **`docs/AGENT_GUIDE.md`**: defines the canonical journal loop a bot follows
  (bootstrap → targeted reads → writes). This loop *follows* that guide as a
  user and reports where it is wrong, unclear, or incomplete.
- **`docs/LIVE_TEST_CHARTER.md`** (locked): single-writer concurrency contract.
  Untouched; informs the intentional-design list (single-writer is deliberate).

## 3. Settled decisions

| Decision | Choice | Rationale |
|---|---|---|
| Interaction surface | **MCP-primary** (`trade-trace-mcp`) | A real bot connects via MCP; tool names/schemas/descriptions surfaced by `tools/list` *are* the discoverability surface. May spot-check CLI parity. |
| Journal continuity | **Hybrid**: persistent spine + per-run cold-start probe | Persistent home exercises recall / calibration buildup / position lifecycle; a throwaway cold-start each run re-probes onboarding friction as docs/tools evolve. |
| Market data | **Live Polymarket fetch** | Most faithful to a real bot; exercises adapter/scan/snapshot friction. Requires enabling network (currently fail-closed) in the loop home only. |
| Resolution ground-truth | **Agent determines outcome, records via `resolution.add`** | Gamma returns `outcome_label='unknown'` even on resolved markets. On a multi-day cron, early forecasts genuinely resolve later; the bot determines the true outcome (Gamma closed/price fields and/or its own research) and records with confidence ≥0.9 + binary label so auto-scoring fires. The "how do I even know the outcome" struggle is itself a first-class finding. |
| Integration / git | **Persistent `ax-dogfood` branch**, dedicated checkout | Continuity comes from the *working tree* (editable install runs working-tree files), so a branch does not hinder refinement. Branch = review + blast-radius control. Rebase onto `origin/main` at run start; standing PR; **never push main** (push-to-main auto-publishes a `.post` to PyPI). |
| Checkout | **Dedicated to the loop** for the experiment's duration | No concurrent owner work in this checkout, so the working tree can live on `ax-dogfood` permanently. |
| Fix authority | **Fix every bug/friction/clarity issue directly, no cap; new features / major reworks → Beads** | Each fix is an atomic commit, keeping even a multi-fix run reviewable. |
| Model | **Opus 4.8** per run | Best at deep UX critique + safe direct fixes. |
| Run budget | **Bounded ~one full lifecycle pass** per firing | Predictable, reviewable per run. |
| Loop journal home | **`~/.trade-trace-axloop`** (outside repo) | DB churn never hits git; isolated from the owner's real `~/.trade-trace` and the trader home. Actor `agent:ax-dogfood`. |

## 4. The run loop (one cron firing)

### A. Sync & orient (as a dev)
1. `git fetch && git rebase origin/main` onto `ax-dogfood`. On conflict: skip
   the rebase, log it, continue — never blocks the run.
2. Read `docs/ax-dogfood/registry.md` (rolling friction registry) and
   `docs/ax-dogfood/intentional-design.md` (do-not-fix list) so the run does
   not re-report or "fix" known/intentional behavior.

### B. Be the trading bot (as a user, COLD) — friction discovery
Drive the `docs/AGENT_GUIDE.md` journal loop through MCP, leaning on
`tool.schema` and the bootstrap packet like a real bot, **narrating friction as
it goes**. The agent must NOT read implementation source in this phase.
1. **Orient:** `report.bootstrap` → `report.work_queue` / `report.lifecycle` /
   `report.recall_receipts`. (Does the bot actually know what to do next?)
2. **Resolve due:** check its own open forecasts for markets that have since
   closed; determine the true outcome as faithfully as possible; record via
   `resolution.add` (confidence ≥0.9 + binary label).
3. **Scan & forecast:** fetch live Gamma markets, pick a few, form a thesis,
   `forecast.add` (with confidence), record decision / `pretrade_intent`,
   `paper_enter`, `snapshot`.
4. **Review:** `report.calibration` / `report.coach` / process reports — *is
   the feedback actually useful to me as a bot?*
5. **Remember:** `memory.retain` / `memory.recall` / `reflection`.
6. **Cold-start probe:** spend a few minutes onboarding a throwaway home from
   scratch to re-probe first-run friction; destroy it after.

### C. Switch hats — improve what hurt (as an engineer, INFORMED)
Triage each friction item (§5); fix bugs/friction/clarity directly with
atomic commits; file new features / major reworks to Beads.

### D. Close out
Run quality gates (§6); commit; push `ax-dogfood`; update the standing PR;
write the run report (§7); update the rolling registry; hand off.

## 5. Triage rubric

**Fix directly this run** (atomic commit + regression test where applicable):
- Bugs with a contained fix.
- Confusing/inaccurate tool **schema descriptions**, error messages,
  `next_actions` hints.
- **Docs** drift (AGENT_GUIDE, getting-started) where reality ≠ docs.
- Small ergonomics (missing obvious default, unhelpful validation message).

**File to Beads** (`label: ax-dogfood`, friction evidence in the description):
- Genuinely new tools/features; major or multi-file/cross-cutting reworks.
- Anything ambiguous or design-level where the "right" answer is not obvious.
- Anything that looks like a bug but might be intentional → file as a
  *question*, do not fix.

**Contract firewall (always a Bead, never a direct edit):** append-only,
idempotency, the typed envelope, single-writer. Even a "small" change here is
filed.

**Intentional-design list (`docs/ax-dogfood/intentional-design.md`):** deliberate
behaviors that look like bugs — resolution-does-not-close-position (pinned
FINDING), single-writer-only, Gamma `unknown`, the auto-score confidence ≥0.9
gate. Seeded from existing `bd` memories + tracelab findings. The cold bot in B
may still *report* friction around these; the engineer in C files-as-question
rather than "fixing."

## 6. Guardrails & honesty

- **Atomic commits, gated before push.** Per fix: `ruff check` + `mypy src` +
  targeted tests. Before pushing the batch: one full `pytest -q` (currently
  2216 tests). The batch pushes only if green.
- **No fake-green.** Never weaken, skip, or delete a test to make a fix pass.
  If a fix cannot pass gates, **revert it and file a Bead**. The run report
  distinguishes *fixed & gate-verified* from *filed* from
  *attempted-then-reverted* — no rounding up.
- **MCP hot-reload caveat.** A tool-code fix does not affect the
  already-running MCP server; it lands next run (fresh server). Verify such
  fixes via a unit test in-session and note "effective next run."
- **Overlap safety.** A lockfile prevents two cron firings from running against
  the same home/branch concurrently.
- **Network isolation.** Polymarket network is enabled only in the loop home's
  config; never globally and never in the owner's real journal.

## 7. Outputs & dedup (all committed on `ax-dogfood`)

- **Run report** → `docs/ax-dogfood/runs/YYYY-MM-DD-NN.md`: friction found,
  fixes (with commit SHAs), Beads filed, gate results, handoff notes.
- **Rolling friction registry** → `docs/ax-dogfood/registry.md`: every friction
  item with status (open / fixed / filed-as-bead). Read at run start for dedup.
- **Intentional-design list** → `docs/ax-dogfood/intentional-design.md`.
- **Beads**: `label:ax-dogfood`; `bd search` before filing to dedup; friction
  evidence in the description.

## 8. Packaging & mechanism

- **Runner:** local cron → headless `claude -p "/ax-dogfood"` in the repo dir,
  with `trade-trace-mcp` connected and Polymarket network enabled. Remote
  `/schedule` routines cannot reach the local repo/MCP/network, so it must be
  local cron.
- **Artifact:** a project slash command `.claude/commands/ax-dogfood.md` holding
  the whole playbook, so it can also be fired manually as `/ax-dogfood` to
  dry-run. Cron calls that command headless with `--model opus`.
- **Isolated journal:** `TRADE_TRACE_HOME=~/.trade-trace-axloop`, actor
  `agent:ax-dogfood`. Initialized once with network/Gamma enabled.

## 9. Open items to resolve during planning

- Exact mechanism the cold bot uses to *determine* a real-world outcome
  faithfully (Gamma raw fields vs. its own web research) and how it records
  provenance / confidence honestly without fabricating ground-truth.
- Seeding content for the initial `intentional-design.md` and `registry.md`.
- Cron cadence + lockfile location (owner-operated; loop must be safe to fire
  on any schedule).
- Whether the cold-start probe in B-6 is every run or every Nth run.
- Per-run wall-clock / token ceiling enforcement under "bounded one pass."

## 10. Non-goals

- Not a substrate/correctness harness (that is tracelab).
- Not a deterministic loop-usefulness gate (that is dogfood-protocol).
- Not authorized to push `main`, tag releases, publish to PyPI, or touch the
  owner's real journal or the trader's home.
