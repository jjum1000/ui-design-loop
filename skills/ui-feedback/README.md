# ui-feedback

Claude's side of the design feedback loop: users leave feedback per component in the review viewer; this skill triages it, asks when unclear, edits the registered wireframe/mockup files, reruns measurements and records each fix (diff + before/after shots) through the `feedback.py` CLI. Users close or reopen items themselves.

## Install

- As part of the `ui-design-loop` Claude Code plugin: `/ui-feedback ShopView`.
- Without the plugin, copy this folder to `.claude/skills/ui-feedback/` in your Unity project. The measurement scripts it calls come from the `ui-wire-skin` skill (copied into each design track's `tools/` folder), so install that skill as well. Other agents (Codex and similar) can read `SKILL.md` directly.
- Do not copy or commit `__pycache__/` or `.ruff_cache/`.

## What it works with

All of these are installed into `<unity-project>/ui-audit/` by the toolkit:

- Review server `ui-audit/scripts/review_server.py` (user side: viewer, posting feedback, attachments)
- CLI `ui-audit/scripts/feedback.py` (Claude side: list, show, comment, claim, release, revise)
- Contract `ui-audit/feedback/CONTRACT.md` (events, states, API, permissions)
- Operations guide: `docs/feedback-loop.md` in this repository

The feedback log and attachments (`ui-audit/feedback/log.jsonl`, `attachments/`, `snap/`, `revisions/`) live on the machine that runs the review server. Do not commit them; run `/ui-feedback` on that machine so claim snapshots, revise diffs and the log stay on one disk.

## Quick start (user side)

```
python ui-audit/scripts/review_server.py
```
Open `http://127.0.0.1:8770/ui-audit/catalog/review.html?screen=ShopView&stage=mockup`, pick a component, leave feedback, then ask Claude `/ui-feedback ShopView`.

In v0.1 the viewer UI and CLI messages are in Korean.
