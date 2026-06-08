#!/usr/bin/env bash
#
# polygon_daily_update.sh — daily cron wrapper for Issue #191.
#
# 1. Runs scripts/polygon_daily_update.py (writes new bars into parquet_data/data/).
# 2. If the submodule changed, commits + pushes it, then bumps the submodule
#    pointer in the main repo and pushes that too.
#
# Any args are passed through to the Python updater, e.g.:
#     scripts/polygon_daily_update.sh --start 2026-04-23
#     scripts/polygon_daily_update.sh --dry-run
#
# Suggested cron (07:00 local, after the prior US session has settled):
#     0 7 * * 1-5  /path/to/july-backtester/scripts/polygon_daily_update.sh >> /path/to/cron.log 2>&1
#
# Requires: POLYGON_API_KEY in env or .env, git-lfs initialised in the submodule.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y-%m-%d)"
LOG="$LOG_DIR/polygon_daily_update_${STAMP}.log"

log() { echo "$@" | tee -a "$LOG"; }

log "=== polygon_daily_update ${STAMP} ==="

# 1. Run the updater. On --dry-run nothing is written, so the commit step no-ops.
python scripts/polygon_daily_update.py "$@" 2>&1 | tee -a "$LOG"

# 2. Commit + push the submodule if data/ changed.
cd "$REPO_ROOT/parquet_data"

# Submodules are often in detached HEAD — land on a real branch before committing.
git checkout master 2>/dev/null || git checkout main 2>/dev/null || true

if [[ -n "$(git status --porcelain data/)" ]]; then
    COUNT="$(git status --porcelain data/ | wc -l | tr -d ' ')"
    git add data/
    git commit -m "chore: polygon daily update ${STAMP} (${COUNT} files)" | tee -a "$LOG"
    git push origin HEAD | tee -a "$LOG"

    cd "$REPO_ROOT"
    git add parquet_data
    git commit -m "chore(submodule): bump parquet_data — daily update ${STAMP}" | tee -a "$LOG"
    git push origin HEAD | tee -a "$LOG"
    log "Pushed ${COUNT} updated parquet file(s) and bumped submodule pointer."
else
    log "No parquet changes — nothing to commit."
fi

log "=== done ${STAMP} ==="
