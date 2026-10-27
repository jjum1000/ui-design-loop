---
name: ui-design-system
description: "Makes agents build new Unity UI screens (View/Popup prefabs, UI prefab build tools, screens from an HTML mockup) from the project's existing templates, skeleton recipes and rules, using the generated design-system package Docs/ui-design-system/ (INDEX.md first), and keeps that package fresh with ui-audit/scripts/ds_publish.py. Use before creating any new UI screen, popup or UI prefab, or when the user asks to refresh or check the design-system index. Triggers: 'new screen', 'new popup', 'build the UI from the mockup', 'create View/Popup prefab', 'UI build tool', 'refresh the design system index' / '새 화면 만들어', '새 팝업 추가', '목업대로 UI 구성', 'View/Popup 프리팹 생성', '빌드 툴로 UI 만들기', '디자인 시스템 색인 갱신'."
user-invocable: true
allowed-tools: Read, Glob, Grep, Write, Edit, Bash, AskUserQuestion
---

# Design system for new UI screens

The `ui-audit` toolkit generates an agent-facing summary of the project's real UI: `Docs/ui-design-system/` (paths are relative to the Unity project root). **Before you build any new UI screen, read its `INDEX.md` and follow the order and rules it gives.** The package reflects what the project actually uses (templates, reference screens, skeletons, decided standards); this skill only tells you how to use it and how to keep it current.

In v0.1 the generated files are written in Korean. Read them as they are; field names in the JSONL files are English.

## When to use

- A new View or Popup, a new UI prefab, or an editor build tool that creates UI prefabs.
- Turning an HTML mockup or a spec into a screen. (Designing the screen first? Use the `ui-wire-skin` skill; it follows the same package and hands an approved mockup to this skill.)
- Not for: a bug or text fix in one existing screen.

## The package (generated - never edit by hand)

| File | What it is | How to read it |
|---|---|---|
| `INDEX.md` | Entry point: reading order, rules and prohibitions, most-used templates, undecided standards, field reference, an instruction template | Read all of it first |
| `skeletons.md` | Skeleton recipes for View and Popup types (node paths, coordinates, templates) | Pick the recipe that matches your screen |
| `screens.jsonl` | One line per screen: templates used, recipe, `cleanReference` | `grep` for templates or recipes; only follow screens with `"cleanReference":true` |
| `templates.jsonl` | One line per template: role, standard, usage, path, frequently overridden properties, look-alike warnings | `grep` only the cards you need; never read the whole file |
| `UPDATE.md` | How and when to refresh the package | Read before regenerating |
| `SKILL.md` | The generated "new UI screen" procedure for this project | Follow it after `INDEX.md` |
| new-screen checklist (optional) | How a screen is wired in this project's code (screen id/enum, controller, view, Addressables...) | Produced by a project-specific producer if the project has one; follow it when present |

## Procedure

1. Read `Docs/ui-design-system/INDEX.md` completely, then the generated `SKILL.md` there. If they disagree with this skill, the generated files win (they carry the project's decisions).
2. If the request leaves blanks (entry point, reference screen, elements, states, data, prohibitions, output scope), ask for them **in one message**, using the instruction template in `INDEX.md`. Unknown data stays "TBD".
3. Pick reference screens (`cleanReference=true` in `screens.jsonl`) and a skeleton recipe (`skeletons.md`).
4. Propose a composition **before building**: a node tree in the recipe's shape, each node marked `[slug]` when it is a template instance or "new" otherwise, plus the list of reused templates (slug, standard) and the list of new things. Mark undecided standards with a warning instead of choosing silently. Get human approval.
5. Build (prefab via the project's build tool, wiring per the project's checklist if any).
6. Render and compare with the reference screens side by side; get the human's visual check before committing.

Stop at step 4 if the requested scope is "wireframe only", or after the prefab if the scope is "prefab only".

## Rules that hold unless INDEX.md says otherwise

- Instantiate templates; never rebuild a template's look out of plain Image/TMP nodes. No matching template -> list it as "new" and get approval.
- Never unpack nested prefabs with `PrefabUnpackMode.Completely` (all template links break). Duplicate with `PrefabUtility.LoadPrefabContents` or `OutermostRoot`.
- Do not modify existing screens' prefabs for a new screen.
- No new sprites and no colors outside the tokens.
- A template whose standard is "deprecated -> X" means use X. "Undecided" means state your reason in the composition and ask.
- Do not copy the structure of screens with `cleanReference=false`.
- No commits without human approval; never `git add -A`.
- Never edit files in `Docs/ui-design-system/` by hand; they are regenerated.

## Keeping the package fresh

Ask the toolkit what is stale; it compares the data build time with git history and the working tree:
```
python ui-audit/scripts/ds_publish.py --plan
```
It prints one of: full regeneration (prefabs, scenes, watched scripts or Addressables changed since the data build - needs Unity batch renders), index only (decisions, approved roles or token names, or the index scripts are newer than the index), or nothing to do, followed by the exact commands. Those commands are relative to `ui-audit/` (run them inside that folder). Then:
```
cd ui-audit
python scripts/ds_publish.py --run-index     # index-only refresh: ds_index.py --run, ds_skeletons.py --run, ... then ds_index.py --check
python scripts/ds_index.py --check           # generated files match current data, row counts, paths exist
python scripts/a0_setup.py --check           # self-tests and data schema validation
```
- `--plan` only reads (git reflog/diff/status and file times); it never runs Unity, pulls or commits.
- A full regeneration needs the Unity editor closed (batch renders with graphics). Follow `UPDATE.md` for the order and for which files your team commits.
- If the index looks stale and you do not own the data refresh, do not patch the generated files; tell the person who maintains the `ui-audit/` workspace.

## Without the ui-audit workspace

`Docs/ui-design-system/` can be committed and shared on its own. Paths inside it that point into `ui-audit/` (thumbnails, layout maps, catalog pages) only open in a checkout that has the workspace data. Without it, work from the Markdown and JSONL files alone.
