"""A3 통합 분석: 대상 노드를 시그니처(스프라이트, 크기 단계, 색, 폰트)로 기존 그룹에 배정하고,
맞는 그룹이 없는 것만 새 그룹(종류 + 시그니처 짧은 해시)으로 묶는다. 그룹 ID 는 재사용하지 않는다.

사용 (조각 = state.py show 가 알려준 A3 조각):
  python scripts/group.py run --batch b1 --chunk <조각>
      이 배치의 A3 스냅샷(data/.bak/A3-<batch>)에서 시작해, 이 종류의 완료된 조각들 + 이번 조각을 다시 적용하고
      기록된 수동 조작(merge·candidate)을 덧붙여 groups/registry/metrics 의 .tmp 를 쓴다. 다시 실행해도 같은 결과.
      조각에 rebuild 표시가 있으면(재분할) 그 종류 전체를 다시 묶고 ID 대응을 aliases·retired 로 남긴다.
  python scripts/group.py merge --batch b1 --kind <종류> <없앨 그룹> <남길 그룹>   경계 사례 병합 (aliases 기록)
  python scripts/group.py candidate --batch b1 --kind <종류> <그룹> --reason "<근거>"   표준 후보 지정
      두 조작 뒤에는 run 을 다시 실행해 .tmp 를 새로 만든다. 사람이 결정한 그룹은 병합할 수 없다.
  python scripts/group.py border --batch b1 --chunk <조각>   시그니처가 비슷한(경계) 그룹 쌍을 출력
  이어서 python scripts/validate.py --rename data/groups/<종류>.json.tmp data/registry/<종류>.json.tmp data/metrics/<종류>.json.tmp
  python scripts/group.py --selftest
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SIZE_STEP = 16
SELECTABLE_KINDS = {"button", "tab", "toggle", "slot", "listcell"}


def size_step(v):
    return int(round(float(v) / SIZE_STEP)) * SIZE_STEP


def signature(kind, n):
    """(sigKey, signature dict)."""
    if kind == "textstyle" and n.get("text"):
        t = n["text"]
        sig = {"font": os.path.basename(t["font"] or "?"), "size": round(t["size"]), "color": t["color"],
               "bold": t.get("bold", False)}
        key = "font=%(font)s|size=%(size)s|color=%(color)s|bold=%(bold)s" % sig
        return key, sig
    g = n.get("graphic") or {}
    sp = g.get("sprite") or {}
    r = n.get("rect") or {"w": 0, "h": 0}
    sprite = "%s:%s" % (sp.get("path") or "-", sp.get("name") or "-") if sp else "none"
    sig = {"sprite": sprite, "imageType": g.get("imageType") or "-", "color": g.get("color") or "-",
           "size": "%dx%d" % (size_step(r["w"]), size_step(r["h"]))}
    if (n.get("text") or {}).get("font"):
        sig["font"] = os.path.basename(n["text"]["font"])
    key = "|".join("%s=%s" % (k, sig[k]) for k in sorted(sig))
    return key, sig


def paths(kind):
    return (C.p("data", "groups", kind + ".json"), C.p("data", "registry", kind + ".json"),
            C.p("data", "metrics", kind + ".json"))


def empty_registry(kind):
    return {"kind": kind, "groups": {}, "aliases": {}, "retired": {}}


def load_base(batch, kind):
    """스냅샷(이 배치 A3 시작 전)이 있으면 그것, 없으면 현재 파일."""
    snap = C.p("data", ".bak", "A3-%s" % batch)
    gp, rp, _ = paths(kind)
    if os.path.isdir(snap):
        groups = C.load_json(os.path.join(snap, "groups", kind + ".json"))
        reg = C.load_json(os.path.join(snap, "registry", kind + ".json"))
    else:
        groups, reg = C.load_json(gp), C.load_json(rp)
    members = {}
    for g in (groups or {}).get("groups", []):
        for mbr in g["members"]:
            members[mbr] = g["id"]
    cands = {g["id"]: g.get("candidateReason") for g in (groups or {}).get("groups", []) if g["status"] == "후보"}
    return members, reg or empty_registry(kind), cands


def resolve(reg, gid):
    seen = set()
    while gid in reg["aliases"] and gid not in seen:
        seen.add(gid)
        gid = reg["aliases"][gid]
    return gid


def decided_targets():
    return {d["target"] for d in (C.load_json(C.p("decisions.json"), []) or []) if d["type"] == "그룹"}


def work_dir(batch):
    return C.p("data", ".work", batch, "A3")


def ops_path(batch, kind):
    return os.path.join(work_dir(batch), "ops-%s.json" % kind)


def apply(kind, batch, members, reg, inv, chunk_specs, rebuild=False):
    """members: node -> gid (갱신됨). chunk_specs: [{"targets": [...], "remove": [...]}]"""
    now = C.now_iso()
    taken = {gid: e["sigKey"] for gid, e in reg["groups"].items()}
    for gid in reg["retired"]:
        taken[gid] = "__retired__:" + gid
    for gid in reg["aliases"]:
        taken.setdefault(gid, "__alias__:" + gid)
    by_sig = {}
    for gid, e in reg["groups"].items():
        if gid not in reg["retired"]:
            by_sig.setdefault(e["sigKey"], gid)
    before = dict(members)
    if rebuild:
        members.clear()
    for spec in chunk_specs:
        for nid in spec.get("remove", []):
            members.pop(nid, None)
        for nid in spec.get("targets", []):
            if nid not in inv:
                members.pop(nid, None)
                continue
            key, _sig = signature(kind, inv[nid][2])
            gid = by_sig.get(key)
            if gid is None:
                gid = C.unique_id(kind, key, taken)
                taken[gid] = key
                by_sig[key] = gid
                reg["groups"][gid] = {"sigKey": key, "createdAt": now, "createdBatch": batch}
            members[nid] = resolve(reg, gid)
    alive = set(members.values())
    for gid in sorted(set(before.values()) - alive):
        gid = resolve(reg, gid)
        if gid in alive or gid in reg["retired"]:
            continue
        succ = sorted({members[n] for n, g in before.items() if g == gid and n in members})
        if rebuild and len(succ) == 1 and all(n in members for n, g in before.items() if g == gid):
            reg["aliases"][gid] = succ[0]  # 재분할에서 멤버가 통째로 한 그룹으로 옮겨감 = 1:1 대응
            continue
        reg["retired"][gid] = {"at": now, "reason": "멤버 0 (재분류·삭제·재분할)", "successors": succ}
    return members, reg


def build_outputs(kind, batch, members, reg, inv, cands):
    groups = {}
    for nid, gid in members.items():
        groups.setdefault(gid, []).append(nid)
    proj = C.project() or {}
    touch = proj.get("touch_min_px", 100)
    out_groups = []
    for gid, mem in groups.items():
        mem = sorted(mem)
        _key, sig = signature(kind, inv[mem[0]][2])
        out_groups.append({"id": gid, "sigKey": reg["groups"][gid]["sigKey"] if gid in reg["groups"] else _key,
                           "signature": sig, "members": mem, "screens": sorted({inv[m][1] for m in mem}),
                           "count": len(mem), "status": "미검토", "candidateReason": None})
    out_groups.sort(key=lambda g: (-g["count"], -len(g["screens"]), g["id"]))
    if cands:
        for g in out_groups:
            if g["id"] in cands:
                g["status"], g["candidateReason"] = "후보", cands[g["id"]] or "에이전트 지정"
    elif out_groups:
        top = out_groups[0]
        top["status"] = "후보"
        top["candidateReason"] = "가장 많이 쓰임 (노드 %d개, 화면 %d개)" % (top["count"], len(top["screens"]))
    nodes = [inv[n][2] for n in members]
    states = {}
    small = 0
    for n in nodes:
        for st in ((n.get("selectable") or {}).get("states") or []):
            states[st] = states.get(st, 0) + 1
        r = n.get("rect") or {}
        if kind in SELECTABLE_KINDS and r and 0 < min(r["w"], r["h"]) < touch:
            small += 1
    cand_nodes = sum(g["count"] for g in out_groups if g["status"] == "후보")
    metrics = {
        "kind": kind, "updatedAt": C.now_iso(), "groupCount": len(out_groups), "nodeCount": len(nodes),
        "screenCount": len({inv[n][1] for n in members}),
        "uniqueSprites": len({((n.get("graphic") or {}).get("sprite") or {}).get("path") for n in nodes} - {None}),
        "uniqueColors": len({(n.get("graphic") or {}).get("color") or (n.get("text") or {}).get("color") for n in nodes} - {None}),
        "uniqueSizes": len({signature(kind, n)[1].get("size") for n in nodes}),
        "fontSizes": sorted({round(n["text"]["size"], 1) for n in nodes if n.get("text")}),
        "candidateShare": round(cand_nodes / len(nodes), 3) if nodes else 0.0,
        "stateCoverage": states, "smallTouchTargets": small,
        "topGroups": [{"id": g["id"], "count": g["count"], "screens": len(g["screens"])} for g in out_groups[:5]]}
    return {"kind": kind, "updatedAt": C.now_iso(), "groups": out_groups}, reg, metrics


def chunk_file(batch, chunk):
    return os.path.join(work_dir(batch), chunk + ".json")


def run(batch, chunk):
    import state
    m = state.load()
    st = m["batches"][batch]["steps"]["A3"]
    if chunk not in st["chunks"]:
        raise SystemExit("A3 조각 '%s' 없음 (state.py show %s A3 확인)" % (chunk, batch))
    meta = st["chunks"][chunk]
    kind = meta["kind"]
    same = [c for c, x in st["chunks"].items() if x.get("kind") == kind and (x["status"] == "완료" or c == chunk)]
    specs = [C.load_json(chunk_file(batch, c)) for c in sorted(same)]
    rebuild = any(s.get("rebuild") for s in specs)
    inv = C.all_inventory()
    members, reg, cands = load_base(batch, kind)
    members, reg = apply(kind, batch, members, reg, inv, specs, rebuild=rebuild)
    for op in C.load_json(ops_path(batch, kind), []) or []:
        if op["op"] == "merge":
            reg["aliases"][op["from"]] = op["into"]
            for n, g in list(members.items()):
                if g == op["from"]:
                    members[n] = op["into"]
        elif op["op"] == "candidate":
            cands = {g: r for g, r in cands.items() if g in set(members.values())}
            cands[op["group"]] = op["reason"]
    cands = {g: r for g, r in cands.items() if g in set(members.values())}
    groups, reg, metrics = build_outputs(kind, batch, members, reg, inv, cands)
    gp, rp, mp = paths(kind)
    tmps = [C.write_tmp(gp, groups), C.write_tmp(rp, reg), C.write_tmp(mp, metrics)]
    print("%s: 그룹 %d, 노드 %d, 새 그룹 %d, retired %d" % (
        kind, metrics["groupCount"], metrics["nodeCount"],
        sum(1 for e in reg["groups"].values() if e["createdBatch"] == batch), len(reg["retired"])))
    print("다음: python scripts/validate.py --rename " + " ".join(
        os.path.relpath(t, C.ROOT).replace("\\", "/") for t in tmps))
    return 0


def add_op(batch, kind, op):
    path = ops_path(batch, kind)
    ops = C.load_json(path, []) or []
    ops.append(dict(op, at=C.now_iso()))
    C.write_json_atomic(path, ops)


def border(batch, chunk):
    """크기 단계만 한 칸 다르거나 색만 다른 그룹 쌍 — 사람이 볼 경계 사례."""
    import state
    kind = state.load()["batches"][batch]["steps"]["A3"]["chunks"][chunk]["kind"]
    gp = C.p("data", "groups", kind + ".json")
    data = C.load_json(gp + ".tmp") or C.load_json(gp) or {"groups": []}
    gs = data["groups"]
    n = 0
    for i, a in enumerate(gs):
        for b in gs[i + 1:]:
            sa, sb = a["signature"], b["signature"]
            diff = [k for k in set(sa) | set(sb) if sa.get(k) != sb.get(k)]
            if len(diff) == 1:
                print("%s(%d) ~ %s(%d): %s %s vs %s" % (a["id"], a["count"], b["id"], b["count"], diff[0],
                                                        sa.get(diff[0]), sb.get(diff[0])))
                n += 1
                if n >= 40:
                    return 0
    print("경계 쌍 %d개 (한 항목만 다른 그룹)" % n)
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["run", "merge", "candidate", "border"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--batch")
    ap.add_argument("--chunk")
    ap.add_argument("--kind")
    ap.add_argument("--reason", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "run":
        return run(a.batch, a.chunk)
    if a.cmd == "border":
        return border(a.batch, a.chunk)
    if a.cmd == "merge":
        frm, into = a.args
        decided = decided_targets()
        if frm in decided or into in decided:
            print("사람이 결정한 그룹은 병합할 수 없음: %s" % ({frm, into} & decided))
            return 1
        add_op(a.batch, a.kind, {"op": "merge", "from": frm, "into": into})
        print("병합 기록: %s → %s. group.py run 을 다시 실행하세요." % (frm, into))
        return 0
    if a.cmd == "candidate":
        add_op(a.batch, a.kind, {"op": "candidate", "group": a.args[0], "reason": a.reason or "에이전트 지정"})
        print("후보 기록: %s. group.py run 을 다시 실행하세요." % a.args[0])
        return 0
    ap.print_help()
    return 2


def selftest():
    def nd(nid, sprite, w, color="#FFFFFFFF"):
        return ("b1", "s1", {"id": nid, "graphic": {"color": color, "sprite": {"path": sprite, "name": "x"},
                                                      "imageType": "Sliced"}, "rect": {"w": w, "h": 50},
                              "selectable": {"states": ["Normal", "Pressed"]}, "text": None})
    inv = {"a": nd("a", "A.png", 160), "b": nd("b", "A.png", 165), "c": nd("c", "B.png", 160),
           "d": nd("d", "A.png", 160, "#FF0000FF")}
    members, reg = apply("button", "b1", {}, {"kind": "button", "groups": {}, "aliases": {}, "retired": {}},
                         inv, [{"targets": ["a", "b", "c", "d"]}])
    assert members["a"] == members["b"], "같은 크기 단계는 같은 그룹이어야 함"
    assert len(set(members.values())) == 3
    ids1 = dict(members)
    members2, reg2 = apply("button", "b1", {}, {"kind": "button", "groups": {}, "aliases": {}, "retired": {}},
                           inv, [{"targets": ["d", "c", "b", "a"]}])
    assert members2 == ids1, "순서와 무관하게 같은 ID 여야 함"
    gid_c = members["c"]
    members, reg = apply("button", "b2", members, reg, inv, [{"remove": ["c"]}])
    assert gid_c in reg["retired"], "비게 된 그룹은 retired"
    members, reg = apply("button", "b2", members, reg, inv, [{"targets": ["c"]}])
    assert members["c"] != gid_c, "retired ID 는 재사용하지 않음"
    reg["groups"]["button-old1"] = {"sigKey": "old", "createdAt": "x", "createdBatch": "b1"}
    old = dict(members, a="button-old1", b="button-old1")
    rebuilt, reg = apply("button", "b2", old, reg, inv, [{"targets": ["a", "b", "c", "d"]}], rebuild=True)
    assert reg["aliases"].get("button-old1") == rebuilt["a"], "재분할 1:1 대응은 aliases"
    assert "button-old1" not in reg["retired"]
    g, reg, met = build_outputs("button", "b1", members, reg, inv, {})
    assert g["groups"][0]["status"] == "후보" and met["nodeCount"] == 4
    import validate
    assert not validate.validate_obj(g, "groups"), validate.validate_obj(g, "groups")
    assert not validate.validate_obj(reg, "registry"), validate.validate_obj(reg, "registry")
    assert not validate.validate_obj(met, "metrics")
    print("group.py selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
