# Measurement commands per deliverable (`/ui-feedback` step 5)

Principle: **baseline before the edit -> same command with the same flags after the edit.** Output goes to a scratch folder outside the deliverable tree (`<S>`, absolute path). Measuring never changes the deliverable (it only writes to the output folder).
When you register a new track in `ui-audit/design/registry.json`, add a row to this table for your project. The authoritative measurement command for a track is the "commands" line at the top of that track's `verify.md`, if the track has one.

The scripts come from the `ui-wire-skin` skill; each design track keeps copies in `<track>/tools/` (see that skill's step 0). Run them from the track folder.

## 1. Table (example for a hypothetical `ShopView` track at `ui-audit/design/shop/`)

| Registry entry | Working folder | Always | Conditional |
|---|---|---|---|
| ShopView - wire - r1 (`design/shop/wire.html`) | `ui-audit/design/shop` | `python tools/shoot.py wire.html --out <S>/<CL>-before` (and `-after`) - no `--strict-colors` (wireframes are intentionally grey; off-kit colors are reported only) | none |
| ShopView - mockup - v2 (`design/shop/variant-v2/`) | `ui-audit/design/shop` | `python tools/shoot.py variant-v2/index.html --out <S>/<CL>-before --strict-colors` (and `-after`) | If you changed text size, color or button/touch areas: `python tools/measure_a11y.py variant-v2/index.html`. If you changed emphasis, animation or layout weight: `python tools/attention.py variant-v2/index.html --out <S>/<CL>-attn` |
| ShopView - mockup - v1 (`design/shop/variant-v1/`) | `ui-audit/design/shop` | `python tools/shoot.py variant-v1/index.html --out <S>/<CL>-before` (add `--strict-colors` only if the baseline passed with it) | same as v2 |
| Entries without measurement scripts | - | report "no measurement" + Read the revise after shot yourself | - |

Record the measured baseline when you add a row (for example: `shoot.py wire.html` PASS, `shoot.py variant-v2/index.html --strict-colors` PASS (8 shots), `measure_a11y.py variant-v2/index.html` exit 0 with WORST target 47 / font 12 / contrast-fails N, where the track's `verify.md` lists which contrast failures are known false positives).

## 2. Pass criteria

- `shoot.py`: exit code 0 and last line `RESULT: PASS`. In addition, no new warning vs. the baseline - compare `report.json`:
  ```bash
  python -c "import json,sys; a=json.load(open(sys.argv[1],encoding='utf-8')); b=json.load(open(sys.argv[2],encoding='utf-8')); a.pop('page'); b.pop('page'); print('report equal' if a==b else [k for k in a if a[k]!=b.get(k)])" <S>/<CL>-before/report.json <S>/<CL>-after/report.json
  ```
  If they differ, look at what changed in which state and decide whether the feedback intended it (for example, longer text that now scrolls). Unintended new scroll, CLIPPED, console errors or off-kit colors are a FAIL.
- `measure_a11y.py`: exit code 0 (minimum touch 47 px, minimum text 12 px by default) and `contrast-fails` not higher than the baseline. If it grew, check the state's screenshot (buttons whose face is an image or `::before` are false positives).
- `attention.py`: no pass/fail - if the top salient item or the number of primary (yellow) actions changed vs. the baseline, mention it in the report.

## 3. Notes

- The page argument of `shoot.py` and `attention.py` is relative to the track folder (absolute paths work too). `measure_a11y.py` resolves it relative to the current folder.
- If Playwright is missing or the browser does not start, treat it as a measurement failure (roll back + `release --reason "failed: measurement tool could not run - <error>"`). Do not work around it with `revise --no-shots`.
- Never write measurement output into track deliverable folders such as `ui-audit/design/**/shots/` (you could overwrite another session's comparison baseline).
