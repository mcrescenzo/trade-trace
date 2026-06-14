# Trade Trace — Vision

**Status:** North star
**Date:** 2026-06-12
**Audience:** Us — maintainers, contributors, and the agents that work on and with this project

This is the highest-level document in the repository. The README describes
what Trade Trace *is* today; the PRD and architecture docs describe what is
*committed and shipped*. This document describes what we are ultimately
building. When it disagrees with the others, they are describing different
points on the same arc.

## North star

**Trade Trace is growing into a complete prediction-market trading agent:
software you point at real markets with real money, that researches,
forecasts, decides, trades, and — above all — gets measurably better over
time, operating on its own inside hard limits a human sets.**

Today Trade Trace is the foundation of that agent: the journal, memory, and
calibration substrate that makes everything the agent does recorded, scored,
and auditable. That is not a smaller product than the trader. It is the part
that has to exist first, because it is the part that makes the rest of it
trustworthy.

## Why we're building this

Three motivations, braided together. We want to be honest about all of them.

**The most honest scoreboard in AI.** The question underneath this project
is whether an LLM agent can genuinely learn from its own track record — not
"feels smarter," but *measurably better-calibrated*. Prediction markets are
the cleanest laboratory that exists for that question: forecasts resolve to
YES or NO on a date, a Brier score doesn't flatter anyone, and calibration
drift is arithmetic, not opinion. Most agents today are amnesiac — their
forecasts disappear into chat transcripts and their lessons evaporate
between sessions. We are building the agent that remembers exactly what it
believed, sees exactly how wrong it was, and carries the lesson forward.

**A trading agent that is actually good.** We are not coy about this: we
want an agent that trades real money well. But we believe lasting
profitability is downstream of process discipline — calibration, honest
review, rules that evolve with provenance — and that anyone claiming
otherwise is selling something. That belief dictates our order of
operations: measure before you improve, improve before you trade.

**Open infrastructure anyone can run.** The end-state is not a hosted black
box. Trade Trace is local-first, open-source software: one database on your
machine, no telemetry, no phone-home, your data and your keys never touching
our hands (or, for keys, the journal core at all). Success includes
strangers we never meet running their own agents on it, with their own
bounds and their own capital.

## Where this ends up

A mature Trade Trace wakes up with its memory intact. It scans prediction
markets, recalls what it learned the last times it saw structurally similar
ones, and writes down its own probability — timestamped, with its reasoning
and evidence — before the outcome is knowable. It sizes positions according
to its risk policy and places trades, all within bounds a human set: capital
caps, per-market exposure limits, venue allowlists, a kill switch. When
markets resolve, it scores itself, reflects on what the scores reveal, and
updates its own playbook with provenance pointing back to the trades that
taught it. Every step lands in an append-only audit trail a skeptic could
replay: not just what it traded, but what it believed, when, and why.

The human's role in that picture is deliberate: **set the bounds, review
the audits, adjust the limits. Never pick the trades.**

And the scope is deliberate too: **prediction markets, natively, forever.**
Binary and categorical event markets with explicit resolution rules are the
one arena where an agent's judgment gets graded unambiguously. We would
rather be the definitive prediction-market trading agent than a mediocre
everything-trader. Depth over breadth is not a phase; it is the identity.

## How we get there: autonomy is earned

Every current doc in this repo says "Trade Trace is not a trader." That is
true, and it is a *phase*, not a destiny. The arc has three stages, and the
gate between them is evidence — track record, calibration, audit
cleanliness — never a roadmap date.

**Phase 1 — the substrate (now).** Journal, typed memory graph, forecast
scoring, calibration reports, playbooks and strategies, exposed to agents
over MCP and a JSON-first CLI. Deliberately not a trader: no execution, no
credentials, no default network calls. This is not timidity — it is
sequencing. An agent that cannot keep an honest record of its own judgment
has not earned a wallet. We dogfood this phase live every day: real
forecasting loops on real markets, finding and fixing the friction.

**Phase 2 — paper and policy.** The agent proposes trades, deterministic
risk checks evaluate them, paper fills track what would have happened, and
reconciliation compares records against imported account truth. The agent
does everything except move money, and the system measures whether it
should be allowed to. Much of this surface already exists in the codebase —
designed, contract-checked, and frozen — waiting for the evidence that
unfreezes it.

**Phase 3 — bounded live execution.** Real orders, behind a separate safety
design: hard caps, staged capital, allowlisted venues, kill switches, and
the same append-only audit trail underneath everything. Execution arrives
last not because it is hard to build — it is the easiest part — but because
it is the hardest to deserve.

The gate between Phase 2 and Phase 3 is made measurable — not prose — by
[`docs/architecture/phase-gates.md`](docs/architecture/phase-gates.md) and
the `report.phase_gate_readiness` report: resolved-N track record, Brier and
skill versus the market baseline, reconciliation cleanliness, audit
readiness, and paper-fill coverage, each computed from the journal. The
*numeric thresholds* remain an explicit owner decision; the report can never
return `ready` until the owner sets them, so the agent cannot pick the bar
that grants itself a wallet.

## What never changes

These hold in every phase, including the last one:

- **Local-first.** One SQLite database on your machine. No cloud
  dependency, no telemetry, no background sync, no phoning home.
- **Append-only honesty.** Forecasts are committed before outcomes are
  known. History is never rewritten; corrections append. A thesis written
  after the fact is a rationalization, and the schema makes it impossible
  to pretend otherwise.
- **Process is graded separately from P&L.** Good process can lose money;
  bad process can make it. We always measure both, independently, because
  conflating them is how trading discipline dies.
- **Capability never outruns accountability.** No feature ships unless its
  behavior is recordable, scoreable, and replayable. The audit trail is
  the precondition for autonomy, not the paperwork after it.
- **Built for agents.** JSON-first, MCP and CLI surfaces, token-efficient,
  schema-checked. No human dashboard. Humans read audits and set bounds.
- **Credential discipline.** The journal and memory core stays
  credential-blind forever. Execution, when it comes, lives behind its own
  isolated safety boundary with its own design review.
- **No hype.** We never claim edge or profitability we have not measured,
  and nothing this project emits is financial advice.

## What success looks like

- The agent runs for months inside its bounds without intervention, and
  its calibration curve visibly improves — and we can trace any rule in
  its playbook back through the reflection that proposed it to the trades
  that taught it.
- Real capital, honestly measured expectancy over enough resolved markets
  to mean something, and an audit trail that survives a skeptic.
- Other people run their own. Agents we have never met keep their journals
  in Trade Trace; some of them trade.
- We can answer, with data instead of anecdotes: **did the agent earn its
  autonomy?**

That last question is the whole project.

## Where the detail lives

- [`README.md`](./README.md) — what Trade Trace is today, truthfully.
- [`docs/PRD.md`](./docs/PRD.md) — committed product requirements for the
  current phase.
- [`docs/architecture/product-scope-v002.md`](./docs/architecture/product-scope-v002.md)
  — the v0.0.2 scope, principles, and non-goals (formerly `docs/VISION.md`;
  it governs the current phase and its "not a trader" boundaries).
- [`docs/architecture/`](./docs/architecture/) — per-surface contracts and
  decision records.
