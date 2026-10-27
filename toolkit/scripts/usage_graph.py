"""T2a·T2c 사용 그래프: 프리팹·씬 YAML 의 PrefabInstance 에서 범위 UI 프리팹 사용 간선을 뽑는다.
Unity 프로젝트는 읽기만 한다.

사용:
  python scripts/usage_graph.py --prefabs     Assets/ 의 모든 프리팹 → data/usage/parts/prefab.json (nested·variant·field)
                                              field = MonoBehaviour 직렬화 필드(또는 중첩 수정값 objectReference)가 프리팹 에셋을 가리킴
                                              (설계 4절 밖 확장: 스크롤 아이템 등 '필드로만 참조되는' 프리팹을 unused 로 잘못 세지 않으려고)
  python scripts/usage_graph.py --scenes      data/scenes/reachable.json 의 씬 → data/usage/parts/scene.json (scene)
                                              + 씬에 직접 둔 Canvas 계층 → data/scenes/ui/<씬 슬러그>.json
  python scripts/usage_graph.py --count <Assets/...prefab>   그 프리팹의 사용 간선 수와 사용자 목록
  python scripts/usage_graph.py --selftest
간선: {template, templateGuid, kind, user, userType, path, overrides:[정규화 propertyPath]}
"""
import argparse
import os
import re
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import parse_prefab as PP  # noqa: E402
import template_scope as TS  # noqa: E402

SOURCE_RE = re.compile(r"m_SourcePrefab: \{fileID: \d+, guid: ([0-9a-f]{32})")
OBJREF_RE = re.compile(r"guid: ([0-9a-f]{32}),\s+type: [23]\}")
KEY_RE = re.compile(r"^\s*(?:- )?([A-Za-z_][\w.]*):")
GO_NAME_RE = re.compile(r"^\s*m_Name: (.*)$", re.M)
GO_REF_RE = re.compile(r"m_GameObject: \{fileID: (-?\d+)\}")
SCRIPT_RE = re.compile(r"m_Script: \{fileID: -?\d+, guid: ([0-9a-f]{32})")
COVERED_SCRIPTS = ("ResourcesLoader", "WrapContent")


# ---------------------------------------------------------------- 문서 단위 파싱
def split_docs(text):
    """[(cls, fileID, stripped, body_text)] — 헤더로 나눈 원문 조각."""
    heads = list(PP.HEADER_RE.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((int(m.group(1)), int(m.group(2)), bool(m.group(3)), text[m.end():end]))
    return out


def parse_body(body_text):
    d = yaml.load(PP.unity_yaml_text(body_text), Loader=PP.YAML_LOADER) or {}
    (_k, b), = d.items()
    return b or {}


def instances_from_text(text, wanted):
    """wanted(guid 집합)에 속하는 원본을 가진 PrefabInstance → [{inst, guid, parent, mods, extra}]"""
    out = []
    for cls, fid, stripped, body in split_docs(text):
        if cls != 1001 or stripped:
            continue
        m = SOURCE_RE.search(body)
        if not m or m.group(1) not in wanted:
            continue
        b = parse_body(body)
        mod = b.get("m_Modification") or {}
        extra = []
        for key, label in (("m_RemovedComponents", "(removed Component)"), ("m_RemovedGameObjects", "(removed GameObject)"),
                           ("m_AddedGameObjects", "(added GameObject)"), ("m_AddedComponents", "(added Component)")):
            if mod.get(key) or b.get(key):
                extra.append(label)
        out.append({"inst": fid, "guid": m.group(1), "parent": PP.ref_id(mod.get("m_TransformParent")),
                    "mods": mod.get("m_Modifications") or [], "extra": extra})
    return out


def field_refs_from_text(text, wanted):
    """MonoBehaviour 필드·중첩 수정값의 objectReference 가 wanted 프리팹을 가리키는 곳 → [(guid, 위치)]"""
    docs = split_docs(text)
    names = {}
    for cls, fid, stripped, body in docs:
        if cls == 1 and not stripped:
            m = GO_NAME_RE.search(body)
            names[fid] = m.group(1).strip().strip("'\"") if m else "?"
    out = []
    for cls, fid, stripped, body in docs:
        if stripped or cls not in (114, 1001) or not any(g in wanted for g in OBJREF_RE.findall(body)):
            continue
        lines = body.split("\n")
        sm = SCRIPT_RE.search(body)
        if cls == 114 and sm and TS.stem(PP.INDEX.get(sm.group(1)) or "") in COVERED_SCRIPTS:
            continue  # code-loader·code-wrap 으로 이미 센다
        if cls == 114:
            m = GO_REF_RE.search(body)
            owner = names.get(int(m.group(1)), "?") if m else "?"
        for m in OBJREF_RE.finditer(body):  # 긴 참조는 'type: 3}' 이 다음 줄로 넘어간다
            g = m.group(1)
            i = body.count("\n", 0, m.start())
            line = lines[i]
            if g in wanted:
                if cls == 114:
                    if "m_Script:" in line:
                        continue
                    key = next((km.group(1) for j in range(i, -1, -1) for km in [KEY_RE.match(lines[j])]
                                if km and not lines[j].lstrip().startswith("- {")), "?")
                    out.append((g, "%s.%s" % (owner, key)))
                elif "objectReference:" in line:  # 중첩 인스턴스의 필드 수정값
                    prop = next((ln.split("propertyPath:", 1)[1].strip() for ln in reversed(lines[:i]) if "propertyPath:" in ln), "?")
                    out.append((g, "(수정값) %s" % prop))
    return out


def get_prop(body, prop):
    """수정 propertyPath 가 가리키는 원본 값 (없으면 _MISSING)."""
    cur = body
    for key in re.sub(r"\.Array\.data\[(\d+)\]", r".#\1", prop).split("."):
        if key.startswith("#") and isinstance(cur, list) and int(key[1:]) < len(cur):
            cur = cur[int(key[1:])]
        elif isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return _MISSING
    return cur


_MISSING = object()


def same_value(old, mod):
    """수정값이 원본 값과 같은가 (Unity 는 인스턴스 루트의 앵커·크기·위치 등을 같아도 기록한다)."""
    if old is _MISSING:
        return False
    ref = mod.get("objectReference") or {}
    if PP.ref_id(ref) or PP.ref_guid(ref) or isinstance(old, dict):
        return isinstance(old, dict) and PP.ref_id(old) == PP.ref_id(ref) and PP.ref_guid(old) == PP.ref_guid(ref)
    v = mod.get("value")
    try:
        return abs(float(old) - float(v)) < 1e-4
    except (TypeError, ValueError):
        return str(old if old is not None else "") == str(v if v is not None else "")


def overrides(inst, src_objs=None):
    """수정 속성 이름(정규화). src_objs(원본을 펼친 객체)를 주면 원본과 값이 같은 수정은 뺀다."""
    props = set()
    for m in inst["mods"]:
        prop = m.get("propertyPath", "")
        if src_objs is not None:
            o = src_objs.get(PP.ref_id(m.get("target")))
            if o is not None and same_value(get_prop(o["body"], prop), m):
                continue
        props.add(TS.norm_prop(prop))
    return sorted((props - {""}) | set(inst["extra"]))


def source_objs(src_rel):
    try:
        return PP.expand(src_rel).objs if src_rel else None
    except (OSError, ValueError, yaml.YAMLError, RecursionError):
        return None


def instance_name(inst, src_rel):
    """인스턴스 루트 이름: 루트 GameObject 의 m_Name 수정값, 없으면 원본 파일명."""
    root_go = None
    try:
        sub = PP.expand(src_rel)
        for sid, o in sub.objs.items():
            if o["cls"] in (224, 4) and PP.ref_id(o["body"].get("m_Father")) == 0:
                root_go = PP.ref_id(o["body"].get("m_GameObject"))
                break
    except (OSError, ValueError, yaml.YAMLError):
        pass
    for m in inst["mods"]:
        if m.get("propertyPath") == "m_Name" and (root_go is None or PP.ref_id(m.get("target")) == root_go):
            return str(m.get("value"))
    return TS.stem(src_rel)


def name_chain(objs, tf):
    """Transform id → 'A/B/C' (펼친 객체 기준, 끊기면 '?' 로 시작)."""
    names, seen = [], set()
    while tf and tf not in seen:
        seen.add(tf)
        o = objs.get(tf)
        if not o:
            names.append("?")
            break
        go = objs.get(PP.ref_id(o["body"].get("m_GameObject")))
        names.append(str((go or {}).get("body", {}).get("m_Name", "?")))
        tf = PP.ref_id(o["body"].get("m_Father"))
    return "/".join(reversed(names))


def user_path(user_rel, parent, name):
    if not parent:
        return name
    try:
        ex = PP.expand(user_rel)
        return name_chain(ex.objs, parent) + "/" + name
    except (OSError, ValueError, yaml.YAMLError, RecursionError):
        return "?/" + name


def edges_for_file(user_rel, text, wanted, user_type):
    out, unresolved = [], []
    for inst in instances_from_text(text, wanted):
        src = PP.INDEX.get(inst["guid"])
        kind = "scene" if user_type == "scene" else ("variant" if inst["parent"] == 0 else "nested")
        name = instance_name(inst, src)
        path = name if kind == "variant" else user_path(user_rel, inst["parent"], name)
        if path.startswith("?"):
            unresolved.append({"ref": "%s#%s" % (user_rel, inst["inst"]), "reason": "path-unresolved",
                               "detail": "부모 Transform 경로를 못 구함 (%s)" % src})
        out.append({"template": src, "templateGuid": inst["guid"], "kind": kind, "user": user_rel,
                    "userType": user_type, "path": path, "overrides": overrides(inst, source_objs(src))})
    for g, where in field_refs_from_text(text, wanted):
        if PP.INDEX.get(g) != user_rel:  # 자기 자신을 가리키는 필드는 사용이 아님
            out.append({"template": PP.INDEX.get(g), "templateGuid": g, "kind": "field", "user": user_rel,
                        "userType": user_type, "path": where, "overrides": []})
    return out, unresolved


def ui_guids():
    out = {}
    for rel in TS.ui_prefabs():
        g = TS.asset_guid(rel)
        if g:
            out[g] = rel
    return out


def read(rel):
    with open(os.path.join(C.unity_root(), rel), "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------- T2a
def all_prefabs():
    idx = C.load_json(C.p("cache", "guid-index.json"))["map"]
    return sorted(v for v in idx.values() if v.startswith("Assets/") and v.endswith(".prefab"))


def run_prefabs():
    t = time.time()
    wanted = ui_guids()
    edges, unresolved = [], []
    users = all_prefabs()
    for i, rel in enumerate(users):
        try:
            text = read(rel)
        except OSError as e:
            unresolved.append({"ref": rel, "reason": "read-failed", "detail": str(e)})
            continue
        if not any(g in wanted for g in OBJREF_RE.findall(text)):
            continue
        try:
            e, u = edges_for_file(rel, text, wanted, "prefab")
        except (ValueError, yaml.YAMLError) as ex:
            unresolved.append({"ref": rel, "reason": "parse-failed", "detail": str(ex)[:200]})
            continue
        edges += e
        unresolved += u
        if i % 1000 == 0:
            print("  %d/%d (%.0fs)" % (i, len(users), time.time() - t), file=sys.stderr)
    out = {"source": "prefab", "updatedAt": C.now_iso(), "edges": edges, "unresolved": unresolved}
    C.write_json_atomic(C.p("data", "usage", "parts", "prefab.json"), out)
    kinds = {}
    for e in edges:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print("프리팹 %d개 훑음 → 간선 %d %s, 미해결 %d (%.0fs)" % (len(users), len(edges), kinds, len(unresolved), time.time() - t))
    return 0


# ---------------------------------------------------------------- T2c
def script_name(guid):
    path = PP.INDEX.get(guid) if guid else None
    return os.path.splitext(os.path.basename(path))[0] if path else ("MissingScript" if not guid else "Script:" + guid[:8])


def scene_ui(scene_rel, text):
    """씬에 직접 둔(프리팹이 아닌) Canvas 루트별 노드. [{root, nodes:[{path,name,components,nested}]}]"""
    docs = {}
    insts = {}
    for cls, fid, stripped, body in split_docs(text):
        if cls == 1001 and not stripped:
            m = SOURCE_RE.search(body)
            insts[fid] = PP.INDEX.get(m.group(1)) if m else None
        elif cls in (1, 4, 224, 223, 114) and not stripped:
            docs[fid] = (cls, body)
        elif stripped and cls in (4, 224):
            m = re.search(r"m_PrefabInstance: \{fileID: (-?\d+)\}", body)
            docs[fid] = (cls, None, int(m.group(1)) if m else 0)
    canvas_go = set()
    parsed = {}

    def P(fid):
        if fid not in parsed:
            parsed[fid] = parse_body(docs[fid][1])
        return parsed[fid]

    for fid, d in docs.items():
        if d[0] == 223 and d[1] is not None:
            m = re.search(r"m_GameObject: \{fileID: (-?\d+)\}", d[1])
            if m:
                canvas_go.add(int(m.group(1)))
    go_tf = {}
    for fid, d in docs.items():
        if d[0] in (4, 224) and d[1] is not None:
            m = re.search(r"m_GameObject: \{fileID: (-?\d+)\}", d[1])
            if m:
                go_tf[int(m.group(1))] = fid
    tf_go = {v: k for k, v in go_tf.items()}

    def father(tf):
        m = re.search(r"m_Father: \{fileID: (-?\d+)\}", docs[tf][1] or "")
        return int(m.group(1)) if m else 0

    def has_canvas_ancestor(tf):
        f = father(tf)
        while f and f in docs and docs[f][1] is not None:
            if tf_go.get(f) in canvas_go:
                return True
            f = father(f)
        return False

    roots = [go_tf[g] for g in canvas_go if g in go_tf and not has_canvas_ancestor(go_tf[g])]
    out = []
    for root in sorted(roots):
        nodes = []

        def walk(tf, parent_path, depth):
            d = docs.get(tf)
            if d is None:
                return
            if d[1] is None:  # 중첩 프리팹 인스턴스의 루트
                src = insts.get(d[2])
                name = TS.stem(src) if src else "?"
                path = parent_path + "/" + name
                nodes.append({"path": path, "name": name, "components": [], "nested": src})
                return
            go = tf_go.get(tf)
            gb = P(go) if go in docs else {}
            name = str(gb.get("m_Name", "?"))
            path = name if parent_path is None else parent_path + "/" + name
            comps = []
            for c in gb.get("m_Component") or []:
                cid = PP.ref_id((c or {}).get("component"))
                if cid in docs and docs[cid][1] is not None:
                    if docs[cid][0] == 114:
                        comps.append(script_name(PP.ref_guid(P(cid).get("m_Script"))))
                    else:
                        comps.append(PP.CLASS_NAMES.get(docs[cid][0], "class%d" % docs[cid][0]))
            nodes.append({"path": path, "name": name, "components": comps, "nested": None})
            if depth > 40:
                return
            for ch in P(tf).get("m_Children") or []:
                walk(PP.ref_id(ch), path, depth + 1)

        walk(root, None, 0)
        out.append({"root": nodes[0]["path"] if nodes else "?", "nodes": nodes})
    return out


def run_scenes():
    t = time.time()
    reach = C.load_json(C.p("data", "scenes", "reachable.json"))
    if not reach:
        print("data/scenes/reachable.json 없음 — scene_enum.py --run 이 먼저 필요")
        return 1
    wanted = ui_guids()
    edges, unresolved, made = [], [], 0
    for s in reach["scenes"]:
        rel = s["path"]
        try:
            text = read(rel)
        except OSError as e:
            unresolved.append({"ref": rel, "reason": "read-failed", "detail": str(e)})
            continue
        e, u = edges_for_file(rel, text, wanted, "scene")
        edges += e
        unresolved += u
        canv = scene_ui(rel, text)
        C.write_json_atomic(C.p("data", "scenes", "ui", C.slugify(s["name"]) + ".json"),
                            {"scene": s["name"], "path": rel, "updatedAt": C.now_iso(), "canvases": canv})
        made += 1
        print("  %s: 간선 %d, 캔버스 %d" % (s["name"], len(e), len(canv)), file=sys.stderr)
    C.write_json_atomic(C.p("data", "usage", "parts", "scene.json"),
                        {"source": "scene", "updatedAt": C.now_iso(), "edges": edges, "unresolved": unresolved})
    print("씬 %d개 → scene 간선 %d, 씬 UI 파일 %d, 미해결 %d (%.0fs)" % (
        len(reach["scenes"]), len(edges), made, len(unresolved), time.time() - t))
    return 0


def count(rel):
    g = TS.asset_guid(rel)
    n = 0
    for part in ("prefab", "scene", "code"):
        d = C.load_json(C.p("data", "usage", "parts", part + ".json")) or {"edges": []}
        hits = [e for e in d["edges"] if e["templateGuid"] == g or e["template"] == rel]
        n += len(hits)
        users = sorted({e["user"] for e in hits})
        print("%s: 간선 %d, 사용자 %d" % (part, len(hits), len(users)))
        for u in users[:30]:
            print("   " + u)
    print("합계 %d" % n)
    return 0


# ---------------------------------------------------------------- CLI
def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prefabs", action="store_true")
    ap.add_argument("--scenes", action="store_true")
    ap.add_argument("--count")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.prefabs:
        return run_prefabs()
    if a.scenes:
        return run_scenes()
    if a.count:
        return count(a.count.replace("\\", "/"))
    ap.print_help()
    return 2


SYN = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &10
GameObject:
  m_Component:
  - component: {fileID: 11}
  - component: {fileID: 12}
  m_Name: Root
--- !u!224 &11
RectTransform:
  m_GameObject: {fileID: 10}
  m_Children:
  - {fileID: 30}
  m_Father: {fileID: 0}
--- !u!223 &12
Canvas:
  m_GameObject: {fileID: 10}
--- !u!1001 &20
PrefabInstance:
  m_Modification:
    serializedVersion: 3
    m_TransformParent: {fileID: 11}
    m_Modifications:
    - target: {fileID: 1, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
      propertyPath: m_Sprite
      value:
      objectReference: {fileID: 213, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 3}
    - target: {fileID: 2, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
      propertyPath: m_Children.Array.data[0]
      value:
      objectReference: {fileID: 0}
    m_RemovedComponents: []
  m_SourcePrefab: {fileID: 100100000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
--- !u!224 &30 stripped
RectTransform:
  m_CorrespondingSourceObject: {fileID: 5, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
  m_PrefabInstance: {fileID: 20}
--- !u!1001 &40
PrefabInstance:
  m_Modification:
    m_TransformParent: {fileID: 0}
    m_Modifications: []
  m_SourcePrefab: {fileID: 100100000, guid: cccccccccccccccccccccccccccccccc, type: 3}
"""


FIELD_SYN = """--- !u!114 &50
MonoBehaviour:
  m_GameObject: {fileID: 10}
  m_Script: {fileID: 11500000, guid: eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee, type: 3}
  itemPrefab: {fileID: 100100000, guid: dddddddddddddddddddddddddddddddd, type: 3}
  list:
  - {fileID: 100100000, guid: dddddddddddddddddddddddddddddddd, type: 3}
  wrappedPrefab: {fileID: 4066569286284644452, guid: dddddddddddddddddddddddddddddddd,
    type: 3}
"""


def selftest():
    insts = instances_from_text(SYN, {"a" * 32, "c" * 32})
    assert len(insts) == 2, insts
    a = [x for x in insts if x["guid"] == "a" * 32][0]
    assert a["parent"] == 11 and overrides(a) == ["m_Children[]", "m_Sprite"], overrides(a)
    assert [x for x in insts if x["guid"] == "c" * 32][0]["parent"] == 0  # → variant
    # 원본과 같은 값의 수정은 빼고(스프라이트 동일), 다른 값만 남긴다
    same = {1: {"cls": 114, "body": {"m_Sprite": {"fileID": 213, "guid": "b" * 32}}}}
    assert overrides(a, same) == ["m_Children[]"], overrides(a, same)
    diff = {1: {"cls": 114, "body": {"m_Sprite": {"fileID": 999, "guid": "b" * 32}}}}
    assert overrides(a, diff) == ["m_Children[]", "m_Sprite"]
    assert same_value(0.5, {"value": "0.50001"}) and not same_value(1, {"value": "2"})
    assert same_value("Btn", {"value": "Btn"}) and not same_value(_MISSING, {"value": "x"})
    assert len(instances_from_text(SYN, {"a" * 32})) == 1
    fr = field_refs_from_text(SYN + FIELD_SYN, {"a" * 32, "d" * 32})
    assert ("d" * 32, "Root.itemPrefab") in fr and ("d" * 32, "Root.list") in fr, fr
    assert ("d" * 32, "Root.wrappedPrefab") in fr, fr  # 줄바꿈된 참조
    assert ("a" * 32, "(수정값) m_Sprite") not in fr and not [x for x in fr if x[0] == "a" * 32 and "Source" in x[1]], fr
    canv = scene_ui("x.unity", SYN)
    assert len(canv) == 1 and canv[0]["root"] == "Root", canv
    assert [n["components"] for n in canv[0]["nodes"]][0] == ["RectTransform", "Canvas"], canv
    assert len(canv[0]["nodes"]) == 2 and canv[0]["nodes"][1]["path"].startswith("Root/"), canv
    # 실제: 다른 UI 프리팹을 중첩하는 프리팹 하나에서 그 템플릿으로 가는 간선이 나와야 함
    wanted = ui_guids()
    path_of = {TS.asset_guid(r): r for r in TS.ui_prefabs()}
    pick = next(((path_of[g], r) for r in TS.ui_prefabs()[::-1]
                 for g in re.findall(r"m_SourcePrefab: \{fileID: \d+, guid: ([0-9a-f]{32})", read(r))
                 if g in path_of and path_of[g] != r), None)
    assert pick, "다른 UI 프리팹을 중첩하는 UI 프리팹이 없음"
    by, user = [pick[0]], pick[1]
    g = TS.asset_guid(by[0])
    e, _u = edges_for_file(user, read(user), wanted, "prefab")
    hit = [x for x in e if x["templateGuid"] == g]
    assert hit and hit[0]["kind"] == "nested" and hit[0]["template"] == by[0], hit[:1]
    assert not hit[0]["path"].startswith("?"), hit[0]
    print("  실제 표본: %s → %s (%s)" % (user.rsplit("/", 1)[-1], hit[0]["path"], ", ".join(hit[0]["overrides"][:4])))
    print("usage_graph.py selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
