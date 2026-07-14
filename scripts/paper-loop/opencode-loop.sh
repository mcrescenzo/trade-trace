#!/usr/bin/env bash
#
# Hourly paper-cycle driver for opencode (the Claude Code equivalent is
# `/loop 1h /paper-cycle` inside a session). Each iteration launches ONE
# non-interactive opencode run that executes one full cycle via the
# harness-shared paper-cycle skill, then sleeps.
#
# Foreground process: run it in a terminal/tmux you can watch or kill.
# A non-blocking flock prevents overlap with a still-running cycle (and
# with the retired run.sh path, which shares the same lockfile).
#
# Overrides (env):
#   TRADE_TRACE_HOME     journal home    (default: $HOME/.trade-trace-paper)
#   PAPER_REPO_DIR       repo checkout   (default: /home/hermes/code/trade-trace)
#   PAPER_CYCLE_SLEEP    seconds between cycles (default: 3600)
#   PAPER_CYCLE_ONCE     set to 1 for a single cycle, no loop
#
set -euo pipefail

export TRADE_TRACE_HOME="${TRADE_TRACE_HOME:-$HOME/.trade-trace-paper}"
REPO_DIR="${PAPER_REPO_DIR:-/home/hermes/code/trade-trace}"
SLEEP_SECS="${PAPER_CYCLE_SLEEP:-3600}"
LOCKFILE="$TRADE_TRACE_HOME/.run.lock"
LOG_DIR="$TRADE_TRACE_HOME/logs"
mkdir -p "$LOG_DIR"

stamp() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
command -v opencode >/dev/null 2>&1 || { echo "opencode CLI not found" >&2; exit 1; }
[ -f "$TRADE_TRACE_HOME/trade-trace.sqlite" ] || { echo "journal home not initialized — run scripts/paper-loop/setup.sh first" >&2; exit 1; }

cd "$REPO_DIR"

run_one_cycle() {
  local log_file="$LOG_DIR/opencode-cycle-$(date -u +%F).log"
  (
    exec 200>"$LOCKFILE"
    if ! flock -n 200; then
      echo "[$(stamp)] another cycle holds the lock; skipping" | tee -a "$log_file"
      exit 0
    fi
    echo "[$(stamp)] ===== opencode paper-cycle start =====" >>"$log_file"
    set +e
    opencode run "Read /home/hermes/code/trade-trace/.claude/skills/paper-cycle/SKILL.md (the harness-shared paper-cycle procedure) and execute exactly ONE full cycle per it, using the opencode column of its Harness mechanics table. This is a non-interactive run: on any owner-decision blocker, record it as a ledger BLOCKER and end the cycle cleanly instead of asking." \
      >>"$log_file" 2>&1
    local status=$?
    set -e
    echo "[$(stamp)] ===== opencode paper-cycle end (exit=$status) =====" >>"$log_file"
    exit "$status"
  )
}

if [ "${PAPER_CYCLE_ONCE:-0}" = "1" ]; then
  run_one_cycle
  exit $?
fi

echo "[$(stamp)] opencode paper-cycle loop started (interval ${SLEEP_SECS}s); Ctrl-C to stop"
while true; do
  run_one_cycle || echo "[$(stamp)] cycle exited nonzero (see logs); continuing"
  sleep "$SLEEP_SECS"
done
