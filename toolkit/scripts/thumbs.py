"""T6 썸네일: Unity 배치모드(그래픽 있음)로 템플릿 프리팹을 렌더한다. Unity 프로젝트는 ClaudeBridge/ 외에는 쓰지 않는다.

사용:
  python scripts/thumbs.py --list       data/template-index.json → previews/templates/_list.json
                                        (렌더 목록 + ResourcesLoader 주소 맵 + T2a 대조 표본 10개)
  python scripts/thumbs.py --run        Unity GUI 가 떠 있으면 거부, 아니면 -batchmode(‑nographics 없이)로
                                        ClaudeBridge.UIThumbnailRenderer.Run 실행 (로그 cache/thumbs-unity.log)
  python scripts/thumbs.py --collect    PNG 빈 판정 → previews/templates/_failed.json, 성공률 출력
  python scripts/thumbs.py --selftest
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

OUT = ("previews", "templates")
METHOD = "ClaudeBridge.UIThumbnailRenderer.Run"
EDITOR_ROOT = r"C:\Program Files\Unity\Hub\Editor"


def out(*parts):
    return C.p(*(OUT + parts))


def usage_samples(temps, n=10):
    """사용 수(nested+variant) 상위·중위·하위에서 고른 표본 경로."""
    used = sorted((t for t in temps if t["counts"].get("nested", 0) + t["counts"].get("variant", 0) > 0),
                  key=lambda t: (-(t["counts"].get("nested", 0) + t["counts"].get("variant", 0)), t["path"]))
    if len(used) <= n:
        return [t["path"] for t in used]
    picks = used[:4] + used[len(used) // 2 - 1:len(used) // 2 + 2] + used[-3:]
    return [t["path"] for t in picks]


def make_list():
    idx = C.load_json(C.p("data", "template-index.json"))
    if not idx:
        print("data/template-index.json 없음 — templates.py --select 가 먼저 필요")
        return 1
    temps = [C.load_json(C.p("data", "templates", s + ".json")) for s in idx["templates"]]
    code = C.load_json(C.p("data", "code-usage.json")) or {"loaderKeys": []}
    lm = [{"key": k["key"], "path": k["prefab"]} for k in code["loaderKeys"] if k.get("prefab")]
    data = {"items": [{"slug": t["slug"], "path": t["path"]} for t in temps], "loaderMap": lm,
            "usageCheck": usage_samples(temps)}
    os.makedirs(out(), exist_ok=True)
    with open(out("_list.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(C.dump_json(data))
    print("렌더 목록 %d, 주소 맵 %d, 대조 표본 %d → %s" % (len(data["items"]), len(lm), len(data["usageCheck"]),
                                                       os.path.relpath(out("_list.json"), C.ROOT)))
    return 0


def unity_running():
    """이 프로젝트를 연 Unity.exe 프로세스 목록 — CIM 으로 본다(tasklist 는 0 으로 오보한다).
    다른 프로젝트를 연 Unity 는 막지 않는다(프로젝트 폴더 잠금은 프로젝트마다 따로다)."""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='Unity.exe'\" | "
          "ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8")
    except OSError:  # PowerShell 없음(Windows 밖) — 확인하지 못함
        return []
    me = os.path.normcase(os.path.normpath(C.unity_root()))
    return [x for x in (r.stdout or "").splitlines()
            if x.strip() and me in os.path.normcase(os.path.normpath(x.replace("/", os.sep)))]


def font_args():
    """project.json render_font(TMP 폰트 에셋 경로)가 있으면 렌더러에 대체 폰트로 넘긴다(-uiAuditFont)."""
    font = (C.project() or {}).get("render_font")
    return ["-uiAuditFont", font] if font else []


def unity_exe():
    """Unity 실행 파일: 환경 변수 UNITY_EXE 가 있으면 그것, 없으면 Hub 기본 경로의 ProjectVersion 버전(Windows)."""
    if os.environ.get("UNITY_EXE"):
        return os.environ["UNITY_EXE"]
    root = C.unity_root()
    with open(os.path.join(root, "ProjectSettings", "ProjectVersion.txt"), encoding="utf-8") as f:
        ver = [x.split(":", 1)[1].strip() for x in f if x.startswith("m_EditorVersion:")][0]
    return os.path.join(EDITOR_ROOT, ver, "Editor", "Unity.exe")


def run_unity():
    running = unity_running()
    if running:
        print("거부: Unity 가 이미 떠 있음 — 닫은 뒤 다시 실행\n  " + "\n  ".join(running))
        return 2
    if not os.path.exists(out("_list.json")):
        print("_list.json 없음 — thumbs.py --list 먼저")
        return 1
    exe = unity_exe()
    log = C.p("cache", "thumbs-unity.log")
    cmd = [exe, "-batchmode", "-quit", "-projectPath", C.unity_root(), "-executeMethod", METHOD, "-logFile", log] + font_args()
    print("실행: " + " ".join(cmd))
    t = time.time()
    r = subprocess.run(cmd)
    print("Unity 종료 코드 %d (%.0fs) — 로그 %s, 진행 %s" % (r.returncode, time.time() - t, log, out("_render-log.txt")))
    return r.returncode


def is_blank(path):
    """(빈가, 사유). 알파가 모두 0 이거나 모든 픽셀이 한 색이면 빈 이미지."""
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGBA")
        if im.getchannel("A").getextrema()[1] == 0:
            return True, "완전 투명"
        if im.getcolors(1) is not None:
            return True, "단일 색"
    return False, None


def collect():
    res = C.load_json(out("_render-result.json"))
    if res is None:
        print("_render-result.json 없음 — thumbs.py --run 먼저")
        return 1
    failed, blank, ok = [], [], 0
    for r in res:
        png = out(r["slug"] + ".png")
        if not r["ok"] or not os.path.exists(png):
            failed.append({"slug": r["slug"], "path": r["path"], "reason": r.get("error") or "PNG 없음"})
            continue
        b, why = is_blank(png)
        if b:
            blank.append({"slug": r["slug"], "path": r["path"], "reason": why, "loaders": r["loaders"],
                          "loaderFailed": r["loaderFailed"]})
            os.remove(png)  # 빈 이미지는 카탈로그에 '런타임 바인딩'으로 표시
        else:
            ok += 1
    data = {"updatedAt": C.now_iso(), "total": len(res), "ok": ok, "failed": failed, "blank": blank,
            "loaderFailed": sum(r["loaderFailed"] for r in res), "fontsFixed": sum(r["fontsFixed"] for r in res)}
    with open(out("_failed.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(C.dump_json(data))
    print("썸네일: %d / %d 성공 (%.1f%%), 실패 %d, 빈 이미지 %d, 로더 실패 %d, 폰트 보정 %d" % (
        ok, len(res), 100.0 * ok / len(res) if res else 0, len(failed), len(blank), data["loaderFailed"], data["fontsFixed"]))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for x in ("list", "run", "collect", "selftest"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.list:
        return make_list()
    if a.run:
        return run_unity()
    if a.collect:
        return collect()
    ap.print_help()
    return 2


def selftest():
    from PIL import Image
    d = C.selftest_dir("thumbs")
    clear, flat, good = (os.path.join(d, x + ".png") for x in ("clear", "flat", "good"))
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(clear)
    Image.new("RGBA", (8, 8), (10, 20, 30, 255)).save(flat)
    im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    im.putpixel((3, 3), (255, 0, 0, 255))
    im.save(good)
    assert is_blank(clear) == (True, "완전 투명") and is_blank(flat) == (True, "단일 색") and is_blank(good) == (False, None)
    temps = [{"path": "p%02d" % i, "counts": {"nested": i}} for i in range(20)]
    s = usage_samples(temps)
    assert len(s) == 10 and s[0] == "p19" and s[-1] == "p01" and "p00" not in s, s
    assert os.path.exists(unity_exe()), unity_exe()
    assert isinstance(unity_running(), list)
    print("thumbs.py selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
