"""T7·S5 탐색기 페이지 빌더(build_catalog.py 가 부른다).
  app-flow.html            홈 — 앱 아이콘 그리드 → 그 앱의 화면 흐름(화면 썸네일 카드 → 다음 화면)
  map.html, map/<slug>     화면 배치 맵 — Unity 렌더 위에 템플릿 박스(data/layout/screen)
  templates.html           템플릿 갤러리(카드 ↔ 표) / templates/<slug> 템플릿 배치 맵·사용처·오버라이드·유사품
  scenes.html, scenes/<씬>, unused.html
그리고 screens/<화면>.html(노드 카탈로그)에 붙일 '구성 템플릿' 절. 이미지는 lazy, 뷰어 데이터는 페이지 안 JSON(fetch 없음).

직접 실행하지 않는다 — python scripts/build_catalog.py --templates (또는 --all) 로 쓴다.
"""
import collections
import json
import os
import shutil

import catalog_flow_badges as CFB
import catalog_review as CR
import common as C
import template_scope as TS

PAGES = ["app-flow", "map", "templates", "scenes", "unused", "review"]
NAV = [("app-flow.html", "앱 흐름"), ("map.html", "화면 맵"), ("templates.html", "템플릿"), ("scenes.html", "씬"),
       ("unused.html", "미사용")]
CSS = ""  # 스타일은 catalog/assets/explorer.css (catalog_assets.py)
FLOW_DEPTH = 6
LIST_CAP = 60


class TData:
    """템플릿 카탈로그·배치 맵 데이터. 없으면 빈 상태(present=False)."""

    def __init__(self, empty=False):
        idx = None if empty else C.load_json(C.p("data", "template-index.json"))
        self.present = idx is not None
        self.idx = idx or {"templates": [], "screens": [], "unused": [], "excluded": [], "counts": {}, "rules": {}}
        self.t = {s: C.load_json(C.p("data", "templates", s + ".json")) for s in self.idx["templates"]}
        self.by_path = {t["path"]: t for t in self.t.values()}
        self.reach = (None if empty else C.load_json(C.p("data", "scenes", "reachable.json"))) or \
            {"scenes": [], "unreferenced": [], "missing": [], "stats": {}}
        self.scene_ui = {}
        for s in self.reach["scenes"]:
            self.scene_ui[s["name"]] = C.load_json(C.p("data", "scenes", "ui", C.slugify(s["name"]) + ".json")) or {"canvases": []}
        self.edges = [] if empty else (C.load_json(C.p("data", "usage", "edges.json")) or {"edges": []})["edges"]
        self.fwd = collections.defaultdict(set)
        for e in self.edges:
            if e["userType"] in ("prefab", "scene") and e["template"]:
                self.fwd[e["user"]].add(e["template"])
        self.screen_by_path = {s["path"]: s for s in self.idx["screens"]}
        self.thumb_fail = {} if empty else {x["slug"]: x["reason"] for k in ("failed", "blank")
                                            for x in (C.load_json(C.p("previews", "templates", "_failed.json")) or {}).get(k, [])}
        self.flow = None if empty else C.load_json(C.p("data", "app-flow.json"))
        # 화면 slug: template-index 우선, 없으면 흐름의 slug (layout_map.targets 와 같은 규칙)
        self.screen_slug = {s["path"]: s["slug"] for s in self.idx["screens"]}
        for s in (self.flow or {"screens": {}})["screens"].values():
            if s.get("prefab") and s["prefab"] not in self.screen_slug:
                self.screen_slug[s["prefab"]] = s.get("slug") or C.slugify(TS.stem(s["prefab"]))
        self.layout_slugs = {k: set() if empty else {os.path.basename(f)[:-5] for f in C.iter_json(C.p("data", "layout", k))}
                             for k in ("screen", "template")}
        self.ui_by_path = collections.defaultdict(list)
        for ui, s in (self.flow or {"screens": {}})["screens"].items():
            if s.get("prefab"):
                self.ui_by_path[s["prefab"]].append(ui)
        self.app_levels = {a["contentsType"]: flow_levels(self.flow, a["screens"]) for a in (self.flow or {"apps": []})["apps"]}
        self.apps_of = collections.defaultdict(list)  # UIType → [앱]
        for a in (self.flow or {"apps": []})["apps"]:
            for lv in self.app_levels[a["contentsType"]]:
                for ui, _src in lv:
                    self.apps_of[ui].append(a)

    def layout(self, kind, slug):
        return C.load_json(C.p("data", "layout", kind, slug + ".json")) if slug in self.layout_slugs[kind] else None

    def descendants(self, start):
        seen, todo = set(), list(self.fwd.get(start, ()))
        while todo:
            x = todo.pop()
            if x not in seen:
                seen.add(x)
                todo += list(self.fwd.get(x, ()))
        return seen


def flow_levels(flow, start):
    """[[(UIType, 이전 UIType|None)]] — 앱 첫 화면에서 BFS. 한 앱 안에서 이미 나온 화면은 다시 펼치지 않는다."""
    if not flow:
        return []
    levels, seen, cur = [], set(start), [(u, None) for u in start]
    while cur and len(levels) < FLOW_DEPTH:
        levels.append(cur)
        nxt = []
        for ui, _src in cur:
            for n in flow["screens"].get(ui, {}).get("next", []):
                if n["uiType"] not in seen:
                    seen.add(n["uiType"])
                    nxt.append((n["uiType"], ui))
        cur = nxt
    return levels


def folder(path):
    if TS.is_common(path):
        return "common"
    parts = path.split("/")
    return parts[4] if len(parts) > 5 else parts[-2]


def color_key(t):
    """박스 색 키: 템플릿 종류, 종류가 other 면 위계."""
    return t["kind"] if t["kind"] != "other" else t["tier"]


# ---------------------------------------------------------------- 공통 조각
def img_src(B, pdir, rel):
    full = C.p(rel)
    return B.E(B.rel_link(pdir, full)) if os.path.exists(full) else None


def template_thumb(B, td, pdir, t):
    """(img src|None, 사유) — 배치 맵 렌더 썸네일 우선, 없으면 T6 썸네일."""
    for rel in ("previews/layout/template/%s.thumb.png" % t["slug"], "previews/templates/%s.png" % t["slug"]):
        src = img_src(B, pdir, rel)
        if src:
            return src, None
    why = td.thumb_fail.get(t["slug"])
    return None, ("런타임 바인딩" if why in ("완전 투명", "단일 색") else ("렌더 실패" if why else "썸네일 없음"))


def screen_thumb(B, pdir, slug):
    return img_src(B, pdir, "previews/layout/screen/%s.thumb.png" % slug) if slug else None


def ph(src, alt, cls="", none="이미지 없음"):
    inner = "<img loading='lazy' src='%s' alt='%s'>" % (src, alt) if src else "<span class='none'>%s</span>" % none
    return "<div class='ph chk %s'>%s</div>" % (cls, inner)


def tcard(B, td, pdir, t, up, i=0, extra=""):
    E = B.E
    src, why = template_thumb(B, td, pdir, t)
    ov = t.get("overrides") or {}
    bar = "<div class='bar' title='변형 사용 %.0f%% · 스타일 변형 %.0f%%'><i style='width:%.0f%%'></i><i style='width:%.0f%%'></i></div>" % (
        100 * ov.get("modifiedRate", 0), 100 * ov.get("styledRate", 0), 100 * ov.get("modifiedRate", 0), 100 * ov.get("styledRate", 0)) \
        if ov.get("instances") else ""
    return ("<a class='tc' style='--i:%d' href='%stemplates/%s.html' data-name='%s' data-tier='%s' data-folder='%s' data-kind='%s' "
            "data-usage='%d' data-screens='%d'>%s<span class='corner'>%s</span><span class='big'>%d</span>"
            "<div class='meta'><div class='nm' title='%s'>%s</div><div class='sub'><span>화면 %d</span><span>%s</span>%s</div>%s</div></a>") % (
        min(i, 40), up, E(t["slug"]), E(t["name"].lower()), t["tier"], E(folder(t["path"]).lower()), E(t["kind"]), t["usageTotal"],
        len(t["screens"]), ph(src, E(t["name"]), none=E(why or "")), t["tier"], t["usageTotal"], E(t["path"]), E(t["name"]),
        len(t["screens"]), E(folder(t["path"])), extra, bar)


def scard(B, td, pdir, slug, title, up, sub="", i=0, cls=""):
    """화면 카드 — 배치 맵이 있으면 map/<slug>.html 로."""
    E = B.E
    src = screen_thumb(B, pdir, slug)
    has = slug in td.layout_slugs["screen"]
    tag = "a" if has else "div"
    href = " href='%smap/%s.html'" % (up, E(slug)) if has else ""
    return "<%s class='tc fcard %s' style='--i:%d'%s data-name='%s'>%s<div class='meta'><div class='nm' title='%s'>%s</div>%s</div></%s>" % (
        tag, cls, min(i, 40), href, E((title or "").lower()), ph(src, E(title), "wide full", "배치 맵 없음"), E(title), E(title), sub, tag)


def ui_slug(td, ui):
    s = (td.flow or {"screens": {}})["screens"].get(ui) or {}
    return td.screen_slug.get(s.get("prefab")) if s.get("prefab") else None


def screen_link(B, d, path, depth=1):
    """화면 프리팹 경로 → 배치 맵 또는 노드 카탈로그 screens/<slug>.html 링크(있으면) 또는 이름."""
    up = "../" * depth
    td = getattr(d, "td", None)
    slug = td.screen_slug.get(path) if td else None
    if slug and slug in td.layout_slugs["screen"]:
        return "<a href='%smap/%s.html'>%s</a>" % (up, B.E(slug), B.E(TS.stem(path)))
    for b in d.batches.values():
        for s in b["screens"]:
            if s["prefab"] == path:
                return "<a href='%sscreens/%s.html'>%s</a>" % (up, B.E(s["slug"]), B.E(s["name"]))
    return B.E(TS.stem(path))


def user_link(B, d, td, user, depth=1):
    up = "../" * depth
    if user in td.by_path:
        t = td.by_path[user]
        return "<a href='%stemplates/%s.html'>%s</a>" % (up, B.E(t["slug"]), B.E(t["name"]))
    if user.endswith(".unity"):
        name = next((s["name"] for s in td.reach["scenes"] if s["path"] == user), TS.stem(user))
        return "<a href='%sscenes/%s.html'>%s</a>" % (up, B.E(C.slugify(name)), B.E(name))
    if user.endswith(".prefab"):
        return screen_link(B, d, user, depth)
    return "<span class='mut'>%s</span>" % B.E(user.rsplit("/", 1)[-1])


def tlink(B, td, slug, depth=1):
    t = td.t.get(slug)
    return "<a href='%stemplates/%s.html'>%s</a>" % ("../" * depth, B.E(slug), B.E(t["name"] if t else slug))


def kpis(items):
    return "<div class='kpis'>%s</div>" % "".join(
        "<div class='kpi%s'><b>%s</b><span>%s</span></div>" % (" hot" if hot else "", v, k) for k, v, hot in items)


# ---------------------------------------------------------------- 배치 맵 뷰어
def viewer(B, td, pdir, lay, up, vid="layout-data"):
    """렌더 이미지 + 박스 오버레이 + 계층 트리. 활성 노드만 싣는다(트리 순서 = Unity 하이어라키 전위 순회)."""
    E = B.E
    tpls, tix, rows = [], {}, []
    for b in lay["boxes"]:
        if not b["active"] or "/[generated] " in "/" + b["path"]:  # UIParticle 이 에디터에서 만든 노드는 프리팹에 없다
            continue
        ti = -1
        t = td.t.get(b["template"]) if b["template"] else None
        if t:
            if t["slug"] not in tix:
                tix[t["slug"]] = len(tpls)
                tpls.append([t["slug"], t["name"], color_key(t), t["tier"]])
            ti = tix[t["slug"]]
        flags = (1 if b["sample"] else 0) | (2 if b["loader"] else 0)
        rows.append([b["x"], b["y"], b["w"], b["h"], b["depth"], flags, b["name"], ti])
    if rows:  # 활성 노드만 남기면 깊이가 끊길 수 있다 — 트리 들여쓰기는 직전 행 +1 로 제한
        rows[0][4] = 0
        for i in range(1, len(rows)):
            rows[i][4] = min(rows[i][4], rows[i - 1][4] + 1)
    data = {"w": lay["width"], "h": lay["height"], "s": lay.get("scale") or 1, "kind": lay["kind"],
            "base": up + "templates/", "b": rows, "t": tpls}
    src = img_src(B, pdir, lay["image"])
    kinds = sorted({t[2] for t in tpls})
    legend = "".join("<span data-k='%s'><i></i>%s</span>" % (E(k), E(C.KIND_LABELS.get(k, k))) for k in kinds)
    blank = "<div class='note'>렌더 결과가 비어 있다 — 런타임에 내용이 채워지는 화면. 박스 위치는 Unity 배치 그대로다.</div>" if lay.get("blank") else ""
    return ("%s<div class='viewer' data-layout='%s'><div class='vtool'>"
            "<button class='ib' data-z='0.8' title='축소'>−</button><span class='z'>100%%</span><button class='ib' data-z='1.25' title='확대'>+</button>"
            "<button class='ib' data-z='fit' title='맞춤' style='width:auto;padding:0 8px;font-size:13px'>FIT</button>"
            "<div class='seg'><button data-mode='tpl'>템플릿</button><button data-mode='all'>모든 노드</button><button data-mode='off'>끔</button></div>"
            "<label><input type='checkbox' data-opt='nosample' checked> 예시 아이템</label>"
            "<label><input type='checkbox' data-opt='noloader' checked> 로더 자식</label>"
            "<div class='legend'>%s<span style='--c:#bbb'><i></i>일반 노드</span></div></div>"
            "<div class='stagewrap chk%s'><div class='stage'><img src='%s' alt='%s'><div class='boxes mode-tpl'></div></div></div>"
            "<aside class='side'><div class='info'><div class='mut'>박스에 마우스를 올리면 이름이, 템플릿 박스를 누르면 그 템플릿으로 내려간다. "
            "Shift+클릭은 선택만. 트리 항목을 누르면 위치를 찾는다. Ctrl+휠 확대.</div></div>"
            "<div class='tf'><input type='search' placeholder='노드·템플릿 이름 찾기'></div><div class='vtree'></div></aside></div>"
            "<script type='application/json' id='%s'>%s</script>") % (
        blank, vid, legend, " small" if lay["kind"] == "template" else "", src or "", E(lay["slug"]), vid,
        json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))


# ---------------------------------------------------------------- 앱 흐름(홈)
def app_state(a):
    return ("숨김" if a["hidden"] == "always" else "조건부 숨김" if a["hidden"] else "") or ("" if a["enabled"] else "꺼짐")


def build_app_flow(B, d, td, out):
    E = B.E
    flow = td.flow if td.present else None
    if not flow:
        B.write(out, "app-flow.html", B.page("앱 흐름", "<p class='mut'>data/app-flow.json 없음 — python scripts/app_flow.py --run</p>",
                                             nav="app-flow.html"))
        return
    st = flow["stats"]
    apps = [{"contentsType": flow["appScreen"], "label": "앱 화면", "hidden": None, "enabled": True, "iconPath": None,
             "screens": [flow["appScreen"]]}] + flow["apps"]
    td.app_levels.setdefault(flow["appScreen"], flow_levels(flow, [flow["appScreen"]]))
    reg = C.load_json(C.p("design", "registry.json")) or {"screens": {}}  # 설계 단계 배지(feedback/CONTRACT.md 4.6)
    icons, panes = [], []
    for a in apps:
        key = a["contentsType"].lower()
        st_ = app_state(a)
        icon = "<em>%s</em>" % E((a["label"] or a["contentsType"])[:1])
        if a.get("iconPath"):
            full = os.path.join(C.unity_root(), a["iconPath"])
            if os.path.exists(full):
                icon = "<img src='%s' alt=''>" % E(B.rel_link(out, full))
        icons.append("<button class='app%s' data-app='%s' title='%s'><span class='ic'>%s</span>%s<span class='lb'>%s</span>%s</button>" % (
            " off" if st_ else "", E(key), E(a["contentsType"]), icon, CFB.app_badge_html(E, reg, a["contentsType"]),
            E(a["label"] or a["contentsType"]),
            "<span class='st'>%s</span>" % E(st_) if st_ else ""))
        levels = td.app_levels.get(a["contentsType"]) or []
        cols = []
        for li, lv in enumerate(levels):
            cards = []
            for i, (ui, src) in enumerate(lv):
                s = flow["screens"].get(ui) or {"next": [], "prefab": None}
                slug = ui_slug(td, ui)
                lay_n = len(td.screen_by_path.get(s.get("prefab"), {}).get("templates", [])) if s.get("prefab") else 0
                via = next((n["via"] for n in flow["screens"].get(src, {}).get("next", []) if n["uiType"] == ui), "") if src else ""
                sub = "<div class='nx'>다음 %d · 템플릿 %d%s</div>%s" % (
                    len(s["next"]), lay_n, "" if s.get("prefab") else " · <span class='warn'>프리팹 없음</span>",
                    "<div class='via' title='%s'>← %s</div>" % (E(src or ""), E(via)) if via else "") + CFB.screen_badges_html(E, reg, ui)
                cards.append(scard(B, td, out, slug, ui, "", sub, i))
            cols.append(("<div class='arrow'></div>" if li else "") +
                         "<div class='col'><div class='step'>%s</div>%s</div>" % ("시작" if li == 0 else "STEP %d" % li, "".join(cards)))
        n_screens = sum(len(lv) for lv in levels)
        panes.append("<section class='flowpane hidden' id='pane-%s'><div class='flowhead'><h2>%s <span class='n'>%s</span></h2>%s"
                     "<span class='tag'>화면 %d</span></div><div class='lane'>%s</div></section>" % (
                         E(key), E(a["label"] or a["contentsType"]), E(a["contentsType"]), "<span class='tag r'>%s</span>" % E(st_) if st_ else "",
                         n_screens, "".join(cols) or "<div class='empty'>열리는 화면 대응 없음</div>"))
    head = kpis([("앱", st["apps"], False), ("앱 화면에 보이는 앱", st["appsShown"], True), ("화면", st["screens"], False),
                 ("전환", st["edges"], False), ("View·Unit 추가", st.get("edgesScript", 0), False), ("미해결", len(flow["unresolved"]), False)])
    note = ("<div class='note'>앱 화면(%s) 아이콘 → 처음 열리는 화면 → 그 화면이 여는 다음 화면. Controller·View·Unit 스크립트의 "
            "EnterAsync·OpenContents 호출을 정적으로 따라간 결과다. 카드를 누르면 Unity 가 계산한 실제 배치 위에 템플릿 박스가 겹친 화면 맵이 열린다. "
            "한 앱 안에서 이미 나온 화면은 다시 펼치지 않는다.</div>") % E(flow["appScreen"])
    body = ("%s%s%s%s<div class='home'><div class='phone'><div class='bar0'><span>DYNAMITE·APP</span><span>%d</span></div>"
            "<div class='apps'>%s</div></div><div class='flow'>%s</div></div>") % (
        CFB.head_html(), head, CFB.progress_html(E, reg), note, len(apps), "".join(icons), "".join(panes))
    B.write(out, "app-flow.html", B.page("앱 흐름", body, nav="app-flow.html", wide=True))


# ---------------------------------------------------------------- 화면 맵
def build_map(B, d, td, out):
    E = B.E
    flow = td.flow or {"screens": {}, "apps": []}
    slugs = sorted(td.layout_slugs["screen"])
    path_of = {v: k for k, v in td.screen_slug.items()}
    cards = []
    for i, slug in enumerate(slugs):
        uis = td.ui_by_path.get(path_of.get(slug), [])
        apps = sorted({a["label"] or a["contentsType"] for ui in uis for a in td.apps_of.get(ui, [])})
        sub = "<div class='sub'>%s%s</div>" % ("".join("<span class='tag y'>%s</span>" % E(x) for x in apps[:3]),
                                               "<span class='tag'>흐름 밖</span>" if not uis else "")
        cards.append(scard(B, td, out, slug, TS.stem(path_of.get(slug, slug)), "", sub, i))
    fl = sum(1 for s in slugs if td.ui_by_path.get(path_of.get(s)))
    body = kpis([("화면 맵", len(slugs), True), ("앱 흐름 안", fl, False), ("흐름 밖", len(slugs) - fl, False)])
    body += ("<div class='filters'><input type='search' data-f='q' placeholder='화면 이름 찾기'><span class='grow'></span>"
             "<span class='mut'>표시 <b id='cnt'></b></span></div><div class='cards' data-gallery>%s</div>"
             "<table id='tview' class='hidden'></table>") % ("".join(cards) or "<div class='empty'>배치 데이터 없음 — layout_map.py --collect</div>")
    B.write(out, "map.html", B.page("화면 맵", body, nav="map.html", wide=True))
    pdir = os.path.join(out, "map")
    for slug in slugs:
        lay = td.layout("screen", slug)
        B.write(out, "map/%s.html" % slug, B.page(TS.stem(lay["path"]), map_body(B, d, td, lay, pdir, flow), depth=1, wide=True,
                                                  crumbs=map_crumbs(td, lay), nav="map.html"))


def map_crumbs(td, lay):
    uis = td.ui_by_path.get(lay["path"], [])
    for ui in uis:
        for a in td.apps_of.get(ui, []):
            return [("앱 흐름", "../app-flow.html"), (a["label"] or a["contentsType"], "../app-flow.html#app-" + a["contentsType"].lower())]
    return [("화면 맵", "../map.html")]


def map_body(B, d, td, lay, pdir, flow):
    E = B.E
    uis = td.ui_by_path.get(lay["path"], [])
    apps = sorted({(a["label"] or a["contentsType"], a["contentsType"]) for ui in uis for a in td.apps_of.get(ui, [])})
    st = lay.get("stats", {})
    used = collections.Counter(b["template"] for b in lay["boxes"] if b["active"] and b["template"] and not b["sample"])
    body = "<div class='facts'>%s%s<span class='tag'>%s</span></div>" % (
        "".join("<a class='tag y' href='../app-flow.html#app-%s'>%s</a>" % (E(c.lower()), E(lbl)) for lbl, c in apps),
        "".join("<span class='tag c'>UIType.%s</span>" % E(u) for u in uis), E(lay["path"]))
    old = next((s["slug"] for b in d.batches.values() for s in b["screens"] if s["prefab"] == lay["path"]), None)
    body += kpis([("활성 노드", st.get("active", 0), False), ("템플릿 인스턴스", st.get("templates", 0), True),
                  ("서로 다른 템플릿", len(used), False), ("예시 아이템 노드", st.get("sample", 0), False),
                  ("로더 자식 노드", st.get("loader", 0), False)])
    if old:
        body += "<p class='mut'>노드 단위 분류·스크린샷: <a href='../screens/%s.html'>노드 카탈로그 화면 페이지</a></p>" % E(old)
    body += viewer(B, td, pdir, lay, "../")
    inc = sorted({(src, n["via"]) for src, s in flow["screens"].items() for n in s["next"] if n["uiType"] in uis})
    nxt = [n for ui in uis for n in flow["screens"][ui]["next"]]
    if inc:
        body += "<h2>들어오는 화면 <span class='n'>%d</span></h2><div class='cards sm'>%s</div>" % (len(inc), "".join(
            scard(B, td, pdir, ui_slug(td, src), src, "../", "<div class='via'>%s</div>" % E(via), i) for i, (src, via) in enumerate(inc)))
    if nxt:
        body += "<h2>이어지는 화면 <span class='n'>%d</span></h2><div class='cards sm'>%s</div>" % (len(nxt), "".join(
            scard(B, td, pdir, ui_slug(td, n["uiType"]), n["uiType"], "../", "<div class='via' title='%s:%d'>%s</div>" % (
                E(n["file"]), n["line"], E(n["via"])), i) for i, n in enumerate(nxt)))
    if used:
        body += "<h2>이 화면의 템플릿 <span class='n'>%d종 · 인스턴스 %d</span></h2><div class='cards sm'>%s</div>" % (
            len(used), sum(used.values()), "".join(tcard(B, td, pdir, td.t[s], "../", i, "<span class='tag y'>×%d</span>" % n)
                                                  for i, (s, n) in enumerate(used.most_common()) if s in td.t))
    return body


# ---------------------------------------------------------------- 템플릿
def build_templates(B, d, td, out):
    E = B.E
    temps = [td.t[s] for s in td.idx["templates"]]
    temps.sort(key=lambda t: (-t["usageTotal"], t["name"]))
    cards = "".join(tcard(B, td, out, t, "", i) for i, t in enumerate(temps))
    rows = []
    for t in temps:
        ov = t.get("overrides") or {}
        src, why = template_thumb(B, td, out, t)
        rows.append("<tr data-name='%s' data-tier='%s' data-folder='%s' data-kind='%s' data-usage='%d' data-screens='%d'><td>%s</td>"
                    "<td><a href='templates/%s.html'>%s</a></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%d</td><td>%d</td>"
                    "<td>%d</td><td>%s</td><td>%d</td></tr>" % (
                        E(t["name"].lower()), t["tier"], E(folder(t["path"]).lower()), E(t["kind"]), t["usageTotal"], len(t["screens"]),
                        "<img loading='lazy' src='%s' alt='' style='height:40px;max-width:90px;object-fit:contain'>" % src if src else
                        "<span class='mut'>%s</span>" % E(why), E(t["slug"]), E(t["name"]), E(C.KIND_LABELS.get(t["kind"], t["kind"])),
                        t["tier"], t["rule"], E(folder(t["path"])), t["usageTotal"], len(t["screens"]), len(t["scenes"]),
                        "%.0f%%" % (100 * ov["modifiedRate"]) if ov.get("instances") else "-", len(t.get("lookalikes") or [])))

    def sel(name, label, vals):
        return "<select data-f='%s' title='%s'><option value=''>%s: 전체</option>%s</select>" % (
            name, label, label, "".join("<option value='%s'>%s</option>" % (E(v.lower()), E(v)) for v in sorted(vals)))
    c = td.idx["counts"]
    body = kpis([("템플릿", c.get("templates", 0), True), ("atom", c.get("atom", 0), False), ("composite", c.get("composite", 0), False),
                 ("공통 폴더(규칙 A)", c.get("ruleA", 0), False), ("접미사+2곳(규칙 B)", c.get("ruleB", 0), False),
                 ("화면", c.get("screens", 0), False), ("미사용 프리팹", c.get("unused", 0), False)])
    body += ("<div class='filters'><input type='search' data-f='q' placeholder='템플릿 이름 찾기'>%s%s%s"
             "<select data-f='used' title='사용 수'><option value=''>사용: 전체</option><option value='10'>10곳 이상</option>"
             "<option value='2'>2곳 이상</option><option value='0'>0곳</option></select>"
             "<select data-f='sort' title='정렬'><option value='usage'>정렬: 사용 수</option><option value='screens'>정렬: 화면 수</option>"
             "<option value='name'>정렬: 이름</option></select><span class='grow'></span><span class='mut'>표시 <b id='cnt'></b></span>"
             "<div class='seg'><button data-view='cards' class='on'>카드</button><button data-view='table'>표</button></div></div>") % (
        sel("tier", "위계", {t["tier"] for t in temps}), sel("folder", "폴더", {folder(t["path"]) for t in temps}),
        sel("kind", "종류", {t["kind"] for t in temps}))
    body += "<div class='cards' data-gallery>%s</div>" % (cards or "<div class='empty'>아직 없음</div>")
    body += ("<table id='tview' class='hidden'><tr><th>썸네일</th><th>템플릿</th><th>종류</th><th>위계</th><th>규칙</th><th>폴더</th>"
             "<th>사용</th><th>화면</th><th>씬</th><th>변형 사용</th><th>유사품</th></tr>%s</table>") % "".join(rows)
    body += "<p class='mut'>규칙: %s · 카드 오른쪽 위 숫자 = 사용 수, 막대 = 변형 사용(노랑)·스타일 변형(파랑) 비율</p>" % E(
        " / ".join("%s: %s" % kv for kv in td.idx["rules"].items()))
    B.write(out, "templates.html", B.page("템플릿", body, nav="templates.html", wide=True))
    pdir = os.path.join(out, "templates")
    for t in temps:
        B.write(out, "templates/%s.html" % t["slug"], B.page(t["name"], template_body(B, d, td, t, pdir), depth=1, wide=True,
                                                             crumbs=[("템플릿", "../templates.html")], nav="templates.html"))


def structure(t):
    import parse_prefab
    try:
        nodes, _u = parse_prefab.build_nodes(t["path"], "t")
    except Exception as e:  # noqa: BLE001 — 깨진 프리팹은 사유만 표시
        return [], "파싱 실패: %s" % e
    return nodes, None


def template_body(B, d, td, t, pdir):
    E = B.E
    ov = t.get("overrides") or {}
    lk = t.get("lookalikes") or []
    body = "<div class='facts'><span class='tag y'>%s</span><span class='tag'>%s</span><span class='tag'>규칙 %s</span><span class='tag'>%s</span>%s</div>" % (
        t["tier"], E(C.KIND_LABELS.get(t["kind"], t["kind"])), t["rule"], E(folder(t["path"])),
        "<span class='tag c'>%s</span>" % E(t["address"]) if t["address"] else "")
    body += "<div class='mono mut'>%s · GUID %s</div>" % (E(t["path"]), E(t["guid"] or "-"))
    body += kpis([("사용", t["usageTotal"], True), ("화면", len(t["screens"]), False), ("씬", len(t["scenes"]), False),
                  ("변형 사용", "%.0f%%" % (100 * ov["modifiedRate"]) if ov.get("instances") else "-", False), ("유사품", len(lk), False)])
    lay = td.layout("template", t["slug"])
    if lay:
        body += viewer(B, td, pdir, lay, "../")
    else:
        src, why = template_thumb(B, td, pdir, t)
        body += "<div class='note'>배치 맵 없음 — %s</div>%s" % (E(why or "렌더 실패(루트가 RectTransform 아님)"),
                                                            "<img class='chk' style='max-width:100%%' src='%s' alt=''>" % src if src else "")
    if t["contains"]:
        body += "<h2>포함한 템플릿 <span class='n'>%d</span></h2><div class='cards sm'>%s</div>" % (
            len(t["contains"]), "".join(tcard(B, td, pdir, td.t[s], "../", i) for i, s in enumerate(t["contains"]) if s in td.t))
    parents = sorted({td.by_path[u["user"]]["slug"] for u in t["users"] if u["user"] in td.by_path})
    if parents:
        body += "<h2>이 템플릿을 포함한 템플릿 <span class='n'>%d</span></h2><div class='cards sm'>%s</div>" % (
            len(parents), "".join(tcard(B, td, pdir, td.t[s], "../", i) for i, s in enumerate(parents)))
    if t["screens"]:
        path_of = {v: k for k, v in td.screen_slug.items()}
        body += "<h2>쓰는 화면 <span class='n'>%d (간접 포함)</span></h2><div class='cards sm'>%s</div>%s" % (
            len(t["screens"]), "".join(scard(B, td, pdir, s, TS.stem(path_of.get(s, s)), "../", "", i)
                                       for i, s in enumerate(t["screens"][:LIST_CAP])),
            "<p class='mut'>외 %d개 — 아래 사용처 표</p>" % (len(t["screens"]) - LIST_CAP) if len(t["screens"]) > LIST_CAP else "")
    if t["scenes"]:
        body += "<h2>씬 <span class='n'>%d</span></h2><div class='chips'>%s</div>" % (len(t["scenes"]), "".join(
            "<a href='../scenes/%s.html'>%s</a>" % (E(C.slugify(s)), E(s)) for s in t["scenes"]))
    if ov.get("instances"):
        body += overrides_section(E, ov)
    if lk:
        body += lookalikes_section(B, td, lk)
    if t["variants"]:
        body += "<h2>Variant</h2><div class='chips'>%s</div>" % "".join(user_link(B, d, td, v) for v in t["variants"])
    by_kind = collections.defaultdict(list)
    for u in t["users"]:
        by_kind[u["kind"]].append(u)
    body += "<h2>사용처 상세 <span class='n'>%d</span></h2>" % t["usageTotal"]
    for k, us in sorted(by_kind.items()):
        body += "<details><summary>%s (%d)</summary><table><tr><th>사용자</th><th>경로·위치</th></tr>%s</table></details>" % (
            E(k), len(us), "".join("<tr><td>%s</td><td class='wrap'>%s</td></tr>" % (user_link(B, d, td, u["user"]), E(u["path"]))
                                   for u in us[:200]))
    nodes, err = structure(t)
    body += tokens_section(B, d, nodes)
    if err:
        body += "<p class='warn'>%s</p>" % E(err)
    return body


CAT_COLORS = {"size": "#8d8878", "active": "#5ea8ff", "text": "#e7a6ff", "sprite": "#ffd21f", "color": "#ff8a3d",
              "position": "#4fe3a7", "other": "#55524a"}


def overrides_section(E, ov):
    n = ov["instances"]
    tot = sum(ov["byCategory"].values()) or 1
    cat = "".join("<i style='width:%.1f%%;background:%s' title='%s %d'></i>" % (100.0 * v / tot, CAT_COLORS.get(k, "#777"), E(k), v)
                  for k, v in sorted(ov["byCategory"].items(), key=lambda kv: -kv[1]))
    leg = "".join("<span><i style='background:%s'></i>%s %d</span>" % (CAT_COLORS.get(k, "#777"), E(k), v)
                  for k, v in sorted(ov["byCategory"].items(), key=lambda kv: -kv[1]))
    use = ("<i style='width:%.1f%%;background:var(--panel2)' title='그대로 %d'></i><i style='width:%.1f%%;background:var(--acc)' title='변형 %d'></i>"
           "<i style='width:%.1f%%;background:var(--cyan)' title='스타일 변형 %d'></i>") % (
        100.0 * ov["asIs"] / n, ov["asIs"], 100.0 * (ov["modified"] - ov.get("styled", 0)) / n, ov["modified"] - ov.get("styled", 0),
        100.0 * ov.get("styled", 0) / n, ov.get("styled", 0))
    props = "".join("<div class='mono'><span style='display:inline-block;width:%dpx;height:6px;background:var(--acc);margin-right:6px'></span>%s %d</div>" % (
        max(2, round(120.0 * c / n)), E(p), c) for p, c in ov["topProps"])
    return ("<h2>오버라이드 <span class='n'>인스턴스 %d</span></h2><div class='ovr'>"
            "<div class='card'><h3>인스턴스</h3><div class='stack'>%s</div><div class='legend2'><span><i style='background:var(--panel2)'></i>그대로 %d</span>"
            "<span><i style='background:var(--acc)'></i>변형 %d</span><span><i style='background:var(--cyan)'></i>스프라이트·색 변형 %d</span>"
            "<span>위치 이동 %d</span></div></div>"
            "<div class='card'><h3>바뀐 범주</h3><div class='stack'>%s</div><div class='legend2'>%s</div></div>"
            "<div class='card'><h3>자주 바뀐 속성</h3>%s</div></div>"
            "<p class='mut'>원본과 값이 같은 수정값(Unity 가 인스턴스 루트에 늘 기록하는 앵커·크기)은 뺐다.</p>") % (
        n, use, ov["asIs"], ov["modified"] - ov.get("styled", 0), ov.get("styled", 0), ov["placed"], cat, leg, props)


def lookalikes_section(B, td, lk):
    E = B.E
    cnt = collections.Counter(x["match"] for x in lk)
    badges = "".join("<div class='b'><b style='color:%s'>%d</b><span>%s</span></div>" % (col, cnt.get(m, 0), m)
                     for m, col in (("exact", "var(--bad)"), ("near", "var(--warn)"), ("borderline", "var(--mut)")))
    rows = "".join("<tr><td><span class='tag %s'>%s</span></td><td>%.2f</td><td>%s</td><td class='wrap mono'>%s</td></tr>" % (
        "r" if x["match"] == "exact" else "", E(x["match"]), x["score"], screen_ref(B, td, x["screen"]), E(x["node"].split("#", 1)[-1]))
        for x in lk)
    return ("<h2>복붙 유사품 <span class='n'>%d — 템플릿을 풀어서 복사한 것으로 보이는 하위 트리</span></h2><div class='badges'>%s</div>"
            "<details><summary>목록</summary><table><tr><th>일치</th><th>점수</th><th>화면</th><th>노드</th></tr>%s</table></details>") % (
        len(lk), badges, rows)


def screen_ref(B, td, slug):
    if slug in td.layout_slugs["screen"]:
        return "<a href='../map/%s.html'>%s</a>" % (B.E(slug), B.E(slug))
    return "<a href='../screens/%s.html'>%s</a>" % (B.E(slug), B.E(slug))


def tokens_section(B, d, nodes):
    color = (d.tokens.get("color") or {}).get("mapping", {})
    typ = (d.tokens.get("type") or {}).get("mapping", {})
    used = collections.Counter()
    for n in nodes:
        for c in ((n.get("graphic") or {}).get("color"), (n.get("text") or {}).get("color")):
            if c and c in color:
                used[color[c]] += 1
        tx = n.get("text")
        if tx:
            key = "%s|%g" % (os.path.basename(tx["font"] or "?"), round(tx["size"]))
            if key in typ:
                used[typ[key]] += 1
    if not used:
        return ""
    return "<h2>사용 토큰</h2><p>%s <a href='../tokens.html'>토큰 표</a></p>" % " ".join(
        "%s×%d" % (B.cp(k), n) for k, n in used.most_common(30))


# ---------------------------------------------------------------- 씬·미사용 (T7 그대로)
def build_scenes(B, d, td, out):
    E = B.E
    rows = []
    for s in td.reach["scenes"]:
        direct = sorted({e["template"] for e in td.edges if e["user"] == s["path"] and e["template"] in td.by_path})
        allt = sorted(x for x in td.descendants(s["path"]) if x in td.by_path)
        canv = td.scene_ui.get(s["name"], {}).get("canvases", [])
        rows.append("<tr><td><a href='scenes/%s.html'>%s</a></td><td>%d</td><td>%d</td><td>%d</td><td class='wrap'>%s</td></tr>" % (
            E(C.slugify(s["name"])), E(s["name"]), len(direct), len(allt), len(canv),
            E(", ".join(sorted({x["kind"] for x in s["sources"]})))))
    st = td.reach.get("stats", {})
    body = kpis([("도달 씬", len(td.reach["scenes"]), True), ("미참조", len(td.reach["unreferenced"]), False),
                 ("없는 씬 참조", len(td.reach["missing"]), False)])
    body += "<p class='mut'>로비는 400_Town 위의 UI다.</p>"
    body += ("<table><tr><th>씬</th><th>직접 템플릿</th><th>템플릿(간접 포함)</th><th>씬 Canvas</th><th>출처</th></tr>%s</table>" %
             ("".join(rows) or "<tr><td colspan=5 class='mut'>아직 없음</td></tr>"))
    body += "<h2>미참조 씬 (범위 제외)</h2><ul>%s</ul>" % ("".join("<li>%s <span class='mut'>%s</span></li>" % (
        E(x["name"]), E(x["path"])) for x in td.reach["unreferenced"]) or "<li class='mut'>없음</li>")
    body += "<h2>데이터가 가리키는데 파일이 없는 씬</h2><ul>%s</ul>" % ("".join("<li>%s <span class='mut'>%s</span></li>" % (
        E(x["name"]), E(", ".join("%s(%s)" % (y["key"], y["file"].rsplit("/", 1)[-1]) for y in x["sources"][:4]))) for x in td.reach["missing"])
        or "<li class='mut'>없음</li>")
    if st:
        body += "<p class='mut'>%s</p>" % E(" · ".join("%s %s" % kv for kv in st.items() if not isinstance(kv[1], (dict, list))))
    B.write(out, "scenes.html", B.page("씬", body, nav="scenes.html"))
    for s in td.reach["scenes"]:
        B.write(out, "scenes/%s.html" % C.slugify(s["name"]), B.page(s["name"], scene_body(B, d, td, s, os.path.join(out, "scenes")), depth=1,
                                                                     crumbs=[("씬", "../scenes.html")], nav="scenes.html"))


def scene_body(B, d, td, s, pdir):
    E = B.E
    body = "<p class='mono mut'>%s</p><h2>출처</h2><ul>%s</ul>" % (E(s["path"]), "".join(
        "<li>%s · %s <span class='mut'>%s</span></li>" % (E(x["kind"]), E(x["key"]), E(x["file"])) for x in s["sources"][:30]))
    direct = [e for e in td.edges if e["user"] == s["path"]]
    body += "<h2>씬에 직접 둔 UI 프리팹 <span class='n'>%d</span></h2><table><tr><th>프리팹</th><th>씬 안 경로</th></tr>%s</table>" % (len(direct), "".join(
        "<tr><td>%s</td><td class='wrap'>%s</td></tr>" % (
            user_link(B, d, td, e["template"]) if e["template"] in td.by_path else screen_link(B, d, e["template"] or "?"),
            E(e["path"])) for e in direct) or "<tr><td colspan=2 class='mut'>없음</td></tr>")
    allt = sorted(td.by_path[x]["slug"] for x in td.descendants(s["path"]) if x in td.by_path)
    if allt:
        body += "<h2>구성 템플릿 <span class='n'>%d (간접 포함)</span></h2><div class='cards sm'>%s</div>" % (
            len(allt), "".join(tcard(B, td, pdir, td.t[x], "../", i) for i, x in enumerate(allt)))
    for c in td.scene_ui.get(s["name"], {}).get("canvases", []):
        lines = []
        for n in c["nodes"][:300]:
            dep = n["path"].count("/")
            lines.append("%s%s%s%s" % ("  " * dep, n["name"], "  [%s]" % ", ".join(
                x for x in n["components"] if x not in ("RectTransform", "CanvasRenderer"))[:80] if n["components"] else "",
                "  ← " + n["nested"].rsplit("/", 1)[-1] if n["nested"] else ""))
        body += "<h2>씬 UI: %s <span class='n'>%d노드, 프리팹 아님</span></h2><div class='tree'>%s</div>" % (E(c["root"]), len(c["nodes"]), E("\n".join(lines)))
    return body


def build_unused(B, d, td, out):
    E = B.E
    rows = "".join("<tr><td>%s</td><td>%s</td><td class='wrap'>%s</td></tr>" % (E(u["name"]), E(u["suffix"] or "-"), E(u["path"]))
                   for u in td.idx["unused"])
    body = kpis([("사용처 0", len(td.idx["unused"]), True), ("제외", len(td.idx["excluded"]), False)])
    body += ("<div class='note'>사용처(중첩·Variant·씬·코드)가 0인 프리팹. 문자열을 조합해 여는 동적 로드와 다른 SO 의 참조는 잡지 못하므로 "
             "확정 전에 사람이 확인한다.</div><table><tr><th>이름</th><th>접미사</th><th>경로</th></tr>%s</table>") % (
        rows or "<tr><td colspan=3 class='mut'>없음</td></tr>")
    body += "<h2>제외 <span class='n'>%d</span></h2><ul>%s</ul>" % (len(td.idx["excluded"]), "".join(
        "<li>%s <span class='mut'>%s</span></li>" % (E(x["path"]), E(x["reason"])) for x in td.idx["excluded"]) or "<li class='mut'>없음</li>")
    B.write(out, "unused.html", B.page("미사용 프리팹", body, nav="unused.html"))


FEEDBACK_ASSETS = ["review.js", "review.css", "badges.js", "badges.css"]  # 손으로 관리하는 원본(catalog_assets.py 가 안 씀)


def build_review(B, d, td, out):
    """리뷰 뷰어(catalog_review.py). 출력이 실제 catalog/ 가 아니면(selftest 등) 피드백 에셋 원본을 옆에 복사한다.
    하단 도크 라이브러리(CONTRACT 7.4): 실제 catalog/ 면 index·<slug>.js 를 다시 만든다(헤드리스 불필요, keys·크롭은
    산출물이 바뀔 때 `catalog_library.py --build` 로 따로). 다른 출력이면 catalog/library 를 옆에 복사한다."""
    src = os.path.join(C.SCRIPTS, os.pardir, "catalog", "assets")
    dst = os.path.join(out, "assets")
    if os.path.normcase(os.path.realpath(src)) != os.path.normcase(os.path.realpath(dst)):
        os.makedirs(dst, exist_ok=True)
        for name in FEEDBACK_ASSETS:
            if os.path.exists(os.path.join(src, name)):
                shutil.copyfile(os.path.join(src, name), os.path.join(dst, name))
        lib = os.path.join(src, os.pardir, "library")
        if os.path.isdir(lib):
            shutil.copytree(lib, os.path.join(out, "library"), dirs_exist_ok=True)
    elif td.present:
        import contextlib
        import io
        import catalog_library as CL
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = CL.cmd_build(no_keys=True)
        warn = [ln for ln in buf.getvalue().splitlines() if rc or "건너뜀" in ln or "초과" in ln or "경고" in ln]
        print("\n".join(["라이브러리(catalog/library) index·slug js 재생성 rc=%s — keys·크롭은 catalog_library.py --build" % rc] + warn))
    CR.build_review(B, out)


BUILDERS = {"app-flow": build_app_flow, "map": build_map, "templates": build_templates, "scenes": build_scenes, "unused": build_unused,
            "review": build_review}


def screen_section(B, td, prefab):
    """screens/<화면>.html(노드 카탈로그) 보강: 배치 맵 링크 + 그 화면을 이루는 템플릿 트리(직접 → 간접)."""
    if not td.present:
        return ""
    E = B.E
    lines, seen = [], set()

    def walk(path, depth):
        for c in sorted(td.fwd.get(path, ()), key=lambda x: TS.stem(x)):
            t = td.by_path.get(c)
            if t:
                lines.append("%s<a href='../templates/%s.html'>%s</a> <span class='mut'>%s · %s</span>" % (
                    "&nbsp;&nbsp;" * depth, E(t["slug"]), E(t["name"]), E(t["kind"]), t["tier"]))
            if c not in seen and depth < 6:
                seen.add(c)
                walk(c, depth + (1 if t else 0))
    walk(prefab, 0)
    slug = td.screen_slug.get(prefab)
    link = "<a class='banner' href='../map/%s.html'><b>배치 맵</b><span>Unity 렌더 위에서 템플릿 위치 보기 ›</span></a>" % E(slug) \
        if slug in td.layout_slugs["screen"] else ""
    return "%s<h2>구성 템플릿</h2>%s" % (link, "<div>%s</div>" % "<br>".join(lines) if lines else "<p class='mut'>템플릿 사용 없음</p>")
