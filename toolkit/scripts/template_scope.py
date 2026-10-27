"""템플릿 카탈로그(T 트랙) 공용: 범위 UI 프리팹 목록, 제외 규칙, 템플릿 원본 노드 id, 수정 속성 정규화.

사용:
  python scripts/template_scope.py --list        범위 UI 프리팹 수(폴더별)
  python scripts/template_scope.py --selftest
"""
import argparse
import contextlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

# 프로젝트별 범위는 project.json 에서 읽는다: ui_roots(없으면 [ui_root]) · common_dirs · exclude[{pattern, reason}]
_PROJ = C.project() or {}
UI_ROOTS = _PROJ.get("ui_roots") or [_PROJ.get("ui_root", "Assets")]
COMMON_DIRS = _PROJ.get("common_dirs", [])
EXCLUDE_RES = [(re.compile(x["pattern"]), x["reason"]) for x in _PROJ.get("exclude", [])]
TEMPLATE_SUFFIXES = ("Unit", "Button", "Panel", "UI")
SCREEN_SUFFIXES = ("View", "Popup")
ARRAY_RE = re.compile(r"\.Array\.data\[\d+\]")
GUID_RE = re.compile(r"guid: ([0-9a-f]{32})")

_UI = None


def ui_prefabs():
    """범위 UI 프리팹의 Assets/ 상대경로(정렬)."""
    global _UI
    if _UI is None:
        root = C.unity_root()
        out = []
        for base in UI_ROOTS:
            for dp, _dn, fn in os.walk(os.path.join(root, base)):
                for f in fn:
                    if f.endswith(".prefab"):
                        out.append(os.path.relpath(os.path.join(dp, f), root).replace("\\", "/"))
        _UI = sorted(out)
    return _UI


def in_scope(rel):
    return any(rel.startswith(b + "/") for b in UI_ROOTS)


def is_excluded(rel):
    """제외 사유 또는 None."""
    for rx, reason in EXCLUDE_RES:
        if rx.search(rel):
            return reason
    return None


def is_common(rel):
    return any(rel.startswith(d) for d in COMMON_DIRS)


def stem(rel):
    return os.path.splitext(os.path.basename(rel))[0]


def suffix(rel):
    """이름 접미사(View·Popup·Unit·Button·Panel·UI) 또는 ''."""
    s = re.sub(r"[\s_]*(\(\d+\)|\d+)$", "", stem(rel))
    for x in SCREEN_SUFFIXES + TEMPLATE_SUFFIXES:
        if s.endswith(x):
            return x
    return ""


def source_node_id(node):
    """중첩 노드의 템플릿 원본 노드 id(`원본 프리팹#원본 루트/…`). 중첩이 아니면 None."""
    ns = node.get("nested")
    if not ns or not ns.get("prefab"):
        return None
    ir, path = ns["instanceRoot"], node["path"]
    if path != ir and not path.startswith(ir + "/"):
        return None
    return "%s#%s%s" % (ns["prefab"], stem(ns["prefab"]), path[len(ir):])


def norm_prop(prop):
    """수정 propertyPath 정규화: `.Array.data[n]` → `[]`."""
    return ARRAY_RE.sub("[]", prop or "")


_GUID = {}


def asset_guid(rel):
    """에셋 .meta 의 guid (없으면 None)."""
    if rel not in _GUID:
        try:
            with open(os.path.join(C.unity_root(), rel + ".meta"), encoding="utf-8") as f:
                m = GUID_RE.search(f.read(512))
            _GUID[rel] = m.group(1) if m else None
        except OSError:
            _GUID[rel] = None
    return _GUID[rel]


@contextlib.contextmanager
def test_scope():
    """자체 테스트용 중립 범위: 공통 폴더 Assets/Game/UI/Common/, 제외 Assets/Game/UI/Vendor/ · Etc/Template 의 Old 사본."""
    global COMMON_DIRS, EXCLUDE_RES
    saved = COMMON_DIRS, EXCLUDE_RES
    COMMON_DIRS = ["Assets/Game/UI/Common/"]
    EXCLUDE_RES = [(re.compile(r"^Assets/Game/UI/Vendor/"), "vendor"),
                   (re.compile(r"/Etc/Template/[^/]*Old[^/]*\.prefab$"), "old copy")]
    try:
        yield
    finally:
        COMMON_DIRS, EXCLUDE_RES = saved


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.list:
        for b in UI_ROOTS:
            print("%s: %d" % (b, sum(1 for x in ui_prefabs() if x.startswith(b + "/"))))
        print("합계 %d, 제외 %d" % (len(ui_prefabs()), sum(1 for x in ui_prefabs() if is_excluded(x))))
        return 0
    ap.print_help()
    return 2


def selftest():
    ui = ui_prefabs()
    assert ui, "UI 프리팹 0개 — project.json ui_roots 확인"
    assert all(in_scope(x) for x in ui)
    with test_scope():
        assert is_excluded("Assets/Game/UI/Vendor/X/A.prefab") == "vendor"
        assert is_excluded("Assets/Game/UI/Etc/Template/ButtonOld.prefab")
        assert not is_excluded("Assets/Game/UI/Etc/Template/Button.prefab")
        assert is_common("Assets/Game/UI/Common/Button_Yellow.prefab") and not is_common("Assets/Game/UI/Shop/A.prefab")
    assert suffix("A/B/ThumbnailCharacterUnit.prefab") == "Unit" and suffix("A/HomeView.prefab") == "View"
    assert suffix("A/Foo Popup (1).prefab") == "Popup" and suffix("A/Thing.prefab") == ""
    base = {"path": "Root/A", "nested": None}
    assert source_node_id(base) is None
    ns = {"prefab": "Assets/x/Btn.prefab", "guid": "g", "instanceRoot": "Root/A"}
    assert source_node_id(dict(base, nested=ns)) == "Assets/x/Btn.prefab#Btn"
    assert source_node_id({"path": "Root/A/Label", "nested": ns}) == "Assets/x/Btn.prefab#Btn/Label"
    assert source_node_id({"path": "Root/B", "nested": ns}) is None
    assert norm_prop("m_Children.Array.data[3]") == "m_Children[]"
    assert asset_guid(ui[0]) and len(asset_guid(ui[0])) == 32
    print("template_scope.py selftest ok (UI 프리팹 %d)" % len(ui))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
