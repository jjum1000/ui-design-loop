# Design feedback loop - operations guide

People leave feedback per component on top of wireframe and mockup HTML deliverables; Claude judges and fixes it through a CLI, and every fix is recorded automatically (diff, snapshot, before/after shots). This guide covers running the review server, using the viewer, registering deliverables and sharing the loop with a team.

Source of truth: `ui-audit/feedback/CONTRACT.md` (contract, API, permissions; installed with the toolkit, Korean in v0.1). Claude's procedure: the `ui-feedback` skill.

All commands run from the Unity project root (the folder that contains `ui-audit/`). In v0.1 the viewer UI, generated pages and CLI messages are in Korean.

## Start the server

```bash
python ui-audit/scripts/review_server.py
```
Then open `http://127.0.0.1:8770/ui-audit/catalog/app-flow.html` and click the review link in the design-progress table, or go straight to the viewer (URL below). If your catalog has no app-flow page (the optional `data/app-flow.json` is missing), open `ui-audit/catalog/index.html` or the viewer URL directly.

Change the port: `python ui-audit/scripts/review_server.py --port 8880`

The server serves only `ui-audit/` and `Assets/` under the project root, accepts GET/HEAD for static files, and accepts `POST /api/feedback` and `POST /api/attachments` from its own origin only. Opening the viewer straight from disk (without the server) shows badges and history read-only; the compose form is hidden.

## Team operation - an example setup

A setup that works well for a team: **viewing goes through git, feedback goes to one shared server.**

| Where | What | How |
|---|---|---|
| **Each person's PC** | Browse the catalog (inventory, templates, components, maps, app flow) and the deliverables; design with `/ui-wire-skin` | `git pull`, then open `ui-audit/catalog/index.html` and friends as files (no server needed; sprites load through relative `../../../Assets/` paths, so a Unity checkout shows them) |
| **Team review server** | Leave feedback (one shared log), run `/ui-feedback` | `http://192.0.2.10:8770/ui-audit/catalog/review.html?screen=ShopView&stage=mockup` (example address) |
| **Data owner's PC** | Regenerate design-system data and the catalog | Follow `Docs/ui-design-system/UPDATE.md`, then commit and push the shared data |

- The shared data (catalog HTML, layout JSON, renders, app flow, tokens, GUID index) is listed in `Docs/ui-design-system/UPDATE.md`. Put PNGs and large JSON in Git LFS.
- **Do not leave feedback on a local review server** when a team server exists: the log would live only on that PC and split from the team log (ids are assigned locally, so logs cannot be merged through git).
- Keep the server's checkout current, for example with a scheduled `git pull` (restart the server when its scripts change). Never run `git clean` in that checkout: the log and attachments are untracked and would be deleted.
- Start the shared server with `--host <that machine's LAN IP>`, for example:
  ```bash
  python ui-audit/scripts/review_server.py --host 192.0.2.10 --port 8770
  ```
  Set `"publish": {"team_server": "http://192.0.2.10:8770"}` in `ui-audit/project.json` and rebuild the catalog so that viewers opened from disk link to the shared server. The server binds to that address and adds `http://<host>:<port>` to its allowed origins (127.0.0.1 and localhost stay allowed). `0.0.0.0`, `::` and empty values are refused, because the server could not check the Origin header against an address it does not know. Everyone must open **exactly that IP**; opening it by host name makes POSTs fail with 403.
- The **name field** at the top of the compose form must be filled before posting (remembered per browser). It is self-reported, not authentication: anyone on the network who can reach the server can post. Claims and revisions cannot be made through the server (CLI only).
- **Attachments**: [attach image] in the compose and comment forms, drag and drop onto the form, or paste (Ctrl+V) into the text field. PNG, JPG, GIF, WebP, up to 10 MB each and 6 per event. Attachments stay **on the server's disk only** (`ui-audit/feedback/attachments/`, not in git). Uploads are refused with 507 once the folder exceeds 1 GiB; cleanup is manual.
- Run `/ui-feedback` **in the server's checkout**: claim snapshots and revise diffs must be on the same disk as the log. Commit and push deliverable fixes from there; others pull.
- Install the Claude skills where `/ui-feedback` runs: the `ui-design-loop` plugin, or copy `skills/ui-feedback` and `skills/ui-wire-skin` (its measurement scripts) into `.claude/skills/`.
- When deliverables change, rebuild the dock data: `python ui-audit/scripts/catalog_library.py --build` (keys and crops are rendered headlessly; needs Playwright).

## Bottom dock - component viewer, library, drill-down

Defined in `CONTRACT.md` section 7.
- Select a component in the deliverable and the dock opens below (or use the [dock] button). Pane 1: tree of semantic nodes (`data-area`, `data-template`, `data-variant`, `data-new`; repeats grouped as xN). Pane 2: zoom view + property table + crops of the same key in other states and variants. Pane 3: template card (thumbnail, usage counts, node tree with drill-down into nested templates, kit rows, rules, alternatives).
- Keyboard (dock open, focus outside text fields): up = parent, down = first child, left/right = siblings. The selected node's path is stored in the feedback's `path`.
- Template swap suggestion: [suggest swap] on an alternative in pane 3 fills the form as kind `template` with a chip. **Nothing is saved until you press submit.** Alternatives come from the track kit's component groups (a template without kit rows has no alternatives).
- In a wireframe, keys without a template show the template the default mockup variant uses ("used in mockup: ...").
- Switching variants in the dropdown keeps the selection through `&k=<key>`. The dock height is adjustable and remembered.
- Opened from disk: the tree comes from pre-built key data, the zoom view from crop images, and composing is hidden.

## Using the review viewer

**URL**: `catalog/review.html?screen=<UIType>&stage=<wire|mockup>[&v=<version>][&state=<id>][&fb=<id>]` (without `v`, the stage's default variant).

**Leaving feedback**: click a component -> choose a kind (bug, visual, copy, flow, other) -> write the comment (reference images via [attach image], drag and drop, or paste) -> submit. Existing items can be commented on, closed, or reopened (reason required).

**Display area**:
- Game screen (default): only the `#canvas` 1280x720 safe area, fitted to the panel.
- Whole document: the full deliverable document (union of content bounds).

**Kinds**: bug, visual, copy, flow, other, template swap (only through [suggest swap] in the dock library).

## Item states

| State | Meaning | Next |
|---|---|---|
| `open` | newly opened by a user | claimed (Claude), closed (user) |
| `reopened` | reopened by a user (from fixed or closed) | claimed, closed |
| `claimed` | Claude is working on it (snapshot taken) | fixed (revise), back to open/reopened (release) |
| `fixed` | Claude submitted a fix (diff and shots recorded) | closed (user), reopened (user) |
| `closed` | the user confirmed it | reopened (user) |

## Permissions

**Users (through the server)**: open (new feedback), comment, close, reopen (reason required).

**Claude (through the CLI)**: comment (questions, explanations), claim (group related items; snapshot + before shots), release (unclaim; reason required), revision (apply a fix; diff, after shots, history).

**Claude never closes or reopens** - that is the user's call.

## Claude's side (CLI)

From the project root:
```bash
python ui-audit/scripts/feedback.py list [--screen S] [--status open,reopened] [--json]
python ui-audit/scripts/feedback.py show <id>
python ui-audit/scripts/feedback.py claim <id...>
python ui-audit/scripts/feedback.py release <id...> --reason "reason"
python ui-audit/scripts/feedback.py revise <id...> --summary "summary" [--new-version V] [--no-shots]
python ui-audit/scripts/feedback.py comment <id> "text"
python ui-audit/scripts/feedback.py keys <screen> [--stage wire|mockup] [--version V] [--top 15]
python ui-audit/scripts/feedback.py build
```

- `list`: feedback list (Markdown, or JSON with `--json`); default status filter `open,reopened`
- `show`: full history of one item
- `claim`: claim several items at once (same screen, stage and version only)
- `release`: release a claim (ids of the same claim)
- `revise`: record a fix (diff and before/after shots generated automatically; refused when no file changed)
- `comment`: add a comment (questions, explanations)
- `keys`: `data-area` keys per state plus large elements without a key (where to add keys)
- `build`: regenerate `feedback/state.js` (after log changes, if needed)

`python ui-audit/scripts/feedback.py --selftest` and `python ui-audit/scripts/review_server.py --selftest` run every command against a temporary root (set `UIAUDIT_ROOT` yourself to experiment on a copy; never on the real log).

## Registering deliverables

Maintain `ui-audit/design/registry.json` by hand:

```json
{"version": 1,
 "screens": {
  "ShopView": {"app": "Shop", "label": "Shop", "stages": [
    {"stage": "wire", "version": "r1", "label": "Wireframe round 1", "status": "done",
     "entry": "design/shop/wire.html",
     "files": ["design/shop/wire.html"],
     "states": [
       {"id": "board", "label": "Board", "steps": [{"call": "loadState", "args": ["board"]},
                                                  {"call": "stopTimers", "args": [], "optional": true}]}
     ]},
    {"stage": "mockup", "version": "v2", "label": "Mockup v2", "status": "wip",
     "entry": "design/shop/variant-v2/index.html",
     "files": ["design/shop/variant-v2/*"],
     "states": [{"id": "board", "label": "Board", "steps": [{"call": "loadState", "args": ["board"]}]}]}
  ]}
 }}
```
- Screen keys are screen type names (the same keys as `screens` in `data/app-flow.json` when the project has that file). `stage` is `wire` or `mockup`; a stage may have several variants, unique by `(stage, version)`; the first one is the default. `status` is `wip`, `done` or `confirmed`.
- `entry` = the HTML the viewer opens; `files` = the edit scope for claims and diffs (paths or `*` globs, no `**`); `states[].steps` = global functions the viewer calls in order (no eval).

After registering:
```bash
python ui-audit/scripts/feedback.py build
python ui-audit/scripts/build_catalog.py --templates
python ui-audit/scripts/validate.py --rename ui-audit/catalog
```
In a checkout without the full data, use instead: `python ui-audit/scripts/catalog_library.py --build`, then `python -c "import sys; sys.path.insert(0,'ui-audit/scripts'); import build_catalog as B, catalog_review as R; R.build_review(B, 'ui-audit/catalog')"`, then `python ui-audit/scripts/validate.py --rename ui-audit/catalog`.

**Deliverable requirements**:
- `data-area="lowercase-hyphen"` on every semantic unit
- repeated units: the same key + `data-idx`
- `#canvas` 1280x720 (the same page contract the `ui-wire-skin` measurement scripts use)

## Files

| Path | Role |
|---|---|
| `feedback/log.jsonl` | append-only event log (never edit by hand) |
| `feedback/state.js` | derived: `window.UIA_FEEDBACK` (regenerated automatically) |
| `feedback/snap/<claim>/` | snapshot at claim time |
| `feedback/revisions/<rev>.diff` | fix diff |
| `feedback/revisions/<rev>/*.png` | component shots after the fix |
| `feedback/attachments/<hash>.<ext>` | user attachments (server upload only, immutable, not in git) |
| `design/registry.json` | deliverable registry (maintained by hand) |
