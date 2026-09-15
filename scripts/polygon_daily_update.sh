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

# Resolve the interpreter. Prefer the repo venv — the system `python3` may be too
# new for the pinned deps (e.g. pandas_ta). Fall back to whatever `python` is on PATH.
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PY="$REPO_ROOT/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
    PY="python"
else
    PY="python3"
fi

# Capture the main-repo branch now, before any submodule checkout, so the
# submodule-pointer push targets the right branch even under cron/detached HEAD.
MAIN_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$MAIN_BRANCH" == "HEAD" ]] && MAIN_BRANCH="main"

LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y-%m-%d)"
LOG="$LOG_DIR/polygon_daily_update_${STAMP}.log"

log() { echo "$@" | tee -a "$LOG"; }

log "=== polygon_daily_update ${STAMP} ==="

# 1. Run the updater. On --dry-run nothing is written, so the commit step no-ops.
"$PY" scripts/polygon_daily_update.py "$@" 2>&1 | tee -a "$LOG"

# 2. Commit + push the submodule if data/ changed.
cd "$REPO_ROOT/parquet_data"

# Submodules are often in detached HEAD — land on a real branch before committing,
# and remember which one so the push is explicit (not the ambiguous `HEAD`).
#
# Under CI the LOCAL branch does not exist at all (actions/checkout leaves every
# submodule detached with only remote-tracking refs), so a bare `git checkout master`
# fails, SUB_BRANCH stays empty, and the `${SUB_BRANCH:-master}` fallback then pushes
# a local ref that was never created — the commit is stranded on a detached HEAD and
# the run reports success. Create the branch from its remote-tracking ref when it is
# missing locally. `-B <b> origin/<b>` is a no-op move when HEAD already points there,
# so freshly written parquet files in the working tree are preserved either way.
SUB_BRANCH=""
for b in master main; do
    if git show-ref --verify --quiet "refs/heads/$b"; then
        git checkout "$b" && SUB_BRANCH="$b" && break
    elif git show-ref --verify --quiet "refs/remotes/origin/$b"; then
        git checkout -B "$b" "origin/$b" && SUB_BRANCH="$b" && break
    fi
done

if [[ -z "$SUB_BRANCH" ]]; then
    log "ERROR: could not resolve a branch in parquet_data (no local or origin master/main)."
    exit 1
fi

if [[ -n "$(git status --porcelain data/)" ]]; then
    COUNT="$(git status --porcelain data/ | wc -l | tr -d ' ')"
    git add data/
    git commit -m "chore: polygon daily update ${STAMP} (${COUNT} files)" | tee -a "$LOG"
    git push origin "$SUB_BRANCH" | tee -a "$LOG"

    cd "$REPO_ROOT"
    git add parquet_data
    git commit -m "chore(submodule): bump parquet_data — daily update ${STAMP}" | tee -a "$LOG"
    git push origin "$MAIN_BRANCH" | tee -a "$LOG"
    log "Pushed ${COUNT} updated parquet file(s) and bumped submodule pointer."
else
    log "No parquet changes — nothing to commit."
fi

log "=== done ${STAMP} ==="
