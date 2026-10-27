"""Screenshot + check an HTML mockup variant in every fixture state (headless, standalone).

Usage (copy this file to <track>/tools/ and run from the track folder, e.g. ui-audit/design/<screen>):
    python tools/shoot.py variant-a/index.html --out shots/variant-a [--strict-colors]

Page contract (globals may be top-level `const`/`function` or `window.*`):
  - #canvas is the 1280x720 safe area.
  - STATE_IDS (array) and loadState(id) switch fixture states.
  - optional window.stopTimers() freezes demo timers/animations before capture.
  - optional window.openDetail(missionId) + window.draftingIds(stateId): the first drafting
    mission of each state gets an extra "<state>-detail-<id>" shot.

Checks (FAIL unless noted):
  - console errors, page errors, failed requests (missing images/fonts/scripts)
  - broken <img>, #canvas not 1280x720, page wider than the 1920 viewport
  - clipped content: element with overflow hidden/clip whose content is taller than its box
  - scroll containers inside #canvas (reported only)
  - off-kit colors (reported; FAIL with --strict-colors): computed color/background/border
    inside #canvas whose RGB is not a hex value in kit/kit.css (<track>/kit/kit.css)
"""
import argparse
import json
import pathlib
import re
import sys

from playwright.sync_api import Page, sync_playwright

HERE = pathlib.Path(__file__).resolve().parent.parent
KIT_CSS = HERE / "kit" / "kit.css"
VIEWPORT = {"width": 1920, "height": 1080}
CANVAS_SIZE = (1280, 720)
RGB = tuple[int, int, int]

COLLECT_JS = r"""
() => {
  const canvas = document.querySelector('#canvas');
  const r = canvas.getBoundingClientRect();
  const colors = new Set();
  const scrollers = [];
  const clipped = [];
  const label = el => el.dataset.area || el.id || el.className.toString().slice(0, 40) || el.tagName;
  for (const el of [canvas, ...canvas.querySelectorAll('*')]) {
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    for (const p of ['color', 'backgroundColor', 'borderTopColor', 'borderBottomColor', 'borderLeftColor', 'borderRightColor', 'outlineColor', 'fill', 'stroke']) {
      const v = cs[p];
      if (!v || v === 'none') continue;
      if (p.startsWith('border') && cs[p.replace('Color', 'Width')] === '0px') continue;
      if (p === 'outlineColor' && cs.outlineStyle === 'none') continue;
      colors.add(v);
    }
    if (el === canvas || el.scrollHeight <= el.clientHeight + 2 || el.clientHeight === 0) continue;
    const info = { area: label(el), client: el.clientHeight, scroll: el.scrollHeight };
    if (['auto', 'scroll'].includes(cs.overflowY)) scrollers.push(info);
    else if (['hidden', 'clip'].includes(cs.overflowY)) clipped.push(info);
  }
  const imgs = [...document.images].filter(i => i.complete && i.naturalWidth === 0).map(i => i.getAttribute('src'));
  return { w: Math.round(r.width), h: Math.round(r.height), colors: [...colors], scrollers, clipped, brokenImgs: imgs,
           pageOverflowX: document.documentElement.scrollWidth > window.innerWidth + 1 };
}
"""


def kit_colors() -> set[RGB]:
    """RGB of every 6/8-digit hex literal in kit.css."""
    text = KIT_CSS.read_text(encoding="utf-8")
    return {tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
            for h in re.findall(r"#([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?\b", text)}


def parse_rgb(value: str) -> tuple[RGB | None, float | None]:
    """'rgb(1, 2, 3)' / 'rgba(1, 2, 3, 0.5)' -> ((1, 2, 3), alpha); anything else -> (None, None)."""
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", value)
    if not m:
        return None, None
    alpha = float(m.group(4)) if m.group(4) is not None else 1.0
    return tuple(int(float(m.group(i))) for i in (1, 2, 3)), alpha


def off_kit(colors: list[str], allowed: set[RGB]) -> list[str]:
    """Visible computed colors whose RGB is not in the kit."""
    out = []
    for c in colors:
        rgb, alpha = parse_rgb(c)
        if rgb is not None and alpha != 0 and rgb not in allowed:
            out.append(c)
    return sorted(set(out))


def capture_states(page: Page, out_dir: pathlib.Path, allowed: set[RGB], report: dict) -> bool:
    """Load every state (+ first drafting detail) and record shots/checks. False if the contract is missing."""
    state_ids = page.evaluate("typeof STATE_IDS !== 'undefined' ? STATE_IDS : window.STATE_IDS")
    if not state_ids:
        report["errors"].append("contract: STATE_IDS missing")
        return False

    def capture(name: str) -> None:
        page.evaluate("window.stopTimers && window.stopTimers()")
        page.wait_for_timeout(150)
        info = page.evaluate(COLLECT_JS)
        page.locator("#canvas").screenshot(path=str(out_dir / f"{name}.png"))
        off = off_kit(info.pop("colors"), allowed)
        if off:
            report["offKitColors"][name] = off
        report["states"][name] = info

    has_detail = page.evaluate("typeof window.openDetail === 'function' && typeof window.draftingIds === 'function'")
    for sid in state_ids:
        page.evaluate(f"loadState({json.dumps(sid)})")
        capture(sid)
        if has_detail:
            for mid in page.evaluate(f"window.draftingIds({json.dumps(sid)})")[:1]:
                page.evaluate(f"window.openDetail({json.dumps(mid)})")
                capture(f"{sid}-detail-{mid}")
    return True


def summarize(report: dict, strict_colors: bool) -> bool:
    """Print per-shot results; True if anything failed."""
    bad = False
    for name, info in report["states"].items():
        flags = []
        if (info["w"], info["h"]) != CANVAS_SIZE:
            flags.append("canvas size")
        if info["pageOverflowX"]:
            flags.append(f"page wider than {VIEWPORT['width']} viewport")
        if info["brokenImgs"]:
            flags.append(f"broken images {info['brokenImgs'][:3]}")
        if info["clipped"]:
            flags.append(f"clipped content x{len(info['clipped'])}")
        bad |= bool(flags)
        tail = "".join(f"  <-- {f}" for f in flags)
        print(f"{name:40s} canvas {info['w']}x{info['h']} scrollers={len(info['scrollers'])}{tail}")
        for s in info["scrollers"]:
            print(f"    scroll  {s['area']}: {s['client']}/{s['scroll']}")
        for s in info["clipped"]:
            print(f"    CLIPPED {s['area']}: {s['client']}/{s['scroll']}")
    for e in report["errors"]:
        print("ERROR", e)
    bad |= bool(report["errors"])
    if report["offKitColors"]:
        print("off-kit colors:", json.dumps(report["offKitColors"], ensure_ascii=False))
        bad |= strict_colors
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page", help="HTML file, relative to the track folder (the parent of tools/)")
    ap.add_argument("--out", required=True, help="shot folder, relative to the track folder (or absolute)")
    ap.add_argument("--strict-colors", action="store_true", help="fail on colors not in kit/kit.css")
    args = ap.parse_args()

    page_path = (HERE / args.page).resolve()
    out_dir = (HERE / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"page": str(page_path), "states": {}, "errors": [], "offKitColors": {}}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        page.on("console", lambda m: m.type == "error" and report["errors"].append(m.text))
        page.on("pageerror", lambda e: report["errors"].append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: report["errors"].append(f"requestfailed: {r.url}"))
        page.goto(page_path.as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        capture_states(page, out_dir, kit_colors(), report)
        browser.close()

    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = summarize(report, args.strict_colors)
    print("RESULT:", "FAIL" if bad else "PASS", "->", out_dir)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
