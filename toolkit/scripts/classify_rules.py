"""A2 분류: 이름·컴포넌트 구성 규칙과 사람이 정한 분류(decisions.json)로 노드를 분류한다.
규칙으로 정하지 못한 노드는 '미정'으로 남겨 에이전트가 스크린샷과 대조해 답을 채운다.

사용:
  python scripts/classify_rules.py --batch b1 --screen <화면>
      규칙 적용. 미정이 없으면 data/classified/<batch>/<화면>.json.tmp 를 쓴다.
      미정이 있으면 data/.work/<batch>/A2/<화면>.pending.json 에 목록을 쓰고 앞부분을 출력한다.
  python scripts/classify_rules.py --batch b1 --screen <화면> --pending [--offset N]
      미정 노드를 40개씩 출력 (이름, 컴포넌트, 크기, 스프라이트, 텍스트)
  python scripts/classify_rules.py --batch b1 --screen <화면> --answers <answers.json>
      에이전트 답을 합쳐 .tmp 를 쓴다. 답은 .work/<batch>/A2/<화면>.answers-store.json 에 누적되므로
      미정 목록을 나눠 여러 파일로 답해도 된다. answers.json 형식:
        {"<노드 id>": {"kind": "button", "basis": "스크린샷: 하단 확인 버튼", "confidence": "high|medium|low",
                      "options": "button|tab"}}   ← low 는 options 필수, 자동으로 H2 질문이 생긴다
  이어서 python scripts/validate.py --rename data/classified/<batch>/<화면>.json.tmp
  python scripts/classify_rules.py --selftest
종류 슬러그: button tab toggle popup slot gauge currency reddot tooltip toast listcell icon textstyle decor other
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


def words(name):
    return [w.lower() for w in WORD_RE.findall(name or "")]


def has(ws, name, *keys):
    low = (name or "").lower()
    return any(k in ws or (len(k) > 4 and k in low) for k in keys)


def decision_kinds():
    """대상 id(노드 id 또는 템플릿 원본 노드 id) -> 마지막 '분류' 결정의 종류. 순서 = 마지막 결정 순."""
    out = {}
    for d in C.load_json(C.p("decisions.json"), []) or []:
        if d["type"] == "분류":
            out.pop(d["target"], None)
            out[d["target"]] = d["kind"]
    return out


def pick_decision(n, dec, rank=None):
    """노드에 적용되는 분류 결정 종류: 노드 자신과 템플릿 원본 노드 중 나중에 기록된 결정. 없으면 None."""
    import template_scope
    keys = [k for k in (n["id"], template_scope.source_node_id(n)) if k and k in dec]
    if not keys:
        return None
    rank = rank or {t: i for i, t in enumerate(dec)}
    return dec[max(keys, key=lambda k: rank[k])]


def rule(n, scroll_paths):
    """(kind, basis, confidence, structural) 또는 None."""
    name = n["name"]
    ws = words(name)
    comps = set(n["components"])
    g, t, sel, lay = n["graphic"], n["text"], n["selectable"], n["layout"]
    r = n["rect"] or {"w": 0, "h": 0}
    small = 0 < max(r["w"], r["h"]) <= 80
    sprite_name = ((g or {}).get("sprite") or {}).get("name") or ""
    sprite_name = sprite_name.split("__", 1)[0] or sprite_name  # 화면별 사본 접미사 '__<프리팹명>' 제거
    sws = words(sprite_name)
    visual_comps = comps - {"RectTransform", "Transform", "CanvasRenderer", "GameObject"}
    if not g and not t and not sel and not n["canvas"]:
        if visual_comps and visual_comps <= {"ParticleSystem", "ParticleSystemRenderer", "UIParticle"}:
            return "other", "파티클 이펙트 노드", "high", True
        return "other", "그래픽·텍스트·입력 없는 컨테이너 (%s)" % (",".join(sorted(visual_comps)) or "빈 노드"), "high", True
    if n["canvas"] and not g and not t:
        return "other", "Canvas 루트", "high", True
    if t:
        return "textstyle", "텍스트 컴포넌트 %s" % t["component"], "high", False
    if sel and sel["type"] == "Toggle":
        if has(ws, name, "tab"):
            return "tab", "Toggle + 이름에 tab", "high", False
        return "toggle", "Toggle 컴포넌트", "high", False
    if sel and sel["type"] == "Slider":
        return "gauge", "Slider 컴포넌트", "high", False
    if sel and sel["type"] == "Scrollbar":
        return "other", "Scrollbar 컴포넌트", "high", False
    if has(ws, name, "tab"):
        return "tab", "이름에 tab", "high" if sel else "medium", False
    if has(ws, name, "reddot", "badge", "noti", "alarm", "newmark") or ("red" in ws and "dot" in ws):
        return "reddot", "이름에 레드닷·알림 표기", "high" if small else "medium", False
    if has(ws, name, "tooltip"):
        return "tooltip", "이름에 tooltip", "high", False
    if has(ws, name, "toast"):
        return "toast", "이름에 toast", "high", False
    if g and g.get("imageType") == "Filled":
        return "gauge", "Image Filled 타입", "high" if has(ws, name, "gauge", "bar", "fill", "progress", "hp", "exp") else "medium", False
    if has(ws, name, "gauge", "progress", "progressbar", "hpbar", "expbar"):
        return "gauge", "이름에 게이지 표기", "medium", False
    if sel or "ButtonWidget" in comps:
        if has(ws, name, "slot"):
            return "slot", "버튼 + 이름에 slot", "medium", False
        return "button", "Selectable(%s)" % ((sel or {}).get("type") or "ButtonWidget"), "high", False
    if has(ws, name, "slot"):
        return "slot", "이름에 slot", "medium", False
    if has(ws, name, "currency", "gold", "gem", "coin", "goods", "money", "cash", "diamond", "crystal"):
        return "currency", "이름에 재화 표기", "medium", False
    if has(ws, name, "popup", "window") or "popup" in sws:
        return "popup", "이름·스프라이트에 popup", "high" if "popup" in sws else "medium", False
    if has(ws, name, "icon", "ico") or "icon" in sws:
        return "icon", "이름·스프라이트에 icon", "high" if has(ws, name, "icon", "ico") else "medium", False
    if any(n["id"].startswith(sp + "/") for sp in scroll_paths) and has(ws, name, "cell", "item", "element", "row", "unit"):
        return "listcell", "ScrollRect 안 + 이름에 cell/item", "medium", False
    if has(ws, name, "bg", "back", "background", "deco", "line", "dim", "shadow", "glow", "frame", "panel",
           "mask", "blur", "noise", "light", "effect", "fx", "border", "outline", "divider", "gradient", "rainbow"):
        return "decor", "이름에 배경·장식 표기", "high", False
    if g and g["color"][-2:] == "00":
        return "decor", "투명 그래픽(레이캐스트·마스크용)", "medium", False
    return None


def classify(inv, dec=None):
    """(records, pending) — records: 확정 기록, pending: 미정 노드."""
    dec = decision_kinds() if dec is None else dec
    scroll = [n["id"] for n in inv["nodes"] if "scroll" in n["flags"]]
    recs, pending = [], []
    rank = {t: i for i, t in enumerate(dec)}
    for n in inv["nodes"]:
        k = pick_decision(n, dec, rank)
        if k:
            recs.append({"id": n["id"], "kind": k, "basis": "사람이 정한 분류", "confidence": "high",
                         "by": "decision", "structural": False, "questionId": None})
            continue
        r = rule(n, scroll)
        if r:
            recs.append({"id": n["id"], "kind": r[0], "basis": r[1], "confidence": r[2], "by": "rule",
                         "structural": r[3], "questionId": None})
        else:
            pending.append(n)
    return recs, pending


def brief(n):
    r = n["rect"] or {}
    g = n["graphic"] or {}
    sp = (g.get("sprite") or {}).get("name") or "-"
    return "%s | %s | %sx%s | sprite=%s | color=%s | comps=%s" % (
        n["id"].split("#", 1)[1], n["name"], r.get("w"), r.get("h"), sp, g.get("color"),
        ",".join(c for c in n["components"] if c not in ("RectTransform", "CanvasRenderer")))


def paths(batch, screen):
    inv = C.p("data", "inventory", batch, screen + ".json")
    out = C.p("data", "classified", batch, screen + ".json")
    pend = C.p("data", ".work", batch, "A2", screen + ".pending.json")
    return inv, out, pend


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch")
    ap.add_argument("--screen")
    ap.add_argument("--answers")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not (a.batch and a.screen):
        ap.print_help()
        return 2
    inv_path, out, pend_path = paths(a.batch, a.screen)
    inv = C.load_json(inv_path)
    if not inv:
        print("inventory 없음: %s (A1 먼저)" % inv_path)
        return 1
    recs, pending = classify(inv)
    if a.pending:
        for n in pending[a.offset:a.offset + 40]:
            print(brief(n))
        print("미정 %d개 중 %d~%d" % (len(pending), a.offset, min(len(pending), a.offset + 40)))
        return 0
    if a.answers:
        import questions
        store = C.p("data", ".work", a.batch, "A2", a.screen + ".answers-store.json")
        answers = C.load_json(store, {}) or {}
        answers.update(C.load_json(a.answers) or {})
        C.write_json_atomic(store, answers)  # 나눠 답해도 앞선 답이 남도록 누적
        left = []
        for n in pending:
            ans = answers.get(n["id"])
            if not ans:
                left.append(n)
                continue
            if ans.get("kind") not in C.KINDS:
                print("잘못된 종류 '%s': %s" % (ans.get("kind"), n["id"]))
                return 1
            conf = ans.get("confidence", "medium")
            qid = None
            if conf == "low":
                if not ans.get("options"):
                    print("확신도 low 는 options 가 필요: %s" % n["id"])
                    return 1
                qid = questions.add("H2", n["id"], ans["options"].split("|"), batch=a.batch,
                                    text="%s 의 분류는? (근거: %s)" % (n["id"].split("#", 1)[1], ans.get("basis", "")))
            recs.append({"id": n["id"], "kind": ans["kind"], "basis": ans.get("basis") or "에이전트 판단",
                         "confidence": conf, "by": "agent", "structural": False, "questionId": qid})
        pending = left
    if pending:
        C.write_json_atomic(pend_path, [brief(n) for n in pending])
        for n in pending[:40]:
            print(brief(n))
        print("규칙 %d개 확정, 미정 %d개 → %s" % (len(recs), len(pending), pend_path))
        print("미정 노드를 스크린샷과 대조해 answers.json 을 만든 뒤 --answers 로 다시 실행하세요.")
        return 3
    order = {n["id"]: i for i, n in enumerate(inv["nodes"])}
    recs.sort(key=lambda r: order[r["id"]])
    tmp = C.write_tmp(out, {"batch": a.batch, "screen": a.screen, "updatedAt": C.now_iso(), "nodes": recs})
    by = {}
    for r in recs:
        by[r["kind"]] = by.get(r["kind"], 0) + 1
    print("분류 %d개 %s → %s" % (len(recs), by, tmp))
    print("다음: python scripts/validate.py --rename %s" % os.path.relpath(tmp, C.ROOT).replace("\\", "/"))
    return 0


def selftest():
    def node(name, comps, g=None, t=None, sel=None, flags=(), w=100, h=50):
        return {"id": "Assets/x.prefab#Root/" + name, "name": name, "components": ["RectTransform"] + comps,
                "graphic": g, "text": t, "selectable": sel, "layout": None, "canvas": None, "flags": list(flags),
                "rect": {"w": w, "h": h}}
    img = {"type": "Image", "color": "#FFFFFFFF", "sprite": {"name": "Popup_BG_Wide"}, "imageType": "Simple"}
    inv = {"nodes": [
        node("Body", []),
        node("Title", ["CustomTextMeshProUGUI"], t={"component": "CustomTextMeshProUGUI"}),
        node("ButtonConfirm", ["Button"], g=img, sel={"type": "Button"}),
        node("TabMenu", ["Toggle"], g=img, sel={"type": "Toggle"}),
        node("RedDot", ["Image"], g=img, w=30, h=30),
        node("HpFill", ["Image"], g=dict(img, imageType="Filled")),
        node("Popup_BG_Wide", ["Image"], g=img),
        node("Bg", ["Image"], g=img),
        node("Mystery", ["Image"], g=dict(img, sprite={"name": "zz"})),
        node("Hole", ["Image"], g=dict(img, sprite={"name": "Ranks_Fill__CharacterTranscendencePopup"})),
    ]}
    recs, pending = classify(inv, dec={"Assets/x.prefab#Root/Bg": "popup"})
    got = {r["id"].split("/")[-1]: r["kind"] for r in recs}
    want = {"Body": "other", "Title": "textstyle", "ButtonConfirm": "button", "TabMenu": "tab",
            "RedDot": "reddot", "HpFill": "gauge", "Popup_BG_Wide": "popup", "Bg": "popup"}
    assert got == want, got
    assert [n["name"] for n in pending] == ["Mystery", "Hole"]
    assert [r for r in recs if r["id"].endswith("/Bg")][0]["by"] == "decision"
    # 템플릿 원본 노드 결정은 모든 인스턴스에 적용되고, 노드 결정과 겹치면 나중 결정이 이긴다
    ns = {"prefab": "Assets/t/Btn.prefab", "guid": "g", "instanceRoot": "Root/Btn"}
    a = dict(node("Btn", ["Image"], g=img), id="Assets/x.prefab#Root/Btn", path="Root/Btn", nested=ns)
    b = dict(a, id="Assets/y.prefab#Root/Btn")
    assert [pick_decision(x, {"Assets/t/Btn.prefab#Btn": "icon"}) for x in (a, b)] == ["icon", "icon"]
    assert pick_decision(a, {"Assets/t/Btn.prefab#Btn": "icon", a["id"]: "decor"}) == "decor"
    assert pick_decision(a, {a["id"]: "decor", "Assets/t/Btn.prefab#Btn": "icon"}) == "icon"
    assert words("ImageBackground_01") == ["image", "background", "01"]
    print("classify_rules.py selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
