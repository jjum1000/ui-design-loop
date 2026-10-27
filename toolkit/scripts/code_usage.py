"""T2b 코드 사용처: Addressable 그룹 파일(주소 <-> GUID)을 정답으로 삼아 코드·컴포넌트가 여는 UI 프리팹을 찾는다.

간선 종류(plan 0.1 계약):
  code-ui     UIBridge(UIType -> Controller) -> GetUIPrefabName() -> "UI_<마지막 토큰>_prefab" -> 그룹 -> 프리팹
  code-local  UIManager.localResourceUI 의 UIType -> Controller 경로 -> Resources/<경로>.prefab
  code-loader 프리팹 안 ResourcesLoader.addressableKey(+ PrefabInstance 수정값) -> 그룹 -> 프리팹 (user=프리팹)
              C# 문자열 리터럴 중 그룹의 UI 프리팹 주소와 같은 것(+ "UI_*_prefab" 형식) (user=.cs)
  code-wrap   프리팹 안 WrapContent.wrapContentPrefabDatas[].guids -> GUID 색인 -> 프리팹

Unity 프로젝트는 읽기만 한다. 주석 안 리터럴은 무시하고, 보간 문자열($"UI_{x}_prefab") 같은 동적 키는 unresolved 로 남긴다.
에디터 전용 스크립트(/Editor/, /EditorLevel/)의 리터럴은 런타임 사용이 아니라서 세기만 하고 간선으로 만들지 않는다.

사용:
  python scripts/code_usage.py --run        data/code-usage.json, data/usage/parts/code.json 을 쓰고 요약 출력
  python scripts/code_usage.py --selftest   합성 C#/YAML 로 파서 검사 + 실제 프로젝트 해석 검사(파일은 쓰지 않음)
"""
import argparse
import bisect
import collections
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import parse_prefab as PP  # noqa: E402
import template_scope as TS  # noqa: E402

# 프로젝트별 경로는 project.json "code" 에서 읽는다: roots(C# 스캔 루트) · resources_dir(Resources.Load 우선 폴더)
# · loader_scripts{resources_loader, wrap_content}(프리팹 안 로더 컴포넌트 스크립트)
_CODE = (C.project() or {}).get("code", {})
CS_ROOTS = _CODE.get("roots", ["Assets"])
GROUPS_DIR = "Assets/AddressableAssetsData/AssetGroups"
RESOURCES_DIR = _CODE.get("resources_dir", "Assets/Resources")
RESOURCES_LOADER_CS = _CODE.get("loader_scripts", {}).get("resources_loader")
WRAP_CONTENT_CS = _CODE.get("loader_scripts", {}).get("wrap_content")
SCREEN_SUFFIXES = ("View", "Popup")
OUT_MAIN = ("data", "code-usage.json")
OUT_PART = ("data", "usage", "parts", "code.json")

# ---------------------------------------------------------------- C# 스캐너
SPECIAL_RE = re.compile(r'//|/\*|"|\'')
PLAIN_STR_RE = re.compile(r'"(?:[^"\\\n]|\\.)*"')
VERBATIM_STR_RE = re.compile(r'"(?:[^"]|"")*"')
CHAR_RE = re.compile(r"'(?:[^'\\\n]|\\.){1,10}'")
CLASS_RE = re.compile(r"\b(?:class|struct)\s+(\w+)\s*(?:<[^>{]*>)?\s*(?::\s*([^{]+))?\{")
CONST_RE = re.compile(r"\bconst\s+string\s+(\w+)\s*=\s*(@?\"(?:[^\"\\\n]|\\.|\"\")*\")\s*;")
OVERRIDE_RE = re.compile(r"\boverride\s+string\s+GetUIPrefabName\s*\(\s*\)\s*")
RETURN_RE = re.compile(r"\breturn\s+([^;]+);")
BRIDGE_RE = re.compile(r"\{\s*UIType\.(\w+)\s*,\s*typeof\(\s*([\w.]+)\s*\)\s*\}")
LOCAL_LIST_RE = re.compile(r"\blocalResourceUI\s*=\s*new\s+HashSet<\s*UIType\s*>\s*(?:\(\s*\))?\s*\{([^}]*)\}")
UITYPE_RE = re.compile(r"UIType\.(\w+)")
EXPR_TOKEN_RE = re.compile(r"\s*(?:(@\"(?:[^\"]|\"\")*\")|(\"(?:[^\"\\]|\\.)*\")|([A-Za-z_][\w.]*)(?![\w.]|\s*\()|(\+))")
UI_KEY_RE = re.compile(r"^UI_\w+_prefab$")


class CsFile:
    """주석을 공백으로 지운 코드(줄 보존)와 문자열 리터럴 목록."""

    def __init__(self, rel, text):
        self.rel = rel
        self.code, self.lits = scan_cs(text)

    def line(self, off):
        return self.code.count("\n", 0, off) + 1


def _read_interp(text, i, verbatim):
    """i 는 여는 따옴표. 보간 문자열의 끝 다음 위치를 돌려준다(구멍 안의 중첩 문자열 처리)."""
    j, n, depth = i + 1, len(text), 0
    while j < n:
        ch = text[j]
        if depth == 0:
            if ch == "{" and text.startswith("{{", j):
                j += 2
                continue
            if ch == "{":
                depth = 1
            elif ch == '"':
                if verbatim and text.startswith('""', j):
                    j += 2
                    continue
                return j + 1
            elif ch == "\\" and not verbatim:
                j += 2
                continue
            elif ch == "\n" and not verbatim:
                return j
        else:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == '"':
                m = PLAIN_STR_RE.match(text, j)
                if m:
                    j = m.end()
                    continue
        j += 1
    return n


def scan_cs(text):
    """(주석을 지운 코드, [(offset, kind, raw)]) — kind: plain|verbatim|interp, raw 는 따옴표 안 원문."""
    out, lits, i, n = [], [], 0, len(text)
    while i < n:
        m = SPECIAL_RE.search(text, i)
        if not m:
            out.append(text[i:])
            break
        s = m.start()
        out.append(text[i:s])
        tok = m.group()
        if tok == "//":
            e = text.find("\n", s)
            e = n if e < 0 else e
            out.append(" " * (e - s))
            i = e
        elif tok == "/*":
            e = text.find("*/", s + 2)
            e = n if e < 0 else e + 2
            out.append(re.sub(r"[^\n]", " ", text[s:e]))
            i = e
        elif tok == "'":
            cm = CHAR_RE.match(text, s)
            e = cm.end() if cm else s + 1
            out.append(text[s:e])
            i = e
        else:  # '"' — 앞의 $/@ 접두사로 종류를 정한다
            pre = text[max(0, s - 2):s]
            interp = pre.endswith("$") or pre in ("$@", "@$")
            verbatim = pre.endswith("@") or pre in ("$@", "@$")
            if interp:
                e = _read_interp(text, s, verbatim)
                kind = "interp"
            else:
                sm = (VERBATIM_STR_RE if verbatim else PLAIN_STR_RE).match(text, s)
                e = sm.end() if sm else s + 1
                kind = "verbatim" if verbatim else "plain"
            raw = text[s + 1:e - 1] if e - s >= 2 else ""
            lits.append((s, kind, raw))
            out.append(text[s:e])
            i = e
    return "".join(out), lits


def literal_value(tok):
    if tok.startswith('@"'):
        return tok[2:-1].replace('""', '"')
    return tok[1:-1]


def eval_expr(expr, consts):
    """`StringDefine.X + "a/b"` 같은 상수·리터럴 연결만 계산한다. (값, None) 또는 (None, 사유)."""
    parts, pos, want_value = [], 0, True
    expr = expr.strip()
    while pos < len(expr):
        m = EXPR_TOKEN_RE.match(expr, pos)
        if not m or m.end() == pos:
            return None, "unsupported-expr"
        verb, plain, ident, plus = m.groups()
        if plus:
            if want_value:
                return None, "unsupported-expr"
            want_value = True
        else:
            if not want_value:
                return None, "unsupported-expr"
            if verb or plain:
                parts.append(literal_value(verb or plain))
            else:
                val = consts.get(ident)
                if val is None:
                    tail = ident.split(".")[-1]
                    cand = consts.get("*" + tail)
                    val = cand if isinstance(cand, str) else None
                if val is None:
                    return None, "unknown-identifier:" + ident
                parts.append(val)
            want_value = False
        pos = m.end()
    if want_value or not parts:
        return None, "unsupported-expr"
    return "".join(parts), None


def _enclosing_class(decls, off):
    """decls: 정렬된 [(offset, name)]. off 직전의 클래스 이름."""
    k = bisect.bisect_right([d[0] for d in decls], off) - 1
    return decls[k][1] if k >= 0 else None


def _brace_body(code, start):
    """code[start] == '{' 일 때 짝 '}' 까지의 (본문, 본문 시작 offset)."""
    depth = 0
    for j in range(start, len(code)):
        ch = code[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return code[start + 1:j], start + 1
    return code[start + 1:], start + 1


def index_cs(files):
    """files: [CsFile]. -> (consts, classes, overrides)
    consts: {"Class.NAME": v, "*NAME": v|set}, classes: {name: {"file","base"}},
    overrides: {class: [{"file","line","expr"}]}"""
    consts, classes, overrides = {}, {}, collections.defaultdict(list)
    for f in files:
        decls = []
        for m in CLASS_RE.finditer(f.code):
            name = m.group(1)
            decls.append((m.start(), name))
            base = None
            if m.group(2):
                first = re.split(r"[,\s]", m.group(2).strip())[0]
                base = re.sub(r"<.*$", "", first).split(".")[-1] or None
            info = classes.setdefault(name, {"file": f.rel, "base": None})
            if base and not info["base"]:
                info["base"] = base
        for m in CONST_RE.finditer(f.code):
            cls = _enclosing_class(decls, m.start())
            val = literal_value(m.group(2))
            if cls:
                consts["%s.%s" % (cls, m.group(1))] = val
            key = "*" + m.group(1)
            prev = consts.get(key)
            consts[key] = val if prev is None or prev == val else {"ambiguous"}
        for m in OVERRIDE_RE.finditer(f.code):
            cls = _enclosing_class(decls, m.start())
            rest = m.end()
            if f.code.startswith("=>", rest):
                e = f.code.find(";", rest)
                exprs = [(f.code[rest + 2:e], rest + 2)]
            elif rest < len(f.code) and f.code[rest] == "{":
                body, b0 = _brace_body(f.code, rest)
                exprs = [(r.group(1), b0 + r.start(1)) for r in RETURN_RE.finditer(body)]
            else:
                exprs = []
            overrides[cls].append({"file": f.rel, "line": f.line(m.start()),
                                   "exprs": [(x.strip(), f.line(o)) for x, o in exprs]})
    return consts, classes, overrides


def resolve_prefab_name(controller, classes, overrides, consts):
    """Controller(상속 포함)의 GetUIPrefabName 값. -> dict(value|None, file, line, expr, reason)."""
    seen, cur = set(), controller
    while cur and cur not in seen:
        seen.add(cur)
        if cur in overrides:
            ov = overrides[cur][0]
            if len(overrides[cur]) > 1:
                return dict(value=None, file=ov["file"], line=ov["line"], expr="", reason="multiple-overrides")
            if not ov["exprs"]:
                return dict(value=None, file=ov["file"], line=ov["line"], expr="", reason="no-return")
            vals = []
            for expr, line in ov["exprs"]:
                v, why = eval_expr(expr, consts)
                if v is None:
                    return dict(value=None, file=ov["file"], line=line, expr=expr, reason=why)
                vals.append((v, line, expr))
            if len({v for v, _l, _e in vals}) > 1:
                return dict(value=None, file=ov["file"], line=vals[0][1], expr=" | ".join(e for _v, _l, e in vals),
                            reason="multiple-returns")
            v, line, expr = vals[0]
            return dict(value=v, file=ov["file"], line=line, expr=expr, reason=None)
        if cur not in classes:
            return dict(value=None, file=None, line=None, expr=controller, reason="controller-not-found")
        cur = classes[cur]["base"]
    return dict(value=None, file=classes.get(controller, {}).get("file"), line=None, expr=controller,
                reason="no-override")


def parse_bridge(f):
    """UIBridge 파일 -> [(uiType, controller, line)] (주석 처리된 줄 제외)."""
    return [(m.group(1), m.group(2).split(".")[-1], f.line(m.start())) for m in BRIDGE_RE.finditer(f.code)]


def parse_local_list(f):
    """localResourceUI 집합 -> [(uiType, line)]."""
    m = LOCAL_LIST_RE.search(f.code)
    if not m:
        return []
    return [(u.group(1), f.line(m.start(1) + u.start())) for u in UITYPE_RE.finditer(m.group(1))]


def is_editor_cs(rel):
    return "/Editor/" in rel or "/EditorLevel/" in rel


def load_cs_files():
    root = C.unity_root()
    out = []
    for base in CS_ROOTS:
        for dp, _dn, fn in os.walk(os.path.join(root, base)):
            for name in fn:
                if name.endswith(".cs"):
                    full = os.path.join(dp, name)
                    with open(full, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                    out.append(CsFile(os.path.relpath(full, root).replace("\\", "/"), text))
    return sorted(out, key=lambda x: x.rel)


# ---------------------------------------------------------------- Addressable 그룹
GROUP_ENTRY_RE = re.compile(r"- m_GUID: ([0-9a-f]{32})\s*\n\s*m_Address: ([^\n]*)")


class Groups:
    """주소 <-> GUID 정답표. addr2guids: {주소: [(guid, 그룹 파일)]}."""

    def __init__(self, entries):
        self.addr2guids = collections.defaultdict(list)
        self.guid2addr = {}
        for guid, addr, group in entries:
            self.addr2guids[addr].append((guid, group))
            self.guid2addr[guid] = (addr, group)

    @classmethod
    def load(cls):
        d = os.path.join(C.unity_root(), GROUPS_DIR)
        if not os.path.isdir(d):  # Addressables 를 안 쓰는 프로젝트
            return cls([])
        entries = []
        for name in sorted(os.listdir(d)):
            if name.endswith(".asset"):
                with open(os.path.join(d, name), "r", encoding="utf-8", errors="replace") as fh:
                    for g, a in GROUP_ENTRY_RE.findall(fh.read()):
                        a = a.strip()
                        if len(a) >= 2 and a[0] == a[-1] and a[0] in "'\"":
                            a = a[1:-1]
                        entries.append((g, a, name))
        return cls(entries)

    def resolve(self, addr):
        """주소 -> (프리팹 경로|None, guid|None, 사유|None)."""
        hits = self.addr2guids.get(addr)
        if not hits:
            return None, None, "address-not-in-groups"
        guid = hits[0][0]
        path = PP.INDEX.get(guid)
        if not path:
            return None, guid, "guid-unresolved"
        if len({g for g, _ in hits}) > 1:
            return path, guid, "duplicate-address"
        return path, guid, None

    def ui_prefab_addresses(self):
        """그룹에 등록된 UI 프리팹: {주소: (경로, guid, 그룹)}."""
        out = {}
        for guid, (addr, group) in self.guid2addr.items():
            path = PP.INDEX.get(guid) or ""
            if path.endswith(".prefab") and "/UI/" in path:
                out[addr] = (path, guid, group)
        return out


def is_standard_address(addr, path):
    return addr == "UI_%s_prefab" % TS.stem(path)


# ---------------------------------------------------------------- 프리팹 YAML
def go_path(docs, go, _cache=None):
    """GameObject 이름 체인(루트부터). 중간에 stripped(중첩 원본 쪽) 객체가 끼면 앞을 '?' 로 둔다."""
    tf_of = _cache if _cache is not None else {}
    if not tf_of:
        for fid, d in docs.items():
            if d["cls"] in (4, 224) and not d["stripped"]:
                tf_of[PP.ref_id(d["body"].get("m_GameObject"))] = fid
    names, cur = [], go
    for _ in range(200):
        d = docs.get(cur)
        if not d or d["cls"] != 1 or d["stripped"]:
            break
        names.append(str(d["body"].get("m_Name", "?")))
        tf = tf_of.get(cur)
        if tf is None:
            break
        father = PP.ref_id(docs[tf]["body"].get("m_Father"))
        if father == 0:
            return "/".join(reversed(names))
        fd = docs.get(father)
        if not fd or fd["stripped"]:
            break
        cur = PP.ref_id(fd["body"].get("m_GameObject"))
    return "/".join(["?"] + list(reversed(names))) if names else "?"


def _guid_str(v):
    if v is None:
        return ""
    if isinstance(v, int):
        return str(v).zfill(32)
    return str(v).strip()


WRAP_MOD_RE = re.compile(r"^wrapContentPrefabDatas\.Array\.data\[(\d+)\]\.guids$")


def extract_prefab(docs, rl_guid, wrap_guid):
    """프리팹 문서 -> [(kind, ref, path)] kind: loader|wrap, ref: 키 또는 guid."""
    out, cache = [], {}
    for fid, d in docs.items():
        b = d["body"]
        if d["cls"] == 114 and not d["stripped"]:
            sg = PP.ref_guid(b.get("m_Script"))
            if sg == rl_guid:
                key = b.get("addressableKey")
                out.append(("loader", "" if key is None else str(key).strip(),
                            go_path(docs, PP.ref_id(b.get("m_GameObject")), cache)))
            elif sg == wrap_guid:
                path = go_path(docs, PP.ref_id(b.get("m_GameObject")), cache)
                datas = b.get("wrapContentPrefabDatas") or []
                if not datas:
                    out.append(("wrap", "", path))
                for item in datas:
                    out.append(("wrap", _guid_str((item or {}).get("guids")), path))
        elif d["cls"] == 1001:
            mod = b.get("m_Modification") or {}
            parent = PP.ref_id(mod.get("m_TransformParent"))
            ppath = None
            for m in mod.get("m_Modifications") or []:
                prop = m.get("propertyPath") or ""
                if prop == "addressableKey" or WRAP_MOD_RE.match(prop):
                    if ppath is None:
                        pd = docs.get(parent)
                        ppath = (go_path(docs, PP.ref_id(pd["body"].get("m_GameObject")), cache) + "/?"
                                 if pd and not pd["stripped"] else "?")
                    val = m.get("value")
                    kind = "loader" if prop == "addressableKey" else "wrap"
                    out.append((kind, ("" if val is None else str(val).strip()) if kind == "loader" else _guid_str(val),
                                ppath))
    return out


def scan_prefabs(rl_guid, wrap_guid):
    """범위 UI 프리팹에서 ResourcesLoader·WrapContent 참조 -> ([(user, kind, ref, path)], 파싱 실패 목록)."""
    root = C.unity_root()
    needles = tuple(n for n in (rl_guid, wrap_guid, "propertyPath: addressableKey", "propertyPath: wrapContentPrefabDatas") if n)
    out, failed = [], []
    for rel in TS.ui_prefabs():
        full = os.path.join(root, rel)
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        if not any(n in text for n in needles):
            continue
        try:
            docs = PP.load_docs(full)
        except ValueError as e:
            failed.append({"file": rel, "line": None, "expr": "", "reason": "yaml-parse-failed: %s" % e})
            continue
        for kind, ref, path in extract_prefab(docs, rl_guid, wrap_guid):
            out.append((rel, kind, ref, path))
    return out, failed


# ---------------------------------------------------------------- Resources
_RES = None


def resources_prefab(res_path):
    """Resources.Load 경로 -> Assets 상대경로 또는 None."""
    global _RES
    cand = "%s/%s.prefab" % (RESOURCES_DIR, res_path)
    if os.path.exists(os.path.join(C.unity_root(), cand)):
        return cand
    if _RES is None:
        PP.INDEX.get("0" * 32)
        _RES = [v for v in (PP.INDEX.map or {}).values() if "/Resources/" in v and v.endswith(".prefab")]
    tail = "/Resources/%s.prefab" % res_path
    hits = [v for v in _RES if v.endswith(tail)]
    return hits[0] if hits else None


# ---------------------------------------------------------------- 조립
def edge(template, kind, user, user_type, path):
    return {"template": template, "templateGuid": TS.asset_guid(template) if template else None, "kind": kind,
            "user": user, "userType": user_type, "path": path, "overrides": []}


def build():
    t0 = time.time()
    rl_guid = RESOURCES_LOADER_CS and TS.asset_guid(RESOURCES_LOADER_CS)
    wrap_guid = WRAP_CONTENT_CS and TS.asset_guid(WRAP_CONTENT_CS)
    if (RESOURCES_LOADER_CS and not rl_guid) or (WRAP_CONTENT_CS and not wrap_guid):  # 설정했는데 못 찾음 = 오류
        raise SystemExit("ResourcesLoader/WrapContent 스크립트 GUID 를 못 찾음: %s %s" % (rl_guid, wrap_guid))
    groups = Groups.load()
    files = load_cs_files()
    consts, classes, overrides = index_cs(files)
    edges, unresolved, part_unres = [], [], []

    def unres(file, line, expr, reason, ref=None, detail=None):
        unresolved.append({"file": file, "line": line, "expr": expr, "reason": reason})
        part_unres.append({"ref": ref if ref is not None else expr, "reason": reason,
                           "detail": detail or ("%s:%s" % (file, line) if line else file)})

    # --- UIType -> Controller -> 프리팹
    bridge_file = next((f for f in files if re.search(r"\bstruct\s+UIBridge\b|\bclass\s+UIBridge\b", f.code)), None)
    local_file = next((f for f in files if LOCAL_LIST_RE.search(f.code)), None)
    if bool(bridge_file) != bool(local_file):
        raise SystemExit("UIBridge 와 localResourceUI 중 하나만 찾음 — 둘 다 있거나 둘 다 없어야 한다")
    local_types = {u: line for u, line in parse_local_list(local_file)} if local_file else {}
    ui_types = []
    for ui_type, ctrl, bline in parse_bridge(bridge_file) if bridge_file else []:
        r = resolve_prefab_name(ctrl, classes, overrides, consts)
        row = {"uiType": ui_type, "controller": ctrl, "prefabName": r["value"], "address": None, "prefab": None,
               "loader": "resources" if ui_type in local_types else "addressable",
               "file": r["file"] or classes.get(ctrl, {}).get("file"), "line": r["line"], "reason": None}
        if r["value"] is None:
            row["reason"] = r["reason"]
            unres(row["file"] or bridge_file.rel, row["line"] or bline, r["expr"], r["reason"], ref=ui_type,
                  detail="%s -> %s" % (ui_type, ctrl))
        elif ui_type in local_types:
            row["prefab"] = resources_prefab(r["value"])
            if row["prefab"]:
                edges.append(edge(row["prefab"], "code-local", local_file.rel, "code",
                                  "%s:%d" % (local_file.rel, local_types[ui_type])))
            else:
                row["reason"] = "resources-path-not-found"
                unres(row["file"], row["line"], r["value"], row["reason"], ref=ui_type)
        else:
            row["address"] = "UI_%s_prefab" % r["value"].split("/")[-1]
            path, _g, why = groups.resolve(row["address"])
            row["prefab"] = path
            if path:
                edges.append(edge(path, "code-ui", row["file"], "code", "%s:%d" % (row["file"], row["line"])))
            if why:
                row["reason"] = why
                unres(row["file"], row["line"], row["address"], why, ref=row["address"],
                      detail="%s -> %s (%s:%s)" % (ui_type, ctrl, row["file"], row["line"]))
        ui_types.append(row)
    bridged = {u for u, _c, _l in parse_bridge(bridge_file)} if bridge_file else set()
    for u, line in local_types.items():
        if u not in bridged:
            unres(local_file.rel, line, u, "local-uitype-not-in-bridge", ref=u)

    # --- 프리팹 안 ResourcesLoader·WrapContent
    loader_users = collections.defaultdict(list)
    wrap_rows = []
    prefab_refs, failed = scan_prefabs(rl_guid, wrap_guid)
    for f in failed:
        unres(f["file"], None, "", f["reason"], ref=f["file"])
    guid_mismatch = 0
    for user, kind, ref, npath in prefab_refs:
        where = "%s @ %s" % (user, npath)
        if kind == "loader":
            if not ref:
                unres(user, None, "", "empty-key", ref="", detail=where)
                continue
            path, _g, why = groups.resolve(ref)
            loader_users[ref].append({"user": user, "userType": "prefab", "path": npath})
            if path:
                edges.append(edge(path, "code-loader", user, "prefab", npath))
            if why:
                unres(user, None, ref, why, ref=ref, detail=where)
        else:
            if not ref:
                unres(user, None, "", "empty-guid", ref="", detail=where)
                continue
            path = PP.INDEX.get(ref)
            wrap_rows.append({"user": user, "path": npath, "guid": ref, "prefab": path})
            if path:
                edges.append(edge(path, "code-wrap", user, "prefab", npath))
            else:
                unres(user, None, ref, "guid-unresolved", ref=ref, detail=where)

    # --- C# 문자열 리터럴
    ui_addr = groups.ui_prefab_addresses()
    editor_hits = 0
    for f in files:
        for off, kind, raw in f.lits:
            known = raw in ui_addr
            looks = bool(UI_KEY_RE.match(raw))
            dynamic = kind == "interp" and raw.startswith("UI_") and raw.endswith("_prefab")
            if not (known or looks or dynamic):
                continue
            line = f.line(off)
            if is_editor_cs(f.rel):
                editor_hits += 1
                continue
            loc = "%s:%d" % (f.rel, line)
            if dynamic:
                unres(f.rel, line, '$"%s"' % raw, "dynamic-key", ref='$"%s"' % raw, detail=loc)
                continue
            path, _g, why = groups.resolve(raw)
            loader_users[raw].append({"user": f.rel, "userType": "code", "path": loc})
            if path:
                edges.append(edge(path, "code-loader", f.rel, "code", loc))
            if why:
                unres(f.rel, line, raw, why, ref=raw, detail=loc)

    loader_keys = []
    for key in sorted(loader_users):
        path, _g, _why = groups.resolve(key)
        loader_keys.append({"key": key, "prefab": path, "standard": bool(path) and is_standard_address(key, path),
                            "users": loader_users[key]})
    local_rows = [{"name": u, "prefab": next((r["prefab"] for r in ui_types if r["uiType"] == u), None),
                   "file": local_file.rel, "line": line} for u, line in sorted(local_types.items())] if local_file else []

    # --- 통계
    linked = collections.defaultdict(set)
    for e in edges:
        linked[e["template"]].add(e["kind"])
    vp = [r for r in TS.ui_prefabs() if TS.suffix(r) in SCREEN_SUFFIXES and not TS.is_excluded(r)]
    vp_linked = [r for r in vp if linked.get(r, set()) & {"code-ui", "code-local"}]
    unlinked = [{"path": r, "otherKinds": sorted(linked.get(r, set()))} for r in vp if r not in set(vp_linked)]
    nonstd = {a: v for a, v in ui_addr.items() if not is_standard_address(a, v[0])}
    nonstd_used = sorted(a for a in nonstd if any(e["template"] == nonstd[a][0] for e in edges))
    stats = {
        "viewPopupTotal": len(vp), "viewPopupLinked": len(vp_linked),
        "linkRate": round(len(vp_linked) / len(vp), 3) if vp else 0.0,
        "uiTypeTotal": len(ui_types), "uiTypeResolved": sum(1 for r in ui_types if r["prefab"]),
        "edgesByKind": dict(sorted(collections.Counter(e["kind"] for e in edges).items())),
        "loaderKeyTotal": len(loader_keys), "loaderKeyResolved": sum(1 for k in loader_keys if k["prefab"]),
        "wrapRefs": len(wrap_rows), "wrapResolved": sum(1 for w in wrap_rows if w["prefab"]),
        "uiPrefabAddresses": len(ui_addr), "nonStandardAddresses": len(nonstd),
        "nonStandardUsed": len(nonstd_used),
        "unresolvedByReason": dict(sorted(collections.Counter(u["reason"].split(":")[0] for u in unresolved).items())),
        "editorLiteralHitsSkipped": editor_hits, "csFiles": len(files),
        "seconds": round(time.time() - t0, 1),
    }
    now = C.now_iso()
    main = {"updatedAt": now, "uiTypes": ui_types, "loaderKeys": loader_keys, "wrapContent": wrap_rows,
            "localResourceUI": local_rows, "unresolved": unresolved, "stats": stats,
            "unlinkedViewPopup": unlinked,
            "nonStandardAddresses": [{"address": a, "prefab": v[0], "group": v[2], "used": a in nonstd_used}
                                     for a, v in sorted(nonstd.items())]}
    part = {"source": "code", "updatedAt": now, "edges": edges, "unresolved": part_unres}
    return main, part


def run():
    main, part = build()
    C.write_json_atomic(C.p(*OUT_MAIN), main)
    C.write_json_atomic(C.p(*OUT_PART), part)
    s = main["stats"]
    print("간선 %s" % s["edgesByKind"])
    print("View·Popup 연결 %d/%d (%.1f%%), UIType 해석 %d/%d" % (
        s["viewPopupLinked"], s["viewPopupTotal"], 100 * s["linkRate"], s["uiTypeResolved"], s["uiTypeTotal"]))
    print("로더 키 %d/%d, WrapContent %d/%d, 비표준 주소 %d (간선 있음 %d)" % (
        s["loaderKeyResolved"], s["loaderKeyTotal"], s["wrapResolved"], s["wrapRefs"],
        s["nonStandardAddresses"], s["nonStandardUsed"]))
    print("unresolved %d %s, %.1fs" % (len(main["unresolved"]), s["unresolvedByReason"], s["seconds"]))
    print("쓴 파일: %s, %s" % ("/".join(OUT_MAIN), "/".join(OUT_PART)))
    return 0


# ---------------------------------------------------------------- selftest
SAMPLE_CS = r'''
// "UI_Commented_prefab"
/* "UI_Block_prefab"
   still comment */
public class StringDefine { public const string PATH_PREFAB_UI_CONTENTS = "UI/Contents/"; }
public class AController : BaseController {
    public override string GetUIPrefabName()
    {   // "UI_InLineComment_prefab"
        return StringDefine.PATH_PREFAB_UI_CONTENTS + "Shop/X" + "Popup";
    }
}
public class BController : AController { }
public class CController : BaseController { public override string GetUIPrefabName() => @"UI/Contents/Y/YView"; }
public class DController : BaseController { public override string GetUIPrefabName() { return Make("x"); } }
class Use { void F() { var k = "UI_Foo_prefab"; var d = $"UI_{a["q"]}_prefab"; var v = @"a""b"; char q = '"'; var u = "http://x"; } }
public struct UIBridge { object G() { return new Dictionary<UIType, System.Type>() {
    {UIType.XPopup, typeof(BController)},
    // {UIType.Dead, typeof(Gone)},
    {UIType.YView, typeof(CController)},
}; } }
class M { private HashSet<UIType> localResourceUI = new HashSet<UIType>
    {
        UIType.YView,
    };
}
'''

SAMPLE_YAML = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100
GameObject:
  m_Component:
  - component: {fileID: 101}
  m_Name: Root
--- !u!224 &101
RectTransform:
  m_GameObject: {fileID: 100}
  m_Father: {fileID: 0}
--- !u!1 &200
GameObject:
  m_Component:
  - component: {fileID: 201}
  m_Name: List
--- !u!224 &201
RectTransform:
  m_GameObject: {fileID: 200}
  m_Father: {fileID: 101}
--- !u!114 &202
MonoBehaviour:
  m_GameObject: {fileID: 200}
  m_Script: {fileID: 11500000, guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa, type: 3}
  guids: 177b2ece58711eb4387a7568ba69fc0c
  addressableKey: UI_ThumbnailCharacterUnit_prefab
--- !u!114 &203
MonoBehaviour:
  m_GameObject: {fileID: 200}
  m_Script: {fileID: 11500000, guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb, type: 3}
  wrapContentPrefabDatas:
  - mPadding: 50
    guids: 497fac623a0c239418851241c484fd4e
  - mPadding: 0
    guids:
--- !u!1001 &300
PrefabInstance:
  m_Modification:
    m_TransformParent: {fileID: 201}
    m_Modifications:
    - target: {fileID: 1, guid: cccccccccccccccccccccccccccccccc, type: 3}
      propertyPath: addressableKey
      value: UI_Other_prefab
      objectReference: {fileID: 0}
"""


def selftest():
    # 1) C# 스캐너·평가
    f = CsFile("Assets/X/Sample.cs", SAMPLE_CS)
    lits = {raw: kind for _o, kind, raw in f.lits}
    assert "UI_Commented_prefab" not in lits and "UI_Block_prefab" not in lits and "UI_InLineComment_prefab" not in lits
    assert lits.get("UI_Foo_prefab") == "plain", lits
    assert any(k == "interp" and r.startswith("UI_") and r.endswith("_prefab") for r, k in lits.items()), lits
    assert lits.get('a""b') == "verbatim" and lits.get("http://x") == "plain"
    assert "http://x" in f.code and "UI_Commented_prefab" not in f.code
    assert f.code.count("\n") == SAMPLE_CS.count("\n")
    foo = next(o for o, _k, r in f.lits if r == "UI_Foo_prefab")
    assert f.line(foo) == SAMPLE_CS[:foo].count("\n") + 1
    consts, classes, ovs = index_cs([f])
    assert consts["StringDefine.PATH_PREFAB_UI_CONTENTS"] == "UI/Contents/"
    assert classes["BController"]["base"] == "AController"
    r = resolve_prefab_name("BController", classes, ovs, consts)
    assert r["value"] == "UI/Contents/Shop/XPopup" and r["file"] == f.rel, r
    assert resolve_prefab_name("CController", classes, ovs, consts)["value"] == "UI/Contents/Y/YView"
    assert resolve_prefab_name("DController", classes, ovs, consts)["reason"] == "unsupported-expr"
    assert resolve_prefab_name("Nope", classes, ovs, consts)["reason"] == "controller-not-found"
    assert eval_expr('"a" "b"', consts)[0] is None and eval_expr("X.Y", consts)[1].startswith("unknown-identifier")
    assert [(u, c) for u, c, _l in parse_bridge(f)] == [("XPopup", "BController"), ("YView", "CController")]
    loc = parse_local_list(f)
    assert [u for u, _l in loc] == ["YView"] and SAMPLE_CS.split("\n")[loc[0][1] - 1].strip() == "UIType.YView,"
    assert is_editor_cs("Assets/Game/Scripts/Editor/A.cs") and not is_editor_cs("Assets/Game/Scripts/Runtime/A.cs")

    # 2) 프리팹 YAML 추출
    fd, tmp = tempfile.mkstemp(suffix=".prefab")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(SAMPLE_YAML)
    try:
        docs = PP.load_docs(tmp)
    finally:
        os.remove(tmp)
    got = extract_prefab(docs, "a" * 32, "b" * 32)
    assert ("loader", "UI_ThumbnailCharacterUnit_prefab", "Root/List") in got, got
    assert ("wrap", "497fac623a0c239418851241c484fd4e", "Root/List") in got and ("wrap", "", "Root/List") in got
    assert ("loader", "UI_Other_prefab", "Root/List/?") in got, got
    assert len(got) == 4

    # 3) Groups 해석(합성)
    g = Groups([("1" * 32, "K", "G.asset"), ("2" * 32, "D", "G.asset"), ("3" * 32, "D", "H.asset")])
    assert g.resolve("none")[2] == "address-not-in-groups"
    assert is_standard_address("UI_Foo_prefab", "Assets/a/Foo.prefab") and not is_standard_address("Foo", "Assets/a/Foo.prefab")

    # 4) 실제 프로젝트(project.json "code" 설정이 있는 만큼만 단정)
    for cs in (RESOURCES_LOADER_CS, WRAP_CONTENT_CS):
        assert cs is None or len(TS.asset_guid(cs) or "") == 32, cs
    real = Groups.load()
    addr = next((a for a, v in sorted(real.ui_prefab_addresses().items()) if is_standard_address(a, v[0])), None)
    if addr:
        path, guid, why = real.resolve(addr)
        assert path and why is None, (addr, path, why)
        assert TS.asset_guid(path) == guid
    res = next((v for v in TS.ui_prefabs() if v.startswith(RESOURCES_DIR + "/")), None)
    if res:
        assert resources_prefab(res[len(RESOURCES_DIR) + 1:-len(".prefab")]) == res
    main, part = build()  # 쓰지 않는다
    kinds = main["stats"]["edgesByKind"]
    if RESOURCES_LOADER_CS and WRAP_CONTENT_CS:
        assert all(kinds.get(k, 0) > 0 for k in ("code-ui", "code-local", "code-loader", "code-wrap")), kinds
        assert main["stats"]["linkRate"] > 0.5, main["stats"]
        assert any(e["kind"] == "code-loader" and e["userType"] == "prefab" for e in part["edges"])
    for e in part["edges"]:
        assert set(e) == {"template", "templateGuid", "kind", "user", "userType", "path", "overrides"}, e
        assert e["userType"] in ("code", "prefab") and e["path"]
    print("code_usage.py selftest ok")
    return 0


def main_cli(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.run:
        return run()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main_cli(sys.argv[1:]))
