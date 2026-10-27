# Kickoff: UX review of the explorer and the review viewer

Use this when the catalog, layout maps and review viewer are working and you want to check their usability: how templates, their usage in screens, look-alike templates and the selected-template marker in the review viewer are exposed, and what to improve. The session verifies and proposes; it does not change page code.

```
You are a new session. There is no earlier conversation. Communicate in <your language>; code and file names in English.
Work at the Unity project root.

[User request]
"The audit and layout evaluation system is done. I want to sort out the UX of the component list and the map/flow pages and how
things are exposed: the template library and its links to the screens that use it, similar-template lists, and how the selected
template is marked on the mockup feedback page (it works, but its usability needs improvement). Verify the UX of the current pages
and propose a direction."

This is a verification and proposal session. Do not edit page code (ui-audit/catalog/assets/*, scripts/catalog_*.py, build_catalog.py).
Produce the findings and improvement directions as a document and batch the decisions the user must make into one message.
Implementation is a separate track after the user picks a direction.

[Read first]
1. ui-audit/reports/FINAL.md - template and layout-map numbers, what the explorer is and where the data lives.
2. docs/feedback-loop.md of the ui-design-loop repository and ui-audit/feedback/CONTRACT.md section 7 - the review viewer's
   bottom dock (tree drill-down, zoom view, template library, swap suggestions).

[Pages to verify (user wording -> page under ui-audit/catalog/)]
| User wording | Pages |
|---|---|
| component list | components.html, templates.html, templates/<slug>.html |
| map/flow | app-flow.html (if the project has data/app-flow.json), map.html, screens.html, screens/<screen>.html, scenes.html |
| template library | templates.html + template detail + the review viewer dock's library card |
| links to screens that use it | usage (screens, scenes) links on the template detail, "used by" in the dock library |
| similar-template list | look-alikes and variants on the template detail, alternatives in the dock library (kit groups) |
| selected template marker on the mockup page | review.html: selection highlight on the deliverable, the right panel, dock panes 1-3 |

[How to look]
- Server: if a review server is running (default http://127.0.0.1:8770) and another session owns it, do not stop or restart it.
  Otherwise start one on a spare port: python ui-audit/scripts/review_server.py --port <port>.
- Never POST feedback: do not press submit, close or reopen in the viewer (the real log is ui-audit/feedback/log.jsonl).
  To test the compose flow, intercept POST /api/feedback with page.route, or use a copy with UIAUDIT_ROOT=<temp root>.
- Screenshots and measurements with headless Python Playwright (no Playwright MCP). Viewports 1920x1080, 1440x900, 1280x800.
  Wait for #rv-zoom-frame[data-ready] before capturing the zoom view. Outputs go to ui-audit/design/ux-review/ (new folder).

[Method (minimum)]
1. Task walkthroughs (per task: start page -> goal, click count, dead ends, confusing labels, with screenshot evidence):
   - T1 "What is the primary button template and which screens and scenes use it?" (component list -> template -> usage)
   - T2 "Which templates make up <a representative screen>, and what is similar to them?" (map/flow -> screen -> template -> look-alikes)
   - T3 "In the <screen> mockup, which template does <an element> use, what are the alternatives, and how do I suggest a swap?"
     (flow/design progress -> review viewer -> select -> dock)
   - T4 "Can I tell at a glance which template and variant the selected element in a mockup is, and what it maps to in the wireframe?"
     (selection marker in the review viewer - the area the user called out)
   - T5 "Starting from the template library, get to the mockups/screens that use the template" (reverse link - check whether it exists)
2. Heuristic review (Nielsen's 10 + information scent, navigation consistency, terminology consistency): findings per page with
   severity (high/medium/low) and evidence (screenshot path, element).
3. Exposure comparison: how the same information (template, usage, look-alikes, selection marker) appears on different pages,
   as a table - duplicates, inconsistencies, broken links.
4. If useful, compare with reference patterns (Storybook, Figma component panel, design-system documentation sites), but propose
   within the explorer's existing shell and tokens (no new design language).

[Deliverables]
- ui-audit/design/ux-review/<date>-ux-review.md: 1 summary (the 3-5 biggest problems), 2 per-task results table (clicks, dead ends,
  evidence), 3 heuristic findings per page (severity, evidence), 4 exposure comparison table, 5 improvement directions per area
  (component list, map/flow, template library + screen links + look-alikes, review viewer selection marker): 2-3 options each,
  a recommendation, rationale and implementation scope (which files, roughly what), 6 the list of decisions for the user.
- Screenshots in ui-audit/design/ux-review/shots/. If visualising a proposal helps, at most 1-2 static HTML wireframes in
  ui-audit/design/ux-review/proposals/ - do not touch existing page code.
- No effort estimates (the axes are order, dependencies, impact).

[Progress and report]
- Read, walk, capture -> interim report (the 3 biggest problems with evidence) -> document -> one message with the user's decisions.
- The working tree may be shared; write nothing outside ui-audit/design/ux-review/.
- Do not commit (ask the user at the end if needed).
```
