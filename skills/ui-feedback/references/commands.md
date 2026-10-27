# Command details (`/ui-feedback`)

All commands run from the Unity project root (the folder that contains `ui-audit/`), in Git Bash or another POSIX shell.
`<S>` = a scratch folder (your session scratch directory, or the output of `mktemp -d`). `<CL>` = a claim id (`cl-0001`). Shell variables do not survive between Bash calls, so define and use them within one call.

## 0. Fixed CLI markers (v0.1 output is Korean)

`feedback.py` prints Korean labels. These are the ones the procedure relies on:

| Marker | Meaning |
|---|---|
| `## fb-0007 — open · visual` | item header: id, status, kind |
| `- 화면/단계/시안:` | screen / stage / variant (version, with its label) |
| `- 컴포넌트:` ... `(키 없음)` | component key (`data-area`); "no key" when null |
| `- 원문:` | the feedback text |
| `- 작성:` | author name (self-reported) |
| `- 첨부:` / `(첨부: ...)` | attachments on the item / on a comment (paths relative to the project root) |
| `[파일 없음]` | attachment file is not on this disk |
| `- 산출물:` | deliverable entry HTML |
| `- 소스 위치:` ... `(없음)` | `path:line` hits of the component key inside the registry `files` ("none") |
| `- 코멘트:` with `  - [user:<name>] ...` / `  - [claude] ...` | comments |
| `- 이전 리비전:` | earlier revisions and their summaries |
| `- 경로:` | node path in the deliverable (`kind=template` and dock selections) |
| `- 교체 제안: <current> → <suggested> · <kit tail>` | template swap suggestion |
| `키트에 없음` / `키트 정보 없음(라이브러리 미빌드)` | kit tail: "not in kit" / "kit info missing (library not built)" |
| `## 이력` then `- [<type>] by=<user|claude> at=<time> {json}` | `show` history lines |
| `claim cl-NNNN: ...` / `release cl-NNNN: ...` / `revision rev-NNNN (claim cl-NNNN): ...` | write results |
| `오류: ...` on stderr, exit code 1 | refused (validation, state transition, lock timeout, unsafe path) |
| `오류: 바뀐 파일이 없음 — revise 거부` | revise refused: no changed files |

## 1. List and filter

```bash
python ui-audit/scripts/feedback.py list --screen ShopView                     # open + reopened (default)
python ui-audit/scripts/feedback.py list --status claimed --json               # any other claim in progress?
python ui-audit/scripts/feedback.py show fb-0003                               # history (open, comment, claim, release, revision)
```

`--stage`/`--version`/`--ids` filters (the CLI has none; filter the JSON. On Windows, reset the pipe encoding to UTF-8):
```bash
python ui-audit/scripts/feedback.py list --screen ShopView --json \
 | python -c "import json,sys; sys.stdin.reconfigure(encoding='utf-8'); sys.stdout.reconfigure(encoding='utf-8'); d=json.load(sys.stdin); [print(i['id'], i['status'], i['stage'], i['version'], i['component'], i['text'][:60]) for i in d if i['stage']=='mockup' and i['version']=='v2']"
```
Items named with `--ids` are read with `show <id>` regardless of status (closed, fixed or claimed items are not processed; leave a comment with the reason).

Attachments - what the list output looks like and how to open them:
```
- 첨부: ui-audit/feedback/attachments/3f9a…e1.png (tablet-ref.png)
  - [user:reviewer-a] see this one too (첨부: ui-audit/feedback/attachments/7c02…94.png (extra.png))
```
Pass the path to the Read tool as is and the image is shown (`<project root>/ui-audit/feedback/attachments/<…>.png`). To list only items that have attachments:
```bash
python ui-audit/scripts/feedback.py list --json \
 | python -c "import json,sys; sys.stdin.reconfigure(encoding='utf-8'); sys.stdout.reconfigure(encoding='utf-8'); [print(i['id'], h['type'], a['path'], a.get('name','')) for i in json.load(sys.stdin) for h in i['history'] for a in h.get('attachments') or []]"
```

Failure history count (stop at 2 or more):
```bash
python ui-audit/scripts/feedback.py show fb-0003 | grep -cE '\[release\] by=claude.*"text": "(failed|no-change|실패|변경 없음):'
```
(`conflict:` / `충돌:` releases are not counted: they are not your failures.)

## 2. Is the file pinned by a checksum baseline? (required before claim; ask if pinned)

One line per registry `files` entry (`F` = path relative to `ui-audit/`). Baseline files use different base folders (some list `wire.html` relative to the track, some `./kit.css` relative to the kit), so match **whole lines** against every suffix of F (`design/shop/wire.html`, `shop/wire.html`, `wire.html`); CRLF is tolerated and partial matches like `attention-wire/...` are not:
```bash
F=design/shop/wire.html; RE=""; s="$F"; while :; do RE="$RE|${s//./\\.}"; [ "${s#*/}" = "$s" ] && break; s="${s#*/}"; done; grep -rnE --include='*.sha1' "^[0-9a-fA-F]+ [ *](\./)?(${RE#|})"$'\r'"?$" ui-audit/design/ && echo "-> pinned" || echo "-> not pinned"
```
For `files` entries with a `*` glob, expand them with `ls ui-audit/<glob>` and run the line per file.

Example result table (fill in for your tree):

| F | Result |
|---|---|
| `design/shop/wire.html` | pinned - `shop/v2/frozen-baseline.sha1:12 *wire.html` |
| `design/shop/variant-v2/app.js`, `index.html`, `style.css` | not pinned |

If pinned, do not claim:
```bash
python ui-audit/scripts/feedback.py comment fb-NNNN "Question (Claude): design/shop/wire.html is pinned by design/shop/v2/frozen-baseline.sha1. May I edit it (including updating the baseline)?"
```
-> list it under "skipped" in the report. If the user later allows it in a comment, fix it in the next run and report "baseline update needed: <baseline file>" (this skill does not update baseline files; they are outside the registry `files`).

## 3. Shared-tree guards

G1 - right before editing (right after claiming): current files equal the snapshot? + mtime:
```bash
CL=cl-0001; SNAP=ui-audit/feedback/snap/$CL/files
for f in $(cd "$SNAP" && find . -type f | sed 's|^\./||'); do
  if cmp -s "$SNAP/$f" "ui-audit/$f"; then echo "SAME $f"; else echo "CHANGED $f"; fi
  stat -c '%y  %n' "ui-audit/$f"
done
```
- Any `CHANGED` -> do not edit. `release --reason "conflict: <file> changed after the claim"` and report.
- If the registry `files` contain a `*` glob, also check whether the current glob result (`ls ui-audit/<glob>`) has files that are not in the snapshot (same handling).

Record the hash of your result right after editing (only the files you changed):
```bash
(cd ui-audit && sha1sum design/shop/wire.html) > "<S>/$CL.mine.sha1"
```

G2 - right before revise and before any restore:
```bash
(cd ui-audit && sha1sum -c "<S>/$CL.mine.sha1")     # every line must be OK
```

## 4. Roll back on failure -> release

```bash
CL=cl-0002; SNAP=ui-audit/feedback/snap/$CL/files
(cd ui-audit && sha1sum -c "<S>/$CL.mine.sha1") || { echo "not my result - abort restore, report"; exit 1; }
for f in design/shop/wire.html; do                 # the files you changed
  if [ -f "$SNAP/$f" ]; then cp "$SNAP/$f" "ui-audit/$f"; else rm "ui-audit/$f"; fi   # not in the snapshot = created by you
done
# run the G1 loop again -> everything must be SAME
python ui-audit/scripts/feedback.py release fb-0003 --reason "failed: <reason> - restored from snapshot"
```
- If you failed before recording the mine hash (in the middle of editing): look at `diff -u "$SNAP/<f>" "ui-audit/<f>"` and restore only if it contains **only your hunks**. If there are hunks you do not recognize, do not restore; report.
- If revise fails with `오류: 바뀐 파일이 없음 — revise 거부` (exit code 1) -> `release --reason "no-change: <why>"`.
- Do not delete snapshot folders (the CLI keeps them as an audit record).

## 5. Report example

```
### fb-0001 - fixed (rev-0001, claim cl-0001)
- Changed: [header-title] added "(wire)" to the title h2 - feedback "append (wire) to the header title"
- File: design/shop/wire.html (user allowed it in a comment -> baseline update needed: design/shop/v2/frozen-baseline.sha1)
- diff: ui-audit/feedback/revisions/rev-0001.diff
- before/after: ui-audit/feedback/snap/cl-0001/before/fb-0001.png -> ui-audit/feedback/revisions/rev-0001/after-fb-0001.png
- Measurement: (ui-audit/design/shop) python tools/shoot.py wire.html --out <S>/cl-0001-after -> PASS, report identical to baseline
- Viewer: http://127.0.0.1:8770/ui-audit/catalog/review.html?screen=ShopView&stage=wire&v=r1&fb=fb-0001
### fb-0002 - question left: "meh" gives no direction -> asked to choose row height / text / badge color
### Server: 200 (running) - Please close or reopen items in the viewer yourself (Claude does not do this).
```

## 6. Procedure test (never on the real log - temp root only)

```bash
T=<S>/uia-root1; mkdir -p "$T/design/shop" "$T/feedback"
cp -r ui-audit/schemas "$T/"; cp ui-audit/design/registry.json "$T/design/"; cp ui-audit/design/shop/wire.html "$T/design/shop/"
# user "open" events go straight into the core, in the temp root only
UIAUDIT_ROOT="$T" PYTHONIOENCODING=utf-8 python -c "import sys; sys.path.insert(0,'ui-audit/scripts'); import feedback_core as FC; print(FC.append({'type':'open','screen':'ShopView','stage':'wire','kind':'copy','text':'…','component':'header-title','state':'board'},'user')['id'])"
# afterwards prefix every feedback.py command with UIAUDIT_ROOT="$T" and use "$T/" instead of ui-audit/ in paths
# measure with the real track tools on absolute paths: (cd ui-audit/design/shop && python tools/shoot.py "$T/design/shop/wire.html" --out "<S>/m-after")
```
`sha1sum ui-audit/feedback/log.jsonl` must be the same before and after the test.
