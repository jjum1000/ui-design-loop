"""Find existing-screen precedents for a UI element and make a contact sheet of render crops.

Usage (any folder inside the repo):
    python find_precedents.py --name "Tab\\d*|Tabs" --sheet tabs.png
    python find_precedents.py --name "Level|Power|Menu\\d" --region 0,0,640,300 --sheet title-area.png
    python find_precedents.py --name "Selected" --include-inactive
    MSYS_NO_PATHCONV=1 python "$(git rev-parse --show-toplevel)/.claude/skills/ui-wire-skin/scripts/find_precedents.py" --pattern "ChannelSlotTemplate/Selected" --include-inactive
      # path regex in Git Bash: MSYS_NO_PATHCONV=1 also stops /e/... conversion, so give the script a Windows path

Searches ui-audit/data/layout/screen/*.json node paths (and/or template slug), optionally only nodes whose
center lies in --region (x,y,w,h in 1280x720 canvas). Prints per screen: hit count, active hits, node names.
--sheet crops each matching screen's render (bounding box of hits + margin, or --region) into one image.
Inactive nodes (e.g. Selected states) are NOT visible in renders — follow the prefab's Image m_Sprite guid
through ui-audit/cache/guid-index.json to see them.
"""
import argparse
import json
import pathlib
import re
import sys

from PIL import Image, ImageDraw


def find_ui_audit() -> pathlib.Path:
    for d in [pathlib.Path.cwd(), *pathlib.Path.cwd().parents]:
        if (d / "ui-audit" / "data" / "layout").is_dir():
            return d / "ui-audit"
        if d.name == "ui-audit" and (d / "data" / "layout").is_dir():
            return d
    sys.exit("ui-audit/data/layout not found above the current folder")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", help="regex on node path (Git Bash mangles args containing '/': set MSYS_NO_PATHCONV=1 or use --name)")
    ap.add_argument("--name", help="regex on the node name only (last path segment) — no slashes needed")
    ap.add_argument("--template", help="template slug the node must be")
    ap.add_argument("--region", help="x,y,w,h — node center must be inside")
    ap.add_argument("--include-inactive", action="store_true", help="also match nodes that are inactive in the default render")
    ap.add_argument("--min-area", type=int, default=100, help="skip boxes smaller than this many px^2")
    ap.add_argument("--limit", type=int, default=12, help="screens in the sheet")
    ap.add_argument("--sheet", help="output contact sheet PNG")
    args = ap.parse_args()
    if not (args.pattern or args.name or args.template):
        ap.error("--pattern, --name or --template required")

    root = find_ui_audit()
    pat = re.compile(args.pattern, re.I) if args.pattern else None
    name_pat = re.compile(rf"^(?:{args.name})$", re.I) if args.name else None
    reg = [float(v) for v in args.region.split(",")] if args.region else None
    results = []
    for f in sorted((root / "data" / "layout" / "screen").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        hits = []
        for b in d["boxes"]:
            if b.get("loader") or b.get("sample") or b["w"] * b["h"] < args.min_area:
                continue
            if not args.include_inactive and not b.get("active"):
                continue
            if pat and not pat.search(b["path"]):
                continue
            if name_pat and not name_pat.match(b["path"].split("/")[-1]):
                continue
            if args.template and b.get("template") != args.template:
                continue
            if reg:
                cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
                if not (reg[0] <= cx <= reg[0] + reg[2] and reg[1] <= cy <= reg[1] + reg[3]):
                    continue
            hits.append(b)
        if hits:
            names = sorted({h["path"].split("/")[-1] for h in hits})
            results.append((d["slug"], hits, names))
    results.sort(key=lambda r: -len(r[1]))
    print(f"{len(results)} screens")
    for slug, hits, names in results:
        act = sum(1 for h in hits if h.get("active"))
        print(f"{slug:36s} hits={len(hits):3d} active={act:3d}  {names[:8]}")

    if args.sheet and results:
        tiles = []
        for slug, hits, _ in results[: args.limit]:
            png = root / "previews" / "layout" / "screen" / f"{slug}.png"
            if not png.exists():
                continue
            im = Image.open(png).convert("RGB")
            if reg:
                box = (reg[0], reg[1], reg[0] + reg[2], reg[1] + reg[3])
            else:
                x0 = min(h["x"] for h in hits); y0 = min(h["y"] for h in hits)
                x1 = max(h["x"] + h["w"] for h in hits); y1 = max(h["y"] + h["h"] for h in hits)
                box = (max(0, x0 - 40), max(0, y0 - 40), min(im.width, x1 + 40), min(im.height, y1 + 40))
            crop = im.crop(tuple(int(v) for v in box))
            crop.thumbnail((620, 300))
            tile = Image.new("RGB", (630, 330), "white")
            tile.paste(crop, (5, 25))
            ImageDraw.Draw(tile).text((6, 6), f"{slug}  ({len(hits)})", fill="black")
            tiles.append(tile)
        cols = 2
        rows = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 630, max(1, rows) * 330), "white")
        for i, t in enumerate(tiles):
            sheet.paste(t, ((i % cols) * 630, (i // cols) * 330))
        sheet.save(args.sheet)
        print("sheet ->", args.sheet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
