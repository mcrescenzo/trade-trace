#!/usr/bin/env bash
#
# Cron wrapper for one AX dogfood run. Fires a single headless Opus session that
# executes the /ax-dogfood playbook against the isolated journal home, with the
# trade-trace MCP server connected. Safe to schedule on any cadence: a non-
# blocking lock prevents overlapping firings.
#
# Contained by design: isolated home, dedicated ax-dogfood branch, never-push-
# main rule + contract firewall live in the playbook. See
# docs/ax-dogfood/2026-06-03-ax-dogfood-loop-design.md.
#
# Overrides (env):
#   TRADE_TRACE_HOME   journal home   (default: $HOME/.trade-trace-axloop)
#   AX_REPO_DIR        repo checkout  (default: /home/hermes/code/trade-trace)
#   AX_MODEL           model          (default: opus)
#
set -euo pipefail

export TRADE_TRACE_HOME="${TRADE_TRACE_HOME:-$HOME/.trade-trace-axloop}"
export MCP_ACTOR_ID="agent:ax-dogfood"
REPO_DIR="${AX_REPO_DIR:-/home/hermes/code/trade-trace}"
MODEL="${AX_MODEL:-opus}"
AX_BRANCH="ax-dogfood"

# Cron runs with a bare environment; make sure the user bin dir (claude, tt,
# git, gh, python3, flock) is on PATH regardless of how this is invoked.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

LOG_DIR="$TRADE_TRACE_HOME/logs"
LOCKFILE="$TRADE_TRACE_HOME/.run.lock"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run-$(date -u +%F).log"

stamp() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }

command -v claude >/dev/null 2>&1 || { echo "[$(stamp)] ERROR: claude CLI not found" >>"$LOG_FILE"; exit 1; }

# Non-blocking lock: if a previous firing is still running, log and exit 0.
exec 200>"$LOCKFILE"
if ! flock -n 200; then
  echo "[$(stamp)] another ax-dogfood run holds the lock; skipping this firing" >>"$LOG_FILE"
  exit 0
fi

cd "$REPO_DIR"

# Defensive: never operate on the wrong branch. The playbook checks this too,
# but harden the wrapper in case the checkout was left elsewhere. A dirty tree
# makes checkout fail -> we stop rather than run against an unexpected state.
git checkout "$AX_BRANCH" >>"$LOG_FILE" 2>&1 || {
  echo "[$(stamp)] ERROR: could not checkout $AX_BRANCH (dirty tree or wrong repo?); skipping run" >>"$LOG_FILE"
  exit 1
}

PLAYBOOK="$REPO_DIR/scripts/ax-dogfood/playbook.md"
[ -f "$PLAYBOOK" ] || { echo "[$(stamp)] ERROR: playbook not found at $PLAYBOOK" >>"$LOG_FILE"; exit 1; }

{
  echo "[$(stamp)] ===== ax-dogfood run start (home=$TRADE_TRACE_HOME model=$MODEL) ====="
} >>"$LOG_FILE"

# Feed the version-controlled playbook directly (the .claude/ slash command is
# gitignored, so we do not depend on it for headless runs).
set +e
claude -p "$(cat "$PLAYBOOK")" \
  --model "$MODEL" \
  --mcp-config scripts/ax-dogfood/mcp.json --strict-mcp-config \
  --dangerously-skip-permissions \
  >>"$LOG_FILE" 2>&1
status=$?
set -e

echo "[$(stamp)] ===== ax-dogfood run end (exit=$status) =====" >>"$LOG_FILE"
exit "$status"
