"""ui-audit 공통 도우미: 경로, JSON 입출력(.tmp → rename), 로그, 시각."""
import datetime as _dt
import hashlib
import json
import os
import re
import sys

ROOT = os.environ.get("UIAUDIT_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.dirname(os.path.abspath(__file__))

KINDS = ["button", "tab", "toggle", "popup", "slot", "gauge", "currency", "reddot",
         "tooltip", "toast", "listcell", "icon", "textstyle", "decor", "other"]
KIND_LABELS = {"button": "버튼", "tab": "탭", "toggle": "토글", "popup": "팝업 프레임",
               "slot": "슬롯", "gauge": "게이지", "currency": "재화 표시", "reddot": "레드닷",
               "tooltip": "툴팁", "toast": "토스트", "listcell": "리스트 셀", "icon": "아이콘",
               "textstyle": "텍스트 스타일", "decor": "배경·장식", "other": "기타"}
TOKEN_CATEGORIES = ["color", "type", "spacing", "nineslice", "size"]
CATALOG_PAGES = ["index", "tokens", "components", "screens", "refactor-map", "decisions"]
SEQUENCE = ["H1", "A1", "A2", "A3", "H2", "A4", "H3", "A5", "A6"]
GATES = ["H1", "H2", "H3"]
STEPS = ["A1", "A2", "A3", "A4", "A5", "A6"]
STEP_LABELS = {"H1": "H1 배치 범위 확인", "A1": "A1 수집", "A2": "A2 분류", "A3": "A3 통합 분석",
               "H2": "H2 그룹·표준 확인", "A4": "A4 토큰 추출", "H3": "H3 토큰 확정",
               "A5": "A5 카탈로그 빌드", "A6": "A6 검증"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def p(*parts):
    """ui-audit 루트 기준 경로."""
    return os.path.join(ROOT, *parts)


def now_iso():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def today():
    return _dt.date.today().isoformat()


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def write_tmp(path, obj):
    """<path>.tmp 에 쓴다. 최종 rename 은 validate.py --rename 이 한다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(dump_json(obj) if not isinstance(obj, str) else obj)
    return tmp


def write_json_atomic(path, obj, schema=None):
    """상태 파일용: .tmp 에 쓰고 (스키마가 있으면 검증한 뒤) rename."""
    tmp = write_tmp(path, obj)
    if schema:
        import validate  # 지연 import (순환 방지)
        errs = validate.validate_obj(obj, schema)
        if errs:
            os.remove(tmp)
            raise SystemExit("스키마 오류(%s): %s" % (schema, "; ".join(errs[:5])))
    os.replace(tmp, path)


def append_log(line):
    os.makedirs(p("handoff"), exist_ok=True)
    with open(p("handoff", "log.md"), "a", encoding="utf-8", newline="\n") as f:
        f.write("- %s %s\n" % (now_iso(), line))


def short_hash(text, n=4):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def unique_id(prefix, key, taken):
    """prefix-<해시>; 다른 키와 충돌하면 해시를 늘린다. taken: id -> key."""
    for n in (4, 6, 8, 12, 40):
        cand = "%s-%s" % (prefix, short_hash(key, n))
        if cand not in taken or taken[cand] == key:
            return cand
    raise RuntimeError("ID 충돌을 해소하지 못함: " + key)


def project():
    return load_json(p("project.json"))


def unity_root():
    proj = project() or {"unity_root": ".."}
    return os.path.normpath(os.path.join(ROOT, proj["unity_root"]))


def slugify(name):
    s = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return s or "x"


def iter_json(dirpath):
    """dirpath 아래 *.json (tmp 제외) 경로를 정렬해 돌려준다."""
    out = []
    if not os.path.isdir(dirpath):
        return out
    for dp, _dn, fn in os.walk(dirpath):
        for f in fn:
            if f.endswith(".json"):
                out.append(os.path.join(dp, f))
    return sorted(out)


def all_inventory():
    """{node_id: (batch, screen, node)} — 모든 배치의 inventory."""
    res = {}
    for f in iter_json(p("data", "inventory")):
        inv = load_json(f)
        for n in inv["nodes"]:
            res[n["id"]] = (inv["batch"], inv["screen"], n)
    return res


def all_classified():
    """{node_id: (batch, screen, record)}"""
    res = {}
    for f in iter_json(p("data", "classified")):
        c = load_json(f)
        for r in c["nodes"]:
            res[r["id"]] = (c["batch"], c["screen"], r)
    return res


def selftest_dir(name):
    """자체 테스트용 임시 ui-audit 루트 (spec/schemas/project.json 복사, Unity 경로는 절대경로)."""
    import atexit
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix="uiaudit-%s-" % name)
    atexit.register(shutil.rmtree, d, True)
    for sub in ("spec", "schemas", "cache"):
        if os.path.isdir(p(sub)):
            shutil.copytree(p(sub), os.path.join(d, sub))
    proj = load_json(p("project.json"))
    proj["unity_root"] = unity_root()
    with open(os.path.join(d, "project.json"), "w", encoding="utf-8") as f:
        f.write(dump_json(proj))
    return d


def run_script(root, script, *args, check=True):
    """다른 루트(UIAUDIT_ROOT)로 스크립트를 실행하고 (returncode, 출력)을 돌려준다."""
    import subprocess
    env = dict(os.environ, UIAUDIT_ROOT=root, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + [str(a) for a in args],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    out = (r.stdout or "") + (r.stderr or "")
    if check and r.returncode != 0:
        raise AssertionError("%s %s 실패(%d):\n%s" % (script, " ".join(map(str, args)), r.returncode, out))
    return r.returncode, out
