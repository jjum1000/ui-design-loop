"""T1 씬 열거: 데이터·코드가 가리키는 씬 키를 정규식으로 뽑아 도달 씬 / 미참조 씬 / 없는 씬 참조로 나눈다.

씬 키 출처(kind):
  <데이터>       project.json `scenes.sources[]` — 출처마다 kind·glob(Unity 루트 기준)·regex(그룹 1 = 키)
                 선택: block(이 정규식의 그룹 1 안에서만 regex 를 찾음) · split(키를 이 문자로 나눔) · prefix(이 접두어 키만)
                 · ignore_prefix·ignore_reason(이 접두어 키는 ignored 로 기록)
  stringdefine   `scenes.string_define` 파일의 `const string *SCENE* = "..."`
  hardcoded      `scenes.code_roots` 아래 런타임 .cs 의 `const string *Scene* = "..."`
  chain          미참조 씬을 도달 씬·도달 데이터가 연쇄로 가리킴(`scenes.chain_globs` 안 참조)
키 ↔ 씬 파일: Addressable 그룹(`AssetGroups/*.asset`)의 `m_GUID`·`m_Address` 가 정답(matchedBy=group),
없으면 파일명(확장자 제외, `/` 가 있으면 경로 끝) 일치(matchedBy=filename).
코드 상수(stringdefine·hardcoded)는 씬으로 해석될 때만 쓴다(해석 안 되면 ignored).

사용:
  python scripts/scene_enum.py --run        data/scenes/reachable.json 을 쓰고 요약 출력
  python scripts/scene_enum.py --selftest   합성 문자열로 출처 정규식 검사 + 실제 프로젝트 단정
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

# 프로젝트별 출처·경로는 project.json "scenes" 에서 읽는다(키 설명은 위 독스트링)
_SCENES = (C.project() or {}).get("scenes", {})
SOURCES = _SCENES.get("sources", [])
GROUPS = "Assets/AddressableAssetsData/AssetGroups"
SCRIPTS_ROOTS = _SCENES.get("code_roots", ["Assets"])
STRING_DEFINE = _SCENES.get("string_define")
PREFERRED_DIR = _SCENES.get("preferred_dir")  # 같은 파일명 씬이 여럿이면 이 경로 조각을 가진 쪽을 고른다
OUT = ("data", "scenes", "reachable.json")

GUID_RE = re.compile(r"guid: ([0-9a-f]{32})")
ENTRY_RE = re.compile(r"- m_GUID: ([0-9a-f]{32})\s*\n\s+m_Address: (.*?)\s*\n")
CODE_CONST_RE = re.compile(r'const\s+string\s+(\w*(?:SCENE|Scene)\w*)\s*=\s*"([^"]+)"')
REGISTRY_LINE_RE = re.compile(r'"(?:sceneName|scenePath)"\s*:')
CHAIN_GLOBS = _SCENES.get("chain_globs", ["*.unity", "*.playable", ":(glob)Assets/**/*.asset"])


# ---------------------------------------------------------------- 파일 도우미
def _rel(abs_path):
    return os.path.relpath(abs_path, C.unity_root()).replace("\\", "/")


def _read(rel):
    with open(os.path.join(C.unity_root(), rel), encoding="utf-8", errors="replace") as f:
        return f.read()


def _glob(pattern):
    return sorted(_rel(x) for x in glob.glob(os.path.join(C.unity_root(), pattern), recursive=True))


def _stem(rel):
    return os.path.splitext(os.path.basename(rel))[0]


# ---------------------------------------------------------------- 출처별 추출 (text → [키])
def source_keys(src, text):
    """출처 정의 하나로 text 에서 키 목록을 뽑는다(ignore_prefix 키 포함 — 거르기는 호출자가 ignored 로 기록)."""
    rx = re.compile(src["regex"], re.M)
    blocks = re.compile(src["block"], re.M).findall(text) if src.get("block") else [text]
    keys = [k for b in blocks for k in rx.findall(b)]
    if src.get("split"):
        keys = [k for v in keys for k in v.split(src["split"])]
    if src.get("prefix"):
        keys = [k for k in keys if k.startswith(src["prefix"])]
    return keys


def keys_code(text):
    """[(상수명, 값)]"""
    return CODE_CONST_RE.findall(text)


def _runtime_cs():
    out = []
    for rel in sorted({r for root in SCRIPTS_ROOTS for r in _glob(root + "/**/*.cs")}):
        if "/Editor/" in rel or "/Tests/" in rel:
            continue
        out.append(rel)
    return out


def data_sources():
    """[(출처 정의, 파일 목록)] — 데이터 출처(해석 안 되면 missing)."""
    return [(src, _glob(src["glob"])) for src in SOURCES]


# ---------------------------------------------------------------- 씬 파일·주소
def scene_files():
    """{guid: Assets 상대경로} — 모든 .unity 의 .meta 를 직접 훑는다(guid-index 는 .unity 를 색인하지 않음)."""
    out = {}
    for meta in glob.glob(os.path.join(C.unity_root(), "Assets", "**", "*.unity.meta"), recursive=True):
        with open(meta, encoding="utf-8", errors="replace") as f:
            m = GUID_RE.search(f.read(512))
        if m:
            out[m.group(1)] = _rel(meta[:-5])
    return out


def addressable_scenes(files):
    """{주소: 경로} — 그룹 파일에서 씬 guid 를 가진 항목만."""
    out = {}
    for rel in _glob(GROUPS + "/*.asset"):
        for guid, addr in ENTRY_RE.findall(_read(rel)):
            if guid in files:
                out.setdefault(addr, files[guid])
    return out


class Resolver:
    def __init__(self, files, addr_map):
        self.addr = addr_map
        self.addr_of = {v: k for k, v in addr_map.items()}
        paths = sorted(files.values(), key=self._rank)
        self.by_stem = {}
        for rel in paths:
            self.by_stem.setdefault(_stem(rel), rel)
        self.paths = paths

    def _rank(self, rel):
        # 같은 파일명이면 Addressable 등록 → preferred_dir → 짧은 경로 순으로 고른다
        return (rel not in self.addr_of, not (PREFERRED_DIR and PREFERRED_DIR in rel), len(rel), rel)

    def resolve(self, key):
        """(경로, 주소, matchedBy) 또는 None."""
        if key in self.addr:
            return self.addr[key], key, "group"
        if "/" in key:
            hit = next((p for p in self.paths if p.endswith("/" + key + ".unity")), None)
        else:
            hit = self.by_stem.get(key)
        if hit:
            return hit, self.addr_of.get(hit), "filename"
        return None


# ---------------------------------------------------------------- 수집
def collect_refs():
    """(data_refs, code_refs, ignored). refs: [(key, {file,key,kind})]"""
    data_refs, code_refs, ignored = [], [], []
    for source, files in data_sources():
        skip = source.get("ignore_prefix")
        for rel in files:
            for key in source_keys(source, _read(rel)):
                src = {"file": rel, "key": key, "kind": source["kind"]}
                if skip and key.startswith(skip):
                    ignored.append(dict(src, reason=source.get("ignore_reason", "ignore_prefix " + skip)))
                else:
                    data_refs.append((key, src))
    for rel in _runtime_cs():
        kind = "stringdefine" if rel == STRING_DEFINE else "hardcoded"
        for const, value in keys_code(_read(rel)):
            code_refs.append((value, {"file": rel, "key": "%s=%s" % (const, value), "kind": kind}))
    return data_refs, code_refs, ignored


def assign(data_refs, code_refs, res):
    """(scenes{path: rec}, missing{key: rec}, ignored)"""
    scenes, missing, ignored = {}, {}, []
    for key, src in data_refs + code_refs:
        hit = res.resolve(key)
        if hit is None:
            if src["kind"] in ("stringdefine", "hardcoded"):
                ignored.append(dict(src, reason="코드 상수가 씬으로 해석되지 않음"))
            else:
                missing.setdefault(key, {"name": key, "sources": []})["sources"].append(src)
            continue
        path, addr, how = hit
        rec = scenes.setdefault(path, {"name": _stem(path), "address": addr, "path": path,
                                       "exists": True, "matchedBy": how, "sources": []})
        if how == "group":
            rec["matchedBy"] = "group"
        if src not in rec["sources"]:
            rec["sources"].append(src)
    return scenes, missing, ignored


# ---------------------------------------------------------------- 연쇄 (git grep)
def git_grep(needles, specs, list_only=False):
    """단어 경계 고정 문자열 검색. list_only 면 [파일], 아니면 [(파일, 줄)]."""
    if not needles:
        return []
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("\n".join(sorted(set(needles))) + "\n")
        pat = f.name
    try:
        # 추적 파일만(--untracked 는 9배 느리고, 2026-10-21 기준 미추적 .unity·.playable 은 0개)
        args = ["git", "-C", C.unity_root(), "grep", "-I", "-w", "-F", "--null", "-f", pat]
        args += ["-l"] if list_only else ["-n"]
        r = subprocess.run(args + ["--"] + specs, capture_output=True, encoding="utf-8", errors="replace")
    finally:
        os.remove(pat)
    if r.returncode not in (0, 1):
        raise SystemExit("git grep 실패: " + r.stderr.strip())
    if list_only:
        return [x for x in r.stdout.split("\0") if x.strip()]
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\0")
        if len(parts) >= 3:
            out.append((parts[0], parts[2]))
    return out


def _guid_of(rel):
    try:
        with open(os.path.join(C.unity_root(), rel + ".meta"), encoding="utf-8") as f:
            m = GUID_RE.search(f.read(512))
        return m.group(1) if m else None
    except OSError:
        return None


def _needles(rec):
    return [x for x in (rec["name"], rec["address"], _guid_of(rec["path"])) if x]


def find_chains(unref, reached_paths, data_files):
    """미참조 씬을 가리키는 참조를 찾고, 원천이 도달 씬·도달 데이터면 받아들인다(고정점까지 반복).
    반환 (chains, accepted{path: [src]})."""
    needle_of = {}
    for rec in unref:
        for n in _needles(rec):
            needle_of.setdefault(n, rec["path"])
    hits = [(f, line) for f, line in git_grep(list(needle_of), CHAIN_GLOBS)
            if not f.endswith(".meta")]
    cands = []  # (scene, from, line)
    for f, line in hits:
        for n, scene in needle_of.items():
            if f != scene and re.search(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(n), line):
                cands.append((scene, f, line.strip()[:160]))
    cands = sorted(set(cands))
    users = _referrers({f for _s, f, _l in cands if f.endswith((".playable", ".asset"))})
    chains, accepted, reached = [], {}, set(reached_paths)
    changed = True
    while changed:
        changed = False
        for scene, f, line in cands:
            if scene in reached:
                continue
            why = _origin(f, line, reached, data_files, users)
            if why:
                reached.add(scene)
                accepted.setdefault(scene, []).append({"file": f, "key": line, "kind": "chain"})
                chains.append({"scene": _stem(scene), "from": f, "accepted": True, "detail": why + " | " + line})
                changed = True
    done = {(c["scene"], c["from"]) for c in chains}
    for scene, f, line in cands:
        if (_stem(scene), f) not in done:
            chains.append({"scene": _stem(scene), "from": f, "accepted": False,
                           "detail": _reject_reason(f, line, data_files) + " | " + line})
            done.add((_stem(scene), f))
    return chains, accepted


def _reject_reason(f, line, data_files):
    if REGISTRY_LINE_RE.search(line):
        return "마커 DB 등록(호출 아님)"
    if f in data_files:
        return "도달 데이터의 런타임 미사용 필드"
    return "원천 미도달"


def _referrers(files):
    """{파일: [그 파일 guid 를 참조하는 .unity·.playable·.asset]}"""
    guid_to = {g: f for f in files for g in [_guid_of(f)] if g}
    out = {f: [] for f in files}
    for user, line in git_grep(list(guid_to), CHAIN_GLOBS):
        for g, f in guid_to.items():
            if g in line and user != f:
                out[f].append(user)
    return out


def _origin(f, line, reached, data_files, users):
    """참조 원천이 도달 씬(또는 도달 씬·도달 데이터가 참조하는 타임라인·SO)이면 이유 문자열, 아니면 None.
    출처 데이터 파일 자체의 다른 필드는 받지 않는다 — 런타임이 읽는 필드는 출처 정규식이 이미 다 뽑는다
    (예: 같은 SO 의 에디터 저작용 씬 경로 필드는 런타임 로드에 안 쓰인다)."""
    if REGISTRY_LINE_RE.search(line) or f in data_files:
        return None
    if f in reached:
        return "도달 씬 안 참조"
    for u in users.get(f, []):
        if u in reached or u in data_files:
            return "도달 %s %s 가 참조하는 %s" % ("씬" if u.endswith(".unity") else "데이터",
                                              _stem(u), os.path.basename(f))
    return None


# ---------------------------------------------------------------- 조립
def build():
    files = scene_files()
    addr_map = addressable_scenes(files)
    res = Resolver(files, addr_map)
    data_refs, code_refs, ignored = collect_refs()
    scenes, missing, ign2 = assign(data_refs, code_refs, res)
    ignored += ign2
    unref = [{"name": _stem(p), "address": a, "path": p}
             for a, p in sorted(addr_map.items()) if p not in scenes]
    data_files = {s["file"] for _k, s in data_refs}
    chains, accepted = find_chains(unref, set(scenes), data_files)
    for path, srcs in accepted.items():
        rec = next(u for u in unref if u["path"] == path)
        scenes[path] = dict(rec, exists=True, matchedBy="group", sources=srcs)
    unref = [u for u in unref if u["path"] not in accepted]
    scene_list = sorted(scenes.values(), key=lambda r: (r["name"], r["path"]))
    return {"updatedAt": C.now_iso(), "scenes": scene_list, "unreferenced": unref,
            "missing": sorted(missing.values(), key=lambda r: r["name"]),
            "chains": chains, "ignored": ignored,
            "stats": {"addressableScenes": len(addr_map), "reachable": len(scene_list),
                      "reachableAddressable": sum(1 for s in scene_list if s["path"] in res.addr_of),
                      "unreferenced": len(unref), "missing": len(missing),
                      "chainAccepted": sum(1 for c in chains if c["accepted"])}}


def summary(obj):
    st = obj["stats"]
    print("Addressable 씬 %(addressableScenes)d · 도달 %(reachable)d(Addressable %(reachableAddressable)d) · "
          "미참조 %(unreferenced)d · 없는 참조 %(missing)d · 연쇄 채택 %(chainAccepted)d" % st)
    kinds = {}
    for s in obj["scenes"]:
        for src in s["sources"]:
            kinds.setdefault(src["kind"], set()).add(s["name"])
    print("출처별 도달 씬 수: " + ", ".join("%s %d" % (k, len(v)) for k, v in sorted(kinds.items())))
    print("없는 참조: " + ", ".join("%s(%d)" % (m["name"], len(m["sources"])) for m in obj["missing"]))
    print("미참조: " + ", ".join(u["address"] for u in obj["unreferenced"]))


def run():
    obj = build()
    C.write_json_atomic(C.p(*OUT), obj)
    summary(obj)
    print("쓰기: " + C.p(*OUT))
    return 0


# ---------------------------------------------------------------- 자체 테스트
def selftest():
    one = {"kind": "level", "glob": "x", "regex": r"^\s*sceneName: (\S+)\s*$"}
    assert source_keys(one, "  - a: 1\n    sceneName: Main_Street\n    sceneName: \n") == ["Main_Street"]
    cut = {"kind": "cut", "glob": "x", "regex": r"^\s*targetID: (Cut_\S*)\s*$", "split": ";", "prefix": "Cut_"}
    assert source_keys(cut, "      targetID: Cut_A;Cut_B;X\n      targetID: NPC_1\n") == ["Cut_A", "Cut_B"]
    js = {"kind": "marker", "glob": "x", "regex": r'"toSceneName"\s*:\s*"([^"]+)"'}
    assert source_keys(js, '{"toSceneName": "Office", "sceneName": "X"}') == ["Office"]
    lst = {"kind": "story", "glob": "x", "block": r"^  scenes:\s*\n((?:  - .*\n)+)", "regex": r"^  - (\S+)\s*$"}
    assert source_keys(lst, "  scenes:\n  - Story_A\n  - CS_A_01\n  rewards:\n  - r\n") == ["Story_A", "CS_A_01"]
    cs = 'public const string SCENE_TOWN = "400_Town";\nprivate const string ENGINE_SCENE_KEY = "600_X";\nconst string Y = "Z";'
    assert keys_code(cs) == [("SCENE_TOWN", "400_Town"), ("ENGINE_SCENE_KEY", "600_X")]
    r = Resolver({"g1": "Assets/A/Town.unity", "g2": "Assets/_Dev/B/Town.unity", "g3": "Assets/S/Sub/Prev.unity"},
                 {"Core/Town": "Assets/A/Town.unity"})
    assert r.resolve("Core/Town") == ("Assets/A/Town.unity", "Core/Town", "group")
    assert r.resolve("Town") == ("Assets/A/Town.unity", "Core/Town", "filename")
    assert r.resolve("S/Sub/Prev")[0] == "Assets/S/Sub/Prev.unity" and r.resolve("Nope") is None
    assert REGISTRY_LINE_RE.search('  "sceneName": "Town_Middle",') and not REGISTRY_LINE_RE.search("sceneName: X")
    obj = build()
    names = {s["name"] for s in obj["scenes"]}
    assert names or not (SOURCES or STRING_DEFINE), "도달 씬 0개 — project.json scenes.sources 확인"
    assert not names & {u["name"] for u in obj["unreferenced"]}
    assert all(s["exists"] and s["sources"] for s in obj["scenes"])
    summary(obj)
    print("scene_enum.py selftest ok")
    return 0


def main(argv):
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
    sys.exit(main(sys.argv[1:]))
