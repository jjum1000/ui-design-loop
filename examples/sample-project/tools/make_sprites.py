"""Generate the sample project's flat UI sprites (original, CC0).

Writes PNGs to Assets/SampleUI/Sprites/ and, for any PNG without one, a minimal .meta
with a GUID derived from the asset path (so GUIDs are stable across machines).
Import settings (Sprite type, 9-slice borders) are applied by SampleUIBuilder.BuildAll().

Run: python tools/make_sprites.py   (from examples/sample-project; needs Pillow)
"""
import hashlib
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Assets" / "SampleUI" / "Sprites"
SS = 4  # supersampling factor for anti-aliased edges

# 8-colour palette
NAVY = (27, 36, 64, 255)
SLATE = (44, 58, 94, 255)
ORANGE = (242, 140, 56, 255)
TEAL = (43, 179, 192, 255)
RED = (229, 72, 77, 255)
GOLD = (245, 197, 66, 255)
GREEN = (60, 194, 122, 255)
WHITE = (244, 246, 250, 255)


def shade(c, f):
    return tuple(max(0, min(255, round(v * f))) for v in c[:3]) + (c[3],)


def canvas(w, h):
    img = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def s(v):
    return v * SS


def finish(img, w, h, name):
    img.resize((w, h), Image.LANCZOS).save(OUT / f"{name}.png", optimize=False)


def rounded(name, size, radius, fill, outline=None, width=0, inset=0):
    img, d = canvas(size, size)
    box = [s(inset), s(inset), s(size - inset) - 1, s(size - inset) - 1]
    d.rounded_rectangle(box, radius=s(radius), fill=outline or fill)
    if outline:
        inner = [box[0] + s(width), box[1] + s(width), box[2] - s(width), box[3] - s(width)]
        d.rounded_rectangle(inner, radius=s(max(1, radius - width)), fill=fill)
    finish(img, size, size, name)


def button(name, base):
    # rounded body with a darker bottom lip (reads as a raised button)
    size, r = 96, 24
    img, d = canvas(size, size)
    d.rounded_rectangle([0, 0, s(size) - 1, s(size) - 1], radius=s(r), fill=shade(base, 0.72))
    d.rounded_rectangle([0, 0, s(size) - 1, s(size - 8) - 1], radius=s(r), fill=base)
    finish(img, size, size, name)


def circle_icon(name, size, fill, ring=None, ring_w=0):
    img, d = canvas(size, size)
    pad = s(6)
    d.ellipse([pad, pad, s(size) - pad, s(size) - pad], fill=ring or fill)
    if ring:
        p2 = pad + s(ring_w)
        d.ellipse([p2, p2, s(size) - p2, s(size) - p2], fill=fill)
    return img, d


def coin():
    img, d = circle_icon("icon_coin", 128, GOLD, ring=shade(GOLD, 0.75), ring_w=10)
    c = s(64)
    d.rounded_rectangle([c - s(10), c - s(30), c + s(10), c + s(30)], radius=s(6), fill=shade(GOLD, 0.75))
    finish(img, 128, 128, "icon_coin")


def gem():
    img, d = canvas(128, 128)
    pts = [(64, 10), (112, 50), (64, 118), (16, 50)]
    d.polygon([(s(x), s(y)) for x, y in pts], fill=TEAL)
    d.polygon([(s(x), s(y)) for x, y in [(64, 10), (112, 50), (64, 50)]], fill=shade(TEAL, 1.25))
    d.polygon([(s(x), s(y)) for x, y in [(16, 50), (64, 50), (64, 118)]], fill=shade(TEAL, 0.78))
    finish(img, 128, 128, "icon_gem")


def star(name="icon_star", fill=GOLD):
    img, d = canvas(128, 128)
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = 58 if i % 2 == 0 else 24
        pts.append((s(64 + rad * math.cos(ang)), s(66 + rad * math.sin(ang))))
    d.polygon(pts, fill=fill)
    finish(img, 128, 128, name)


def potion():
    img, d = canvas(128, 128)
    d.rounded_rectangle([s(50), s(8), s(78), s(44)], radius=s(6), fill=WHITE)
    d.ellipse([s(20), s(34), s(108), s(122)], fill=RED)
    d.ellipse([s(36), s(52), s(60), s(76)], fill=shade(RED, 1.3))
    finish(img, 128, 128, "icon_potion")


def sword():
    img, d = canvas(128, 128)
    blade = [(98, 12), (116, 12), (116, 30), (52, 94), (34, 76)]
    d.polygon([(s(x), s(y)) for x, y in blade], fill=WHITE)
    d.line([(s(28), s(70)), (s(58), s(100))], fill=GOLD, width=s(12))
    d.line([(s(42), s(86)), (s(16), s(112))], fill=SLATE, width=s(14))
    finish(img, 128, 128, "icon_sword")


def shield():
    img, d = canvas(128, 128)
    pts = [(64, 8), (112, 26), (106, 76), (64, 120), (22, 76), (16, 26)]
    d.polygon([(s(x), s(y)) for x, y in pts], fill=TEAL)
    inner = [(64, 24), (98, 36), (94, 72), (64, 104)]
    d.polygon([(s(x), s(y)) for x, y in inner], fill=shade(TEAL, 0.78))
    finish(img, 128, 128, "icon_shield")


def close_x():
    img, d = canvas(64, 64)
    w = s(9)
    d.line([(s(16), s(16)), (s(48), s(48))], fill=WHITE, width=w)
    d.line([(s(48), s(16)), (s(16), s(48))], fill=WHITE, width=w)
    finish(img, 64, 64, "icon_close")


def back_arrow():
    img, d = canvas(64, 64)
    d.polygon([(s(8), s(32)), (s(32), s(10)), (s(32), s(54))], fill=WHITE)
    d.rectangle([s(28), s(25), s(56), s(39)], fill=WHITE)
    finish(img, 64, 64, "icon_back")


def avatar():
    img, d = circle_icon("icon_avatar", 128, SLATE, ring=TEAL, ring_w=6)
    d.ellipse([s(44), s(26), s(84), s(66)], fill=WHITE)
    d.pieslice([s(26), s(72), s(102), s(148)], 180, 360, fill=WHITE)
    finish(img, 128, 128, "icon_avatar")


def gear():
    img, d = canvas(128, 128)
    for i in range(8):
        ang = i * math.pi / 4
        cx, cy = 64 + 46 * math.cos(ang), 64 + 46 * math.sin(ang)
        d.ellipse([s(cx - 13), s(cy - 13), s(cx + 13), s(cy + 13)], fill=WHITE)
    d.ellipse([s(22), s(22), s(106), s(106)], fill=WHITE)
    d.ellipse([s(48), s(48), s(80), s(80)], fill=(0, 0, 0, 0))
    finish(img, 128, 128, "icon_gear")


def checkmark():
    img, d = canvas(64, 64)
    d.line([(s(12), s(34)), (s(27), s(48)), (s(52), s(16))], fill=WHITE, width=s(9), joint="curve")
    finish(img, 64, 64, "toggle_check")


def titlebar_bg():
    img, d = canvas(64, 64)
    d.rectangle([0, 0, s(64), s(64)], fill=SLATE)
    d.rectangle([0, s(58), s(64), s(64)], fill=TEAL)
    finish(img, 64, 64, "titlebar_bg")


def progress_fill():
    rounded("progress_fill", 48, 12, GREEN)


def write_meta(png: Path):
    meta = png.with_name(png.name + ".meta")
    if meta.exists():
        return
    rel = png.relative_to(ROOT).as_posix()
    guid = hashlib.md5(("ui-design-loop-sample:" + rel).encode()).hexdigest()
    meta.write_text(f"fileFormatVersion: 2\nguid: {guid}\n", encoding="utf-8", newline="\n")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    button("btn_primary", ORANGE)
    button("btn_secondary", TEAL)
    rounded("btn_close", 96, 48, RED, outline=WHITE, width=6)
    rounded("panel_rounded", 96, 24, SLATE)
    rounded("frame_popup", 128, 28, NAVY, outline=TEAL, width=6)
    rounded("slot_frame", 96, 16, SLATE, outline=WHITE, width=5)
    rounded("tab_off", 96, 20, SLATE)
    rounded("tab_on", 96, 20, ORANGE)
    rounded("toggle_bg", 64, 16, NAVY, outline=WHITE, width=4)
    rounded("pill", 64, 32, NAVY)
    titlebar_bg()
    progress_fill()
    coin()
    gem()
    star()
    potion()
    sword()
    shield()
    close_x()
    back_arrow()
    avatar()
    gear()
    checkmark()
    for png in sorted(OUT.glob("*.png")):
        write_meta(png)
    print(f"wrote {len(list(OUT.glob('*.png')))} sprites to {OUT}")


if __name__ == "__main__":
    main()
