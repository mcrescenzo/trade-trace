# Paper-Loop Evidence Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scripts/paper-loop/` — a cron-driven headless-Claude harness that runs the full Phase-2 paper-trading chain against live Polymarket data every 6 hours, accumulating calibration and paper-P&L evidence in a dedicated journal home.

**Architecture:** Adapts the proven ax-dogfood wrapper pattern (flock, PATH hardening, headless `claude -p` with `--strict-mcp-config`) but with **zero git operations** and a playbook built around the Phase-2 chain proven by `tests/integration/test_phase2_paper_trading_loop.py`. All state lives in `~/.trade-trace-paper` (SQLite journal) — the repo gains only scripts and docs, no product code.

**Tech Stack:** bash, python3 (JSON plumbing only), `tt` CLI / `trade-trace-mcp` (editable install at `~/.local/bin`, points at this checkout), `claude` CLI, cron.

**Spec:** `docs/superpowers/specs/2026-07-10-paper-loop-evidence-harness-design.md` · **Bead:** trade-trace-jbn3m

## Global Constraints

- Journal home: `~/.trade-trace-paper` (`TRADE_TRACE_HOME`); never touch `~/.trade-trace` or `~/.trade-trace-axloop`.
- Actor id: `agent:paper-loop`. Env on every run: `TRADE_TRACE_DISPATCH_TRACE=1`, `MCP_INCLUDE_EXPERIMENTAL=1`.
- Risk policy v1 values (owner-approved, verbatim): bankroll $10,000; per-intent notional $200; per-market exposure $400; per-category $1,500; total $6,000; daily loss $500; weekly loss $1,000; max spread $0.05; slippage cap 100 bps; min resolution runway 21600 s; market selection ≤ 90 days to resolution; binary markets only; `paper_only=true`.
- Edge threshold: act only when |forecast probability − tradeable price| ≥ 0.05 (ask for buys, bid for sells). Tunable only by playbook revision.
- The loop NEVER: runs git commands, edits repo code, pushes anywhere, places real orders (no such code path exists), or resizes a risk-failed intent until it passes.
- CLI facts (verified): subcommand paths use underscores (`tt journal config_set`; hyphen form is rejected); flags use hyphens (`--idempotency-key`); admin tools need `--confirm`; `journal.config_set` needs `--confirm --allow-no-idempotency` (or an explicit key).
- Idempotency facts (verified): `pretrade_intent.record`, `paper_fill.record`, `account_snapshot.import`, `external_receipt.import`, and all 5 adapter fetch tools REQUIRE an explicit `idempotency_key`; `market.bind`, `snapshot.add`, `forecast.add`, `decision.add`, `resolution.add`, `risk.*`, `reconciliation.record` can auto-derive but the loop supplies explicit keys anyway (`paper:<RUN_ID>:<purpose>`).
- Commit after every task; conventional-commit messages referencing trade-trace-jbn3m.

---

### Task 1: Static assets — `mcp.json` + `conventions.md`

**Files:**
- Create: `scripts/paper-loop/mcp.json`
- Create: `scripts/paper-loop/conventions.md`

**Interfaces:**
- Produces: MCP config consumed by `run.sh` (Task 4); conventions doc referenced by `playbook.md` (Task 3).

- [ ] **Step 1: Write `scripts/paper-loop/mcp.json`**

```json
{
  "mcpServers": {
    "trade-trace": {
      "command": "/home/hermes/.local/bin/trade-trace-mcp",
      "args": [],
      "env": {
        "TRADE_TRACE_HOME": "${TRADE_TRACE_HOME}",
        "TRADE_TRACE_DISPATCH_TRACE": "1",
        "MCP_ACTOR_ID": "agent:paper-loop",
        "MCP_INCLUDE_EXPERIMENTAL": "1"
      }
    }
  }
}
```

(`${TRADE_TRACE_HOME}` env interpolation is the same mechanism the ax-dogfood config used; `MCP_INCLUDE_EXPERIMENTAL=1` is new — it makes the 5 adapter fetch tools visible in `list_tools`.)

- [ ] **Step 2: Write `scripts/paper-loop/conventions.md`**

````markdown
# Paper-Loop Conventions

Versioned decisions the playbook applies every run. Changing anything here
is a methodology change: bump the run-summary `conventions_version` and note
it in the next run summary.

`conventions_version: 1`

## Keys

- `RUN_ID` = `YYYY-MM-DD-NN` (UTC date + 2-digit sequence for the day).
- Every write: `idempotency_key = paper:<RUN_ID>:<purpose>[:<market_id>]`,
  e.g. `paper:2026-07-11-01:forecast:mkt_abc`.
- Evidence-family tools also take
  `semantic_key = paper:<RUN_ID>:<family>:<market_id>` (families: `intent`,
  `fill`, `account-snapshot`, `external-receipt`, `reconciliation`).
- `account_label = paper-loop`. `environment_label = paper`.

## Fill model (v1: conservative touch-price, honest no_fill)

Inputs: a fresh snapshot (bid/ask/mid/volume) for the market, side,
requested quantity, risk policy caps.

1. Tradeable price: **buy → ask**, **sell → bid**. Never mid.
2. Liquidity check: requested notional (quantity × price) must be
   ≤ 5% of the snapshot's 24h volume (USD). Fail → do NOT trade; if an
   intent was already recorded, record the fill attempt anyway and let it
   come back `fill_status=no_fill` — that is valid evidence.
3. `paper_fill.record` args: `book_levels=[{"price": <touch>, "quantity":
   <requested>}]`, `limit_price=<touch>`, `reference_mid_price=<mid>`,
   `slippage_cap_bps=100`, `snapshot_id` + `snapshot_as_of` from the
   snapshot actually used, `order_as_of=<now>`,
   `max_snapshot_age_seconds=900` (the snapshot must come from THIS run).
4. Never fabricate depth, never widen the level to force a fill. `partial`
   and `no_fill` results are recorded as-is.

## Settlement exits (the one exception)

When a market resolves while we hold a position: `decision.add(paper_exit)`
then `paper_fill.record` with a single book level at the resolution value
(winning side → price 1.0, losing side → 0.0), no liquidity check,
`evidence_json.reason = "settlement_exit"`. Settlement is not a market
order.

## Reconciliation ("external truth" = derived-from-venue-data)

Once per run, after fills and settlements:

1. `account_snapshot.import`: positions from `report.current_exposure`
   (each as decimal strings), balances derived as
   `available = bankroll_usd − Σ open cost basis + Σ realized proceeds − fees`
   (all from `report.paper_exposure`), `source_system =
   "paper-loop-derived"`, `source_run_id = <RUN_ID>`,
   `confidence_label = "high"`, `staleness_status = "fresh"`,
   `venue_label = "polymarket"`, marked-to-market at THIS run's snapshots.
2. `external_receipt.import` for each fill recorded this run:
   `lifecycle_state = "filled"` (or `"rejected"` for no_fill),
   `external_event_type = "fill"`, `pretrade_intent_id` linked,
   `sanitized_facts` mirroring the fill's quantities/price/fees as decimal
   strings.
3. `reconciliation.record` (semantic_key per above) →
   `report.reconciliation_mismatches`. Any non-empty mismatch_codes set is
   investigated in-run and explained in the run summary; a mismatch that
   recurs across 2+ runs becomes a bead.

This is NOT broker truth (the report caveat flags say exactly this); it is
a drift-detector for the local ledger and the source of
`reconciliation_cleanliness` evidence.

## Trading rule

- Universe: binary Polymarket markets, resolving in > 6 hours and
  ≤ 90 days, with enough 24h volume that a $200 intent passes the 5% check
  (i.e. ≥ $4,000 24h volume).
- Edge: trade only when |forecast p − tradeable price| ≥ 0.05.
- Size: notional = min($200, room under market/category/total exposure
  caps); quantity = notional / price.
- Every intent gets `risk.evaluate` → `risk.check_record` FIRST. A fail or
  missing_data verdict is recorded and journaled as an abstention
  (`decision.add` reason notes the abstention) — never resized to pass.
````

- [ ] **Step 3: Verify JSON parses**

Run: `python3 -m json.tool scripts/paper-loop/mcp.json`
Expected: pretty-printed JSON, exit 0.

- [ ] **Step 4: Commit**

```bash
git add scripts/paper-loop/mcp.json scripts/paper-loop/conventions.md
git commit -m "feat(paper-loop): mcp config and run conventions (trade-trace-jbn3m)"
```

---

### Task 2: Risk policy v1 + `setup.sh`

**Files:**
- Create: `scripts/paper-loop/risk-policy-v1.json`
- Create: `scripts/paper-loop/setup.sh`

**Interfaces:**
- Consumes: nothing from other tasks (standalone bootstrap).
- Produces: an initialized `~/.trade-trace-paper` with adapter config + policy version whose `policy_key="paper-loop"`, `version="1"` — the playbook (Task 3) looks the policy up by that key.

- [ ] **Step 1: Write `scripts/paper-loop/risk-policy-v1.json`**

All fields constant (including `effective_from`) so re-running setup replays idempotently instead of conflicting.

```json
{
  "policy_key": "paper-loop",
  "version": "1",
  "source": "owner_decision_2026-07-10",
  "effective_from": "2026-07-10T00:00:00.000Z",
  "limits_json": {
    "bankroll_usd": 10000,
    "per_intent_notional_usd": 200,
    "market_exposure_usd": 400,
    "category_exposure_usd": 1500,
    "total_exposure_usd": 6000,
    "daily_loss_usd": 500,
    "weekly_loss_usd": 1000,
    "max_spread": 0.05,
    "slippage_cap_bps": 100,
    "min_seconds_to_resolution": 21600,
    "selection_max_days_to_resolution": 90,
    "paper_only": true
  },
  "rules_json": [
    {"rule_id": "per_intent_notional", "limit_class": "notional", "severity": "hard_block", "threshold": 200},
    {"rule_id": "market_exposure", "limit_class": "market_exposure", "severity": "hard_block", "threshold": 400},
    {"rule_id": "category_exposure", "limit_class": "category_exposure", "severity": "hard_block", "threshold": 1500},
    {"rule_id": "total_exposure", "limit_class": "total_exposure", "severity": "hard_block", "threshold": 6000},
    {"rule_id": "daily_loss", "limit_class": "daily_loss", "severity": "hard_block", "threshold": 500},
    {"rule_id": "weekly_loss", "limit_class": "weekly_loss", "severity": "hard_block", "threshold": 1000},
    {"rule_id": "max_spread", "limit_class": "spread", "severity": "hard_block", "threshold": 0.05},
    {"rule_id": "slippage_bps", "limit_class": "slippage", "severity": "hard_block", "threshold": 100},
    {"rule_id": "min_resolution_runway_seconds", "limit_class": "time_to_resolution", "severity": "hard_block", "threshold": 21600},
    {"rule_id": "required_evidence_links", "limit_class": "required_links", "severity": "hard_block", "threshold": ["forecast_id", "snapshot_id", "decision_id"]},
    {"rule_id": "paper_only", "limit_class": "paper_only", "severity": "hard_block", "threshold": true}
  ]
}
```

(Every `limit_class` above is verified against `LIMIT_CLASSES` in `src/trade_trace/tools/risk.py:127`. `time_to_resolution` is a MIN-runway rule — `_eval_min`, "intent must have at least N units of runway" — hence 21600 s here and the ≤90-day cap as a selection rule in conventions.md instead. Units convention: the playbook passes `snapshots.market.time_to_resolution` in seconds and `slippage` in bps.)

- [ ] **Step 2: Write `scripts/paper-loop/setup.sh`**

```bash
#!/usr/bin/env bash
#
# One-time (idempotent) setup for the paper-loop evidence harness journal.
#
# Creates ~/.trade-trace-paper, enables live Polymarket Gamma access in THAT
# home only (never the owner's real ~/.trade-trace), and seeds risk policy v1
# from risk-policy-v1.json. Safe to re-run: config writes overwrite in place
# and the policy write replays idempotently (all-constant payload + fixed key).
#
# Overrides (env):
#   TRADE_TRACE_HOME       journal home              (default: $HOME/.trade-trace-paper)
#   PAPER_GAMMA_BASE_URL   Polymarket Gamma base url (default: https://gamma-api.polymarket.com)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export TRADE_TRACE_HOME="${TRADE_TRACE_HOME:-$HOME/.trade-trace-paper}"
GAMMA_BASE_URL="${PAPER_GAMMA_BASE_URL:-https://gamma-api.polymarket.com}"
POLICY_FILE="$SCRIPT_DIR/risk-policy-v1.json"

log() { printf '[paper-setup] %s\n' "$*"; }
die() { printf '[paper-setup] ERROR: %s\n' "$*" >&2; exit 1; }

command -v tt >/dev/null 2>&1 || die "tt CLI not found on PATH (need the editable install)."
[ -f "$POLICY_FILE" ] || die "policy file not found: $POLICY_FILE"

log "Journal home: $TRADE_TRACE_HOME"
mkdir -p "$TRADE_TRACE_HOME/logs" "$TRADE_TRACE_HOME/reports"

log "Initializing journal (no-op if already initialized)..."
tt journal init >/dev/null

# journal.config_set is a retryable admin write: it needs --confirm to persist
# (not preview) and an idempotency opt-out for these one-time config writes.
set_cfg() {
  local key="$1" value="$2"
  tt journal config_set --key "$key" --value "$value" \
    --confirm --allow-no-idempotency >/dev/null \
    || die "failed to set config $key"
  log "  set $key = $value"
}

log "Enabling Polymarket network + Gamma endpoint (this home only)..."
set_cfg network.polymarket.enabled true
set_cfg network.polymarket.gamma_base_url "$GAMMA_BASE_URL"
# polygon_rpc_url intentionally left unset: resolution uses Gamma-derived
# winningOutcome/outcomePrices + manual resolution.add (validated pattern).

log "Seeding risk policy v1 from $(basename "$POLICY_FILE")..."
field() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); v=d[sys.argv[2]]; print(v if isinstance(v,str) else json.dumps(v))' "$POLICY_FILE" "$1"; }

policy_out="$(tt risk policy_version_add \
  --policy-key "$(field policy_key)" \
  --version "$(field version)" \
  --source "$(field source)" \
  --effective-from "$(field effective_from)" \
  --limits-json "$(field limits_json)" \
  --rules-json "$(field rules_json)" \
  --idempotency-key "paper:setup:risk-policy-v1")" \
  || die "risk.policy_version_add failed"

printf '%s' "$policy_out" | python3 -c '
import json, sys
body = json.load(sys.stdin)
assert body["ok"] is True, body
replay = body.get("meta", {}).get("idempotent_replay", False)
print("  policy id={} (idempotent_replay={})".format(body["data"]["id"], replay))
' || die "unexpected policy_version_add envelope"

log "Verifying adapter state..."
tt journal status | python3 -c '
import sys, json
d = json.load(sys.stdin)["data"]
pm = d.get("adapter_state", {}).get("polymarket", {})
ep = pm.get("configured_endpoints", {})
net = d.get("outbound_network_active")
enabled = pm.get("enabled")
gamma = ep.get("gamma_base_url")
print("  outbound_network_active={}  enabled={}  gamma_set={}".format(net, enabled, gamma))
sys.exit(0 if (net and enabled and gamma) else 1)
' || die "adapter did not come up enabled — check config above."

log "Ready. Home '$TRADE_TRACE_HOME' is initialized with live Polymarket access and risk policy v1."
log "Next: one supervised pass via  scripts/paper-loop/run.sh  (see README)."
```

- [ ] **Step 3: Make executable and test against a scratch home**

```bash
chmod +x scripts/paper-loop/setup.sh
SCRATCH="$(mktemp -d)"   # or under your session scratchpad dir
TRADE_TRACE_HOME="$SCRATCH/home" bash scripts/paper-loop/setup.sh
```

Expected: `set network.polymarket.enabled = true`, `set network.polymarket.gamma_base_url = ...`, `policy id=... (idempotent_replay=False)`, `outbound_network_active=True enabled=True gamma_set=https://gamma-api.polymarket.com`, `Ready.` — exit 0.

- [ ] **Step 4: Test idempotent re-run against the same scratch home**

Run: `TRADE_TRACE_HOME="$SCRATCH/home" bash scripts/paper-loop/setup.sh`
Expected: exit 0 again, this time `policy id=<same id> (idempotent_replay=True)`. Then clean up: `rm -rf "$SCRATCH"`.

- [ ] **Step 5: Run for real**

Run: `bash scripts/paper-loop/setup.sh`
Expected: same success output; `~/.trade-trace-paper/trade-trace.sqlite` now exists. Verify: `TRADE_TRACE_HOME="$HOME/.trade-trace-paper" tt journal status | python3 -m json.tool | head -20` shows `"ok": true`.

- [ ] **Step 6: Commit**

```bash
git add scripts/paper-loop/risk-policy-v1.json scripts/paper-loop/setup.sh
git commit -m "feat(paper-loop): journal bootstrap + owner risk policy v1 (trade-trace-jbn3m)"
```

---

### Task 3: `playbook.md`

**Files:**
- Create: `scripts/paper-loop/playbook.md`

**Interfaces:**
- Consumes: conventions.md (Task 1), policy_key `paper-loop` (Task 2).
- Produces: the prompt text `run.sh` (Task 4) feeds to headless claude.

Design note: the playbook pins PROCEDURE, DISCIPLINE, and CONVENTIONS but tells the agent to introspect `tool.schema` for exact arg schemas at runtime — the June loop's playbook fossilized schemas and drifted. The reference for the full chain is named, not inlined.

- [ ] **Step 1: Write `scripts/paper-loop/playbook.md`**

````markdown
# Paper-Loop Evidence Run

You are the trading agent for one **evidence-accumulation pass** of the
Trade Trace paper-trading loop. You use Trade Trace as a live paper-trading
bot against real Polymarket data. Your output is journal evidence:
forecasts, risk receipts, intents, paper fills, reconciliations, reports.

**Read `scripts/paper-loop/conventions.md` first** — it defines RUN_ID,
key formats, the fill model, settlement exits, the reconciliation
procedure, and the trading rule. Follow it exactly.

## Hard rules

1. **Paper only.** No live-execution path exists in this system; do not
   attempt to create one or imply one exists.
2. **No git. No code edits. No pushes.** You are not a developer in this
   session. If substrate friction blocks the run, file a bead
   (`bd create` with label `paper-loop`) and continue or stop honestly.
3. **Risk discipline.** Every intent: `risk.evaluate` →
   `risk.check_record` BEFORE any fill, against policy_key `paper-loop`
   version `1`. A fail/missing_data verdict is journaled as an abstention.
   NEVER resize or re-shape an intent to sneak under a limit.
4. **Honesty.** Never fabricate resolution outcomes, confidences, prices,
   or depth. `no_fill` and abstentions are good evidence. If Gamma data is
   ambiguous, say so in the journal and move on.
5. **Tool surface.** Use the connected `trade-trace` MCP tools; if the MCP
   server is not connected, use the `tt` CLI with
   `TRADE_TRACE_HOME=$HOME/.trade-trace-paper` (identical contract; dots
   become spaces: `paper_fill.record` → `tt paper_fill record`). Introspect
   `tool.schema` (per tool: `tool.schema {"tool": "<name>"}`) whenever
   unsure of args — do not guess. Adapter tools (`market.search`,
   `market.refresh`, `snapshot.fetch`, `snapshot.fetch_series`,
   `outcome.fetch`) require an explicit `idempotency_key`; so do
   `pretrade_intent.record`, `paper_fill.record`,
   `account_snapshot.import`, `external_receipt.import`.

## Phases (do all six, in order)

### 1. Orient
`report.bootstrap`, then `report.work_queue`. Set RUN_ID
(`YYYY-MM-DD-NN`, UTC; NN = 1 + count of files in
`$TRADE_TRACE_HOME/reports/` matching today's date).

### 2. Settle
For every market with an open forecast or open paper position:
`market.refresh` + `snapshot.fetch` (fresh prices; explicit idempotency
keys). If the venue data shows resolution (`winningOutcome`, or
`outcomePrices` pinned ~1.0/~0.0 on one side): `resolution.add` with
`status=resolved_final` and `confidence>=0.9` ONLY if genuinely
unambiguous — otherwise record the honest status (`disputed`,
`ambiguous`, `resolved_provisional`) and skip auto-scoring. Then exit any
open position on a resolved market per the settlement-exit convention.

### 3. Mark & reconcile
Using this run's fresh snapshots: `report.current_exposure`,
`report.paper_exposure`; then `account_snapshot.import` (derived truth),
`external_receipt.import` per fill recorded this run (including
settlement exits), `reconciliation.record`, and
`report.reconciliation_mismatches`. Investigate any mismatch now and
explain it in the run summary.

### 4. Discover & forecast
`market.search` with 2–3 single-topic queries (rotate domains across
runs: politics, central banks, sports, crypto, entertainment, science —
check `memory.recall` for what recent runs covered). Select up to 4 new
binary markets meeting the universe rule (conventions.md): >6h and ≤90d
to resolution, 24h volume ≥ $4,000, unambiguous resolution rules. For
each: `market.bind` (source=polymarket), `snapshot.fetch`,
`memory.recall` for priors, then `forecast.add` (kind=binary, both
outcomes, probabilities summing to 1, `rationale_body` with your actual
reasoning, `snapshot_id` anchored). Forecast EVERY selected market even
if you will not trade it — forecasts are the evidence backbone.

### 5. Trade under policy
For each forecast where the edge rule passes (≥ 0.05 vs tradeable
price): size per conventions, `decision.add` (type=paper_enter, side,
quantity, price, declared_risk_amount/unit=USDC), `risk.evaluate`
(policy version above; supply `snapshots.market` from the fresh snapshot
— spread, time_to_resolution in seconds, slippage in bps — and
`snapshots.exposure` from report.current_exposure/paper_exposure) →
`risk.check_record` → if pass: `pretrade_intent.record` (link
forecast/decision/snapshot/receipt, proposed_shape, risk_budget) →
`paper_fill.record` per the fill convention. If the edge rule fails
everywhere, trade nothing — say so.

### 6. Review & retain
`report.calibration`, `report.coach`, `report.paper_exposure`,
`report.phase_gate_readiness` (record its snapshot; it will say
owner_thresholds_unset — that is correct and expected). `memory.retain`
at most 1–3 durable lessons (market-level insights, not run trivia).
Write the run summary to `$TRADE_TRACE_HOME/reports/<RUN_ID>.md`:
markets touched, forecasts made (with probabilities), trades/abstentions
(with risk verdicts), settlements, reconciliation result, calibration
numbers, `conventions_version`, and anything anomalous.

## Failure handling
If the adapter is disabled/misconfigured (`ADAPTER_DISABLED`,
`CONFIG_REQUIRED`) or the journal is missing, STOP: write what happened
to the run summary (create the reports dir if needed), file a bead if
actionable, and exit — do not improvise around a fail-closed boundary.
````

- [ ] **Step 2: Verify the playbook's tool names against the live registry**

```bash
TRADE_TRACE_HOME="$HOME/.trade-trace-paper" python3 - <<'EOF'
from trade_trace.core import build_registry
reg = build_registry()
names = set(reg.by_name)
used = ["report.bootstrap","report.work_queue","market.refresh","snapshot.fetch",
        "resolution.add","report.current_exposure","report.paper_exposure",
        "account_snapshot.import","external_receipt.import","reconciliation.record",
        "report.reconciliation_mismatches","market.search","market.bind",
        "memory.recall","forecast.add","decision.add","risk.evaluate",
        "risk.check_record","pretrade_intent.record","paper_fill.record",
        "report.calibration","report.coach","report.phase_gate_readiness",
        "memory.retain","tool.schema"]
missing = [t for t in used if t not in names]
print("missing:", missing)
assert not missing
EOF
```

Expected: `missing: []`, exit 0.

- [ ] **Step 3: Commit**

```bash
git add scripts/paper-loop/playbook.md
git commit -m "feat(paper-loop): per-run playbook for the Phase-2 evidence pass (trade-trace-jbn3m)"
```

---

### Task 4: `run.sh`

**Files:**
- Create: `scripts/paper-loop/run.sh`

**Interfaces:**
- Consumes: `mcp.json` (Task 1), `playbook.md` (Task 3), initialized home (Task 2).
- Produces: the cron entrypoint; `--dry-run` mode for tests.

- [ ] **Step 1: Write `scripts/paper-loop/run.sh`**

```bash
#!/usr/bin/env bash
#
# Cron wrapper for one paper-loop evidence run. Fires a single headless Opus
# session that executes scripts/paper-loop/playbook.md against the dedicated
# journal home, with the trade-trace MCP server connected. Safe to schedule on
# any cadence: a non-blocking lock prevents overlapping firings.
#
# Unlike the retired ax-dogfood wrapper this runs ZERO git commands: the loop
# writes journal evidence only. See docs/superpowers/specs/
# 2026-07-10-paper-loop-evidence-harness-design.md.
#
# Usage: run.sh [--dry-run]
#   --dry-run   print the claude command instead of executing it
#
# Overrides (env):
#   TRADE_TRACE_HOME   journal home   (default: $HOME/.trade-trace-paper)
#   PAPER_REPO_DIR     repo checkout  (default: /home/hermes/code/trade-trace)
#   PAPER_MODEL        model          (default: opus)
#
set -euo pipefail

export TRADE_TRACE_HOME="${TRADE_TRACE_HOME:-$HOME/.trade-trace-paper}"
export TRADE_TRACE_DISPATCH_TRACE=1
export MCP_ACTOR_ID="agent:paper-loop"
REPO_DIR="${PAPER_REPO_DIR:-/home/hermes/code/trade-trace}"
MODEL="${PAPER_MODEL:-opus}"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

# Cron runs with a bare environment; make sure the user bin dir (claude, tt,
# python3, flock, bd) is on PATH regardless of how this is invoked.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

LOG_DIR="$TRADE_TRACE_HOME/logs"
LOCKFILE="$TRADE_TRACE_HOME/.run.lock"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run-$(date -u +%F).log"

stamp() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }

command -v claude >/dev/null 2>&1 || { echo "[$(stamp)] ERROR: claude CLI not found" >>"$LOG_FILE"; exit 1; }

PLAYBOOK="$REPO_DIR/scripts/paper-loop/playbook.md"
MCP_CONFIG="$REPO_DIR/scripts/paper-loop/mcp.json"
[ -f "$PLAYBOOK" ] || { echo "[$(stamp)] ERROR: playbook not found at $PLAYBOOK" >>"$LOG_FILE"; exit 1; }
[ -f "$MCP_CONFIG" ] || { echo "[$(stamp)] ERROR: mcp config not found at $MCP_CONFIG" >>"$LOG_FILE"; exit 1; }
[ -f "$TRADE_TRACE_HOME/trade-trace.sqlite" ] || { echo "[$(stamp)] ERROR: journal home not initialized — run setup.sh first" >>"$LOG_FILE"; exit 1; }

if [ "$DRY_RUN" = "1" ]; then
  echo "would run: claude -p <playbook.md> --model $MODEL --mcp-config $MCP_CONFIG --strict-mcp-config --dangerously-skip-permissions (cwd=$REPO_DIR, home=$TRADE_TRACE_HOME)"
  exit 0
fi

# Non-blocking lock: if a previous firing is still running, log and exit 0.
exec 200>"$LOCKFILE"
if ! flock -n 200; then
  echo "[$(stamp)] another paper-loop run holds the lock; skipping this firing" >>"$LOG_FILE"
  exit 0
fi

# cwd = repo so `bd` (friction beads) resolves; the loop itself never runs git.
cd "$REPO_DIR"

{
  echo "[$(stamp)] ===== paper-loop run start (home=$TRADE_TRACE_HOME model=$MODEL) ====="
} >>"$LOG_FILE"

set +e
claude -p "$(cat "$PLAYBOOK")" \
  --model "$MODEL" \
  --mcp-config "$MCP_CONFIG" --strict-mcp-config \
  --dangerously-skip-permissions \
  >>"$LOG_FILE" 2>&1
status=$?
set -e

echo "[$(stamp)] ===== paper-loop run end (exit=$status) =====" >>"$LOG_FILE"
exit "$status"
```

- [ ] **Step 2: Make executable, test dry-run and preconditions**

```bash
chmod +x scripts/paper-loop/run.sh
bash scripts/paper-loop/run.sh --dry-run
```
Expected: one `would run: claude -p ...` line, exit 0.

```bash
TRADE_TRACE_HOME=/nonexistent bash scripts/paper-loop/run.sh --dry-run; echo "exit=$?"
```
Expected: `exit=1` (mkdir fails or journal-missing guard trips before any claude invocation; error line in log only if the log dir was creatable — the guard must fire either way).

- [ ] **Step 3: Test the lock**

```bash
(
  exec 200>"$HOME/.trade-trace-paper/.run.lock"
  flock -n 200 || { echo "ABORT: could not take lock for the test"; exit 1; }
  bash scripts/paper-loop/run.sh --dry-run  # dry-run exits before locking: prints
  bash scripts/paper-loop/run.sh || true    # real path: must skip via our held lock
) ; tail -1 "$HOME/.trade-trace-paper/logs/run-$(date -u +%F).log"
```
Expected: last log line contains `another paper-loop run holds the lock; skipping this firing` and the inner real invocation exited 0 without launching claude. (The explicit abort guard matters: if the outer `flock` ever failed silently, the second invocation would launch a REAL headless run.)

- [ ] **Step 4: Commit**

```bash
git add scripts/paper-loop/run.sh
git commit -m "feat(paper-loop): git-free cron wrapper for headless evidence runs (trade-trace-jbn3m)"
```

---

### Task 5: `README.md`, local slash command, commented cron entry

**Files:**
- Create: `scripts/paper-loop/README.md`
- Create: `.claude/commands/paper-trade.md` (gitignored — local only, like the ax-dogfood command)
- Modify: user crontab (append a COMMENTED entry; nothing fires yet)

**Interfaces:**
- Consumes: everything above.
- Produces: operator documentation; `/paper-trade` for interactive passes; the exact cron line for later enablement.

- [ ] **Step 1: Write `scripts/paper-loop/README.md`**

````markdown
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

- Supervised single pass: `bash scripts/paper-loop/run.sh`
  (watch: `tail -f ~/.trade-trace-paper/logs/run-$(date -u +%F).log`)
- Interactive pass: `/paper-trade` in a Claude Code session in this repo.
- Sanity check without running: `bash scripts/paper-loop/run.sh --dry-run`

## Enabling the cron (after 2–3 clean supervised passes)

Uncomment the paper-loop line in `crontab -e`. The prepared entry:

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
````

- [ ] **Step 2: Write `.claude/commands/paper-trade.md`** (local file; `.claude/` is gitignored — do NOT `git add -f` it)

```markdown
---
description: One paper-loop evidence pass — drive the full Phase-2 paper-trading chain against live Polymarket data.
model: opus
---

Execute one paper-loop evidence run. Read `scripts/paper-loop/playbook.md`
(the version-controlled source of truth) and follow it exactly, end to end.
Do not summarize it back to me first — carry out the run. If the
trade-trace MCP server is not connected in this session, use the `tt` CLI
with `TRADE_TRACE_HOME=$HOME/.trade-trace-paper` as the playbook directs.
```

- [ ] **Step 3: Append the COMMENTED cron entry (non-destructive)**

```bash
crontab -l > "$HOME/.trade-trace-paper/logs/crontab.bak.$(date -u +%Y%m%dT%H%M%SZ)"
{ crontab -l 2>/dev/null; cat <<'EOF'

# Paper-loop evidence harness — headless Opus run every 6 hours.
# Managed: scripts/paper-loop/run.sh (self-hardens PATH; git-free). Logs:
#   ~/.trade-trace-paper/logs/run-<date>.log  (per-run, detailed)
#   ~/.trade-trace-paper/logs/cron.log        (wrapper-level / pre-claude errors)
# DISABLED until supervised validation passes (see scripts/paper-loop/README.md).
#0 */6 * * * bash -lc '/home/hermes/code/trade-trace/scripts/paper-loop/run.sh' >> /home/hermes/.trade-trace-paper/logs/cron.log 2>&1
EOF
} | crontab -
crontab -l | tail -8
```
Expected: the new commented block appears at the end; the existing (paused) ax-dogfood block is untouched; backup written to the scratchpad.

- [ ] **Step 4: Commit**

```bash
git add scripts/paper-loop/README.md
git commit -m "docs(paper-loop): operator README with staged cron enablement (trade-trace-jbn3m)"
```

---

### Task 6: Supervised validation pass + close-out

**Files:**
- No repo changes expected (evidence lands in `~/.trade-trace-paper`); bead update only.

**Interfaces:**
- Consumes: the complete harness (Tasks 1–5).
- Produces: validation evidence recorded on trade-trace-jbn3m; go/no-go basis for cron enablement (enablement itself stays an owner action).

- [ ] **Step 1: Fire one real supervised pass**

Run: `bash scripts/paper-loop/run.sh` (this launches a live headless Opus session against real Polymarket data; takes several minutes).
Expected: exit 0; `~/.trade-trace-paper/logs/run-$(date -u +%F).log` shows `run start` … `run end (exit=0)`.

- [ ] **Step 2: Verify the evidence trail**

```bash
export TRADE_TRACE_HOME="$HOME/.trade-trace-paper"
ls ~/.trade-trace-paper/reports/                       # expect one <RUN_ID>.md
tt report calibration | python3 -c 'import json,sys; b=json.load(sys.stdin); print("ok:", b["ok"])'
tt report paper_exposure | python3 -c 'import json,sys; b=json.load(sys.stdin); print("ok:", b["ok"])'
tt report current_exposure | python3 -c 'import json,sys; b=json.load(sys.stdin); d=b["data"]; print("ok:", b["ok"], "open_positions:", d["summary"]["open_position_count"])'
tt report reconciliation_mismatches | python3 -c 'import json,sys; b=json.load(sys.stdin); print("ok:", b["ok"], "codes:", b["data"]["summary"]["mismatch_codes"])'
```
Expected: every `ok: True`. Judge the run by the summary file: forecasts recorded with real rationale, every fill preceded by a pass receipt, reconciliation recorded. **Zero trades is a PASS if the summary shows the edge rule or risk policy honestly said no.** Failure = a phase skipped, a fabricated resolution/fill, or an uninvestigated mismatch.

- [ ] **Step 3: Read the run summary + log; file friction beads if warranted**

Read `~/.trade-trace-paper/reports/<RUN_ID>.md` and the day's log end to end. Anything the agent flagged as blocking → `bd create` (label `paper-loop`). Playbook ambiguity (agent misread a phase) → fix `playbook.md`/`conventions.md` now, commit as `fix(paper-loop): ...`, and note that a second supervised pass is needed before enablement.

- [ ] **Step 4: Record validation on the bead**

```bash
bd update trade-trace-jbn3m --notes "Supervised pass 1 complete: <RUN_ID>, <n> forecasts, <n> intents (<n> filled, <n> abstained), reconciliation codes=<...>. Cron entry staged (commented). Enablement = owner action after 2-3 clean passes per README."
```

- [ ] **Step 5: Quality gates + final commit if anything changed**

Run: `ruff check src tests && mypy src && pytest -q` — expected all clean (harness adds no product code; this confirms nothing regressed). Commit any Task-6 doc/playbook fixes; leave the bead open until the owner enables the cron, or close it if the owner considers staged-enablement the deliverable.
