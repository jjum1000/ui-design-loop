# Kickoff: A0 preparation (once per project)

Paste the message below into a **new** Claude Code session started at the Unity project root, after installing the toolkit into `ui-audit/`. Fill in every `<placeholder>` first; check the facts yourself (Unity version, UI system, prefab root and counts) so the agent does not have to guess.

```
You are responsible for the A0 preparation step of the UI audit of this Unity project.
Follow ui-audit/ROADMAP.md, section "에이전트 정의 > A0 준비" (agent definitions > A0 preparation), exactly.
Only A0 may read planning documents; every later session works from the files under ui-audit/ alone.

[Project facts - already verified]
- Project root: <path to the Unity project> (Unity <version>, <render pipeline>)
- UI system: uGUI (com.unity.ugui <version>) + TextMeshPro. Not UI Toolkit.
- Reference resolution: <width>x<height>. Platforms: <e.g. mobile + Steam>
- UI prefab root: <Assets/... UI folder> (<N> prefabs)
  Subfolders: <folder> <count>, <folder> <count>, ...
- Naming conventions document: <path, or "none">
- Workspace: <project root>/ui-audit (already in .gitignore: <yes/no>)

[Rules]
1. Follow the project's CLAUDE.md/AGENTS.md. If something is uncertain, ask instead of guessing.
2. Everything outside ui-audit/ is read-only. Do not create or modify files in Assets/, ProjectSettings/, .gitignore or any other project file.
   (ui-audit/ is outside Assets/, so Unity does not import it.)
3. First run python --version and confirm Python 3.10 or newer. If not, stop and tell me.
4. Write ui-audit/project.json from the facts above. unity_root is ".." (relative to ui-audit/), ui_root is "<Assets/... UI folder>".
   Key reference: docs/project-json.md of the ui-design-loop repository.
5. Write ui-audit/spec/batch-plan.json with the batch order mapped to real folders, as candidates only:
   b1 lobby, top bar, common popups -> <folders>
   b2 <feature screens>               -> <folders>
   b3 <feature screens>               -> <folders> (if a folder for <feature> was not found, leave an H1 question)
   b4 the rest                         -> all other folders
   If you do not know which prefab is the top bar, leave it as an H1 question.
6. Confirm parse_prefab.py works on 3 real UI prefabs from different folders (nodes come out).

[Run, inside ui-audit/]
python scripts/a0_setup.py
python scripts/a0_setup.py --check
python scripts/state.py render

[Done when]
- every script self-test passes (a0_setup.py --check)
- the next action in python scripts/state.py render is "H1 배치 범위 확인" (H1 batch scope)
- report the files you created and the H1 questions only, in 10 lines or fewer, then stop.

[Afterwards]
The audit continues in new sessions with the single line:
Read ui-audit/handoff/START.md and follow it exactly.
(or unattended: powershell -ExecutionPolicy Bypass -File ui-audit/run_audit.ps1)
```
