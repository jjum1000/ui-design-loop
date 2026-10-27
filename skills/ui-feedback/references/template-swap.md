# Template swap suggestions (`kind=template`; adds to steps 2, 4 and 5)

> Premise: this document sits **on top of** all rules of SKILL.md steps 0-6 (baseline questions, one claim at a time, scope = registry `files`, ...). It does not replace them. `kind=template` items go through the same list -> judge -> claim -> edit -> measure -> record -> report steps as any other item; this document only makes "what, where and how to change" (steps 2, 4, 5) concrete for `kind=template`.
> Basis: `CONTRACT.md` 7.1 (`path` and `suggest` fields), 7.3 (list/show digest lines), 7.4 (library data).
>
> **Principle (no revise if violated):** when a user suggests "swap to this template", they want the deliverable to **look** and behave like that template. If only the `data-template`/`data-variant` attributes change and the screen looks the same, the `fixed` record is false. Such "metadata-only" swaps are **not allowed**. Revise only after step 5 confirms the visual really changed.

## 1. Read the input - `list`/`show` already evaluate it

For `kind=template` items, `feedback.py list`/`show` print two extra lines (other kinds do not have them):

```
- 경로: item-row[listitemunit · shop-row] › thumbnailitemunit[ShopItemSlotUnit]
- 교체 제안: thumbnailitemunit → thumbnailemptyunit · 키트: Thumbnails/Empty slot `(스니펫)`
```

- **Path** (`경로`, field `path`) = the chain inside the deliverable from outside to the selected node. The last item is the node to swap (brackets = template, variant, idx). If a node has no `area` (like the second item above), it has no `data-area` itself and the nearest ancestor's `data-area` is the `component` (the feedback's anchor key).
- **Swap suggestion** (`교체 제안`, field `suggest`) = `<current slug> → <suggested slug> (variant: X)? · <kit tail>`. The current slug is `item.template` (else the template of the last path item, else `—`).
- **Kit tail**, three cases - the first criterion in step 2 (the final decision also needs sections 2 and 3):
  | Tail | Meaning | First call |
  |---|---|---|
  | `키트: <group>/<element> \`<kitClass>\`; ...` (one or more rows) | the slug exists in the track kit's component table (`kit/components.md`), with a mockup class/file, 9-slice and notes | go to section 2 (semantic fit) -> if it passes, sections 4 and 5 (swap and measure) |
  | `키트에 없음` (not in kit) | the slug exists in the Unity template index (checked at append time, which is why `suggest` could be stored) but has no row in this track's kit. No asset or class to back it | **ask** (section 3) |
  | `키트 정보 없음(라이브러리 미빌드)` (library not built) | `ui-audit/catalog/library/index.json` itself is missing - cannot judge | **ask** (section 3, different wording) |

## 2. Semantic fit - check even when the kit has a row

A kit row does not mean the template fits **in that spot**. First check whether the suggested slug matches the element's **current data state**.

- Example (a real case): suggesting to swap a slot **filled with a character** (`thumbnailcharacterunit`, `data-variant="...SlotUnit"`) to the **empty slot** template (`thumbnailemptyunit`). The kit has a row (Thumbnails/Empty slot), but this node currently holds character data; making it look "empty" means stripping the character data binding (image, badge, title), which is a structural change, not an attribute swap. The text alone does not decide between "remove the data too" and "just make the frame look empty". -> **Ask.**
- Same pattern: an in-progress/done node swapped to a "default" template, a success badge to a failure template, a filled list cell to an "empty" template - the data state and the suggested template's meaning disagree.
- Passes when the suggested template is **another style variant used for the same data state** (a difference in look such as color or frame, not in meaning such as data presence or success/failure). Examples: button color variants (`button-cream` <-> `button-yellow`), tab style variants.
- Wording: `Question (Claude): <current slug> -> <suggested slug> differs in meaning from this element's current data state (<what it holds>). Please confirm <what else must change / whether a plain swap is enough>.` -> do not claim; skip as in section 3.

## 3. Ask - do not claim

Four reasons; **keep the wording separate per reason** (SKILL.md step 2 "when unclear, ask and skip", and separate from baseline questions):

| Reason | Wording |
|---|---|
| Not in kit | `Question (Claude): <current slug> -> <suggested slug> has no row in the track kit (kit/components.md), so there is no asset or class to back it. Should it be added to the kit, re-suggested with another template, or put on hold?` |
| Library not built | `Question (Claude): catalog/library/index.json is missing, so I cannot check the kit row for <suggested slug>. It must be generated first with python ui-audit/scripts/catalog_library.py --build.` |
| Semantic mismatch (section 2) | the section 2 wording |
| Snippet transplant too large (found in section 4) | `Question (Claude): <current slug> -> <suggested slug> has no reusable class (kit: snippet), and transplanting it locally into this element is too large (<reason - e.g. needs a new asset / entangled with data binding in another file>). Should I go ahead with the snippet transplant, or re-suggest with another slug?` |

- If one item hits several reasons (for example a baseline pin + not in kit), leave **one comment per reason**.
- "If your question is already the last comment and the user has not answered, do not ask again" (SKILL.md step 2) still applies.
- In the report's "skipped" section write "kind=template - <reason>", separate from baseline skips.

## 4. Locate the node and swap (only after sections 2 and 3 pass)

1. **Locate**: use the last path item's `template` (current slug) and `variant`/`idx` to find the exact place inside the registry `files`. The "source location" in `feedback.py list` greps the `component` (`data-area`) and may miss the template node's own line - search for `data-template="<current slug>"` near that hit, and if the slug appears several times, narrow it with `data-variant="<variant of the last path item>"`.
   - If the current slug is `null` (the selected node is a `data-new` element with no template), this is "assigning a template to a new element", not a swap - out of scope. Comment `Question (Claude): This element is a new element without a template (data-new). Assigning a template is a design decision and is handled differently from a swap suggestion - how should I proceed?` and skip.
   - Several items in the same `(screen, stage, version)` pointing at the same current -> suggested pair (same cause) are claimed together, per SKILL.md step 3.
2. **Look for a helper function first**: if the markup comes from a shared helper (for example `btn({variant, ...})`, where one parameter decides the variant), **prefer changing that parameter at the call site**. The helper derives `data-template`, classes and extra markup (icons, ...) together, so the variant switch stays consistent in one place.
   - Example: `btn({ label: "Buy all", variant: "cream", area: "btn-buyall", ... })` -> changing only `variant: "cream"` to `variant: "yellow"` switches `data-template="button-cream"` -> `"button-yellow"`, the class `v-cream` -> `k-btn--yellow`, and drops the cream-only decoration icon in one go. Other call sites already using `variant: "yellow"` prove the path works.
3. **Raw markup without a helper**: edit directly.
   - Set `data-template` to the suggested slug. Change `data-variant` **only if `suggest.variant` is present** (otherwise leave it - but first check whether the track's CSS/JS uses `[data-variant=` as a selector: `grep -n "data-variant" *.css *.js`).
   - Look at the kit tail's `kitClass` (4th column of `components.md`, or `templates[slug].kit[].kitClass` in `index.json`):
     - **A real CSS class starting with `.`** (e.g. `.k-thumb`, `.k-title`, `.k-btn.k-btn--yellow`) -> **replace the old variant class with the new one** (do not just add it). **Adding only can leave the old look through specificity**: `.k-btn.v-cream` (specificity 0,2,0, overriding both face color and frame sprite) beats `.k-btn--yellow` (0,1,0), so adding `k-btn--yellow` without removing `v-cream` keeps the cream look. Keep shared layout/size classes (`.k-btn`, `.slot`, size utilities - anything that is not a variant); remove only the variant class.
     - **A sprite file path** (e.g. `assets/buttons/BackBTN.png`) -> point the element's `src`/`background` at that asset.
     - **`(snippet)` / `(snippet: specimen)`**, or `(스니펫)` in kit tables written in Korean (no single reusable class or asset - search the slug in `kit/specimen.html` to see the markup) -> transplant it **only if the snippet structure fits this element's existing data binding** (a local change inside the registry `files`). If it needs a new asset file, or the element's data structure (repeated bindings, ...) does not fit the snippet so the transplant spills beyond that one file, **do not claim**; leave the "snippet transplant too large" question from section 3 and skip. Warning: if the snippet uses `.k-tint` (CSS `mask`/`-webkit-mask: var(--mask) ...`), it can **silently fail to render when the page is opened from disk** even though the class and asset exist locally (section 5, CORS). "Transplantable locally" is not the end of the judgement; it must also pass the section 5 crop + error check. (Sprite file paths and `-webkit-mask-box-image` (mask-border) did not have this problem.)
   - Never touch `data-area` or `data-idx` (SKILL.md rule 3 - anchors stay).

## 5. Measure - confirm the visual really changed

Run the structural regression measurement (`references/measure.md`, SKILL.md step 5) as usual. **In addition**, compare before/after crops of the swapped element yourself.

- Before = the claim's `feedback/snap/<cl>/before/<id>.png`.
- After = crop the same element again after the edit and **before calling `revise`** (revise writes its own after shot and the event in the same call, so failures must be caught first to be able to roll back):
  ```python
  # <scratch>/crop_check.py - fill ENTRY/SELECTOR/STEPS/OUT for the item and run it
  from playwright.sync_api import sync_playwright
  import pathlib

  ENTRY = r"<absolute path of the entry - the copy in a temp root, or ui-audit/design/.../index.html>"
  SELECTOR = '[data-area="btn-buyall"]'              # same rule as component(+idx): else selector, then bbox
  STEPS = [("loadState", ["mixed"]), ("stopTimers", [])]  # the registry steps of the item's state (optional calls skipped if missing)
  OUT = r"<scratch>/<cl>-after/<id>.png"
  MARGIN = 16

  with sync_playwright() as pw:
      browser = pw.chromium.launch()
      page = browser.new_page(viewport={"width": 1920, "height": 1080})
      errors = []  # required - even with a different crop, success needs this to stay empty (below)
      page.on("console", lambda m: m.type == "error" and errors.append(m.text))
      page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
      page.on("requestfailed", lambda r: errors.append(f"requestfailed: {r.url}"))
      page.goto(pathlib.Path(ENTRY).resolve().as_uri())
      page.wait_for_load_state("networkidle")
      for name, args in STEPS:
          if page.evaluate("(n) => typeof window[n] === 'function'", name):
              page.evaluate("(a) => window[a.name].apply(null, a.args)", {"name": name, "args": args})
      box = page.query_selector(SELECTOR).bounding_box()
      clip = {"x": max(0.0, box["x"] - MARGIN), "y": max(0.0, box["y"] - MARGIN),
              "width": box["width"] + 2 * MARGIN, "height": box["height"] + 2 * MARGIN}
      pathlib.Path(OUT).parent.mkdir(parents=True, exist_ok=True)
      page.screenshot(path=OUT, clip=clip)
      print("errors:", errors)
      browser.close()
  ```
  (This reproduces the rules of `feedback.py`'s `_crop_shot`/`_run_steps` in a temp script; `feedback.py` itself is outside this skill's write scope, so no new CLI command. **Do not remove the `errors` listeners** - reason below.)
- Success needs **a different crop AND zero errors**:
  - `sha1sum <before.png> <after.png>` **equal** -> the visual did not change (the swap did not apply) - **do not revise.** Roll back per SKILL.md step 6 (G2 check -> restore from the snap copy) -> `release --reason "failed: before/after crops identical - the swap did not apply"`.
  - Hashes **differ** but `errors` is not empty -> the crop changed but **partly broken** (like the mask/CORS case below), which is not success - roll back and `release --reason "failed: crop differs but console/requestfailed errors occurred - <summary>"`.
    - Warning: **the regular `shoot.py` regression in `references/measure.md` may not catch these errors.** If none of the track's fixed fixture states (STATE_IDS) shows this element at all (for example, every slot is filled so no empty slot appears), `report.json` stays silently clean. **So this crop check's `errors` listener complements the structural regression; look at both.**
    - Warning (a real trap): when transplanting a `(스니펫)` locally, CSS `mask`/`-webkit-mask` (`--mask: url(...)`, i.e. `.k-tint`-style) referencing an external PNG is **blocked by CORS when the page is opened from disk** and silently disappears (`Access to image at '...' ... blocked by CORS policy`, `requestfailed`). The same image works from disk via `<img src>`, `background-image`, `border-image` or `mask-border` (`-webkit-mask-box-image`). If the snippet has `.k-tint` (`mask`/`-webkit-mask`), suspect this before transplanting and always check `errors` with this crop check. (Served over `http://` from the review server, CORS may not apply - check every time anyway.)
  - Only when both pass (hashes differ + zero errors) call `revise` together with the structural regression result (its official after shot and event become the record).
  - Two accumulated failures -> stop and report per the failure-history rule in SKILL.md step 2.

revise `--summary` format (**there is no "visual: metadata only" option** - always say what changed):
```
[<last path label or component>] <current slug> -> <suggested slug>(+ variant: X) - kit: <group>/<element> `<kitClass>` - visual: <what changed, e.g. face color cream->yellow, halftone frame swapped> - before/after crops differ - structural measurement: <result>
```

## 6. Additions to the report

- Fixed: in the SKILL.md step 7 format, add "swap: <current slug> -> <suggested slug>" + "visual: <what changed>" + the before/after crop hashes (or file sizes).
- Questions left: mark "kind=template" + reason (not in kit / library not built / semantic mismatch / snippet transplant too large), **separate** from baseline reasons (list both if both apply).
- Released because the crop check failed: id, reason (identical crops / crop differs but errors - summary), whether rolled back.
