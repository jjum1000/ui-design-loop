"""미결 질문(questions.json) 추가·목록·종료. 파일은 이 스크립트로만 바꾼다.

사용:
  python scripts/questions.py add --gate H2 --target <노드|그룹|토큰 id> --options "<보기1>|<보기2>"
        [--text "<질문>"] [--batch b1] [--evidence "<경로>|<경로>"]
      보기는 '라벨' 또는 '라벨::행동'. 행동을 생략하면 대상이 노드(#포함)면 '<대상> 분류 <라벨>',
      그 밖이면 '<라벨> 표준' 이 된다. 같은 관문·대상의 열린 질문이 있으면 새로 만들지 않는다.
  python scripts/questions.py list <H1|H2|H3> [--all]    모든 배치의 열린 질문 (--all 은 닫힌 것 포함)
  python scripts/questions.py close <q-id> [--status answered|dropped] [--answer "<답>"]
  python scripts/questions.py --selftest
답 기록은 record_decision.py --question <q-id> --pick <번호> 로 한다.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402


def path():
    return C.p("questions.json")


def load():
    return C.load_json(path(), []) or []


def save(qs):
    C.write_json_atomic(path(), qs, "questions")


def current_batch():
    m = C.load_json(C.p("manifest.json"))
    return m["current"]["batch"] if m else "b1"


def default_action(target, label):
    return "%s 분류 %s" % (target, label) if "#" in target else "%s 표준" % label


def add(gate, target, options, batch=None, text=None, evidence=None):
    qs = load()
    for q in qs:
        if q["status"] == "open" and q["gate"] == gate and q["target"] == target:
            return q["id"]
    opts = []
    for o in options:
        o = o.strip()
        if not o:
            continue
        label, _sep, action = o.partition("::")
        opts.append({"label": label.strip(), "action": action.strip() or default_action(target, label.strip())})
    if not opts:
        raise SystemExit("보기가 없음")
    n = max([int(q["id"][2:]) for q in qs] + [0]) + 1
    qid = "q-%04d" % n
    qs.append({"id": qid, "gate": gate, "batch": batch or current_batch(), "status": "open", "target": target,
               "text": text or "%s: 어느 쪽으로 할까요?" % target, "options": opts,
               "evidence": [e for e in (evidence or []) if e], "answer": None, "createdAt": C.now_iso()})
    save(qs)
    return qid


def close(qid, status="answered", answer=None):
    qs = load()
    hit = [q for q in qs if q["id"] == qid]
    if not hit:
        raise SystemExit("없는 질문 ID: %s" % qid)
    hit[0]["status"] = status
    hit[0]["answer"] = answer
    save(qs)


def close_for_target(targets, answer):
    qs = load()
    n = 0
    for q in qs:
        if q["status"] == "open" and q["target"] in targets:
            q["status"], q["answer"] = "answered", answer
            n += 1
    if n:
        save(qs)
    return n


def open_questions(gate=None):
    return [q for q in load() if q["status"] == "open" and (gate is None or q["gate"] == gate)]


def list_cmd(gate, show_all=False):
    qs = [q for q in load() if q["gate"] == gate and (show_all or q["status"] == "open")]
    if not qs:
        print("%s 열린 질문 없음" % gate)
        return 0
    for q in qs:
        print("%s [%s] %s%s" % (q["id"], q["batch"], q["text"], "" if q["status"] == "open" else " (%s)" % q["status"]))
        for i, o in enumerate(q["options"], 1):
            print("   %d) %s  →  %s" % (i, o["label"], o["action"]))
        if q["evidence"]:
            print("   근거: " + ", ".join(q["evidence"]))
    print("%s 질문 %d건. 답: python scripts/record_decision.py --question <q-id> --pick <번호>" % (gate, len(qs)))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", choices=["add", "list", "close"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--gate", choices=["H1", "H2", "H3"])
    ap.add_argument("--target")
    ap.add_argument("--options")
    ap.add_argument("--text")
    ap.add_argument("--batch")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--status", default="answered", choices=["answered", "dropped"])
    ap.add_argument("--answer")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.cmd == "add":
        if not (a.gate and a.target and a.options):
            print("add 는 --gate --target --options 가 필요")
            return 2
        print(add(a.gate, a.target, a.options.split("|"), a.batch, a.text, a.evidence.split("|")))
        return 0
    if a.cmd == "list":
        return list_cmd(a.args[0] if a.args else (a.gate or "H2"), a.all)
    if a.cmd == "close":
        close(a.args[0], a.status, a.answer)
        print("닫음: %s (%s)" % (a.args[0], a.status))
        return 0
    ap.print_help()
    return 2


def selftest():
    root = C.selftest_dir("questions")
    C.write_json_atomic(os.path.join(root, "questions.json"), [])
    _rc, out = C.run_script(root, "questions.py", "add", "--gate", "H2", "--target", "Assets/a.prefab#Root/Btn",
                            "--options", "button|tab", "--batch", "b1")
    assert out.strip() == "q-0001", out
    _rc, out = C.run_script(root, "questions.py", "add", "--gate", "H2", "--target", "Assets/a.prefab#Root/Btn",
                            "--options", "button|tab", "--batch", "b1")
    assert out.strip() == "q-0001", "중복 질문을 새로 만들면 안 됨"
    _rc, out = C.run_script(root, "questions.py", "add", "--gate", "H2", "--target", "button-a3f2",
                            "--options", "button-a3f2|button-7c1e::button-7c1e 표준", "--batch", "b1")
    qs = C.load_json(os.path.join(root, "questions.json"))
    assert qs[0]["options"][0]["action"] == "Assets/a.prefab#Root/Btn 분류 button"
    assert qs[1]["options"][0]["action"] == "button-a3f2 표준"
    _rc, out = C.run_script(root, "questions.py", "list", "H2")
    assert "q-0002" in out and "질문 2건" in out, out
    C.run_script(root, "questions.py", "close", "q-0001", "--status", "dropped")
    _rc, out = C.run_script(root, "questions.py", "list", "H2")
    assert "q-0001" not in out
    print("questions.py selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
