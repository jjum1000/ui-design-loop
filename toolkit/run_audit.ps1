# UI audit autonomous runner.
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File <unity-project>\ui-audit\run_audit.ps1
# Each round starts a fresh Claude Code session (L0) in ui-audit/, so context never carries over.
# Stops when handoff\DONE exists, when two rounds in a row add nothing to handoff\log.md, or after MaxRuns.
param(
  [int]$MaxRuns = 40
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$log    = Join-Path $root "handoff\log.md"
$runlog = Join-Path $root "handoff\runs.log"
$done   = Join-Path $root "handoff\DONE"
$stall  = 0

function LineCount($p) { if (Test-Path $p) { (Get-Content $p).Count } else { 0 } }

for ($i = 1; $i -le $MaxRuns; $i++) {
  if (Test-Path $done) { Write-Host "DONE found. See reports\FINAL.md"; break }

  $before = LineCount $log
  "[$(Get-Date -Format s)] round $i start" | Add-Content $runlog

  claude -p "Read handoff/START.md and follow it exactly. Reply in the language handoff/START.md is written in." `
    --permission-mode acceptEdits `
    --permission-prompts none `
    --allowedTools "Read" "Glob" "Grep" "Agent" "Bash(python *)" "Bash(py *)" *>> $runlog

  $after = LineCount $log
  "[$(Get-Date -Format s)] round $i end (log lines $before -> $after)" | Add-Content $runlog

  if ($after -le $before) { $stall++ } else { $stall = 0 }
  if ($stall -ge 2) { Write-Host "Stopped: no progress in 2 rounds. Check handoff\runs.log"; break }
}

if (Test-Path $done) { Write-Host "Finished. Open reports\FINAL.md and catalog\index.html" }
