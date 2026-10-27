"""A4 토큰 추출: 그룹에 속한 노드의 값(inventory)을 분류별로 모아, token-registry 의 기존 토큰에 먼저
배정하고 맞는 토큰이 없는 값만 새로 묶어 새 ID(분류 + 처음 값의 짧은 해시)를 준다. ID 는 재사용하지 않는다.

분류(조각): color(색) · type(폰트+크기) · spacing(LayoutGroup spacing·padding, 늘린 앵커의 여백)
           · nineslice(Sliced 스프라이트 border) · size(입력·슬롯·아이콘류의 크기)
허용 오차: color 채널 ±6/255(알파 같음) · type 같은 폰트 ±1pt · spacing ±2px · nineslice 각 변 ±2px · size 같은 종류 ±4px

사용:
  python scripts/cluster_values.py run --batch b1 --chunk <분류>      tokens/token-registry .tmp 쓰기
  python scripts/cluster_values.py family --batch b1 --chunk color <토큰> grade|attribute|base   등급·속성 색 등 별도 그룹 지정
  python scripts/cluster_values.py except --batch b1 --chunk <분류> "<값 키>" --reason "<사유>"   예외로 빼기
  python scripts/cluster_values.py merge --batch b1 --chunk <분류> <없앨 토큰> <남길 토큰>         토큰 병합 (aliases)
      조작 뒤에는 run 을 다시 실행한다. 사람이 결정한 토큰은 병합할 수 없다.
  이어서 python scripts/validate.py --rename data/tokens/<분류>.json.tmp data/token-registry/<분류>.json.tmp
  python scripts/cluster_values.py --selftest
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

SIZE_KINDS = {"button", "tab", "toggle", "slot", "icon", "currency", "reddot", "listcell", "gauge"}


def grouped_nodes():
    """그룹에 속한 노드: {node_id: kind}"""
    out = {}
    for f in C.iter_json(C.p("data", "groups")):
        g = C.load_json(f)
        for grp in g["groups"]:
            for mbr in grp["members"]:
                out[mbr] = g["kind"]
    return out


def collect(cat, inv=None, grouped=None):
    """{valueKey: {"value": v, "count": n, "samples": [node ids]}}"""
    inv = C.all_inventory() if inv is None else inv
    grouped = grouped_nodes() if grouped is None else grouped
    vals = {}

    def add(key, value, nid):
        e = vals.setdefault(key, {"value": value, "count": 0, "samples": []})
        e["count"] += 1
        if len(e["samples"]) < 5:
            e["samples"].append(nid)

    for nid in sorted(grouped):
        if nid not in inv:
            continue
        n, kind = inv[nid][2], grouped[nid]
        g, t, lay, r = n.get("graphic"), n.get("text"), n.get("layout"), n.get("rect")
        if cat == "color":
            if g and (g.get("sprite") or g["color"][-2:] != "00"):
                add(g["color"], g["color"], nid)
            if t:
                add(t["color"], t["color"], nid)
        elif cat == "type" and t:
            font = os.path.basename(t["font"] or "?")
            size = round(t["size"])
            add("%s|%d" % (font, size), {"font": font, "size": size}, nid)
        elif cat == "spacing":
            if lay:
                sp = lay.get("spacing")
                for v in (sp if isinstance(sp, list) else [sp]):
                    if v:
                        add("%g" % round(v), round(v), nid)
                for v in lay.get("padding") or []:
                    if v:
                        add("%g" % round(v), round(v), nid)
            if r:
                for axis in (0, 1):
                    if r["anchorMin"][axis] != r["anchorMax"][axis]:
                        piv, pos, sd = r["pivot"][axis], r["pos"][axis], r["sizeDelta"][axis]
                        for v in (pos - sd * piv, -(pos + sd * (1 - piv))):
                            v = round(v)
                            if v:
                                add("%g" % v, v, nid)
        elif cat == "nineslice" and g and g.get("imageType") == "Sliced":
            b = (g.get("sprite") or {}).get("border")
            if b and any(b):
                b = [round(x) for x in b]
                add(",".join(map(str, b)), b, nid)
        elif cat == "size" and kind in SIZE_KINDS and r:
            w, h = round(r["w"]), round(r["h"])
            add("%s:%dx%d" % (kind, w, h), {"kind": kind, "w": w, "h": h}, nid)
    return vals


def close(cat, a, b):
    if cat == "color":
        ca = [int(a[i:i + 2], 16) for i in (1, 3, 5, 7)]
        cb = [int(b[i:i + 2], 16) for i in (1, 3, 5, 7)]
        return ca[3] == cb[3] and max(abs(x - y) for x, y in zip(ca[:3], cb[:3])) <= 6
    if cat == "type":
        return a["font"] == b["font"] and abs(a["size"] - b["size"]) <= 1
    if cat == "spacing":
        return abs(a - b) <= 2
    if cat == "nineslice":
        return max(abs(x - y) for x, y in zip(a, b)) <= 2
    if cat == "size":
        return a["kind"] == b["kind"] and abs(a["w"] - b["w"]) <= 4 and abs(a["h"] - b["h"]) <= 4
    raise ValueError(cat)


def parse_key(cat, key):
    if cat == "color":
        return key
    if cat == "type":
        font, size = key.rsplit("|", 1)
        return {"font": font, "size": int(size)}
    if cat == "spacing":
        return float(key)
    if cat == "nineslice":
        return [int(x) for x in key.split(",")]
    kind, wh = key.split(":")
    w, h = wh.split("x")
    return {"kind": kind, "w": int(w), "h": int(h)}


def empty_registry(cat):
    return {"category": cat, "tokens": {}, "aliases": {}, "retired": {}, "families": {}, "exceptions": {}}


def resolve(reg, tid):
    seen = set()
    while tid in reg["aliases"] and tid not in seen:
        seen.add(tid)
        tid = reg["aliases"][tid]
    return tid


def cluster(cat, batch, vals, reg):
    """(tokens, mapping, exceptions, reg) — 기존 토큰 우선, 남은 값은 빈도순 탐욕 묶기."""
    now = C.now_iso()
    mapping, exceptions = {}, []
    live = {tid: parse_key(cat, e["valueKey"]) for tid, e in reg["tokens"].items()
            if tid not in reg["retired"] and tid not in reg["aliases"]}
    rest = []
    for key in sorted(vals, key=lambda k: (-vals[k]["count"], k)):
        if key in reg.get("exceptions", {}):
            exceptions.append({"value": key, "reason": reg["exceptions"][key], "count": vals[key]["count"]})
            continue
        hit = next((tid for tid, v in sorted(live.items()) if close(cat, v, vals[key]["value"])), None)
        if hit:
            mapping[key] = hit
        else:
            rest.append(key)
    taken = {tid: e["valueKey"] for tid, e in reg["tokens"].items()}
    for tid in reg["retired"]:
        taken[tid] = "__retired__:" + tid
    while rest:
        anchor = rest.pop(0)
        tid = C.unique_id(cat, anchor, taken)
        taken[tid] = anchor
        reg["tokens"][tid] = {"valueKey": anchor, "createdAt": now, "createdBatch": batch}
        live[tid] = parse_key(cat, anchor)
        mapping[anchor] = tid
        for k in list(rest):
            if close(cat, live[tid], vals[k]["value"]):
                mapping[k] = tid
                rest.remove(k)
    mapping = {k: resolve(reg, t) for k, t in mapping.items()}
    used = {}
    for k, tid in mapping.items():
        used.setdefault(tid, []).append(k)
    tokens = []
    for tid, keys in used.items():
        keys.sort(key=lambda k: -vals[k]["count"])
        samples = []
        for k in keys:
            samples.extend(vals[k]["samples"])
        tokens.append({"id": tid, "value": parse_key(cat, reg["tokens"][tid]["valueKey"]),
                       "valueKey": reg["tokens"][tid]["valueKey"], "family": reg["families"].get(tid, "base"),
                       "members": keys, "count": sum(vals[k]["count"] for k in keys), "status": "미검토",
                       "samples": samples[:5]})
    tokens.sort(key=lambda t: (-t["count"], t["id"]))
    for tid in reg["tokens"]:
        if tid not in used and tid not in reg["retired"] and tid not in reg["aliases"]:
            reg["retired"][tid] = {"at": now, "reason": "쓰는 값 없음", "successors": []}
    return tokens, mapping, exceptions, reg


def ops_path(batch, cat):
    return C.p("data", ".work", batch, "A4", "ops-%s.json" % cat)


def load_base(batch, cat):
    snap = C.p("data", ".bak", "A4-%s" % batch, "token-registry", cat + ".json")
    cur = C.p("data", "token-registry", cat + ".json")
    reg = C.load_json(snap) if os.path.isdir(C.p("data", ".bak", "A4-%s" % batch)) else C.load_json(cur)
    reg = reg or empty_registry(cat)
    reg.setdefault("families", {})
    reg.setdefault("exceptions", {})
    for op in C.load_json(ops_path(batch, cat), []) or []:
        if op["op"] == "family":
            reg["families"][op["token"]] = op["family"]
        elif op["op"] == "except":
            reg["exceptions"][op["value"]] = op["reason"]
        elif op["op"] == "merge":
            reg["aliases"][op["from"]] = op["into"]
    return reg


def run(batch, cat):
    if cat not in C.TOKEN_CATEGORIES:
        raise SystemExit("분류는 %s 중 하나" % C.TOKEN_CATEGORIES)
    vals = collect(cat)
    reg = load_base(batch, cat)
    tokens, mapping, exceptions, reg = cluster(cat, batch, vals, reg)
    out = {"category": cat, "updatedAt": C.now_iso(), "tokens": tokens, "mapping": mapping, "exceptions": exceptions}
    t1 = C.write_tmp(C.p("data", "tokens", cat + ".json"), out)
    t2 = C.write_tmp(C.p("data", "token-registry", cat + ".json"), reg)
    print("%s: 값 %d종 → 토큰 %d개, 예외 %d" % (cat, len(vals), len(tokens), len(exceptions)))
    for t in tokens[:15]:
        print("  %s %s ×%d (값 %d종) %s" % (t["id"], t["valueKey"], t["count"], len(t["members"]), t["family"]))
    print("다음: python scripts/validate.py --rename %s %s" % (
        os.path.relpath(t1, C.ROOT).replace("\\", "/"), os.path.relpath(t2, C.ROOT).replace("\\", "/")))
    return 0


def add_op(batch, cat, op):
    path = ops_path(batch, cat)
    ops = C.load_json(path, []) or []
    ops.append(dict(op, at=C.now_iso()))
    C.write_json_atomic(path, ops)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["run", "family", "except", "merge"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--batch")
    ap.add_argument("--chunk")
    ap.add_argument("--reason", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "run":
        return run(a.batch, a.chunk)
    if a.cmd == "family":
        add_op(a.batch, a.chunk, {"op": "family", "token": a.args[0], "family": a.args[1]})
    elif a.cmd == "except":
        add_op(a.batch, a.chunk, {"op": "except", "value": a.args[0], "reason": a.reason or "예외"})
    elif a.cmd == "merge":
        decided = {d["target"] for d in (C.load_json(C.p("decisions.json"), []) or []) if d["type"] == "토큰"}
        if set(a.args) & decided:
            print("사람이 결정한 토큰은 병합할 수 없음: %s" % (set(a.args) & decided))
            return 1
        add_op(a.batch, a.chunk, {"op": "merge", "from": a.args[0], "into": a.args[1]})
    else:
        ap.print_help()
        return 2
    print("기록함. cluster_values.py run --batch %s --chunk %s 을 다시 실행하세요." % (a.batch, a.chunk))
    return 0


def selftest():
    import validate
    vals = {"#FFFFFFFF": {"value": "#FFFFFFFF", "count": 10, "samples": ["n1"]},
            "#FDFDFDFF": {"value": "#FDFDFDFF", "count": 2, "samples": ["n2"]},
            "#000000FF": {"value": "#000000FF", "count": 3, "samples": ["n3"]},
            "#FFFFFF80": {"value": "#FFFFFF80", "count": 1, "samples": ["n4"]}}
    reg = empty_registry("color")
    tokens, mapping, exc, reg = cluster("color", "b1", vals, reg)
    assert mapping["#FFFFFFFF"] == mapping["#FDFDFDFF"], "가까운 색은 한 토큰"
    assert mapping["#FFFFFF80"] != mapping["#FFFFFFFF"], "알파가 다르면 다른 토큰"
    assert len(tokens) == 3
    ids = set(reg["tokens"])
    vals2 = dict(vals, **{"#FEFEFEFF": {"value": "#FEFEFEFF", "count": 50, "samples": ["n5"]}})
    tokens2, mapping2, _e, reg2 = cluster("color", "b2", vals2, reg)
    assert mapping2["#FEFEFEFF"] == mapping["#FFFFFFFF"], "기존 토큰에 먼저 배정"
    assert ids <= set(reg2["tokens"]), "기존 토큰 ID 유지"
    out = {"category": "color", "updatedAt": "x", "tokens": tokens2, "mapping": mapping2, "exceptions": []}
    assert not validate.validate_obj(out, "tokens"), validate.validate_obj(out, "tokens")
    assert not validate.validate_obj(reg2, "token-registry")
    assert close("spacing", 10, 12) and not close("spacing", 10, 13)
    assert parse_key("size", "button:160x50") == {"kind": "button", "w": 160, "h": 50}
    print("cluster_values.py selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
