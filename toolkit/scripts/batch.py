"""H1 배치 범위: spec/batch-plan.json 의 후보 폴더에서 화면 프리팹 후보를 보여주고, 확인된 목록으로 배치를 만든다.

사용:
  python scripts/batch.py suggest <batch>
      후보 폴더의 프리팹 목록. [화면] = 이름이 View·Popup·UI 로 끝남, [부품] = 그 밖,
      (포함됨) = 같은 배치의 화면 후보 안에 중첩·ResourcesLoader 로 들어가 있어 그 화면과 함께 수집됨.
      끝에 H1 에서 물어볼 질문을 출력한다.
  python scripts/batch.py create <batch> <프리팹 경로 또는 폴더...> [--title "<제목>"]
      경로는 Unity 루트 기준(Assets/...) 또는 ui_root 기준(Contents/Lobby/...). 폴더는 아래 .prefab 전부.
      batches/<batch>.json 을 쓰고, 스크린샷(input/screenshots/<batch>/<화면>_<비율>.png) 누락은 경고로 출력.
      이어서 python scripts/state.py gate-done <batch> H1
  python scripts/batch.py --selftest
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SCREEN_RE = re.compile(r"(View|Popup|UI)$")
SRC_RE = re.compile(r"m_SourcePrefab: \{fileID: \d+, guid: ([0-9a-f]{32})")
LOADER_RE = re.compile(r"^\s*guids: ([0-9a-f]{32})", re.M)


def plan_entry(b):
    for x in C.load_json(C.p("spec", "batch-plan.json"))["batches"]:
        if x["batch"] == b:
            return x
    raise SystemExit("spec/batch-plan.json 에 배치 %s 없음" % b)


def prefabs_under(rel_dir):
    root = C.unity_root()
    base = os.path.join(root, rel_dir)
    out = []
    for dp, _dn, fn in os.walk(base):
        for f in fn:
            if f.endswith(".prefab"):
                out.append(os.path.relpath(os.path.join(dp, f), root).replace("\\", "/"))
    return sorted(out)


def guid_of(rel):
    with open(os.path.join(C.unity_root(), rel + ".meta"), encoding="utf-8") as f:
        m = re.search(r"guid: ([0-9a-f]{32})", f.read())
    return m.group(1) if m else None


def refs_of(rel):
    with open(os.path.join(C.unity_root(), rel), encoding="utf-8") as f:
        text = f.read()
    return set(SRC_RE.findall(text)) | set(LOADER_RE.findall(text))


def suggest(b):
    e = plan_entry(b)
    ui_root = C.project()["ui_root"]
    print("배치 %s — %s (후보, H1 확인 전)" % (b, e["title"]))
    by_folder = {f: prefabs_under(ui_root + "/" + f) for f in e["folders"]}
    allp = [x for v in by_folder.values() for x in v]
    screens = [x for x in allp if SCREEN_RE.search(os.path.splitext(os.path.basename(x))[0])]
    included = set()
    guid = {x: guid_of(x) for x in allp}
    for s in screens:
        refs = refs_of(s)
        included |= {x for x in allp if guid[x] in refs}
    total = 0
    for f, items in by_folder.items():
        n_scr = sum(1 for x in items if x in screens)
        print("\n## %s — 프리팹 %d (화면 후보 %d, 포함됨 %d)" % (f, len(items), n_scr, sum(1 for x in items if x in included)))
        for x in items:
            tag = "[화면]" if x in screens else "[부품]"
            inc = " (포함됨)" if x in included else ""
            print("  %s %s%s" % (tag, x[len(ui_root) + 1:], inc))
        total += len(items)
    print("\n합계: 프리팹 %d, 화면 후보 %d, 화면에 포함된 부품 %d" % (total, len(screens), len(included - set(screens))))
    if e.get("questions"):
        print("\nH1 질문:")
        for i, q in enumerate(e["questions"], 1):
            print("  %d. %s" % (i, q))
    print("\n확인되면: python scripts/batch.py create %s <프리팹 또는 폴더...>" % b)
    return 0


def resolve_paths(args):
    root = C.unity_root()
    ui_root = C.project()["ui_root"]
    out = []
    for a in args:
        a = a.replace("\\", "/").rstrip("/")
        cands = [a, ui_root + "/" + a]
        hit = next((c for c in cands if os.path.exists(os.path.join(root, c))), None)
        if not hit:
            raise SystemExit("경로 없음: %s" % a)
        if os.path.isdir(os.path.join(root, hit)):
            out.extend(prefabs_under(hit))
        elif hit.endswith(".prefab"):
            out.append(hit)
        else:
            raise SystemExit(".prefab 또는 폴더가 아님: %s" % a)
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def create(b, args, title=None):
    import validate
    prefabs = resolve_paths(args)
    if not prefabs:
        raise SystemExit("프리팹이 없음")
    screens, slugs = [], {}
    for rel in prefabs:
        name = os.path.splitext(os.path.basename(rel))[0]
        slug = C.slugify(name)
        if slug in slugs:
            slug = C.slugify(os.path.basename(os.path.dirname(rel)) + "-" + name)
        n = 2
        base = slug
        while slug in slugs:
            slug = "%s-%d" % (base, n)
            n += 1
        slugs[slug] = rel
        screens.append({"slug": slug, "name": name, "prefab": rel})
    others = {}
    for f in C.iter_json(C.p("batches")):
        ob = C.load_json(f)
        if ob["batch"] != b:
            for s in ob["screens"]:
                others[s["prefab"]] = ob["batch"]
    data = {"batch": b, "title": title or plan_entry(b)["title"], "createdAt": C.now_iso(), "screens": screens}
    errs = validate.validate_obj(data, "batch")
    if errs:
        raise SystemExit("스키마 오류: %s" % errs[:3])
    C.write_json_atomic(C.p("batches", b + ".json"), data)
    print("batches/%s.json: 화면 %d개" % (b, len(screens)))
    dup = [s["prefab"] for s in screens if s["prefab"] in others]
    for d in dup:
        print("경고: %s 는 이미 배치 %s 에 있음" % (d, others[d]))
    ratios = C.project()["screenshot_ratios"]
    missing = []
    for s in screens:
        for r in ratios:
            if not os.path.exists(C.p("input", "screenshots", b, "%s_%s.png" % (s["slug"], r))):
                missing.append("%s_%s.png" % (s["slug"], r))
    if missing:
        print("경고: 스크린샷 누락 %d개 (input/screenshots/%s/) 예: %s" % (len(missing), b, ", ".join(missing[:6])))
    print("다음: python scripts/state.py gate-done %s H1" % b)
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["suggest", "create"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--title")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "suggest" and len(a.args) == 1:
        return suggest(a.args[0])
    if a.cmd == "create" and len(a.args) >= 2:
        return create(a.args[0], a.args[1:], a.title)
    ap.print_help()
    return 2


def selftest():
    root = C.selftest_dir("batch")
    _rc, out = C.run_script(root, "batch.py", "suggest", "b1")
    folders = plan_entry("b1")["folders"]
    assert any("## %s " % f in out for f in folders) and "H1 질문" in out, out[-500:]
    ui_root = C.project()["ui_root"]
    folder = next(f for f in folders if prefabs_under(ui_root + "/" + f))
    other = next(x for f in folders + [""] for x in prefabs_under((ui_root + "/" + f).rstrip("/"))
                 if not x.startswith(ui_root + "/" + folder + "/"))
    n = len(prefabs_under(ui_root + "/" + folder)) + 1
    _rc, out = C.run_script(root, "batch.py", "create", "b1", folder, other[len(ui_root) + 1:])
    data = C.load_json(os.path.join(root, "batches", "b1.json"))
    assert len(data["screens"]) == n, (n, data["screens"])
    assert len({s["slug"] for s in data["screens"]}) == n
    assert "스크린샷 누락" in out
    rc, out = C.run_script(root, "batch.py", "create", "b1", "Contents/NoSuchFolder", check=False)
    assert rc != 0 and "경로 없음" in out
    print("batch.py selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
