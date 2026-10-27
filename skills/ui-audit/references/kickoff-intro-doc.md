# Kickoff: an HTML introduction to the system for your team

Use this when you want a single page that explains the whole loop to planners, artists and engineers: why it exists, how it works, and what it can do - from analysing the existing project, through the template library, to designing new screens, collecting feedback in the review viewer, and applying it.

```
You are a new session. There is no earlier conversation. Communicate in <your language>; code and file names in English.
Work at the Unity project root.

[User request]
"Make an HTML document that introduces our UI audit system: how it analyses the existing project's design system, the template
component list and how things connect, how we build a library with it and use it when adding new content, and the flow from
screen design through the feedback page to applying the feedback. In this order: why we need it, how it works, what it can do."

[Deliverable]
- One self-contained HTML page: <docs folder>/ui-audit-intro/index.html (+ img/ in the same folder).
  No external JS, inline CSS, web fonts from Google Fonts at most. Readers are teammates, planners and artists - explain jargon.
- Section order as requested: 1 Why -> 2 How it works -> 3 What it can do. Then briefly 4 How to start (3 commands)
  and 5 Current limits and next steps.
- Load the frontend-design:frontend-design skill first and follow it. Keep the tone consistent with the explorer
  (ui-audit/catalog/assets/ styles).
- Show the flows as diagrams (inline SVG or HTML/CSS), at least:
  (a) the whole pipeline: Unity project analysis -> library -> new content screen design -> feedback in the review viewer
      -> Claude applies it -> review and close -> move to Unity;
  (b) the states of one feedback item: open -> claimed -> fixed -> closed / reopened.
- Include real screenshots, taken by you with headless Python Playwright into img/ (no Playwright MCP).
  Candidates: catalog index or app-flow, templates list, a template detail page, a screen layout map,
  the review viewer (selection + bottom dock), wireframe vs. mockup.

[Sources - read them; take numbers and names only from here, never invent]
1. Analysis and library: ui-audit/reports/FINAL.md (node catalog, template and screen counts, usage checks, layout maps),
   Docs/ui-design-system/ (INDEX, templates.jsonl, screens.jsonl, skeletons) if it exists.
2. New screen design (wireframe -> kit -> mockup): the ui-wire-skin skill (SKILL.md, README) and your own design tracks
   under ui-audit/design/<screen>/ (kit/components.md maps Unity templates to the mockup kit).
   Include what failed and what you learned, honestly, in the "limits" section.
3. Feedback and applying it: docs/feedback-loop.md of the ui-design-loop repository, ui-audit/feedback/CONTRACT.md
   (section 6 permissions: people open and close, Claude claims and revises, Claude never closes), the ui-feedback skill
   (+ references/template-swap.md: only record a fix when the screen really changed), and one real fix from your log
   (its diff in ui-audit/feedback/revisions/<rev>.diff and before/after shots).

[Screens to capture]
- If a review server is already running (default http://127.0.0.1:8770), use it; do not stop or restart it if another session owns it.
  Otherwise start one on a spare port: python ui-audit/scripts/review_server.py --port <port>.
  Pages: /ui-audit/catalog/index.html, the review viewer /ui-audit/catalog/review.html?screen=<UIType>&stage=mockup.
- Never POST feedback: do not press submit, close or reopen in the viewer (protect the real log). If you need the compose form
  in a screenshot, type into the field without submitting.
- Wait for #rv-zoom-frame[data-ready] before capturing the zoom view.

[Steps]
1. Read the sources -> show the user a table of contents and the key message per section (3-5 lines each) in one message, and get confirmation.
2. After confirmation: screenshots -> HTML -> headless screenshots at 1440 and 1920 wide and at phone width (390) to confirm
   nothing breaks and there is no horizontal scroll.
3. Fact check: compare numbers, file names and commands in the page with the sources once more (report as a table).
4. Report the file path and how to open it, then ask the user whether to (a) publish it as an Artifact, (b) commit it.

[Rules]
- Write only in <docs folder>/ui-audit-intro/ and temporary folders. ui-audit/ code, data and deliverables are read-only
  (other sessions may be writing there).
- Commit or push only with the user's permission. No effort estimates.
```
