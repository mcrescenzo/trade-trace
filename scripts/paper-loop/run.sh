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
SETTINGS="$REPO_DIR/scripts/paper-loop/headless-settings.json"
[ -f "$PLAYBOOK" ] || { echo "[$(stamp)] ERROR: playbook not found at $PLAYBOOK" >>"$LOG_FILE"; exit 1; }
[ -f "$MCP_CONFIG" ] || { echo "[$(stamp)] ERROR: mcp config not found at $MCP_CONFIG" >>"$LOG_FILE"; exit 1; }
[ -f "$SETTINGS" ] || { echo "[$(stamp)] ERROR: headless settings not found at $SETTINGS" >>"$LOG_FILE"; exit 1; }
[ -f "$TRADE_TRACE_HOME/trade-trace.sqlite" ] || { echo "[$(stamp)] ERROR: journal home not initialized — run setup.sh first" >>"$LOG_FILE"; exit 1; }

if [ "$DRY_RUN" = "1" ]; then
  echo "would run: claude -p <playbook.md> --model $MODEL --mcp-config $MCP_CONFIG --strict-mcp-config --settings $SETTINGS (cwd=$REPO_DIR, home=$TRADE_TRACE_HOME)"
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
# Scoped permissions, not --dangerously-skip-permissions: the settings file
# allowlists exactly the trade-trace MCP surface, journal-home writes, and
# bd-create friction filing; git/gh/crontab/web are explicitly denied.
claude -p "$(cat "$PLAYBOOK")" \
  --model "$MODEL" \
  --mcp-config "$MCP_CONFIG" --strict-mcp-config \
  --settings "$SETTINGS" \
  >>"$LOG_FILE" 2>&1 200>&-
status=$?
set -e

echo "[$(stamp)] ===== paper-loop run end (exit=$status) =====" >>"$LOG_FILE"
exit "$status"
