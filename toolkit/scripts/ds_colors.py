"""P1-3 의미 토큰 이름 초안: 빌드 툴이 직접 적은 색을 모아 색 토큰에 맞추고, 핵심 색에 역할 이름을 붙인다.

빌드 툴 = project.json `editor_build_tool_dir`(Unity 루트 기준) 아래에서 `PrefabUtility.SaveAsPrefabAsset` 을 호출하는 파일
        + 그 파일들이 이름으로 부르는 도우미 클래스(예: XxxUiKit) 중 색을 적은 파일.
색 리터럴 = "#RRGGBB(AA)" 문자열 · Hex("RRGGBB") · Hex(0xRRGGBB) · new Color(r,g,b[,a]) · new Color32(r,g,b,a).
          Color.white 류 상수는 따로 센다. 에디터 GUI 줄(GUI.·EditorGUI·GUILayout·Handles…)의 색은 뺀다.
토큰 일치 = 알파 같고 RGB 각 채널 ±6/255 (cluster_values.close 와 같은 기준). 토큰 멤버 정확 일치가 먼저,
          아니면 기준값(valueKey)과 가장 가까운 토큰.

사용 (ui-audit/ 에서):
  python scripts/ds_colors.py --scan            → ds/build-tool-colors.json
  python scripts/ds_colors.py --draft-names     → ds/token-names.draft.json (scan 결과 필요)
  python scripts/ds_colors.py --review          → ds/token-names-review.md
  python scripts/ds_colors.py --approve [--set color-xxxx=name ...]   승인 → ds/token-names.json (사용자 승인 뒤에만)
  python scripts/ds_colors.py --set color-xxxx=name ...               지정한 것만 승인·이름 덮어쓰기
  python scripts/ds_colors.py --selftest
"""
import argparse
import ast
import collections
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

TOL = 6
CORE_N = 20
OUT_CORE_MIN_TOOLS = 3  # 토큰 밖 색이 이만큼의 툴에서 쓰이면 핵심 후보로 따로 올린다
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
EDITOR_REL = (C.project() or {}).get("editor_build_tool_dir", "Assets/Editor")  # UI 프리팹 빌드 툴(에디터 스크립트) 폴더

GUI_RE = re.compile(r"\bGUI\.|EditorGUI|GUILayout|EditorStyles|GUIStyle|Handles\.|Gizmos\.|\.textColor\b|\btextColor\s*=(?!=)|"
                    r"backgroundColor|contentColor|DrawRect|DrawColorSwatch|Debug\.Log|SceneView")
# 프리팹 조립 흔적: 컴포넌트 추가·노드 생성·Graphic 색 대입
UI_RE = re.compile(r"AddComponent\s*<|new\s+GameObject\s*\(|(?<!GUI)(?<!Handles)(?<!Gizmos)\.color\s*=|\bcolor\s*:|\bImage\b|TextMeshProUGUI|"
                   r"\bTMP_Text\b|\bGraphic\b|\bRawImage\b|\bOutline\b|\bShadow\b|RectTransform|SaveAsPrefabAsset|"
                   r"LoadPrefabContents|faceColor|outlineColor|ColorBlock|normalColor")
SIG_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:(?:public|private|protected|internal|static|override|virtual|async|"
                    r"unsafe|extern|new|partial|sealed)\s+)+[\w<>\[\],.? ]+?\s+\w+\s*(?:<[^>]*>)?\s*\(")
HEX_STR_RE = re.compile(r'"#([0-9A-Fa-f]{8}|[0-9A-Fa-f]{6})"')
HEX_CALL_STR_RE = re.compile(r'\b(\w*(?:Hex|Html|Col)\w*)\s*\(\s*"([0-9A-Fa-f]{8}|[0-9A-Fa-f]{6})"')
HEX_CALL_INT_RE = re.compile(r'\b(\w*Hex\w*)\s*\(\s*0x([0-9A-Fa-f]{6})\s*(?:,\s*([^,()]+?)\s*)?\)')
NEW_COLOR_RE = re.compile(r'\bnew\s+(Color32|Color)\s*\(')
CONST_RE = re.compile(r'\bColor\.(white|black|clear|red|green|blue|yellow|gray|grey|cyan|magenta)\b')
CONST_HEX = {"white": "#FFFFFFFF", "black": "#000000FF", "clear": "#00000000", "red": "#FF0000FF",
             "green": "#00FF00FF", "blue": "#0000FFFF", "yellow": "#FFEB04FF", "gray": "#7F7F7FFF",
             "grey": "#7F7F7FFF", "cyan": "#00FFFFFF", "magenta": "#FF00FFFF"}
STR_LIT_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
CLASS_RE = re.compile(r'\bstatic\s+(?:partial\s+)?class\s+(\w+)')
DECL_RE = re.compile(r'\b(?:var|Color32|Color)\s+(\w+)\s*=(?!=)')


# ---------------------------------------------------------------- 리터럴 파서
def _num(expr):
    """산술 리터럴 식(1f·51/255f·0x4C·(byte)0x33)을 값으로. 식별자가 섞이면 None."""
    s = re.sub(r"\(\s*(?:byte|float|int)\s*\)", "", expr.strip())
    s = re.sub(r"0[xX][0-9A-Fa-f]+", lambda m: str(int(m.group(0), 16)), s)
    s = re.sub(r"(?<=[0-9.])[fFdDmM]\b", "", s)
    if not s or not re.fullmatch(r"[0-9a-fA-FxX.+\-*/() ]+", s):
        return None
    try:
        node = ast.parse(s, mode="eval")
    except SyntaxError:
        return None
    for n in ast.walk(node):
        if not isinstance(n, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.operator, ast.unaryop)):
            return None
    try:
        v = eval(compile(node, "<lit>", "eval"), {"__builtins__": {}}, {})
    except (ZeroDivisionError, ValueError, TypeError):
        return None
    return float(v) if isinstance(v, (int, float)) else None


def _args(text, start):
    """text[start] 이 '(' 다음 위치일 때 최상위 쉼표로 나눈 인자와 닫는 위치."""
    depth, cur, out, i = 0, [], [], start
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                out.append("".join(cur))
                return out, i
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    return None, i


def _b(f):
    return max(0, min(255, int(round(f * 255))))


def to_key(rgba):
    return "#" + "".join("%02X" % max(0, min(255, int(v))) for v in rgba)


def literals_in_line(line):
    """한 줄 → [(시작 위치, 형식, 값 키 | None(못 푼 식), 원문)]. 주석 뒤는 보지 않는다."""
    code = line
    cut = _comment_pos(line)
    if cut is not None:
        code = line[:cut]
    hits, spans = [], []

    def add(m0, m1, form, key, raw):
        if any(a <= m0 < b for a, b in spans):
            return
        spans.append((m0, m1))
        hits.append((m0, form, key, raw))

    for m in HEX_CALL_STR_RE.finditer(code):
        h = m.group(2).upper()
        add(m.start(), m.end(), "hex", "#" + h + ("" if len(h) == 8 else "FF"), m.group(0))
    for m in HEX_CALL_INT_RE.finditer(code):
        h = m.group(2).upper()
        a = "FF"
        if m.group(3):
            av = _num(m.group(3))
            if av is None:
                add(m.start(), m.end(), "hex-int", None, m.group(0))
                continue
            a = "%02X" % (_b(av) if av <= 1 else int(av))
        add(m.start(), m.end(), "hex-int", "#" + h + a, m.group(0))
    for m in HEX_STR_RE.finditer(code):
        h = m.group(1).upper()
        add(m.start(), m.end(), "hex", "#" + h + ("" if len(h) == 8 else "FF"), m.group(0))
    for m in NEW_COLOR_RE.finditer(code):
        args, end = _args(code, m.end())
        raw = code[m.start():end + 1]
        if not args or len(args) not in (3, 4):
            add(m.start(), end, m.group(1), None, raw)
            continue
        vals = [_num(a) for a in args]
        if any(v is None for v in vals):
            add(m.start(), end, m.group(1), None, raw)
            continue
        if m.group(1) == "Color32":
            rgba = [int(round(v)) for v in vals] + ([255] if len(vals) == 3 else [])
        else:
            rgba = [_b(v) for v in vals] + ([255] if len(vals) == 3 else [])
        add(m.start(), end, m.group(1), to_key(rgba), raw)
    hits.sort()
    return hits


def _comment_pos(line):
    """문자열 밖의 // 위치."""
    in_s = False
    i = 0
    while i < len(line) - 1:
        ch = line[i]
        if ch == '"' and (i == 0 or line[i - 1] != "\\"):
            in_s = not in_s
        elif not in_s and ch == "/" and line[i + 1] == "/":
            return i
        i += 1
    return None


def line_context(line, pos):
    """리터럴 주변 문맥: 대입 대상 변수, 같은 줄 문자열(노드 이름), 주석, 감싼 호출 이름."""
    before = line[:pos]
    var = None
    m = re.search(r"(\w+)\s*(?:=|:)\s*[^=;:]*$", before)
    if m and m.group(1) not in ("new", "return"):
        var = m.group(1)
    call = None
    for cm in re.finditer(r"(\w+)\s*\(", before):
        if cm.group(1) not in ("new", "Color", "Color32", "Hex", "if", "for", "foreach", "while"):
            call = cm.group(1)
    cut = _comment_pos(line)
    comment = line[cut + 2:].strip() if cut is not None else ""
    strs = [s for s in STR_LIT_RE.findall(line[:cut] if cut is not None else line)
            if not re.fullmatch(r"#?[0-9A-Fa-f]{6,8}", s)]
    return {"var": var, "call": call, "strings": strs[:4], "comment": comment[:80]}


# ---------------------------------------------------------------- 토큰 매칭
def parse_hex(key):
    return [int(key[i:i + 2], 16) for i in (1, 3, 5, 7)]


def dist(a, b):
    """RGB 채널 최대 차(체비쇼프). 알파는 따로 비교."""
    ca, cb = parse_hex(a), parse_hex(b)
    return max(abs(x - y) for x, y in zip(ca[:3], cb[:3]))


def match_token(key, tokens, mapping):
    """(token id | None, 기준값과의 거리). tokens: [{id, valueKey}]"""
    if key in mapping:
        tid = mapping[key]
        vk = next(t["valueKey"] for t in tokens if t["id"] == tid)
        return tid, dist(key, vk)
    a = parse_hex(key)[3]
    best = None
    for t in tokens:
        if parse_hex(t["valueKey"])[3] != a:
            continue
        d = dist(key, t["valueKey"])
        if d <= TOL and (best is None or (d, -t.get("count", 0)) < (best[1], -best[2])):
            best = (t["id"], d, t.get("count", 0))
    return (best[0], best[1]) if best else (None, None)


def nearest_token(key, tokens):
    """토큰 밖 색 → 가장 가까운 토큰 {token, dist, alphaDiff}. 같은 알파 우선, 없으면 RGBA 전체 최대 차."""
    a = parse_hex(key)[3]
    same = [(dist(key, t["valueKey"]), t["id"]) for t in tokens if parse_hex(t["valueKey"])[3] == a]
    if same:
        d, tid = min(same)
        return {"token": tid, "dist": d, "alphaDiff": 0}
    ca = parse_hex(key)
    best = min(((max(abs(x - y) for x, y in zip(ca, parse_hex(t["valueKey"]))), t["id"], t["valueKey"]) for t in tokens))
    return {"token": best[1], "dist": dist(key, best[2]), "alphaDiff": abs(a - parse_hex(best[2])[3])}


# ---------------------------------------------------------------- 스캔
def editor_dir():
    return os.path.join(C.unity_root(), *EDITOR_REL.split("/"))


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def find_tools(edir):
    """(빌드 툴 rel 목록, 도우미 rel 목록). rel 은 Editor 기준 '/' 경로."""
    files = {}
    for base, _d, fns in os.walk(edir):
        for fn in fns:
            if fn.endswith(".cs"):
                full = os.path.join(base, fn)
                files[os.path.relpath(full, edir).replace("\\", "/")] = read(full)
    builders = sorted(r for r, c in files.items() if "PrefabUtility.SaveAsPrefabAsset" in c)
    bcode = "\n".join(files[r] for r in builders)
    helpers = []
    for r, c in sorted(files.items()):
        if r in builders or not (HEX_CALL_STR_RE.search(c) or HEX_CALL_INT_RE.search(c) or HEX_STR_RE.search(c)
                                 or NEW_COLOR_RE.search(c)):
            continue
        names = CLASS_RE.findall(c)
        if any(re.search(r"\b%s\s*\.|using\s+static\s+[\w.]*\b%s\s*;" % (n, n), bcode) for n in names):
            helpers.append(r)
    return builders, helpers, files


def method_regions(lines):
    """줄 번호(1부터) → 그 줄이 속한 메서드 영역의 성격 'ui' | 'gui' | 'none'.
    영역 = 메서드 시그니처 줄부터 다음 시그니처 직전까지(대략). 프리팹 조립 흔적이 있으면 ui,
    그것 없이 에디터 GUI 호출만 있으면 gui."""
    sigs = [i for i, ln in enumerate(lines) if SIG_RE.match(ln) and "=" not in ln.split("(")[0] and ";" not in ln]
    bounds = sorted(set([0] + sigs + [len(lines)]))
    kind = {}
    for start, end in zip(bounds, bounds[1:]):
        seg = "\n".join(lines[start:end])
        if UI_RE.search(seg):
            kd = "ui"
        elif GUI_RE.search(seg) or re.search(r"\bvoid\s+OnGUI\b", seg):
            kd = "gui"
        else:
            kd = "none"
        for j in range(start, end):
            kind[j + 1] = kd
    # 조립·GUI 흔적이 둘 다 없는 영역(도우미 호출만 하는 조립 메서드가 흔하다)은 파일의 우세 성격을 따른다
    ui_n = sum(1 for s, e in zip(bounds, bounds[1:]) if kind.get(s + 1) == "ui")
    gui_n = sum(1 for s, e in zip(bounds, bounds[1:]) if kind.get(s + 1) == "gui")
    default = "ui" if ui_n >= gui_n else "none"
    return {j: (default if k == "none" else k) for j, k in kind.items()}


def scan_file(rel, code, users=()):
    """→ (locs, consts, unresolved, skipped). locs: [{file,line,form,key,raw,ctx,decl,refs}]
    users: 이 파일(도우미)을 부르는 빌드 툴 코드들 — 필드 상수의 참조를 거기서도 찾는다.
    skipped: [{file,line,why, raw}] — why: 'gui'(에디터 GUI 줄·영역) | 'noui'(GUI 가 우세한 파일에서 조립 흔적
    없는 영역) | 'unused'(아무 데서도 안 쓰는 필드 상수)"""
    lines = code.split("\n")
    region = method_regions(lines)
    locs, consts, unresolved, skipped = [], [], [], []
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*") or s.startswith("///"):
            continue
        is_gui = bool(GUI_RE.search(ln))
        for pos, form, key, raw in literals_in_line(ln):
            ctx = line_context(ln, pos)
            d = DECL_RE.search(ln)
            decl = d.group(1) if d and d.start() < pos else None
            field = bool(decl and re.search(r"\b(?:static|readonly|const)\b", ln))
            refs, ref_lines, ref_strs = 0, [], []
            if field:  # 필드 상수는 참조한 곳의 성격을 따른다
                for j, l2 in enumerate(lines, 1):
                    if j != i and re.search(r"\b%s\b" % re.escape(decl), l2):
                        refs += 1
                        ref_lines.append(j)
                        cut = _comment_pos(l2)
                        ref_strs += [x for x in STR_LIT_RE.findall(l2[:cut] if cut is not None else l2)][:2]
                kinds = {("gui" if GUI_RE.search(lines[j - 1]) else region[j]) for j in ref_lines}
                for ucode in users:
                    ulines = [u for u in ucode.split("\n") if re.search(r"\b%s\b" % re.escape(decl), u)]
                    refs += len(ulines)
                    for u in ulines:
                        kinds.add("gui" if GUI_RE.search(u) else "ui")
                        cut = _comment_pos(u)
                        ref_strs += STR_LIT_RE.findall(u[:cut] if cut is not None else u)[:2]
                where = "ui" if "ui" in kinds else ("gui" if "gui" in kinds else ("noui" if kinds else "unused"))
            else:
                where = "gui" if is_gui else region[i]
                where = "noui" if where == "none" else where
            if where != "ui":
                skipped.append({"file": rel, "line": i, "why": where, "key": key, "raw": raw[:80]})
                continue
            if key is None:
                unresolved.append({"file": rel, "line": i, "raw": raw[:100]})
                continue
            locs.append({"file": rel, "line": i, "form": form, "key": key, "raw": raw[:100], "ctx": ctx,
                         "decl": decl if field else None, "refs": refs, "refStrings": ref_strs[:6]})
        if not is_gui and region[i] == "ui":
            cut = _comment_pos(ln)
            for m in CONST_RE.finditer(ln[:cut] if cut is not None else ln):
                consts.append({"file": rel, "line": i, "name": m.group(1)})
    return locs, consts, unresolved, skipped


def token_usage(tokens_doc):
    """토큰별 화면 사용: {tid: {nodes, screens, text, graphic, names: Counter, kinds: Counter}}"""
    import cluster_values as CV
    inv = C.all_inventory()
    grouped = CV.grouped_nodes()
    mapping = tokens_doc["mapping"]
    use = {}

    def add(tid, screen, n, kind, is_text):
        u = use.setdefault(tid, {"nodes": 0, "screens": set(), "text": 0, "graphic": 0,
                                 "names": collections.Counter(), "kinds": collections.Counter()})
        u["nodes"] += 1
        u["screens"].add(screen)
        u["text" if is_text else "graphic"] += 1
        u["names"][re.sub(r"\s*\(\d+\)$", "", n["name"])] += 1
        u["kinds"][kind] += 1

    for nid, kind in grouped.items():
        if nid not in inv:
            continue
        _b_, screen, n = inv[nid]
        g, t = n.get("graphic"), n.get("text")
        if g and (g.get("sprite") or g["color"][-2:] != "00") and g["color"] in mapping:
            add(mapping[g["color"]], screen, n, kind, False)
        if t and t["color"] in mapping:
            add(mapping[t["color"]], screen, n, kind, True)
    return use


def scan():
    edir = editor_dir()
    builders, helpers, files = find_tools(edir)
    tdoc = C.load_json(C.p("data", "tokens", "color.json"))
    tokens, mapping = tdoc["tokens"], tdoc["mapping"]
    tok_by = {t["id"]: t for t in tokens}
    all_locs, all_consts, unresolved, skipped_list = [], [], [], []
    for rel in builders + helpers:
        names = CLASS_RE.findall(files[rel])  # 정적 클래스(도우미)면 다른 빌드 툴이 필드 상수를 쓴다
        users = [files[b] for b in builders if b != rel
                 and any(re.search(r"\b%s\s*\.|using\s+static\s+[\w.]*\b%s\s*;" % (n, n), files[b]) for n in names)]
        locs, consts, unr, sk = scan_file(rel, files[rel], users)
        all_locs += locs
        all_consts += consts
        unresolved += unr
        skipped_list += sk
    skipped = collections.Counter(x["why"] for x in skipped_list)
    usage = token_usage(tdoc)

    colors = {}
    for loc in all_locs:
        e = colors.setdefault(loc["key"], {"hex": loc["key"], "locations": []})
        e["locations"].append(loc)
    out_colors = []
    for key, e in colors.items():
        tid, d = match_token(key, tokens, mapping)
        tools = sorted({x["file"] for x in e["locations"]})
        rec = {"hex": key, "token": tid, "tokenDist": d, "tools": len(tools), "literals": len(e["locations"]),
               "refs": sum(x["refs"] for x in e["locations"]), "toolFiles": tools,
               "forms": dict(collections.Counter(x["form"] for x in e["locations"]))}
        if tid is None:
            rec["nearest"] = nearest_token(key, tokens)
        rec["locations"] = [{k: x[k] for k in ("file", "line", "form", "raw", "ctx", "decl", "refs", "refStrings")}
                            for x in e["locations"]]
        out_colors.append(rec)
    out_colors.sort(key=lambda r: (-r["tools"], -r["literals"], r["hex"]))

    consts = {}
    for c in all_consts:
        e = consts.setdefault(c["name"], {"name": "Color." + c["name"], "hex": CONST_HEX[c["name"]], "count": 0,
                                          "tools": set()})
        e["count"] += 1
        e["tools"].add(c["file"])
    const_list = []
    for e in sorted(consts.values(), key=lambda e: -e["count"]):
        tid, _d = match_token(e["hex"], tokens, mapping)
        const_list.append({"name": e["name"], "hex": e["hex"], "token": tid, "count": e["count"],
                           "tools": len(e["tools"])})

    # 토큰 단위 묶음
    groups = {}
    for r in out_colors:
        gk = r["token"] or ("hex:" + r["hex"])
        g = groups.setdefault(gk, {"key": gk, "token": r["token"], "hexes": [], "tools": set(), "literals": 0,
                                   "refs": 0, "constUses": 0, "constTools": set(), "consts": set()})
        g["hexes"].append(r["hex"])
        g["tools"].update(r["toolFiles"])
        g["literals"] += r["literals"]
        g["refs"] += r["refs"]
    for c in all_consts:
        tid, _d = match_token(CONST_HEX[c["name"]], tokens, mapping)
        if not tid:
            continue
        g = groups.setdefault(tid, {"key": tid, "token": tid, "hexes": [], "tools": set(), "literals": 0,
                                    "refs": 0, "constUses": 0, "constTools": set(), "consts": set()})
        g["constUses"] += 1
        g["constTools"].add(c["file"])
        g["consts"].add("Color." + c["name"])
    glist = []
    for g in groups.values():
        u = usage.get(g["token"]) if g["token"] else None
        t = tok_by.get(g["token"]) if g["token"] else None
        item = {"key": g["key"], "token": g["token"], "tokenValue": t["valueKey"] if t else None,
                "family": t["family"] if t else None, "hexes": sorted(g["hexes"]), "tools": len(g["tools"]),
                "toolFiles": sorted(g["tools"]), "literals": g["literals"], "refs": g["refs"],
                "constUses": g["constUses"], "constTools": len(g["constTools"]), "consts": sorted(g["consts"]),
                "constOnlyTools": len(g["constTools"] - g["tools"]),
                "screenNodes": u["nodes"] if u else 0, "screens": len(u["screens"]) if u else 0,
                "textShare": round(u["text"] / u["nodes"], 2) if u and u["nodes"] else None,
                "topNodeNames": [n for n, _c in u["names"].most_common(6)] if u else [],
                "topKinds": [k for k, _c in u["kinds"].most_common(3)] if u else []}
        if not g["token"]:
            item["nearest"] = nearest_token(g["hexes"][0], tokens)
        glist.append(item)
    for g in glist:
        g["score"] = round(core_score(g), 2)
    glist.sort(key=lambda g: (-g["score"], g["key"]))
    core = [g["key"] for g in glist if g["token"]][:CORE_N]
    core_out = [g["key"] for g in glist if not g["token"] and g["tools"] >= OUT_CORE_MIN_TOOLS]

    in_tok = [r for r in out_colors if r["token"]]
    by_form = {}
    for label, forms in (("hexOnly", {"hex", "hex-int"}), ("hexAndColor32", {"hex", "hex-int", "Color32"}),
                         ("all", None)):
        sel = [r for r in out_colors if forms is None or set(r["forms"]) & forms]
        by_form[label] = {"colors": len(sel), "inToken": sum(1 for r in sel if r["token"])}
    hi = [r for r in out_colors if "hex-int" in r["forms"]]
    plan_repro = {"form": "Hex(0xRRGGBB)", "colors": len(hi), "exactMember": sum(1 for r in hi if r["hex"] in mapping),
                  "within": sum(1 for r in hi if r["token"]),
                  "files": sorted({x["file"].split("/")[-1] for r in hi for x in r["locations"] if x["form"] == "hex-int"})}
    unused_hi = {x["key"] for x in skipped_list if x["why"] == "unused" and x["raw"].startswith("Hex(0x")} - {r["hex"] for r in hi}
    plan_repro["withUnused"] = {"colors": len(hi) + len(unused_hi),
                                "exactMember": plan_repro["exactMember"] + sum(1 for k in unused_hi if k in mapping),
                                "unusedAdded": sorted(unused_hi)}
    summary = {"planRepro": plan_repro, "builders": len(builders), "helpers": helpers, "toolsWithColor": len({x["file"] for x in all_locs}),
               "literals": len(all_locs), "uniqueColors": len(out_colors), "inToken": len(in_tok),
               "outOfToken": len(out_colors) - len(in_tok), "tokenGroups": sum(1 for g in glist if g["token"]),
               "byForm": by_form, "skipped": dict(skipped), "unresolved": len(unresolved),
               "constantUses": sum(c["count"] for c in const_list)}
    doc = {"generatedAt": C.now_iso(), "tolerance": TOL, "summary": summary, "core": core, "coreOutOfToken": core_out, "groups": glist,
           "colors": out_colors, "constants": const_list, "unresolved": unresolved, "skippedLocations": skipped_list,
           **({"plan": {"claimed": PLAN["claimed"], "source": PLAN["source"]}} if PLAN.get("claimed") else {})}
    os.makedirs(C.p("ds"), exist_ok=True)
    C.write_json_atomic(C.p("ds", "build-tool-colors.json"), doc)
    s = summary
    print("빌드 툴 %d + 도우미 %d, 색을 적은 파일 %d · 리터럴 %d · 고유 색 %d (토큰 안 %d / 밖 %d) · 토큰 묶음 %d"
          % (s["builders"], len(helpers), s["toolsWithColor"], s["literals"], s["uniqueColors"], s["inToken"],
             s["outOfToken"], s["tokenGroups"]))
    for k, v in by_form.items():
        print("  형식 %-14s 고유 %d · 토큰 안 %d" % (k, v["colors"], v["inToken"]))
    print("  제외: 에디터 GUI %d · GUI 우세 파일의 무흔적 영역 %d · 안 쓰는 필드 %d · 못 푼 식 %d · 상수 사용 %d"
          % (skipped["gui"], skipped["noui"], skipped["unused"], len(unresolved), s["constantUses"]))
    print("핵심 %d: %s" % (len(core), ", ".join(core)))
    return doc


def core_score(g):
    """툴 수(가장 무겁게; Color.* 상수로만 쓴 툴은 1/3) · 리터럴+참조 수 · 화면 사용(토큰일 때).
    토큰 밖은 화면 근거가 없어 감점."""
    import math
    s = (3.0 * g["tools"] + 1.0 * g["constOnlyTools"] + 1.0 * math.log2(1 + g["literals"] + g["refs"])
         + 0.5 * math.log2(1 + g["constUses"]))
    if g["token"]:
        s += 1.0 * math.log2(1 + g["screens"])
    else:
        s -= 2.0
    return s


# ---------------------------------------------------------------- 이름 초안
# 이름은 사람이 확정한다. 초안 표는 작업 공간 ds/token-names.seed.json 의 draft(빌드 툴 문맥·화면 노드 쓰임을 보고 고른 것):
# (토큰 id → 이름, 대안, 근거 요지, 사람이 판단할 점 | null). 근거 요지 뒤에 스캔 수치가 자동으로 붙는다.
# 분류: palette(눈에 보이는 색) / utility(투명·히트 영역 — 색이라기보다 장치)
SEED = C.load_json(C.p("ds", "token-names.seed.json")) or {}  # 프로젝트 데이터(없으면 빈 표) — install 이 덮어쓰지 않는다
DRAFT = {k: tuple(v) for k, v in SEED.get("draft", {}).items()}
UTILITY = set(SEED.get("utility", []))
# 토큰 밖 핵심 후보 — 승인 대상이 아니라 '토큰을 새로 둘지' 결정 재료. (hex → 이름, 대안, 근거 요지)
DRAFT_NEW = {k: tuple(v) for k, v in SEED.get("draftNew", {}).items()}
PLAN = SEED.get("plan") or {}  # 계획 문서의 주장 수치와 대조할 때만(claimed·source·claimNote·reproLine)


def draft_names():
    doc = C.load_json(C.p("ds", "build-tool-colors.json"))
    if not doc:
        raise SystemExit("먼저 --scan")
    groups = {g["key"]: g for g in doc["groups"]}
    out, seen = {}, set()
    for key in doc["core"]:
        g = groups[key]
        name, alt, note, decide = DRAFT.get(g["token"], ("?" + g["token"], [], "초안 없음 — 사람이 정할 것", None))
        if name in seen:
            raise SystemExit("초안 이름 중복: " + name)
        seen.add(name)
        e = {"name": name, "hex": g["tokenValue"], "why": note + " | " + evidence(g, doc), "alt": alt,
             "kind": "utility" if g["token"] in UTILITY else "palette", "tools": g["tools"],
             "literals": g["literals"], "screens": g["screens"], "members": g["hexes"]}
        if decide:
            e["decide"] = decide
        out[g["token"]] = e
    path = C.p("ds", "token-names.draft.json")
    C.write_json_atomic(path, out)
    print("초안 %d개 → %s" % (len(out), os.path.relpath(path, C.ROOT)))
    missing = [k for k in doc["core"] if groups[k]["token"] not in DRAFT]
    if missing:
        print("초안 표에 없는 핵심 토큰(이름 '?…' — 사람이 정할 것): " + ", ".join(missing))
    if doc.get("coreOutOfToken"):
        print("토큰 밖 핵심 후보(승인 대상 아님, 리뷰 표 참고): " + ", ".join(doc["coreOutOfToken"]))
    return out


def evidence(g, doc):
    vars_, nodes = collections.Counter(), collections.Counter()
    hexes = set(g["hexes"])
    for r in doc["colors"]:
        if r["hex"] not in hexes:
            continue
        for loc in r["locations"]:
            if loc["decl"]:
                vars_[loc["decl"]] += 1
            elif loc["ctx"]["var"]:
                vars_[loc["ctx"]["var"]] += 1
            for s in loc["ctx"]["strings"] + loc["refStrings"]:
                if re.fullmatch(r"[A-Za-z][\w ]{1,30}", s):
                    nodes[s] += 1
    parts = ["툴 %d·리터럴 %d" % (g["tools"], g["literals"])]
    if vars_:
        parts.append("변수 " + ", ".join(v for v, _c in vars_.most_common(4)))
    if nodes:
        parts.append("툴 노드 " + ", ".join(v for v, _c in nodes.most_common(4)))
    if g["screens"]:
        parts.append("화면 %d곳·노드 %d(텍스트 %d%%) %s" % (g["screens"], g["screenNodes"], round(100 * (g["textShare"] or 0)),
                                                   "/".join(g["topNodeNames"][:4])))
    return "; ".join(parts)


# ---------------------------------------------------------------- 리뷰 표
def review():
    doc = C.load_json(C.p("ds", "build-tool-colors.json"))
    draft = C.load_json(C.p("ds", "token-names.draft.json")) or {}
    if not doc:
        raise SystemExit("먼저 --scan")
    s = doc["summary"]
    groups = {g["key"]: g for g in doc["groups"]}
    L = ["# 의미 토큰 이름 초안 — 검토표 (P1-3)", "",
         "생성 %s · `scripts/ds_colors.py --review`. 승인은 `--approve [--set color-xxxx=name …]` (사용자 승인 뒤)." % doc["generatedAt"], "",
         "## 스캔 요약", "",
         "- 빌드 툴(`SaveAsPrefabAsset` 호출) %d개 + 도우미 %d개(%s), 그중 색을 직접 적은 파일 %d개" % (
             s["builders"], len(s["helpers"]), ", ".join(s["helpers"]) or "-", s["toolsWithColor"]),
         "- 리터럴 %d건 → 고유 색 %d종: 토큰 안 %d · 밖 %d (±%d/255, 알파 같음).%s" % (
             s["literals"], s["uniqueColors"], s["inToken"], s["outOfToken"], TOL, PLAN.get("claimNote", "")),
         "- 형식별: " + " · ".join("%s %d종(토큰 안 %d)" % (k, v["colors"], v["inToken"]) for k, v in s["byForm"].items()),
         "- 제외: 에디터 GUI(줄·메서드 영역) %d건, GUI 가 우세한 파일의 조립 흔적 없는 메서드 %d건, 아무 데서도 안 쓰는 "
         "필드 상수 %d건, 변수가 섞여 못 푼 식 %d건. `Color.white` 류 상수 %d건은 따로 셈. 제외 위치는 "
         "`build-tool-colors.json` 의 `skippedLocations`." % (
             s["skipped"].get("gui", 0), s["skipped"].get("noui", 0), s["skipped"].get("unused", 0), s["unresolved"],
             s["constantUses"]),
         repro_line(s), "",
         "## 핵심 색 %d — 제안 이름" % len(doc["core"]), "",
         "선정: 점수 = 3×툴 수 + (Color.* 상수로만 쓴 툴 수) + log2(1+리터럴+필드 참조) + 0.5×log2(1+상수 사용) "
         "+ log2(1+토큰이 쓰인 화면 수), 상위 %d 토큰. '툴'은 리터럴을 적은 툴 수(괄호 = 상수로만 쓴 툴 수 추가)." % CORE_N, "",
         "| # | 토큰 | 대표 hex | 제안 이름 | 대안 | 분류 | 툴 | 리터럴 | 화면 | 근거 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for i, key in enumerate(doc["core"], 1):
        g = groups[key]
        d = draft.get(g["token"], {})
        why = d.get("why", "-").replace("|", "/")
        tools = "%d%s" % (g["tools"], " (+%d)" % g["constOnlyTools"] if g["constOnlyTools"] else "")
        L.append("| %d | `%s` | `%s` | **%s** | %s | %s | %s | %d | %d | %s |" % (
            i, g["token"], g["tokenValue"], d.get("name", "-"), ", ".join(d.get("alt", [])) or "-",
            d.get("kind", "-"), tools, g["literals"], g["screens"], why))
    decide = [(draft[g]["name"], g, draft[g]["decide"]) for g in doc["core"] if draft.get(g, {}).get("decide")]
    if decide:
        L += ["", "## 사람이 판단할 점", ""]
        L += ["- **%s** (`%s`): %s" % (n, t, x) for n, t, x in decide]
    L += ["", "## 토큰 밖 핵심 후보 (툴 %d개 이상 — 토큰을 새로 둘지 결정)" % OUT_CORE_MIN_TOOLS, "",
          "승인 대상이 아니다(토큰 id 가 없다). 새 토큰을 만들거나 가장 가까운 토큰으로 흡수할지 정한 뒤 다시 스캔한다.", "",
          "| hex | 제안 이름 | 대안 | 툴 | 리터럴 | 최근접 토큰 | 거리 | 근거 |", "|---|---|---|---|---|---|---|---|"]
    for key in doc.get("coreOutOfToken", []):
        g = groups[key]
        h = g["hexes"][0]
        name, alt, note = DRAFT_NEW.get(h, ("-", [], "-"))
        L.append("| `%s` | **%s** | %s | %d | %d | `%s` | %d | %s |" % (
            h, name, ", ".join(alt) or "-", g["tools"], g["literals"], g["nearest"]["token"], g["nearest"]["dist"], note))
    L += ["", "## 같은 토큰으로 묶인 근접 Hex", "", "| 토큰 | 대표 | 빌드 툴이 쓴 값 |", "|---|---|---|"]
    for g in doc["groups"]:
        if g["token"] and len(g["hexes"]) > 1:
            L.append("| `%s` | `%s` | %s |" % (g["token"], g["tokenValue"], " · ".join("`%s`" % h for h in g["hexes"])))
    L += ["", "## 토큰 밖 색 (가장 가까운 토큰)", "", "| hex | 툴 | 리터럴 | 최근접 토큰 | 거리 | 위치 예 |", "|---|---|---|---|---|---|"]
    for r in doc["colors"]:
        if r["token"]:
            continue
        n = r["nearest"]
        loc = r["locations"][0]
        L.append("| `%s` | %d | %d | `%s` | %d%s | %s:%d |" % (
            r["hex"], r["tools"], r["literals"], n["token"], n["dist"], " (알파 %d 다름)" % n["alphaDiff"] if n["alphaDiff"] else "",
            loc["file"], loc["line"]))
    L += ["", "## 상수 (`Color.*`)", "", "| 상수 | hex | 토큰 | 사용 | 툴 |", "|---|---|---|---|---|"]
    for c in doc["constants"]:
        L.append("| `%s` | `%s` | %s | %d | %d |" % (c["name"], c["hex"], "`%s`" % c["token"] if c["token"] else "-",
                                                 c["count"], c["tools"]))
    L = [x for x in L if x is not None]
    path = C.p("ds", "token-names-review.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(L) + "\n")
    print("→ " + os.path.relpath(path, C.ROOT))


def repro_line(s):
    """seed plan.reproLine(계획 수치 대조 문장 서식)을 스캔 수치로 채운다. 없으면 None(줄 생략)."""
    fmt = PLAN.get("reproLine")
    if not fmt:
        return None
    return fmt % (", ".join(s["planRepro"]["files"]), ", ".join(s["planRepro"]["withUnused"]["unusedAdded"]),
                  s["planRepro"]["withUnused"]["colors"], s["planRepro"]["withUnused"]["exactMember"],
                  s["planRepro"]["colors"], s["planRepro"]["exactMember"], TOL, s["planRepro"]["within"], TOL)


# ---------------------------------------------------------------- 승인
def approve(draft_path, out_path, token_ids, sets, take_all):
    """초안(take_all 이면 전부) + sets 덮어쓰기 → out_path 에 병합 저장. 반환: 저장된 dict."""
    draft = C.load_json(draft_path) or {}
    cur = C.load_json(out_path) or {}
    chosen = dict(draft) if take_all else {}
    for tid, name in sets.items():
        if tid not in token_ids:
            raise SystemExit("없는 토큰: " + tid)
        base = dict(chosen.get(tid) or draft.get(tid) or {"hex": token_ids[tid], "why": "사용자 지정", "alt": []})
        base["name"] = name
        chosen[tid] = base
    if not chosen:
        raise SystemExit("승인할 것이 없다 (--approve 또는 --set)")
    now = C.now_iso()
    merged = dict(cur)
    for tid, e in chosen.items():
        if tid not in token_ids:
            raise SystemExit("없는 토큰: " + tid)
        if not NAME_RE.match(e["name"]):
            raise SystemExit("이름 형식 오류(소문자-하이픈): %s=%s" % (tid, e["name"]))
        merged[tid] = {"name": e["name"], "hex": e.get("hex") or token_ids[tid], "why": e.get("why", ""),
                       "alt": e.get("alt", []), "approvedAt": now}
    names = collections.Counter(e["name"] for e in merged.values())
    dup = [n for n, c in names.items() if c > 1]
    if dup:
        raise SystemExit("이름 중복: " + ", ".join(dup))
    C.write_json_atomic(out_path, merged)
    return merged


def parse_sets(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit("--set 형식: color-xxxx=name")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


# ---------------------------------------------------------------- 자체 테스트
def selftest():
    # 1) 리터럴 파서
    L = literals_in_line('var a = Hex("332d2d"); var b = new Color32(0x34, 0x2D, 0x2E, 0xFF); // Hex("ffffff")')
    assert [(f, k) for _p, f, k, _r in L] == [("hex", "#332D2DFF"), ("Color32", "#342D2EFF")], L
    L = literals_in_line('img.color = new Color(51/255f, 45f/255f, 0.1764706f); t.color = "#352F2F80";')
    assert [k for _p, _f, k, _r in L] == ["#332D2DFF", "#352F2F80"], L
    L = literals_in_line('x = Hex(0x454040); y = new Color(1f, 1f, 1f, alpha); z = new Color(0f, 0f, 0f, 0.6f);')
    assert [k for _p, _f, k, _r in L] == ["#454040FF", None, "#00000099"], L
    L = literals_in_line('c = new Color32((byte)51, (byte)45, (byte)45, 255); s = "http://a//b";')
    assert [k for _p, _f, k, _r in L] == ["#332D2DFF"], L
    L = literals_in_line('ColorUtility.TryParseHtmlString("#ABCDEF", out var c);')
    assert [k for _p, _f, k, _r in L] == ["#ABCDEFFF"], L
    ln = '    private static readonly Color Ink = Hex("332d2d"); // body text'
    ctx = line_context(ln, ln.index("Hex"))
    assert ctx["var"] == "Ink" and ctx["comment"] == "body text", ctx
    assert DECL_RE.search('private static readonly Color Ink = Hex("332d2d");').group(1) == "Ink"
    locs, consts, unr, sk = scan_file("T.cs", "\n".join([
        'static readonly Color Ink = Hex("332d2d");',
        'static readonly Color Tag = Hex("4caf50");',
        'private static void Build(GameObject root) {',
        '    var t = root.AddComponent<TextMeshProUGUI>(); MakeText(root, "Title", Ink);',
        '    GUI.color = new Color(0.4f, 0.8f, 0.4f);',
        '    img.color = Color.white;',
        '    var k = new Color(1, 1, 1, a);',
        '}',
        'private void OnGUI() {',
        '    EditorGUILayout.LabelField("x"); var c = new Color(0.2f, 0.2f, 0.2f); DrawTag(Tag);',
        '}',
        'private static Color Pick() {',
        '    return new Color(1f, 0f, 0f);',
        '}',
        'private void DrawHeader() {',
        '    GUILayout.Label("h");',
        '}',
        'static readonly Color Unused = Hex("123456");']))
    assert len(locs) == 1 and locs[0]["decl"] == "Ink" and locs[0]["refs"] == 1 and "Title" in locs[0]["refStrings"], locs
    assert collections.Counter(x["why"] for x in sk) == {"gui": 3, "noui": 1, "unused": 1} and len(unr) == 1 and [c["name"] for c in consts] == ["white"], (sk, unr, consts)
    # 2) ±6 매칭
    toks = [{"id": "color-23ac", "valueKey": "#332D2DFF", "count": 472},
            {"id": "color-aaaa", "valueKey": "#3A3434FF", "count": 5},
            {"id": "color-bfa4", "valueKey": "#000000FF", "count": 9},
            {"id": "color-a060", "valueKey": "#00000099", "count": 3}]
    assert match_token("#352F2FFF", toks, {}) == ("color-23ac", 2)
    assert match_token("#392D2DFF", toks, {}) == ("color-23ac", 6)
    assert match_token("#392F2FFF", toks, {}) == ("color-aaaa", 5)  # 둘 다 ±6 안이면 가까운 쪽
    assert match_token("#3A3434FF", toks, {}) == ("color-aaaa", 0)
    assert match_token("#3A3434FF", toks, {"#3A3434FF": "color-23ac"}) == ("color-23ac", 7)  # 멤버 우선
    assert match_token("#40393AFF", toks, {}) == ("color-aaaa", 6)
    assert match_token("#4A3434FF", toks, {}) == (None, None)
    assert match_token("#000000A0", toks, {}) == (None, None)  # 알파 다르면 불일치
    assert match_token("#00000099", toks, {}) == ("color-a060", 0)
    assert nearest_token("#4A3434FF", toks) == {"token": "color-aaaa", "dist": 16, "alphaDiff": 0}
    assert nearest_token("#000000A0", toks)["token"] == "color-a060"
    # 3) approve (임시 폴더, 실제 ds/token-names.json 은 건드리지 않는다)
    real = C.p("ds", "token-names.json")
    existed = os.path.exists(real)
    d = tempfile.mkdtemp(prefix="uiaudit-dscolors-")
    try:
        dp, op = os.path.join(d, "draft.json"), os.path.join(d, "names.json")
        with open(dp, "w", encoding="utf-8") as f:
            f.write(C.dump_json({"color-23ac": {"name": "ink", "hex": "#332D2DFF", "why": "w", "alt": ["text"]},
                                 "color-bfa4": {"name": "shade", "hex": "#000000FF", "why": "w", "alt": []}}))
        tid = {t["id"]: t["valueKey"] for t in toks}
        m = approve(dp, op, tid, {"color-bfa4": "overlay"}, True)
        assert m["color-23ac"]["name"] == "ink" and m["color-bfa4"]["name"] == "overlay" and "approvedAt" in m["color-23ac"]
        m = approve(dp, op, tid, {"color-aaaa": "ink-soft"}, False)
        assert set(m) == {"color-23ac", "color-bfa4", "color-aaaa"} and m["color-aaaa"]["hex"] == "#3A3434FF"
        for bad in ({"color-aaaa": "ink"}, {"color-zzzz": "x"}, {"color-aaaa": "Ink_Soft"}):
            try:
                approve(dp, op, tid, bad, False)
                raise AssertionError("거부해야 함: %s" % bad)
            except SystemExit:
                pass
        assert C.load_json(op)["color-aaaa"]["name"] == "ink-soft"  # 실패한 승인은 파일을 바꾸지 않는다
        assert parse_sets(["color-23ac=ink"]) == {"color-23ac": "ink"}
    finally:
        shutil.rmtree(d, True)
    assert os.path.exists(real) == existed, "selftest 가 실제 token-names.json 을 건드렸다"
    print("ds_colors selftest ok")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--draft-names", action="store_true")
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--set", nargs="+", metavar="TOKEN=NAME")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not any((a.scan, a.draft_names, a.review, a.approve, a.set)):
        ap.print_help()
        return
    if a.scan:
        scan()
    if a.draft_names:
        draft_names()
    if a.review:
        review()
    if a.approve or a.set:
        tdoc = C.load_json(C.p("data", "tokens", "color.json"))
        tid = {t["id"]: t["valueKey"] for t in tdoc["tokens"]}
        m = approve(C.p("ds", "token-names.draft.json"), C.p("ds", "token-names.json"), tid, parse_sets(a.set), a.approve)
        print("승인 %d개 → ds/token-names.json" % len(m))


if __name__ == "__main__":
    main(sys.argv[1:])
