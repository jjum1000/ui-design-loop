#!/usr/bin/env bash
# UI audit autonomous runner (bash twin of run_audit.ps1).
# Run:  bash <unity-project>/ui-audit/run_audit.sh [max-runs]
# Each round starts a fresh Claude Code session (L0) in ui-audit/, so context never carries over.
# Stops when handoff/DONE exists, when two rounds in a row add nothing to handoff/log.md, or after max-runs.
set -u
max_runs=${1:-40}
root=$(cd "$(dirname "$0")" && pwd)
cd "$root"
log=handoff/log.md
runlog=handoff/runs.log
done_flag=handoff/DONE
stall=0
mkdir -p handoff
count() { [ -f "$1" ] && wc -l < "$1" || echo 0; }

for ((i = 1; i <= max_runs; i++)); do
  if [ -f "$done_flag" ]; then echo "DONE found. See reports/FINAL.md"; break; fi
  before=$(count "$log")
  echo "[$(date +%FT%T)] round $i start" >> "$runlog"
  claude -p "Read handoff/START.md and follow it exactly. Reply in the language handoff/START.md is written in." \
    --permission-mode acceptEdits \
    --allowedTools "Read" "Glob" "Grep" "Agent" "Bash(python *)" "Bash(py *)" >> "$runlog" 2>&1
  after=$(count "$log")
  echo "[$(date +%FT%T)] round $i end (log lines $before -> $after)" >> "$runlog"
  if [ "$after" -le "$before" ]; then stall=$((stall + 1)); else stall=0; fi
  if [ "$stall" -ge 2 ]; then echo "Stopped: no progress in 2 rounds. Check handoff/runs.log"; break; fi
done

if [ -f "$done_flag" ]; then echo "Finished. Open reports/FINAL.md and catalog/index.html"; fi
