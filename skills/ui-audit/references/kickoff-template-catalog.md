# Kickoff: template catalog (T track)

The node catalog (A1-A6) describes individual UI nodes. The template catalog answers a different question: **which prefabs are reused as components, where, with which overrides, and which copy-pasted look-alikes exist.** It needs the project.json keys `ui_roots`/`common_dirs`/`exclude`, `code` and `scenes` (see `docs/project-json.md`) and, for thumbnails, the ClaudeBridge renderer package from `unity/`.

Paste the message below into a new session at the Unity project root.

```
You are building the template catalog ("T track") of the ui-audit workspace. There is no earlier conversation; start from the files below.
Communicate in <your language>; code and file names in English.

[Read first, in this order]
1. ui-audit/reports/FINAL.md sections on the node catalog: results and limits (if the node audit has run).
2. The usage docstrings of the scripts you will run (python scripts/<x>.py -h, or the top of the file):
   template_scope.py, scene_enum.py, code_usage.py, usage_graph.py, templates.py, thumbs.py, build_catalog.py.
   Do not read ROADMAP.md; the scripts are the reference for this track.
3. ui-audit/project.json: check ui_roots/ui_root, common_dirs, exclude, code.*, scenes.* against the real project
   (docs/project-json.md of the ui-design-loop repository describes every key). Missing keys fall back to defaults;
   list any value you think is wrong as a question instead of changing it.

[Do, inside ui-audit/]
1. python scripts/template_scope.py --list          (in-scope UI prefabs per folder - sanity check)
2. python scripts/parse_prefab.py --reindex
3. python scripts/scene_enum.py --run
4. python scripts/code_usage.py --run
5. python scripts/usage_graph.py --prefabs  and  python scripts/usage_graph.py --scenes
6. python scripts/templates.py --select --overrides --lookalikes
7. Thumbnails (Unity batch render):
   - Before running, check with Get-CimInstance Win32_Process -Filter "Name='Unity.exe'" that no Unity editor
     has this project open (tasklist misreports Unity.exe). If one is open, tell me and wait.
   - python scripts/thumbs.py --list --run --collect   (batch mode with graphics; never add -nographics)
8. python scripts/templates.py --assemble
9. python scripts/build_catalog.py --templates, then python scripts/validate.py --rename catalog,
   then python scripts/build_catalog.py --check (0 broken links)
10. python scripts/a0_setup.py --check must pass, with 0 mismatches in existing data.

[Rules]
- The Unity project is read-only. The only exception is the renderer package you installed. All outputs stay in ui-audit/.
- Do not commit. Do not create worktrees.
- Do not delete or overwrite existing data (data/inventory, classified, groups, tokens, decisions.json, manifest.json).
  Template-level decisions are recorded only through python scripts/record_decision.py --template <name|slug> ...
- Follow the project's CLAUDE.md principles: only what is asked, simple, precise, goal-driven.
- Write code files with the Write tool, not Bash heredocs (heredocs collapse backslashes).

[Report at the end, 15 lines or fewer]
Number of templates selected and how (common folder vs. suffix + 2+ usages), usage match rate on samples,
thumbnail success rate (previews/templates/_failed.json), self-test results, open problems,
and the 3 HTML pages a human should open first (catalog/templates.html, a template detail page, catalog/unused or scenes page).
After this works, append a "Template catalog" section with those numbers to ui-audit/reports/FINAL.md.
```
