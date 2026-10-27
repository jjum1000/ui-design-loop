"""진행 상태(manifest.json)의 유일한 수정 경로. 단계 상태: 대기·진행·완료·무효·실패.

사용:
  python scripts/state.py render [--new-session]   다음 행동 판단 + handoff/STATE.md 갱신 (새 세션은 남은 '진행'을 crash 로)
  python scripts/state.py show <batch> <step>        남은 조각·reopen 사유·명령 안내
  python scripts/state.py start <batch> <step>       위임 직전에 '진행' 기록 (crash 처리, .tmp 정리, .bak 스냅샷, 조각 채우기)
  python scripts/state.py chunk-done <batch> <step> <조각> [--calls N]
  python scripts/state.py step-done <batch> <step>   spec/steps.json 의 완료 조건 검사 후 완료
  python scripts/state.py limit <batch> <step> <조각>  한도로 조각을 끝냄 (limitHits+1)
  python scripts/state.py reopen <batch> <step> --chunks <조각들> --reason "<사유>"
  python scripts/state.py gate-done <batch> <H1|H2|H3>
  python scripts/state.py reset <batch> <step>        실패 2회 뒤 1회 재시도 (resets+1)
  python scripts/state.py skip <batch> <step> --reason "<사유>"   reset 뒤 또 실패 2회: 미완료 조각을 '보류'로, 단계는 보류 포함 완료
  python scripts/state.py init [--force-reset]        (A0 전용) manifest.json 생성
  python scripts/state.py --selftest
"""
import argparse
import glob
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

DONE, WAIT, RUN, VOID, FAIL = "완료", "대기", "진행", "무효", "실패"
HOLD = "보류"  # 조각 상태: skip 으로 미룬 조각 (완료 조건 검사에서 제외)
SPLIT_LIMIT = 300


# ---------------------------------------------------------------- 기본
def mpath():
    return C.p("manifest.json")


def load():
    m = C.load_json(mpath())
    if not m:
        raise SystemExit("manifest.json 없음 — A0 준비가 먼저 필요합니다")
    return m


def save(m):
    m["current"]["next"] = next_action(m)[0]
    C.write_json_atomic(mpath(), m, "manifest")


def new_step():
    return {"status": WAIT, "attempts": 0, "failures": 0, "crashes": 0, "resets": 0, "skipped": None,
            "failedBy": None, "startedAt": None,
            "finishedAt": None, "reopen": None, "lastCheck": None, "chunks": {}}


def new_batch():
    return {"gates": {g: WAIT for g in C.GATES}, "steps": {s: new_step() for s in C.STEPS}}


def plan():
    return C.load_json(C.p("spec", "batch-plan.json"))


def steps_spec():
    return C.load_json(C.p("spec", "steps.json"))


def batch_title(b):
    for x in (plan() or {}).get("batches", []):
        if x["batch"] == b:
            return x["title"]
    return ""


def die(msg):
    print(msg)
    raise SystemExit(1)


def get_step(m, b, s):
    if b not in m["batches"]:
        die("배치 %s 가 아직 시작되지 않음 (현재 %s)" % (b, m["current"]["batch"]))
    if s not in C.STEPS:
        die("단계는 %s 중 하나" % C.STEPS)
    return m["batches"][b]["steps"][s]


def unacked(m, gate):
    import questions
    return [q for q in questions.open_questions(gate) if q["id"] not in m["ack"][gate]]


def batch_done(m, b):
    B = m["batches"][b]
    return all(B["gates"][g] == DONE for g in C.GATES) and all(B["steps"][s]["status"] == DONE for s in C.STEPS)


def crash_running(m):
    n = 0
    for b, B in m["batches"].items():
        for s, st in B["steps"].items():
            if st["status"] == RUN:
                st["status"], st["failedBy"] = WAIT, "crash"
                st["crashes"] += 1
                C.append_log("%s %s crash (남아 있던 '진행')" % (b, s))
                n += 1
    return n


# ---------------------------------------------------------------- 다음 행동
def step_text(b, s, st):
    if s in ("A5", "A6") and st["status"] == VOID and st["finishedAt"]:
        label = "A5 재빌드" if s == "A5" else "A6 재검증"
    else:
        label = C.STEP_LABELS[s]
    extra = " — 진행 중 기록 있음(start 가 crash 로 처리)" if st["status"] == RUN else ""
    return "%s (%s)%s" % (label, b, extra), "python scripts/state.py start %s %s" % (b, s)


def next_action(m):
    """(문구, 명령)"""
    order = [b for b in m["batchOrder"] if b in m["batches"]]
    for b in order:
        for s in C.STEPS:
            st = m["batches"][b]["steps"][s]
            if st["status"] == FAIL or (st["status"] != DONE and st["failures"] >= 2):
                why = st["lastCheck"] or (st["reopen"] or {}).get("reason", "")
                if st.get("resets", 0):
                    hint = "이미 reset %d회 → skip 으로 보류" % st["resets"]
                    cmd = 'python scripts/state.py skip %s %s --reason "<실패 사유>"' % (b, s)
                else:
                    hint, cmd = "처음 → reset 후 재시도", "python scripts/state.py reset %s %s" % (b, s)
                return "사용자 확인 필요: %s %s 실패 %d회 — %s (자율 모드: %s)" % (b, s, st["failures"], why, hint), cmd
    cur = m["current"]["batch"]
    ci = order.index(cur)
    for b in order[:ci]:
        for s in ("A1", "A2"):
            st = m["batches"][b]["steps"][s]
            if st["status"] != DONE:
                t, c = step_text(b, s, st)
                return t + " — 이전 배치 재처리", c
    for b in reversed(order[:ci]):
        for s in ("A5", "A6"):
            st = m["batches"][b]["steps"][s]
            if st["status"] != DONE:
                return step_text(b, s, st)
    B = m["batches"][cur]
    for item in C.SEQUENCE:
        if item in C.GATES:
            if B["gates"][item] != DONE:
                return gate_text(C.STEP_LABELS[item], item, cur)
            continue
        if item == "A4" and unacked(m, "H2"):
            return gate_text("H2 추가 확인", "H2", cur)
        if item == "A5" and unacked(m, "H3"):
            return gate_text("H3 추가 확인", "H3", cur)
        st = B["steps"][item]
        if st["status"] != DONE:
            return step_text(cur, item, st)
    for g in ("H2", "H3"):
        if unacked(m, g):
            return gate_text("%s 추가 확인" % g, g, cur)
    if os.path.exists(C.p("handoff", "DONE")):
        return "완료 — 모든 배치 끝, 최종 보고 작성됨 (결정을 기록하면 A5 재빌드가 다음 행동이 됨)", "-"
    return "최종 보고(F) — 마지막 배치 %s 의 A6 까지 끝" % cur, "서브에이전트에게: agents/F.md를 읽고 최종 보고를 작성해"


def gate_text(label, gate, b):
    """관문은 사용자 확인이 아니라 관문 에이전트에게 위임한다 (자율 실행 모드)."""
    return ("%s (%s) — 관문 에이전트 위임" % (label, b),
            "서브에이전트에게: agents/%s.md를 읽고 batch=%s의 관문을 결정해" % (gate, b))


# ---------------------------------------------------------------- 조각 채우기
def batch_screens(b):
    data = C.load_json(C.p("batches", b + ".json"))
    if not data:
        die("batches/%s.json 없음 — H1 이 먼저 필요" % b)
    return [s["slug"] for s in data["screens"]]


def a3_targets(b):
    """종류별 {"targets": [...], "remove": [...]} — 이 배치 A3 스냅샷 기준으로 미배정 노드와 분류가 바뀐 노드.
    (스냅샷 기준이라 A3 이 무효가 돼 다시 채워도 이 배치에서 배정한 노드를 모두 다시 포함한다.)"""
    import group
    cls = C.all_classified()
    member_kind = {}
    snap = C.p("data", ".bak", "A3-%s" % b, "groups")
    base = snap if os.path.isdir(C.p("data", ".bak", "A3-%s" % b)) else C.p("data", "groups")
    for f in C.iter_json(base):
        g = C.load_json(f)
        for grp in g["groups"]:
            for mbr in grp["members"]:
                member_kind[mbr] = g["kind"]
    out = {}
    for nid, (_b, _s, r) in cls.items():
        if r.get("structural"):
            if nid in member_kind:
                out.setdefault(member_kind[nid], {"targets": [], "remove": []})["remove"].append(nid)
            continue
        old = member_kind.get(nid)
        if old != r["kind"]:
            out.setdefault(r["kind"], {"targets": [], "remove": []})["targets"].append(nid)
            if old:
                out.setdefault(old, {"targets": [], "remove": []})["remove"].append(nid)
    for nid, kind in member_kind.items():
        if nid not in cls:
            out.setdefault(kind, {"targets": [], "remove": []})["remove"].append(nid)
    inv = C.all_inventory()
    for kind, spec in out.items():
        spec["targets"].sort(key=lambda n: (group.signature(kind, inv[n][2])[0] if n in inv else "", n))
        spec["remove"].sort()
    return out


def write_a3_chunk(b, name, kind, targets, remove, rebuild=False):
    path = os.path.join(C.p("data", ".work", b, "A3"), name + ".json")
    C.write_json_atomic(path, {"kind": kind, "targets": targets, "remove": remove, "rebuild": rebuild})
    return {"status": WAIT, "limitHits": 0, "calls": 0, "kind": kind,
            "targets": os.path.relpath(path, C.ROOT).replace("\\", "/")}


def populate(m, b, s):
    if s in ("A1", "A2"):
        a1 = m["batches"][b]["steps"]["A1"]["chunks"]
        held = {c for c, x in a1.items() if x["status"] == HOLD} if s == "A2" else set()  # A1 에서 보류된 화면은 A2 도 보류
        return {x: {"status": HOLD if x in held else WAIT, "limitHits": 0, "calls": 0} for x in batch_screens(b)}
    if s == "A3":
        chunks = {}
        for kind, spec in sorted(a3_targets(b).items()):
            t = spec["targets"]
            if len(t) <= SPLIT_LIMIT:
                chunks[kind] = write_a3_chunk(b, kind, kind, t, spec["remove"])
            else:
                parts = [t[i:i + SPLIT_LIMIT] for i in range(0, len(t), SPLIT_LIMIT)]
                for i, part in enumerate(parts, 1):
                    chunks["%s-%d" % (kind, i)] = write_a3_chunk(b, "%s-%d" % (kind, i), kind, part,
                                                                 spec["remove"] if i == 1 else [])
        return chunks
    if s == "A4":
        return {x: {"status": WAIT, "limitHits": 0, "calls": 0} for x in C.TOKEN_CATEGORIES}
    if s == "A5":
        return {x: {"status": WAIT, "limitHits": 0, "calls": 0} for x in C.CATALOG_PAGES}
    kinds = {c.get("kind") for c in m["batches"][b]["steps"]["A3"]["chunks"].values()} - {None}
    for d in C.load_json(C.p("decisions.json"), []) or []:
        if d["batch"] == b and d["type"] == "그룹":
            kinds.add(d["target"].split("-")[0])
    if not kinds:
        kinds = {os.path.splitext(os.path.basename(f))[0] for f in C.iter_json(C.p("data", "groups"))}
    return {k: {"status": WAIT, "limitHits": 0, "calls": 0, "kind": k} for k in sorted(kinds or {"catalog"})}


def split_chunk(b, st, name):
    meta = st["chunks"][name]
    spec = C.load_json(os.path.join(C.ROOT, meta["targets"]))
    t = spec["targets"]
    if len(t) < 2:
        return False
    half = len(t) // 2
    del st["chunks"][name]
    st["chunks"][name + "a"] = write_a3_chunk(b, name + "a", meta["kind"], t[:half], spec["remove"], spec.get("rebuild", False))
    st["chunks"][name + "b"] = write_a3_chunk(b, name + "b", meta["kind"], t[half:], [], spec.get("rebuild", False))
    C.append_log("%s A3 split %s → %sa, %sb" % (b, name, name, name))
    return True


def splittable(st, name):
    meta = st["chunks"].get(name, {})
    if "targets" not in meta:
        return False
    spec = C.load_json(os.path.join(C.ROOT, meta["targets"])) or {}
    return len(spec.get("targets", [])) >= 2


# ---------------------------------------------------------------- 파일 정리
def fmt(pattern, b, chunk=None, kind=None):
    return pattern.replace("{batch}", b).replace("{chunk}", chunk or "").replace("{kind}", kind or chunk or "")


def clean_tmp(b, s):
    n = 0
    for pat in steps_spec()[s]["tmpdirs"]:
        d = C.p(fmt(pat, b))
        if os.path.isdir(d):
            for f in glob.glob(os.path.join(d, "**", "*.tmp"), recursive=True):
                os.remove(f)
                n += 1
    return n


def snapshot(b, s):
    dst = C.p("data", ".bak", "%s-%s" % (s, b))
    if os.path.isdir(dst):
        return False
    os.makedirs(dst)
    for pat in steps_spec()[s]["snapshot"]:
        src = C.p(fmt(pat, b))
        rel = os.path.relpath(src, C.p("data")) if src.startswith(C.p("data")) else os.path.relpath(src, C.ROOT)
        target = os.path.join(dst, rel)
        if os.path.isdir(src):
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("*.tmp"))
        elif os.path.isfile(src):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(src, target)
    return True


def drop_snapshots(b):
    for d in glob.glob(C.p("data", ".bak", "*-%s" % b)):
        shutil.rmtree(d)


# ---------------------------------------------------------------- 완료 조건 검사
def check_step(m, b, s):
    """[(조각 또는 None, 사유)]"""
    import validate
    spec = steps_spec()[s]
    st = m["batches"][b]["steps"][s]
    st = dict(st, chunks={c: x for c, x in st["chunks"].items() if x["status"] != HOLD})  # 보류 조각은 검사 제외
    bad = []
    for name in spec["checks"]:
        if name == "chunks_done":
            bad += [(c, "조각 미완료") for c, x in st["chunks"].items() if x["status"] != DONE]
        elif name in ("outputs_exist", "outputs_valid"):
            for c, x in st["chunks"].items():
                for pat in spec["outputs"]:
                    f = C.p(fmt(pat, b, c, x.get("kind")))
                    if not os.path.exists(f):
                        bad.append((c, "산출 없음: %s" % os.path.relpath(f, C.ROOT)))
                    elif name == "outputs_valid":
                        errs = validate.validate_file(f)
                        if errs:
                            bad.append((c, "스키마 오류 %s: %s" % (os.path.relpath(f, C.ROOT), errs[0])))
        elif name == "all_nodes_classified":
            for c in st["chunks"]:
                inv = C.load_json(C.p("data", "inventory", b, c + ".json")) or {"nodes": []}
                cl = C.load_json(C.p("data", "classified", b, c + ".json")) or {"nodes": []}
                got = {r["id"]: r for r in cl["nodes"]}
                miss = [n["id"] for n in inv["nodes"] if n["id"] not in got]
                lowq = [r["id"] for r in cl["nodes"] if r["confidence"] == "low" and not r.get("questionId")]
                if miss:
                    bad.append((c, "분류 안 된 노드 %d개 (예: %s)" % (len(miss), miss[0])))
                if lowq:
                    bad.append((c, "확신도 low 인데 질문 없음 %d개 (예: %s)" % (len(lowq), lowq[0])))
        elif name in ("targets_grouped", "no_foreign_members", "group_ids_kept"):
            bad += check_a3(m, b, st, name)
        elif name in ("values_mapped", "token_ids_kept"):
            bad += check_a4(b, st, name)
        elif name == "pages_exist":
            for page in C.CATALOG_PAGES:
                if not os.path.exists(C.p("catalog", page + ".html")):
                    bad.append((page, "페이지 없음: catalog/%s.html" % page))
        elif name == "catalog_links":
            import build_catalog
            for page, msg in build_catalog.check():
                bad.append((page if page in st["chunks"] else None, msg))
        elif name == "report_samples":
            f = C.p("reports", "review-%s.md" % b)
            if not os.path.exists(f):
                bad += [(c, "리포트 없음: reports/review-%s.md" % b) for c in st["chunks"]]
            else:
                with open(f, encoding="utf-8") as fh:
                    got = validate.report_chunks(fh.read())
                for c in st["chunks"]:
                    if got.get(c, 0) < 5:
                        bad.append((c, "리포트 절 '## %s' 표본 %d개 (5개 이상 필요)" % (c, got.get(c, 0))))
        else:
            die("spec/steps.json 의 알 수 없는 검사: " + name)
    return bad


def check_a3(m, b, st, name):
    bad = []
    cls = C.all_classified()
    kinds = {}
    for c, x in st["chunks"].items():
        kinds.setdefault(x["kind"], []).append(c)
    for kind, chunks in kinds.items():
        gfile = C.load_json(C.p("data", "groups", kind + ".json")) or {"groups": []}
        member = {mbr: g["id"] for g in gfile["groups"] for mbr in g["members"]}
        if name == "targets_grouped":
            for c in chunks:
                spec = C.load_json(os.path.join(C.ROOT, st["chunks"][c]["targets"])) or {"targets": []}
                miss = [t for t in spec["targets"] if t in cls and cls[t][2]["kind"] == kind and t not in member]
                if miss:
                    bad.append((c, "그룹에 없는 대상 노드 %d개 (예: %s)" % (len(miss), miss[0])))
        elif name == "no_foreign_members":
            foreign = [n for n in member if n not in cls or cls[n][2]["kind"] != kind or cls[n][2].get("structural")]
            if foreign:
                bad.append((chunks[0], "다른 종류·삭제된 노드가 %s 그룹에 남음 %d개 (예: %s)" % (kind, len(foreign), foreign[0])))
        else:
            snap = C.load_json(C.p("data", ".bak", "A3-%s" % b, "registry", kind + ".json"))
            if snap:
                reg = C.load_json(C.p("data", "registry", kind + ".json")) or {"groups": {}, "aliases": {}, "retired": {}}
                lost = [g for g in snap["groups"] if g not in reg["groups"]]
                lost += [g for g in snap["aliases"] if reg["aliases"].get(g) is None]
                lost += [g for g in snap["retired"] if g not in reg["retired"]]
                if lost:
                    bad.append((chunks[0], "기존 그룹 ID 가 사라짐 %d개 (예: %s)" % (len(lost), lost[0])))
    return bad


def check_a4(b, st, name):
    import cluster_values
    bad = []
    for c in st["chunks"]:
        tok = C.load_json(C.p("data", "tokens", c + ".json"))
        reg = C.load_json(C.p("data", "token-registry", c + ".json"))
        if not tok or not reg:
            continue
        if name == "values_mapped":
            exc = {e["value"] for e in tok["exceptions"]}
            miss = [k for k in cluster_values.collect(c) if k not in tok["mapping"] and k not in exc]
            if miss:
                bad.append((c, "토큰·예외에 없는 값 %d개 (예: %s)" % (len(miss), miss[0])))
        else:
            snap = C.load_json(C.p("data", ".bak", "A4-%s" % b, "token-registry", c + ".json"))
            if snap:
                lost = [t for t in snap["tokens"] if t not in reg["tokens"]]
                lost += [t for t in snap["aliases"] if t not in reg["aliases"]]
                lost += [t for t in snap["retired"] if t not in reg["retired"]]
                if lost:
                    bad.append((c, "기존 토큰 ID 가 사라짐 %d개 (예: %s)" % (len(lost), lost[0])))
    return bad


# ---------------------------------------------------------------- 명령
def cmd_init(force):
    if os.path.exists(mpath()) and not force:
        die("manifest.json 이 이미 있음 — 진행 상태를 잃으므로 거부 (--force-reset 을 사용자가 명시할 때만)")
    order = [x["batch"] for x in plan()["batches"]]
    m = {"version": 1, "current": {"batch": order[0], "next": ""}, "batchOrder": order,
         "ack": {"H2": [], "H3": []}, "batches": {order[0]: new_batch()}}
    save(m)
    print("manifest.json 생성: 배치 %s, 다음 행동 %s" % (order[0], m["current"]["next"]))


def cmd_render(new_session):
    if not os.path.exists(mpath()):
        print("A0 준비가 먼저 필요합니다 (manifest.json 없음)")
        return 1
    m = load()
    if new_session:
        n = crash_running(m)
        if n:
            print("이전 세션의 '진행' %d건을 crash 로 기록함" % n)
    save(m)
    text = render_text(m)
    os.makedirs(C.p("handoff"), exist_ok=True)
    with open(C.p("handoff", "STATE.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(text, end="")
    return 0


def render_text(m):
    import questions
    nxt, cmd = next_action(m)
    cur = m["current"]["batch"]
    opn = {g: len(questions.open_questions(g)) for g in ("H2", "H3")}
    new = {g: len(unacked(m, g)) for g in ("H2", "H3")}
    n_nodes = len(C.all_inventory()) if os.path.isdir(C.p("data", "inventory")) else 0
    n_groups = sum(len((C.load_json(f) or {}).get("groups", [])) for f in C.iter_json(C.p("data", "groups")))
    n_tokens = sum(len((C.load_json(f) or {}).get("tokens", [])) for f in C.iter_json(C.p("data", "tokens")))
    n_dec = len(C.load_json(C.p("decisions.json"), []) or [])
    lines = ["# UI 현황 정리 — 상태 요약", "",
             "scripts/state.py render 가 manifest.json 에서 만든 파일 (직접 고치지 마; 어긋나면 manifest 가 맞다)", "",
             "- 갱신: %s" % C.now_iso(),
             "- 현재 배치: %s (%s)" % (cur, batch_title(cur)),
             "- 다음 행동: %s" % nxt,
             "- 명령: %s" % cmd,
             "- 대기 질문: H2 %d건(새 %d) · H3 %d건(새 %d)" % (opn["H2"], new["H2"], opn["H3"], new["H3"]),
             "- 지표: 노드 %d · 그룹 %d · 토큰 %d · 결정 %d" % (n_nodes, n_groups, n_tokens, n_dec), ""]
    for b in [x for x in m["batchOrder"] if x in m["batches"]][-2:]:
        B = m["batches"][b]
        lines.append("## %s %s" % (b, batch_title(b)))
        lines.append("| " + " | ".join(C.SEQUENCE) + " |")
        lines.append("|" + "---|" * len(C.SEQUENCE))
        cells = []
        for item in C.SEQUENCE:
            if item in C.GATES:
                cells.append(B["gates"][item])
            else:
                st = B["steps"][item]
                ch = st["chunks"]
                done = sum(1 for x in ch.values() if x["status"] == DONE)
                held = sum(1 for x in ch.values() if x["status"] == HOLD)
                cells.append(("%s %d/%d" % (st["status"], done, len(ch)) + (" 보류 %d" % held if held else ""))
                             if ch else st["status"])
        lines.append("| " + " | ".join(cells) + " |")
        for s in C.STEPS:
            st = B["steps"][s]
            if st["reopen"] or st["failures"] or st["crashes"]:
                lines.append("- %s: 실패 %d · crash %d%s" % (s, st["failures"], st["crashes"],
                             " · reopen: %s" % st["reopen"]["reason"] if st["reopen"] else ""))
        lines.append("")
    log = C.p("handoff", "log.md")
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            tail = [x.rstrip("\n") for x in f.readlines() if x.strip()][-3:]
        if tail:
            lines += ["## 최근 로그"] + tail
    return "\n".join(lines[:40]) + "\n"


def cmd_show(b, s):
    m = load()
    st = get_step(m, b, s)
    print("%s %s: %s (시도 %d · 실패 %d · crash %d)" % (b, C.STEP_LABELS[s], st["status"], st["attempts"],
                                                     st["failures"], st["crashes"]))
    if st["reopen"]:
        print("reopen 사유 (먼저 해결): 조각 %s — %s [%s]" % (", ".join(st["reopen"]["chunks"]),
                                                       st["reopen"]["reason"], st["reopen"]["by"]))
    if st["lastCheck"] and st["lastCheck"] != "ok":
        print("마지막 검사: %s" % st["lastCheck"])
    todo = [c for c, x in st["chunks"].items() if x["status"] not in (DONE, HOLD)]
    done = [c for c, x in st["chunks"].items() if x["status"] == DONE]
    held = [c for c, x in st["chunks"].items() if x["status"] == HOLD]
    print("남은 조각 %d: %s" % (len(todo), ", ".join(todo) or "-"))
    print("완료 조각 %d: %s" % (len(done), ", ".join(done) or "-"))
    if held:
        print("보류 조각 %d (건너뛸 것): %s" % (len(held), ", ".join(held)))
    for c in todo:
        x = st["chunks"][c]
        if "targets" in x:
            spec = C.load_json(os.path.join(C.ROOT, x["targets"])) or {}
            print("  %s: 종류 %s, 대상 %d, 제외 %d%s → %s" % (c, x["kind"], len(spec.get("targets", [])),
                  len(spec.get("remove", [])), ", 재분할" if spec.get("rebuild") else "", x["targets"]))
        if x["limitHits"]:
            print("  %s: limitHits %d" % (c, x["limitHits"]))
    print("명령:")
    for line in steps_spec()[s]["commands"]:
        print("  " + fmt(line, b))
    return 0


def cmd_start(b, s):
    m = load()
    st = get_step(m, b, s)
    B = m["batches"][b]
    for item in C.SEQUENCE[:C.SEQUENCE.index(s)]:
        ok = B["gates"][item] == DONE if item in C.GATES else B["steps"][item]["status"] == DONE
        if not ok:
            die("거부: %s %s 가 끝나지 않음 (%s 보다 먼저)" % (b, item, s))
    if st["status"] == FAIL:
        die("거부: %s %s 는 실패 2회 — 사용자 확인 후 reset 필요" % (b, s))
    if st["status"] == DONE:
        die("거부: %s %s 는 이미 완료" % (b, s))
    crash_running(m)
    n_tmp = clean_tmp(b, s)
    snap = snapshot(b, s)
    if st["status"] == VOID or st["attempts"] == 0:
        keep = {c: x for c, x in st["chunks"].items() if st["reopen"] and c in st["reopen"]["chunks"]}
        st["chunks"] = populate(m, b, s)
        for c, x in keep.items():
            st["chunks"].setdefault(c, dict(x, status=WAIT))
    if s == "A3":
        for c in [c for c, x in st["chunks"].items() if x["limitHits"] >= 2 and x["status"] != DONE]:
            split_chunk(b, st, c)
    st["attempts"] += 1
    st["status"], st["startedAt"], st["failedBy"] = RUN, C.now_iso(), None
    save(m)
    C.append_log("%s %s start (시도 %d, .tmp 정리 %d, 스냅샷 %s)" % (b, s, st["attempts"], n_tmp, "새로" if snap else "기존"))
    return cmd_show(b, s)


def cmd_chunk_done(b, s, chunk, calls):
    m = load()
    st = get_step(m, b, s)
    if st["status"] == VOID:
        die("거부: %s %s 가 무효로 바뀜" % (b, s))
    if chunk not in st["chunks"]:
        die("조각 '%s' 없음: %s" % (chunk, ", ".join(st["chunks"])))
    x = st["chunks"][chunk]
    x["status"], x["calls"] = DONE, int(calls or 0)
    if st["reopen"] and chunk in st["reopen"]["chunks"]:
        st["reopen"]["chunks"] = [c for c in st["reopen"]["chunks"] if c != chunk]
        if not st["reopen"]["chunks"]:
            st["reopen"] = None
    save(m)
    C.append_log("%s %s chunk-done %s calls=%s" % (b, s, chunk, calls or 0))
    left = sum(1 for y in st["chunks"].values() if y["status"] != DONE)
    print("조각 완료: %s (남은 조각 %d)" % (chunk, left))
    return 0


def cmd_step_done(b, s):
    m = load()
    st = get_step(m, b, s)
    if st["status"] == VOID:
        die("거부: %s %s 가 무효로 바뀜 — 다시 start 부터" % (b, s))
    if st["status"] != RUN:
        die("거부: %s %s 상태가 '%s' (진행 중일 때만)" % (b, s, st["status"]))
    bad = check_step(m, b, s)
    if bad:
        chunks = sorted({c for c, _r in bad if c})
        for c in chunks:
            st["chunks"][c]["status"] = WAIT
        reason = "; ".join(r for _c, r in bad[:5])
        st["failures"] += 1
        st["lastCheck"] = reason
        st["reopen"] = {"chunks": chunks, "reason": reason, "by": "step-done"}
        st["failedBy"] = "check"
        if st["failures"] >= 2:
            st["status"] = FAIL
        save(m)
        C.append_log("%s %s step-done 실패 (%d회): %s" % (b, s, st["failures"], reason))
        print("검사 실패 (%d회) — 조각 %s 를 대기로 되돌림:" % (st["failures"], ", ".join(chunks) or "-"))
        for c, r in bad[:20]:
            print("  - [%s] %s" % (c or "-", r))
        if st["status"] == FAIL:
            print("실패 2회: 사용자 확인 필요")
        return 1
    st["status"], st["finishedAt"], st["lastCheck"], st["reopen"] = DONE, C.now_iso(), "ok", None
    st["skipped"] = None  # 보류했던 단계도 정상 완료되면 보류 표시를 지운다
    msg = complete_step(m, b, s, "%s %s step-done" % (b, s))
    save(m)
    C.append_log(msg)
    print("단계 완료: %s %s. 다음: %s" % (b, s, m["current"]["next"]))
    return 0


def complete_step(m, b, s, msg):
    """완료 처리 공통 (step-done·skip): A6 이면 스냅샷을 지우고, 배치가 끝났으면 다음 배치로."""
    if s == "A6":
        drop_snapshots(b)
        if b == m["current"]["batch"] and batch_done(m, b):
            i = m["batchOrder"].index(b)
            if i + 1 < len(m["batchOrder"]):
                nb = m["batchOrder"][i + 1]
                m["batches"].setdefault(nb, new_batch())
                m["current"]["batch"] = nb
                msg += " → 다음 배치 %s" % nb
    return msg


def cmd_skip(b, s, reason):
    m = load()
    st = get_step(m, b, s)
    if st["status"] == DONE:
        die("거부: %s %s 는 이미 완료" % (b, s))
    if st["status"] != FAIL or not st.get("resets", 0):
        die("거부: skip 은 reset 1회 뒤 다시 실패 2회일 때만 (%s %s: 상태 %s, 실패 %d, reset %d)" % (
            b, s, st["status"], st["failures"], st.get("resets", 0)))
    held =[c for c, x in st["chunks"].items() if x["status"] != DONE]
    for c in held:
        st["chunks"][c]["status"] = HOLD
    st["status"], st["finishedAt"], st["reopen"], st["failedBy"] = DONE, C.now_iso(), None, None
    st["failures"] = 0  # 남겨 두면 다음 reopen 이 곧바로 실패 2회로 되돌아가 재시도 없이 다시 skip 된다
    st["skipped"] = reason
    st["lastCheck"] = "보류 포함 완료: %s" % reason
    os.makedirs(C.p("reports"), exist_ok=True)
    f = C.p("reports", "blockers.md")
    new = not os.path.exists(f)
    with open(f, "a", encoding="utf-8", newline="\n") as fh:
        if new:
            fh.write("# 보류 항목 (state.py skip 이 추가)\n\n")
        fh.write("- %s %s %s 보류 조각 %d개 [%s] — %s\n" % (C.now_iso(), b, s, len(held), ", ".join(held) or "-", reason))
    msg = complete_step(m, b, s, "%s %s skip 보류 %s: %s" % (b, s, ",".join(held) or "-", reason))
    save(m)
    C.append_log(msg)
    print("보류 처리: %s %s 조각 %d개 → 단계 완료(보류 포함). 다음: %s" % (b, s, len(held), m["current"]["next"]))
    return 0


def cmd_limit(b, s, chunk):
    m = load()
    st = get_step(m, b, s)
    if chunk not in st["chunks"]:
        die("조각 '%s' 없음" % chunk)
    x = st["chunks"][chunk]
    x["limitHits"] += 1
    x["status"] = WAIT
    note = ""
    if x["limitHits"] >= 2 and not splittable(st, chunk):
        st["failures"] += 1
        x["limitHits"] = 0
        st["failedBy"] = "limit"
        st["lastCheck"] = "조각 %s 가 한도 2회 초과, 더 나눌 수 없음" % chunk
        note = " (나눌 수 없음 → 실패 %d회)" % st["failures"]
    elif x["limitHits"] >= 2:
        note = " (다음 start 가 절반으로 나눔)"
    if st["status"] == RUN:
        st["status"] = FAIL if st["failures"] >= 2 else WAIT
    save(m)
    C.append_log("%s %s limit %s limitHits=%d%s" % (b, s, chunk, x["limitHits"], note))
    print("한도 기록: %s %s %s%s" % (b, s, chunk, note))
    return 0


def reopen(m, b, s, chunks, reason, by="A6", count_failure=True):
    cur = m["current"]["batch"]
    if s not in ("A1", "A2", "A3", "A4", "A5"):
        die("reopen 은 A1~A5 만 가능")
    if b != cur and s in ("A3", "A4", "A5"):
        die("거부: 이전 배치(%s)의 %s 는 열 수 없음 — A3 이후는 누적 데이터라 현재 배치(%s)로 여세요" % (b, s, cur))
    st = get_step(m, b, s)
    opened = []
    for c in chunks:
        if c in st["chunks"]:
            st["chunks"][c].update(status=WAIT, limitHits=0)
            opened.append(c)
        elif s == "A3":
            kind = c.split("-")[0]
            if kind not in C.KINDS:
                die("A3 조각 이름은 종류 슬러그로 시작해야 함: %s" % c)
            cls = C.all_classified()
            targets = sorted(n for n, (_b, _s, r) in cls.items() if r["kind"] == kind and not r.get("structural"))
            parts = [targets[i:i + SPLIT_LIMIT] for i in range(0, len(targets), SPLIT_LIMIT)] or [[]]
            for i, part in enumerate(parts, 1):
                name = c if len(parts) == 1 else "%s-%d" % (c, i)
                st["chunks"][name] = write_a3_chunk(b, name, kind, part, [], rebuild=True)
                opened.append(name)
        elif s in ("A1", "A2") and c not in batch_screens(b):
            die("배치 %s 에 화면 '%s' 없음" % (b, c))
        else:
            st["chunks"][c] = {"status": WAIT, "limitHits": 0, "calls": 0}
            opened.append(c)
    if s == "A3" and "재분할" in reason:
        for c in opened:
            meta = st["chunks"][c]
            spec = C.load_json(os.path.join(C.ROOT, meta["targets"]))
            spec["rebuild"] = True
            C.write_json_atomic(os.path.join(C.ROOT, meta["targets"]), spec)
    if st["status"] in (DONE, RUN):
        st["status"] = WAIT
    if count_failure:
        st["failures"] += 1
        if st["failures"] >= 2:
            st["status"] = FAIL
    st["reopen"] = {"chunks": opened, "reason": reason, "by": by}
    st["lastCheck"] = reason
    B = m["batches"][b]
    if s == "A1" and B["steps"]["A2"]["attempts"]:
        a2 = B["steps"]["A2"]
        for c in chunks:
            a2["chunks"].setdefault(c, {"status": WAIT, "limitHits": 0, "calls": 0})["status"] = WAIT
        a2["status"] = WAIT
    first_void = {"A1": "A3", "A2": "A3", "A3": "A4", "A4": "A5", "A5": "A6"}[s]
    for later in C.STEPS[C.STEPS.index(first_void):]:
        lst = m["batches"][cur]["steps"][later]
        if (b, later) != (cur, s) and (lst["status"] in (DONE, RUN) or lst["attempts"]):
            lst["status"] = VOID
    for ob, OB in m["batches"].items():
        a6 = OB["steps"]["A6"]
        if ob != cur and a6["status"] == RUN:
            a6["status"], a6["finishedAt"] = DONE, C.now_iso()
            a6["lastCheck"] = "문제를 %s %s 로 넘기고 종료" % (b, s)
    C.append_log("%s %s reopen %s by=%s: %s" % (b, s, ",".join(chunks), by, reason))


def cmd_reopen(b, s, chunks, reason):
    m = load()
    reopen(m, b, s, chunks, reason, by="A6")
    save(m)
    print("reopen 기록: %s %s %s. 다음: %s" % (b, s, ",".join(chunks), m["current"]["next"]))
    return 0


def invalidate_for_decision(m):
    """결정이 기록되면 '현재 배치'의 A5·A6 을 무효로. 현재 배치가 H1 이면 직전(끝난) 배치."""
    order = m["batchOrder"]
    cur = m["current"]["batch"]
    target = cur
    if m["batches"][cur]["gates"]["H1"] != DONE and order.index(cur) > 0:
        target = order[order.index(cur) - 1]
    for s in ("A5", "A6"):
        st = m["batches"][target]["steps"][s]
        if st["status"] in (DONE, RUN):
            st["status"] = VOID
    return target


def cmd_gate_done(b, gate):
    import questions
    import validate
    m = load()
    if b not in m["batches"]:
        die("배치 %s 없음" % b)
    if gate not in C.GATES:
        die("관문은 H1·H2·H3")
    if gate == "H1":
        f = C.p("batches", b + ".json")
        if not os.path.exists(f):
            die("거부: batches/%s.json 없음 — batch.py create 를 먼저" % b)
        errs = validate.validate_file(f)
        if errs:
            die("거부: batches/%s.json 스키마 오류: %s" % (b, errs[0]))
    else:
        ids = [q["id"] for q in questions.open_questions(gate)]
        m["ack"][gate] = sorted(set(m["ack"][gate]) | set(ids))
    m["batches"][b]["gates"][gate] = DONE
    save(m)
    C.append_log("%s %s gate-done" % (b, gate))
    print("관문 완료: %s %s. 다음: %s" % (b, gate, m["current"]["next"]))
    return 0


def cmd_reset(b, s):
    m = load()
    st = get_step(m, b, s)
    st["failures"], st["failedBy"], st["lastCheck"] = 0, None, None
    st["resets"] = st.get("resets", 0) + 1
    if st["status"] in (FAIL, RUN):
        st["status"] = WAIT
    for x in st["chunks"].values():
        x["limitHits"] = 0
    save(m)
    C.append_log("%s %s reset (%d회)" % (b, s, st["resets"]))
    print("reset: %s %s. 다음: %s" % (b, s, m["current"]["next"]))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--new-session", action="store_true")
    ap.add_argument("--calls", type=int, default=0)
    ap.add_argument("--chunks", nargs="+")
    ap.add_argument("--reason")
    ap.add_argument("--force-reset", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        import state_selftest
        return state_selftest.run()
    c, x = a.cmd, a.args
    if c == "render":
        return cmd_render(a.new_session)
    if c == "init":
        return cmd_init(a.force_reset)
    if c == "show" and len(x) == 2:
        return cmd_show(*x)
    if c == "start" and len(x) == 2:
        return cmd_start(*x)
    if c == "chunk-done" and len(x) == 3:
        return cmd_chunk_done(x[0], x[1], x[2], a.calls)
    if c == "step-done" and len(x) == 2:
        return cmd_step_done(*x)
    if c == "limit" and len(x) == 3:
        return cmd_limit(*x)
    if c == "reopen" and len(x) == 2 and a.chunks and a.reason:
        return cmd_reopen(x[0], x[1], [y for z in a.chunks for y in z.split(",") if y], a.reason)
    if c == "gate-done" and len(x) == 2:
        return cmd_gate_done(*x)
    if c == "reset" and len(x) == 2:
        return cmd_reset(*x)
    if c == "skip" and len(x) == 2 and a.reason:
        return cmd_skip(x[0], x[1], a.reason)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
