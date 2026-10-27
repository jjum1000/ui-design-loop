# Pitfalls (each one actually happened on a real track)

## Data and facts
- **Code defaults are not real preset values.** Quoting field defaults from a `*Config.cs` gets numbers wrong (reward ratios off by 2x, success chances off by half). Confirm from the code which value the runtime actually reads.
- Unity serializes a preset `List<int>` into YAML as a little-endian hex blob; decode it before quoting.
- Fields that only the server uses (min/max party size and similar) are easy to mistake for client rules. Grep whether the client runtime reads them.
- Recompute agent-made sample data with an **independent script**. Real cases: parties that violated limits, missing combos, the same unit assigned twice in one state.
- Factually wrong labels: a "minimum reward" label when failure actually pays 50% is a lie. Do not copy such wording from a decision draft.

## Screen and presentation
- **Passing wireframe box geometry as a layout spec breaks the scene composition.** A variant that skinned the two bordered side panels of a grey-box wireframe "as structured" ended up with two paper panels, while every existing screen used one (docked right and flowing off-screen, or full-width at the bottom). The wireframe carries topology only; geometry comes from the existing scene composition in S3-0.
- **Handing over an element -> slug mapping table as "top priority" turns the builder into a spec assembler**: elements are slotted in without any composition decision. The mapping is reference material after composition.
- **All measurements PASS is not aesthetic approval.** shoot, attention, a11y and coverage only measure rule compliance. If the orchestrator does not look at the reference comparison sheet, a screen that "looks like a different game" passes. A reviewer given the mapping as a premise only reports "kit consistency is good".
- **Matching the scene composition without checking component precedents** drifts again at the element level. One round produced five user-caught issues: information rows as cards on the background, a tab art used by only one other screen, a screen-specific staff tile, a separate status text cell, and a different selection marker per row. S3-0 now includes a component crop comparison.
- **Node coordinates equal to the template default do not mean "same as the precedent".** Tabs placed at the template's default offset were judged "matching", but precedents with a panel docked right used right-aligned tabs. Judge by render crops.
- Art that belongs to one screen is easy to mistake for shared art because of its name (a `Common_*` sprite used by a single screen). Check usage count and screens before using any art.
- Checking one precedent ("panel without tabs") but not the screen-level precedent ("how many panels per screen") leads to wrong recommendations. Check composition precedents across all screens.
- Shared templates (the title plate and similar) cannot be shrunk for one screen. Check ownership before writing attention rules around them.
- Lists with sort rules make rows jump right after an action. Pin rows in place while the selection lasts.
- A button inside a row that does the same thing as clicking the row is redundant; keep row selection only.
- Wireframes tend to pile information under the title plate. Precedents usually put list information in that panel's header.
- State nodes such as Selected are switched off in the default render; look at the prefab's sprites directly.

## Tools and environment
- When a page is opened from disk (not through an HTTP server), CSS `mask-image` with an external PNG is blocked by CORS. Use `-webkit-mask-box-image` or pre-baked tinted PNGs.
- A viewport narrower than the background art reports false horizontal overflow; use 1920.
- Clipping with `overflow:hidden` can "pass" the no-scroll check; `shoot.py` reports this as CLIPPED.
- Contrast measurement gives false positives (around 1.3:1) when the background is a child sprite; confirm on the screenshot.
- Git Bash rewrites arguments containing `/` into Windows paths (`(^|/)Selected` becomes `(^|C:/Program Files/Git/)Selected`). Use `--name` (no slashes) or `MSYS_NO_PATHCONV=1`; in the latter case give the script path as a Windows path too.
- On Windows, `tasklist` may report zero `Unity.exe` processes when the editor is running; use `Get-CimInstance Win32_Process`.
- A stale `.git/index.lock` can remain in a shared working tree. Remove it only after confirming no git process is running, it is 0 bytes, and its timestamp is old.
- If `ui-audit/` or your docs folder is gitignored, share only through deliberate force-adds of the files meant for the team.

## Agents
- `accessibility-specialist` has no Write tool: it reported "written" and produced zero files, and its math was wrong (luminance without linearization). Use general-purpose.
- Parallel agents sharing the Playwright MCP browser collide; use headless Python Playwright.
- Fix requests that arrive after an agent ends its turn are sometimes never processed; check file timestamps and recompute, then send again.
- Agent self-measurements and independent measurements differ because of judging rules (coverage 52% vs. 50%); documents use the independent value.
