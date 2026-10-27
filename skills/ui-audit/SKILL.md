---
name: ui-audit
description: "Sets up and runs the ui-audit toolkit on a Unity uGUI project: install the toolkit into <project>/ui-audit/, prepare A0 (project.json, spec/batch-plan.json, a0_setup.py), then let agents run the batch pipeline H1 -> A1..A6 -> F (state.py render names the next action; run_audit.ps1 runs it unattended) to build the HTML UI catalog, then extend it with the template catalog, screen layout maps and the agent-facing design-system index. Use when auditing a project's existing UI, (re)building the catalog, or resuming an audit. Triggers: 'UI audit', 'audit the UI', 'build the UI catalog', 'template catalog', 'screen layout map', 'resume the audit', 'A0 setup' / 'UI 오딧', 'UI 현황 정리', '카탈로그 만들어', '템플릿 카탈로그', '화면 배치 맵', '오딧 이어서', 'A0 준비'."
argument-hint: "[setup|run|status|templates|screen-map|design-system]"
user-invocable: true
allowed-tools: Read, Glob, Grep, Write, Edit, Bash, Agent, AskUserQuestion, Skill
---

# UI audit (`ui-audit` toolkit)

The toolkit reads a Unity project's UI prefabs (text-serialized YAML; the project is never modified), classifies every UI node, groups variants, extracts token drafts and builds a static **HTML catalog** of what exists and how fragmented it is. Later stages add a **template catalog** (which prefabs are reused as components and where), **screen layout maps** (real Unity renders with node boxes) and an **agent-facing design-system index** that the `ui-design-system`, `ui-wire-skin` and `ui-feedback` skills build on.

This skill is the overview and entry point. The step definitions live in `ui-audit/ROADMAP.md` (installed with the toolkit; Korean in v0.1); `a0_setup.py` turns its code blocks into the agent instruction files under `ui-audit/agents/`. Do not restate those rules here; point agents at the generated files.

Conventions:
- **Paths** are relative to the Unity project root (the folder that contains `ui-audit/`) unless noted.
- **Working folder**: the audit pipeline (A0, `state.py`, `batch.py`, `build_catalog.py`, the `agents/*.md` instructions, `handoff/START.md`) runs **inside `ui-audit/`** (`python scripts/<x>.py`). The design and feedback tools are usually called from the project root (`python ui-audit/scripts/<x>.py`); scripts resolve their own root, so both work, but follow whatever the generated instruction file says.
- **Language**: in v0.1, generated files (catalog HTML, `agents/*.md`, `handoff/*`, reports), CLI messages and some CLI arguments (decision statuses such as `표준`/`폐기`/`예외`, step labels such as `H1 배치 범위 확인`) are Korean. Agents handle this fine; tell human readers to expect it.
- **Rules for every session**: the Unity project is read-only (write only inside `ui-audit/`, plus the renderer package you installed); state files (`manifest.json`, `decisions.json`, `questions.json`) change only through their scripts; write code and docs with the Write tool, not shell heredocs (they mangle backslashes); report only verified facts.

## Requirements

- Python 3.10+ (standard library for the audit; `playwright` + Chromium, `Pillow` for render checks, previews and the review tools).
- A Unity project using **uGUI + TextMeshPro** with assets serialized as text (Force Text).
- Claude Code CLI (`claude`) for unattended runs.
- For the render steps (thumbnails, layout maps): the Unity editor version from `ProjectSettings/ProjectVersion.txt` installed through Unity Hub, and the ClaudeBridge renderer package from this repository's `unity/` folder added to the project. Renders run in batch mode **with graphics** (never `-nographics`) and need the project closed in the Unity editor.

## 1. Install

Copy the toolkit into the project with the repository's installer (see the repository README for the exact options):
```
python <ui-design-loop>/install.py --target <unity-project>/ui-audit
```
This creates `ui-audit/` with `scripts/`, `schemas/`, `spec/` (`steps.json`, `catalog.md`), `ROADMAP.md`, `run_audit.ps1`, `catalog/assets/` and `feedback/CONTRACT.md`. Add `ui-audit/` to `.gitignore` unless your team decides to share parts of it.

## 2. A0 - prepare the workspace (once)

You (or a session started with `references/kickoff-a0.md`) write two project files, then run A0:

1. `ui-audit/project.json` - Unity root relative to `ui-audit/` (usually `".."`), UI system, UI prefab root, reference resolution, platforms, screenshot ratios, minimum touch size, GUID index roots. Every key, type, default and the script that reads it: `docs/project-json.md` in this repository.
2. `ui-audit/spec/batch-plan.json` - the batch order as candidate folders under `ui_root`:
   ```json
   {"batches": [
     {"batch": "b1", "title": "Lobby, top bar, common popups", "folders": ["<Lobby folder>", "<Common folder>"],
      "questions": ["Which prefab is the top bar?"]},
     {"batch": "b2", "title": "Character, inventory", "folders": ["<Character folder>", "<Inventory folder>"]},
     {"batch": "b3", "title": "Remaining screens", "folders": ["<other folders>"]}
   ]}
   ```
   Start with the most-used screens (lobby, top bar, common popups), then the big feature screens, then the rest. `questions` are optional notes for the H1 gate.
3. Inside `ui-audit/`:
   ```
   python scripts/a0_setup.py            # writes agents/, handoff/START.md, schemas/, manifest.json (refuses if manifest.json exists)
   python scripts/a0_setup.py --check    # every script's self-test + validation of existing data
   python scripts/state.py render        # the next action must be "H1 배치 범위 확인" (H1 batch scope)
   ```
   After editing `ROADMAP.md`, regenerate the instruction files with `python scripts/a0_setup.py --docs-only` (it never touches `scripts/`, `data/` or state files).

## 3. Run the audit - H1 -> A1..A6 -> F

Per batch: **H1** batch scope -> **A1** collect (`parse_prefab.py`) -> **A2** classify -> **A3** group -> **H2** groups/standards -> **A4** tokens -> **H3** token decisions -> **A5** catalog build -> **A6** verification against the sources; after the last batch, **F** writes `reports/FINAL.md` and `handoff/DONE`. Definitions: `ROADMAP.md` "에이전트 정의" (agent definitions) and the generated `agents/*.md`.

`python scripts/state.py render` (inside `ui-audit/`) always prints the current batch, the **next action** and how to delegate it; `manifest.json` is the single source of truth.

- **Unattended (default)**: from the project root,
  ```
  powershell -ExecutionPolicy Bypass -File ui-audit/run_audit.ps1
  ```
  Each round starts a fresh `claude -p` session in `ui-audit/` that reads `handoff/START.md` (the L0 session manager), delegates one step or gate to a sub-agent and hands over. Gates H1-H3 are decided by gate agents with the rules in `agents/H1.md`-`H3.md` and recorded as `by: agent`. It stops when `handoff/DONE` exists, when two rounds add nothing to `handoff/log.md`, or after `-MaxRuns` (default 40). Progress: `ui-audit/handoff/runs.log`, `handoff/log.md`. See `references/kickoff-autonomous.md` before the first run (permission flags, Claude Code version).
- **Interactive**: start a session in `ui-audit/` with "Read handoff/START.md and follow it exactly."
- **Human review at the end**: `ui-audit/reports/FINAL.md` (agent decisions in review order, held chunks, items without visual verification) and `ui-audit/catalog/index.html`. Override any decision with `python scripts/record_decision.py <id> 표준|폐기 [--to <id>]|예외 --reason "..."` (standard / deprecated / exception; `--by user` is the default). Recording a decision invalidates A5/A6 of the current batch; `state.py render` then asks for "A5 재빌드 -> A6 재검증" (rebuild, re-verify).
- Failure handling is built in: twice-failed steps are `reset` once, then `skip`ped into `reports/blockers.md`.

## 4. Template catalog and screen layout maps (after F)

These extend the node catalog with reusable templates, their usage, look-alikes, thumbnails and per-screen layout maps. Run inside `ui-audit/`, in this order (`[Unity]` = batch render, close the editor first):
```
python scripts/parse_prefab.py --reindex                          # prefab nodes + GUID index
python scripts/scene_enum.py --run                                # reachable scenes (project.json "scenes")
python scripts/code_usage.py --run                                # prefabs loaded from code (project.json "code")
python scripts/usage_graph.py --prefabs
python scripts/usage_graph.py --scenes
python scripts/templates.py --select --overrides --lookalikes      # template selection, overrides, look-alikes
python scripts/thumbs.py --list --run --collect                   # [Unity] template thumbnails
python scripts/templates.py --assemble
python scripts/layout_map.py --list --run --collect               # [Unity] screen and template layout renders
python scripts/layout_map.py --check-samples <slug>,<slug>,<slug> # boxes vs. parsed prefab nodes on 3 screens of yours
python scripts/build_catalog.py --all
python scripts/validate.py --rename catalog
python scripts/build_catalog.py --check                           # zero broken links
python scripts/catalog_library.py --build                         # review-viewer dock data (needs playwright)
```
- `data/app-flow.json` (app icon -> screen flow; schema `schemas/app-flow.json`) is an **optional input** produced by a project-specific producer that is not part of this toolkit. If present, the layout map also covers its screens and the catalog home becomes the app-flow explorer; otherwise the home is the screen list.
- `python scripts/ds_publish.py --plan` compares the data build time with git history and prints which of these steps are needed now.
- Session kickoffs for building or extending these features: `references/kickoff-template-catalog.md`, `references/kickoff-screen-map.md`.

## 5. Design system for agents

The `ui-design-system` skill covers the generated package `Docs/ui-design-system/` (`INDEX.md`, `templates.jsonl`, `screens.jsonl`, `skeletons.md`, `UPDATE.md`, `SKILL.md`): `python scripts/ds_index.py --run`, `python scripts/ds_skeletons.py --run`, then `python scripts/ds_index.py --check`. Optional drafting tools: `ds_roles.py` (role labels for templates, human-approved) and `ds_colors.py` (semantic color token names, human-approved). Kickoffs: `references/kickoff-ds-agents.md` (build the package end to end with human gates) and `references/kickoff-ds-usage.md` (explain to the user what is ready and how to brief agents).

## 6. Design and feedback

- New or redesigned screens: `ui-wire-skin` skill (wireframe -> composition -> skinned HTML mockup -> measured verification).
- Feedback on registered mockups: start `python ui-audit/scripts/review_server.py`, open `ui-audit/catalog/review.html?screen=<UIType>&stage=<wire|mockup>`; Claude processes it with the `ui-feedback` skill. Operations: `docs/feedback-loop.md`.

## 7. Other kickoffs

- `references/kickoff-intro-doc.md` - build an HTML introduction to the system for your team.
- `references/kickoff-ux-review.md` - UX review of the catalog/explorer pages and the review viewer.

Every kickoff is a message to paste into a **new** session. Replace the `<placeholders>` with your project's facts first.

## Pitfalls

- On Windows, `tasklist` may report zero `Unity.exe` processes while the editor runs; check with `Get-CimInstance Win32_Process -Filter "Name='Unity.exe'"`. The render scripts refuse to start while Unity is running.
- Do not wrap batch renders with tools that force `-nographics`; renders come out empty.
- After a `git pull` that touches prefabs, scenes, scripts or Addressables, regenerate from `parse_prefab.py --reindex` (section 4 order); `ds_publish.py --plan` detects this.
- Generated folders (`catalog/`, `Docs/ui-design-system/`) are overwritten by the next build; change the scripts or data, never the HTML/Markdown output.
- Do not run `a0_setup.py` without `--docs-only` once `manifest.json` exists (it refuses; `--force-reset` discards all progress and is for an explicit user request only).
