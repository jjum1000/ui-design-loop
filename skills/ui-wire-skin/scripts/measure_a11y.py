"""Measure touch-target size, font size and text contrast per state (+ first drafting detail).

Usage (copy this file to <track>/tools/ and run from the track folder; the page path is relative to the current folder):
    python tools/measure_a11y.py variant-x/index.html [--min-target 47] [--min-font 12]

Same page contract as shoot.py. Contrast uses WCAG relative luminance (sRGB linearized) against the
nearest opaque ancestor background (alpha-composited); text over a background-image is skipped.
Known false positive: a button/band whose face is drawn by a child sprite looks like low contrast —
confirm every failure on the screenshot before reporting it.
"""
import argparse
import json
import pathlib
import sys

from playwright.sync_api import Page, sync_playwright

JS = r"""
() => {
  const canvas = document.querySelector('#canvas');
  const parse = s => { const m = s.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?/); return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null; };
  const lin = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  const visible = el => { const cs = getComputedStyle(el); const r = el.getBoundingClientRect(); return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
  const bgOf = el => {
    const stack = [];
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return { img: true };
      const c = parse(cs.backgroundColor);
      if (c && c[3] > 0) { stack.push(c); if (c[3] >= 1) break; }
    }
    let out = [255, 255, 255];
    for (const c of stack.reverse()) out = out.map((v, i) => v * (1 - c[3]) + c[i] * c[3]);
    return { rgb: out };
  };
  const opacityOf = el => { let o = 1; for (let e = el; e; e = e.parentElement) o *= +getComputedStyle(e).opacity; return o; };
  const label = el => (el.dataset.area || el.className.toString() || el.tagName).slice(0, 40) + ' "' + (el.innerText || '').trim().split('\n')[0].slice(0, 20) + '"';
  const targets = [];
  for (const el of canvas.querySelectorAll('button,[role=button],a,[onclick],input')) {
    if (!visible(el)) continue;
    // an inner clickable inside a larger clickable row is not its own target
    const outer = el.parentElement && el.parentElement.closest('button,[role=button],[onclick]');
    const r = el.getBoundingClientRect();
    if (outer && canvas.contains(outer)) { const o = outer.getBoundingClientRect(); if (o.height >= r.height && o.width >= r.width) continue; }
    targets.push({ w: Math.round(r.width), h: Math.round(r.height), el: label(el) });
  }
  targets.sort((a, b) => Math.min(a.w, a.h) - Math.min(b.w, b.h));
  const fonts = [], fails = [];
  const walker = document.createTreeWalker(canvas, NodeFilter.SHOW_TEXT); const seen = new Set();
  while (walker.nextNode()) {
    const el = walker.currentNode.parentElement;
    if (!walker.currentNode.textContent.trim() || seen.has(el) || !visible(el)) continue;
    seen.add(el);
    const cs = getComputedStyle(el); const fs = parseFloat(cs.fontSize);
    fonts.push({ fs, el: label(el) });
    const fg = parse(cs.color); const bg = bgOf(el);
    if (!fg || bg.img) continue;
    const op = opacityOf(el) * fg[3];
    const f = fg.slice(0, 3).map((v, i) => v * op + bg.rgb[i] * (1 - op));
    const L1 = lum(f), L2 = lum(bg.rgb);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const large = fs >= 24 || (fs >= 18.66 && +cs.fontWeight >= 700);
    if (ratio < (large ? 3 : 4.5)) fails.push({ ratio: Math.round(ratio * 100) / 100, fs, el: label(el) });
  }
  fonts.sort((a, b) => a.fs - b.fs);
  fails.sort((a, b) => a.ratio - b.ratio);
  return { targets: targets.slice(0, 5), minFont: fonts[0] || null, fails: fails.slice(0, 6), texts: seen.size };
}
"""


def probe(page: Page, name: str, out: list) -> None:
    page.evaluate("window.stopTimers && window.stopTimers()")
    r = page.evaluate(JS)
    t = r["targets"][0] if r["targets"] else None
    print(f"{name:26s} minTarget={t and (t['w'], t['h'])} {t and t['el']} | minFont={r['minFont'] and r['minFont']['fs']} | contrast fails {len(r['fails'])}/{r['texts']}")
    for f in r["fails"]:
        print(f"      {f['ratio']}:1 fs={f['fs']} {f['el']}")
    out.append({"name": name, **r})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("page", help="HTML file, relative to the current folder (or absolute)")
    ap.add_argument("--min-target", type=int, default=47, help="minimum touch target side in CSS px (exit 1 below this)")
    ap.add_argument("--min-font", type=float, default=12, help="minimum font size in CSS px (exit 1 below this)")
    args = ap.parse_args()
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1920, "height": 1080})
        page.goto(pathlib.Path(args.page).resolve().as_uri())
        page.wait_for_load_state("networkidle")
        ids = page.evaluate("typeof STATE_IDS !== 'undefined' ? STATE_IDS : window.STATE_IDS")
        for sid in ids:
            page.evaluate(f"loadState({json.dumps(sid)})")
            probe(page, sid, out)
            if page.evaluate("typeof window.openDetail === 'function' && typeof window.draftingIds === 'function'"):
                for mid in page.evaluate(f"window.draftingIds({json.dumps(sid)})")[:1]:
                    page.evaluate(f"window.openDetail({json.dumps(mid)})")
                    probe(page, f"{sid}-detail", out)
        b.close()
    worst_t = min((min(x["targets"][0]["w"], x["targets"][0]["h"]) for x in out if x["targets"]), default=None)
    worst_f = min((x["minFont"]["fs"] for x in out if x["minFont"]), default=None)
    n_fail = sum(len(x["fails"]) for x in out)
    print(f"WORST target={worst_t}px (min {args.min_target}) font={worst_f}px (min {args.min_font}) contrast-fails={n_fail} (confirm on screenshots)")
    return 0 if (worst_t or 0) >= args.min_target and (worst_f or 0) >= args.min_font else 1


if __name__ == "__main__":
    sys.exit(main())
