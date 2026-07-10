# Paper-Loop Evidence Harness — Design

> Status: design — approved by owner 2026-07-10, pending implementation
> Owner decisions recorded inline. Implementation plan to follow
> (docs/superpowers/plans/).

## Goal

Give an AI agent (Claude, headless) a durable end-to-end environment that
exercises the full Phase-2 paper-trading surface against live Polymarket
data, on a fixed cadence, to accumulate the evidence stream the Phase-3
gate criteria are defined over (resolved_n, brier, skill_vs_market,
reconciliation_cleanliness, audit_readiness, paper_fill_coverage — see
`docs/architecture/phase-gates.md`).

**Primary goal: evidence accumulation.** Not friction-hunting (that was
the June ax-dogfood loop), not interactive co-trading. Friction is filed
to Beads only when it blocks a run; the loop never edits code.

## Owner decisions (2026-07-10)

| Decision | Choice |
|---|---|
| Goal | Evidence accumulation (calibration + paper-P&L track record) |
| Vehicle | Local cron + headless `claude -p`, journal-only writes, zero git |
| Approach | New purpose-built `scripts/paper-loop/` (ax-dogfood assets untouched as historical record) |
| Risk scale | $10,000 paper bankroll, 2% per-intent notional cap |
| Cadence | Every 6 hours (4 runs/day) |
| Model | Opus for all runs |

## Non-goals / hard boundaries

- **No live execution.** No order placement, signing, credentials, or
  custody path exists in the repo (owner decision trade-trace-cjgz2.5,
  2026-07-10); this harness does not change that and must never imply
  otherwise.
- **No git operations from the loop.** `run.sh` contains no git commands.
  Run artifacts live under the journal home, outside the repo. This
  structurally removes the June cron-vs-drain collision class AND the
  PyPI-auto-publish-on-main-push hazard.
- **No inline code fixes during runs.** Substrate friction becomes a bead
  with run evidence attached; the methodology stays stable so the
  evidence stays comparable.
- **No mid-stream risk-policy edits.** Policy changes only via a new
  `risk.policy_version_add` version.

## Components (`scripts/paper-loop/`, repo-committed)

| File | Purpose |
|---|---|
| `setup.sh` | One-time idempotent bootstrap of the journal home (see below) |
| `mcp.json` | MCP server config for headless runs |
| `playbook.md` | The per-run procedure (phases 1–6 below) |
| `conventions.md` | Fill-model + reconciliation + idempotency conventions (versioned decisions, not prompt folklore) |
| `run.sh` | Cron wrapper: PATH hardening, non-blocking flock, logging, headless invocation; supports manual single-pass runs |
| `README.md` | Operator doc: enable/pause protocol, validation staging, log locations |

Plus a gitignored local slash command (`.claude/commands/paper-trade.md`)
that just points at `playbook.md`, mirroring the ax-dogfood pattern —
headless runs never depend on it.

## Journal home & config

- Fresh dedicated home: `~/.trade-trace-paper` (`TRADE_TRACE_HOME`).
  Existing homes are stale (`~/.trade-trace` at schema 15,
  `~/.trade-trace-axloop` June-era) and stay untouched.
- `setup.sh` runs `tt journal init` (forward-migrates to current schema),
  then via `tt journal config_set --confirm`:
  - `network.polymarket.enabled=true`
  - `network.polymarket.gamma_base_url=https://gamma-api.polymarket.com`
    (explicit — this key has **no built-in default**)
  - `network.polymarket.polygon_rpc_url` left **unset**: resolution uses
    Gamma-derived `winningOutcome`/`outcomePrices` + manual
    `resolution.add`, the pattern validated by the June loop.
- `setup.sh` then seeds **risk policy v1** (below) and verifies with
  `tt journal status`.

## MCP wiring (`mcp.json`)

Server `trade-trace` → resolved absolute path to `trade-trace-mcp`, env:

- `TRADE_TRACE_HOME=~/.trade-trace-paper` (expanded)
- `MCP_ACTOR_ID=agent:paper-loop`
- `TRADE_TRACE_DISPATCH_TRACE=1` — feeds deferred bead trade-trace-jpana's
  catalog census (due 2026-07-23)
- `MCP_INCLUDE_EXPERIMENTAL=1` — surfaces the 5 adapter tools
  (market.refresh/search, snapshot.fetch/fetch_series, outcome.fetch),
  which are experimental-tier and invisible to a default catalog listing

## Risk policy v1 (owner-approved values)

Recorded once by `setup.sh` via `risk.policy_version_add`
(`paper_only=true`); exact `rules_json` pinned in the implementation plan
using the shipped `limit_class` taxonomy (`src/trade_trace/tools/risk.py`):

- Paper bankroll: **$10,000** notional
- Per-intent notional cap: **$200** (2%)
- Per-market exposure cap: **$400**
- Per-category exposure cap: **$1,500**
- Total exposure cap: **$6,000** (60%)
- Daily loss limit: **$500**; weekly: **$1,000**
- Max spread: **$0.05**; slippage cap: **100 bps**
- Time to resolution: **≤ 90 days** as a market-*selection* rule (the
  evaluator's `time_to_resolution` limit_class is a MIN-runway check, so
  the policy encodes a **≥ 6 h runway** hard block and the 90-day cap
  lives in the playbook's universe rule)
- Markets: binary only (market.bind constraint), no blocked categories in v1

Every intent is evaluated (`risk.evaluate` → `risk.check_record`) before
any fill. A **fail is journaled as an abstention** — never resized until
it passes. `missing_data` is a fail, not a soft pass (evaluator
semantics).

## Per-run playbook (phases)

1. **Orient** — `report.bootstrap`, `report.work_queue`; establish
   `RUN_ID` (`YYYY-MM-DD-NN`); idempotency keys `paper:<RUN_ID>:<purpose>`
   for every retryable write.
2. **Settle** — refresh markets with due/near-due forecasts; where
   resolution is unambiguous (`winningOutcome` present, or
   `outcomePrices` pinned to one side) record `resolution.add` honoring
   the auto-score gate (confidence ≥ 0.9 only when genuinely unambiguous;
   never fabricate — per `docs/ax-dogfood/intentional-design.md`).
   Resolved markets with open paper positions exit at settlement value:
   `decision.add(paper_exit)` + closing `paper_fill.record`.
3. **Mark & reconcile** — fresh `snapshot.fetch` for every open-position
   market; import mark-to-market `account_snapshot` + mirror
   `external_receipt`s (convention below); `reconciliation.record` →
   `report.reconciliation_mismatches`. Mismatches are investigated in-run
   and surfaced in the run summary; a recurring mismatch becomes a bead.
4. **Discover & forecast** — `market.search` across a rotating domain set
   (single-topic queries — Gamma search is conjunctive); bind 2–4 new
   binary markets resolving within the policy horizon; `snapshot.fetch`;
   `memory.recall` for priors; `forecast.add` with probability,
   confidence, rationale. Forecasts happen every run even when nothing is
   tradeable — they are the evidence backbone.
5. **Trade under policy** — only where forecast-vs-market edge clears the
   playbook threshold (v1: ≥ 5 percentage points vs the tradeable price —
   ask for buys, bid for sells — tunable only by playbook revision, never
   mid-run): `risk.evaluate` → `risk.check_record` → (pass)
   `pretrade_intent.record` → `paper_fill.record` per the fill
   convention. Failures are journaled abstentions.
6. **Review & retain** — `report.paper_exposure`,
   `report.current_exposure`, `report.calibration`, `report.coach`,
   `report.phase_gate_readiness` (structurally never `ready` — recorded
   as the longitudinal evidence snapshot); `memory.retain` durable
   lessons; write run summary to `~/.trade-trace-paper/reports/<RUN_ID>.md`.

## Conventions (`conventions.md`)

**Fill model (Gamma snapshot → `book_levels`).** Snapshots carry
bid/ask/mid/spread/volume but no depth. Construct a single-level
conservative book: buys fill at the **ask**, sells at the **bid**, only
if requested size passes a liquidity sanity check (v1: ≤ 5% of the
snapshot's 24h volume) and the policy's spread/slippage caps. Anything
else is honestly `fill_status=no_fill`. No mid-price fills, no invented
depth. The snapshot used is recorded (`snapshot_as_of`) and must satisfy
`max_snapshot_age_seconds`. **Settlement exits** (phase 2) are the one
exception: a resolved market fills the closing side at resolution value
(0 or 1) with no liquidity check — settlement is not a market order.

**Reconciliation ("external truth" in a paper world).** The external
side is **derived-from-venue-data**: `account_snapshot.import` carries
the mark-to-market portfolio valued at live Polymarket prices;
`external_receipt.import` mirrors each fill against its snapshot
evidence. This is not broker truth (the reports' caveat flags already
say exactly this) but it makes reconciliation a real drift-detector for
the internal ledger and produces `reconciliation_cleanliness` evidence
for the phase gate rather than skipping that leg.

**Idempotency.** Explicit keys `paper:<RUN_ID>:<purpose>` everywhere,
following the June loop's proven scheme; a re-fired run replays
idempotently instead of double-writing.

## Operations

- **Cron:** `0 */6 * * *` → `run.sh`, stdout/err appended to
  `~/.trade-trace-paper/logs/cron.log`.
- **run.sh:** hardens PATH for cron's bare env; non-blocking `flock` at
  `$TRADE_TRACE_HOME/.run.lock` (skip if a run is live); invokes
  `claude -p "$(cat playbook.md)" --model opus --mcp-config mcp.json
  --strict-mcp-config --dangerously-skip-permissions`; per-run log
  `logs/run-<date>.log`. No git commands anywhere.
- **Staged enablement:** first 2–3 passes fired manually via
  `run.sh --once` and reviewed before the crontab line is uncommented.
- **Pause protocol (June lesson):** pause this cron before running any
  long autonomous Workflow/drain job in this repo; the crontab entry
  carries a comment pointing at bd memory
  `drain-workflow-vs-ax-cron-collision`. Because the loop is git-free the
  blast radius is now only "two Claude processes at once," but the
  courtesy pause stays.
- **Failure handling:** a run that cannot proceed (adapter down, config
  missing, MCP server fails to boot) logs the failure, files a bead if
  actionable, and exits nonzero; the next scheduled run retries fresh.
  Single-writer lock contention is handled by the substrate (busy_timeout
  + dispatch retry).

## Testing / validation

- `setup.sh` idempotent re-run test (safe to run twice).
- One supervised end-to-end pass (manual `run.sh --once`) verifying every
  phase writes what it should: forecast rows, risk receipts, intents,
  fills, reconciliation records, reports readable.
- Contract sanity: the loop's tool sequence matches
  `tests/integration/test_phase2_paper_trading_loop.py`; the harness adds
  no new product code, so quality gates are unaffected — but any bead
  fixes it triggers follow the normal gate rules.

## Out of scope (future beads, filed with run evidence)

- Substrate hardening identified in review: snapshot-aware fill helper
  (derive `book_levels` server-side), enforced risk-check→fill linkage,
  AGENT_GUIDE Phase-2 chapter. These get beads once runs demonstrate the
  friction is real.
- Phase-3 thresholds remain owner-unset by design; this harness produces
  the evidence, not the decision.
