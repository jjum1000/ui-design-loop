"""P0-1 보강: 화면 → 템플릿 역색인 Docs/ui-design-system/screens.jsonl 의 행을 만든다.

직접 실행하지 않는다 — `python scripts/ds_index.py --run` 이 templates.jsonl·INDEX.md 와 함께 쓰고,
`--check` 가 대조하고, `--selftest` 가 이 파일의 selftest() 를 부른다.

한 줄 = 화면 하나(data/layout/screen/<slug>.json). 필드는 FIELD_ORDER.
- recipe: ds_skeletons 의 형 분류(matches)를 RECIPE_ORDER 우선순위로 하나만 고른다(목록+탭형은 View 기본형의 부분집합).
- templates: 예시·로더·[generated] 를 뺀 정적 템플릿 인스턴스 수(다른 템플릿 안에 든 것 포함), 많은 순.
- lookalikeCopies: 이 화면의 템플릿 사본 노드 수 = 이름 매칭(template null 인데 이름이 템플릿 이름과 같은 노드)
  ∪ 템플릿 메타 lookalikes(exact/near). 같은 경로는 한 번만 센다.
- cleanReference: clean_reference() 규칙(아래 COPY_TOLERANCE·COPY_SHARE) — INDEX.md 에도 같은 문장이 들어간다.
"""
import collections
import json
import os
import re

import common as C
import ds_skeletons as SK

FIELD_ORDER = ("name", "slug", "kind", "recipe", "templates", "loadedTemplates", "lookalikeCopies", "looseButtons",
               "cleanReference", "cleanReason", "app", "map", "image")
LOOSE_SKIP = {"TouchMask"}  # 바깥 터치 닫기 마스크 — 템플릿이 없는 공통 노드
RECIPE_ORDER = ("list-tab", "view-basic", "popup-tall", "popup-wide")
COPY_TOLERANCE = 1      # 사본이 이 수 이하이고
COPY_SHARE = 0.10       # 사본 / (사본 + 정적 템플릿 인스턴스) 가 이 비율 이하이면 깨끗한 참고로 본다
REASON_TOP = 3
COPY_RE = re.compile(r"\s*\(\d+\)\s*$")


def norm_name(s):
    """비교용 이름: 끝의 ' (1)' 제거 → 소문자 → 영숫자만 (ds_pilot.norm_name 과 같은 규칙)."""
    return re.sub(r"[^a-z0-9]", "", COPY_RE.sub("", s or "").lower())


def name_index(temps, tlayout_root_names):
    """{정규화 이름: {slug}} — 템플릿 이름 + 템플릿 배치의 루트 이름."""
    idx = collections.defaultdict(set)
    for t in temps:
        idx[norm_name(t["name"])].add(t["slug"])
        root = tlayout_root_names.get(t["slug"])
        if root:
            idx[norm_name(root)].add(t["slug"])
    return idx


def lookalike_index(temps):
    """{screen slug: [(prefab, 노드 경로, template slug)]} — 템플릿 메타 lookalikes 중 exact/near."""
    res = collections.defaultdict(list)
    for t in temps:
        for x in t.get("lookalikes") or []:
            if x.get("match") in ("exact", "near") and x.get("screen"):
                prefab, _sep, path = x["node"].partition("#")
                res[x["screen"]].append((prefab, path, t["slug"]))
    return res


# ---------------------------------------------------------------- 사본
def tlayout_has_template(tlayout, rel_in):
    """템플릿 배치에서 루트 기준 상대 경로 rel_in 의 박스가 템플릿 인스턴스면 그 slug."""
    if not tlayout or not tlayout.get("boxes"):
        return None
    root = tlayout["boxes"][0]["path"]
    for b in tlayout["boxes"]:
        if b["path"][len(root) + 1:] == rel_in and b.get("template"):
            return b["template"]
    return None


def template_rels(tlayout):
    """템플릿 배치의 루트 기준 상대 경로 집합(예시·로더 포함). 배치가 없으면 None."""
    if not tlayout or not tlayout.get("boxes"):
        return None
    root = tlayout["boxes"][0]["path"]
    return {b["path"][len(root) + 1:] for b in tlayout["boxes"][1:]}


def screen_owned(s, rels_of):
    """화면 몫 노드의 rel 집합 — 템플릿 인스턴스 밖이거나, 인스턴스 안이지만 그 템플릿 배치에 없는 경로(화면에서 덧붙인 노드).
    가장 가까운 템플릿 조상의 배치를 본다. 그 배치가 없으면 템플릿 몫으로 둔다(보수적)."""
    inst, owned = {}, set()
    for n in s["nodes"][1:]:
        parts = n["rel"].split("/")
        anc = next(("/".join(parts[:k]) for k in range(len(parts) - 1, 0, -1) if "/".join(parts[:k]) in inst), None)
        if anc is None:
            owned.add(n["rel"])
        else:
            rels = rels_of(inst[anc])
            if rels is not None and n["rel"][len(anc) + 1:] not in rels:
                owned.add(n["rel"])
        if n["template"]:
            inst[n["rel"]] = n["template"]
    return owned


def under(rel, roots):
    return any(rel.startswith(p + "/") for p in roots)


def loose_buttons(s, owned, copies):
    """템플릿 밖 Button: 화면 몫 · template null · Button 컴포넌트 · TouchMask 아님 · 사본·다른 템플릿 밖 Button 안쪽 아님."""
    out = []
    for n in s["nodes"][1:]:
        if (n["rel"] in owned and not n["template"] and "Button" in n["comps"] and n["name"] not in LOOSE_SKIP
                and n["rel"] not in copies and not under(n["rel"], copies) and not under(n["rel"], out)):
            out.append(n["rel"])
    return out


def same_kind(n, tlayout):
    """노드 컴포넌트가 템플릿 루트 컴포넌트와 하나라도 겹치나. 템플릿 배치·루트 컴포넌트를 모르면 True.
    이름만 같은 다른 것(파티클 'Noise', ResourcesLoader 로더 자리)을 거른다."""
    if not tlayout or not tlayout.get("boxes"):
        return True
    rc = SK.comps_of(tlayout["boxes"][0])
    return not rc or bool(n["comps"] & rc)


def copy_nodes(s, layout_path, names, lookalikes, tlayout_of, owned=None):
    """{rel 경로: template slug} — 이 화면의 템플릿 사본.
    이름 매칭: template null · 화면 몫(owned, 없으면 템플릿 인스턴스 밖) · 이름이 정확히 템플릿 하나와 같음
    · 같은 템플릿 인스턴스 자식이 없음(로더 자리 아님) · 컴포넌트가 템플릿 루트와 겹침(same_kind).
    이미 사본으로 본 노드 안쪽은 원래 템플릿 배치에서 그 자리가 템플릿 인스턴스일 때만 센다(사본 템플릿의 내부 노드 제외).
    lookalikes: 노드 프리팹이 이 화면 프리팹이면 루트를 뗀 경로, 아니면 원래 노드 id 를 키로."""
    children = collections.defaultdict(list)
    for n in s["nodes"]:
        children[n["parent"]].append(n)
    copies = collections.OrderedDict()
    for n in sorted(s["nodes"][1:], key=lambda x: (x["depth"], x["i"])):
        if n["template"] or (n["rel"] not in owned if owned is not None else n["owner"]):
            continue
        slugs = names.get(norm_name(n["name"])) or set()
        if len(slugs) != 1:
            continue
        slug = next(iter(slugs))
        if any(c["template"] == slug for c in children.get(n["rel"], ())):
            continue
        anc = [p for p in copies if n["rel"].startswith(p + "/")]
        if anc:
            cp = max(anc, key=len)
            inner = tlayout_has_template(tlayout_of(copies[cp]), n["rel"][len(cp) + 1:])
            if not inner:
                continue
            slug = inner
        if not same_kind(n, tlayout_of(slug)):
            continue
        copies[n["rel"]] = slug
    for prefab, path, slug in lookalikes:
        if prefab != layout_path:
            key = prefab + "#" + path
        else:
            key = path.split("/", 1)[1] if "/" in path else path
        copies.setdefault(key, slug)
    return copies


def clean_reference(completely, copies, static_total, loose=0):
    """(bool, 이유). Completely 출력 → false. 사본 0 → true. 사본 ≤ COPY_TOLERANCE 이고
    사본 비율(사본 / (사본 + 정적 인스턴스)) ≤ COPY_SHARE → true. 그 밖 → false.
    템플릿 밖 Button(loose)은 판정에 넣지 않고 이유에만 붙인다(템플릿이 없는 버튼일 수 있어 위반으로 단정 못 함)."""
    n = len(copies)
    tail = " · 템플릿 밖 Button %d — 그 버튼 구성은 따르지 말 것" % loose if loose else ""
    if completely:
        return False, "Completely 언팩 빌드 툴 출력 — 템플릿 링크가 끊긴 반면교사" + tail
    if n == 0:
        return True, "사본 0 · 정적 템플릿 인스턴스 %d" % static_total + tail
    share = n / float(n + static_total)
    top = collections.Counter(copies.values()).most_common(REASON_TOP)
    what = ", ".join("%s ×%d" % kv for kv in top) + (" 외" if len(set(copies.values())) > REASON_TOP else "")
    ok = n <= COPY_TOLERANCE and share <= COPY_SHARE
    return ok, "사본 %d(%s) · 사본 비율 %d%% — 허용 기준(사본 ≤%d · 비율 ≤%d%%) %s%s" % (
        n, what, round(share * 100), COPY_TOLERANCE, round(COPY_SHARE * 100), "안" if ok else "넘음", tail)


# ---------------------------------------------------------------- 앱
def app_index(flow, levels_of):
    """{prefab 경로: [contentsType]} — 앱 첫 화면에서의 단계가 가까운 순(같으면 앱 순서)."""
    if not flow:
        return {}
    best = {}
    for ai, a in enumerate(flow.get("apps") or []):
        for depth, lv in enumerate(levels_of(flow, a["screens"])):
            for ui, _src in lv:
                pf = (flow["screens"].get(ui) or {}).get("prefab")
                if pf:
                    key = (depth, ai)
                    cur = best.setdefault(pf, {})
                    if a["contentsType"] not in cur or key < cur[a["contentsType"]]:
                        cur[a["contentsType"]] = key
    return {pf: [c for c, _k in sorted(d.items(), key=lambda kv: kv[1])] for pf, d in best.items()}


# ---------------------------------------------------------------- 행
def recipe_of(s):
    for rid in RECIPE_ORDER:
        r = next(x for x in SK.RECIPES if x["id"] == rid)
        if SK.matches(s, r):
            return rid
    return "none"


def screen_findings(layout, names, lookalikes, tlayout_of, rels_of):
    """(normalize 결과, 사본 {rel: slug}, 템플릿 밖 Button [rel])."""
    s = SK.normalize(layout)
    owned = screen_owned(s, rels_of)
    copies = copy_nodes(s, layout["path"], names, lookalikes.get(layout["slug"], ()), tlayout_of, owned)
    return s, copies, loose_buttons(s, owned, copies)


def build_row(layout, names, lookalikes, tlayout_of, rels_of, completely, apps, exists=os.path.exists):
    s, copies, loose = screen_findings(layout, names, lookalikes, tlayout_of, rels_of)
    static = collections.Counter(n["template"] for n in s["nodes"] if n["template"])
    loaded = sorted({b["template"] for b in layout["boxes"]
                     if b.get("template") and (b.get("sample") or b.get("loader"))} - set(static))
    ok, why = clean_reference(s["name"] in completely, copies, sum(static.values()), len(loose))
    img = "previews/layout/screen/%s.png" % layout["slug"]
    row = {
        "name": s["name"], "slug": layout["slug"], "kind": s["kind"] or "other", "recipe": recipe_of(s),
        "templates": collections.OrderedDict(sorted(static.items(), key=lambda kv: (-kv[1], kv[0]))),
        "loadedTemplates": loaded, "lookalikeCopies": len(copies), "looseButtons": len(loose),
        "cleanReference": ok, "cleanReason": why,
        "app": apps.get(layout["path"]) or None,
        "map": "ui-audit/catalog/map/%s.html" % layout["slug"],
        "image": "ui-audit/" + img if exists(C.p(img)) else None,
    }
    return {k: row[k] for k in FIELD_ORDER}


def build_rows(layouts, temps, tlayouts, completely, flow, levels_of, exists=os.path.exists):
    """layouts: 화면 배치 목록 · temps: 템플릿 메타 목록 · tlayouts: {slug: 템플릿 배치} (없으면 None 값 허용)."""
    names, lk, rels_of = indexes(temps, tlayouts)
    apps = app_index(flow, levels_of)
    rows = [build_row(l, names, lk, tlayouts.get, rels_of, completely, apps, exists) for l in layouts]
    return sorted(rows, key=lambda r: (r["name"].lower(), r["slug"]))


def indexes(temps, tlayouts):
    """(이름 색인, lookalikes 색인, 템플릿 경로 집합 조회 함수(캐시))."""
    names = name_index(temps, {k: v["boxes"][0]["name"] for k, v in tlayouts.items() if v and v.get("boxes")})
    cache = {}

    def rels_of(slug):
        if slug not in cache:
            cache[slug] = template_rels(tlayouts.get(slug))
        return cache[slug]
    return names, lookalike_index(temps), rels_of


def copy_detail(layout, temps, tlayouts):
    """디버그·보고용: ({rel: slug} 사본, [rel] 템플릿 밖 Button)."""
    names, lk, rels_of = indexes(temps, tlayouts)
    _s, copies, loose = screen_findings(layout, names, lk, tlayouts.get, rels_of)
    return copies, loose


def jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows)


def load_inputs():
    """(화면 배치들, 템플릿 배치 {slug: 배치}, app-flow)."""
    layouts = [C.load_json(f) for f in C.iter_json(C.p("data", "layout", "screen"))]
    tlayouts = {}
    for f in C.iter_json(C.p("data", "layout", "template")):
        t = C.load_json(f)
        tlayouts[t["slug"]] = t
    return layouts, tlayouts, C.load_json(C.p("data", "app-flow.json"))


def clean_map(rows):
    """{slug: (cleanReference, cleanReason)} — ds_skeletons 출처 화면 경고용."""
    return {r["slug"]: (r["cleanReference"], r["cleanReason"]) for r in rows}


# ---------------------------------------------------------------- 자체 테스트
def selftest():
    def B(path, tpl=None, sample=False, loader=False, comps=""):
        return {"path": path, "name": path.split("/")[-1], "depth": path.count("/"), "x": 0, "y": 0, "w": 10, "h": 10,
                "template": tpl, "active": True, "sample": sample, "loader": loader, "comps": comps}
    pv = "Assets/UI/AView.prefab"
    a = {"slug": "aview", "path": pv, "boxes": [
        B("AView", comps="AView"), B("AView/UnSafeArea"), B("AView/SafeArea", comps="SafeArea"),
        B("AView/UnSafeArea/ContentTitle", "contenttitle"),
        B("AView/SafeArea/BackButton", "backbutton"),
        B("AView/SafeArea/Button_Yellow"),                                # 이름 사본 (template null)
        B("AView/SafeArea/Button_Yellow/Label"),
        B("AView/SafeArea/Popup_Rect", comps="CanvasGroup"),              # 사본 → 안쪽 Popup_BG_Tall 도 사본
        B("AView/SafeArea/Slot2/Popup_Rect", comps="ResourcesLoader"),   # 이름만 같은 로더 자리(컴포넌트 안 겹침)
        B("AView/SafeArea/Popup_Rect/Popup_BG_Tall"),
        B("AView/SafeArea/Popup_Rect/Title"),                             # 사본 내부 일반 노드(제외)
        B("AView/SafeArea/Slot"), B("AView/SafeArea/Slot/Slot", "slot"),  # 로더 자리(같은 이름 자식이 템플릿)
        B("AView/SafeArea/List", comps="ScrollRect,WrapContent"),
        B("AView/SafeArea/List/Item", "itemunit", sample=True),
        B("AView/SafeArea/List/Item/Button_Yellow", sample=True),        # 예시 안(제외)
        B("AView/SafeArea/Load/X", "loadunit", loader=True),
        B("AView/SafeArea/Weird"),                                        # lookalikes 사본
        B("AView/SafeArea/Button_Yellow/Dimmed", comps="Image,Button"),  # 사본 안 Button(템플릿 밖 Button 아님)
        B("AView/UnSafeArea/TouchMask", comps="Button"),                  # 제외 이름
        B("AView/SafeArea/[generated] Button_Yellow")]}                  # generated(제외)
    b = {"slug": "bpopup", "path": "Assets/UI/BPopup.prefab", "boxes": [
        B("BPopup", comps="BPopup"), B("BPopup/SafeArea/BG", "popup-bg-tall"),
        B("BPopup/SafeArea/BG/Button_Yellow", "button-yellow"),
        B("BPopup/SafeArea/BG/Frame", comps="Image,Button"),              # 템플릿 내부(배치에 있음)
        B("BPopup/SafeArea/BG/Body/Button_Cancel", comps="Button"),       # 템플릿 안에 덧붙인 손조립 버튼
        B("BPopup/SafeArea/BG/Body/Button_Cancel/Hit", comps="Button"),   # 그 안쪽(중복 안 셈)
        B("BPopup/SafeArea/BG/Body/Popup_Rect", comps="CanvasGroup")]}                         # 템플릿 안에 덧붙인 사본
    c = {"slug": "cview", "path": "Assets/UI/CView.prefab", "boxes": [B("CView", comps="CView")]}
    temps = [{"slug": s, "name": n, "lookalikes": None} for s, n in (
        ("contenttitle", "ContentTitle"), ("backbutton", "BackButton"), ("button-yellow", "Button_Yellow"),
        ("popup-rect", "Popup_Rect"), ("popup-bg-tall", "Popup_BG_Tall"), ("slot", "Slot"), ("itemunit", "ItemUnit"),
        ("loadunit", "LoadUnit"))]
    temps[2]["lookalikes"] = [{"node": pv + "#AView/SafeArea/Weird", "screen": "aview", "match": "near"},
                              {"node": pv + "#AView/SafeArea/Button_Yellow", "screen": "aview", "match": "exact"},
                              {"node": pv + "#AView/SafeArea/Other", "screen": "aview", "match": "borderline"}]
    tl = {"popup-rect": {"slug": "popup-rect", "boxes": [B("Popup_Rect", comps="VerticalLayoutGroup,CanvasGroup"),
                                                         B("Popup_Rect/Popup_BG_Tall", "popup-bg-tall"),
                                                         B("Popup_Rect/Title")]},
          "popup-bg-tall": {"slug": "popup-bg-tall", "boxes": [B("Popup_BG_Tall"), B("Popup_BG_Tall/Frame", comps="Button")]}}
    flow = {"apps": [{"contentsType": "Far", "screens": ["XView"]}, {"contentsType": "Near", "screens": ["AView"]}],
            "screens": {"XView": {"prefab": "x", "next": [{"uiType": "AView"}]}, "AView": {"prefab": pv, "next": []}}}

    def levels(fl, start):
        out, seen, cur = [], set(start), [(u, None) for u in start]
        while cur:
            out.append(cur)
            nxt = [(n["uiType"], u) for u, _ in cur for n in fl["screens"].get(u, {}).get("next", []) if n["uiType"] not in seen]
            seen.update(x for x, _ in nxt)
            cur = nxt
        return out
    rows = build_rows([a, b, c], temps, tl, {"CView"}, flow, levels, exists=lambda p: p.endswith("aview.png"))
    by = {r["slug"]: r for r in rows}
    assert [r["slug"] for r in rows] == ["aview", "bpopup", "cview"] and list(by["aview"]) == list(FIELD_ORDER)
    det, loose = copy_detail(a, temps, tl)
    assert dict(det) == {"SafeArea/Button_Yellow": "button-yellow", "SafeArea/Popup_Rect": "popup-rect",
                         "SafeArea/Popup_Rect/Popup_BG_Tall": "popup-bg-tall", "SafeArea/Weird": "button-yellow"}, det
    assert loose == [], loose  # 사본 안 Button·TouchMask 는 안 셈
    det_b, loose_b = copy_detail(b, temps, tl)
    assert dict(det_b) == {"SafeArea/BG/Body/Popup_Rect": "popup-rect"}, det_b  # 템플릿 안에 덧붙인 노드도 화면 몫
    assert loose_b == ["SafeArea/BG/Body/Button_Cancel"], loose_b  # 템플릿 내부 Frame·버튼 안쪽 Hit 제외
    ar = by["aview"]
    assert ar["kind"] == "View" and ar["recipe"] == "view-basic", ar  # 탭 없음 → 목록+탭형 아님
    assert ar["templates"] == {"backbutton": 1, "contenttitle": 1, "slot": 1} and list(ar["templates"])[0] == "backbutton"
    assert ar["loadedTemplates"] == ["itemunit", "loadunit"] and ar["lookalikeCopies"] == 4
    assert ar["cleanReference"] is False and "사본 4(button-yellow ×2" in ar["cleanReason"] and "넘음" in ar["cleanReason"]
    assert ar["app"] == ["Near", "Far"], ar["app"]  # 단계 0 이 단계 1 보다 먼저
    assert ar["image"] == "ui-audit/previews/layout/screen/aview.png" and ar["map"] == "ui-audit/catalog/map/aview.html"
    br = by["bpopup"]
    assert br["kind"] == "Popup" and br["recipe"] == "popup-tall" and br["app"] is None
    assert br["lookalikeCopies"] == 1 and br["looseButtons"] == 1 and br["cleanReference"] is False  # 비율 33%
    assert br["cleanReason"].endswith("템플릿 밖 Button 1 — 그 버튼 구성은 따르지 말 것"), br["cleanReason"]
    assert br["templates"] == {"button-yellow": 1, "popup-bg-tall": 1} and br["image"] is None
    cr = by["cview"]
    assert cr["cleanReference"] is False and cr["cleanReason"].startswith("Completely") and cr["recipe"] == "none"
    assert cr["kind"] == "View" and cr["templates"] == {}
    assert clean_reference(False, {"x": "s"}, 9) == (True, "사본 1(s ×1) · 사본 비율 10% — 허용 기준(사본 ≤1 · 비율 ≤10%) 안")
    assert clean_reference(False, {"x": "s"}, 3)[0] is False      # 비율 25% 초과
    assert clean_reference(False, {"x": "s", "y": "t"}, 100)[0] is False  # 사본 2 초과
    assert clean_reference(False, {}, 0, loose=5)[0] is True       # 템플릿 밖 Button 은 판정에 안 넣는다
    line = jsonl(rows).splitlines()[1]
    assert re.search(r'"kind":"Popup".*"button-yellow":', line) and re.search(r'"popup-bg-tall":.*"cleanReference":false', line)
    assert norm_name("Button_Yellow (2)") == "buttonyellow"
    return "ds_screens ok (행 %d · 사본 %d)" % (len(rows), ar["lookalikeCopies"])


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["--selftest"]:
        sys.exit("사용: python scripts/ds_screens.py --selftest (생성은 ds_index.py --run)")
    print(selftest().replace("ds_screens ok", "ds_screens.py selftest ok"))
