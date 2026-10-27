"""Attention / information-density probe for an HTML mockup variant (headless, standalone).

Usage (copy this file to <track>/tools/ and run from the track folder, e.g. ui-audit/design/<screen>):
    python tools/attention.py variant-b/index.html --out review/attention-b

Per fixture state it records:
  - text inventory: visible text items, distinct font sizes (type-scale steps), distinct text colors
  - emphasis: visible primary (button-yellow*) actions and their labels, all clickable targets
  - motion: running animations inside #canvas (after load, before stopTimers)
  - per-region text counts ([data-area])
  - flat-area ratio: share of 32px canvas cells with near-uniform pixels (empty space)
  - saliency: spectral-residual saliency map + heavy blur image ("squint test"), top-3 salient
    points and the [data-area] element under each
Writes <out>/<state>.png, -blur.png, -saliency.png, attention.json and prints a summary.
Same page contract as tools/shoot.py (STATE_IDS, loadState, window.stopTimers).
"""
import argparse
import json
import pathlib
import sys

import cv2
import numpy as np
from playwright.sync_api import Page, sync_playwright

HERE = pathlib.Path(__file__).resolve().parent.parent
CELL = 32
FLAT_STD = 6.0

INVENTORY_JS = r"""
() => {
  const c = document.querySelector('#canvas'); const cr = c.getBoundingClientRect();
  const vis = el => { const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && +cs.opacity > 0.05 && r.width > 0 && r.height > 0
      && r.right > cr.left && r.left < cr.right && r.bottom > cr.top && r.top < cr.bottom; };
  const texts = []; const owners = new Set();
  const w = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) { const el = w.currentNode.parentElement; const t = w.currentNode.textContent.trim();
    if (!t || owners.has(el) || !vis(el)) continue; owners.add(el);
    const cs = getComputedStyle(el); texts.push({ fs: Math.round(parseFloat(cs.fontSize)), color: cs.color }); }
  const primary = [...c.querySelectorAll('[data-template^="button-yellow"]')].filter(vis)
    .map(e => (e.innerText || '').trim().split('\n')[0].slice(0, 14));
  const targets = [...c.querySelectorAll('button,[role=button]')].filter(vis).length;
  const anims = document.getAnimations().filter(a => a.playState === 'running' && a.effect && a.effect.target && c.contains(a.effect.target)).length;
  const regions = {};
  for (const el of c.querySelectorAll('[data-area]')) { if (!vis(el)) continue;
    const n = [...owners].filter(t => el.contains(t)).length; regions[el.dataset.area] = Math.max(regions[el.dataset.area] || 0, n); }
  return { textItems: texts.length, fontSizes: [...new Set(texts.map(x => x.fs))].sort((a, b) => a - b),
           textColors: new Set(texts.map(x => x.color)).size, primaryActions: primary, targets, runningAnims: anims, regions };
}
"""

AREA_AT_JS = """([x, y]) => { const c = document.querySelector('#canvas').getBoundingClientRect();
  const el = document.elementFromPoint(c.left + x, c.top + y); const a = el && el.closest('[data-area]');
  return (a ? a.dataset.area : '-') + ' / ' + ((el && el.innerText) || '').trim().split('\\n')[0].slice(0, 16); }"""


def image_metrics(png: pathlib.Path) -> dict:
    """Blur + saliency images next to the shot; flat-area ratio and top-3 salient points."""
    img = cv2.imread(str(png))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    cells = flat = 0
    for y in range(0, h - CELL + 1, CELL):
        for x in range(0, w - CELL + 1, CELL):
            cells += 1
            flat += float(gray[y:y + CELL, x:x + CELL].std()) < FLAT_STD
    cv2.imwrite(str(png.with_name(png.stem + "-blur.png")), cv2.GaussianBlur(img, (0, 0), 6))
    ok, sal = cv2.saliency.StaticSaliencySpectralResidual_create().computeSaliency(img)
    sal = cv2.GaussianBlur((sal * 255).astype("uint8"), (0, 0), 25)
    cv2.imwrite(str(png.with_name(png.stem + "-saliency.png")), cv2.applyColorMap(sal, cv2.COLORMAP_JET))
    peaks, work = [], sal.copy()
    for _ in range(3):
        _, mx, _, loc = cv2.minMaxLoc(work)
        peaks.append([int(loc[0]), int(loc[1]), int(mx)])
        cv2.circle(work, loc, 140, 0, -1)
    return {"flatRatio": round(flat / cells, 3), "saliencyPeaks": peaks}


def probe_state(page: Page, sid: str, out_dir: pathlib.Path) -> dict:
    page.evaluate(f"loadState({json.dumps(sid)})")
    page.wait_for_timeout(400)
    info = page.evaluate(INVENTORY_JS)
    page.evaluate("window.stopTimers && window.stopTimers()")
    page.wait_for_timeout(150)
    shot = out_dir / f"{sid}.png"
    page.locator("#canvas").screenshot(path=str(shot))
    info.update(image_metrics(shot))
    info["saliencyAt"] = [page.evaluate(AREA_AT_JS, [x, y]) for x, y, _ in info["saliencyPeaks"]]
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page", help="HTML file, relative to the track folder (the parent of tools/)")
    ap.add_argument("--out", required=True, help="output folder, relative to the track folder (or absolute)")
    args = ap.parse_args()
    out_dir = (HERE / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto((HERE / args.page).resolve().as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        for sid in page.evaluate("typeof STATE_IDS !== 'undefined' ? STATE_IDS : window.STATE_IDS"):
            report[sid] = probe_state(page, sid, out_dir)
        browser.close()
    (out_dir / "attention.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'state':16s} {'texts':>5s} {'sizes':>5s} {'colors':>6s} {'primary':>7s} {'anims':>5s} {'flat':>5s}  top salient")
    for sid, r in report.items():
        print(f"{sid:16s} {r['textItems']:5d} {len(r['fontSizes']):5d} {r['textColors']:6d} {len(r['primaryActions']):7d} "
              f"{r['runningAnims']:5d} {r['flatRatio']:5.2f}  {r['saliencyAt'][0]}")
    print("->", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
