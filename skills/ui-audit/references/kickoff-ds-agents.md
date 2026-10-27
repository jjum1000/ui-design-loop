# Kickoff: build the agent-facing design system (orchestrated, with human gates)

The catalog is HTML for humans. Agents need a short, greppable entry point: `Docs/ui-design-system/` with `INDEX.md` (reading order, rules, prohibitions, most-used templates, undecided standards), `templates.jsonl` (one template card per line), `screens.jsonl` (screen -> templates, `cleanReference`), `skeletons.md` (View/Popup skeleton recipes), `UPDATE.md` (refresh procedure) and `SKILL.md`. This kickoff builds that package and the human decisions that make it trustworthy.

Write a short plan document first (for example `ui-audit/design/<date>-design-system-for-agents.md`) with the decisions, facts, steps and acceptance criteria you agreed with the team; the session below treats it as the source of truth.

```
You are the orchestrator of a new session. There is no earlier conversation. Communicate in <your language>;
code, file names and commits in English. Work at the Unity project root; ui-audit commands run inside ui-audit/.

[Goal]
Complete the plan in ui-audit/design/<date>-design-system-for-agents.md (the source of truth). Order:
P0 index -> pilot on one screen -> P1 decision queue -> P1 role labels and color token names -> P2 refresh/share procedure.
Stop only at the human gates G1-G3 below; proceed on your own in between.

[Read first, in this order]
1. The plan document above - decisions, facts, plan, acceptance criteria. Do not re-ask decided points.
2. ui-audit/reports/FINAL.md - how decisions are recorded (record_decision.py), limits of the template and layout data.
3. python scripts/state.py render and git status --short | head, to see the current state. If a git pull brought new
   prefabs/scenes/scripts, regenerate data first (python scripts/ds_publish.py --plan prints what to run).

[Steps]
- P0: python scripts/ds_index.py --run (templates.jsonl, screens.jsonl, INDEX.md, UPDATE.md, SKILL.md),
  python scripts/ds_skeletons.py --run (skeletons.md), python scripts/ds_index.py --check.
  If the project has its own producer for a new-screen wiring checklist (screen enum, controller, view, Addressables...),
  run it as well; it is project-specific and not part of the toolkit.
- Pilot (read-only): take one existing, finished screen, rebuild its composition from the index alone
  (reference screen, skeleton recipe, template list) and compare with the real layout data. Record what the index was missing.
- P1 decision queue: for templates whose standard is undecided (look-alikes, baked copies), prepare candidates with renders,
  usage counts and screens, plus a recommendation.
- P1 labels: python scripts/ds_roles.py --draft, --review -> human approval -> --approve.
  python scripts/ds_colors.py --scan, --draft-names, --review -> human approval -> --approve.
- P2: python scripts/ds_publish.py --plan / --run-index works and UPDATE.md describes how your team refreshes and shares the package.

[How to work]
- Delegate each step to sub-agents (bulk file reading is delegated); you only verify outputs against acceptance criteria.
- After each step, append results, numbers and open problems to an "agent-facing design system" section of
  ui-audit/reports/FINAL.md, and update the plan's checkboxes.
- Every output must be reproducible by a script under ui-audit/scripts/ (no hand-written generated files).
  New scripts get a --selftest and are added to a0_setup.py's self-test list.
- Write code and docs with the Write tool (Bash heredocs collapse backslashes).
- No effort estimates in time. The axes are order, dependencies and acceptance criteria.
- Report only verified facts; mark estimates as estimates.

[Human gates - stop only here, and batch questions into one message]
- G1 (P1 decision queue): open the candidate page to the user. Record only what the user picked, with
  python scripts/record_decision.py --template <name|slug> 표준|폐기 [--to <slug>]|예외 --reason "..." --by user
  (표준 = standard, 폐기 = deprecated, 예외 = exception). Never decide for the user. Then rebuild the index
  (python scripts/ds_index.py --run) and, if node-level decisions were recorded, the catalog (state.py render tells you).
- G2 (Unity-side shared UI kit, if the plan has one): it changes how the team writes UI build tools, so team agreement
  comes first. Show the design (kit API, migration of existing helpers, whether the renderer package is committed) and write
  Unity code only after the user answers "agreed".
- G3 (commit/push): show the file list and message and get confirmation before committing Docs/ui-design-system/ or any Unity code.

[Forbidden / caution]
- Until G2 the Unity project is read-only. data/, decisions.json and manifest.json change only through their scripts.
- In a shared working tree: no stash, no discarding changes, no git add -A; add an allow-list of paths only.
  Do not commit test scenes or timelines.
- Unity batch mode and the editor GUI cannot use the project at the same time. Check with
  Get-CimInstance Win32_Process -Filter "Name='Unity.exe'" (tasklist misreports). Never -nographics.
- The pilot is read-only: do not edit that screen's prefabs or build tools.

[End]
When everything is done (or blocked at a gate), finish the FINAL.md section and a short handoff document for the team (G3 target),
then report the remaining gates and open problems to the user in one message.
```
