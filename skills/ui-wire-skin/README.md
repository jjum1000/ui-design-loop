# ui-wire-skin

Design one game UI screen with agents, on top of the design-system data that the `ui-audit` toolkit extracts from your Unity project: feature inventory -> wireframe -> scene composition -> skinned HTML mockup -> measured verification -> review -> comparison page.

## Install

- As part of the `ui-design-loop` Claude Code plugin, this skill is available as `/ui-wire-skin <screen>`.
- Without the plugin, copy this folder to `.claude/skills/ui-wire-skin/` in your Unity project. Other agents (Codex and similar) can read `SKILL.md` directly and follow it.
- Do not copy or commit `__pycache__/`.

## What it needs

- The `ui-audit/` workspace with generated data (`data/layout/`, `data/templates/`, `data/tokens/`, `previews/layout/`). Precedent searches and kit extraction only work in a checkout that has this data.
- Python 3.10+ with `playwright` (Chromium installed via `python -m playwright install chromium`), `Pillow`, and `opencv-python` + `numpy` (for `attention.py`).
- `shoot.py`, `attention.py` and `measure_a11y.py` only need an HTML mockup that follows the page contract in `SKILL.md`; they run anywhere.

## Relationship to other skills

- If your project has a generated design-system package (`Docs/ui-design-system/`, see the `ui-design-system` skill), its rules take precedence; this skill covers the design stage before prefabs.
- Mockups registered in `ui-audit/design/registry.json` can be reviewed in the feedback viewer and fixed with the `ui-feedback` skill.

## Files

| Path | Purpose |
|---|---|
| `SKILL.md` | The routine (stages, gates, rules) |
| `references/agent-prompts.md` | Prompt templates per stage |
| `references/pitfalls.md` | Mistakes that actually happened |
| `references/precedents.md` | Template for your project's precedent catalog (fill it as you go) |
| `scripts/shoot.py` | Screenshot every fixture state and check canvas, scroll, clipping, errors, off-kit colors |
| `scripts/attention.py` | Attention and information-density probe (font sizes, primary actions, motion, saliency) |
| `scripts/measure_a11y.py` | Touch target, font size and WCAG contrast per state |
| `scripts/find_precedents.py` | Find existing-screen precedents for a node and make a contact sheet of render crops |
