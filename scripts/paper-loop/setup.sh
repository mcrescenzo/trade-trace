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
