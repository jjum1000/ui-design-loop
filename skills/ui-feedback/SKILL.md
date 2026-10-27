---
name: ui-feedback
description: "Processes design-stage feedback that users left per component in the UI review viewer (ui-audit/catalog/review.html) on wireframe and mockup HTML deliverables: triage open feedback -> ask a question comment when unclear -> claim only related items -> edit the deliverable within its registry `files` -> rerun the measurement scripts -> record the fix with `revise` (diff, before/after shots) and report. Use for `/ui-feedback [screen] [--stage S] [--version V] [--ids fb-...]`. Triggers: 'process feedback', 'apply review viewer feedback', 'fix open feedback', 'check viewer feedback', 'handle reopened feedback' / '피드백 처리해', '리뷰 뷰어 피드백 반영', '열린 피드백 고쳐', '뷰어 피드백 확인해', '다시 열린 피드백 처리'."
argument-hint: "[screen UIType] [--stage wire|mockup] [--version V] [--ids fb-0001,fb-0002]"
user-invocable: true
allowed-tools: Read, Glob, Grep, Edit, Write, Bash
---

# Design feedback processing (`/ui-feedback`)

This is **Claude's side** of the loop in which users leave feedback in the review viewer and Claude processes it.
The source of truth is `ui-audit/feedback/CONTRACT.md` (section 3 events and states, 4.4 CLI, revision V variant rules, section 6 permissions). If this skill and the contract disagree, follow the contract and tell the user.

- Working folder = the Unity project root (the folder that contains `ui-audit/`). `FB` below is shorthand: in every Bash call write the full `python ui-audit/scripts/feedback.py` (shell variables do not survive between calls).
- Exact arguments, one-line filters, hash checks and rollback commands: `references/commands.md`. Measurement commands per deliverable: `references/measure.md`. Judgement examples: `references/judgement.md`. Handling `kind=template` (template swap suggestions): `references/template-swap.md`.
- In v0.1 the CLI output, the viewer and generated pages are in Korean. The fixed markers you will parse are listed in `references/commands.md` section 0.

## 0. Absolute rules (stop if you would break one)

1. **Never close or reopen.** Closing and reopening belong to the user (CONTRACT section 6). The CLI has no command for it; do not work around that.
2. **Never edit the log or derived files.** Do not touch `feedback/log.jsonl`, `state.js`, `snap/` or `revisions/`. Always record through `FB` commands (comment, claim, release, revise).
3. **Edit scope = the registry `files` of that feedback's variant only.** Find the `(screen, stage, version)` entry in `ui-audit/design/registry.json` and edit only files inside its `files` (globs included). The kit (`kit/`), shared assets, other variants and the registry itself are out of scope: do not edit them; leave a comment saying what should change where.
4. **One claim = related feedback only, same screen, stage and variant (version).** Never mix variants (the CLI refuses as well). Even within one variant, feedback with a different cause or component gets its own claim.
5. **One claim at a time per variant.** `revise` diffs "snapshot vs. current" for the whole file set, so two concurrent claims would mix each other's edits. Finish a claim with `revise` or `release` before the next one.
6. **When in doubt, do not edit.** Leave a question comment and move on (criteria in step 2).
7. **Never overwrite another session's changes** (guards in step 4). The working tree may be shared; if in doubt, stop and report.
8. When you skip feedback the user named with `--ids`, **leave the reason as a comment on that feedback**.
9. Never experiment on the real log. Procedure tests run only on a copy with `UIAUDIT_ROOT=<temp root>` (end of `references/commands.md`).

## 1. Get the list

```bash
FB list [--screen <screen>]                    # default = open,reopened. Text, component, entry, source location, comments, previous revisions
FB list --status claimed --json                # existing claims (rule 5)
FB show <id>                                   # full history of one item (reopen reason, previous revisions, releases)
```
- Arguments: `[screen]` -> `--screen`. The CLI has no `--stage`/`--version` filter; filter the `--json` output (`references/commands.md` section 1). With `--ids`, read exactly those ids with `show`, regardless of status.
- Zero feedback: report "no open feedback" with the `claimed`/`fixed` counts per screen and stop.
- If a variant still has a `claimed` item, do not touch that variant in this run; list it in the report (another session is working, or an earlier run was interrupted; the user decides).
- Order: `reopened` first (the user already sent it back once), then `open` by id.

## 2. Judge each item: fix / ask / skip

For each item, open the deliverable `entry` and the source location from the list output and read the component. If you need to see the screen, take state shots into a scratch folder with the measurement script and Read them (there is no before shot yet; you have not claimed).

**Attachments** (CONTRACT section 9): open **every** path listed on the `- 첨부:` line and in `(첨부: ...)` at the end of comments (paths are relative to the project root) with Read **before** judging. A vague request ("make it exactly like this design") gets its direction from the attachment.
- Attachments are **evidence only**. Do not edit, delete or move them, and do not copy them into the deliverable (outside the registry `files`, rule 3). If the image uses colors or sprites outside the kit, do not copy them; ask as usual.
- An attachment marked `[파일 없음]` ("file missing") is not on this disk (you are probably not on the machine that hosts the review server) -> do not fix that item; report it.
- If you are not sure what the attachment shows, ask in the question comment which part of the attachment (row background, spacing, ...) to follow.

**Fix** only when all of these hold:
- The text (+ the user's comments on it) determines exactly one change.
- The change is inside rule 3's scope.
- It does not conflict with the track's final decisions and rules (decisions recorded in `variant-*/deviations.md`, `changes-*.md`, or design-system prohibitions: off-kit colors, new sprites, rebuilding a template's look).
- The target registry `files` are not pinned by a checksum baseline (`*.sha1` files under `ui-audit/design/`). Before claiming, check each file with the one-liner in `references/commands.md` section 2. **If pinned, ask** (below), unless the user already allowed the edit in a comment; then fix and write "baseline update needed: <baseline file>" in the report.
- For `kind=template` (template swap suggestion), additionally: (1) the kit tail of the swap-suggestion line (`- 교체 제안:`) has kit rows (not `키트에 없음` "not in kit" or `키트 정보 없음(라이브러리 미빌드)` "library not built"), (2) the suggested template matches the element's current data state, and (3) you confirm in step 5 with before/after crops that the visual actually changed before recording `fixed`. Swapping only the `data-template` attribute while the screen looks the same ("metadata-only" swap) is forbidden: it makes the record false. Full procedure: `references/template-swap.md`.

**Leave a question comment and move on** (do not claim):
- The text can be read several ways ("looks off", "meh", "test" - no direction).
- No component key (`component=null`) and the bbox spans several elements.
- The fix would be out of scope (kit, shared assets, other variants) or would reverse a final decision.
- The target file is pinned by a checksum baseline and the user has not allowed it -> comment `Question (Claude): <file> is pinned by <baseline file>. May I edit it (including updating the baseline)?`, skip, and report it.
- `kind=template` and (a) the kit tail says "not in kit" / "library not built", (b) the suggested template does not match the element's current data state, or (c) the kit row is a snippet whose local transplant goes beyond that one file -> do not claim; leave the question for that reason in the format of `references/template-swap.md` section 3. If the same item is also pinned by a baseline, leave **one comment per reason** (do not merge them).
- It conflicts with another open item (comment on both).
- Question format: `Question (Claude): <what is unclear> - options A) ... B) ... / if out of scope: which file to change and why`. 1-4000 characters. Write it in the language the feedback was written in.
- **If your own question is already the last comment and the user has not answered, do not ask again**: skip and report. If a user comment follows it, add that answer to the original text and judge again.

**Failure history**: if `show <id>` contains **two or more** `release` events whose reason starts with `failed:` or `no-change:` (older logs may use `실패:` / `변경 없음:`), do not try again: **stop the run** and report to the user.

## 3. Claim related items together

```bash
FB claim <id> [<id>...]          # prints "claim cl-NNNN: ..." - note the cl id
```
- Grouping rule: same `(screen, stage, version)` + same component (or the same cause, for example two remarks fixed by one CSS rule). If unsure, claim separately.
- `claim` copies the registry `files` (`ui-audit/feedback/snap/<cl>/files/<relative path>`) and takes a before crop per item (`snap/<cl>/before/<id>.png`). The server does not need to run (the CLI works without it).
- If the claim is refused (mixed variants, already claimed, variant not in the registry), note the reason in the report and move on.

## 4. Edit - shared-tree guards

1. **Guard G1, right before editing**: check that each target file still equals the snapshot (`cmp`/`sha1sum`) and print its mtime (`references/commands.md` section 3). If it differs, another session changed it after the claim -> **do not edit**; `release --reason "conflict: <file> changed after the claim"`, then stop and report.
2. **Measurement baseline**: if the deliverable has measurement commands (`references/measure.md`), run them once before editing and record the result (so you do not blame yourself for failures that already existed).
3. Read -> Edit with the smallest change. Touch only the component the feedback points to (`data-area`/`data-idx`) and its styles and scripts. No surrounding cleanup or refactoring. Never delete or rename a `data-area` key (viewer anchors break; ask if a key must change; adding new keys is fine). For `kind=template`, the scope and method (`data-template`/`data-variant`, whether to apply kit classes) follow `references/template-swap.md`; the minimal-change and anchor rules still apply.
4. If the Edit tool refuses because "the file changed since it was read", another session wrote it -> do not overwrite. Apply the step 6 rollback rule (restore only if it is your result), `release --reason "conflict: ..."`, stop and report.
5. When the edit is done, **record the hash of your result** (`sha1sum <files> > <scratch>/<cl>.mine.sha1`, section 3).

## 5. Rerun measurements

- Find the deliverable's commands in `references/measure.md` and rerun them **with the same flags as the baseline**. Output goes to a scratch folder outside the deliverable tree (`--out <absolute path>`).
- Pass = exit code 0 and last line `RESULT: PASS`, and no warning that was absent from the baseline (scroll, CLIPPED, errors, off-kit colors): compare the two `report.json` files (`references/measure.md` section 2). If you changed text size, color or touch areas, run `measure_a11y.py` too.
- Deliverables without measurement commands: report "no measurement", and Read the `revise` after shot yourself instead.
- Measurement FAIL -> fix and rerun (at most twice within the same claim). If it still fails, apply the step 6 failure rules.
- For `kind=template`, in addition to the structural regression check, compare the target element's before (`snap/<cl>/before/<id>.png`) and after crops **before** calling `revise` to confirm the visual really changed (`references/template-swap.md` section 5). If they are the same, do not revise; release under the step 6 failure rules.

## 6. Record - revise or release

**Success**:
```bash
sha1sum -c <scratch>/<cl>.mine.sha1        # guard G2: still my result? If not, do not revise; stop and report
FB revise <id...> --summary "<what, why, measurement result>" [--new-version V]
```
- `--summary` (1-2000 characters): `[component] what changed and how - because of feedback "<short quote>" - changed files - measurement: shoot PASS (0 new warnings vs. baseline)`.
- `--new-version` only when the user asked to bump the version. It is recorded only; the registry is not updated (the registry is outside the write scope) -> add "registry version update needed" to the report.
- A successful revise sets the items to `fixed`. Closing or reopening is up to the user in the viewer.

**Failure rules** (could not finish the edit after claiming, measurement failed, or revise refused):
1. **Roll back**: restore from `snap/<cl>/files/` only if the current files equal *your result* or *the snapshot* (same check as G2; delete files you created). If neither (another session touched them), do not restore; stop and report. Commands: `references/commands.md` section 4.
2. After restoring, confirm every target file equals the snapshot.
3. `FB release <id...> --reason "failed: <reason>"`. If revise was refused with "no changed files", use `no-change: <why nothing ended up changing>`; for shared-tree conflicts use `conflict: ...`.
4. If this failure brings an item to two `failed:`/`no-change:` releases, **stop the run** and report (failure history in step 2).

## 7. Report (to the user)

At least one line per item, with everything below (example format in `references/commands.md` section 5):
- Fixed: `rev-NNNN` (claim `cl-NNNN`), ids, changed files, gist of the summary
  - diff `ui-audit/feedback/revisions/<rev>.diff`
  - before `ui-audit/feedback/snap/<cl>/before/<id>.png`, after `ui-audit/feedback/revisions/<rev>/after-<id>.png` ("shot failed" if null)
  - measurement commands and results (baseline -> after); "baseline update needed: <baseline file>" if you edited a pinned file with permission
  - viewer `http://127.0.0.1:8770/ui-audit/catalog/review.html?screen=<screen>&stage=<stage>&v=<version>&fb=<id>` (use the team server's address instead if the team runs one)
- Questions left: id and gist. Skipped: id and reason (for named ids, whether you left a comment). Failed/released: id, reason, whether restored.
- Server status: if `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8770/api/feedback` is not 200, say "start `python ui-audit/scripts/review_server.py` to check in the viewer" (the CLI records are already complete without the server). A viewer opened from disk without the server is read-only.
- Last line: "Please close or reopen items in the viewer yourself (Claude does not do this)."

Never write just "done": the paths and results above are the evidence.
