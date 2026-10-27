# Lessons learned building this toolkit

These are the mistakes and surprises we ran into while building and using the toolkit on a real, mid-sized Unity uGUI project (several hundred UI prefabs, about a hundred screens), and the rule we adopted after each one. Read this before adapting the toolkit to your project; most of the rules are already enforced somewhere, and the "Enforced by" lines say where.

Design-stage pitfalls that are specific to building wireframes and mockups are listed in more detail in [`skills/ui-wire-skin/references/pitfalls.md`](../skills/ui-wire-skin/references/pitfalls.md); this page only keeps the ones that shaped the overall process.

## Prefab YAML parsing and nested prefabs

**1. Nested-prefab object IDs follow a formula - except when they don't.**
The fileID of an object that comes from a nested prefab is normally `(PrefabInstance fileID ^ source fileID) & 0x7FFFFFFFFFFFFFFF`, and the `--- !u!... stripped` placeholder entries in the file match that formula. But Unity can re-save a prefab with stripped objects whose fileID is **not** the formula value, while other objects in the file still reference the stripped ID.
Rule: compute the formula ID, and when a stripped entry disagrees, treat its ID as an alias of the formula ID and rewrite references through the alias.
Enforced by: `parse_prefab.py` (stripped-ID aliasing; its self-test counts formula matches and asserts every stripped object resolves after expansion).

**2. Prefab YAML is not quite YAML, and removals are subtrees.**
Unity writes empty keys (`- : {fileID: 0}`) that libyaml rejects, and YAML 1.1 implicit typing turns a GameObject named `On`/`Off` into a boolean and date-like names into timestamps. Separately, removing only the GameObjects listed in a prefab instance's `m_RemovedGameObjects` leaves their children floating in the expanded tree.
Rule: pre-process the empty keys, remove the bool/timestamp implicit resolvers, treat names as strings, and remove the whole subtree under every removed GameObject.
Enforced by: `parse_prefab.py` (custom loader, subtree removal).

**3. A fresh clone cannot resolve uGUI script GUIDs.**
The GUIDs of `Image`, `Button`, `TextMeshProUGUI` and friends live in `.meta` files under `Library/PackageCache`, which does not exist until Unity has opened the project once. On a fresh clone, every UI component looked like an unknown script. Built-in resources (`0000000000000000f000000000000000`, e.g. `UISprite`) have no `.meta` at all.
Rule: ship a built-in table of uGUI/TextMeshPro script GUIDs and built-in resource IDs as a fallback; use the GUID index first when it exists.
Enforced by: `parse_prefab.py` (built-in script and resource tables); `project.json` `guid_index_roots` should include `Library/PackageCache` and `Packages` when available.

**4. Missing assets are real data, not parser bugs.**
Some referenced font and sprite GUIDs existed nowhere in the project. Hiding them would have hidden real defects.
Rule: record every unresolved GUID, missing sprite and code-filled empty container in `unresolved`, and report them for visual checking instead of guessing.
Enforced by: A1 instructions (`agents/A1.md`) and the F report.

## Template detection and usage

**5. Names lie; match suffixes, not substrings.**
A classification rule for popups fired on sprite names such as `Popup_Icon_Add`, and per-screen baked sprite copies (a `__<PrefabName>` suffix on the sprite name) looked like different sprites, so identical visuals landed in separate variant groups.
Rule: classify on name suffixes and component makeup, strip the baked-copy suffix before comparing sprites, and send ambiguous nodes to a question instead of a guess.
Enforced by: `classify_rules.py` and `templates.py` (suffix stripping); ambiguous cases go to `questions.py` and the H2 gate. `group.py` signatures do not strip the suffix yet, so expect some duplicate groups.

**6. Usage is more than nesting.**
Counting only nested prefab instances marked many prefabs as unused: list items referenced through serialized fields, prefabs loaded by address from code, and items instantiated by recycling lists were invisible.
Rule: build the usage graph from four sources - nested instances, serialized field references, code loaders, and scenes - and treat "unused" as a candidate list for a human, never as a deletion list. Dynamic loads built from string concatenation stay unresolved.
Enforced by: `usage_graph.py` (prefabs, scenes), `code_usage.py` (`project.json` `code.*`), `scene_enum.py` (`scenes.*`), `templates.py --select`.

**7. Use the build system's address table as the truth, not a naming convention.**
Many prefab addresses did not follow the documented address pattern.
Rule: resolve keys to assets through the Addressables group files (`m_GUID`, `m_Address`) and fall back to file names only when no group entry exists.
Enforced by: `code_usage.py`, `scene_enum.py`.

**8. "Clone then unpack completely" silently destroys the design system.**
Editor build tools that duplicated an existing screen and then called `PrefabUtility.UnpackPrefabInstance(..., PrefabUnpackMode.Completely, ...)` turned every shared template (title plate, back button, popup frames) into a same-named plain copy. A rebuild pilot showed that all broken template links in the rebuilt screens came from this one call; prefab variants kept every link.
Rule: duplicate with `PrefabUtility.LoadPrefabContents` or unpack `OutermostRoot` only; never `Completely`.
Enforced by: the generated `Docs/ui-design-system/INDEX.md` prohibitions and the `ui-design-system` skill.

## Rendering and measurement

**9. Batch rendering needs graphics, an idle editor, and a check that actually works.**
A command-line wrapper that always added `-nographics` produced empty images; the editor GUI and batch mode cannot open the same project at the same time; and on Windows `tasklist` reported zero `Unity.exe` processes while the editor was running.
Rule: render in `-batchmode` without `-nographics`, check for a running editor with `Get-CimInstance Win32_Process`, and refuse to start if one is found.
Enforced by: `thumbs.py --run`, `layout_map.py --run` (both refuse while Unity runs).

**10. Prefabs are not screens until you wrap them.**
Most UI prefabs have no Canvas of their own, loader components only populate children when asked, and a few prefabs have a plain Transform root. Renders came out empty or failed.
Rule: wrap prefabs in a temporary Canvas at the reference resolution, trigger loaders explicitly, record failures and empty renders as "runtime-bound" instead of hiding them, and check layout boxes against parsed prefab nodes on a few sample screens.
Enforced by: the ClaudeBridge renderers in `unity/`, `thumbs.py --collect` / `layout_map.py --collect` (failure lists), `layout_map.py --check-samples <slug,...>`.

**11. Measurement PASS is not "looks right".**
A mockup passed every measurement (no scroll, no clipping, no off-kit color, touch and contrast minimums, high template coverage) and was still rejected as "looks like a different game": it had two main panels where every existing screen had one. The scripts measure rule compliance, not similarity to the existing scenes.
Rule: every mockup gets a reference comparison sheet (existing renders above, mockup states below, same scale) that the orchestrator inspects item by item, and the art review judges renders before it sees any mapping table.
Enforced by: `ui-wire-skin` steps 4-0 (composition gate) and 5 (`ref-compare.png`).

**12. Font sizes need the font asset's scale.**
Kit font sizes taken from TextMeshPro `fontSize` were 1.25x too large: the rendered glyph size also depends on the font asset's own scale (`m_Scale`), and the HTML mockups use a 2/3-scale canvas.
Rule: kit pixel size = TMP size x font asset scale x mockup canvas scale; verify one sample against a render before trusting the kit.
Enforced by: convention in the kit generator a design track writes (`ui-wire-skin` S2); not checked by a toolkit script.

**13. Huge PNGs are usually metadata.**
A few portrait PNGs weighed hundreds of MB and made the viewer crawl; the pixels were small, the embedded XMP metadata was not.
Rule: strip metadata from images before putting them into mockups or shared data.
Enforced by: nothing automatic - check file sizes when a page is slow.

## Agent orchestration and gates

**14. Agents without a Write tool report fake completion.**
A review agent whose definition had only read tools replied "report written" - no file existed, and its numbers were generic. Another agent reported 28/28 tests passing where a re-run gave 27/28, and one "fixed" a template swap by changing only a `data-template` attribute while the screen looked the same.
Rule: give file-producing work only to agents with Write/Bash (put the specialist view in the prompt), check that the files exist after every report, and re-run acceptance commands yourself.
Enforced by: `ui-wire-skin` step 6; `ui-feedback` template-swap rule (before/after crops must differ, or no `revise`).
Related: shell heredocs collapsed `\\` into `\` and broke regular expressions in generated code twice, so agents write code and docs with the Write/Edit tools (stated in every kickoff prompt and the `ui-audit` skill).

**15. One source of truth for state, changed only by scripts.**
Long autonomous runs crash, hit context limits and get resumed by fresh sessions. A second, hand-edited status file or an agent "remembering" progress led to repeated or lost work in early designs.
Rule: `manifest.json` is the only progress record, changed only through `state.py`; every write goes to `.tmp`, passes schema validation, then is renamed; chunks are small enough to redo.
Enforced by: `state.py` (render/start/chunk-done/step-done/reopen/skip), `validate.py --rename`, `spec/steps.json` done conditions.

**16. Autonomous decisions must be labelled and reversible.**
In a full unattended run, every one of the standard/token decisions was made by gate agents. That is fine for a first catalog, but agents then had weak grounds to choose "which button is the standard".
Rule: gate agents record `--by agent --reason "<rule and numbers>"`; the final report lists them in review order; a human decision always overrides and invalidates the affected catalog steps; narrow standard decisions that drive new screens are queued for a person.
Enforced by: `record_decision.py --by`, `agents/H1-H3.md`, `agents/F.md`, `state.py render` ("A5 rebuild -> A6 re-verify").

**17. Verify plan premises before building on them.**
Several plan statements turned out false when measured (a zoom view that "works the same when opened from disk" cannot, because running state steps needs DOM access; a component assumed to live in one region lived in another; a suspected cause of a flaky test was disproved by measurement).
Rule: confirm each premise of a plan with a measurement or a file read before implementing, and do not name a cause for a flaky failure until it is measured. Self-tests plus one end-to-end pass are not proof for concurrency or UI code - repeat runs.
Enforced by: process only (contract documents carry a "report contradictions instead of implementing around them" rule).

## Wireframe -> mockup design process

**18. Flow first, then the layout of the most similar finished screen.**
Designing a new screen by scoring candidate screens on overall impression and recomposing the layout freely failed twice, the second time even though the flow had been confirmed: the reference was borrowed wholesale from one finished screen that did not fit, and four complete mockups were produced where a low-fidelity layout comparison was needed.
Rule: confirm the user flow, verify which finished screens have a similar flow and which templates they use at each step (clean references only), build on that layout, record deviations, and show low-fidelity comparisons at layout gates.
Enforced by: `ui-wire-skin` stages S1a/S1b and the "flow first" rule.

**19. A wireframe is topology, not geometry.**
Passing the grey-box wireframe "as structured" to the skinning agent copied its box geometry and broke the scene composition.
Rule: wireframes pass regions, order, flow, hierarchy, interactions and states; geometry is decided in a separate scene-composition step from existing screens, with a gate before any skinning. Component precedents (list rows and their container, tabs and their alignment, thumbnails, selection markers) are compared as render crops at the same scale - equal node coordinates are not a precedent match.
Enforced by: `ui-wire-skin` S3-0 and section 4-0.

**20. Keep the adopted variant as the base; change by deltas.**
Once a variant was adopted, "rebuilding" the next revision from the wireframe lost what had been tuned.
Rule: a new revision = a copy of the adopted variant's code + an explicit delta list. Freeze earlier variants with checksums. Treat any instruction to "rebuild from scratch" as something to confirm with the user.
Enforced by: `ui-wire-skin` section 4-1 (frozen checksums), `ui-feedback` baseline check (pinned files are not edited without permission).

**21. Re-implementing templates in HTML drifts.**
When several agents each redrew the same Unity templates in HTML, coverage ranged widely, colors were approximated to the nearest token, and stretched non-9-slice frames broke.
Rule: build one kit per track (`kit.css` + real sprites + a component table mapping kit elements to template slugs) and reuse it in every variant; flag stretched frames and off-kit colors as deviations.
Enforced by: `ui-wire-skin` S2, `shoot.py --strict-colors`, the kit table read by `catalog_library.py` (`project.json` `design.kit_dir`).

## Feedback loop operations

**22. Ask what the user means before fixing a visual remark.**
A remark about "empty margins" was first fixed in the wrong place - the user meant the area outside the game canvas, not empty space in the document.
Rule: confirm on a screenshot which region a remark refers to; when a remark has no single direction, leave a question comment instead of editing.
Enforced by: `ui-feedback` step 2 (fix / ask / skip), and the viewer's game-screen display mode.

**23. The log is append-only, and Claude never closes.**
Rule: users open, comment, close and reopen through the server; Claude comments, claims, releases and revises through the CLI; every fix is recorded as a diff with before/after shots; edits stay inside the registry `files`; one claim at a time per variant so diffs do not mix.
Enforced by: `feedback_core.py` validation (who may write which event), `feedback.py` (claim/revise refuse mixing variants, revise refuses when nothing changed), `ui-feedback` rules 0-9.

## Team and shared-repository operations

**24. One shared log per team, on a server you restart after updates.**
Feedback ids are issued locally, so logs written on different machines cannot be merged through git. And after a fix to the feedback core, a running review server kept the old module in memory and behaved as before.
Rule: viewing goes through git (catalog and design data), feedback goes to one shared server, and `/ui-feedback` runs in that server's checkout so snapshots, diffs and the log share a disk. Never `git clean` that checkout. Restart `review_server.py` whenever its scripts are updated.
Enforced by: `review_server.py --host` (Origin checks), `project.json` `publish.team_server` (read-only viewers link to the team server), [`feedback-loop.md`](feedback-loop.md).

**25. Someone will pull while you work.**
A `git pull` into a shared working tree in the middle of a run made the GUID index stale and the data inconsistent.
Rule: after any pull that touches prefabs, scenes, watched scripts or Addressables, regenerate from `parse_prefab.py --reindex` in the documented order; let the tool decide what is stale. In a shared tree, never stash, reset or `git add -A`; add an allow-list of paths.
Enforced by: `ds_publish.py --plan` (compares the data build time with git history and the working tree), the generated `UPDATE.md`.
