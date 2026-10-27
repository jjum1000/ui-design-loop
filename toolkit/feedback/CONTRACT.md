# Contract - design-stage feedback loop

> Source of truth. Implementation agents do not change this document. If you find a contradiction or a gap, do not implement around it; report it.
> All paths are **relative to the ui-audit root, with `/` separators** (for example `design/shop/variant-v2/app.js`). Scripts use `common.ROOT` as the root (overridable with the environment variable `UIAUDIT_ROOT`); self-tests run in a temporary root.
> In v0.1, error messages returned by the server and printed by the CLI are Korean.

## 1. File layout

| Path | Written by | Content |
|---|---|---|
| `design/registry.json` | people (orchestrator) | deliverable registry (section 2) |
| `schemas/feedback-event.schema.json` | toolkit | event schema (the `validate.py` subset: type, enum, required, properties, additionalProperties, items, minItems, maxItems, minLength, pattern, anyOf - when `anyOf` is present, other keys at the same level are ignored) |
| `feedback/log.jsonl` | only `feedback_core.append()` | event log, one line = one event (JSON, UTF-8, `ensure_ascii=False`), **append-only** |
| `feedback/state.js` | only `feedback_core` | derived: `window.UIA_FEEDBACK = {...};` (4.3) |
| `feedback/.lock` | `feedback_core` | inter-process lock file |
| `feedback/snap/<claim>/` | `feedback.py claim` | snapshot at claim time: `files/<ui-audit relative path>` copies of the originals + `before/<id>.png` (component crop shot) |
| `feedback/revisions/<rev>.diff` | `feedback.py revise` | unified diff snapshot <-> current (path headers `a/<relative path>` `b/<relative path>`) |
| `feedback/revisions/<rev>/after-<id>.png` | `feedback.py revise` | component crop shot after the fix (the before shot is referenced by its snap path) |
| `feedback/attachments/<first 20 chars of sha256>.<ext>` | only the `review_server.py` upload API | user attachment images (revision F, section 9). Content-addressed, immutable, not shared through git (same disk as the log) |
| `feedback/fixtures/` | toolkit | `sample-log.jsonl`, `sample-registry.json`, `expected-state.json`, `reject-cases.json` |
| `feedback/tests/` | toolkit | headless tests |
| `scripts/feedback_core.py` | toolkit | registry and log reading, validation, folding, append, state.js rendering |
| `scripts/review_server.py` | toolkit | local server |
| `scripts/feedback.py` | toolkit | Claude-side CLI |
| `scripts/catalog_review.py` | toolkit | `build_review(B, out)` -> `catalog/review.html.tmp` |
| `catalog/assets/review.js`, `review.css`, `badges.js` | toolkit | **hand-maintained sources** (`catalog_assets.py` does not overwrite them) |
| `scripts/catalog_flow_badges.py` | toolkit | app-flow badges and the "design progress" HTML fragment |
| `scripts/catalog_library.py`, `catalog/library/` | toolkit (revision L) | generator and output of the bottom-dock library and key data (7.4) |
| `feedback/fixtures/sample-template-index.json`, `sample-lib-index.json` | toolkit (revision L) | template index (at `data/template-index.json`) and library index (at `catalog/library/index.json`) for self-test temp roots |

## 2. Deliverable registry `design/registry.json`

```json
{"version": 1,
 "screens": {
  "ShopView": {"app": "Shop", "label": "Shop", "stages": [
    {"stage": "wire", "version": "r1", "label": "Wireframe round 1", "status": "done",
     "entry": "design/shop/wire.html", "files": ["design/shop/wire.html"],
     "states": [{"id": "board", "label": "Board", "steps": [{"call": "loadState", "args": ["mixed"]}]}, ...]}
  ]}}}
```
- `screens` keys = screen type names (the same as the `screens` keys of `data/app-flow.json`, when the project has that file). `app` = `apps[].contentsType` of the app flow.
- `stage` is `wire | mockup`. **A stage may appear several times (variants)**; `(stage, version)` is unique within a screen. The **first entry of a stage is the default variant** (used when the viewer opens without `v` and when an open event has no version). (Revision V - variant dropdown.) `version` = short string (`^[a-z0-9][a-z0-9-]*$`).
- `status` is `wip | done | confirmed`. "Finished mockup" = a `mockup` entry with `done|confirmed`.
- `entry` = the HTML the viewer iframe opens. `files` = edit scope (snapshot and diff targets) - file paths or `*` globs (`fnmatch`, no subfolders, no `**`). Binary files (png, ...) appear in the diff only as a "binary change" line.
- `states[]` = screen states inside the deliverable. `steps` is a list of global function calls in the iframe: `{"call": "<function name on window>", "args": [JSON values...], "optional": true?}`, run in order as `contentWindow[call](...args)`. A missing function is skipped when `optional`, otherwise the state entry is marked failed. **No eval.** The first state is the default state.
- Viewer and CLI shots call `stopTimers` (optional) after entering a state to stop timers (put it in the registry steps).

## 3. Events (one line of log.jsonl)

Common fields (required on every event): `type`, `at` (ISO 8601, seconds, with time zone - `common.now_iso()`), `by` in `user | claude`.
Field names exactly as in the table. Keys not in the table are rejected (schema `additionalProperties: false`).

| type | by | required | optional | effect |
|---|---|---|---|---|
| `open` | user | `id` `screen` `stage` `version` `kind` `text` `component` | `idx` `template` `selector` `bbox` `state` `path` `suggest` `attachments` `author` | new feedback, status `open` (`path`/`suggest` = revision L, 7.1; `attachments` = revision F, 9.2; `author` = revision A, 8.1) |
| `comment` | user, claude | `id` `text` | `attachments` (user only, 9.2), `author` (user only) | status unchanged |
| `claim` | claude | `ids` (1 or more) `claim` `snap` | - | each id: `open`/`reopened` -> `claimed` |
| `release` | claude | `ids` `claim` `text` (reason) | - | each id: `claimed` -> the status before the claim (`open` or `reopened`) |
| `revision` | claude | `rev` `ids` `claim` `files` (1 or more) `diff` `summary` `shots` | `newVersion` | each id: `claimed` -> `fixed` |
| `close` | user | `id` | `text`, `author` | any status other than `closed` -> `closed` |
| `reopen` | user | `id` `text` (reason) | `author` | `fixed`/`closed` -> `reopened` |

Field definitions:
- `id` = `fb-` + a zero-padded serial of at least 4 digits (`fb-0001`). `claim` = `cl-0001`. `rev` = `rev-0001`. All three are **issued by append from the log** (current max + 1), and the `snap` and `diff` paths are filled with the issued ids. Caller-supplied `id` (open), `claim` (claim), `rev`, `snap` and `diff` are overwritten (how the CLI decides folder names first: `next_id` in 4.2).
- `screen` = a registry `screens` key. `stage` = a stage registered for that screen. `version` = the variant the feedback is on. If the client sends it, that `(stage, version)` must be registered (else 400); if not, append fills in that stage's default variant (revision V).
- `kind` in `bug | visual | copy | flow | other | template` (shown as bug, visual, copy, flow, other, template swap). `template` = revision L - requires `suggest` (7.1).
- `text` = 1-4000 characters (at least 1 after trimming). Over 4000 is rejected (in code, not the schema).
- `component` = a `data-area` value (`^[a-z0-9][a-z0-9-]*$`) or `null` (no key). If `null`, `selector` and `bbox` are required.
- `idx` = a `data-idx` value (string, `^[A-Za-z0-9][A-Za-z0-9_.-]*$`) or absent. `template` = the nearest `data-template` value or absent.
- `selector` = a CSS selector string (made by the viewer, 1-500 characters). `bbox` = `{"x","y","w","h"}` numbers in **deliverable document coordinates** (iframe document, CSS px before scaling).
- `state` = a registry `states[].id`, or absent.
- `ids` = an array of existing feedback ids (no duplicates).
- `snap` = `feedback/snap/<claim>`. `diff` = `feedback/revisions/<rev>.diff`. `files` = relative paths of changed files (inside the registry `files`). `snap`, `diff`, `files` and `shots[].before/after` must not contain `:` or `\` (blocks schemes and drive letters).
- `shots` = `[{"id": "fb-0001", "before": "<path>|null", "after": "<path>|null"}]` (null when a shot failed; the array itself is required - empty with `--no-shots`).
- `summary` = 1-2000 characters. `newVersion` = a version string (recorded only; the registry is not updated).

### 3.1 Validation rules (append rejects = exception, log unchanged)
1. Schema violation (unknown type, key or format).
2. `by` not allowed for that type (for example `close` by `claude`, `revision` by `user`).
3. Unknown `screen` / a `stage` not on that screen / a `version` not in that stage / a `state` not in **that variant's** `states` (when `state` is present).
4. Unknown `id` / `ids`.
5. Impossible state transition (the starting status in the "effect" column does not match). For `release` and `revision`, every id must be claimed by **the same `claim`** (the unit of grouping is the claim).
6. Length limits (text 4000, summary 2000, selector 500, author 40, attachment name 120), whitespace-only text/summary/author/name, `author` or `attachments` on a `by=claude` event.
7. (Revision L) `path` / `suggest` rule violations - the code checks listed in 7.1.

Check order = after filling the issued fields (`id`, `claim`, `rev`, `snap`, `diff`, and `version` for open) and `at`/`by`, in the numbered order above. The first violation decides the status: 1, 2, 3, 4, 6, 7 -> 400; 5 -> 409. The reference reject cases are `fixtures/reject-cases.json` (after appending the whole sample log, each case must be rejected with its `expect` status).

### 3.2 Folding state
- status in `open | reopened | claimed | fixed | closed`. "Open" = `open|reopened`, "awaiting review" = `fixed`.
- Log line order = history order. Folding is deterministic (same log -> same result, including key order - compared with `json.dumps(sort_keys=True)`).
- If the log contains a line that fails validation, folding **raises with the line number** (it never skips silently).

## 4. Interfaces

### 4.1 Folded state (fold result, the shape of `expected-state.json`)
```json
{"items": {"fb-0001": {
    "id": "fb-0001", "screen": "...", "stage": "...", "version": "...", "kind": "...", "text": "...",
    "component": "item-row|null", "idx": null, "template": null, "selector": null, "bbox": null, "state": null,
    "path": null, "suggest": null,
    "status": "fixed", "claim": null, "openedAt": "<at of open>", "updatedAt": "<at of the last event about this id>",
    "revisions": ["rev-0001"], "history": [<raw events about this id, in log order, including open>]}},
 "revisions": {"rev-0001": <raw revision event>},
 "counts": {"ShopView": {"wire": {"open": 0, "reopened": 0, "claimed": 0, "fixed": 0, "closed": 0}, "mockup": {...}}},
 "versionCounts": {"ShopView": {"wire": {"r1": {"open": 0, ...}}, "mockup": {...}}}}
```
- Every item key is always present (`null` when absent). `claim` = the claim id while status is `claimed`, else null. `revisions` = the revs that include this id (log order). `author` and `attachments` stay inside `history` events; they do not add item keys.
- `counts` = 5 statuses, zero-filled, for **every** screen and stage in the registry (summed over the stage's variants).
- `versionCounts` = `{screen: {stage: {version: {5 statuses}}}}`, zero-filled for every registered `(stage, version)`. Feedback on a variant that was removed from the registry is counted in `counts`, and its version key is added to `versionCounts` (revision V).

### 4.2 `scripts/feedback_core.py` - public functions other modules import
| Function | Description |
|---|---|
| `load_registry() -> dict` | `design/registry.json` |
| `read_log() -> list[dict]` | all log lines ([] if none) |
| `fold(events, registry) -> dict` | 4.1. Invalid line -> `FeedbackError("log.jsonl:<line>: <reason>")` |
| `check(event, state, registry) -> list[str]` | 3.1 rule violations (empty = pass). Issued fields are assumed filled |
| `append(event, by) -> dict` | lock -> read and fold the log -> force `by` and `at` -> issue id/claim/rev -> fill `version` of an open from the registry -> `check` -> append one line (flush + fsync) -> regenerate `state.js` -> unlock. Returns the stored event. On failure `FeedbackError` (log unchanged) |
| `next_id(prefix, events) -> str` | next id for `prefix` in `fb`, `cl`, `rev`. The CLI uses it inside `with lock():` to name the snapshot folder, then appends inside the same lock (the issued value is guaranteed equal) |
| `lock()` | context manager. Inter-process exclusive lock (`feedback/.lock`, must work on Windows), 10 s timeout -> `FeedbackError(status=503)`. **Re-entrant within one process** (append does not lock again if already held) |
| `render_state_js(state, registry) -> str` | `window.UIA_FEEDBACK = <JSON>;\n` - JSON = `{"generatedAt", "registry", "items", "revisions", "counts", "versionCounts"}`. `</` is escaped as `<\/` |
| `write_state_js()` | log -> fold -> atomic write of `feedback/state.js` (.tmp -> os.replace) |
| `FeedbackError(Exception)` | `.status`: 400 (validation), 409 (state transition), 503 (lock timeout) |

### 4.3 Server API (`scripts/review_server.py`)
- Binds `127.0.0.1:8770` (change with `--port`; shared hosting with `--host`, 8.3). Static root = **the client repository** (the parent of `ui-audit`). Allowed static prefixes: `ui-audit/` and `Assets/` only, everything else 403. `..`, absolute paths, drive letters and backslash escapes are 403. GET/HEAD only for static files.
- `POST /api/feedback` - JSON body (`Content-Type: application/json` required, else 415). Max 64 KiB (413 above). If an `Origin` header is present it must be `http://127.0.0.1:<port>` or `http://localhost:<port>` (or the `--host` origin, 8.3), else 403. Allowed types: `open | comment | close | reopen` only (others 403). The server forces `by=user` and `at`; `id` (open) and `version` come from issuing / the registry. Responses:
  - 201 `{"ok": true, "event": <stored event>, "item": <folded item>}`
  - 400/409 `{"ok": false, "error": "<message>"}` (the FeedbackError status), and 413, 415, 403 in the same shape.
- `GET /api/feedback[?screen=X]` - 200, the same JSON as `state.js` (`generatedAt`, `registry`, `items`, `revisions`, `counts`, `versionCounts`). With `screen`, items, revisions, counts and versionCounts are limited to that screen.
- No CORS headers. Cache: `/api/*` and `feedback/state.js` are `Cache-Control: no-store`.
- Run: `python ui-audit/scripts/review_server.py` -> `http://127.0.0.1:8770/ui-audit/catalog/app-flow.html`.

### 4.4 CLI (`scripts/feedback.py`) - every write is `by=claude`
| Command | Behaviour |
|---|---|
| `list [--screen S] [--status open,reopened] [--json]` | default status filter = `open,reopened`. Markdown: per item id, status, kind, screen/stage/version, state, component (+idx/template), text, deliverable entry path, **source location** (`path:line` grep hits of `data-area="<component>"` or `'<component>'`/`"<component>"` inside the registry `files`), comments, previous revision summaries; (revision L) lines in the 7.3 format when `path`/`suggest` exist; (revision A) the author; (revision F) attachments (9.5) |
| `show <id>` | the full history of one item |
| `claim <id...>` | claim ids -> copy the registry `files` scope into `feedback/snap/<claim>/files/` + a before crop shot per id -> `claim` event. Refuses mixing different screens, stages or **variants (versions)**. Target registry entry = the feedback's `(screen, stage, version)` (revision V - claim is refused if that variant was removed from the registry) |
| `release <id...> --reason "..."` | release a claim (ids of the same claim) -> `release` event. Snapshots are kept |
| `revise <id...> --summary "..." [--new-version V] [--no-shots]` | ids of the same claim. diff snapshot <-> current (**refused** when 0 files changed) -> `revisions/<rev>.diff` -> after crop shots -> `revision` event |
| `comment <id> "text"` | `comment` event |
| `keys <screen> [--stage wire\|mockup] [--version V] [--top 15]` | (revision V: default = every registered `(stage, version)`) renders every state headlessly -> per state, the `data-area` list (count, number of idx) + the top N large elements without a key (by area, inside `#canvas`, whose nearest `[data-area]` ancestor is at screen-root level), as Markdown |
| `build` | regenerate `state.js` |
| `--selftest` | runs every command on a copy in a temp root |

Crop shot rule: viewport 1920x1080, open `entry` from disk (static HTML, no server needed), run the feedback's `state` steps (or the first state) -> first `[data-area="<component>"]` (+`[data-idx]`), else `selector`, else `bbox` -> PNG crop with 16 px margin on each side. On failure record null (the command continues).

### 4.5 Viewer URL and behaviour
- `catalog/review.html?screen=<UIType>&stage=<wire|mockup>[&v=<version>][&state=<id>][&fb=<id>]`. Without `v`, the stage's default variant (revision V).
- Variant dropdown (revision V): one stage tab per stage (label = the variant being viewed, else the default variant). If the stage has 2 or more variants, a `<select>` in or next to the tab picks the variant (label, version, status, open count) and navigates to `review.html?screen=&stage=&v=`. Current target = `(stage, version)`; the thread, component list and composing apply only to it, and open POSTs include `version`. Feedback on another stage **or another variant of the same stage** is shown greyed as "other stage/variant (reference)". If the `fb` item is on another `(stage, version)`, it is not selected; a link to that variant is shown instead.
- Data: when served, `GET /api/feedback?screen=` (GET again after posting); opened from disk, `window.UIA_FEEDBACK` from `<script src="../feedback/state.js">` (read-only: the compose form is hidden and a hint to start `python ui-audit/scripts/review_server.py` is shown; if `project.json` `publish.team_server` is set, a link to the team server is shown instead).
- iframe src = `../` + the registry `entry` of the current `(stage, version)` (ui-audit relative -> relative to catalog). Component selection: the nearest `[data-area]` of the click point -> else `[data-template]` (component=null, template recorded, "no key") -> else selector + bbox ("no key").
- Tabs for the other stages of the same screen. Feedback on non-current stages is shown greyed for reference (not carried over).
- Display range: the iframe document width (1920) stays as is; only the **content bounds** of visible elements (union in document coordinates) are shown. "Fit" fits that width, and "100%" also hides margins outside the bounds. Re-measured when states change or re-render. Recorded coordinates (bbox) remain document coordinates before scaling and cropping.
- Display mode: [game screen | whole document], default game screen. Game screen = only the deliverable's `#canvas` (the 1280x720 safe area - the same contract as `shoot.py`), and "fit" makes that area fit the panel width and height. Without `#canvas` or DOM access, whole-document (content bounds) mode. The chosen mode is remembered in localStorage (works even if storage fails). Recorded coordinates are document coordinates regardless of mode.
- All stored text is inserted with `textContent` (never innerHTML), including strings from the library and key data (7.4).
- (Revision L) Bottom dock, drill-down and `path`/`suggest` composing: 7.5. URLs gain `&k=<data-area>` (keeps the selection).

### 4.6 App-flow badges
- For screens in the registry, badges on screen cards and app icons: per stage, e.g. `wire r1 · mockup v2 confirmed`, plus the open count (`open+reopened`) and the awaiting-review count (`fixed`). Numbers are filled at runtime from `window.UIA_FEEDBACK.counts`. Without state.js, the numbers show `—`.
- A "design progress" table at the top of the app flow: screen, wire (version, status), mockup (version, status), open, awaiting review, review viewer link.
- Revision V: the stage cells of badges and the table show the **default variant** (the stage's first entry), with `+N variants` when there are 2 or more. Numbers are the stage totals (`counts`). Review links point to the default variant (no `v`).

## 5. Component key convention (`data-area`)
- One `data-area="<lowercase-hyphen>"` per semantic unit. Unique within the screen, or for repeated units the same key + `data-idx="<serial or stable id>"`.
- Keys may change between stages (wire -> mockup); feedback is anchored by `stage` and `version`.
- When feedback anchored by selector (no key) accumulates, `feedback.py keys` reports what to add keys to.

## 6. Permission boundary
- Users (through the server): open, comment, close, reopen. **Claude never closes or reopens.**
- Claude (through the CLI): comment, claim, release, revision. Deliverable edits only within the registry `files`.
- The server writes only user events (a page cannot pretend to be Claude). The CLI writes only claude events.

## 7. Revision L - bottom dock, drill-down, template swap suggestions

> **Existing logs stay valid** (only fields and a kind value were added). Folded items gain the keys `path` and `suggest`; removing those two keys (all `null`) from the fold of a pre-revision-L log gives a byte-identical result to the earlier fold (`json.dumps(sort_keys=True)`).

### 7.1 New optional fields of `open`
- `path` = the chain of **semantic nodes** (7.5) in the deliverable, from outside to the selected node (inclusive). 1-12 items. Each item = `{"area"?, "template"?, "variant"?, "idx"?, "selector"?}` (other keys rejected).
  - `area` = `data-area` value (same pattern as component), `template` = the element's own `data-template` (1-200 chars), `variant` = its own `data-variant` (1-200 chars; the viewer truncates longer values to 200), `idx` = its own `data-idx` (idx pattern), `selector` = the element's CSS selector (1-500 chars).
  - Every item has at least one of `area`, `template`, `selector` (schema anyOf). The viewer **puts a selector on every item** (so Claude can find the exact place).
  - 13 or more items are rejected; the viewer drops outer items and sends the inner 12.
  - If `component` is not null, some item's `area` must equal component.
  - When `path` is present, the top-level `selector`, `bbox` and `template` refer to the **last path node (the selected node)**. `template` = the selected node's own data-template, else the nearest data-template between the selected node and the component (existing rule). `component` and `idx` = the selected node itself or its nearest `data-area` ancestor and its `data-idx`.
- `suggest` = `{"template": "<slug>", "variant"?: "<string 1-200 chars>"}` (other keys rejected) - the suggestion to swap to this template (and variant).
  - `template` matches the slug pattern `^[a-z0-9][a-z0-9_.-]*$` and **must exist in the template index** (the `templates` array of `data/template-index.json`). Without the index file, an open with `suggest` is rejected (template index missing).
  - `kind=template` requires `suggest`. Any other kind forbids `suggest`.
- Code checks (3.1 rule 7, all 400): path length 1-12, item string limits (template and variant 200, selector 500), component <-> path area, suggest/kind combination, slug existence. (The schema enforces `maxItems: 12` but not string lengths; those are checked in code.)
- Fixtures: lines of `sample-log.jsonl` with a 2-level path and with kind=template + suggest, the revision-L cases in `reject-cases.json`, `sample-template-index.json` (copied to `data/template-index.json` in self-test temp roots), `sample-lib-index.json` (copied to `catalog/library/index.json`), and `expected-state.json`.

### 7.2 Server and core
- The server's allowed types are unchanged (`open|comment|close|reopen`). `path` and `suggest` in an open body are passed to the core as is; the core's `check`/`append` validates them.
- The core reads the template index from `C.p("data", "template-index.json")` (on every append, or with an mtime cache).

### 7.3 `feedback.py list` digest (revision-L lines)
If `path` exists (the labels are printed in Korean in v0.1: `경로` = path):
```
- 경로: item-row[listitemunit · shop-row] › thumbnailitemunit[ShopItemSlotUnit]
```
Item label = `area`, else `template`, else `selector:<first 40 chars>`. Brackets = (template, if area is the label), variant, `#idx` - whichever exist, separated by ` · `. No brackets if there is nothing to put in them.
If `suggest` exists (`교체 제안` = swap suggestion):
```
- 교체 제안: thumbnailitemunit → thumbnailemptyunit (variant: X) · 키트: Thumbnails/Empty slot `(snippet)`
```
Left = the current template (`template`, else the template of the last path item, else `—`). `(variant: …)` only when suggest.variant exists. Kit (`키트`) = one `group/element \`kit class\`` per row of `templates[<suggested slug>].kit` in `catalog/library/index.json` (separated by `; `). If that file is missing: `키트 정보 없음(라이브러리 미빌드)` (kit info missing - library not built); if there are no rows: `키트에 없음` (not in kit). `--json` prints the item as is (including path and suggest).

### 7.4 Library data (`catalog/library/`, generated, static, works when opened from disk)
All path values are **relative to the ui-audit root** (the viewer prefixes `../`). JSON with `ensure_ascii=False`; inside JS files `</` -> `<\/`. Files are written atomically (`.tmp` -> `os.replace`).

**`index.js`** = `window.UIA_LIB_INDEX = <JSON>;`, **`index.json`** = the same JSON (for the Python CLI)
```json
{"generatedAt": "...", "templates": {"<slug>": {
   "name": "ListItemUnit", "thumb": "previews/layout/template/listitemunit.thumb.png|null",
   "usage": 4, "screens": 1, "tier": "atom|composite|null", "kind": "...|null",
   "page": "catalog/templates/<slug>.html|null", "layout": true,
   "groups": ["Thumbnails"], "kit": [{"group": "Thumbnails", "element": "Empty slot", "kitClass": "(snippet)"}],
   "alts": ["<slug>", "..."]}},
 "groups": {"<group>": ["<slug>", "..."]}}
```
- `templates` = every entry of `templates` in `data/template-index.json`. name, usage (`usageTotal`), screens (length of `screens`), tier and kind come from `data/templates/<slug>.json` (if missing: name=slug, numbers 0, the rest null). thumb = `previews/layout/template/<slug>.thumb.png` if it exists, else the `thumbnail` of `data/templates/<slug>.json` (if that file exists), else null. `layout` = `data/layout/template/<slug>.json` exists.
- Kit = the first mapping table in the kit's `components.md` (the kit folder is project.json `design.kit_dir`, default `design/kit`): 7 columns - group, element, mockup class/file, Unity template slug/source, usage/screen counts, 9-slice, notes. Only backtick tokens of the slug column that exist in the template index count as slugs (sprite paths and "none" are excluded). One slug may appear in several rows.
- `groups[group]` = union of the slugs of that group's rows, sorted by `usage` descending, then slug ascending. `alts` = union of the slugs of every group the template belongs to, minus itself, same order. Without groups: `[]` (no alternatives - never invent guessed alternatives).

**`<slug>.js`** = `window.UIA_LIB = window.UIA_LIB || {}; window.UIA_LIB["<slug>"] = <JSON>;` (all slugs of the index; slugs without layout have `nodes: []`)
```json
{"slug": "...", "name": "...", "path": "<prefab path>", "size": {"w": 724, "h": 140},
 "nodes": [{"id": "b0", "name": "ListItemUnit", "path": "ListItemUnit", "depth": 0,
            "x": 0, "y": 0, "w": 724, "h": 138, "template": "<nested slug>|null", "active": true}],
 "truncated": null,
 "kit": [{"group": "", "element": "", "kitClass": "", "slugs": [], "usage": "<raw usage cell>", "slice": "<raw 9-slice cell>", "note": "<raw notes cell>"}],
 "rules": [{"file": "design/kit/rules.md", "line": 47, "text": "<that line, max 300 chars>"}],
 "screens": [{"slug": "shopview", "page": "catalog/screens/shopview.html|null"}]}
```
- nodes = the `boxes` of `data/layout/template/<slug>.json` in order, coordinates rounded to integers. `template` = the box's nested template slug (only if in the index, else null).
- `rules` = lines of the kit's `rules.md` that mention the slug in backticks or on a word boundary, at most 8. `screens` = the first 8 `screens` of `data/templates/<slug>.json`; page only if the file exists.
- **Size limit 512 KiB per file.** Above it, the deepest nodes are dropped until it fits, and `truncated = {"kept": n, "dropped": m, "maxDepth": d}`. The generator prints file count, total size, the largest file (name, size) and the truncated slugs.

**`keys-<Screen>.js`** = `window.UIA_LIB_KEYS = window.UIA_LIB_KEYS || {}; window.UIA_LIB_KEYS["<Screen>"] = <JSON>;` (one per registry screen)
```json
{"screen": "ShopView", "generatedAt": "...",
 "targets": {"wire/r1": {"entry": "design/shop/wire.html",
    "states": {"board": {"error": null, "keys": {"header-title": {
        "template": "title-plate|null", "variant": null, "new": null, "count": 1, "idx": [],
        "parent": "<nearest data-area ancestor key>|null", "bbox": {"x": 0, "y": 0, "w": 0, "h": 0},
        "crop": "catalog/library/crops/ShopView/wire-r1/board/header-title.png|null"}}}},
    "src": {"header-title": ["design/shop/wire.html:123"]}}},
 "keymap": {"source": "design/shop/keymap.json|null", "map": {"<wire key>": "<mockup key>"}},
 "mockupUse": {"wire/r1": {"header-title": {"version": "v2", "state": "board", "area": "header-title",
                                             "template": "title-plate", "variant": null, "new": null}}}}
```
- Renders every registered `(stage, version)` x every state headlessly (1920x1080, from disk, same entry and `stopTimers` rules as the 4.4 crop shots). A failed state entry is recorded as an `error` string and rendering continues.
- Keys = visible (size > 0) `[data-area]`. For repeated keys, the attributes, bbox and crop of the first visible element; `count` = number visible, `idx` = data-idx values (max 50). `template`/`variant`/`new` = the element's own attributes.
- Crop = document-coordinate bbox with 8 px margin on each side (clipped to the document), scaled so the long side is at most 320 px (`crops/<Screen>/<stage>-<version>/<state>/<area>.png`). null for size 0.
- `src` = the same grep rule as the 4.4 `list` source location (inside the registry `files`), at most 5 per key.
- `keymap` = `keymap.json` in the folder of the screen's first registry entry (for example `design/shop/keymap.json`, format `{"map": {...}}`); if missing, `source: null, map: {}`.
- `mockupUse[wire target][wire key]` = the attributes of the first matching key (`map[key]` if present, else the same key) found in the states (registry order) of the **default mockup variant** (the first mockup entry in the registry). If not found, the key is omitted.
- Generator: `python ui-audit/scripts/catalog_library.py --build [--screen S] [--no-keys]`, `--selftest` (temp root).

### 7.5 Viewer bottom dock
**Semantic node** = an element with any of `data-area`, `data-template`, `data-variant`, `data-new` (visible only). A node's children = its nearest semantic descendants (wrappers are skipped). Tree root = the document `body` (including modals outside `#canvas`); the first breadcrumb item is "screen".
- Grouping repeats: 2 or more siblings under the same parent with the same `(area, template, variant)` and an area or template become a group node "xN"; expanding shows instances (label = `data-idx` or `#n`). Selecting the group node selects its first instance.
- Node label = area -> template -> `new element: <first 24 chars of data-new>`. Clicking a keyless element in the deliverable (existing selector + bbox fallback) temporarily attaches a grey "no key" node under the nearest semantic ancestor.
- Click selection in the deliverable follows 4.5 (nearest data-area -> data-template -> selector). Selecting in the tree makes that node the selected node. Either way, `path` (7.1) is computed and put into the open.
- Highlight: parent = dashed, current = solid, children = thin lines. When the selection changes, the iframe highlight, the right panel (thread, compose target) and dock panes 1-3 change together.
- Keyboard (dock open, focus not in a text field): up = parent, down = first child, left = previous sibling, right = next sibling.
- Pane 2 zoom view: **live** = with DOM access, open `iframe#rv-zoom-frame` (same entry), run the current state's steps, then transform so the selected bbox (+16 px) fits the pane, pointer events off. Moving the selection within the same state only changes the transform; steps run again only on state changes. **crop** = without DOM access (opened from disk, ...), the crop image from the key data in `img#rv-zoom-img`. If neither, "no zoom image". (Running state steps needs iframe DOM access, which is blocked when opened from disk - hence the crop fallback.)
- Pane 2 property table = area, template, variant, new, size (w x h), position (x, y - document coordinates, 1920 wide), source location (`src` from keys, else `—`). Comparison strip = crops from the key data of the same key (wire <-> mockup through `keymap`) in other states, other variants of the same stage, and other stages; each item links to that target's review URL (`&v=&state=&k=`), "none" without a crop.
- Pane 3 library slug = the selected node's template (else the nearest ancestor template). In a wireframe without a template, the `mockupUse` template with the label "used in mockup: <slug>". `data-new` nodes (no template) show "new element - no template" + the data-new text (+ a button to the ancestor template's card if there is one). Slugs not in the index: "not in the template index: <slug>" (`data-state="missing"`).
- Pane 3 card = name, slug, thumbnail, usage/screen counts, screens that use it (links), catalog page link; node tree (depth indent; nested template nodes have ▸ to enter that card, with card breadcrumb and back); kit rows; rule excerpts; alternatives (`alts`), each with [suggest swap].
- Correspondence: if the card slug is the selected node's template and the selected node has a variant, highlight the first node where `node.name === variant` or `node.path` ends with `/<variant>`. Otherwise "no correspondence" (never link by guess).
- [suggest swap] -> fills the compose form with `kind=template` + `suggest={template: <alternative slug>}` (chip "swap: <current> -> <alternative>" + clear), focus on the text field. **POST only when the user presses submit.** If kind template is chosen without suggest, submit is disabled with the hint "press [suggest swap] in the library".
- Data loading: on start `library/index.js` and `library/keys-<Screen>.js`; when a card opens, `library/<slug>.js`, through `<script>` injection (each slug cached after the first load). A slug goes into src only after its pattern and index existence are checked. onerror -> that pane gets `data-state="error"` + a hint (`python ui-audit/scripts/catalog_library.py --build`). Feedback works without this data.
- Opened from disk: no DOM access to the deliverable, so pane 1 tree = keys of the current (stage, version, state) from the key data linked by `parent`, pane 2 = crop, pane 3 unchanged. Only the compose form is hidden (4.5).
- Variant dropdown and state changes: on a state change, keep the selection if the same key exists in the new state and refresh the dock, otherwise show "<key> not in this state". Variant navigation URLs carry `&k=<current component>`; after loading, that key is selected and the dock opened if it exists.
- Dock: opens when something is selected, resizable height (grip, remembered in localStorage - works even if storage fails), foldable. Below 1280 px width panes 1-3 stack vertically, no horizontal scroll. The right panel's former "components" list is absorbed into the dock tree.

**DOM contract (ids and attributes used by tests)**

| Element | id / selector | Attributes, states |
|---|---|---|
| Dock | `#rv-dock` | closed = `.hidden`, open = `data-open="1"`; `#rv-dock-fold` (aria-expanded), `#rv-dock-grip` (height grip) |
| Breadcrumb | `#rv-dock-crumb` | `.rv-crumb[data-node]` |
| Pane 1 tree | `#rv-dock-tree` (role=tree) | `.rv-node[data-node]` (role=treeitem), current `aria-selected="true"`, `.group[data-count]`, `.keyless`, original `data-area`/`data-template` copied onto node elements |
| Pane 2 zoom | `#rv-zoom` | `data-mode="live|crop|none"`, `iframe#rv-zoom-frame`, `img#rv-zoom-img` |
| Pane 2 properties | `#rv-props` | `tr[data-prop="area|template|variant|new|size|pos|src"] > td` |
| Pane 2 strip | `#rv-strip` | `a.rv-strip-item[data-target="<stage>/<version>"][data-state]` |
| Pane 3 library | `#rv-dock-lib` | `data-state="none|loading|ready|error|missing"`, `#rv-lib-card[data-slug]`, `#rv-lib-use` (used-in-mockup label), `#rv-lib-crumb`, `#rv-lib-back` |
| Pane 3 node tree | `#rv-lib-nodes` | `.rv-lnode[data-depth]`, `.rv-lnode.match`, `button.rv-drill[data-slug]`, `#rv-lib-nomatch` |
| Pane 3 kit, rules, alternatives | `#rv-lib-kit`, `#rv-lib-rules`, `#rv-lib-alts` | `button.rv-suggest` inside `.rv-alt[data-slug]` |
| Compose form | `#rv-suggest`, `#rv-suggest-clear` | suggestion chip (`.hidden` when none); kind radio gains `template` |

## 8. Revision A - author name, shared server binding

> Background: a team can run one shared review server, so feedback from several people lands in one log and needs an author. **Existing logs stay valid** (optional field only).

### 8.1 `author` (optional)
- Optional field `author` on user events (`open`, `comment`, `close`, `reopen`) = the author's name, 1-40 characters (at least 1 after trimming). The schema enforces `minLength: 1`; the upper limit and whitespace are checked in the core (`AUTHOR_MAX`, rule 6 of 3.1).
- `author` on a `by=claude` event is 400 (rule 6). claim, release and revision reject it in the schema.
- The server passes it through unchanged. It is a **self-reported value** - not authentication or proof of identity.
- Folded items do not change (it stays in the `history` events). `feedback.py list` shows it as the `- 작성: <name>` line (author) and as `[user:<name>]` on comments.

### 8.2 Viewer
- `#rv-author` (name field, max 40 chars) at the top of the compose form. Its value is remembered in `localStorage['uiaudit-review-author']` (per browser; if storage fails, the value typed in that session is used).
- Every user POST (compose, comment, close, reopen) includes `author`. With an empty name, submit is disabled with a hint to fill in the name first; inline sends do not POST and focus the name field with a hint.
- Author cell in the history = the name if `by=user` and `author` exists, otherwise "user" / "Claude".

### 8.3 Server `--host`
- `python ui-audit/scripts/review_server.py --host <this machine's LAN IP> [--port 8770]` (for example `--host 192.0.2.10`) - binds to that address and adds `http://<host>:<port>` to the Origin allow-list (4.3). 127.0.0.1 and localhost stay allowed.
- `0.0.0.0`, `::` and empty values are refused (the server cannot know the address browsers use, so it could not check Origin). Team members must open exactly the address given to `--host` (the IP); opening by host name makes POSTs fail with 403.
- `project.json` `publish.team_server` (for example `"http://192.0.2.10:8770"`) is embedded into `review.html` at build time, so a viewer opened from disk links to the team server.

## 9. Revision F - attachment images

> Background: users need to leave reference images with feedback (for example "make it exactly like this design"). Limits: 10 MiB per file, 6 per event, 1 GiB in total, images only; comment text stays required.
> **Existing logs stay valid** (optional field only). Folded items do not change - attachments stay inside the open/comment events in `history` (`expected-state.json` unchanged).

### 9.1 Storage and sharing
- Location = `feedback/attachments/<first 20 chars of sha256 (lower-case hex)>.<ext>`, `ext` in `png | jpg | gif | webp` (the format the server detected from the file's leading bytes). Same content = same path (no duplicates). Never modified once written (append-only, no delete API).
- **Not shared through git** - they live only on the same disk as the log (in team operation, the shared server). Uploaded files that no event references (orphans) remain.
- Static serving as in 4.3 (`ui-audit/` prefix).

### 9.2 Event field `attachments` (open and comment, optional)
- `[{"path": "feedback/attachments/<20hex>.<ext>", "name"?: "<original file name>"}]` - 1-6 items (schema `maxItems: 6`), other keys rejected. `path` must match the schema pattern `^feedback/attachments/[0-9a-f]{20}\.(png|jpg|gif|webp)$` exactly. `name` = 1-120 characters (at least 1 after trimming; upper limit and whitespace checked in the core - rule 6 of 3.1), a self-reported display value.
- Only on `by=user` events (400 on a `by=claude` comment, rule 6). The same path twice within one event is 400.
- **File existence is checked only at `append`** (400 "attachment file missing: <path>" if absent). `fold` and `check` do not check existence, so a later missing file never makes the whole log unreadable.
- Comment `text` stays required (no attachment-only comments).

### 9.3 Server upload API
- `POST /api/attachments` - body = the raw file bytes. `Content-Type` in `image/png | image/jpeg | image/gif | image/webp` (else 415). `Content-Length` required (400 if missing), 400 if 0, **413 above 10 MiB without reading the body**. Origin check as in 4.3 and 8.3 (403). If the leading bytes (signature) differ from the declared format, 400. If saving would make `feedback/attachments/` exceed **1 GiB** in total, nothing is saved and 507 is returned. If the same content already exists, it is not rewritten and the same response is returned.
- Response 201 `{"ok": true, "attachment": {"path": "<9.1 path>", "type": "<MIME>", "size": <bytes>}}`; failures use the 4.3 shape `{"ok": false, "error"}`.
- Writes are atomic (`.tmp` -> `os.replace`). SVG, PDF and anything outside the 4 image types are refused (embedded scripts, out of purpose).
- Uploading does not write the log. Attaching to an event is the job of the following `POST /api/feedback` (open or comment).

### 9.4 Viewer
- The new-feedback form and the inline comment form get attachments: [attach image] (`input[type=file]`, multiple, `accept` = the 4 types) + pasting clipboard images into the text field + **drag and drop** (new feedback = the whole `#rv-form-sec`, comment = that inline form; `.rv-dropping` while dragging). Files dropped outside a drop zone are ignored, but browser navigation (losing the draft) is prevented document-wide. Close and reopen forms are not drop zones. Picked files show as thumbnail chips (`.rv-att-chip`, each with [remove]). Format, 10 MiB and 6-file limits are enforced in the browser first, with a hint.
- Submit = `POST /api/attachments` for each attachment in order -> put the returned paths and file names (`name`, truncated to 120 chars) into `attachments` of the open/comment POST. If any upload fails, the event is not sent and the draft (text and attachments) is kept.
- In the thread history, thumbnails in `.rv-atts` below open and comment events (`a.rv-att > img`, original in a new tab). Paths go into src/href only if they match the 9.2 pattern; names go into `textContent` and `title`.
- Opened from disk (read-only) there is no attachment form (the compose form stays hidden). If an attachment image in the history is not on that PC, only its name is shown instead of a broken image.

### 9.5 CLI
- `feedback.py list`: open attachments as `- 첨부: ui-audit/feedback/attachments/<…> (<name>)` (`첨부` = attachment; several separated by `, `), and ` (첨부: <path>, …)` at the end of comment lines. Paths are **relative to the client repository root** (so Read can open them directly); `[파일 없음]` (file missing) is appended when the file is not on this disk. `show` and `--json` keep them in history as is.
- Claude never writes or deletes attachments (uploading is server-only). Attachments are evidence, not edit targets - they are outside the registry `files`.
