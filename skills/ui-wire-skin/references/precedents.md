# Precedent catalog (template)

This file is **project data**. It starts empty; fill it with the precedents of your own game as you find them. Agents read it before deciding any placement or visual expression (SKILL.md sections 3 and 4-0), so a well-kept catalog saves a precedent search on every screen.

## How to fill it

1. **Search**, do not guess. For each element, run (from your track folder, after copying `scripts/` to `tools/`):
   ```
   python tools/find_precedents.py --name "<node name regex>" [--template <slug>] [--region x,y,w,h] [--include-inactive] --sheet <out.png>
   ```
   It searches `ui-audit/data/layout/screen/*.json` and crops `ui-audit/previews/layout/screen/<slug>.png` into one contact sheet.
2. **Look at the crops** and confirm the role is really the same. For states that are off in the default render (Selected, Disabled, ...), follow the prefab's Image `m_Sprite` guid through `ui-audit/cache/guid-index.json` to the sprite.
3. **Count across all screens** for composition questions ("how many main panels per screen?"); a single matching screen is not a precedent rule.
4. **Write the entry** below with: screens (layout slugs), node path or template slug, rect (x,y,w,h on the 1280x720 canvas used by the layout data), what it looks like, and constraints. Date the section header when you do a full count.
5. **Record negatives too**: "no precedent" entries prevent the next agent from searching again and tell the user a pattern would be new.

Evidence sources: `ui-audit/data/layout/screen/*.json` (nodes, rects, template slugs), `ui-audit/previews/layout/screen/*.png` (default-state renders), prefab YAML (states that are off by default), `Docs/ui-design-system/screens.jsonl` (`cleanReference`, recipes).

## Scene composition (basis for S3-0) - <date of full count>

Main panel = <template slug of your main panel/sheet>, measured by <node that marks its bounds>.

| Form | Screens (panel rect) | Notes |
|---|---|---|
| <e.g. docked right, flows off the right/bottom edge> | <screen x,y,w,h> ... | |
| <e.g. full width at the bottom> | | |
| <e.g. near full-screen (popup-like)> | | |

- **Left side (outside the panel)**: <what sits directly on the background, with screen + node + rect>
- **Panel header strip**: <icon / title / n/max / chips / divider, with an example screen and node rects>
- **Panel body**: <paper color, card style>
- **Tabs**: <cell size, position relative to the panel, alignment rule, selected/unselected art and text style>
- **Information row container**: <where rows with title/meta/buttons live>
- **List row templates**: <slug - when to use>
- **Selection marker**: <one grammar: frame / check / tint, with precedent screen and node>
- **Thumbnails**: <unit template that screens doing the same job use; empty-slot template>
- **Panel action buttons**: <where they sit, label rules>
- **Title plate**: <template slug, measured text height, help-button position>

## Screen skeleton

| Element | Precedent | Notes |
|---|---|---|
| Title plate | <slug, rect, number of screens sharing it> | <what cannot be changed per screen> |
| Back button | <slug, rect> | |
| Help button | <screen> | |
| Information below the title | <single headline number / sub-menu precedents> | <what has no precedent> |

## Panels and tabs

| Element | Precedent | Notes |
|---|---|---|
| Main panel | | |
| Tabs | | <what kinds of switching tabs are used for; patterns with no precedent> |
| Panel action buttons | | |
| Panel header numbers (n/max) | | |
| Disabled tab | <precedent or "none"> | |

## State expression

| State | Precedent | Expression |
|---|---|---|
| List row selected | | |
| Grid tile selected | | <do not reuse for rows if it is tile-specific> |
| Thumbnail selected | | |
| Tab selected | | |
| Locked / done / target | | |

## Buttons and colors

| Element | Precedent | Notes |
|---|---|---|
| Primary action | <slug, size, usage count> | <one per region> |
| Cancel | | |
| Destructive | | |
| Rank/grade art | <asset path> | |
| Currency icons | <asset path> | <look-alike assets to avoid> |

## Shared screens and units

| Purpose | Precedent | Constraints |
|---|---|---|
| Toast | | <e.g. single line only> |
| Confirmation dialog | | <e.g. singleton, default cancel color> |
| Toggle | | |
| Small label button | | |
| Reward icon + amount | | |
| Linear progress bar | <precedent or "no shared one"> | |
| Chip / tag | | |
| List virtualization | | |
