"""T3·T4·T5 템플릿 선정·위계, 오버라이드 요약, 복붙 유사품, 그리고 결과 합치기(assemble).

사용:
  python scripts/templates.py --select       data/usage/parts/*.json → data/usage/edges.json, data/templates/<slug>.json,
                                             data/template-index.json (설계 4절 규칙: A 공통 폴더, B 접미사+사용처 2곳 이상)
  python scripts/templates.py --overrides    → data/usage/overrides.json (템플릿별 그대로 사용 / 변형 사용 비율)
  python scripts/templates.py --lookalikes   → data/usage/lookalikes.json (템플릿 인스턴스가 아닌 하위 트리 중 구조 서명이 같거나 가까운 것)
  python scripts/templates.py --assemble     overrides·lookalikes·썸네일을 data/templates/<slug>.json 에 채운다(재실행 안전)
  python scripts/templates.py --all          위 네 가지를 차례로
  python scripts/templates.py --selftest
"""
import argparse
import collections
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import template_scope as TS  # noqa: E402

PARTS = ("prefab", "code", "scene")
CONTAIN_KINDS = ("nested", "field", "code-loader", "code-wrap")  # 사용자가 프리팹일 때 '포함'으로 보는 사용 종류
INSTANCE_KINDS = ("nested", "scene", "variant")  # 수정 속성이 있는 사용 종류
OVR_CATS = [("sprite", re.compile(r"^m_Sprite$|^m_OverrideSprite$|m_SpriteState")),
            ("color", re.compile(r"^m_Color\b|^m_fontColor|^m_faceColor|m_Colors\.")),
            ("size", re.compile(r"^m_SizeDelta|^m_Anchor(Min|Max)|^m_LocalScale|^m_Pivot")),
            ("text", re.compile(r"^m_text$|^m_Text$|^m_fontSize|^m_fontAsset|^m_FontData")),
            ("active", re.compile(r"^m_IsActive$|^m_Enabled$"))]
PLACEMENT_RE = re.compile(r"^m_AnchoredPosition|^m_LocalPosition|^m_LocalRotation|^m_LocalEulerAnglesHint|^m_RootOrder|^m_Name$")
NEAR, BORDER = 0.8, 0.6


# ---------------------------------------------------------------- 공용
def load_edges():
    edges, missing = [], []
    for part in PARTS:
        d = C.load_json(C.p("data", "usage", "parts", part + ".json"))
        if d is None:
            missing.append(part)
            continue
        edges += d["edges"]
    return edges, missing


def addresses():
    """프리팹 guid → Addressable 주소 (AssetGroups 그룹 파일이 정답)."""
    out = {}
    rx = re.compile(r"m_GUID: ([0-9a-f]{32})\s+m_Address: ([^\n]+)")
    for f in glob.glob(os.path.join(C.unity_root(), "Assets", "AddressableAssetsData", "AssetGroups", "*.asset")):
        with open(f, encoding="utf-8", errors="replace") as fh:
            for m in rx.finditer(fh.read()):
                out[m.group(1)] = m.group(2).strip()
    return out


def scene_names():
    d = C.load_json(C.p("data", "scenes", "reachable.json")) or {"scenes": []}
    return {s["path"]: s["name"] for s in d["scenes"]}


def edge_target(e, by_guid):
    return e["template"] or by_guid.get(e["templateGuid"])


def template_path(slug):
    return C.p("data", "templates", slug + ".json")


def load_templates():
    idx = C.load_json(C.p("data", "template-index.json"))
    if not idx:
        raise SystemExit("data/template-index.json 없음 — templates.py --select 가 먼저 필요")
    return idx, {s: C.load_json(template_path(s)) for s in idx["templates"]}


# ---------------------------------------------------------------- T3 선정
def classify_prefab(rel, cls, inv_by_root, rule_cache):
    """(종류, 근거). 화면 루트로 분류된 기록 → 인스턴스 루트 다수결 → 규칙 → other."""
    root_id = "%s#%s" % (rel, TS.stem(rel))
    if root_id in cls:
        return cls[root_id][2]["kind"], "A2 분류(화면 루트)"
    roots = inv_by_root.get(rel, [])
    kinds = collections.Counter(cls[n][2]["kind"] for n in roots if n in cls)
    if kinds:
        k, n = sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        return k, "A2 분류(인스턴스 루트 %d개 중 %d)" % (sum(kinds.values()), n)
    if rel not in rule_cache:
        rule_cache[rel] = rule_kind_of_prefab(rel)
    return rule_cache[rel]


def rule_kind_of_prefab(rel):
    import classify_rules
    import parse_prefab
    try:
        nodes, _u = parse_prefab.build_nodes(rel, "t")
    except Exception as e:  # noqa: BLE001 — 깨진 프리팹도 목록에는 남긴다
        return "other", "파싱 실패: %s" % str(e)[:80]
    r = classify_rules.rule(nodes[0], [n["id"] for n in nodes if "scroll" in n["flags"]])
    return (r[0], "규칙: %s" % r[1]) if r else ("other", "규칙 결과 없음")


def select(edges, scope, cls=None, inv=None, addr=None, scenes=None, kind_fn=None):
    """순수 계산: (templates{path: rec}, index). 데이터 로드는 호출자."""
    by_guid = {g: r for r in scope for g in [TS.asset_guid(r)] if g}  # 경로 없이 GUID 만 있는 간선도 잡는다
    scope_set = set(scope)
    counts = {r: collections.Counter() for r in scope}
    users = collections.defaultdict(list)
    fwd = collections.defaultdict(set)  # 사용자 프리팹 → 사용한 프리팹
    rev = collections.defaultdict(set)  # 프리팹 → 사용자(프리팹·씬)
    for e in edges:
        t = edge_target(e, by_guid)
        if t not in scope_set:
            continue
        counts[t][e["kind"]] += 1
        users[t].append({"user": e["user"], "userType": e["userType"], "kind": e["kind"], "path": e["path"]})
        if e["userType"] in ("prefab", "scene") and e["kind"] in CONTAIN_KINDS + ("scene", "variant"):
            fwd[e["user"]].add(t)
            rev[t].add(e["user"])
    total = {r: sum(counts[r].values()) for r in scope}
    opened = {r for r in scope if counts[r]["code-ui"] or counts[r]["code-local"]}
    screens = sorted(r for r in scope if not TS.is_excluded(r) and (
        r in opened or (TS.suffix(r) in TS.SCREEN_SUFFIXES and not counts[r]["nested"] and not TS.is_common(r))))
    screen_set = set(screens)
    templates, unused, excluded, others = {}, [], [], []
    for r in scope:
        why = TS.is_excluded(r)
        if why:
            excluded.append({"path": r, "reason": why})
            continue
        if r in screen_set:
            continue
        if total[r] == 0:
            unused.append({"path": r, "name": TS.stem(r), "suffix": TS.suffix(r)})
        elif TS.is_common(r):
            templates[r] = "A"
        elif TS.suffix(r) in TS.TEMPLATE_SUFFIXES and total[r] >= 2:
            templates[r] = "B"
        else:
            others.append(r)

    def ancestors(r):
        seen, todo = set(), [r]
        while todo:
            x = todo.pop()
            for u in rev.get(x, ()):
                if u not in seen:
                    seen.add(u)
                    todo.append(u)
        return seen

    def descendants(r):
        seen, todo = set(), [r]
        while todo:
            x = todo.pop()
            for c in fwd.get(x, ()):
                if c not in seen:
                    seen.add(c)
                    todo.append(c)
        return seen

    slugs, taken = {}, {}
    for r in sorted(templates) + screens:
        s = C.slugify(TS.stem(r))
        if s in taken and taken[s] != r:
            s = "%s-%s" % (s, (TS.asset_guid(r) or C.short_hash(r))[:4])
        taken[s] = r
        slugs[r] = s
    scenes = scenes or {}
    addr = addr or {}
    recs = {}
    for r, rule in sorted(templates.items()):
        anc = ancestors(r)
        contains = sorted(slugs[c] for c in fwd.get(r, ()) if c in templates)
        kind, basis = kind_fn(r) if kind_fn else ("other", "규칙 결과 없음")
        g = TS.asset_guid(r)
        recs[r] = {"slug": slugs[r], "name": TS.stem(r), "path": r, "guid": g, "address": addr.get(g),
                   "rule": rule, "kind": kind, "kindBasis": basis, "tier": "composite" if contains else "atom",
                   "counts": dict(counts[r]), "usageTotal": total[r], "users": users[r],
                   "screens": sorted(slugs[a] for a in anc if a in screen_set),
                   "scenes": sorted({scenes.get(a, TS.stem(a)) for a in anc if a.endswith(".unity")}),
                   "contains": contains,
                   "variants": sorted({u["user"] for u in users[r] if u["kind"] == "variant"}),
                   "overrides": None, "lookalikes": None, "thumbnail": None}
    scr = [{"slug": slugs[r], "name": TS.stem(r), "path": r,
            "templates": sorted(slugs[c] for c in descendants(r) if c in templates)} for r in screens]
    index = {"updatedAt": C.now_iso(), "templates": sorted(x["slug"] for x in recs.values()), "screens": scr,
             "unused": unused, "excluded": excluded,
             "rules": {"A": "공통 폴더: " + ", ".join(TS.COMMON_DIRS) + " (사용처 1곳 이상)",
                       "B": "그 밖의 %s 접미사 프리팹 중 사용처 2곳 이상(모든 사용 종류 합산)" % "·".join(TS.TEMPLATE_SUFFIXES),
                       "screen": "UIType·localResourceUI 로 열리는 프리팹, 또는 View·Popup 접미사이면서 중첩 사용이 없는 것",
                       "unused": "화면·제외가 아니면서 사용처 0", "tier": "다른 템플릿을 포함(nested·field·code-loader·code-wrap)하면 composite",
                       "field": "설계 밖 확장: 직렬화 필드가 프리팹을 가리키는 사용(스크롤 아이템 등)"},
             "counts": {"scope": len(scope), "templates": len(recs), "ruleA": sum(1 for v in templates.values() if v == "A"),
                        "ruleB": sum(1 for v in templates.values() if v == "B"),
                        "atom": sum(1 for x in recs.values() if x["tier"] == "atom"),
                        "composite": sum(1 for x in recs.values() if x["tier"] == "composite"),
                        "screens": len(screens), "unused": len(unused), "excluded": len(excluded),
                        "otherUsed": len(others)}}
    return recs, index


def run_select():
    edges, missing = load_edges()
    if missing:
        print("경고: 사용처 part 없음 %s — 그 종류는 0 으로 셈" % missing)
    kinds = collections.Counter(e["kind"] for e in edges)
    C.write_json_atomic(C.p("data", "usage", "edges.json"),
                        {"updatedAt": C.now_iso(), "edges": edges, "counts": dict(kinds)}, "usage")
    cls, inv = C.all_classified(), C.all_inventory()
    inv_by_root = collections.defaultdict(list)
    for nid, (_b, _s, n) in inv.items():
        ns = n.get("nested")
        if ns and ns.get("prefab") and n["path"] == ns["instanceRoot"]:
            inv_by_root[ns["prefab"]].append(nid)
    cache = {}
    recs, index = select(edges, TS.ui_prefabs(), addr=addresses(), scenes=scene_names(),
                         kind_fn=lambda r: classify_prefab(r, cls, inv_by_root, cache))
    old = {os.path.basename(f)[:-5] for f in glob.glob(C.p("data", "templates", "*.json"))}
    for rec in recs.values():
        prev = C.load_json(template_path(rec["slug"]))
        if prev:  # assemble 결과는 유지
            for k in ("overrides", "lookalikes", "thumbnail"):
                rec[k] = prev.get(k)
        C.write_json_atomic(template_path(rec["slug"]), rec, "template")
    for s in old - set(index["templates"]):
        os.remove(template_path(s))
    C.write_json_atomic(C.p("data", "template-index.json"), index, "template-index")
    c = index["counts"]
    print("간선 %d %s" % (len(edges), dict(kinds)))
    print("범위 %d → 템플릿 %d (A %d · B %d, atom %d · composite %d), 화면 %d, unused %d, 제외 %d, 그 밖의 사용 프리팹 %d" % (
        c["scope"], c["templates"], c["ruleA"], c["ruleB"], c["atom"], c["composite"], c["screens"], c["unused"],
        c["excluded"], c["otherUsed"]))
    return 0


# ---------------------------------------------------------------- T4 오버라이드
def override_stats(edges_of):
    """edges_of: 템플릿 경로 → 간선 목록. → {경로: 통계}"""
    out = {}
    for t, es in edges_of.items():
        inst = [e for e in es if e["kind"] in INSTANCE_KINDS]
        by_cat, props, modified, placed, styled = collections.Counter(), collections.Counter(), 0, 0, 0
        for e in inst:
            cats = set()
            for pr in e["overrides"]:
                hit = [c for c, rx in OVR_CATS if rx.search(pr)]
                if hit:
                    cats.update(hit)
                    props[pr] += 1
                elif not PLACEMENT_RE.search(pr):
                    props[pr] += 1
            by_cat.update(cats)
            modified += bool(cats)
            styled += bool(cats & {"sprite", "color"})
            placed += any(PLACEMENT_RE.search(pr) for pr in e["overrides"])
        out[t] = {"instances": len(inst), "asIs": len(inst) - modified, "modified": modified,
                  "modifiedRate": round(modified / len(inst), 3) if inst else 0.0, "placed": placed,
                  "styled": styled, "styledRate": round(styled / len(inst), 3) if inst else 0.0,
                  "byCategory": {c: by_cat[c] for c, _rx in OVR_CATS}, "topProps": props.most_common(8)}
    return out


def run_overrides():
    idx, temps = load_templates()
    edges = C.load_json(C.p("data", "usage", "edges.json"))["edges"]
    paths = {t["path"]: s for s, t in temps.items()}
    edges_of = {p_: [] for p_ in paths}
    for e in edges:
        if e["template"] in edges_of:
            edges_of[e["template"]].append(e)
    stats = override_stats(edges_of)
    res = {paths[p_]: v for p_, v in stats.items()}
    used = [v for v in res.values() if v["instances"]]
    C.write_json_atomic(C.p("data", "usage", "overrides.json"),
                        {"updatedAt": C.now_iso(), "what": "overrides", "templates": res,
                         "stats": {"templates": len(res), "withInstances": len(used),
                                   "meanStyledRate": round(sum(v["styledRate"] for v in used) / len(used), 3) if used else 0,
                                   "meanModifiedRate": round(sum(v["modifiedRate"] for v in used) / len(used), 3) if used else 0}},
                        "template-ext")
    print("오버라이드 요약: 템플릿 %d (인스턴스 있는 것 %d), 평균 변형 사용 비율 %.0f%% (스프라이트·색 변형 %.0f%%)" % (
        len(res), len(used), 100 * (sum(v["modifiedRate"] for v in used) / len(used) if used else 0),
        100 * (sum(v["styledRate"] for v in used) / len(used) if used else 0)))
    return 0


# ---------------------------------------------------------------- T5 유사품
def node_kind(n, rule_fn):
    r = rule_fn(n)
    return r[0] if r else "?"


def sprite_name(n):
    sp = ((n.get("graphic") or {}).get("sprite") or {}).get("name") or ""
    return sp.split("__", 1)[0]


def signature(root, kids_of, kind_of):
    """(루트 종류, 루트 스프라이트 + 깊이 1·2 자식의 (종류, 스프라이트) 다중집합)"""
    items = collections.Counter()
    if sprite_name(root):
        items[("root", sprite_name(root))] += 1
    for c in kids_of.get(root["id"], []):
        items[(kind_of(c), sprite_name(c))] += 1
        for g in kids_of.get(c["id"], []):
            items[(kind_of(g), sprite_name(g))] += 1
    return kind_of(root), items


def jaccard(a, b):
    inter = sum((a & b).values())
    union = sum((a | b).values())
    return inter / union if union else 0.0


def match(tsig, cands, min_items=2):
    """tsig: (kind, Counter). cands: [(id, (kind, Counter))]. → [(id, score, label)]"""
    k, items = tsig
    n = sum(items.values())
    informative = sum(v for (ck, sp), v in items.items() if sp)
    if n < min_items or not informative:
        return []  # 스프라이트 없는 빈 컨테이너 서명은 무엇과도 맞아 버린다
    out = []
    for cid, (ck, citems) in cands:
        if ck != k:
            continue
        m = sum(citems.values())
        if not m or min(n, m) / max(n, m) < BORDER:
            continue
        s = jaccard(items, citems)
        shared = sum(v for (ck2, sp), v in (items & citems).items() if sp)
        if s >= BORDER and shared >= min(2, informative):
            out.append((cid, round(s, 3), "exact" if citems == items else ("near" if s >= NEAR else "borderline")))
    return sorted(out, key=lambda x: (-x[1], x[0]))


def similar_size(a, b, factor=2.0):
    """루트 크기가 factor 배 안쪽이면 True (크기를 모르면 True)."""
    ra, rb = a.get("rect") or {}, b.get("rect") or {}
    for k in ("w", "h"):
        x, y = ra.get(k) or 0, rb.get(k) or 0
        if x > 0 and y > 0 and max(x, y) / min(x, y) > factor:
            return False
    return True


def run_lookalikes():
    import classify_rules
    import parse_prefab
    idx, temps = load_templates()
    scroll = []
    rule_fn = lambda n: classify_rules.rule(n, scroll)  # noqa: E731
    kind_cache = {}

    def kind_of(n):
        if n["id"] not in kind_cache:
            kind_cache[n["id"]] = node_kind(n, rule_fn)
        return kind_cache[n["id"]]

    inv = C.all_inventory()
    kids, by_kind = collections.defaultdict(list), collections.defaultdict(list)
    for _nid, (_b, _s, n) in inv.items():
        if n["parent"]:
            kids[n["parent"]].append(n)
    temp_paths = {t["path"] for t in temps.values()}
    for nid, (_b, scr, n) in inv.items():
        if n.get("nested") or not kids.get(nid) or nid.split("#", 1)[0] in temp_paths or n["depth"] == 0:
            continue  # 템플릿 인스턴스·잎·템플릿 자신·화면 루트는 후보가 아니다
        k, items = signature(n, kids, kind_of)
        by_kind[k].append((nid, (k, items)))
    res, n_exact, n_near, n_border = {}, 0, 0, 0
    for slug, t in sorted(temps.items()):
        try:
            nodes, _u = parse_prefab.build_nodes(t["path"], "t")
        except Exception as e:  # noqa: BLE001
            res[slug] = {"error": str(e)[:120], "items": []}
            continue
        tk = collections.defaultdict(list)
        for n in nodes:
            if n["parent"]:
                tk[n["parent"]].append(n)
        tsig = signature(nodes[0], tk, kind_of)
        hits = [h for h in match(tsig, by_kind.get(tsig[0], [])) if similar_size(nodes[0], inv[h[0]][2])]
        items = [{"node": cid, "screen": inv[cid][1], "batch": inv[cid][0], "score": s, "match": lab} for cid, s, lab in hits[:50]]
        n_exact += sum(1 for x in items if x["match"] == "exact")
        n_near += sum(1 for x in items if x["match"] == "near")
        n_border += sum(1 for x in items if x["match"] == "borderline")
        res[slug] = {"signatureSize": sum(tsig[1].values()), "rootKind": tsig[0], "total": len(hits), "items": items}
    C.write_json_atomic(C.p("data", "usage", "lookalikes.json"),
                        {"updatedAt": C.now_iso(), "what": "lookalikes", "templates": res,
                         "stats": {"exact": n_exact, "near": n_near, "borderline": n_border,
                                   "templatesWithHits": sum(1 for v in res.values() if v.get("items")),
                                   "candidates": sum(len(v) for v in by_kind.values())}}, "template-ext")
    print("유사품: 후보 하위 트리 %d → exact %d · near %d · borderline %d (템플릿 %d개에 있음)" % (
        sum(len(v) for v in by_kind.values()), n_exact, n_near, n_border, sum(1 for v in res.values() if v.get("items"))))
    return 0


# ---------------------------------------------------------------- assemble
def run_assemble():
    idx, temps = load_templates()
    ov = (C.load_json(C.p("data", "usage", "overrides.json")) or {"templates": {}})["templates"]
    lk = (C.load_json(C.p("data", "usage", "lookalikes.json")) or {"templates": {}})["templates"]
    n_th = 0
    for slug, t in temps.items():
        t["overrides"] = ov.get(slug)
        t["lookalikes"] = (lk.get(slug) or {}).get("items") if slug in lk else None
        png = C.p("previews", "templates", slug + ".png")
        t["thumbnail"] = "previews/templates/%s.png" % slug if os.path.exists(png) else None
        n_th += bool(t["thumbnail"])
        C.write_json_atomic(template_path(slug), t, "template")
    print("합침: 템플릿 %d, 오버라이드 %d, 유사품 %d, 썸네일 %d" % (len(temps), sum(1 for s in temps if s in ov),
                                                         sum(1 for s in temps if s in lk), n_th))
    return 0


# ---------------------------------------------------------------- CLI
def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for x in ("select", "overrides", "lookalikes", "assemble", "all", "selftest"):
        ap.add_argument("--" + x, action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    steps = [("select", run_select), ("overrides", run_overrides), ("lookalikes", run_lookalikes),
             ("assemble", run_assemble)]
    ran = False
    for name, fn in steps:
        if a.all or getattr(a, name):
            ran = True
            if fn():
                return 1
    if not ran:
        ap.print_help()
        return 2
    return 0


def selftest():
    with TS.test_scope():
        return _selftest()


def _selftest():
    P = "Assets/Game/UI/"
    common = "Assets/Game/UI/Common/Button_Yellow.prefab"
    scope = [common, P + "A/ItemUnit.prefab", P + "A/OnceUnit.prefab", P + "A/HomeView.prefab",
             P + "A/LonelyPanel.prefab", P + "A/ListPopup.prefab", "Assets/Game/UI/Vendor/M.prefab"]

    def E(t, kind, user, ut="prefab"):
        return {"template": t, "templateGuid": None, "kind": kind, "user": user, "userType": ut, "path": "x", "overrides": []}
    edges = [E(common, "nested", P + "A/ItemUnit.prefab"), E(P + "A/ItemUnit.prefab", "nested", P + "A/HomeView.prefab"),
             E(P + "A/ItemUnit.prefab", "code-loader", P + "A/ListPopup.prefab"),
             E(P + "A/OnceUnit.prefab", "nested", P + "A/HomeView.prefab"),
             E(P + "A/HomeView.prefab", "code-ui", "Assets/X/HomeController.cs", "code"),
             E(P + "A/HomeView.prefab", "scene", "Assets/S/400_Town.unity", "scene")]
    recs, idx = select(edges, scope, kind_fn=lambda r: ("button", "t"), scenes={"Assets/S/400_Town.unity": "400_Town"})
    assert set(recs) == {common, P + "A/ItemUnit.prefab"}, sorted(recs)
    assert recs[common]["rule"] == "A" and recs[common]["tier"] == "atom"
    it = recs[P + "A/ItemUnit.prefab"]
    assert it["rule"] == "B" and it["tier"] == "composite" and it["contains"] == ["button-yellow"], it
    assert it["screens"] == ["homeview", "listpopup"] and it["scenes"] == ["400_Town"], it
    assert [s["slug"] for s in idx["screens"]] == ["homeview", "listpopup"], idx["screens"]
    assert [u["name"] for u in idx["unused"]] == ["LonelyPanel"] and len(idx["excluded"]) == 1
    assert idx["counts"]["otherUsed"] == 1  # OnceUnit: 사용처 1곳
    hv = [s for s in idx["screens"] if s["slug"] == "homeview"][0]
    assert hv["templates"] == ["button-yellow", "itemunit"], hv
    st = override_stats({"t": [dict(E("t", "nested", "u"), overrides=["m_Sprite", "m_AnchoredPosition.x"]),
                               dict(E("t", "nested", "u"), overrides=["m_AnchoredPosition.x", "m_Name"]),
                               dict(E("t", "scene", "s", "scene"), overrides=["m_Color.a"]),
                               E("t", "code-loader", "c")]})["t"]
    assert st["instances"] == 3 and st["modified"] == 2 and st["asIs"] == 1 and st["placed"] == 2, st
    assert st["byCategory"]["sprite"] == 1 and st["byCategory"]["color"] == 1 and st["styled"] == 2, st
    Cn = collections.Counter
    t = ("button", Cn({("textstyle", ""): 1, ("icon", "Ico"): 1, ("decor", "Bg"): 1}))
    cands = [("same", ("button", Cn(t[1]))), ("other-kind", ("decor", Cn(t[1]))),
             ("near", ("button", Cn({("textstyle", ""): 1, ("icon", "Ico"): 1, ("decor", "Bg"): 1, ("decor", "Line"): 1}))),
             ("far", ("button", Cn({("textstyle", ""): 1})))]
    got = {cid: lab for cid, _s, lab in match(t, cands)}
    assert got == {"same": "exact", "near": "borderline"}, got  # 교집합 3 / 합집합 4 = 0.75
    assert match(("button", Cn({("x", ""): 1})), cands) == []  # 자식 1개짜리 템플릿은 비교하지 않음
    assert match(("decor", Cn({("decor", ""): 3})), [("c", ("decor", Cn({("decor", ""): 3})))]) == []  # 스프라이트 없는 서명
    assert similar_size({"rect": {"w": 100, "h": 50}}, {"rect": {"w": 150, "h": 60}})
    assert not similar_size({"rect": {"w": 100, "h": 50}}, {"rect": {"w": 1920, "h": 1080}})
    assert similar_size({"rect": None}, {"rect": {"w": 1, "h": 1}})
    nodes = {"r": {"id": "r", "graphic": None}, "a": {"id": "a", "graphic": {"sprite": {"name": "Bg__HomeView"}}},
             "b": {"id": "b", "graphic": None}}
    k, items = signature(nodes["r"], {"r": [nodes["a"]], "a": [nodes["b"]]}, lambda n: "decor")
    assert k == "decor" and items == Cn({("decor", "Bg"): 1, ("decor", ""): 1}), items
    print("templates.py selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
