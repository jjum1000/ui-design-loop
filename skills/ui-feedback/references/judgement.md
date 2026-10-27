# Judgement examples (`/ui-feedback` steps 2 and 3)

Examples use a hypothetical `ShopView` with a wireframe `r1` (`design/shop/wire.html`) and mockup variants `v2` (`design/shop/variant-v2/`, the current one) and `v1` (an earlier variant).

## Fix or ask

| Feedback (component) | Decision | Why |
|---|---|---|
| "Change the header title to 'Black Market'" (header-title, mockup v2) | Fix | What and where are fully determined, inside `variant-v2`, not pinned by a baseline |
| "The claim-all button is too small" (btn-claimall, mockup v2) | Fix | One change (make it bigger). Touch area changes -> also run `measure_a11y.py` |
| "meh" / "looks off" / "test" (item-row) | Ask | No direction. Offer 2-3 options |
| "Make this purple instead" (v2) | Ask | Off-kit color conflicts with the design-system prohibitions. Offer in-kit candidates |
| "The button border image looks broken" - cause is in `kit/assets/...` | Ask (out of scope) | The file to change is in `kit/`, outside the registry `files`. "kit/assets/... must change; kit changes need user approval" |
| "Add (wire) to the header title" (wire r1) - `wire.html` is pinned by `shop/v2/frozen-baseline.sha1` | Ask | Pinned by a checksum baseline. Fix only after a user comment allows it, then report "baseline update needed" |
| "Make item rows shorter" + "put more info in item rows" on the same variant | Ask on both | They conflict - ask for priority |
| No key (`component=null`), bbox spans two panels | Ask | Ambiguous target. Quote the bbox and the nearest key candidates |
| "Remove the bundles tab" (flow, v2 confirmed) | Ask | Reverses a structural decision of a confirmed variant (`changes-v2.md`) |
| reopened, reason "text is still small" + previous rev summary "14->16px" | Fix | The previous direction was right, just not enough - read the previous diff and continue |

Question wording examples:
```
Question (Claude): "meh" alone does not tell me what to change - A) row height and spacing B) text size and weight C) status badge color? If you meant something else, please describe it.
Question (Claude): The broken border comes from kit/assets/buttons/Btn_Frame.png (9-slice margins), which is outside this variant's edit scope (registry files). Should I go ahead with a kit asset change?
```

## Grouping

- Claim together: same `(screen, stage, version)` + "item row text is small" (item-row idx 0) and "item row text is small" (item-row idx 3) - one CSS rule.
- Claim separately: within the same variant, "title text" (header-title) and "claim-all size" (btn-claimall) - different causes and file locations get separate revisions (so the user can close or reopen them one by one in the viewer).
- Never together: wire r1 feedback + mockup v2 feedback; v2 + v1 (different variants, even within the mockup stage).
- One claim at a time per variant: claim -> edit -> revise/release -> next claim.

## Skipping named ids (comment required)

- status `fixed` -> "Already fixed in rev-NNNN - please check it and close or reopen it in the viewer."
- `closed` -> "This item is closed, so I did not process it. Reopen it if you want it handled."
- `claimed` (by another claim) -> "In progress under cl-NNNN - will handle it after that finishes."
- A question by judgement -> the question comment is the reason.
