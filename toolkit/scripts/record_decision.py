"""사람(by user)·관문 에이전트(by agent)의 결정을 decisions.json 에 한 건씩 기록한다 (이 스크립트로만 추가).

사용:
  python scripts/record_decision.py <id> 표준
  python scripts/record_decision.py <id> 폐기 [--to <대체 id>]       (--to 없으면 '대체 미정')
  python scripts/record_decision.py <id> 예외 --reason "<사유>"
  python scripts/record_decision.py "<노드 id>|<원본 프리팹#경로>" 분류 <종류 슬러그>
      중첩(템플릿 인스턴스) 노드를 주면 대상은 템플릿 원본 노드 id 로 바뀌어 기록되고 모든 인스턴스에 적용된다.
  python scripts/record_decision.py template:<slug> 표준|폐기 [--to template:<slug>]|예외 --reason "<사유>"
  python scripts/record_decision.py --template <이름|slug|경로|guid> 표준|폐기 [--to <이름|slug>]|예외 --reason ".."
      템플릿 단위 결정(type 템플릿). 대상·--to 는 data/template-index.json 에 있는 템플릿이어야 하고 template:<slug> 로
      정규화해 기록한다(--template 이 있으면 --to 도 이름·slug 로 줄 수 있다). memberSnapshot 은 그 템플릿의 사용처.
      노드 카탈로그(A2·A5·A6)는 건드리지 않는다 — 반영은 python scripts/ds_index.py --run.
  python scripts/record_decision.py --consistency [--emit <파일>]
      같은 템플릿 원본 노드의 인스턴스 사이 분류 불일치를 센다(결정 반영 후). --emit 은 불일치를 0 으로 만드는
      다수결 분류 명령(--by agent)을 파일로 쓴다 — 실행하지 않는다(기록하면 A2 reopen·A5·A6 무효).
  python scripts/record_decision.py --question <q-id> --pick <번호>   (보기의 행동을 기록하고 질문을 닫음)
  공통 옵션: --by user|agent (기본 user, agent 는 관문 에이전트 결정 — --reason 필수), --reason "<근거>"
  python scripts/record_decision.py --selftest
규칙: alias ID 는 현재 ID 로 바꿔 기록, retired ID 는 오류(이어받은 후보 표시), 같은 대상의 이전 결정은 supersedes 로 연결,
     같은 대상의 열린 질문은 answered 로 닫힘, 분류 결정은 대상(원본 노드면 모든 인스턴스)이 있는 화면의 A2 조각을 reopen,
     기록 뒤 현재 배치(현재 배치가 H1 이면 직전 배치)의 A5·A6 이 무효가 된다(템플릿 결정은 제외 — manifest 를 바꾸지 않는다).
"""
import argparse
import copy
import difflib
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import template_scope as TS  # noqa: E402

STATUSES = ("표준", "폐기", "예외")
BY = ("user", "agent")
TEMPLATE = "템플릿"
TEMPLATE_PREFIX = "template:"


class DecisionError(Exception):
    pass


def registries():
    """[(type, kind_or_cat, path, registry)]"""
    out = []
    for f in C.iter_json(C.p("data", "registry")):
        r = C.load_json(f)
        out.append(("그룹", r["kind"], f, r))
    for f in C.iter_json(C.p("data", "token-registry")):
        r = C.load_json(f)
        out.append(("토큰", r["category"], f, r))
    return out


def template_meta(slug):
    return C.load_json(C.p("data", "templates", slug + ".json")) or {}


def resolve_template(xid):
    """템플릿 지정(template:<slug> 또는 slug·이름·경로·guid, 대소문자 무시) → slug. 오류는 DecisionError."""
    slugs = (C.load_json(C.p("data", "template-index.json")) or {}).get("templates") or []
    if not slugs:
        raise DecisionError("data/template-index.json 이 없거나 비어 있음 — 템플릿 카탈로그(T 트랙)가 먼저 필요")
    key = xid[len(TEMPLATE_PREFIX):] if xid.startswith(TEMPLATE_PREFIX) else xid
    if key in slugs:
        return key
    low = key.lower()
    hits = [s for s in slugs if low in {str(v).lower() for k, v in template_meta(s).items()
                                        if k in ("slug", "name", "path", "guid") and v} | {s}]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise DecisionError("모호한 템플릿 지정: %s → %s" % (xid, ", ".join(hits)))
    near = difflib.get_close_matches(low.replace("_", "-"), slugs, 3)
    raise DecisionError("없는 템플릿: %s (data/template-index.json 에 없음)%s" % (
        xid, " — 비슷한 slug: " + ", ".join(near) if near else ""))


def resolve(xid, template=False):
    """(type, current id, kind_or_cat). 템플릿이면 (템플릿, template:<slug>, slug). 오류는 DecisionError."""
    if template or xid.startswith(TEMPLATE_PREFIX):
        slug = resolve_template(xid)
        return TEMPLATE, TEMPLATE_PREFIX + slug, slug
    if "#" in xid:
        inv = C.all_inventory()
        if xid in inv:
            return "분류", TS.source_node_id(inv[xid][2]) or xid, None
        if instances(xid, inv):
            return "분류", xid, None
        raise DecisionError("없는 노드 ID: %s (노드·템플릿 원본 노드 어디에도 없음)" % xid)
    for typ, kc, _f, r in registries():
        ids = r.get("groups") or r.get("tokens") or {}
        cur = xid
        seen = set()
        while cur in r["aliases"] and cur not in seen:
            seen.add(cur)
            cur = r["aliases"][cur]
        if cur in r["retired"]:
            succ = r["retired"][cur]["successors"]
            raise DecisionError("retired ID: %s (%s) — 이어받은 후보: %s" % (
                cur, r["retired"][cur]["reason"], ", ".join(succ) or "없음"))
        if cur in ids:
            return typ, cur, kc
    raise DecisionError("없는 ID: %s (그룹·토큰·노드 어디에도 없음)" % xid)


def instances(target, inv):
    """분류 대상(노드 id 또는 템플릿 원본 노드 id)이 적용되는 노드 id 목록."""
    return sorted(nid for nid, (_b, _s, n) in inv.items() if nid == target or TS.source_node_id(n) == target)


def member_snapshot(typ, xid, kc):
    if typ == "분류":
        return instances(xid, C.all_inventory())
    if typ == TEMPLATE:  # 결정 당시 사용처(프리팹·씬·코드 파일)
        return sorted({u["user"] for u in template_meta(kc).get("users", [])})
    if typ == "그룹":
        g = C.load_json(C.p("data", "groups", kc + ".json")) or {"groups": []}
        return next((x["members"] for x in g["groups"] if x["id"] == xid), [])
    t = C.load_json(C.p("data", "tokens", kc + ".json")) or {"tokens": []}
    return next((x["members"] for x in t["tokens"] if x["id"] == xid), [])


def parse_action(action):
    """보기의 행동 문자열 → (id, status, to, reason, kind)"""
    m = re.match(r"^(.+) 분류 ([a-z]+)$", action)
    if m:
        return m.group(1), "분류", None, None, m.group(2)
    parts = shlex.split(action)
    if len(parts) >= 2 and parts[1] in STATUSES:
        to = parts[parts.index("--to") + 1] if "--to" in parts else None
        reason = parts[parts.index("--reason") + 1] if "--reason" in parts else None
        return parts[0], parts[1], to, reason, None
    raise DecisionError("행동을 해석할 수 없음: %s" % action)


def record(xid, status, to=None, reason=None, kind=None, question=None, by="user", template=False):
    import questions
    import state
    typ, cur, kc = resolve(xid, template)
    if status == "분류":
        if typ != "분류":
            raise DecisionError("분류 결정은 노드 ID 에만: %s" % xid)
        if kind not in C.KINDS:
            raise DecisionError("종류 슬러그가 아님: %s (%s)" % (kind, " ".join(C.KINDS)))
    elif typ == "분류":
        raise DecisionError("노드 ID 에는 '분류 <종류>' 만 쓸 수 있음")
    if status == "예외" and not reason:
        raise DecisionError("예외에는 --reason 이 필요")
    if by not in BY:
        raise DecisionError("--by 는 %s 중 하나" % "|".join(BY))
    if by == "agent" and not reason:
        raise DecisionError("--by agent 에는 --reason(적용한 규칙과 수치)이 필요")
    if to:
        ttyp, to, _kc = resolve(to, template)
        if ttyp != typ:
            raise DecisionError("--to 는 같은 종류의 ID 여야 함 (%s vs %s)" % (typ, ttyp))
        if to == cur:
            raise DecisionError("자기 자신으로 대체할 수 없음")
    m = state.load()
    decs = C.load_json(C.p("decisions.json"), []) or []
    prev = [d for d in decs if d["target"] == cur]
    n = max([int(d["id"][2:]) for d in decs] + [0]) + 1
    # 템플릿 결정은 노드 카탈로그 입력(분류·그룹·토큰)이 아니므로 A5·A6 을 무효로 하지 않는다 — 배치 이름만 같은 규칙으로 얻는다.
    batch = state.invalidate_for_decision(copy.deepcopy(m) if typ == TEMPLATE else m)
    d = {"id": "d-%04d" % n, "type": typ, "target": cur, "status": status, "to": to if status == "폐기" else None,
         "kind": kind, "reason": reason or ("대체 미정" if status == "폐기" and not to else None),
         "supersedes": prev[-1]["id"] if prev else None, "memberSnapshot": member_snapshot(typ, cur, kc),
         "by": by, "at": C.today(), "batch": batch, "questionId": question}
    decs.append(d)
    C.write_json_atomic(C.p("decisions.json"), decs, "decisions")
    answer = "%s %s%s" % (cur, status, (" " + kind) if kind else "")
    if question:
        questions.close(question, "answered", answer)
    closed = questions.close_for_target({xid, cur}, answer)
    if typ == "분류":
        inv = C.all_inventory()
        screens = {}
        for nid in d["memberSnapshot"]:
            nb, screen, _n = inv[nid]
            screens.setdefault(nb, set()).add(screen)
        for nb, scr in sorted(screens.items()):
            a2 = m["batches"].get(nb, {}).get("steps", {}).get("A2")
            if a2 and a2["attempts"]:
                state.reopen(m, nb, "A2", sorted(scr), "분류 결정 %s: %s → %s" % (d["id"], cur, kind),
                             by="decision", count_failure=False)
    if typ != TEMPLATE:
        state.save(m)
    C.append_log("decision %s %s %s%s" % (d["id"], cur, status, (" --to " + to) if to else ""))
    print("기록: %s %s %s%s%s (by %s, 배치 %s, supersedes %s, 질문 닫음 %d)" % (
        d["id"], cur, status, (" → " + to) if to else "", " " + kind if kind else "", by, batch, d["supersedes"],
        closed + (1 if question else 0)))
    if cur != xid:
        note = {"분류": "템플릿 원본 노드 — 인스턴스 %d개에 적용" % len(d["memberSnapshot"]),
                TEMPLATE: "템플릿 — 사용처 %d곳" % len(d["memberSnapshot"])}.get(typ, "alias → 현재 ID")
        print("참고: %s → %s 로 기록 (%s)" % (xid, cur, note))
    if typ == TEMPLATE:
        print("반영: python scripts/ds_index.py --run (노드 카탈로그 A2·A5·A6 은 그대로 — manifest 변경 없음)")
    print("다음: %s" % m["current"]["next"])
    return d


def consistency(inv=None, cls=None, dec=None):
    """같은 템플릿 원본 노드 인스턴스 사이 분류 불일치. [(원본 id, {종류: [노드 id]})]"""
    import classify_rules
    inv = C.all_inventory() if inv is None else inv
    cls = C.all_classified() if cls is None else cls
    dec = classify_rules.decision_kinds() if dec is None else dec
    rank = {t: i for i, t in enumerate(dec)}
    by_src = {}
    for nid, (_b, _s, n) in inv.items():
        src = TS.source_node_id(n)
        if not src:
            continue
        kind = classify_rules.pick_decision(n, dec, rank) or (cls[nid][2]["kind"] if nid in cls else None)
        if kind:
            by_src.setdefault(src, {}).setdefault(kind, []).append(nid)
    return sorted((s, k) for s, k in by_src.items() if len(k) > 1)


def emit_commands(bad):
    """불일치 원본마다 다수결 종류로 분류하는 명령 줄."""
    lines = []
    for src, kinds in bad:
        ranked = sorted(kinds.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        total = sum(len(v) for v in kinds.values())
        lines.append('python scripts/record_decision.py "%s" 분류 %s --by agent --reason "T8 다수결: 인스턴스 %d개 중 %s"' % (
            src, ranked[0][0], total, ", ".join("%s %d" % (k, len(v)) for k, v in ranked)))
    return lines


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("args", nargs="*")
    ap.add_argument("--to")
    ap.add_argument("--reason")
    ap.add_argument("--question")
    ap.add_argument("--pick", type=int)
    ap.add_argument("--by", choices=BY, default="user")
    ap.add_argument("--template", action="store_true", help="대상·--to 를 템플릿 이름·slug·경로·guid 로 해석")
    ap.add_argument("--consistency", action="store_true")
    ap.add_argument("--emit")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        import state_selftest
        selftest_propagation()
        selftest_templates()
        return state_selftest.run_decisions()
    if a.consistency:
        bad = consistency()
        for src, kinds in bad[:20]:
            print("%s: %s" % (src, ", ".join("%s %d" % (k, len(v)) for k, v in sorted(kinds.items()))))
        print("같은 원본 인스턴스 사이 분류 불일치: 원본 %d개 (노드 %d개)" % (len(bad), sum(len(v) for _s, k in bad for v in k.values())))
        if a.emit:
            with open(a.emit, "w", encoding="utf-8", newline="\n") as f:
                f.write("".join(line + "\n" for line in emit_commands(bad)))
            print("명령 %d줄 → %s (실행하면 0 이 된다. 기록은 A2 reopen·A5·A6 무효를 부른다)" % (len(bad), a.emit))
        return 1 if bad else 0
    try:
        if a.question:
            import questions
            q = [x for x in questions.load() if x["id"] == a.question]
            if not q:
                raise DecisionError("없는 질문 ID: %s" % a.question)
            q = q[0]
            if q["status"] != "open":
                raise DecisionError("이미 닫힌 질문: %s (%s)" % (a.question, q["status"]))
            if not a.pick or not 1 <= a.pick <= len(q["options"]):
                raise DecisionError("--pick 은 1~%d" % len(q["options"]))
            xid, status, to, reason, kind = parse_action(q["options"][a.pick - 1]["action"])
            reason = "; ".join(x for x in (reason, a.reason) if x) or None  # 보기의 사유 + 결정 근거
            record(xid, status, to, reason, kind, question=a.question, by=a.by)
            return 0
        if len(a.args) == 2 and a.args[1] in STATUSES:
            record(a.args[0], a.args[1], a.to, a.reason, by=a.by, template=a.template)
            return 0
        if len(a.args) == 3 and a.args[1] == "분류":
            record(a.args[0], "분류", reason=a.reason, kind=a.args[2], by=a.by)
            return 0
    except DecisionError as e:
        print("오류: %s" % e)
        return 1
    ap.print_help()
    return 2


def selftest_propagation():
    """T8: 같은 원본의 인스턴스 2개 — 원본 노드 결정이 둘 다에 적용되어 불일치 0, 노드 결정만 있으면 불일치."""
    ns = {"prefab": "Assets/t/Btn.prefab", "guid": "g", "instanceRoot": "Root/Btn"}
    a = {"id": "Assets/x.prefab#Root/Btn", "path": "Root/Btn", "nested": ns}
    b = dict(a, id="Assets/y.prefab#Root/Btn")
    inv = {a["id"]: ("b1", "x", a), b["id"]: ("b1", "y", b)}
    cls = {a["id"]: ("b1", "x", {"kind": "button"}), b["id"]: ("b1", "y", {"kind": "icon"})}
    assert instances("Assets/t/Btn.prefab#Btn", inv) == sorted(inv)
    bad = consistency(inv, cls, {})
    assert len(bad) == 1 and bad[0][0] == "Assets/t/Btn.prefab#Btn", bad
    assert emit_commands(bad)[0].startswith('python scripts/record_decision.py "Assets/t/Btn.prefab#Btn" 분류 button')
    assert consistency(inv, cls, {"Assets/t/Btn.prefab#Btn": "icon"}) == []
    assert len(consistency(inv, cls, {"Assets/t/Btn.prefab#Btn": "icon", a["id"]: "decor"})) == 1
    print("  T8 전파 단위 검사 ok")


def selftest_templates():
    """템플릿 결정: 임시 루트(합성 템플릿 3개)에서 정규화·없는 slug·--to 검사·supersedes·질문 닫기·manifest 불변·ds_index 호환."""
    import json
    import ds_index
    root = C.selftest_dir("tdec")
    metas = {
        "button-yellow": {"name": "Button_Yellow", "guid": "g1", "users": [{"user": "Assets/B.prefab"}, {"user": "Assets/A.prefab"},
                                                                            {"user": "Assets/A.prefab"}]},
        "button-yellow-new": {"name": "Button_Yellow_New", "guid": "g2", "users": [{"user": "Assets/C.prefab"}]},
        "popup-bg-tall": {"name": "Popup_BG_Tall", "guid": "g3", "users": []}}
    os.makedirs(os.path.join(root, "data", "templates"))
    for slug, t in metas.items():
        t.update(slug=slug, path="Assets/UI/%s.prefab" % t["name"])
        with open(os.path.join(root, "data", "templates", slug + ".json"), "w", encoding="utf-8") as f:
            json.dump(t, f, ensure_ascii=False)
    manifest = {"batchOrder": ["b1", "b2"], "current": {"batch": "b2", "next": "완료"}, "batches": {
        b: {"gates": {"H1": "완료" if b == "b1" else "대기"}, "steps": {"A2": {"status": "완료", "attempts": [1]},
                                                                     "A5": {"status": "완료"}, "A6": {"status": "완료"}}}
        for b in ("b1", "b2")}}
    q = {"id": "q-0001", "gate": "H2", "batch": "b1", "status": "open", "target": "template:popup-bg-tall", "text": "?",
         "options": [{"label": "예외", "action": 'template:popup-bg-tall 예외 --reason "런타임 배경"'}], "evidence": []}
    for rel, obj in (("data/template-index.json", {"templates": sorted(metas)}), ("manifest.json", manifest),
                     ("decisions.json", []), ("questions.json", [q])):
        with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    with open(os.path.join(root, "manifest.json"), "rb") as f:
        m_before = f.read()

    def r(*args):
        return C.run_script(root, "record_decision.py", *args, check=False)

    def decs():
        return C.load_json(os.path.join(root, "decisions.json"))

    rc, out = r("template:button-yellow", "표준")
    d = decs()[-1]
    assert rc == 0 and d["type"] == TEMPLATE and d["target"] == "template:button-yellow", (out, d)
    assert d["memberSnapshot"] == ["Assets/A.prefab", "Assets/B.prefab"] and d["batch"] == "b1" and d["supersedes"] is None, d
    assert "ds_index.py --run" in out, out
    rc, out = r("--template", "Button_Yellow_New", "폐기", "--to", "template:button-yellow")
    d = decs()[-1]
    assert rc == 0 and d["target"] == "template:button-yellow-new" and d["to"] == "template:button-yellow", (out, d)
    rc, out = r("--template", "button_yellow_new", "폐기", "--to", "Button_Yellow")  # 대소문자 무시·--to 도 이름으로
    d = decs()[-1]
    assert rc == 0 and d["to"] == "template:button-yellow" and d["supersedes"] == decs()[-2]["id"], (out, d)
    n = len(decs())
    for args, msg in ((("template:nope", "표준"), "없는 템플릿"),
                      (("template:button-yelow", "표준"), "button-yellow"),  # 비슷한 slug 제안
                      (("template:button-yellow-new", "폐기", "--to", "template:nope"), "없는 템플릿"),
                      (("template:button-yellow-new", "폐기", "--to", "button-0000"), "없는 ID"),  # 접두사·플래그 없으면 그룹/토큰
                      (("template:button-yellow", "폐기", "--to", "template:button-yellow"), "자기 자신"),
                      (("template:popup-bg-tall", "예외"), "--reason"),
                      (("template:popup-bg-tall", "분류", "button"), "노드 ID")):
        rc, out = r(*args)
        assert rc == 1 and msg in out, (args, out)
    assert len(decs()) == n, "오류는 기록하지 않음"
    rc, out = r("--question", "q-0001", "--pick", "1")
    d = decs()[-1]
    assert rc == 0 and d["status"] == "예외" and d["reason"] == "런타임 배경" and d["questionId"] == "q-0001", (out, d)
    assert C.load_json(os.path.join(root, "questions.json"))[0]["status"] == "answered"
    with open(os.path.join(root, "manifest.json"), "rb") as f:
        assert f.read() == m_before, "템플릿 결정은 manifest(A2 reopen·A5·A6 무효)를 건드리지 않음"
    std = {s: ds_index.standard_of(t, decs()) for s, t in metas.items()}
    assert std == {"button-yellow": "표준", "button-yellow-new": "폐기→button-yellow",
                   "popup-bg-tall": "예외"}, std
    print("  템플릿 결정 검사 ok (정규화·오류 7종·supersedes·질문·manifest 불변·ds_index 호환)")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
