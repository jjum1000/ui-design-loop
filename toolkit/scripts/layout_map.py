"""S1·S2 화면 배치 맵: Unity 가 계산한 배치(렌더 이미지 + 노드 화면 좌표)를 data/layout/<kind>/<slug>.json 으로 정리한다.
화면 = app-flow 화면 ∪ template-index 화면, 템플릿 = template-index 템플릿. 렌더는 ClaudeBridge.UILayoutRenderer.

사용:
  python scripts/layout_map.py --list [--only a,b]   → previews/layout/_list.json (렌더 목록 + ResourcesLoader 주소 맵, 예시 아이템 켬)
                                                    --only: 그 slug 들만(표본 확인용)
  python scripts/layout_map.py --run               Unity GUI 가 떠 있으면 거부, 아니면 -batchmode(-nographics 없이) 실행
                                                    (로그 cache/layout-unity.log, 진행 previews/layout/_render-log.txt)
  python scripts/layout_map.py --collect           원시 좌표 → data/layout/<kind>/<slug>.json, 카드용 .thumb.png,
                                                    previews/layout/_failed.json, 성공률 출력
  python scripts/layout_map.py --check-samples [slug,...]
                                                    표본 화면의 박스(로더·예시 제외)를 프리팹 파싱 노드와 대조하고
                                                    박스를 겹친 확인용 PNG 를 cache/layout-check/ 에 쓴다
  python scripts/layout_map.py --selftest
좌표: 저장 PNG 픽셀, 왼쪽 위 원점, 잘라낸 영역 기준. 화면은 1920×1080 전체를 폭 1280 으로 줄여 저장한다.
"""
import argparse
import collections
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import thumbs  # noqa: E402

OUT = ("previews", "layout")
METHOD = "ClaudeBridge.UILayoutRenderer.Run"
KINDS = ("screen", "template")
# --check-samples 기본 표본(화면 slug): project.json layout.check_samples, 없으면 렌더된 화면 중 앞의 3개
SAMPLES = ((C.project() or {}).get("layout") or {}).get("check_samples") or []
THUMB_W = 360
DUP_RE = re.compile(r"\[\d+\](?=/|$)")


def out(*parts):
    return C.p(*(OUT + parts))


def targets():
    """[{kind, slug, path}] — 화면(app-flow ∪ template-index, slug 는 template-index 우선) + 템플릿."""
    idx = C.load_json(C.p("data", "template-index.json")) or {"templates": [], "screens": []}
    flow = C.load_json(C.p("data", "app-flow.json")) or {"screens": {}}
    screens = collections.OrderedDict((s["path"], s["slug"]) for s in idx["screens"])
    for s in flow["screens"].values():
        if s.get("prefab") and s["prefab"] not in screens:
            screens[s["prefab"]] = s.get("slug") or C.slugify(os.path.splitext(os.path.basename(s["prefab"]))[0])
    items = [{"kind": "screen", "slug": slug, "path": path} for path, slug in screens.items()]
    for slug in idx["templates"]:
        t = C.load_json(C.p("data", "templates", slug + ".json"))
        items.append({"kind": "template", "slug": slug, "path": t["path"]})
    return items


def make_list(only=None):
    items = targets()
    if only:
        items = [x for x in items if x["slug"] in only]
    code = C.load_json(C.p("data", "code-usage.json")) or {"loaderKeys": []}
    lm = [{"key": k["key"], "path": k["prefab"]} for k in code["loaderKeys"] if k.get("prefab")]
    os.makedirs(out(), exist_ok=True)
    with open(out("_list.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(C.dump_json({"items": items, "loaderMap": lm, "samples": True}))
    n = collections.Counter(x["kind"] for x in items)
    print("렌더 목록: 화면 %d · 템플릿 %d, 주소 맵 %d → %s" % (n["screen"], n["template"], len(lm),
                                                       os.path.relpath(out("_list.json"), C.ROOT)))
    return 0


def run_unity():
    running = thumbs.unity_running()
    if running:
        print("거부: Unity 가 이미 떠 있음 — 닫은 뒤 다시 실행\n  " + "\n  ".join(running))
        return 2
    if not os.path.exists(out("_list.json")):
        print("_list.json 없음 — layout_map.py --list 먼저")
        return 1
    log = C.p("cache", "layout-unity.log")
    cmd = [thumbs.unity_exe(), "-batchmode", "-quit", "-projectPath", C.unity_root(), "-executeMethod", METHOD, "-logFile", log]
    cmd += thumbs.font_args()
    print("실행: " + " ".join(cmd))
    t = time.time()
    r = subprocess.run(cmd)
    print("Unity 종료 코드 %d (%.0fs) — 로그 %s, 진행 %s" % (r.returncode, time.time() - t, log, out("_render-log.txt")))
    return r.returncode


def to_layout(raw, by_path, image_rel, thumb_rel, blank):
    """원시 좌표(UILayoutRenderer) → layout 스키마. by_path: 템플릿 경로 → slug."""
    boxes = []
    for i, n in enumerate(raw["nodes"]):
        nested = n.get("nested") or None
        boxes.append({"id": "b%d" % i, "path": n["path"], "name": n["name"], "depth": n["depth"],
                      "x": round(n["x"], 1), "y": round(n["y"], 1), "w": round(n["w"], 1), "h": round(n["h"], 1),
                      "template": by_path.get(nested) if nested else None, "nested": nested,
                      "active": bool(n["active"]), "sample": bool(n["sample"]), "loader": bool(n["loader"]),
                      "comps": n.get("comps") or ""})
    act = [b for b in boxes if b["active"]]
    return {"slug": raw["slug"], "kind": raw["kind"], "path": raw["path"], "image": image_rel, "thumb": thumb_rel,
            "width": raw["width"], "height": raw["height"], "scale": raw.get("scale", 1), "blank": blank, "boxes": boxes,
            "stats": {"boxes": len(boxes), "active": len(act), "zero": sum(1 for b in act if b["w"] <= 0 or b["h"] <= 0),
                      "templates": sum(1 for b in act if b["template"]), "loader": sum(1 for b in boxes if b["loader"]),
                      "sample": sum(1 for b in boxes if b["sample"])}}


def template_paths():
    idx = C.load_json(C.p("data", "template-index.json")) or {"templates": []}
    return {C.load_json(C.p("data", "templates", s + ".json"))["path"]: s for s in idx["templates"]}


def make_thumb(png, dst):
    from PIL import Image
    with Image.open(png) as im:
        if im.width > THUMB_W:
            im = im.resize((THUMB_W, max(1, round(im.height * THUMB_W / im.width))), Image.LANCZOS)
        im.save(dst, optimize=True)


def collect():
    res = C.load_json(out("_render-result.json"))
    if res is None:
        print("_render-result.json 없음 — layout_map.py --run 먼저")
        return 1
    res = res["results"]
    by_path = template_paths()
    failed, blank, ok = [], [], collections.Counter()
    for r in res:
        png, rawf = out(r["kind"], r["slug"] + ".png"), out(r["kind"], r["slug"] + ".raw.json")
        if not r["ok"] or not os.path.exists(png) or not os.path.exists(rawf):
            failed.append({"kind": r["kind"], "slug": r["slug"], "path": r["path"], "reason": r.get("error") or "PNG 없음"})
            continue
        b, why = thumbs.is_blank(png)
        if b:
            blank.append({"kind": r["kind"], "slug": r["slug"], "path": r["path"], "reason": why})
        thumb = out(r["kind"], r["slug"] + ".thumb.png")
        make_thumb(png, thumb)
        rel = lambda f: os.path.relpath(f, C.ROOT).replace("\\", "/")  # noqa: E731
        data = to_layout(C.load_json(rawf), by_path, rel(png), rel(thumb), b)
        C.write_json_atomic(C.p("data", "layout", r["kind"], r["slug"] + ".json"), data, "layout")
        ok[r["kind"]] += 1
    summary = {"updatedAt": C.now_iso(), "total": len(res), "ok": dict(ok), "failed": failed, "blank": blank,
               "loaderFailed": sum(r["loaderFailed"] for r in res), "samples": sum(r["samples"] for r in res)}
    with open(out("_failed.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(C.dump_json(summary))
    tot = collections.Counter(r["kind"] for r in res)
    for k in KINDS:
        if tot[k]:
            print("%s: 렌더 %d / %d (%.1f%%), 빈 이미지 %d" % (k, ok[k], tot[k], 100.0 * ok[k] / tot[k],
                                                        sum(1 for x in blank if x["kind"] == k)))
    print("실패 %d, 로더 실패 %d, 예시 아이템 %d → previews/layout/_failed.json" % (len(failed), summary["loaderFailed"], summary["samples"]))
    return 0


def generated(n):
    """UIParticle 등이 에디터에서 만든 노드('[generated] …', 프리팹에 없음)."""
    return "/[generated] " in "/" + n["path"]


def compare(raw, nodes):
    """(Unity 박스 수, 프리팹 노드 수, 경로 차이, activeSelf 차이) — 로더·예시·루트 activeSelf 는 뺀다."""
    own = [n for n in raw["nodes"] if not n["loader"] and not n["sample"] and not generated(n)]
    mine = collections.Counter(n["path"] for n in own)
    theirs = collections.Counter(DUP_RE.sub("", n["path"]) for n in nodes)  # parse_prefab 은 같은 이름 형제에 [n] 을 붙인다
    diff = sorted(((mine - theirs) + (theirs - mine)).elements())
    self_u = sum(1 for n in own[1:] if n["self"])
    self_p = sum(1 for n in nodes[1:] if n["active"])
    return sum(mine.values()), sum(theirs.values()), diff, self_u - self_p


def overlay(png, raw, dst):
    """박스를 겹친 확인용 PNG. 템플릿 인스턴스 = 빨강 굵게, 예시 = 초록, 로더 = 파랑, 나머지 활성 노드 = 노랑 가늘게."""
    from PIL import Image, ImageDraw
    by_path = template_paths()
    with Image.open(png) as im:
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (40, 40, 40, 255))
        bg.alpha_composite(im)
        dr = ImageDraw.Draw(bg)
        for n in raw["nodes"]:
            if not n["active"] or n["w"] <= 0 or n["h"] <= 0:
                continue
            tpl = n.get("nested") in by_path
            col, wd = ((255, 60, 60, 255), 3) if tpl else ((60, 220, 90, 255), 2) if n["sample"] else \
                ((80, 150, 255, 255), 2) if n["loader"] else ((255, 220, 0, 110), 1)
            dr.rectangle([n["x"], n["y"], n["x"] + n["w"], n["y"] + n["h"]], outline=col, width=wd)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        bg.convert("RGB").save(dst)


def default_samples():
    if SAMPLES:
        return list(SAMPLES)
    d = out("screen")
    raws = sorted(f[:-len(".raw.json")] for f in os.listdir(d) if f.endswith(".raw.json")) if os.path.isdir(d) else []
    if not raws:
        raise SystemExit("표본 없음 — 화면 배치 렌더(--run --collect)를 먼저 하거나 --check-samples a,b,c 로 지정")
    return raws[:3]


def check_samples(slugs):
    import parse_prefab
    bad = 0
    for slug in slugs:
        rawf, png = out("screen", slug + ".raw.json"), out("screen", slug + ".png")
        if not os.path.exists(rawf):
            print("%s: 원시 좌표 없음" % slug)
            bad += 1
            continue
        raw = C.load_json(rawf)
        nodes, _u = parse_prefab.build_nodes(raw["path"], slug)
        nu, npf, diff, dself = compare(raw, nodes)
        act = sum(1 for n in raw["nodes"] if n["active"])
        print("%s: Unity 박스 %d (활성 %d, 로더 %d, 예시 %d, 자동생성 %d) · 프리팹 노드 %d · 경로 차이 %d · activeSelf 차이 %d%s" % (
            slug, len(raw["nodes"]), act, sum(n["loader"] for n in raw["nodes"]), sum(n["sample"] for n in raw["nodes"]),
            sum(generated(n) for n in raw["nodes"]),
            npf, len(diff), dself, (" — 예: " + ", ".join(diff[:3])) if diff else ""))
        bad += bool(diff) or nu != npf or dself != 0
        dst = C.p("cache", "layout-check", slug + ".png")
        overlay(png, raw, dst)
        print("  확인용 이미지: %s" % os.path.relpath(dst, C.ROOT))
    return 1 if bad else 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for x in ("list", "run", "collect", "selftest"):
        ap.add_argument("--" + x, action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--check-samples", nargs="?", const="")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.list:
        return make_list(set(a.only.split(",")) if a.only else None)
    if a.run:
        return run_unity()
    if a.collect:
        return collect()
    if a.check_samples is not None:
        return check_samples(a.check_samples.split(",") if a.check_samples else default_samples())
    ap.print_help()
    return 2


def selftest():
    from PIL import Image
    import validate
    items = targets()
    n = collections.Counter(x["kind"] for x in items)
    assert n["template"] == len((C.load_json(C.p("data", "template-index.json")) or {"templates": []})["templates"]), n
    assert len({(x["kind"], x["slug"]) for x in items}) == len(items), "slug 중복"
    screens = {x["slug"] for x in items if x["kind"] == "screen"}
    assert all(s in screens for s in SAMPLES), (SAMPLES, sorted(screens)[:10])
    raw = {"slug": "s", "kind": "screen", "path": "Assets/s.prefab", "width": 20, "height": 10, "nodes": [
        {"path": "S", "name": "S", "depth": 0, "x": 0, "y": 0, "w": 20, "h": 10, "nested": "", "active": True, "self": True,
         "loader": False, "sample": False, "comps": ""},
        {"path": "S/B", "name": "B", "depth": 1, "x": 2.04, "y": 3, "w": 4, "h": 2, "nested": "Assets/b.prefab", "active": True,
         "self": True, "loader": False, "sample": False, "comps": "Image"},
        {"path": "S/B/I", "name": "I", "depth": 2, "x": 0, "y": 0, "w": 0, "h": 0, "nested": "", "active": True, "self": True,
         "loader": False, "sample": True, "comps": ""},
        {"path": "S/H", "name": "H", "depth": 1, "x": 0, "y": 0, "w": 1, "h": 1, "nested": "Assets/x.prefab", "active": False,
         "self": False, "loader": True, "sample": False, "comps": ""}]}
    lay = to_layout(raw, {"Assets/b.prefab": "b"}, "previews/layout/screen/s.png", None, False)
    assert lay["boxes"][1]["template"] == "b" and lay["boxes"][1]["x"] == 2.0 and lay["boxes"][3]["template"] is None
    assert lay["stats"] == {"boxes": 4, "active": 3, "zero": 1, "templates": 1, "loader": 1, "sample": 1}, lay["stats"]
    assert validate.validate_obj(lay, "layout") == [], validate.validate_obj(lay, "layout")
    nodes = [{"path": "S", "active": False}, {"path": "S/B", "active": True}]
    assert compare(raw, nodes) == (2, 2, [], 0), compare(raw, nodes)
    assert compare(raw, nodes + [{"path": "S/Z", "active": True}])[2:] == (["S/Z"], -1)
    assert compare(raw, [{"path": "S", "active": False}, {"path": "S/B[1]", "active": True}])[2] == []
    d = C.selftest_dir("layout")
    png, dst, th = (os.path.join(d, x) for x in ("s.png", "o.png", "t.png"))
    Image.new("RGBA", (20, 10), (0, 0, 0, 0)).save(png)
    overlay(png, raw, dst)
    with Image.open(dst) as im:
        assert im.getpixel((2, 3))[0] > 200, "템플릿 박스 테두리가 빨강이어야 함"
    Image.new("RGBA", (720, 360), (9, 9, 9, 255)).save(png)
    make_thumb(png, th)
    with Image.open(th) as im:
        assert im.size == (THUMB_W, 180), im.size
    if not os.path.exists(thumbs.unity_exe()):
        print("  주의: Unity 실행 파일 없음(%s) — 렌더 단계(--run)는 UNITY_EXE 를 지정해야 한다" % thumbs.unity_exe())
    print("layout_map.py selftest ok (화면 %d · 템플릿 %d)" % (n["screen"], n["template"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
