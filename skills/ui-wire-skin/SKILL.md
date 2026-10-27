---
name: ui-wire-skin
description: "Orchestrates agents to design one game UI screen on top of the project's design-system data (ui-audit catalog + kit): feature inventory -> low-fidelity wireframe (UX flow, attention budget, precedent check) -> design-system skinning (HTML mockup) -> measured verification -> review -> alignment audit -> comparison page and user gates. Use when planning the UI for new content or redesigning an existing screen. Triggers: 'wireframe', 'mockup', 'skinning', 'design variant', 'precedent check', 'build a screen from the design system' / '와이어', '목업', '스키닝', '시안', '범례 확인', '디자인 시스템으로 화면 만들기'."
argument-hint: "<screen name> [feature source path/description] [--from wire|skin|audit]"
user-invocable: true
allowed-tools: Read, Glob, Grep, Write, Edit, Bash, Agent, AskUserQuestion, Skill
---

# UI wireframe -> skinning routine

This routine was distilled from a real screen redesign that went through several failed and successful rounds. Its rules exist because each one was broken at least once.

You are the **orchestrator**. Do not build the screen yourself: hand each stage to an agent, and keep the contracts (files), independent verification and user gates for yourself.

All paths below are relative to the Unity project root (the folder that contains `ui-audit/`) unless a step says it runs inside a track folder.

## Relationship to the design-system package (read first)

- If the project has a generated design-system package (`Docs/ui-design-system/`, see the `ui-design-system` skill), **its `INDEX.md` rules and prohibitions take precedence over this skill.** Paste those rules verbatim into every agent prompt. Typical ones: only use screens marked `cleanReference=true` as references; mark templates whose `standard` is undecided with a warning and ask a human; never rebuild a template's look out of plain Image/TMP nodes; never unpack prefabs with `PrefabUnpackMode.Completely`; no new sprites and no colors outside the tokens.
- This skill covers the **design stage** (feature inventory -> wireframe -> HTML mockup -> verification and comparison). Moving an approved mockup into prefabs and wiring code is a separate step that follows the design-system package (`Docs/ui-design-system/SKILL.md`, skeleton recipes, and the project's new-screen checklist if it has one).
- **Flow first.** Do not recompose a layout from a blank page. (1) Confirm the main user flow from the spec (user gate). (2) List existing, finished screens whose real flow resembles it, using the `next` links in `ui-audit/data/app-flow.json` if the project provides that file, and verify the templates used at each step against the data (user gate). (3) Build on the **layout of the most similar flow** and place templates on it. Anything that departs from the reference layout goes into `deviations.md` with a reason. A track that scored similarity by visual impression and recomposed freely was judged a failure on both layout and templates.

## 0. Prerequisites and track folder

- Design-system data lives in `ui-audit/`: `data/layout/screen|template/*.json` (node boxes and template slugs), `data/templates/*.json` and `data/template-index.json`, `data/tokens/*.json`, `previews/layout/*/*.png` (real Unity layout renders), `catalog/app-flow.html`. If it is missing or stale, regenerate it first (`ui-audit` skill; `python ui-audit/scripts/ds_publish.py --plan` tells you what is stale).
- `ui-audit/data/app-flow.json` is an optional input written by a project-specific producer (schema: `ui-audit/schemas/app-flow.json`). Without it, pick reference screens from the catalog and `screens.jsonl` and ask the user to confirm the flow.
- Track folder: everything for one screen goes into `ui-audit/design/<screen>/`. The first task is a plan file `<date>-<screen>-plan.md` (stages, agents, acceptance criteria, checklist).
- Scripts: copy this skill's `scripts/` into `<track>/tools/` and run them from the track folder. `shoot.py` and `attention.py` resolve page and output paths relative to the track folder and read `<track>/kit/kit.css`; `measure_a11y.py` resolves the page relative to the current folder.
- If the existing mockups or the current prefab are just a "list of features", declare them **not usable as a reference** and redesign from the features. Confirm this with the user.

## 1. Stages

| Stage | Owner (agent) | Output | User gate |
|---|---|---|---|
| **S0 Feature inventory** | systems-designer (features, formulas, states) in parallel with Explore (runtime and server contract) | `features.md` (features F1..., evidence file:line, frequency, locks, state machine, formulas, unknowns), `runtime-facts.md`, `fixture.json` (about 5 states with real data and real computed values) | Feature list and frequency ranking |
| **S2 Design kit** (parallel with S0) | art-director (`kit/rules.md`: visual rules, reference screens) in parallel with general-purpose (`kit/` extraction: `kit.css` tokens, ColorTint, 9-slice, fonts, real sprites, `components.md`, specimen, `build_kit.py`) | `kit/` | Specimen review, how to treat off-kit colors |
| **S1a Flow and reference flow** | ux-designer (flow) -> general-purpose (flows of similar finished screens and their templates, verified against data, `cleanReference=true` only) | `flow.md` (main flow, per candidate screen: flow, templates per step, similarity evidence) | Flow confirmed, reference screen chosen |
| **S1b Wireframe** | ux-designer -> game-designer (adversarial review) | `ux-flow.md` (tasks, changes vs. reference layout, hierarchy, placement table, interactions, tap counts), `wire.html` (grey boxes on the reference layout, state toggles, working interactions) | Wireframe approved |
| **Precedent check** (every wireframe revision) | orchestrator | For every placement and visual expression: an existing-screen precedent or "new" -> wireframe revision note | Whether to register new patterns |
| **S3-0 Scene composition** (before skinning, mandatory) | general-purpose x1 (loads the frontend-design skill; the aesthetic is the existing scene composition). The **same agent** continues into S3 | `<x>/composition.md` (one-line concept, 2-3 reference screens and why, panel count/position/off-screen flow, left-side composition, block coordinates per region with a **content-based rationale**, wireframe region/flow mapping) + `<x>/composition-sheet.png` (2-3 reference renders next to the planned block layout) | **Orchestrator gate** (load frontend-design, confirm zero precedent violations) -> show the user one composition sheet |
| **S3 Skinning** | the S3-0 agent continues (keeps the composition context), x1-2 (frontend-design skill, but the aesthetic is the project kit and existing screens) | `variant-x/` (+`deviations.md`) + **`shots/variant-x/ref-compare.png`** (reference renders vs. variant). Default: a strict variant (kit only) and a proposal variant (deviations recorded) in parallel | Pick a variant |
| **S4 Verification and review** | orchestrator measures + judges `ref-compare` itself + 4 reviews in parallel: ux-designer, art-director (**judges only reference renders vs. variant**), general-purpose (measured accessibility), unity-ui-specialist | `review/s4-*.md`, fix instructions | Policy decisions surfaced by reviews |
| **Alignment audit** (when aligning the chosen variant with the design system) | general-purpose (component evidence table) in parallel with ux-designer (attention budget, information audit) -> verdicts from art-director, game-designer, unity-ui-specialist | `<x>2/component-audit.md` (1 revert, 2 variant, 3 promote, 4 screen-only), `attention-budget.md`, `art-verdict.md`, `decisions.md` | Decision page |
| **Compare** | orchestrator | `compare-*.html` (states side by side, blur, attention view, metrics, decision items) | Final pick |

Detailed prompt templates: `references/agent-prompts.md`. Put each stage's acceptance criteria verbatim into its prompt.

**Wireframe -> mockup translation rule.** A wireframe is a **topology drawing**: only the list of regions, their order, the flow, the hierarchy, interactions and states pass to S3. Say explicitly in the prompt that the wireframe's coordinates, box shapes, panel borders, widths and any measured sizes are **not** passed on, and never write "keep the wireframe structure" or "same region as the wireframe". Geometry is decided fresh in S3-0 from the **existing scene composition**. (A variant that copied the two bordered side panels of a grey-box wireframe passed every measurement, yet ended up with two paper panels where every existing screen used one, and was rejected as "looks like a different game".)

## 2. Wireframe principles (UX)

- Hierarchy = **order of user action frequency** (confirmed with the user). Set an **attention budget** per state: one first-priority item, two or three second-priority items, and what may stay invisible.
- Put action buttons **in the panel that holds their target** (no global toolbar; the usual precedent is an action bar at the bottom of the panel). Information that belongs to a list goes in that panel's header; below the title plate, only a single headline number for the screen or a sub-menu.
- Make selection and assignment **visible**: show what is selected and, before the action, where it will go. After an action, do not let rows jump because of sorting; pin them while the selection lasts.
- Do not invent things the server contract does not have.
- Wireframe page contract (used by the measurement scripts): `#canvas` 1280x720; global `STATE_IDS` and `loadState(id)`; optional `window.stopTimers()`, `openDetail(id)` and `draftingIds(stateId)`. Reuse the project's shared screen skeleton (title plate, back button, safe-area background) with the coordinates from `skeletons.md` or the layout data.

## 3. Precedent check routine (before every placement or visual decision)

1. `python tools/find_precedents.py --name "<node name regex>" [--region x,y,w,h] [--template <slug>] [--include-inactive] --sheet <out.png>` finds screens that contain the node, where it sits and whether it is active, and crops the renders into one contact sheet. A path regex (`--pattern`) needs `MSYS_NO_PATHCONV=1` in Git Bash.
2. Look at the crops yourself and decide whether the role is the same. States that are **switched off** in the default render (Selected and similar) are not visible: follow the prefab YAML for that GameObject -> Image `m_Sprite` guid -> `ui-audit/cache/guid-index.json` to find and open the sprite (a full `Assets/` grep takes minutes).
3. Record the result in the wireframe revision note as "precedent: <screen> <node/sprite>" or "**new** (no precedent)". New patterns go to the user's decision queue.
- Keep the precedents you find in `references/precedents.md` (a template for your project's catalog).

## 4. Skinning rules

### 4-0. S3-0 scene composition (before skinning, same agent)

Decide **scene composition first, components second**. Mapping elements to components first makes the composition follow the wireframe's box geometry.
1. Open 2-3 renders of existing screens of the same nature (`ui-audit/previews/layout/screen/<slug>.png`) **yourself** and choose them, with a one-line reason each. The agent writes a **one-line concept** of its own (for example "a notice board in a tavern"); give it that authority.
2. Decide the following, using the "Scene composition" precedents in `references/precedents.md` (evidence: the panel rects in `data/layout/screen/*.json` across all screens, plus renders):
   - **How many main panels** existing screens use and **where** (for example: docked right and flowing off the right/bottom edge, or full-width at the bottom). Derive the panel position from **content** within the precedent range (for example "n cards x height + header strip -> panel height", "minimum detail width -> panel x").
   - **Left-side composition** (what sits directly on the background: info plates, standalone slots, a button row next to the back button). Do not wrap the left side in the main panel unless precedents do.
   - **Tabs**, the **panel header strip** (icon + title + n/max, chips on the right) and the **panel body** style, as your precedents define them.
   - Title plate and back-button coordinates come straight from the shared skeleton.
3. **Core component precedent check** (added after a round that matched the composition but skipped this step, so the user had to catch five element-level mismatches): for each item below, find the precedent template and the screens using it with `find_precedents.py` and `references/precedents.md`, then put **the precedent render crop next to the plan at the same scale**.
   - The list-row template and **the container that holds those rows** (information rows live inside a panel, popup or list board; not as standalone cards on the background, unless your precedents say otherwise)
   - Tabs: selected/unselected art, offset, text rules, **alignment** (for example, a panel docked right may right-align its tabs)
   - Character or item thumbnails: the unit that screens doing the same job actually use
   - Selected/target/done/locked markers: one grammar for the whole screen
   - The action button row and the popup frame
   "The node coordinates equal the template default" is not a precedent match; the same template is aligned and spaced differently depending on the screen. Judge by render crops.
4. Output: `composition.md` (the decisions above + block coordinates per region + content-based rationale + wireframe region/flow mapping with zero missing regions + precedent source per component) and `composition-sheet.png` (2-3 reference renders next to the planned blocks, plus a **row of component crop comparisons**, made by a script).
5. **Orchestrator gate**: load the frontend-design skill, look at the sheet yourself and confirm zero precedent violations (panel count, position, left side, tabs, header strip, plus the component crop row), then show the user one composition sheet. No skinning before this gate passes. Re-check any "same" verdict from a research agent against the crops.

### 4-1. Skinning

- The aesthetic is **the project's existing scene composition plus the kit** (`kit/rules.md`), not a "new aesthetic" from frontend-design. Use frontend-design's principles (spatial composition, whitespace, density, detail) to match the existing renders. No default rounded corners or soft shadows.
- **The element mapping (element -> template slug table) is reference material after composition.** Never pass it as the "top priority" constraint. When it conflicts with the composition, **composition wins**.
- Every visual element carries `data-template="<slug>"` (+`data-variant`), or `data-new="promote:<name>"` (candidate for a shared component), or `data-new="<name - description>"` (screen-only). Colors or shapes outside the kit go in `deviations.md` (what, why, Unity cost, small/medium/large; no effort estimates in time).
- Give every meaningful region a `data-area="<lowercase-hyphen>"` key (and `data-idx` on repeated units) so the review viewer and the `ui-feedback` loop can anchor feedback to it.
- Strict variant = `kit.css` colors only (`shoot.py --strict-colors`). Proposal variant = every deviation recorded.
- Reuse the wireframe's behavior JS (states, formulas). Never edit a frozen earlier variant; verify with a checksum (`sha1sum ... > <x>.frozen.sha1`).

## 5. Verification (the orchestrator runs it; do not trust agent reports)

Run inside the track folder:
```
python tools/shoot.py variant-x/index.html --out shots/variant-x [--strict-colors]   # canvas, scroll, clipping, images, errors, off-kit colors
python tools/attention.py variant-x/index.html --out <dir>                           # font sizes, yellow primary actions, animations, empty area, blur, top salient point
python tools/measure_a11y.py variant-x/index.html                                    # minimum touch target, font size, contrast
```
- Default acceptance values (agree them with the user and re-check per screen; adapt to your project): touch target >= 47 px, primary button >= 51 px tall, text >= 12 px, decision numbers >= 14 px, information text contrast >= 4.5:1, at most 9 distinct font sizes per state, one primary (yellow) action per region, looping motion only in states that need an action. `attention.py` counts primary actions via `data-template^="button-yellow"`; if your primary-button slug differs, adjust the copy in `tools/`.
- **A reference comparison sheet is mandatory**: `shots/variant-x/ref-compare.png` (top: the 2-3 reference renders chosen in S3-0; bottom: 2-3 representative states of the variant, same scale). The orchestrator **opens it** and judges each scene-composition precedent (panel count, position, off-screen flow, left side, tabs, header strip, body, title plate) as pass/fail. **Never report measurement PASS as aesthetic or composition approval**: the scripts measure rule compliance, not similarity to the existing scenes.
- The art review judges **reference renders vs. variant** first. Do not give it the mapping table or decision documents as premises (only afterwards, for cross-checking); a review that received the mapping as a premise reported "kit consistency is good" and missed the composition drift.
- Confirm every contrast failure **on the screenshot**: when a button face or strip is drawn by a child sprite, the measurement is a false positive.
- Record template coverage (share of visible elements with `data-template`) per variant.
- Recompute fixture numbers with an independent script; do not trust the agent's `calc` fields.

## 6. Orchestration rules

- Contracts are files. Every prompt states input paths, acceptance criteria and **allowed write paths**. Parallel calls go in one message.
- Agents must **not use the Playwright MCP browser** (it is shared and collides). Headless scripts only; only the orchestrator may use MCP.
- **Do not ask agents without a Write tool (for example `accessibility-specialist`) to produce files.** Use general-purpose with a specialist prompt instead. After a completion report, **check the files exist first**.
- Messages sent to an agent after it ended its turn may never be processed. Check file modification times and re-verify, then wake it again.
- At most two fix loops. Whatever is left goes on the comparison page as "unresolved".
- Batch user questions into one message (AskUserQuestion, recommended option first), and only ask what changes the direction. Record policy decisions in `decisions.md`.
- Treat the Unity project as read-only. Commit only when the user says so. Update the plan's checklist after every stage.

## 7. Pitfalls

See `references/pitfalls.md`: passing wireframe geometry as a layout spec (composition collapses), CSS mask CORS when pages are opened from disk, shared templates (title plate and similar) that cannot be shrunk for one screen, constraints of shared screens such as confirmation dialogs and toasts, rows jumping after sorting, factual errors in labels, code defaults vs. real preset values, and more.
