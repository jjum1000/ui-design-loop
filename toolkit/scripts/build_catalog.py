"""A5 카탈로그 빌드: data/ 와 decisions.json 으로 정적 HTML 을 만든다 (catalog/ 는 직접 편집 금지).

사용:
  python scripts/build_catalog.py --page <index|tokens|components|screens|refactor-map|decisions>
      그 페이지(components·screens 는 하위 페이지 포함)를 catalog/ 아래 .tmp 로 쓴다.
      이어서 python scripts/validate.py --rename catalog
  python scripts/build_catalog.py --all          6개 페이지 전부 .tmp 로 쓰기 (+ data/template-index.json 이 있으면 템플릿 페이지)
  python scripts/build_catalog.py --templates    템플릿 카탈로그 페이지(templates·scenes·unused)만 .tmp 로 쓰기
  python scripts/build_catalog.py --check        깨진 링크·이미지 검사 (0개여야 A5 완료)
  python scripts/build_catalog.py --samples <종류> [--n 5]   A6 대조용 표본 (노드 id·출처·값·결정)
  python scripts/build_catalog.py --selftest
"""
import argparse
import html
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog_assets as CA  # noqa: E402
import catalog_templates as CT  # noqa: E402
import common as C  # noqa: E402

E = html.escape
NAV = [("index.html", "현황"), ("tokens.html", "토큰"), ("components.html", "컴포넌트"), ("screens.html", "노드 화면"),
       ("refactor-map.html", "리팩터 맵"), ("decisions.html", "결정")]
IMG_EXT = (".png", ".jpg", ".jpeg")
TEMPLATE_NAV = []  # 템플릿 카탈로그 데이터가 있을 때 build() 가 CT.NAV 로 채운다


# ---------------------------------------------------------------- 데이터
class Data:
    def __init__(self):
        self.inv = C.all_inventory()
        self.cls = C.all_classified()
        self.groups = {}
        for f in C.iter_json(C.p("data", "groups")):
            g = C.load_json(f)
            self.groups[g["kind"]] = g["groups"]
        self.metrics = {k: C.load_json(C.p("data", "metrics", k + ".json")) for k in self.groups}
        self.registry = {k: C.load_json(C.p("data", "registry", k + ".json")) for k in self.groups}
        self.tokens = {c: C.load_json(C.p("data", "tokens", c + ".json")) for c in C.TOKEN_CATEGORIES}
        self.treg = {c: C.load_json(C.p("data", "token-registry", c + ".json")) for c in C.TOKEN_CATEGORIES}
        self.decisions = C.load_json(C.p("decisions.json"), []) or []
        self.questions = C.load_json(C.p("questions.json"), []) or []
        self.manifest = C.load_json(C.p("manifest.json"))
        self.batches = {}
        for f in C.iter_json(C.p("batches")):
            b = C.load_json(f)
            self.batches[b["batch"]] = b
        self.last = {}
        for d in self.decisions:
            self.last[d["target"]] = d
        self.node_group = {}
        for kind, gs in self.groups.items():
            for g in gs:
                for mbr in g["members"]:
                    self.node_group[mbr] = g["id"]
        self.group_by_id = {g["id"]: (k, g) for k, gs in self.groups.items() for g in gs}

    def status(self, xid, default):
        d = self.last.get(xid)
        return d["status"] if d and d["status"] in ("표준", "폐기", "예외") else default


def rel_link(page_dir, target_abs):
    try:
        return os.path.relpath(target_abs, page_dir).replace("\\", "/")
    except ValueError:  # 드라이브가 다르면 절대 경로
        return "file:///" + os.path.abspath(target_abs).replace("\\", "/")


def page(title, body, depth=0, crumbs=None, nav=None, wide=False):
    """공통 셸: 상단 내비(탐색기 | 노드 카탈로그) · 탐색 경로 · 라이트/다크. 스타일·스크립트는 assets/ (catalog_assets.py)."""
    up = "../" * depth

    def link(h, t):
        return '<a href="%s%s"%s><span>%s</span></a>' % (up, h, ' class="on"' if h == nav else "", E(t))
    nav_html = "".join(link(h, t) for h, t in TEMPLATE_NAV) + ('<span class="sep"></span>' if TEMPLATE_NAV else "") + \
        "".join(link(h, t).replace("<a ", '<a class="sub" ', 1) if h != nav else link(h, t) for h, t in NAV)
    home = "app-flow.html" if TEMPLATE_NAV else "index.html"
    base = json.dumps([[t, h] for t, h in (crumbs or [])], ensure_ascii=False)
    return ('<!doctype html>\n<html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>%s · UI 탐색기</title>'
            '<link rel="stylesheet" href="%sassets/explorer.css"><script src="%sassets/explorer.js"></script></head>'
            '<body><header class="top"><a class="brand" href="%s%s"><b><span>UI</span></b>AUDIT</a><nav class="nav">%s</nav>'
            '<button class="themebtn" type="button" title="라이트/다크">◐ 테마</button></header>'
            '<div class="crumbs" data-title="%s" data-base="%s"></div><main%s><h1>%s</h1>%s</main><div class="tip"></div></body></html>\n') % (
        E(title), up, up, up, home, nav_html, E(title), E(base), ' class="wide"' if wide else "", E(title), body)


def cp(xid):
    return '<button class="cp" data-id="%s" title="ID 복사">%s</button>' % (E(xid), E(xid))


def tag(st):
    return '<span class="tag %s">%s</span>' % (E(st), E(st))


def swatch(color):
    if not color or not re.match(r"^#[0-9A-F]{8}$", color):
        return E(str(color))
    r, g, b, a = (int(color[i:i + 2], 16) for i in (1, 3, 5, 7))
    return '<span class="sw" style="background:rgba(%d,%d,%d,%.2f)"></span>%s' % (r, g, b, a / 255, E(color))


def sprite_img(page_dir, node):
    sp = ((node or {}).get("graphic") or {}).get("sprite") or {}
    path = sp.get("path") or ""
    if not path.lower().endswith(IMG_EXT) or sp.get("fileID") != 21300000:
        return ""
    full = os.path.join(C.unity_root(), path)
    if not os.path.exists(full):
        return ""
    return '<img loading="lazy" src="%s" alt="%s">' % (E(rel_link(page_dir, full)), E(sp.get("name") or ""))


def source_prefab(node_id, d):
    n = d.inv.get(node_id)
    if n and n[2].get("nested"):
        return n[2]["nested"]["prefab"]
    return node_id.split("#", 1)[0]


# ---------------------------------------------------------------- 페이지
def build_index(d, out):
    rows = []
    for kind in C.KINDS:
        m = d.metrics.get(kind)
        if not m:
            continue
        rows.append("<tr><td><a href='components/%s.html'>%s</a> <span class='mut'>%s</span></td><td>%d</td><td>%d</td>"
                    "<td>%d</td><td>%d</td><td>%d</td><td>%.0f%%</td><td>%d</td></tr>" % (
                        kind, E(C.KIND_LABELS[kind]), kind, m["groupCount"], m["nodeCount"], m["screenCount"],
                        m["uniqueColors"], m["uniqueSizes"], 100 * (m.get("candidateShare") or 0), m.get("smallTouchTargets", 0)))
    colors = {(n[2].get("graphic") or {}).get("color") for nid, n in d.inv.items() if nid in d.node_group} - {None}
    colors |= {(n[2].get("text") or {}).get("color") for nid, n in d.inv.items() if nid in d.node_group} - {None}
    sizes = sorted({round(n[2]["text"]["size"]) for n in d.inv.values() if n[2].get("text")})
    fonts = sorted({os.path.basename(n[2]["text"]["font"] or "?") for n in d.inv.values() if n[2].get("text")})
    body = ("<a class='banner' href='app-flow.html'><b>탐색기 홈</b><span>앱 아이콘 → 화면 흐름 → 실제 배치 맵 → 템플릿 ›</span></a>"
            if TEMPLATE_NAV else "")
    body += "<h2>파편화 지표</h2><p>고유 색 %d개 · 폰트 크기 %d종 (가장 작은 크기 %s) · 폰트 에셋 %d종 · 노드 %d개 · 그룹 %d개</p>" % (
        len(colors), len(sizes), sizes[0] if sizes else "-", len(fonts), len(d.inv), len(d.group_by_id))
    body += ("<table><tr><th>종류</th><th>변형(그룹)</th><th>노드</th><th>화면</th><th>고유 색</th><th>크기 단계</th>"
             "<th>후보 비율</th><th>터치 &lt;100px</th></tr>%s</table>") % "".join(rows)
    body += "<h2>배치 진행</h2><table><tr><th>배치</th>%s</tr>" % "".join("<th>%s</th>" % s for s in C.SEQUENCE)
    m = d.manifest or {"batchOrder": [], "batches": {}}
    for b in m["batchOrder"]:
        B = m["batches"].get(b)
        if not B:
            body += "<tr><td>%s</td>%s</tr>" % (b, "<td class='mut'>-</td>" * len(C.SEQUENCE))
            continue
        cells = "".join("<td>%s</td>" % E(B["gates"][s] if s in C.GATES else B["steps"][s]["status"]) for s in C.SEQUENCE)
        body += "<tr><td>%s</td>%s</tr>" % (b, cells)
    body += "</table>"
    warn = []
    for t, dec in d.last.items():
        for kind, reg in list(d.registry.items()) + list(d.treg.items()):
            if reg and (t in reg.get("aliases", {}) or t in reg.get("retired", {})):
                now = reg["aliases"].get(t) or ", ".join(reg["retired"][t]["successors"]) or "없음"
                warn.append("<li class='warn'>%s 결정 %s 의 대상 %s 가 바뀜 → %s</li>" % (dec["id"], dec["status"], E(t), E(now)))
    if warn:
        body += "<h2>경고: retired·aliases 로 바뀐 결정</h2><ul>%s</ul>" % "".join(warn)
    openq = [q for q in d.questions if q["status"] == "open"]
    body += "<h2>미결 질문 %d건</h2><table><tr><th>ID</th><th>관문</th><th>배치</th><th>질문</th><th>보기</th></tr>" % len(openq)
    for q in openq[:100]:
        body += "<tr><td>%s</td><td>%s</td><td>%s</td><td class='wrap'>%s</td><td class='wrap'>%s</td></tr>" % (
            q["id"], q["gate"], q["batch"], E(q["text"]), E(" | ".join(o["label"] for o in q["options"])))
    body += "</table>"
    write(out, "index.html", page("UI 현황 카탈로그", body))


def build_tokens(d, out):
    body = ""
    for c in C.TOKEN_CATEGORIES:
        t = d.tokens.get(c)
        body += "<h2>%s</h2>" % E(c)
        if not t:
            body += "<p class='mut'>아직 없음</p>"
            continue
        body += "<table><tr><th>토큰</th><th>상태</th><th>값</th><th>계열</th><th>사용</th><th>원래 값 → 토큰</th></tr>"
        for tok in t["tokens"]:
            val = swatch(tok["valueKey"]) if c == "color" else E(tok["valueKey"])
            body += "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%d</td><td class='wrap'>%s</td></tr>" % (
                cp(tok["id"]), tag(d.status(tok["id"], tok["status"])), val, E(tok["family"]), tok["count"],
                E(", ".join(tok["members"][:12]) + (" …" if len(tok["members"]) > 12 else "")))
        body += "</table>"
        if t["exceptions"]:
            body += "<p>예외: %s</p>" % E(", ".join("%s(%s)" % (e["value"], e["reason"]) for e in t["exceptions"]))
    write(out, "tokens.html", page("토큰 초안", body))


def build_components(d, out):
    links = "".join("<li><a href='components/%s.html'>%s</a> (%s) — 그룹 %d</li>" % (
        k, E(C.KIND_LABELS[k]), k, len(d.groups[k])) for k in C.KINDS if k in d.groups)
    write(out, "components.html", page("컴포넌트", "<ul>%s</ul>" % (links or "<li class='mut'>아직 없음</li>")))
    pdir = os.path.join(out, "components")
    for kind, gs in d.groups.items():
        std = next((g for g in gs if d.status(g["id"], "") == "표준"), None) or next((g for g in gs if g["status"] == "후보"), None)
        cards = []
        for g in gs:
            first = d.inv.get(g["members"][0], (None, None, {}))[2]
            states = {}
            for mbr in g["members"]:
                for s in ((d.inv.get(mbr, (0, 0, {}))[2].get("selectable") or {}).get("states") or []):
                    states[s] = states.get(s, 0) + 1
            diff = ""
            if std and std["id"] != g["id"]:
                diff = ", ".join("%s: %s" % (k, g["signature"].get(k)) for k in sorted(set(g["signature"]) | set(std["signature"]))
                                 if g["signature"].get(k) != std["signature"].get(k))
            prefabs = sorted({source_prefab(mbr, d) for mbr in g["members"]})
            sig = "".join("<div><span class='mut'>%s</span> %s</div>" % (E(k), swatch(v) if k == "color" else E(str(v)))
                          for k, v in g["signature"].items())
            cards.append("<div class='card'>%s %s<div class='mut'>노드 %d · 화면 %d</div>%s%s"
                         "<div>상태: %s</div>%s<div class='mut'>사용 화면: %s</div><div class='mut'>프리팹: %s</div></div>" % (
                             cp(g["id"]), tag(d.status(g["id"], g["status"])), g["count"], len(g["screens"]),
                             sprite_img(pdir, first), sig,
                             E(", ".join("%s %d" % (s, n) for s, n in states.items()) or "-"),
                             "<div>표준 후보와 차이: %s</div>" % E(diff) if diff else "",
                             ", ".join("<a href='../screens/%s.html'>%s</a>" % (E(s), E(s)) for s in g["screens"][:8]),
                             E(", ".join(p.rsplit("/", 1)[-1] for p in prefabs[:5]) + (" …" if len(prefabs) > 5 else ""))))
        body = "<p>그룹 %d개. 표준 후보: %s</p><div class='grid'>%s</div>" % (len(gs), cp(std["id"]) if std else "-", "".join(cards))
        write(out, "components/%s.html" % kind, page("%s (%s)" % (C.KIND_LABELS[kind], kind), body, depth=1))


def build_screens(d, out):
    proj = C.project()
    items = [(b, s) for b in sorted(d.batches) for s in d.batches[b]["screens"]]
    links = "".join("<li><a href='screens/%s.html'>%s</a> <span class='mut'>%s · %s</span></li>" % (
        E(s["slug"]), E(s["name"]), b, E(s["prefab"])) for b, s in items)
    write(out, "screens.html", page("화면", "<ul>%s</ul>" % (links or "<li class='mut'>아직 없음</li>")))
    pdir = os.path.join(out, "screens")
    touch = proj.get("touch_min_px", 100)
    for b, s in items:
        nodes = [n for nid, n in d.inv.items() if n[1] == s["slug"] and n[0] == b]
        body = "<p class='mut'>%s · 배치 %s</p>" % (E(s["prefab"]), b)
        shots = []
        for r in proj["screenshot_ratios"]:
            f = C.p("input", "screenshots", b, "%s_%s.png" % (s["slug"], r))
            if os.path.exists(f):
                shots.append('<img src="%s" alt="%s">' % (E(rel_link(pdir, f)), r))
        missing = [r for r in proj["screenshot_ratios"] if not os.path.exists(C.p("input", "screenshots", b, "%s_%s.png" % (s["slug"], r)))]
        body += "<h2>스크린샷</h2><div class='shots'>%s</div>%s" % ("".join(shots) or "<span class='mut'>없음</span>",
                                                                   "<p class='warn'>누락 비율: %s</p>" % ", ".join(missing) if missing else "")
        kinds = {}
        grouped = std = 0
        for _b, _s, n in nodes:
            c = d.cls.get(n["id"])
            if not c or c[2].get("structural"):
                continue
            k = c[2]["kind"]
            kinds.setdefault(k, set())
            gid = d.node_group.get(n["id"])
            if gid:
                kinds[k].add(gid)
                grouped += 1
                std += d.status(gid, "") == "표준"
        body += "<h2>사용 컴포넌트</h2><p>표준 사용 비율 %s (%d/%d)</p><table><tr><th>종류</th><th>그룹</th></tr>%s</table>" % (
            "%.0f%%" % (100.0 * std / grouped) if grouped else "-", std, grouped,
            "".join("<tr><td><a href='../components/%s.html'>%s</a></td><td class='wrap'>%s</td></tr>" % (
                k, E(C.KIND_LABELS.get(k, k)), " ".join(cp(g) for g in sorted(v))) for k, v in sorted(kinds.items())))
        ns = [n for _b, _s, n in nodes]
        canv = ["%s: %s %s match %s" % (n["path"], n["canvas"].get("scaler"), n["canvas"].get("referenceResolution"),
                                        n["canvas"].get("match")) for n in ns if n.get("canvas")]
        sels = [n for n in ns if n.get("selectable")]
        hover = sum(1 for n in sels if "Hover" in n["selectable"]["states"])
        focus = sum(1 for n in sels if "Focused" in n["selectable"]["states"])
        small = [n for n in sels if n.get("rect") and 0 < min(n["rect"]["w"], n["rect"]["h"]) < touch]
        tsz = sorted({n["text"]["size"] for n in ns if n.get("text")})
        tfont = sorted({os.path.basename(n["text"]["font"] or "?") for n in ns if n.get("text")})
        body += ("<h2>플랫폼 항목</h2><table><tr><th>항목</th><th>기록</th></tr>"
                 "<tr><td>Canvas Scaler</td><td class='wrap'>%s</td></tr>"
                 "<tr><td>Safe Area</td><td>%s</td></tr>"
                 "<tr><td>상태 (Hover·Focused)</td><td>입력 %d개 중 Hover %d · Focused %d</td></tr>"
                 "<tr><td>터치 영역 &lt;%dpx</td><td class='wrap'>%d개 %s</td></tr>"
                 "<tr><td>텍스트</td><td class='wrap'>폰트 %s · 크기 %s (최소 %s)</td></tr>"
                 "<tr><td>화면 비율</td><td>스크린샷으로 확인 (누락: %s)</td></tr></table>") % (
            E("; ".join(canv) or "화면 프리팹에 없음 (상위 캔버스 사용)"),
            "있음" if any("safeArea" in n["flags"] for n in ns) else "없음",
            len(sels), hover, focus, touch, len(small), E(", ".join(n["path"].rsplit("/", 1)[-1] for n in small[:10])),
            E(", ".join(tfont) or "-"), E(", ".join("%g" % x for x in tsz) or "-"), "%g" % tsz[0] if tsz else "-",
            ", ".join(missing) or "없음")
        body += CT.screen_section(sys.modules[__name__], d.td, s["prefab"]) if getattr(d, "td", None) else ""
        write(out, "screens/%s.html" % s["slug"], page("%s" % s["name"], body, depth=1))


def difficulty(prefabs):
    if len(prefabs) <= 2:
        return "쉬움"
    return "보통" if len(prefabs) <= 9 else "어려움"


def build_refactor(d, out):
    rows = []
    for t, dec in d.last.items():
        if dec["status"] != "폐기":
            continue
        members = dec["memberSnapshot"]
        prefabs = sorted({source_prefab(mbr, d) for mbr in members})
        screens = sorted({d.inv[mbr][1] for mbr in members if mbr in d.inv})
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td class='wrap'>%s</td></tr>" % (
            cp(t), cp(dec["to"]) if dec["to"] else "<span class='warn'>대체 미정</span>", E(dec["type"]), len(screens),
            difficulty(prefabs), E(", ".join(prefabs[:8]) + (" …" if len(prefabs) > 8 else ""))))
    body = ("<p>폐기 → 표준 매핑. 영향 화면이 많고 교체가 쉬운 항목부터 작업 단위로 끊는다.</p><table><tr><th>폐기</th><th>표준(대체)</th>"
            "<th>유형</th><th>영향 화면</th><th>난이도</th><th>프리팹</th></tr>%s</table>") % (
        "".join(rows) or "<tr><td colspan=6 class='mut'>폐기 결정 없음</td></tr>")
    write(out, "refactor-map.html", page("리팩터 맵", body))


def build_decisions(d, out):
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class='wrap'>%s</td></tr>" % (
        dec["id"], dec["at"], E(dec["type"]), cp(dec["target"]), tag(dec["status"]) + (" " + E(dec.get("kind") or "")),
        E(dec["to"] or ""), E(dec["supersedes"] or ""), E(dec.get("reason") or "")) for dec in reversed(d.decisions))
    body = ("<table><tr><th>ID</th><th>날짜</th><th>유형</th><th>대상</th><th>결정</th><th>대체</th><th>이전 결정</th><th>사유</th></tr>%s</table>"
            % (rows or "<tr><td colspan=8 class='mut'>결정 없음</td></tr>"))
    write(out, "decisions.html", page("결정 이력", body))


BUILDERS = {"index": build_index, "tokens": build_tokens, "components": build_components, "screens": build_screens,
            "refactor-map": build_refactor, "decisions": build_decisions}


def write(out, rel, text):
    path = os.path.join(out, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def build(pages, out=None, templates=False):
    out = out or C.p("catalog")
    d = Data()
    d.td = CT.TData()
    if d.td.present:
        TEMPLATE_NAV[:] = CT.NAV
    CA.write_assets(out)
    for p_ in pages:
        BUILDERS[p_](d, out)
    if templates and d.td.present:
        for p_ in CT.PAGES:
            CT.BUILDERS[p_](sys.modules[__name__], d, d.td, out)
        pages = pages + CT.PAGES
    elif templates:
        print("data/template-index.json 없음 — 템플릿 페이지는 건너뜀 (templates.py --select 먼저)")
    print("생성(.tmp): %s → 다음: python scripts/validate.py --rename catalog" % ", ".join(pages))
    return 0


LINK_RE = re.compile(r"""(?:href|src)=["']([^"'#?]+)[?"']""")  # ?쿼리는 떼고 파일만 검사(review.html?screen=…)


def check(out=None):
    """[(페이지 조각, 메시지)] — 깨진 링크·이미지, 없는 페이지."""
    out = out or C.p("catalog")
    bad = []
    for p_ in C.CATALOG_PAGES:
        if not os.path.exists(os.path.join(out, p_ + ".html")):
            bad.append((p_, "페이지 없음: catalog/%s.html" % p_))
    for dp, _dn, fn in os.walk(out):
        for f in fn:
            if not f.endswith(".html"):
                continue
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, out).replace("\\", "/")
            chunk = rel.split("/")[0].replace(".html", "")
            with open(full, encoding="utf-8") as fh:
                text = fh.read()
            for link in LINK_RE.findall(text):
                link = html.unescape(link)
                if link.startswith("file:///"):
                    target = link[len("file:///"):]
                elif re.match(r"^[a-z]+:", link):
                    continue
                else:
                    target = os.path.join(dp, link)
                if not os.path.exists(os.path.normpath(target)):
                    bad.append((chunk, "깨진 링크 %s → %s" % (rel, link)))
    return bad


def samples(kind, n=5):
    d = Data()
    gs = d.groups.get(kind)
    if not gs:
        print("종류 %s 의 그룹 없음" % kind)
        return 1
    picks = []
    i = 0
    while len(picks) < n and any(i < len(g["members"]) for g in gs):
        for g in gs:
            if i < len(g["members"]) and len(picks) < n:
                picks.append((g, g["members"][i]))
        i += 1
    for g, nid in picks:
        b, s, node = d.inv.get(nid, ("?", "?", {}))
        r = node.get("rect") or {}
        gr = node.get("graphic") or {}
        t = node.get("text") or {}
        c = d.cls.get(nid, (0, 0, {}))[2]
        print("- 노드: %s" % nid)
        print("  배치 %s · 화면 %s · 분류 %s(%s, %s) · 그룹 %s(%s)" % (b, s, c.get("kind"), c.get("by"), c.get("basis"), g["id"],
                                                               d.status(g["id"], g["status"])))
        print("  크기 %sx%s · 색 %s · 스프라이트 %s · 폰트 %s %s" % (r.get("w"), r.get("h"), gr.get("color") or t.get("color"),
                                                         (gr.get("sprite") or {}).get("path"), t.get("font"), t.get("size")))
        print("  출처 프리팹: %s · 스크린샷: input/screenshots/%s/%s_<비율>.png" % (source_prefab(nid, d), b, s))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", choices=C.CATALOG_PAGES)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--templates", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--samples")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.page:
        return build([a.page])
    if a.all:
        return build(C.CATALOG_PAGES, templates=True)
    if a.templates:
        return build([], templates=True)
    if a.check:
        bad = check()
        for c, msg in bad:
            print("[%s] %s" % (c, msg))
        print("깨진 링크·이미지·없는 페이지 %d개" % len(bad))
        return 1 if bad else 0
    if a.samples:
        return samples(a.samples, a.n)
    ap.print_help()
    return 2


def selftest():
    out = os.path.join(C.selftest_dir("catalog"), "catalog")
    d = Data.__new__(Data)
    d.inv, d.cls, d.groups, d.metrics, d.registry = {}, {}, {}, {}, {}
    d.tokens = {c: None for c in C.TOKEN_CATEGORIES}
    d.treg = dict(d.tokens)
    d.decisions, d.questions, d.manifest, d.batches, d.last = [], [], None, {}, {}
    d.node_group, d.group_by_id = {}, {}
    d.td = CT.TData(empty=True)
    TEMPLATE_NAV[:] = CT.NAV
    CA.write_assets(out)
    for p_ in C.CATALOG_PAGES:
        BUILDERS[p_](d, out)
    for p_ in CT.PAGES:
        CT.BUILDERS[p_](sys.modules[__name__], d, d.td, out)
    for dp, _dn, fn in os.walk(out):
        for f in fn:
            if f.endswith(".tmp"):
                os.replace(os.path.join(dp, f), os.path.join(dp, f[:-4]))
    assert check(out) == [], check(out)
    assert os.path.exists(os.path.join(out, "assets", "explorer.css")) and os.path.exists(os.path.join(out, "assets", "explorer.js"))
    td = CT.TData(empty=True)  # 배치 맵 뷰어 데이터: 비활성·자동생성 노드 제외, 템플릿 색 키, 깊이 끊김 보정
    td.t = {"b": {"slug": "b", "name": "B", "kind": "other", "tier": "atom"}}

    def bx(path, depth, active=True, tpl=None):
        return {"path": path, "name": path.rsplit("/", 1)[-1], "depth": depth, "x": 1, "y": 1, "w": 2, "h": 2, "template": tpl,
                "active": active, "sample": False, "loader": False}
    lay = {"slug": "s", "kind": "screen", "image": "previews/none.png", "width": 10, "height": 5,
           "boxes": [bx("S", 0), bx("S/H", 1, False), bx("S/H/K", 3), bx("S/[generated] P", 1), bx("S/B", 1, tpl="b")]}
    html_ = CT.viewer(sys.modules[__name__], td, out, lay, "../")
    data = json.loads(re.search(r"<script type='application/json' id='layout-data'>(.*?)</script>", html_).group(1))
    assert [r[6] for r in data["b"]] == ["S", "K", "B"] and data["b"][1][4] == 1, data["b"]
    assert data["t"] == [["b", "B", "atom", "atom"]] and data["b"][2][7] == 0 and data["base"] == "../templates/"
    with open(os.path.join(out, "index.html"), "a", encoding="utf-8") as f:
        f.write('<a href="nope.html">x</a>')
    assert len(check(out)) == 1, "깨진 링크를 잡아야 함"
    print("build_catalog.py selftest ok (전체 데이터 경로는 state.py --selftest 가 검사)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
