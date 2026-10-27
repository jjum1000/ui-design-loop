# Kickoff: check autonomous mode before the first unattended run

Autonomous mode is the default in the toolkit: gate agents decide H1-H3 with the rules in `agents/H1.md`-`H3.md` (recorded as `by: agent` with a reason), twice-failed steps are reset once and then skipped into `reports/blockers.md`, and the final step F writes `reports/FINAL.md` and `handoff/DONE`. `run_audit.ps1` starts a fresh `claude -p` session per round.

Paste the message below into a new session at the Unity project root after A0 is done. It only checks; it does not run the audit.

```
You are preparing the ui-audit workspace for an unattended run. The human only looks at the final result.
Do not analyse anything and do not work on H1. Check and report only.

[Read]
Only these parts of ui-audit/ROADMAP.md:
- "자율 실행 모드 (기본값)" (autonomous mode, default)
- "세션 관리" (session management): the "L0 시작 메시지" (L0 start message) code block
- "에이전트 정의" (agent definitions): the H1, H2, H3 and F code blocks

[Check]
1. ui-audit/agents/ has H1.md, H2.md, H3.md and F.md, and ui-audit/handoff/START.md starts with the
   "work folder is ui-audit/" line. If not, run python scripts/a0_setup.py --docs-only inside ui-audit/.
2. python scripts/state.py render (inside ui-audit/) shows the gates as delegated to gate agents, and the next action is H1.
3. python scripts/a0_setup.py --check passes.
4. Run claude -v. If this Claude Code version does not support the --permission-prompts flag used in
   ui-audit/run_audit.ps1, tell me (I will remove that line myself); do not edit the file.
5. Read ui-audit/run_audit.ps1 and summarise what it allows (permission mode, allowed tools, stop conditions). Do not run it.

[Rules]
- Follow the project's CLAUDE.md/AGENTS.md. Change nothing that was not asked.
- Everything outside ui-audit/ is read-only.

[Report, 10 lines or fewer]
What you checked, self-test results, Claude Code version, and the one line the human runs from the project root:
powershell -ExecutionPolicy Bypass -File ui-audit/run_audit.ps1
```

Notes for the human:
- `run_audit.ps1` uses `--permission-mode acceptEdits` and an allow-list (`Read`, `Glob`, `Grep`, `Agent`, `Bash(python *)`, `Bash(py *)`); edits are only auto-accepted inside the session's working folder (`ui-audit/`).
- Watch `ui-audit/handoff/runs.log`. Stop conditions: `handoff/DONE` exists, two rounds without new lines in `handoff/log.md`, or `-MaxRuns` (default 40).
- The runner's prompt asks the sessions to reply in Korean (v0.1 default); edit your installed copy if you prefer another language.
