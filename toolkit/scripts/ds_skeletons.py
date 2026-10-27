"""P0-2 골격 레시피: 화면 배치 데이터(data/layout/screen)에서 형별 공통 골격 노드를 뽑아
<저장소>/Docs/ui-design-system/skeletons.md 를 만든다.

형 4종: View 기본형 / 목록+탭형 / Popup Tall형 / Popup Wide형 (RECIPES).
골격 노드 = 형의 화면 중 MIN_SHARE 이상(최소 2)이 가진 노드. 템플릿 노드는 slug 로, 나머지는 루트 기준 경로로 맞춘다.
템플릿 내부 노드는 템플릿 몫이라 뺀다(단 형을 정하는 템플릿은 다른 템플릿 안에 있어도 센다).
역할 노드(목록 = ScrollRect+WrapContent, 탭 = ToggleGroup)는 컴포넌트로 찾는다.
좌표 합의: 대표 박스와 x·y(·w·h) 가 각각 ±TOL_PX 렌더 px 안이면 같은 좌표로 센다.

사용:
  python scripts/ds_skeletons.py --run        → Docs/ui-design-system/skeletons.md
  python scripts/ds_skeletons.py --selftest
"""
import argparse
import collections
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

TOL_PX = 4.0
MIN_SHARE = 0.35
CORE_SHARE = 0.5
MAX_PATH_DEPTH = 3
AGREE_MIN = 0.6
PARENT_MIN = 0.8
TOP_PROPS = 4
SOURCES = 3
ROLES = collections.OrderedDict([("list", {"ScrollRect", "WrapContent"}), ("tabs", {"ToggleGroup"})])
ROLE_LABELS = {"list": "목록(ScrollRect+WrapContent)", "tabs": "탭(ToggleGroup)"}
SAFE = {"safearea", "unsafearea"}
CLOSE_RE = re.compile(r"close|exit", re.I)
RECIPES = [
    {"id": "view-basic", "title": "View 기본형", "kind": "View", "templates": ("contenttitle", "backbutton"),
     "safe": True, "roles": (), "rule": "View · 템플릿 contenttitle·backbutton · 루트 바로 아래 SafeArea+UnSafeArea"},
    {"id": "list-tab", "title": "목록+탭형", "kind": "View", "templates": ("contenttitle", "backbutton"),
     "safe": True, "roles": ("list", "tabs"),
     "rule": "View 기본형 조건 + 목록 노드(ScrollRect+WrapContent) + 탭 노드(ToggleGroup) — 켜짐 여부 무관"},
    {"id": "popup-tall", "title": "Popup Tall형", "kind": "Popup", "templates": ("popup-bg-tall",),
     "safe": False, "roles": (), "rule": "Popup · 템플릿 popup-bg-tall(다른 템플릿 안 포함)"},
    {"id": "popup-wide", "title": "Popup Wide형", "kind": "Popup", "templates": ("popup-bg-wide",),
     "safe": False, "roles": (), "rule": "Popup · 템플릿 popup-bg-wide(다른 템플릿 안 포함)"},
]


# ---------- 읽기 ----------

def repo_root():
    return os.path.dirname(C.ROOT)


def out_path():
    return os.path.join(repo_root(), "Docs", "ui-design-system", "skeletons.md")


def comps_of(box):
    return {c.strip() for c in (box.get("comps") or "").split(",") if c.strip()}


def screen_kind(root):
    name = root["name"]
    for k in ("View", "Popup"):
        if name.endswith(k):
            return k
    for c in sorted(comps_of(root)):
        for k in ("View", "Popup"):
            if c.endswith(k):
                return k
    return None


def normalize(layout):
    """layout json → {slug, name, kind, scale, nodes}. 예시·로더·[generated] 노드는 뺀다. owner = 가장 가까운 템플릿 조상."""
    boxes = [b for b in layout["boxes"] if not b.get("sample") and not b.get("loader")
             and "/[generated] " not in "/" + b["path"]]
    tpl_at, nodes = {}, []
    for i, b in enumerate(boxes):
        parts = b["path"].split("/")
        owner = None
        for k in range(len(parts) - 1, 0, -1):
            owner = tpl_at.get("/".join(parts[:k]))
            if owner:
                break
        if b.get("template"):
            tpl_at[b["path"]] = b["template"]
        rel = "/".join(parts[1:])
        nodes.append({"i": i, "rel": rel, "parent": "/".join(parts[1:-1]), "name": b["name"], "depth": b["depth"],
                      "x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"], "template": b.get("template"),
                      "active": bool(b.get("active")), "comps": comps_of(b), "owner": owner})
    root = boxes[0]
    return {"slug": layout["slug"], "name": root["name"], "kind": screen_kind(root),
            "scale": layout.get("scale") or 1, "nodes": nodes}


def load_screens(dirpath):
    return [normalize(C.load_json(f)) for f in C.iter_json(dirpath)]


def template_meta(slug, metas=None):
    if metas is not None:
        return metas.get(slug) or {}
    return C.load_json(C.p("data", "templates", slug + ".json")) or {}


# ---------- 분류 ----------

def templates_anywhere(s):
    return {n["template"] for n in s["nodes"] if n["template"]}


def has_safe(s):
    return SAFE <= {n["name"].lower() for n in s["nodes"] if n["depth"] == 1}


def role_nodes(s, role):
    return [n for n in s["nodes"] if ROLES[role] <= n["comps"]]


def matches(s, r):
    if s["kind"] != r["kind"] or not set(r["templates"]) <= templates_anywhere(s):
        return False
    if r["safe"] and not has_safe(s):
        return False
    return all(role_nodes(s, role) for role in r["roles"])


def screen_keys(s, r):
    """{key: [노드]} — T:<slug> 템플릿, P:<경로> 일반 노드, R:<역할> 역할 노드."""
    keys = collections.defaultdict(list)
    for n in s["nodes"][1:]:
        if n["template"] and (n["owner"] is None or n["template"] in r["templates"]):
            keys["T:" + n["template"]].append(n)
        elif not n["template"] and n["owner"] is None and n["depth"] <= MAX_PATH_DEPTH:
            keys["P:" + n["rel"]].append(n)
    for role in r["roles"]:
        keys["R:" + role] = role_nodes(s, role)
    return keys


# ---------- 좌표 합의 ----------

def near(a, b, fields):
    return all(abs(a[f] - b[f]) <= TOL_PX for f in fields)


def support(by_slug, c, fields):
    return sorted(slug for slug, ns in by_slug.items() if any(near(c, m, fields) for m in ns))


def display_rel(chosen):
    """화면별 몫 인스턴스의 최빈 부모 + 최빈 이름 → (경로, 부모가 모였나).
    최빈 부모가 2 미만이거나 1/3 미만이면 공통 접두 + '…' 로 접는다."""
    parents = collections.Counter(n["parent"] for n in chosen.values())
    top, cnt = sorted(parents.items(), key=lambda kv: (-kv[1], kv[0].count("/"), kv[0]))[0]
    clear = cnt >= 2 and cnt * 3 >= len(chosen)
    pool = [n for n in chosen.values() if n["parent"] == top] if clear else list(chosen.values())
    name = sorted(collections.Counter(n["name"] for n in pool).items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    if clear:
        return (top + "/" + name if top else name), True
    segs = [n["parent"].split("/") if n["parent"] else [] for n in chosen.values()]
    common = []
    for parts in zip(*segs):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    return "/".join(common + ["…", name]), False


def consensus(by_slug, prefer=None):
    """(대표 화면, 대표 노드, 위치·크기 일치 화면들). 지지 화면이 가장 많은 후보, 동점이면 prefer 경로·얕은 노드·이름순."""
    best = None
    for slug in sorted(by_slug):
        for c in by_slug[slug]:
            sup = support(by_slug, c, "xywh")
            score = (-len(sup), prefer is not None and c["rel"] != prefer, c["depth"], slug, c["i"])
            if best is None or score < best[0]:
                best = (score, slug, c, sup)
    return best[1], best[2], best[3]


def pick(ns, rep):
    return min(ns, key=lambda n: (max(abs(n[f] - rep[f]) for f in "xywh"), n["i"]))


def clusters(by_slug, limit=3):
    """화면별 대표 인스턴스를 좌표·크기로 묶는다 → [(노드, 화면 수)]."""
    left = {slug: list(ns) for slug, ns in by_slug.items()}
    out = []
    while left and len(out) < limit:
        _slug, rep, sup = consensus(left)
        out.append((rep, len(sup)))
        left = {s: ns for s, ns in left.items() if s not in sup}
    return out


def analyze_key(key, by_slug):
    _s, rep0, _f = consensus(by_slug)
    rel, clear = display_rel({slug: pick(ns, rep0) for slug, ns in by_slug.items()})
    rep_slug, rep, full = consensus(by_slug, rel if clear else None)
    pos = support(by_slug, rep, "xy")
    chosen = {slug: pick(ns, rep) for slug, ns in by_slug.items()}
    parents = collections.Counter(n["parent"] for n in chosen.values())
    return {"key": key, "have": sorted(by_slug), "rep_slug": rep_slug, "rep": rep, "full": full, "pos": pos,
            "rel": rel, "parents": parents, "by_slug": by_slug,
            "multi": sum(1 for ns in by_slug.values() if len(ns) > 1)}


def skeleton(screens, r):
    per_key = collections.defaultdict(dict)
    for s in screens:
        for k, ns in screen_keys(s, r).items():
            if ns:
                per_key[k][s["slug"]] = ns
    need = max(2, int(math.ceil(MIN_SHARE * len(screens))))
    forced = {"T:" + t for t in r["templates"]} | {"R:" + x for x in r["roles"]}
    keep = [k for k in per_key if len(per_key[k]) >= need or k in forced]
    return [analyze_key(k, per_key[k]) for k in keep]


def root_comps(screens):
    cnt = collections.Counter()
    for s in screens:
        cnt.update(c for c in s["nodes"][0]["comps"] if c != s["name"])
    return [(c, v) for c, v in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0])) if v * 2 >= len(screens)]


def sources(screens, sk, keep=None):
    """골격 노드를 대표 좌표 그대로(위치·크기) 가장 많이 가진 화면 순. keep 이 있으면 그 slug 만."""
    score = collections.Counter()
    for k in sk:
        score.update(k["full"])
    pool = [s["slug"] for s in screens if keep is None or s["slug"] in keep]
    return sorted(pool, key=lambda x: (-score[x], x))[:SOURCES]


def unclean_tag(slug, clean):
    """screens.jsonl cleanReference=false 인 출처 화면 꼬리표. clean = {slug: screens 행} (없으면 빈 문자열)."""
    row = (clean or {}).get(slug)
    if not row or row["cleanReference"]:
        return ""
    why = "Completely 출력" if row["cleanReason"].startswith("Completely") else "사본 %d" % row["lookalikeCopies"]
    return " ⚠ cleanReference=false(%s)" % why


# ---------- 형별 ⚠ ----------

def warn_nodes(sk):
    out = []
    for k in sk:
        h = len(k["have"])
        if h >= 2 and len(k["full"]) < AGREE_MIN * h:
            cl = "; ".join("%s ×%d" % (fmt_box(n), c) for n, c in clusters(k["by_slug"]))
            out.append("**%s** 좌표가 갈린다 — 보유 %d 중 대표 좌표·크기 일치 %d, 위치만 일치 %d. 상위 묶음(±%g px): %s"
                       % (label(k), h, len(k["full"]), len(k["pos"]), TOL_PX, cl))
        top = k["parents"].most_common(3)
        if h >= 2 and top[0][1] < PARENT_MIN * h:
            out.append("**%s** 부모 경로가 갈린다 — %s" % (label(k), ", ".join("`%s` %d" % (p or "(루트)", c) for p, c in top)))
    return out


def safe_component(cls):
    """루트 바로 아래 SafeArea 노드 중 SafeArea 컴포넌트가 붙은 화면 수 / SafeArea 노드가 있는 화면 수."""
    have = [s for s in cls if any(n["depth"] == 1 and n["name"] == "SafeArea" for n in s["nodes"])]
    comp = sum(any(n["depth"] == 1 and n["name"] == "SafeArea" and "SafeArea" in n["comps"] for n in s["nodes"]) for s in have)
    if comp == len(have):
        return []
    return ["**SafeArea 컴포넌트** — `SafeArea` 노드가 있는 화면 %d 중 SafeArea 컴포넌트가 붙은 화면 %d, "
            "나머지 %d 은 컴포넌트 없이 이름만 SafeArea(위 좌표 묶음이 갈리는 이유로 보임 — 추정)" % (len(have), comp, len(have) - comp)]


def warn_view(all_screens, cls):
    cand = [s for s in all_screens if s["kind"] == "View" and {"contenttitle", "backbutton"} <= templates_anywhere(s)]
    miss = sorted(s["slug"] for s in cand if not has_safe(s))
    out = ["**SafeArea+UnSafeArea 없는 View** — contenttitle·backbutton 을 가진 View %d 중 %d: %s"
           % (len(cand), len(miss), ", ".join(miss) or "없음")] + safe_component(cls)
    views = [s for s in all_screens if s["kind"] == "View"]
    out.append("**View 전체에서의 골격 보급률** — View %d 중 SafeArea+UnSafeArea %d · backbutton %d · contenttitle %d"
               % (len(views), sum(has_safe(s) for s in views), sum("backbutton" in templates_anywhere(s) for s in views),
                  sum("contenttitle" in templates_anywhere(s) for s in views)))
    return out


def tabs_origin(all_screens):
    """ToggleGroup 노드의 출처 분포 → Counter(템플릿 slug | '템플릿 아님')."""
    cnt = collections.Counter()
    for s in all_screens:
        for n in role_nodes(s, "tabs"):
            cnt[n["owner"] or "템플릿 아님"] += 1
    return cnt


def count_screens_with(screens, slug):
    return sum(slug in templates_anywhere(s) for s in screens)


def warn_list_tab(all_screens, cls, metas=None):
    out = []
    rows = []
    for s in cls:
        tg = role_nodes(s, "tabs")
        rows.append("%s %s" % (s["slug"], "/".join(sorted({n["owner"] or "직접" for n in tg}))))
    g = tabs_origin(all_screens)
    out.append("**탭 템플릿 없음** — 이 형의 탭(ToggleGroup) 출처: %s. 화면 159 전체 ToggleGroup 노드 %d 의 출처: %s. "
               "togglebuttonunit 템플릿을 쓰는 화면 %d"
               % ("; ".join(rows), sum(g.values()), ", ".join("%s %d" % kv for kv in g.most_common(6)),
                  count_screens_with(all_screens, "togglebuttonunit")))
    meta = ["%s 사용 %d·화면 %d" % (t, template_meta(t, metas).get("usageTotal") or 0, len(template_meta(t, metas).get("screens") or []))
            for t in ("sortingbuttonunit", "sortingbuttonunitv2")]
    out.append("**정렬 V1/V2 미정** — 배치 데이터(로더 제외) 화면 수: 이 형 sortingbuttonunit %d · sortingbuttonunitv2 %d / 전체 %d · %d. "
               "템플릿 메타(로더·하위 Unit 경유 포함): %s"
               % (count_screens_with(cls, "sortingbuttonunit"), count_screens_with(cls, "sortingbuttonunitv2"),
                  count_screens_with(all_screens, "sortingbuttonunit"), count_screens_with(all_screens, "sortingbuttonunitv2"),
                  " / ".join(meta)))
    return out


def close_kind(s):
    t = templates_anywhere(s)
    if "button-close" in t:
        return "button-close 템플릿"
    if "backbutton" in t:
        return "backbutton 템플릿"
    hits = [n for n in s["nodes"] if CLOSE_RE.search(n["name"]) and {"Button", "ButtonWidget"} & n["comps"]]
    if any(n["template"] for n in hits):
        return "다른 버튼 템플릿을 닫기로(이름 close/exit)"
    if hits:
        return "템플릿 아닌 닫기 노드(이름 close/exit)"
    if any(n["depth"] == 1 and n["name"] == "TouchMask" and "ButtonWidget" in n["comps"] for n in s["nodes"]):
        return "닫기 노드 없음·TouchMask(ButtonWidget) 있음"
    return "닫기 노드 없음·TouchMask 없음"


def bg_children(slug, tlayouts=None):
    d = (tlayouts or {}).get(slug) if tlayouts is not None else C.load_json(C.p("data", "layout", "template", slug + ".json"))
    if not d:
        return []
    return [b["name"] for b in d["boxes"] if b["depth"] == 1 and not b.get("sample")]


def warn_popup(all_screens, cls, r, tlayouts=None):
    out = safe_component(cls)
    ck = collections.Counter(close_kind(s) for s in cls)
    out.append("**닫기 버튼 표준 없음** — %s. (TouchMask 가 바깥 터치로 닫는다는 것은 이름·컴포넌트로 본 추정, 코드 미확인)"
               % ", ".join("%s %d" % kv for kv in ck.most_common()))
    bg = r["templates"][0]
    out.append("**제목** — popup-title 템플릿을 쓰는 화면 %d / %d. %s 템플릿 자체의 1단 자식: %s"
               % (count_screens_with(cls, "popup-title"), len(cls), bg, ", ".join(bg_children(bg, tlayouts)) or "(배치 데이터 없음)"))
    btn = ["button-yellow", "button-yellow-new", "button-blue", "button-red"]
    out.append("**주·보조 버튼 미정** — 화면 수: %s" % ", ".join("%s %d" % (b, count_screens_with(cls, b)) for b in btn))
    other = "popup-bg-wide" if bg == "popup-bg-tall" else "popup-bg-tall"
    both = sorted(s["slug"] for s in cls if other in templates_anywhere(s))
    out.append("**Tall·Wide 동시 사용** — %d: %s" % (len(both), ", ".join(both) or "없음"))
    nonpop = sorted(s["slug"] for s in all_screens if s["kind"] != "Popup" and bg in templates_anywhere(s))
    out.append("**Popup 이 아닌 화면의 %s** — %d: %s (형 분류에서 뺐다)" % (bg, len(nonpop), ", ".join(nonpop) or "없음"))
    return out


def warns(all_screens, cls, r, sk, metas=None, tlayouts=None):
    out = warn_nodes(sk)
    if r["id"] == "view-basic":
        out += warn_view(all_screens, cls)
    elif r["id"] == "list-tab":
        out += warn_list_tab(all_screens, cls, metas)
    else:
        out += warn_popup(all_screens, cls, r, tlayouts)
    return out


# ---------- 출력 ----------

def num(v):
    s = "%.1f" % v
    return s[:-2] if s.endswith(".0") else s


def fmt_box(n, scale=None):
    k = 1.0 / scale if scale else 1.0
    return "%s,%s %s×%s" % (num(n["x"] * k), num(n["y"] * k), num(n["w"] * k), num(n["h"] * k))


def label(k):
    kind, val = k["key"].split(":", 1)
    if kind == "T":
        return "[%s]" % val
    if kind == "R":
        return ROLE_LABELS[val]
    return val.split("/")[-1]


def map_link(slug, name):
    return "[%s](../../ui-audit/catalog/map/%s.html)" % (name, slug)


def top_props(slug, metas):
    tp = (template_meta(slug, metas).get("overrides") or {}).get("topProps") or []
    return ", ".join("`%s` %d" % (p, c) for p, c in tp[:TOP_PROPS]) or "—"


def order_keys(sk):
    return sorted(sk, key=lambda k: (k["rel"].count("/"), k["rel"]))


def build_tree(sk):
    """{seg: {'k': key|None, 'c': {...}}} — 최빈 경로로 끼워 넣는다."""
    tree = collections.OrderedDict()
    for k in order_keys(sk):
        cur = tree
        segs = k["rel"].split("/")
        for j, seg in enumerate(segs):
            node = cur.setdefault(seg, {"k": [], "c": collections.OrderedDict()})
            if j == len(segs) - 1:
                node["k"].append(k)
            cur = node["c"]
    return tree


def optional(k, n):
    return len(k["have"]) < CORE_SHARE * n


def tree_line(seg, ks, n):
    if not ks:
        return seg
    parts = []
    for k in ks:
        tag = "[%s] " % k["key"][2:] if k["key"].startswith("T:") else ""
        role = ""
        if k["key"].startswith("R:"):
            own = collections.Counter(pick(ns, k["rep"])["owner"] or "직접" for ns in k["by_slug"].values())
            role = " (%s · 출처 %s)" % (ROLE_LABELS[k["key"][2:]], ", ".join("%s %d" % kv for kv in sorted(own.items(), key=lambda kv: (-kv[1], kv[0]))))
        parts.append("%s%s%s %s  보유 %d/%d · 같은 좌표 %d%s" % (tag, seg, role, fmt_box(k["rep"]), len(k["have"]), n,
                                                           len(k["full"]), " · 선택" if optional(k, n) else ""))
    return " | ".join(parts)


def render_tree(tree, n, prefix=""):
    lines, items = [], list(tree.items())
    for i, (seg, node) in enumerate(items):
        last = i == len(items) - 1
        lines.append(prefix + ("└ " if last else "├ ") + tree_line(seg, node["k"], n))
        lines += render_tree(node["c"], n, prefix + ("    " if last else "│   "))
    return lines


def by_slug_name(screens):
    return {s["slug"]: s["name"] for s in screens}


def section(no, r, cls, sk, all_screens, metas, tlayouts=None, clean=None):
    names = by_slug_name(all_screens)
    scale = {s["slug"]: s["scale"] for s in all_screens}
    n = len(cls)
    src = sources(cls, sk)
    rc = root_comps(cls)
    L = ["## %d. %s" % (no, r["title"]), "",
         "- 분류 조건: %s" % r["rule"],
         "- 화면 %d개: %s" % (n, ", ".join(names[s["slug"]] for s in cls)),
         "- 출처 화면(골격 노드를 대표 좌표 그대로 가장 많이 가진 순): %s"
         % " · ".join(map_link(x, names[x]) + unclean_tag(x, clean) for x in src)]
    if clean is not None:
        ok = sources(cls, sk, {x for x, row in clean.items() if row["cleanReference"]})
        L.append("- 참고 화면으로 열 것(위 순서 중 `screens.jsonl` cleanReference=true 만): %s"
                 % (" · ".join(map_link(x, names[x]) for x in ok) or "없음"))
    L += ["- 골격 노드 %d개 (보유 기준 %d/%d 이상)" % (len(sk), max(2, int(math.ceil(MIN_SHARE * n))), n), "",
         "와이어 — 좌표는 렌더 px `x,y w×h`(왼쪽 위 원점, 1920×1080 → 폭 1280), 경로는 최빈 부모 경로(화면마다 갈리면 `…`):",
         "", "```",
         "<Name>%s  (루트: %s 스크립트 · %s)" % (r["kind"], r["kind"],
                                             " · ".join("%s %d/%d" % (c, v, n) for c, v in rc) or "공통 컴포넌트 없음")]
    L += render_tree(build_tree(sk), n)
    L += ["```", "",
          "| 노드 | 최빈 경로 (대표: 화면) | 렌더 px x,y w×h | 캔버스 단위 x,y w×h | 템플릿 | 보유 | 같은 위치·크기 / 같은 위치 (±%g px) | 자주 바꾸는 속성 상위 |" % TOL_PX,
          "|---|---|---|---|---|---|---|---|"]
    for k in order_keys(sk):
        slug = k["key"][2:] if k["key"].startswith("T:") else None
        L.append("| %s | `%s` (대표: %s `%s`) | %s | %s | %s | %d/%d%s | %d / %d | %s |" % (
            label(k), k["rel"], names[k["rep_slug"]], k["rep"]["rel"], fmt_box(k["rep"]),
            fmt_box(k["rep"], scale[k["rep_slug"]]), slug or "—", len(k["have"]), n, " 선택" if optional(k, n) else "",
            len(k["full"]), len(k["pos"]),
            top_props(slug, metas) if slug else "—"))
    w = warns(all_screens, cls, r, sk, metas, tlayouts)
    L += ["", "표준이 없어 갈리는 지점:", ""] + ["- ⚠ " + x for x in w] + [""]
    return L, {"id": r["id"], "screens": n, "nodes": len(sk), "sources": src, "warns": len(w)}


def render(all_screens, metas=None, tlayouts=None, clean=None):
    """clean = {slug: screens.jsonl 행} — 주면 출처 화면에 cleanReference=false 꼬리표를 달고 깨끗한 출처 줄을 더한다."""
    head = ["# UI 골격 레시피 (skeletons)", "",
            "> 생성물이다. 손으로 고치지 말고 `ui-audit/scripts/ds_skeletons.py --run` 으로 다시 만든다.",
            "> 데이터: `ui-audit/data/layout/screen/*.json`(Unity 배치 렌더, 화면 %d) · 템플릿 메타 `ui-audit/data/templates/<slug>.json`."
            % len(all_screens),
            "> 링크(`ui-audit/catalog/map/…`)는 ui-audit 작업 공간이 있는 체크아웃에서만 열린다(gitignore).", "",
            "## 읽는 법", "",
            "- **렌더 px**: 1920×1080 화면을 폭 1280 으로 줄인 렌더의 픽셀, 왼쪽 위 원점의 절대 박스. **캔버스 단위** = 렌더 px ÷ scale(화면별 `scale`, 보통 0.6667) → 1920×1080 기준. 둘 다 Unity `anchoredPosition` 이 아니다 — 앵커·피벗은 대표 화면 프리팹에서 가져온다.",
            "- **허용 오차**: x·y·w·h 각각 ±%g 렌더 px(≈ ±%g 캔버스 단위). '같은 위치' = x·y 만, '같은 위치·크기' = 넷 다." % (TOL_PX, round(TOL_PX * 1.5)),
            "- **골격 노드** = 그 형의 화면 중 %d%% 이상(최소 2)이 가진 노드. 템플릿 노드는 slug 로, 그 밖은 루트 기준 경로(깊이 %d 까지)로 맞춘다. 템플릿 내부 노드는 템플릿 몫이라 뺀다(형을 정하는 템플릿은 다른 템플릿 안에 있어도 센다). 역할 노드는 컴포넌트로 찾는다. 예시 아이템·로더 노드는 뺀다." % (round(MIN_SHARE * 100), MAX_PATH_DEPTH),
            "- **선택** = 골격 노드 중 보유가 %d%% 미만인 것 — 형의 필수 뼈대가 아니라 자주 붙는 부품." % round(CORE_SHARE * 100),
            "- **대표 좌표** = 오차 안에 드는 화면이 가장 많은 인스턴스. 한 화면에 같은 노드가 여럿이면 대표에 가장 가까운 것을 그 화면 몫으로 본다.",
            "- **자주 바꾸는 속성** = 템플릿 메타 `overrides.topProps`(전체 인스턴스 기준 `속성 횟수`).",
            "- **⚠ cleanReference=false** = 출처 화면이 `screens.jsonl` 기준 깨끗한 참고가 아님(템플릿 사본·Completely 출력). 좌표 근거로는 남기되, 구조를 따라 할 화면은 '참고 화면으로 열 것' 줄에서 고른다.", ""]
    secs, stats = [], []
    for i, r in enumerate(RECIPES, 1):
        cls = [s for s in all_screens if matches(s, r)]
        if not cls:
            stats.append({"id": r["id"], "screens": 0, "nodes": 0, "sources": [], "warns": 0})
            secs += ["## %d. %s" % (i, r["title"]), "", "해당 화면 없음.", ""]
            continue
        lines, st = section(i, r, cls, skeleton(cls, r), all_screens, metas, tlayouts, clean)
        secs += lines
        stats.append(st)
    names = by_slug_name(all_screens)
    summ = ["## 요약", "", "| 형 | 화면 | 골격 노드 | ⚠ | 출처 화면 |", "|---|---|---|---|---|"]
    for r, st in zip(RECIPES, stats):
        summ.append("| %s | %d | %d | %d | %s |" % (r["title"], st["screens"], st["nodes"], st["warns"],
                                                 ", ".join(names[x] + (" ⚠" if unclean_tag(x, clean) else "") for x in st["sources"]) or "—"))
    summ += ["", "목록+탭형 화면은 View 기본형에도 들어간다(상위 집합). ⚠ = cleanReference=false(참고 화면으로 권하지 않음).", ""]
    tail = ["## 새 화면 만들 때 이 레시피를 쓰는 법", "",
            "1. 형을 고른다 — 전체 화면 View(뒤로 가기 있음) → View 기본형, 목록+카테고리 탭이 있으면 목록+탭형, 세로로 긴 팝업 → Popup Tall형, 가로 팝업·확인창 → Popup Wide형.",
            "2. 와이어의 노드를 같은 경로·같은 템플릿으로 놓는다. `[slug]` 노드는 **템플릿 인스턴스로** 넣는다(복사·`Completely` 언팩 금지).",
            "3. 좌표는 표의 캔버스 단위를 기준으로 하고, 앵커·피벗은 출처 화면 프리팹(cleanReference=true 인 것)에서 그대로 가져온다.",
            "4. 템플릿에서 바꾸는 값은 '자주 바꾸는 속성' 안에서 고른다. 그 밖을 바꿔야 하면 조합안에 적는다.",
            "5. ⚠ 지점(표준 미정)은 임의로 고르지 말고 조합안의 '표준 없는 지점'으로 올린다.", "",
            "## 다시 만들기", "", "`ui-audit/` 에서 (배치 데이터가 최신일 때 — `layout_map.py --collect` 뒤):", "",
            "```", "python scripts/ds_skeletons.py --run", "python scripts/ds_skeletons.py --selftest", "```", ""]
    return "\n".join(head + summ + secs + tail), stats


def clean_rows():
    """{slug: screens.jsonl 행} — ds_index 와 같은 입력으로 ds_screens 를 돌린다(앱 흐름은 쓰지 않음)."""
    import ds_index
    import ds_screens
    idx = C.load_json(C.p("data", "template-index.json")) or {"templates": []}
    temps = [C.load_json(C.p("data", "templates", s + ".json")) for s in idx["templates"]]
    layouts, tlayouts, _flow = ds_screens.load_inputs()
    rows = ds_screens.build_rows(layouts, [t for t in temps if t], tlayouts, ds_index.completely_outputs(), None, None)
    return {r["slug"]: r for r in rows}


def run():
    screens = load_screens(C.p("data", "layout", "screen"))
    if not screens:
        print("data/layout/screen 비어 있음 — layout_map.py --collect 먼저")
        return 1
    text, stats = render(screens, clean=clean_rows())
    dst = out_path()
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("화면 %d → %s (%d줄, %d bytes)" % (len(screens), os.path.relpath(dst, repo_root()), text.count("\n"), len(text.encode("utf-8"))))
    for st in stats:
        print("  %s: 화면 %d · 골격 노드 %d · ⚠ %d · 출처 %s" % (st["id"], st["screens"], st["nodes"], st["warns"], ", ".join(st["sources"])))
    return 0


# ---------- selftest ----------

def _b(path, x, y, w, h, tpl=None, comps="", sample=False):
    return {"path": path, "name": path.split("/")[-1], "depth": path.count("/"), "x": x, "y": y, "w": w, "h": h,
            "template": tpl, "active": True, "sample": sample, "loader": False, "comps": comps}


def _view(slug, name, dx=0.0, tabs=False, safe=True, ct=True):
    bs = [_b(name, 0, 0, 1280, 720, comps=name + ",PlayableDirector,Animator")]
    if safe:
        bs.append(_b(name + "/UnSafeArea", 0, 0, 1280, 720))
    if ct:
        bs.append(_b(name + "/UnSafeArea/ContentTitle", dx, 0, 568, 203.3, "contenttitle", "Image"))
        bs.append(_b(name + "/UnSafeArea/ContentTitle/Title", 7, 23, 145, 33, comps="CustomTextMeshProUGUI"))
    if safe:
        bs.append(_b(name + "/SafeArea", 0, 0, 1280, 720, comps="SafeArea"))
    bs.append(_b(name + "/SafeArea/AnchorBottom/BackButton", 0, 632, 179, 72, "backbutton", "BackButtonUnit"))
    if tabs:
        bs.append(_b(name + "/SafeArea/ScrollBackground", 70, 214, 1209, 506, "scrollbackground"))
        bs.append(_b(name + "/SafeArea/ScrollBackground/Tabs", 370, 175, 739, 67, comps="HorizontalLayoutGroup,ToggleGroup"))
        bs.append(_b(name + "/SafeArea/List", 160, 319, 1129, 400, comps="ScrollRect,WrapContent"))
        bs.append(_b(name + "/SafeArea/List/Item", 160, 319, 100, 100, "thumbnailgroupunit", sample=True))
    return {"slug": slug, "scale": 0.6666667, "boxes": bs}


def _popup(slug, name, bg, y=0.0, close=False):
    bs = [_b(name, 0, 0, 1280, 720, comps=name), _b(name + "/SafeArea", 0, 0, 1280, 720, comps="SafeArea"),
          _b(name + "/SafeArea/BG", 332, y, 616, 763, bg, "Image,Button"),
          _b(name + "/SafeArea/BG/Content", 400, 100, 500, 500, comps="Image")]
    if close:
        bs.append(_b(name + "/SafeArea/CloseButton", 900, 10, 60, 60, comps="Button"))
    return {"slug": slug, "scale": 0.6666667, "boxes": bs}


def selftest():
    raw = [_view("av", "AView"), _view("bv", "BView", dx=3.0), _view("cv", "CView", dx=40.0, tabs=True),
           _view("dv", "DView", tabs=True), _view("ev", "EView", safe=False), _view("fv", "FView", ct=False),
           _popup("ap", "APopup", "popup-bg-tall"), _popup("bp", "BPopup", "popup-bg-tall", y=2.0, close=True),
           _popup("cp", "CPopup", "popup-bg-wide"), _popup("dp", "DPopup", "popup-bg-tall", y=-21.0)]
    d = C.selftest_dir("ds-skeletons")
    for x in raw:
        C.write_json_atomic(os.path.join(d, "screen", x["slug"] + ".json"), x)
    screens = load_screens(os.path.join(d, "screen"))
    by = {s["slug"]: s for s in screens}
    assert [s["kind"] for s in screens].count("View") == 6, [s["kind"] for s in screens]
    assert all(not n["template"] == "thumbnailgroupunit" for n in by["cv"]["nodes"]), "예시 노드는 빠져야 함"
    assert by["av"]["nodes"][3]["owner"] == "contenttitle" and by["av"]["nodes"][2]["owner"] is None
    cls = {r["id"]: sorted(s["slug"] for s in screens if matches(s, r)) for r in RECIPES}
    assert cls == {"view-basic": ["av", "bv", "cv", "dv"], "list-tab": ["cv", "dv"],
                   "popup-tall": ["ap", "bp", "dp"], "popup-wide": ["cp"]}, cls
    vb = [s for s in screens if s["slug"] in cls["view-basic"]]
    sk = {k["key"]: k for k in skeleton(vb, RECIPES[0])}
    assert "P:UnSafeArea/ContentTitle/Title" not in sk, "템플릿 내부 노드는 골격에서 빠져야 함"
    ct = sk["T:contenttitle"]
    assert ct["full"] == ["av", "bv", "dv"] and ct["pos"] == ["av", "bv", "dv"] and ct["rep"]["x"] == 0, ct["full"]
    assert sk["T:backbutton"]["full"] == ["av", "bv", "cv", "dv"]
    assert "T:scrollbackground" in sk and "R:list" not in sk  # 2/4 ≥ 35% → 들어감, 역할은 목록+탭형만
    lt = {k["key"]: k for k in skeleton([by["cv"], by["dv"]], RECIPES[1])}
    assert lt["R:tabs"]["rep"]["owner"] == "scrollbackground" and len(lt["R:list"]["full"]) == 2
    pt = {k["key"]: k for k in skeleton([by[x] for x in cls["popup-tall"]], RECIPES[2])}
    assert pt["T:popup-bg-tall"]["full"] == ["ap", "bp"] and len(pt["T:popup-bg-tall"]["have"]) == 3
    assert [c for _n, c in clusters(pt["T:popup-bg-tall"]["by_slug"])] == [2, 1]
    assert close_kind(by["bp"]).startswith("템플릿 아닌") and close_kind(by["ap"]) == "닫기 노드 없음·TouchMask 없음"
    a, b, c = ({"parent": p, "name": "N"} for p in ("X/A", "X/B", "X/C"))
    assert display_rel({"1": a, "2": b, "3": c}) == ("X/…/N", False)
    assert display_rel({"1": a, "2": dict(a), "3": c}) == ("X/A/N", True)
    assert sk["T:scrollbackground"]["rel"] == "SafeArea/ScrollBackground" and not optional(sk["T:scrollbackground"], 4)
    assert optional(sk["T:scrollbackground"], 5)
    metas = {"contenttitle": {"overrides": {"topProps": [["m_text", 27], ["m_Color.a", 28]]}}}
    text, stats = render(screens, metas, tlayouts={})
    assert "├ " in text and "└ " in text and "⚠" in text and "`m_text` 27" in text, text[:400]
    assert "../../ui-audit/catalog/map/av.html" in text
    assert [st["screens"] for st in stats] == [4, 2, 3, 1], stats
    assert "⚠ cleanReference=false(" not in text and "\n- 참고 화면으로 열 것" not in text  # clean 없으면 꼬리표·줄 없음
    row = lambda ok, why="사본 0", n=0: {"cleanReference": ok, "cleanReason": why, "lookalikeCopies": n}  # noqa: E731
    clean = {s["slug"]: row(True) for s in screens}
    clean.update(av=row(False, "사본 2(x ×2)", 2), bp=row(False, "Completely 언팩 빌드 툴 출력", 2))
    text2, stats2 = render(screens, metas, tlayouts={}, clean=clean)
    assert [st["sources"] for st in stats2] == [st["sources"] for st in stats], "꼬리표는 출처 순서를 바꾸지 않는다"
    assert "[AView](../../ui-audit/catalog/map/av.html) ⚠ cleanReference=false(사본 2)" in text2
    assert "⚠ cleanReference=false(Completely 출력)" in text2 and "| DView, CView, AView ⚠ |" in text2
    vb_line = [x for x in text2.splitlines() if x.startswith("- 참고 화면으로 열 것")][0]
    assert "av.html" not in vb_line and "bv.html" in vb_line, vb_line
    assert unclean_tag("zz", clean) == "" and unclean_tag("av", None) == ""
    assert "**SafeArea+UnSafeArea 없는 View** — contenttitle·backbutton 을 가진 View 5 중 1: ev" in text
    assert fmt_box({"x": 2, "y": 4, "w": 6, "h": 8}, 0.5) == "4,8 12×16"
    assert "**SafeArea 컴포넌트**" not in text and "출처 scrollbackground 2" in text
    bare = normalize(_popup("xp", "XPopup", "popup-bg-tall"))
    bare["nodes"][1]["comps"] = set()
    assert "화면 2 중 SafeArea 컴포넌트가 붙은 화면 1, 나머지 1" in safe_component([by["ap"], bare])[0]
    print("ds_skeletons.py selftest ok")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.run:
        return run()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
