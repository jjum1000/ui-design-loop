"""state.py · record_decision.py 자체 테스트: 임시 ui-audit 루트에서 실제 UI 프리팹 2개로
H1 → A1 → A2 → A3 → H2 → A4 → H3 → A5 → A6 → 다음 배치 H1 을 끝까지 돌리고,
crash·검사 실패·한도·reopen 거부·결정 무효화·에이전트 결정(--by agent)·reset→skip 보류·최종 보고(F)→완료를 확인한다. (state.py --selftest / record_decision.py --selftest)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402



def _prefabs():
    """흐름 테스트에 쓸 UI 프리팹 2개(ui_root 기준): project.json selftest_prefabs, 없으면 서로 다른 폴더의 첫 프리팹 2개."""
    proj = C.project() or {}
    if proj.get("selftest_prefabs"):
        return list(proj["selftest_prefabs"])
    base = os.path.join(C.unity_root(), proj["ui_root"])
    picks, dirs = [], set()
    for dp, dn, fn in sorted(os.walk(base)):
        dn.sort()
        for f in sorted(fn):
            rel = os.path.relpath(os.path.join(dp, f), base).replace("\\", "/")
            if f.endswith(".prefab") and os.path.dirname(rel) not in dirs:
                picks.append(rel)
                dirs.add(os.path.dirname(rel))
                break
    assert len(picks) >= 2, "UI 프리팹이 있는 폴더가 2개 이상 필요: %s" % base
    return picks[:2]


PREFABS = _prefabs()


class Flow:
    def __init__(self):
        self.root = C.selftest_dir("state")
        for f in ("decisions.json", "questions.json"):
            with open(os.path.join(self.root, f), "w", encoding="utf-8") as fh:
                fh.write("[]\n")

    def r(self, script, *args, check=True):
        return C.run_script(self.root, script, *args, check=check)

    def m(self):
        return C.load_json(os.path.join(self.root, "manifest.json"))

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def nxt(self):
        return self.render()[0]

    def render(self):
        """(다음 행동, 명령)"""
        _rc, out = self.r("state.py", "render")
        get = lambda k: [x for x in out.splitlines() if x.startswith(k)][0].split(":", 1)[1].strip()  # noqa: E731
        return get("- 다음 행동:"), get("- 명령:")

    def chunks(self, b, s):
        return list(self.m()["batches"][b]["steps"][s]["chunks"])


def a2_answers(f, b, slug):
    inv = C.load_json(f.path("data", "inventory", b, slug + ".json"))
    pend = C.load_json(f.path("data", ".work", b, "A2", slug + ".pending.json")) or []
    paths = [x.split(" | ", 1)[0] for x in pend]
    ids = [n["id"] for n in inv["nodes"] if n["path"] in paths]
    ans = {}
    for i, nid in enumerate(ids):
        ans[nid] = ({"kind": "decor", "basis": "selftest", "confidence": "low", "options": "decor|icon"} if i == 0
                    else {"kind": "decor", "basis": "selftest", "confidence": "medium"})
    keys = list(ans)
    half = len(keys) // 2
    paths = []
    for i, part in enumerate((keys[:half], keys[half:])):
        path = f.path("data", ".work", b, "A2", "%s.answers%d.json" % (slug, i))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({k: ans[k] for k in part}, fh, ensure_ascii=False)
        paths.append(path)
    return paths


def flow_batch1(f):
    f.r("state.py", "init")
    rc, out = f.r("state.py", "init", check=False)
    assert rc != 0 and "거부" in out, "manifest 가 있으면 init 거부"
    nxt, cmd = f.render()
    assert nxt == "H1 배치 범위 확인 (b1) — 관문 에이전트 위임", nxt
    assert cmd == "서브에이전트에게: agents/H1.md를 읽고 batch=b1의 관문을 결정해", cmd
    f.r("batch.py", "create", "b1", *PREFABS)
    rc, out = f.r("state.py", "start", "b1", "A1", check=False)
    assert rc != 0 and "H1" in out, "H1 전에는 A1 시작 거부"
    f.r("state.py", "gate-done", "b1", "H1")
    assert f.nxt().startswith("A1 수집 (b1)"), f.nxt()
    # A1
    f.r("state.py", "start", "b1", "A1")
    slugs = f.chunks("b1", "A1")
    assert len(slugs) == 2
    for s in slugs:
        f.r("parse_prefab.py", "--batch", "b1", "--screen", s)
        f.r("validate.py", "--rename", f.path("data", "inventory", "b1", s + ".json.tmp"))
        f.r("state.py", "chunk-done", "b1", "A1", s, "--calls", "3")
    f.r("state.py", "step-done", "b1", "A1")
    # A2 + crash (새 세션) + 같은 세션 재시작
    f.r("state.py", "start", "b1", "A2")
    f.r("state.py", "render", "--new-session")
    st = f.m()["batches"]["b1"]["steps"]["A2"]
    assert st["crashes"] == 1 and st["status"] == "대기", st
    f.r("state.py", "start", "b1", "A2")
    f.r("state.py", "start", "b1", "A2")
    assert f.m()["batches"]["b1"]["steps"]["A2"]["crashes"] == 2
    for i, s in enumerate(slugs):
        rc, _out = f.r("classify_rules.py", "--batch", "b1", "--screen", s, check=False)
        if rc == 3:
            first, second = a2_answers(f, "b1", s)
            rc1, _o = f.r("classify_rules.py", "--batch", "b1", "--screen", s, "--answers", first, check=False)
            f.r("classify_rules.py", "--batch", "b1", "--screen", s, "--answers", second)  # 앞 파일의 답이 누적돼야 통과
        f.r("validate.py", "--rename", f.path("data", "classified", "b1", s + ".json.tmp"))
        if i == 0:
            f.r("state.py", "chunk-done", "b1", "A2", s)
            rc, out = f.r("state.py", "step-done", "b1", "A2", check=False)
            assert rc != 0 and "검사 실패" in out, "남은 조각이 있으면 step-done 실패"
            st = f.m()["batches"]["b1"]["steps"]["A2"]
            assert st["failures"] == 1 and st["status"] == "진행", st
        else:
            f.r("state.py", "chunk-done", "b1", "A2", s)
    f.r("state.py", "step-done", "b1", "A2")
    # A3
    f.r("state.py", "start", "b1", "A3")
    a3 = f.chunks("b1", "A3")
    assert a3, "A3 조각이 비어 있음"
    for c in a3:
        kind = f.m()["batches"]["b1"]["steps"]["A3"]["chunks"][c]["kind"]
        f.r("group.py", "run", "--batch", "b1", "--chunk", c)
        f.r("validate.py", "--rename", *[f.path("data", d, kind + ".json.tmp") for d in ("groups", "registry", "metrics")])
        f.r("state.py", "chunk-done", "b1", "A3", c)
    f.r("state.py", "step-done", "b1", "A3")
    # H2
    assert f.nxt() == "H2 그룹·표준 확인 (b1) — 관문 에이전트 위임", f.nxt()
    _rc, out = f.r("questions.py", "list", "H2")
    assert "q-0001" in out, "A2 low 확신도 질문이 있어야 함"
    f.r("state.py", "gate-done", "b1", "H2")
    # A4
    f.r("state.py", "start", "b1", "A4")
    for c in f.chunks("b1", "A4"):
        f.r("cluster_values.py", "run", "--batch", "b1", "--chunk", c)
        f.r("validate.py", "--rename", f.path("data", "tokens", c + ".json.tmp"), f.path("data", "token-registry", c + ".json.tmp"))
        f.r("state.py", "chunk-done", "b1", "A4", c)
    f.r("state.py", "step-done", "b1", "A4")
    f.r("state.py", "gate-done", "b1", "H3")
    # A5
    f.r("state.py", "start", "b1", "A5")
    for c in f.chunks("b1", "A5"):
        f.r("build_catalog.py", "--page", c)
        f.r("validate.py", "--rename", f.path("catalog"))
        f.r("state.py", "chunk-done", "b1", "A5", c)
    _rc, out = f.r("build_catalog.py", "--check")
    f.r("state.py", "step-done", "b1", "A5")
    # A6
    f.r("state.py", "start", "b1", "A6")
    a6 = f.chunks("b1", "A6")
    assert os.path.isdir(f.path("data", ".bak", "A6-b1"))
    text = ""
    for c in a6:
        f.r("build_catalog.py", "--samples", c)
        text += "## %s\n" % c + "".join("- 표본 %d: selftest | OK\n" % i for i in range(1, 6))
    os.makedirs(f.path("reports"), exist_ok=True)
    with open(f.path("reports", "review-b1.md.tmp"), "w", encoding="utf-8") as fh:
        fh.write(text)
    f.r("validate.py", "--rename", f.path("reports", "review-b1.md.tmp"))
    for c in a6:
        f.r("state.py", "chunk-done", "b1", "A6", c)
    f.r("state.py", "step-done", "b1", "A6")
    assert not [d for d in os.listdir(f.path("data", ".bak")) if d.endswith("-b1")], ".bak 이 지워져야 함"
    assert f.m()["current"]["batch"] == "b2"
    assert f.nxt() == "H1 배치 범위 확인 (b2) — 관문 에이전트 위임", f.nxt()


def flow_rules(f):
    rc, out = f.r("state.py", "reopen", "b1", "A3", "--chunks", "button", "--reason", "x", check=False)
    assert rc != 0 and "이전 배치" in out, "이전 배치 A3 reopen 은 거부"
    rc, out = f.r("state.py", "start", "b1", "A1", check=False)
    assert rc != 0 and "이미 완료" in out
    # limit: 나눌 수 없는 조각 2회 → 실패 1회
    m = f.m()
    assert m["batches"]["b1"]["steps"]["A1"]["status"] == "완료"


def flow_decisions(f):
    groups = C.load_json(f.path("data", "groups", "textstyle.json")) or C.load_json(
        C.iter_json(f.path("data", "groups"))[0])
    gid = groups["groups"][0]["id"]
    rc, out = f.r("record_decision.py", "nope-0000", "표준", check=False)
    assert rc == 1 and "없는 ID" in out, out
    f.r("record_decision.py", gid, "표준")
    m = f.m()
    assert m["batches"]["b1"]["steps"]["A5"]["status"] == "무효", "결정 뒤 직전 배치 A5 무효"
    assert f.nxt() == "A5 재빌드 (b1)", f.nxt()
    f.r("record_decision.py", gid, "폐기")
    decs = C.load_json(f.path("decisions.json"))
    assert decs[-1]["supersedes"] == decs[0]["id"] and decs[-1]["reason"] == "대체 미정"
    assert decs[-1]["by"] == "user", "기본은 by user"
    # 관문 에이전트 결정: --by agent 는 --reason 필수, 둘 다 기록
    rc, out = f.r("record_decision.py", gid, "표준", "--by", "agent", check=False)
    assert rc == 1 and "--reason" in out, out
    f.r("record_decision.py", gid, "표준", "--by", "agent", "--reason", "H2 규칙1: 노드 12 > 3")
    d = C.load_json(f.path("decisions.json"))[-1]
    assert d["by"] == "agent" and d["reason"] == "H2 규칙1: 노드 12 > 3" and d["supersedes"] == decs[-1]["id"], d
    rc, _out = f.r("record_decision.py", gid, "표준", "--by", "robot", check=False)
    assert rc != 0, "--by 는 user|agent 만"
    reg = C.load_json(f.path("data", "registry", gid.split("-")[0] + ".json"))
    reg["retired"]["button-dead"] = {"at": "x", "reason": "selftest", "successors": [gid]}
    reg["groups"]["button-dead"] = {"sigKey": "x", "createdAt": "x", "createdBatch": "b1"}
    C.write_json_atomic(f.path("data", "registry", gid.split("-")[0] + ".json"), reg)
    rc, out = f.r("record_decision.py", "button-dead", "표준", check=False)
    assert rc == 1 and "retired" in out and gid in out, out
    # T8: 중첩(템플릿 인스턴스) 노드에 분류 결정 → 대상은 템플릿 원본 노드 id, 스냅숏은 그 원본의 모든 인스턴스
    import template_scope
    open_q = {q["target"] for q in C.load_json(f.path("questions.json")) if q["status"] == "open"}
    nested = [n for f_ in C.iter_json(f.path("data", "inventory")) for n in C.load_json(f_)["nodes"] if n["nested"]
              and n["id"] not in open_q and template_scope.source_node_id(n) not in open_q]  # 아래 q-0001 은 열린 채로 둔다
    if nested:
        f.r("record_decision.py", nested[0]["id"], "분류", "icon", "--reason", "T8 selftest")
        d = C.load_json(f.path("decisions.json"))[-1]
        src = template_scope.source_node_id(nested[0])
        assert d["target"] == src and nested[0]["id"] in d["memberSnapshot"], d
        assert len(d["memberSnapshot"]) == sum(1 for n in nested if template_scope.source_node_id(n) == src)
    rc, out = f.r("record_decision.py", "--question", "q-0001", "--pick", "2", "--by", "agent", "--reason", "H2 분류 규칙")
    assert "분류" in out
    d = C.load_json(f.path("decisions.json"))[-1]
    assert d["by"] == "agent" and d["reason"] == "H2 분류 규칙" and d["questionId"] == "q-0001", d
    m = f.m()
    a2 = m["batches"]["b1"]["steps"]["A2"]
    assert a2["status"] == "대기" and a2["reopen"]["by"] == "decision", a2
    assert f.nxt().startswith("A2 분류 (b1)"), f.nxt()
    qs = C.load_json(f.path("questions.json"))
    assert qs[0]["status"] == "answered"
    # 한도: A2 조각을 두 번 limit → 나눌 수 없음 → 실패 1회
    f.r("state.py", "start", "b1", "A2")
    s = f.chunks("b1", "A2")[0]
    f.r("state.py", "limit", "b1", "A2", s)
    f.r("state.py", "start", "b1", "A2")
    f.r("state.py", "limit", "b1", "A2", s)
    st = f.m()["batches"]["b1"]["steps"]["A2"]
    # 앞의 step-done 검사 실패 1회 + 나눌 수 없는 한도 초과 1회 = 실패 2회
    assert st["failures"] == 2 and st["failedBy"] == "limit" and st["status"] == "실패", st
    nxt, cmd = f.render()
    assert nxt.startswith("사용자 확인 필요: b1 A2") and "reset 후 재시도" in nxt, nxt
    assert cmd == "python scripts/state.py reset b1 A2", cmd
    rc, out = f.r("state.py", "start", "b1", "A2", check=False)
    assert rc != 0 and "reset" in out
    f.r("state.py", "reset", "b1", "A2")
    assert f.nxt().startswith("A2 분류 (b1)"), f.nxt()
    _rc, out = f.r("state.py", "show", "b1", "A2")
    assert "reopen 사유" in out


def flow_skip(f):
    """reset 뒤 또 실패 2회 → render 가 skip 을 안내 → skip 이 미완료 조각을 보류로, 단계는 완료."""
    f.r("state.py", "start", "b1", "A2")
    s = f.chunks("b1", "A2")[0]
    rc, out = f.r("state.py", "skip", "b1", "A2", "--reason", "x", check=False)
    assert rc != 0 and "실패 2회일 때만" in out, "실패 전 skip 은 거부"
    for _ in range(2):
        rc, _out = f.r("state.py", "step-done", "b1", "A2", check=False)
        assert rc != 0
    st = f.m()["batches"]["b1"]["steps"]["A2"]
    assert st["status"] == "실패" and st["resets"] == 1, st
    nxt, cmd = f.render()
    assert nxt.startswith("사용자 확인 필요: b1 A2") and "skip" in nxt, nxt
    assert cmd.startswith("python scripts/state.py skip b1 A2 --reason"), cmd
    n_held = sum(1 for x in f.m()["batches"]["b1"]["steps"]["A2"]["chunks"].values() if x["status"] != "완료")
    rc, _out = f.r("state.py", "skip", "b1", "A2", check=False)
    assert rc == 2, "skip 은 --reason 필수"
    f.r("state.py", "skip", "b1", "A2", "--reason", "selftest 실패 2회")
    st = f.m()["batches"]["b1"]["steps"]["A2"]
    assert st["status"] == "완료" and st["skipped"] == "selftest 실패 2회", st
    assert st["chunks"][s]["status"] == "보류", st["chunks"]
    assert not f.nxt().startswith("사용자 확인 필요"), f.nxt()
    with open(f.path("reports", "blockers.md"), encoding="utf-8") as fh:
        text = fh.read()
    assert "b1 A2" in text and s in text and "selftest 실패 2회" in text, text
    with open(f.path("handoff", "log.md"), encoding="utf-8") as fh:
        assert "b1 A2 skip 보류" in fh.read()
    _rc, out = f.r("state.py", "show", "b1", "A2")
    assert "보류 조각 %d" % n_held in out and "남은 조각 0" in out, out
    rc, out = f.r("state.py", "skip", "b1", "A1", "--reason", "x", check=False)
    assert rc != 0 and "이미 완료" in out
    # 보류 뒤 reopen 은 재시도 기회를 준다 (곧바로 실패 2회로 되돌아가지 않음)
    f.r("state.py", "reopen", "b1", "A2", "--chunks", s, "--reason", "보류 조각 재시도")
    st = f.m()["batches"]["b1"]["steps"]["A2"]
    assert st["status"] == "대기" and st["failures"] == 1 and st["chunks"][s]["status"] == "대기", st
    assert not f.nxt().startswith("사용자 확인 필요"), f.nxt()


def flow_final(f):
    """마지막 배치 A6 을 skip 으로 끝내면 최종 보고(F), handoff/DONE 이 있으면 완료."""
    m = f.m()
    m["batchOrder"] = list(m["batches"])
    last = m["batchOrder"][-1]
    for b, B in m["batches"].items():
        B["gates"] = {g: "완료" for g in B["gates"]}
        for s, st in B["steps"].items():
            if st["status"] != "완료":
                st.update(status="완료", failures=0)
    a6 = m["batches"][last]["steps"]["A6"]
    a6.update(status="실패", failures=2, resets=1, chunks={"button": {"status": "대기", "limitHits": 0, "calls": 0}})
    m["ack"] = {g: [q["id"] for q in C.load_json(f.path("questions.json"))] for g in ("H2", "H3")}
    C.write_json_atomic(f.path("manifest.json"), m, "manifest")
    nxt, cmd = f.render()
    assert nxt.startswith("사용자 확인 필요: %s A6" % last) and "skip" in cmd, (nxt, cmd)
    f.r("state.py", "skip", last, "A6", "--reason", "selftest A6 보류")
    nxt, cmd = f.render()
    assert nxt.startswith("최종 보고(F)"), nxt
    assert cmd == "서브에이전트에게: agents/F.md를 읽고 최종 보고를 작성해", cmd
    _rc, out = f.r("state.py", "render")
    assert "보류 1" in out, out
    with open(f.path("handoff", "DONE"), "w", encoding="utf-8") as fh:
        fh.write("selftest\n")
    assert f.nxt().startswith("완료"), f.nxt()


def run():
    f = Flow()
    flow_batch1(f)
    flow_rules(f)
    flow_decisions(f)
    flow_skip(f)
    flow_final(f)
    with open(f.path("handoff", "log.md"), encoding="utf-8") as fh:
        n = len(fh.readlines())
    assert n > 20, "log.md 에 기록이 쌓여야 함"
    print("state.py / record_decision.py selftest ok (b1 H1~A6 → b2 H1 전체 흐름 + skip·F·완료, 로그 %d줄)" % n)
    return 0


def run_decisions():
    return run()


if __name__ == "__main__":
    sys.exit(run())
