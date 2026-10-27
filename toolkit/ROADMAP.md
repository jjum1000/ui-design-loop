# Game UI inventory and cleanup - agent orchestration

## Overview

Agents collect and classify the current UI of a Unity project (and, optionally, screen captures) and build an **HTML catalog** that shows how fragmented the UI is and proposes how to consolidate it. The catalog becomes the reference for later design work and partial refactoring. It is filled in gradually, by running the pipeline once per batch of screens.

**In scope**

- Collect every UI component, sprite, font, color and size value in use
- Group variants with the same role, propose standard candidates, extract token drafts
- Present fragmentation metrics and an "existing -> standard" mapping as an HTML catalog

**Out of scope (done later, using the catalog)**

- Editing prefabs, writing shared scripts, replacing screens
- Building a Figma library

**Assumptions and principles**

- Unity with uGUI + TextMeshPro, a reference resolution and target platforms from `project.json`.
- Agents treat the Unity project as read-only. `.prefab` and `.meta` files are text (YAML), so they can be parsed without the editor.
- Every item carries its source (prefab path or screenshot path). Decisions such as "standard" or "deprecated" are confirmed by people.

**Platform items to record during collection**

| Item | What to record |
| --- | --- |
| Aspect ratio | Cropping and margins at 20:9 phones, 4:3 tablets, 16:10 (handheld PC), 21:9 |
| Safe Area | Whether notches are handled |
| States | Whether Hover and Focused (mouse, gamepad) states exist |
| Touch area | Touch targets smaller than `touch_min_px` (project.json) at the reference resolution |
| Text | Font assets and size variety, the smallest size |
| Canvas Scaler | Whether settings differ between canvases |

## Autonomous mode (default)

Agents run every step and gate; people only check `reports/FINAL.md` and the catalog at the end. This section overrides the "ask the user" and "human check" rules in the sections below.

| What a human used to do | In autonomous mode | Where the rationale is recorded |
| --- | --- | --- |
| H1 batch scope | A gate agent picks screens with the rules in `agents/H1.md`, then `batch.py create` -> `gate-done` | `reports/gates-<batch>.md` |
| H2/H3 answers | A gate agent picks options with the rules in `agents/H2.md`/`H3.md` and runs `record_decision.py --by agent --reason` | `by: agent` and `reason` in decisions.json |
| User check after 2 failures | `reset` and retry once; after 2 more failures `state.py skip` holds that chunk and the run continues | `reports/blockers.md` |
| Preparing screenshots | Skipped. Classification and verification use prefab data only; items without a visual check are flagged in the final report | `reports/FINAL.md` |
| Typing the start message for each new session | `run_audit.ps1` runs new sessions repeatedly with `claude -p` | `handoff/log.md` |

**Gate rules in short** (A0 writes them to `agents/H1.md`, `H2.md`, `H3.md`)

- H1: In the batch plan's folders, count View/Popup root prefabs and Units that are not nested in any other prefab as screens. Shared/common folders (project.json `common_dirs`, or folders the batch plan describes as common) collect shared components, so include all of them. Screens whose location is unclear (a top bar, a gacha/summon screen, ...) are found by name and script search plus nested-reference counts; if none is found, write that down in the rationale file and continue.
- H2: Standard candidates are chosen by node usage count -> screen usage count -> membership in a common folder -> ID order. Classification questions follow the rule-based classification; if still ambiguous, use `other` and flag it.
- H3: For near-identical values, the most used value becomes the token; values outside the cluster threshold stay as exceptions.
- Every agent decision is recorded as `by: agent`, so a person can change it at any time with `record_decision.py`.

**Final step F**: when the last batch's A6 is done, L0 rebuilds the catalog and writes `reports/FINAL.md`: fragmentation metrics before/after, the agent decisions (in the order a person should review them), held chunks, and items without a visual check. Finally it creates `handoff/DONE`, which stops the runner.

**Runner** (`ui-audit/run_audit.ps1`, run from the project root)

- Each round starts a fresh `claude -p` session with `ui-audit/` as its working folder and passes "Read handoff/START.md and follow it exactly".
- In `acceptEdits` mode, edits are auto-accepted only inside `ui-audit/`. Other writes are refused through `--permission-prompts none`.
- It stops when `handoff/DONE` exists, when `log.md` does not grow for two rounds in a row, or after the maximum number of rounds.

## Session management (top level)

The top level is the session manager (L0); each step is done by a newly started step lead (L1). The single source of truth for progress is `manifest.json`, and any session can resume by reading `handoff/START.md` alone, without this document.

| Level | Role | May read | Writes |
| --- | --- | --- | --- |
| L0 session manager | Decide the next action, delegate to L1, relay human questions and decisions, hand over | `handoff/START.md`, output of `state.py render` and `questions.py list` | manifest and decisions, only through scripts |
| L1 step lead | Run and verify one step, chunk by chunk | `agents/_common.md`, `agents/L1.md`, `agents/<step>.md`, output of `state.py show`, parts of the input files | that step's output files; that step in the manifest, through scripts |

By default there are no step agents (L2). Many environments do not let sub-agents start sub-agents, so L1 does the step itself and leaves bulk work to scripts.

**One source of truth for state**

- Step and chunk states, attempts, failures and limit counts live only in `manifest.json`.
- `handoff/STATE.md` is a summary that `scripts/state.py render` generates from the manifest. If they disagree, the manifest wins.
- L0 records "running" with `state.py start` right before delegating. The first `render --new-session` of a new session turns any leftover "running" into a crash. If L1 dies within the same session and leaves "running", `start` treats that as a crash too. `start` then deletes leftover `.tmp` files and resumes from the unfinished chunks.
- `start` fills the chunk list with per-step rules. A1 and A2: the batch's screens. A3: every kind that got new nodes in this batch, plus the old and new kinds of nodes whose classification changed in reopened A1/A2 chunks (split by signature groups above 300 nodes). A4: the 5 token categories. A5: the 6 pages. A6: the kinds changed in this batch.
- `start` takes a `.bak` snapshot only if that step/batch has none yet; all of a batch's snapshots are deleted when its A6 reaches `step-done`. So even after invalidation and re-runs, work starts from the point before the batch began.

**The 50% limit and measurable substitutes**

Agents cannot know their context usage exactly. If the environment shows usage, use it; otherwise apply the substitutes below. The numbers are initial values, to be tuned after batch 1.

| Level | 40% substitute (start no new work) | 50% substitute (hand over now) |
| --- | --- | --- |
| L0 | 4 delegations or 2 rounds of human checks | 6 delegations or 3 rounds of human checks |
| L1 | 30 tool calls | 45 tool calls |

- One round of human checks = showing the list of questions once and recording the answers, regardless of how many questions.
- L1 reads at most 200 lines of a file at a time, never reads whole JSON files (aggregates with scripts), and looks at no more than 10 images per chunk.
- A chunk ended by a limit gets `limitHits` + 1; the next L1 skips finished chunks and continues from unfinished ones.
- When a chunk reaches `limitHits` 2, `start` splits it in half. Only if it cannot be split further does it count as one failure.
- Failures (`failures`) are: A6 reopens, failed `step-done` checks, and limit overruns that cannot be split. Session drops (`crashes`) are not failures.
- If a `step-done` check fails, the script returns the offending chunks to "waiting" and records the reason in `reopen`. The next L1 receives that reason from `show`.
- At 2 failures, render reports "user check needed"; once a direction is chosen, L0 releases it with `state.py reset`.

**Handover files and resuming**

| File | Content | Rule |
| --- | --- | --- |
| `handoff/START.md` | the L0 start message | created by A0, regenerated only by `--docs-only` |
| `handoff/STATE.md` | manifest summary: current step, next action, open question count, one metrics line | generated by a script, at most 40 lines |
| `handoff/log.md` | one line per finished step or chunk | appended by scripts; read only the last 10 lines |

A new session starts with the single line `Read ui-audit/handoff/START.md and follow it exactly`. A person can type it, or a script can repeat it. In Claude Code you can also put that line in the project's `CLAUDE.md`.

### L0 start message (`handoff/START.md`)

```
You are the session manager (L0) of the UI inventory and cleanup project. Work in autonomous mode: do not ask the user
anything; only decide, delegate and hand over. People check reports/FINAL.md and catalog/ only at the end.
The Unity project (..) is read-only. Apply the project's CLAUDE.md principles as "when unsure, do not guess: record the
decision together with its evidence".
Scripts print Korean in this version. Key markers in python scripts/state.py render output:
"다음 행동" = next action, "명령" = command, "관문 에이전트 위임" = delegate to a gate agent,
"사용자 확인 필요" = user check needed (2 failures), "최종 보고(F)" = final report (F),
"A5 재빌드" = A5 rebuild, "A6 재검증" = A6 re-verify, "H2 추가 확인" / "H3 추가 확인" = additional H2/H3 check,
"완료" = done.

[Start - first run and resume alike]
1. If handoff/DONE exists, print the single line "already done" and exit.
2. Run python scripts/state.py render --new-session and read only its output. Do not open data/ or catalog/.
3. If manifest.json does not exist (render prints "A0 준비가 먼저 필요합니다" = A0 preparation needed first),
   print "A0 preparation needed" and exit.

[Loop - follow the "다음 행동" (next action) line of the render output]
4. If it is a step (A1-A6, including "A5 재빌드" and "A6 재검증"): run python scripts/state.py start <batch> <step>,
   then give a new sub-agent (L1) only this one line: "Read agents/L1.md and perform batch=<batch> step=<step>".
5. If it is a gate (H1, H2, H3, "H2 추가 확인", "H3 추가 확인"): give a new sub-agent only this one line:
   "Read agents/<H1|H2|H3>.md and decide the gate for batch=<batch>".
   The gate agent records the decisions and runs gate-done itself.
6. If render reports "사용자 확인 필요" (user check needed, 2 failures): if this is the first time for that step, run
   python scripts/state.py reset <batch> <step> and continue. If that step was already reset once, run
   python scripts/state.py skip <batch> <step> --reason "<the failure reason shown by render>" and continue.
7. If render reports "최종 보고(F)" (final report): give a new sub-agent "Read agents/F.md and write the final report".
   When it finishes, check that handoff/DONE exists and exit.
8. After every sub-agent finishes, decide again with python scripts/state.py render.

[Handover]
- If the environment shows usage: stop new delegations at 40%, hand over at 50%.
- If not: stop new delegations after 4 delegations, hand over at 6 delegations.
- To hand over: run python scripts/state.py render to refresh STATE.md, print the single line "handover" and exit.
  run_audit.ps1 starts the next session automatically. Do not ask the user for anything.
```

### L1 instructions (`agents/L1.md`)

```
You are the step lead (L1). Handle only the batch and step you were given, then exit.
Read: agents/_common.md, agents/<step>.md (input, chunks, outputs and done conditions at the top),
      the output of python scripts/state.py show <batch> <step> (remaining chunks, reopen reason).
      show prints Korean labels: "남은 조각" = remaining chunks, "완료 조각" = done chunks, "보류 조각" = held chunks
      (skip them), "reopen 사유 (먼저 해결)" = reopen reason (resolve first), "명령" = commands.

1. Start with the unfinished chunks that show lists. Do not redo finished chunks.
   If there is a reopen reason, resolve it first.
2. Per chunk: write the output to *.tmp -> pass python scripts/validate.py <files> -> rename
   -> python scripts/state.py chunk-done <batch> <step> <chunk> --calls <tool calls so far>.
3. When every chunk is done, run python scripts/state.py step-done <batch> <step>.
   It checks the done conditions from spec/steps.json. If a check fails, it returns the offending chunks to waiting
   and records the reason; if you are within your limits, run show again and handle those chunks, otherwise exit.
   If the step has been invalidated, this command is refused.
4. If you recorded a reopen in A6, exit without step-done.

Limits: at 30 tool calls, start no new chunk. At 45, abandon the current chunk,
        run python scripts/state.py limit <batch> <step> <chunk> and exit.
        Read at most 200 lines of a file at a time, never whole JSON files (aggregate with scripts), at most 10 images per chunk.
Return (5 lines or fewer): result, chunks finished, chunks remaining, number of new questions.
```

## Orchestration flow

After A0, the L0 session manager hands one batch to a fresh L1 per step, from A1 to A6; people decide only at H1-H3 (in autonomous mode, gate agents decide and record their reasons). Decisions accumulate in `decisions.json` and apply to every later batch.

```
H1 batch scope -> A1 collect -> A2 classify -> A3 group -> H2 groups/standards
  -> A4 tokens -> H3 token decisions -> A5 catalog build -> A6 verify -> (next batch: H1 ...) -> F final report
```

After A6, the next batch starts again from H1, and the same catalog grows batch by batch.

## Agent definitions

The steps are A0 preparation (once) and A1-A6, with the gates H1-H3. A0 copies the code blocks below verbatim into files under `agents/`; each file begins with its input, chunks, outputs and done conditions, so no session reads this document afterwards. The table summarises them.

| Step | Chunk unit | Output files | How it ends |
| --- | --- | --- | --- |
| A0 preparation | none | `agents/`, `spec/`, `schemas/`, `scripts/`, `handoff/`, `project.json`, `manifest.json`, `decisions.json`, `questions.json` | self-tests pass, render's next action is H1 |
| H1 batch scope (blocking) | none | `batches/<batch>.json` | `batch.py create` -> `gate-done` |
| A1 collect | one screen prefab | `data/inventory/<batch>/<screen>.json` | `step-done` |
| A2 classify | one screen | `data/classified/<batch>/<screen>.json` | `step-done` |
| A3 consolidated analysis | one kind with new nodes (split above 300) | `data/groups/<kind>.json`, `data/registry/<kind>.json`, `data/metrics/<kind>.json` | `step-done` |
| H2 groups/standards | none | `decisions.json` | `gate-done` even without answers |
| A4 token extraction | one token category | `data/tokens/<category>.json` | `step-done` |
| H3 token decisions | none | `decisions.json` | `gate-done` even without answers |
| A5 catalog build | one page | `catalog/` | `step-done` |
| A6 verification | one kind changed in this batch | `reports/review-<batch>.md` | `step-done` if no problem; otherwise `reopen` and exit |

`step-done` marks a step done only after a script checks the done conditions listed in `spec/steps.json` (all chunks done, schema validation, per-step checks). Scripts do the bulk work; agents look only at the edge cases the scripts cannot decide.

### Common rules (`agents/_common.md`)

```
- The Unity project is read-only. Its path and UI system are in project.json.
- Write every output to <file>.tmp and rename it only after python scripts/validate.py passes.
  .bak snapshots and cleanup of leftover .tmp files are done by state.py start; do not do them yourself.
- Name chunks and files with English slugs (button, slot, color, nineslice, ...). Display names may be in any language.
- decisions.json is read-only for you. Never change groups, tokens or classifications that a person decided.
- Never write a value without a source (prefab path#hierarchy path, or a screenshot path). If an estimate is needed, leave a question:
  python scripts/questions.py add --gate <H2|H3> --target <id> --options "<option 1>|<option 2>"
- Do not read planning documents. Everything you need is in agents/, spec/, schemas/ and project.json.
- Scripts print Korean messages in this version; read them as they are.
```

### A0 preparation (run once, in a session that has this document)

```
Prepare ui-audit/ from this roadmap. Later sessions work from the files alone, without this document.
If manifest.json already exists, refuse to run, because progress would be lost (only with --force-reset when the user says so explicitly).
1. Folder structure and schemas/*.json: manifest, project, batch, inventory, classified, groups,
   registry, metrics, tokens, token-registry, decisions, questions
2. agents/_common.md, L1.md, A1-A6.md, H1-H3.md, F.md: copy the code blocks of this document verbatim
   (including input, chunks, outputs and done conditions at the top)
3. spec/catalog.md (the table and rules of the "HTML catalog layout" section), spec/steps.json (done-condition checks per step),
   spec/batch-plan.json (batch order and candidate folders - written by the person preparing the project, from the
   "Incremental cleanup" section)
4. handoff/START.md (the L0 start message), handoff/STATE.md, handoff/log.md (empty)
5. scripts/
   state.py: render [--new-session] · show · start · chunk-done [--calls N] · step-done · limit
             · reopen <batch> <step> --chunks <chunks> --reason "<reason>" · gate-done · reset · skip
             (chunk-done, step-done, limit and reopen append one line each to log.md)
   batch.py suggest/create · questions.py add/list/close · record_decision.py · validate.py
   parse_prefab.py · classify_rules.py · group.py · cluster_values.py · build_catalog [--check]
   each with a self-test
6. project.json (Unity path, uGUI/UI Toolkit, reference resolution), manifest.json (batch b1, next action H1),
   decisions.json and questions.json (empty lists)
Done when: self-tests pass and the next action of state.py render is "H1 배치 범위 확인" (H1 batch scope).

After editing this document, run with --docs-only: it regenerates only items 2 and 3, schemas/ and START.md,
and does not touch scripts/, data/ or state files. At the end it runs every script self-test and validates existing data;
if they disagree with the new schemas, it reports what disagrees and stops.
```

### A1 collect (`agents/A1.md`)

```
Input: batches/<batch>.json, the Unity path in project.json
Chunk: one screen prefab
Output: data/inventory/<batch>/<screen>.json
Done when: every screen chunk of the batch is done and the schema passes

Extract UI nodes with python scripts/parse_prefab.py and record them. Per node:
id (prefab path#hierarchy path), component type, size, anchors, color, sprite path (GUID -> .meta),
9-slice border, LayoutGroup spacing/padding, font asset and size, nested prefab source, screen.
Collect GUIDs that cannot be resolved, missing sprites, and empty containers that look filled by code in unresolved.
```

### A2 classify (`agents/A2.md`)

```
Input: data/inventory/<batch>/<screen>.json, input/screenshots/<batch>/ (optional), classification decisions in decisions.json
Chunk: one screen
Output: data/classified/<batch>/<screen>.json
Done when: every node is classified or turned into a question, and the schema passes

First run python scripts/classify_rules.py to handle nodes that can be classified from name and component makeup alone,
and classifications a person decided; classify only the remaining nodes yourself (against screenshots if they exist).
Kinds (slug = meaning):
  button = button, tab = tab, toggle = toggle, popup = popup frame, slot = slot, gauge = gauge,
  currency = currency display, reddot = red dot (notification badge), tooltip = tooltip, toast = toast,
  listcell = list cell, icon = icon, textstyle = text style, decor = background/decoration, other = other
Record: node id / kind slug / basis / confidence (high|medium|low).
For low confidence: python scripts/questions.py add --gate H2 --target <node id> --options "<slug1>|<slug2>".
```

### A3 consolidated analysis (`agents/A3.md`)

```
Input: the target nodes of that kind as reported by state.py show - new nodes of this batch, plus existing nodes whose
       classification changed in reopened A1/A2 chunks / the inventory values of those nodes /
       data/registry/<kind>.json (always start from this batch's .bak snapshot)
Chunk: one kind (start splits it into signature groups when there are more than 300 target nodes)
Output: data/groups/<kind>.json, data/registry/<kind>.json, data/metrics/<kind>.json
Done when: every target node belongs to a group of its current kind, 0 nodes remain in another kind's groups,
           0 existing group IDs changed (except entries recorded in aliases/retired), and the schema passes

1. With python scripts/group.py, assign target nodes to existing groups by signature (sprite, size step, color, font);
   group only the nodes that fit no existing group, and give them new IDs.
   Remove reclassified nodes from their old kind's groups and assign them again. Record groups that became empty as retired.
   Do not regroup any other existing node.
   If the reopen reason is a re-split, regroup the whole kind, but record the ID mapping in aliases/retired.
2. Decide only edge cases and the rationale for standard candidates yourself.
3. Write all three files as .tmp, validate them together, then rename in the order groups -> registry -> metrics.
   Re-running the chunk starts from the snapshot, so it produces the same result.
```

### A4 token extraction (`agents/A4.md`)

```
Input: values in data/inventory/, the groups in data/groups/, data/token-registry/<category>.json, decisions.json
Chunk: one token category - color, type (typography), spacing (spacing, padding, anchor margins), nineslice (9-slice, corners), size (size steps)
Output: data/tokens/<category>.json, data/token-registry/<category>.json
Done when: every value maps to a token or to exceptions, 0 existing token IDs changed (except aliases/retired), and the schema passes

Collect values with python scripts/cluster_values.py, first assign them to existing tokens in token-registry,
and cluster only values that fit no existing token into new IDs (category + short hash of the first value).
Keep grade/rarity colors and attribute colors in separate groups.
When tokens merge or split, record it in aliases/retired. Never reuse an ID.
Record: token drafts, original value -> token mapping, usage counts, exceptions.
```

### A5 catalog build (`agents/A5.md`)

```
Input: all of data/, decisions.json, spec/catalog.md
Chunk: one page - index, tokens, components, screens, refactor-map, decisions
Output: catalog/
Done when: every page is generated and build_catalog --check reports 0 broken links and images

Let scripts/build_catalog generate the page from data and decisions. Never edit HTML by hand.
If you changed the script, make its self-test pass again.
If a deprecation decision has no replacement, show "replacement undecided" in refactor-map,
and show decisions changed by retired/aliases as warnings on index.
```

### A6 verification (`agents/A6.md`)

```
Input: catalog/, data/, the source prefabs and screenshots
Chunk: one kind changed in this batch
Output: reports/review-<batch>.md
Done when: every chunk has at least 5 sample checks recorded

Do not look at the work records of earlier steps (log, intermediate outputs).
Check at least 5 samples per chunk against the sources: classification, size and color values, source links, whether decisions are applied.
Report format (the done-condition check counts these literally): one section "## <chunk>" per chunk, and inside it
at least 5 lines that start with "- 표본" (Korean for "sample"), e.g. "- 표본 1: <node id> - classification ok, size ok, ...".
If there is a problem, find the step that caused it, record a reopen, and exit without step-done.
- If the cause is collection or classification (A1/A2), open that chunk in the batch where the cause is:
  python scripts/state.py reopen <cause batch> <A1|A2> --chunks <screens> --reason "<what was wrong and what was expected>"
- If the cause is A3 or later (groups, tokens, catalog), always open it in the current batch, even if the cause is in an earlier batch.
  Outputs from A3 on are cumulative data across all batches, so rebuilding them in the current batch is enough.
  python scripts/state.py reopen <current batch> <A3|A4|A5> --chunks <chunks> --reason "<...>"
reopen invalidates every later step of the current batch. The script refuses requests to open A3 or later of an earlier batch.
```

### H1 batch scope decision (`agents/H1.md`)

```
Input: this batch's candidate folders in spec/batch-plan.json, cache/guid-index.json, the Unity project (read-only)
Output: batches/<batch>.json, reports/gates-<batch>.md (decisions and rationale)
Done when: batch.py create succeeds and state.py gate-done <batch> H1 succeeds

1. Get the candidates with python scripts/batch.py suggest <batch>.
2. Count as screens: View/Popup root prefabs + Units that are not nested in any prefab.
   Shared/common folders (project.json common_dirs, or folders that spec/batch-plan.json describes as common/shared)
   collect shared components, so include all of them.
3. Find screens whose location is unclear (a top bar, a gacha/summon screen, ...) by prefab and script name search
   (for example TopBar|CurrencyBar|MenuBar, Gacha|Summon|Recruit|Pickup|Draw) and nested-reference counts.
   Also follow the "questions" of this batch in spec/batch-plan.json.
   If there are several candidates, include them all; if there are none, write "not found" in the rationale file.
4. Do not ask for screenshots. If there are none, continue without them.
5. python scripts/batch.py create <batch> <prefab paths...> -> python scripts/state.py gate-done <batch> H1.
6. In reports/gates-<batch>.md write "H1: what was included and excluded, and by which rule number" in 20 lines or fewer.
```

### H2 group/standard decision (`agents/H2.md`)

```
Input: output of python scripts/questions.py list H2, data/groups/ and data/metrics/ (aggregate with scripts)
Output: decisions.json (by: agent), an H2 section appended to reports/gates-<batch>.md
Done when: 0 open H2 questions and state.py gate-done <batch> H2 succeeds

For every question, pick one option by these rules in order:
- Standard candidate: higher node usage count -> higher screen usage count -> membership in a common folder -> ID in dictionary order.
- Classification question: follow the classify_rules.py result; if still ambiguous, other.
python scripts/record_decision.py --question <q-id> --pick <number> --by agent --reason "<rule applied and the numbers>"
When done, run python scripts/state.py gate-done <batch> H2.
```

### H3 token decision (`agents/H3.md`)

```
Input: output of python scripts/questions.py list H3, data/tokens/ (aggregate with scripts)
Output: decisions.json (by: agent), an H3 section appended to reports/gates-<batch>.md
Done when: 0 open H3 questions and state.py gate-done <batch> H3 succeeds

For every cluster of near-identical values, make the most used value the token and keep values outside the cluster threshold as exceptions.
python scripts/record_decision.py --question <q-id> --pick <number> --by agent --reason "<usage counts and differences>"
When done, run python scripts/state.py gate-done <batch> H3.
```

### F final report (`agents/F.md`)

```
Input: data/metrics/, decisions.json, reports/gates-*.md, reports/review-*.md, reports/blockers.md, catalog/
Output: reports/FINAL.md, handoff/DONE
Done when: build_catalog --check passes, FINAL.md is written, handoff/DONE exists

1. Rebuild and check the whole catalog with python scripts/build_catalog --check.
2. reports/FINAL.md (at most 2 pages):
   - a one-line conclusion and fragmentation metrics before/after (variants per kind, distinct colors, font size variety,
     and naming-rule compliance if project.json naming_doc is set)
   - agent decisions for a person to review: most affected screens first, with decision ID, target, rule, and the command to change it
   - held chunks (blockers.md) and items without a visual check
   - the 3 catalog pages to open first
3. Write one line with the completion time to handoff/DONE.
```

## Workspace and data layout

State and instructions all live as files in `ui-audit/`. After A0 any session can resume from this folder alone, and the three state files change only through scripts.

```
ui-audit/
  project.json           Unity path, uGUI/UI Toolkit, reference resolution
  manifest.json          the single source of truth for progress (changed only by scripts/state.py)
  decisions.json         human decisions (appended only by scripts/record_decision.py)
  questions.json         open questions (added/closed only by scripts/questions.py)
  handoff/   START.md  STATE.md  log.md
  agents/    _common.md  L1.md  A1.md ... A6.md  H1.md  H2.md  H3.md  F.md
  spec/      catalog.md  steps.json  batch-plan.json
  schemas/   *.json
  scripts/   state.py  batch.py  validate.py  questions.py  record_decision.py
             parse_prefab.py  classify_rules.py  group.py  cluster_values.py  build_catalog
  batches/<batch>.json
  input/screenshots/<batch>/<screen>_<ratio>.png
  data/
    inventory/<batch>/<screen>.json
    classified/<batch>/<screen>.json
    groups/<kind>.json
    registry/<kind>.json         group ID ledger (including aliases, retired)
    metrics/<kind>.json
    tokens/<category>.json
    token-registry/<category>.json   token ID ledger (including aliases, retired)
    .bak/<step>-<batch>/         snapshots kept until the batch's A6 is done
  previews/
  catalog/                       generated (never edit by hand)
  reports/
```

**Write rule**: every file is written to `.tmp` and renamed only after schema validation. Data is split into files per batch, screen, kind and category, so an interrupted chunk cannot corrupt other chunks' results. Only `decisions.json` and `questions.json` accumulate in one file; scripts add one entry at a time and rewrite the whole file through `.tmp` each time.

**manifest.json** - step states are `대기` (waiting), `진행` (running), `완료` (done), `무효` (invalidated) and `실패` (failed); chunks also use `보류` (held). `attempts` = how many times an L1 was started, `failures` = A6 reopens plus limit overruns that cannot be split, `crashes` = session drops (not counted as failures). `reopen` holds the chunks, the reason and the requesting step, and `show` prints it as is.

```
{
  "current": {"batch": "b2", "next": "A3"},
  "batches": {
    "b2": {
      "gates": {"H1": "완료", "H2": "대기", "H3": "대기"},
      "steps": {
        "A3": {
          "status": "진행",
          "attempts": 2, "failures": 0, "crashes": 1,
          "failedBy": "crash",
          "startedAt": "2026-01-01T09:10:00+00:00",
          "reopen": {"chunks": ["slot"], "reason": "slots with different grade frames were grouped together", "by": "A6"},
          "chunks": {
            "button": {"status": "완료", "limitHits": 0, "calls": 22},
            "slot": {"status": "진행", "limitHits": 1, "calls": 0},
            "gauge": {"status": "대기", "limitHits": 0, "calls": 0}
          }
        }
      }
    }
  }
}
```

**decisions.json / questions.json entries** (`type` and `status` values are Korean literals the scripts use: type `그룹` group, `토큰` token, `분류` classification, `템플릿` template; status `표준` standard, `폐기` deprecated, `예외` exception, `분류` classification)

```
{"id": "d-0009", "type": "그룹", "target": "button-a3f2", "status": "폐기", "to": "button-7c1e",
 "supersedes": "d-0007", "memberSnapshot": ["Assets/UI/Shop/ShopView.prefab#Root/Footer/BuyBtn"],
 "by": "user", "at": "2026-01-02", "batch": "b2", "questionId": null}

{"id": "q-0012", "gate": "H2", "batch": "b1", "status": "open", "target": "button-a3f2",
 "text": "Which of the two shop buy-button variants should be the standard?",
 "options": [{"label": "button-a3f2", "action": "button-a3f2 표준"},
             {"label": "button-7c1e", "action": "button-7c1e 표준"}],
 "evidence": ["previews/button-a3f2.png", "previews/button-7c1e.png"]}
```

**Decision rules** (enforced by `record_decision.py`)

- When a target has several decisions, the last one wins and links the earlier one through `supersedes`.
- Alias IDs are recorded as the current ID; retired IDs produce an error that shows the candidate IDs that took over. Groups and tokens follow the same rule.
- A deprecation without `--to` is recorded as "replacement undecided" and shown as such in refactor-map.
- Answering with `--question <q-id> --pick <number>` records that option's action and closes the question as answered. For a classification question, that screen's A2 chunk is reopened.
- Deciding by ID directly also closes open questions about the same target as answered.
- Recording a decision invalidates A5 and A6 of the current batch. If that batch is already finished, or the next batch is at H1, render first reports "A5 재빌드 -> A6 재검증" (A5 rebuild -> A6 re-verify) as the next action.

**ID rules**

- Node ID = prefab path + `#` + hierarchy path
- Group ID = kind + short hash of the visual signature at creation (for example `button-a3f2`). Once assigned, it stays in `data/registry/<kind>.json` and is never reused.
- When groups merge or split, `aliases` and `retired` track it, and decisions store a `memberSnapshot` so you can see what was originally decided.

**Item states**: agents only write `미검토` (unreviewed) and `후보` (candidate); `표준` (standard), `폐기` (deprecated) and `예외` (exception) come only from `decisions.json`.

| State | Meaning | Decided by |
| --- | --- | --- |
| `미검토` unreviewed | collected only | agent |
| `후보` candidate | proposed as the standard by an agent | agent |
| `표준` standard | use only this from now on | person |
| `폐기` deprecated | to be replaced by the standard | person |
| `예외` exception | intentionally different (event-only, ...) | person |

**Re-runs and invalidation**

- `reopen` reopens only the given chunks of the given batch and step, and invalidates every later step of the current batch.
- Earlier batches can only reopen A1/A2. Outputs from A3 on are cumulative across batches, so they are always rebuilt in the current batch, and `state.py reopen` enforces this. That way the current batch's snapshot never overwrites a fix made to an earlier batch.
- When A1/A2 of an earlier batch are reprocessed, nodes whose classification changed are automatically added to the current batch's A3 chunks and reassigned.
- H2/H3 gates are never invalidated. If a re-run creates new open questions, render reports "H2 추가 확인" or "H3 추가 확인" (additional H2/H3 check) as the next action before moving past that gate. The last batch behaves the same.
- At 2 failures, render reports "user check needed"; once a direction is chosen, L0 releases it with `reset`.

The "A5 rebuild -> A6 re-verify" after a decision runs under the name of the last finished batch. If that A6 finds a problem in A3 or later, it does not reopen immediately; the reason is passed to the next batch's A3 chunk and handled after that batch's A1/A2.

## HTML catalog layout

The catalog is static HTML that shows, in one place, "what is scattered and how much" and "what to consolidate it into". It opens directly from disk and is regenerated in full after every batch.

| Page | Shows | Used for |
| --- | --- | --- |
| `index.html` overview | fragmentation metrics (variants per kind, distinct colors, font size variety), batch progress, open questions | deciding what to clean up first |
| `tokens.html` tokens | color, typography, spacing and corner token drafts, original value -> token mapping, usage counts, exceptions | organising design variables |
| `components/<kind>.html` | gallery of variant groups, standard candidates and their differences, which states exist (Normal, Pressed, Disabled, Hover, Focused), screens that use them, prefab paths | organising component design |
| `screens/<screen>.html` | screen screenshots, components used, share of standard usage, recorded platform items | screen-level improvements |
| `refactor-map.html` | deprecated -> standard mapping, prefab paths, affected screen count, replacement difficulty | units of partial refactoring work |
| `decisions.html` | confirmed decisions and dates | history |

**How decisions get in**: the catalog is static HTML and is never edited by hand. Tell the L0 session manager something like "button-a3f2 standard"; the decision script checks the ID, records it in `decisions.json`, and the next build reflects it. A button that copies each item's group ID makes this easy.

**Using it for design work**

- On a component page, review the standard candidates and their differences, confirm a standard, and build only confirmed standards as components in your design tool.
- Confirm the merge proposals on the token page and move them into design variables.

**Using it for partial refactoring**

- In `refactor-map.html`, pick items with many affected screens and easy replacements first, and cut them into work units.
- After the work, run the same batch again and check that the share of standard usage per screen went up.

## Incremental cleanup

Instead of looking at everything at once, split screens into batches, most-used first, and repeat H1 -> A1 -> A2 -> A3 -> H2 -> A4 -> H3 -> A5 -> A6. A1/A2 process only that batch; A3-A6 reprocess all accumulated data chunk by chunk and refresh the catalog.

**Batch order (suggested)** - written to `spec/batch-plan.json` with real folders under `ui_root` as candidates:

1. Lobby, top bar, common popups
2. The main feature screens (for example character, inventory)
3. Store and gacha/summon screens, if the game has them
4. Remaining screens, event screens

**Operating rules**

- The source of truth for order and rules is `handoff/START.md` and the `agents/` files. When you edit this document, re-run A0 with `--docs-only` to refresh only `agents/`, `spec/catalog.md`, `schemas/` and START.md. That run ends with every script self-test and a validation of existing data, and stops with a message if they disagree.
- `--docs-only` never touches `scripts/`, data or state files. A full A0 refuses to run when manifest.json exists.
- A person can tell L0 a decision at any time, not only at H steps; it is recorded, A5/A6 of the current batch are invalidated, and the next delegation applies it.
- No agent ever overwrites a decision a person made.
- The catalog must always be reproducible from scratch with `build_catalog`.

**Main risks**

| Risk | Mitigation |
| --- | --- |
| UI generated by code at runtime does not appear in prefab YAML | A1 collects empty containers as unresolved; A6 compares with screenshots and leaves questions about what is missing |
| Script bugs accumulate wrong data | A0 self-tests, schema validation on every write, A6 sample checks, `.bak` snapshots for rollback |
| A3/A4 workload grows with every batch | chunks per kind and category; clustering is done by script thresholds |
| Substitute limits do not match real usage | after batch 1, tune them from the per-chunk tool-call counts in log.md |

**Next steps**

- [ ] Decide the path agents use to read the Unity project (repository or folder)
- [ ] Confirm uGUI vs. UI Toolkit (the parsers support uGUI)
- [ ] Write `project.json` and `spec/batch-plan.json`, then run A0 preparation once
- [ ] Optional: prepare screenshots for batch 1 (16:9, 20:9, 4:3)
- [ ] Start a new session with "Read ui-audit/handoff/START.md and follow it exactly", or run `run_audit.ps1`

## Adversarial review of the handover design

A separate review agent that had not seen the design checked it five times until it **passed**. The single pass criterion: a fresh L0 or L1 started at any point after A0 must be able to continue using only the files A0 created, without opening this document or guessing commands or fields, and without lost work, silent corruption or infinite loops.

| Round | Verdict | Key findings | Applied |
| --- | --- | --- | --- |
| 1 | fail (15) | instructions only existed in the document, two sources of state, infinite restarts at the 50% limit, group IDs renumbered | A0 preparation added, manifest as single source, per-chunk resume, ID ledgers |
| 2 | fail | done conditions not moved into files, no command to end H1, no reopen reason, A3 chunks too big, session drops not detected | per-file done conditions and steps.json, gate-done and batch.py, reopen reasons, incremental assignment and auto-split, render --new-session |
| 3 | fail (2 high) | no way out when step-done fails, reclassified nodes stayed in old groups | return chunks on failure and count failures, reassign reclassified nodes, keep snapshots |
| 4 | fail (1 new high) | reopening A3 of an earlier batch collided with the kept snapshot | earlier batches can only reopen A1/A2 |
| 5 | pass | no high findings left | the 2 remaining medium/low findings applied too |

**Situations simulated**

- A session drops in the middle of an A3 chunk and a new L0 resumes
- A new L1 runs A4: every file it reads and every command it runs comes from A0 outputs
- A person's deprecation decision (with a replacement) three sessions later
- A6 finds the cause in an earlier batch's A2 and reopens it
- The next batch starts at H1 after a batch completes
- A0 `--docs-only` re-run after editing the document

**Remaining limits**

- The review covered the design document. Real behaviour of the scripts must be confirmed by the A0 self-tests and by running batch 1 on a real project.
- The substitute limits (30/45 tool calls, 4/6 delegations, 300 nodes per chunk) are initial values; tune them from the per-chunk call counts in log.md after batch 1.
