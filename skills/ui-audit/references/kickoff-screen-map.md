# Kickoff: screen layout maps and the visual explorer (S track)

Screen layout maps render every screen and template in Unity (batch mode with graphics) and record each node's on-screen box, so the catalog can show "this screen is built from these templates, here". They feed the explorer pages (`catalog/map/<slug>.html`, screen pages), the design-system index and every design skill. Requires the template catalog (previous kickoff) and the ClaudeBridge renderer package from `unity/`.

Paste the message below into a new session at the Unity project root.

```
You are building the screen layout maps of the ui-audit workspace and checking the explorer pages ("S track").
There is no earlier conversation; start from the files below. Communicate in <your language>; code and file names in English.

[Read first, in this order]
1. ui-audit/reports/FINAL.md: template catalog results and the regeneration order.
2. Only the parts you need of: python scripts/layout_map.py -h, thumbs.py, build_catalog.py (page, write, check),
   schema_defs.py, validate.py, common.py, and the renderer package's UILayoutRenderer.cs.
   Do not read ROADMAP.md.

[Inputs]
- data/template-index.json and data/templates/ (template catalog) must exist and be current.
- data/app-flow.json is OPTIONAL: if the project has a producer for it (app icon -> screen flow; schema schemas/app-flow.json),
  run it first; layout_map.py then also renders the flow's screens and the catalog home becomes the app-flow explorer.
  Without it, screens come from the template index only.

[Do, inside ui-audit/]
1. Unity check: Get-CimInstance Win32_Process -Filter "Name='Unity.exe'" must show no editor with this project
   (tasklist misreports). If one is open, tell me and wait.
2. python scripts/layout_map.py --list --only <3 slugs>   then --run --collect, as a small sample first.
   Batch mode with graphics; never add -nographics.
3. python scripts/layout_map.py --check-samples <slug>,<slug>,<slug>
   (pick 3 representative screens of this project; boxes without loaders/sample items must match parsed prefab nodes;
   overlay PNGs go to cache/layout-check/). Open the overlays and confirm the boxes sit on the rendered elements.
4. Full run: python scripts/layout_map.py --list --run --collect, then report the success rate (previews/layout/_failed.json).
5. python scripts/build_catalog.py --all, python scripts/validate.py --rename catalog, python scripts/build_catalog.py --check.
6. Look at the pages yourself: serve the project root with python -m http.server --bind 127.0.0.1 (headless Playwright may
   block pages opened from disk), take screenshots with headless Python Playwright, inspect them, then stop the server.
   If a page reads like a work list instead of a visual explorer, load the frontend-design skill before proposing changes,
   and propose them; do not rewrite generated HTML by hand (fix the generator scripts if asked).
7. Every new or changed script keeps its --selftest; python scripts/a0_setup.py --check must pass with 0 data mismatches.

[Rules]
- The Unity project is read-only (the renderer package is the only exception). Outputs stay in ui-audit/.
- Do not commit. Do not create worktrees.
- Do not delete or overwrite existing data (data/inventory, classified, groups, tokens, decisions.json, manifest.json, handoff/DONE).
- Write code files with the Write tool, not Bash heredocs.
- Before finishing, run your verification-before-completion and code-review steps if the project requires them.

[Report at the end, 15 lines or fewer]
Changed/created files, render success rate (screens and templates), box-check results on the 3 samples, self-test results,
open problems, and the 3 HTML pages a human should open first (with screenshot paths).
Then add a "Screen layout map" section to ui-audit/reports/FINAL.md.
```
