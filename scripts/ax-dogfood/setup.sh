#!/usr/bin/env bash
#
# One-time (idempotent) setup for the AX dogfood loop's isolated journal.
#
# Creates ~/.trade-trace-axloop, enables live Polymarket network access and the
# Gamma endpoint in THAT home only (never the owner's real ~/.trade-trace), and
# verifies the adapter is live. Safe to re-run.
#
# Overrides (env):
#   TRADE_TRACE_HOME    journal home              (default: $HOME/.trade-trace-axloop)
#   AX_GAMMA_BASE_URL   Polymarket Gamma base url (default: https://gamma-api.polymarket.com)
#
set -euo pipefail

export TRADE_TRACE_HOME="${TRADE_TRACE_HOME:-$HOME/.trade-trace-axloop}"
GAMMA_BASE_URL="${AX_GAMMA_BASE_URL:-https://gamma-api.polymarket.com}"

log() { printf '[ax-setup] %s\n' "$*"; }
die() { printf '[ax-setup] ERROR: %s\n' "$*" >&2; exit 1; }

command -v tt >/dev/null 2>&1 || die "tt CLI not found on PATH (need the editable install)."

log "Journal home: $TRADE_TRACE_HOME"
mkdir -p "$TRADE_TRACE_HOME/logs"

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
# polygon_rpc_url intentionally left unset: on-chain reads are not needed.

log "Verifying adapter state..."
tt journal status | python3 -c '
import sys, json
d = json.load(sys.stdin)["data"]
pm = d.get("adapter_state", {}).get("polymarket", {})
ep = pm.get("configured_endpoints", {})
ok = bool(d.get("outbound_network_active")) and bool(pm.get("enabled")) and bool(ep.get("gamma_base_url"))
print(f"  outbound_network_active={d.get(\"outbound_network_active\")}  "
      f"enabled={pm.get(\"enabled\")}  gamma_set={ep.get(\"gamma_base_url\")}")
sys.exit(0 if ok else 1)
' || die "adapter did not come up enabled — check config above."

log "Ready. Home '$TRADE_TRACE_HOME' is initialized with live Polymarket access."
log "Next: dry-run the loop with  /ax-dogfood  (interactive) or  scripts/ax-dogfood/run.sh  (headless)."
