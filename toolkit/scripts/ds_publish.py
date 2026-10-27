"""P2-3 갱신·공유 절차: 지금 무엇을 다시 돌려야 하는지 판정하고, 색인 단계만 실행한다.
공유 문서 Docs/ui-design-system/{UPDATE.md, SKILL.md} 의 내용도 여기서 만든다(쓰기는 ds_index.py --run 이 한다).

사용:
  python scripts/ds_publish.py --plan        판정(전체 재생성 / 색인만 / 할 일 없음)과 명령 목록 출력. 아무것도 실행하지 않는다
  python scripts/ds_publish.py --run-index   색인 단계만 실행(ds_index · ds_skeletons · ds_checklist → ds_index --check).
                                             Unity 가 필요한 단계는 실행하지 않고 명령만 안내한다
  python scripts/ds_publish.py --selftest    가짜 시각·변경 목록으로 판정 로직·문서 내용 검사(git·파일 수정 없음)

판정 근거:
  데이터 빌드 시각 = data/template-index.json 의 updatedAt(없으면 mtime).
  그 시각의 HEAD(reflog) → 지금 HEAD 사이 커밋 변경 + 작업 트리에서 그 뒤에 수정된 파일 중
  프리팹(*.prefab) · 씬(*.unity) · 스크립트(project.json `publish.watch_code_roots` 의 *.cs) · Addressable 그룹이 있으면 → 전체 재생성.
  아니고 색인 입력(데이터·decisions.json·ds/roles.json·ds/token-names.json·색인 생성 스크립트)이 색인 파일보다 새로우면 → 색인만.
규칙: git 은 읽기만(reflog·diff·status). git add/commit/pull 과 Unity 실행은 하지 않는다. data/·decisions.json·ds/* 는 mtime 만 읽는다.
"""
import argparse
import collections
import contextlib
import datetime
import io
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import ds_colors as DC  # noqa: E402

_PROJ = C.project() or {}
DOCS_DIR = "Docs/ui-design-system"
_PUB = _PROJ.get("publish", {})
WATCH_CODE_ROOTS = _PUB.get("watch_code_roots", ["Assets"])  # 바뀌면 전체 재생성할 C# 루트
REVIEW_SERVER = _PUB.get("review_server", "리뷰 서버")  # 피드백을 남기는 팀 서버를 부르는 이름
SHARED_SINCE = _PUB.get("shared_since")  # 작업 공간 데이터를 git 으로 공유하기 시작한 날(문서 표기용)
AFTER_PUSH_NOTE = _PUB.get("after_push_note")  # 푸시 뒤 팀 서버가 따라오는 방식(문서 표기용)
COMPLETELY_CASE = _PUB.get("completely_case")  # Completely 언팩 금지 규칙에 붙일 프로젝트 사례(INDEX.md 표기용)
BRIDGE_DIR = _PROJ.get("bridge_dir", "Packages/com.ui-design-loop.bridge")  # 배치 렌더러(UIThumbnailRenderer·UILayoutRenderer) 폴더
Step = collections.namedtuple("Step", "cmd unity note")

# FINAL 5절(템플릿 카탈로그) → 7절(앱 흐름·배치 맵) 다시 만들기 순서. 7절은 5절 데이터가 최신이라는 전제라 이어 붙인다.
FULL_STEPS = (
    Step("python scripts/parse_prefab.py --reindex", False, "프리팹 노드·GUID 색인"),
    Step("python scripts/scene_enum.py --run", False, "씬 목록"),
    Step("python scripts/code_usage.py --run", False, "코드가 로드하는 프리팹"),
    Step("python scripts/usage_graph.py --prefabs", False, "사용 간선(프리팹)"),
    Step("python scripts/usage_graph.py --scenes", False, "사용 간선(씬)"),
    Step("python scripts/templates.py --select --overrides --lookalikes", False, "템플릿 선정·오버라이드·유사품"),
    Step("python scripts/thumbs.py --list --run --collect", True, "템플릿 썸네일 렌더"),
    Step("python scripts/templates.py --assemble", False, "템플릿 카드 조립"),
    Step("python scripts/layout_map.py --list --run --collect", True, "화면·템플릿 배치 렌더"),
    Step("python scripts/layout_map.py --check-samples", False, "표본 3화면 박스 = 프리팹 노드"),
    Step("python scripts/build_catalog.py --all", False, "카탈로그 HTML"),
    Step("python scripts/validate.py --rename catalog", False, ".tmp → 확정"),
    Step("python scripts/build_catalog.py --check", False, "깨진 링크 0"),
)
INDEX_STEPS = (
    Step("python scripts/ds_index.py --run", False, "templates.jsonl · screens.jsonl · INDEX.md · UPDATE.md · SKILL.md"),
    Step("python scripts/ds_skeletons.py --run", False, "skeletons.md"),
)


def with_project_steps(base, extra):
    """project.json project_producers 의 단계({after, cmd, note[, unity]} — after = 바로 앞 단계 cmd)를 끼운다.
    프로젝트 전용 생산자(앱 흐름 추적 등)는 그 스크립트가 작업 공간에 있을 때만 넣는다."""
    out = list(base)
    for x in extra:
        if not os.path.exists(C.p(*x["cmd"].split()[1].split("/"))):
            continue
        at = next(i for i, s in enumerate(out) if s.cmd == x["after"]) + 1
        out.insert(at, Step(x["cmd"], bool(x.get("unity")), x["note"]))
    return tuple(out)


_PRODUCERS = _PROJ.get("project_producers") or {}
FULL_STEPS = with_project_steps(FULL_STEPS, _PRODUCERS.get("full_steps", []))
INDEX_STEPS = with_project_steps(INDEX_STEPS, _PRODUCERS.get("index_steps", []))
CHECK_STEPS = (
    Step("python scripts/ds_index.py --check", False, "생성물 = 현재 데이터 · 행 수 · 경로 존재"),
    Step("python scripts/a0_setup.py --check", False, "자체 테스트 · data 스키마 불일치 0"),
)

# (파일, 이유, 만드는 스크립트) — 커밋 allowlist. 이미지·ui-audit/ 원본은 넣지 않는다.
# 프로젝트 생산자가 만드는 '새 화면 연결 체크리스트' 문서(있으면): project.json project_producers.checklist
# = {file, commit_why(커밋 표 설명), by(만드는 스크립트 표기), read_why(읽는 순서 설명)}
CHECKLIST = _PRODUCERS.get("checklist")
COMMIT_FILES = tuple(x for x in (
    ("INDEX.md", "진입점 — 읽는 순서·규칙·금지·많이 쓰는 템플릿·표준 미정 지점", "`ds_index.py`"),
    ("templates.jsonl", "템플릿 카드(한 줄 = 템플릿 하나, grep 대상)", "`ds_index.py`"),
    ("screens.jsonl", "화면 → 템플릿 역색인·깨끗한 참고 화면 표시", "`ds_index.py`"),
    ("skeletons.md", "View·Popup 골격 레시피(노드 경로·좌표·템플릿)", "`ds_skeletons.py`"),
    (CHECKLIST["file"], CHECKLIST["commit_why"], CHECKLIST["by"]) if CHECKLIST else None,
    ("UPDATE.md", "이 갱신·공유 절차", "`ds_index.py`(내용은 `ds_publish.py`)"),
    ("SKILL.md", "팀 에이전트용 '새 UI 화면 만들기' 지침", "`ds_index.py`(내용은 `ds_publish.py`)"),
) if x)
AGENTS_NOTE = "`AGENTS.md` — 'UI 작업' 안내 한 줄이 바뀐 경우에만(추적 파일이라 `-f` 불필요)"
# (경로 — 저장소 루트 기준 pathspec, 내용) — git 으로 공유하는 작업 공간 데이터. 팀 PC 는 pull 만으로
# 카탈로그(file://)·설계 스킬 입력을 갖는다. PNG·큰 JSON 은 LFS 를 권장(.gitattributes).
SHARED_DATA = (
    ("ui-audit/catalog", "카탈로그 HTML 전체(+ `asset-refs.txt` · 하단 도크 `library/`)"),
    ("ui-audit/data/layout", "화면·템플릿 배치 JSON(화면 쪽 LFS)"),
    ("ui-audit/data/templates", "템플릿 카드 데이터"),
    ("ui-audit/data/template-index.json", "템플릿 색인"),
    ("ui-audit/data/app-flow.json", "앱 → 화면 흐름(동선·참고 흐름)"),
    ("ui-audit/data/tokens", "색·글자 토큰"),
    ("ui-audit/previews/layout/screen/*.png", "화면 배치 렌더(LFS) — `.raw.json` 중간 산출은 제외"),
    ("ui-audit/previews/layout/template/*.png", "템플릿 배치 렌더(LFS)"),
    ("ui-audit/previews/templates/*.png", "템플릿 썸네일(LFS)"),
    ("ui-audit/cache/guid-index.json", "GUID → 경로 색인(LFS) — 꺼진 상태 스프라이트 찾기"),
)
# 담당자 PC 는 `/ui-audit/` 전체를 로컬 ignore 해서 add 에 `-f` 가 필요하다 — `-f` 는 팀 .gitignore 도 무시하므로 캐시·임시 파일을 경로로 뺀다
SHARED_EXCLUDES = (
    ":(exclude,glob)ui-audit/**/.ruff_cache/**",
    ":(exclude,glob)ui-audit/**/__pycache__/**",
    ":(exclude,glob)ui-audit/**/*.tmp",
)
NOT_COMMITTED = (
    ("`ui-audit/` 의 나머지(4절 공유 데이터 밖)", "담당자 PC 전용 작업 공간(배치 중간 산출·입력·리포트·`.raw.json` 등). 피드백 로그(`feedback/log.jsonl`·`state.js`·`snap/`·`revisions/`)는 %s에만 있다" % REVIEW_SERVER),
    ("이미지(PNG)", "색인은 렌더 경로만 적는다(렌더 원본은 4절 공유 데이터). 이 폴더에 이미지를 복사해 커밋하지 않는다"),
    ("`%s/`" % BRIDGE_DIR, "렌더러(gitignore). 존치·커밋은 사용자 결정 대기"),
    ("`.unity` · `.playable`", "테스트 씬·타임라인은 커밋하지 않는다(팀 규칙)"),
    ("작업 트리의 다른 변경", "공유 트리라 다른 세션의 변경이 섞여 있다. allowlist 밖은 손대지 않는다"),
)

WATCH_PATHSPECS = (
    ":(glob)Assets/**/*.prefab",
    ":(glob)Assets/**/*.unity",
    *(":(glob)%s/**/*.cs" % r for r in WATCH_CODE_ROOTS),
    "Assets/AddressableAssetsData/AddressableAssetSettings.asset",
    ":(glob)Assets/AddressableAssetsData/AssetGroups/*.asset",
)
CATEGORIES = ("prefab", "scene", "code", "addressable")
INDEX_INPUTS = (
    ("데이터 빌드", "data/template-index.json"),
    ("앱 흐름", "data/app-flow.json"),
    ("색 토큰", "data/tokens/color.json"),
    ("결정 기록", "decisions.json"),
    ("역할 승인", "ds/roles.json"),
    ("토큰 이름 확정", "ds/token-names.json"),
    ("생성 스크립트", "scripts/ds_index.py"),
    ("생성 스크립트", "scripts/ds_screens.py"),
    ("생성 스크립트", "scripts/ds_skeletons.py"),
    ("생성 스크립트", "scripts/ds_checklist.py"),
    ("생성 스크립트", "scripts/ds_publish.py"),
)
UNITY_CHECK = "Get-CimInstance Win32_Process -Filter \"Name='Unity.exe'\" | Select-Object ProcessId,CommandLine"
SAMPLE_PATHS = 5
LEVEL_FULL, LEVEL_INDEX, LEVEL_NONE = "full", "index", "none"
LEVEL_LABELS = {LEVEL_FULL: "전체 재생성", LEVEL_INDEX: "색인만", LEVEL_NONE: "할 일 없음"}

INSTRUCTION_TEMPLATE = (
    "새 화면: <이름>View|Popup — 한 줄 목적",
    "진입: 앱 아이콘 <ContentsType> | <화면>의 <버튼>",
    "참고 화면: ui-audit/catalog/map/<slug>.html (screens.jsonl 에서 cleanReference=true 인 것)",
    "요소: 목록(아이템=?), 탭(?개), 정렬/필터, 버튼(주/보조), 빈 상태 문구",
    "상태: 비어 있음 · 잠김 · 레드닷 · 로딩",
    "데이터: 서버 DTO / SO (모르면 '미정')",
    "금지: 새 스프라이트 · 토큰 밖 색 · 기존 화면 프리팹 수정 · Completely 언팩",
    "산출 범위: 와이어까지 | 프리팹까지 | 연결 코드까지",
)


def repo_root():
    return C.unity_root()


# ---------------------------------------------------------------- 판정 (순수 함수)
def category(path):
    p = path.replace("\\", "/")
    if p.endswith(".prefab"):
        return "prefab"
    if p.endswith(".unity"):
        return "scene"
    if p.endswith(".cs"):
        return "code"
    if p.startswith("Assets/AddressableAssetsData/"):
        return "addressable"
    return None


def parse_reflog(text):
    """`git log -g --date=unix --format=%H<TAB>%gd<TAB>%gs` → [(sha, unix 초, 메시지)] (최신 먼저)."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3 or "@{" not in parts[1]:
            continue
        ts = parts[1].rsplit("@{", 1)[1].rstrip("}")
        if ts.isdigit():
            out.append((parts[0], int(ts), parts[2]))
    return out


def head_at(reflog, t):
    """시각 t 에 HEAD 가 가리키던 커밋과 그 뒤 HEAD 이동 목록. reflog 가 t 까지 닿지 않으면 sha=None."""
    after = [e for e in reflog if e[1] > t]
    before = [e for e in reflog if e[1] <= t]
    return (before[0][0] if before else None), after


def parse_status_z(raw):
    """`git status --porcelain=v1 -z --no-renames` → [(XY, 경로)]."""
    return [(e[:2], e[3:]) for e in raw.split("\0") if len(e) > 3]


def dirty_after(entries, t, mtime):
    """작업 트리 변경 중 시각 t 뒤에 수정된 것 / 지워져 시각을 알 수 없는 것. mtime(path) 는 없으면 None."""
    changed, unknown = [], []
    for xy, path in entries:
        m = mtime(path)
        if m is None:
            unknown.append(path)
        elif m > t:
            changed.append(path)
    return changed, unknown


def newer_inputs(inputs, index_at):
    """색인 파일보다 새로운 입력 [(이름, 경로)]. index_at=None(색인 파일이 하나도 없음)이면 빈 목록."""
    if index_at is None:
        return []
    return [(label, rel) for label, rel, m in inputs if m is not None and m > index_at]


def decide(changes, newer, missing_outputs):
    """changes: 빌드 뒤 바뀐 감시 경로(커밋+작업 트리). → (수준, 이유 목록)."""
    if changes:
        by = collections.Counter(category(p) for p in changes)
        return LEVEL_FULL, ["데이터 빌드 뒤 바뀐 파일: " + " · ".join("%s %d" % (c, by[c]) for c in CATEGORIES if by[c])]
    reasons = []
    if missing_outputs:
        reasons.append("색인 파일 없음: " + ", ".join(missing_outputs))
    if newer:
        reasons.append("색인보다 새 입력: " + ", ".join("%s(%s)" % (rel, label) for label, rel in newer))
    return (LEVEL_INDEX, reasons) if reasons else (LEVEL_NONE, ["데이터 빌드 뒤 감시 경로 변경 없음 · 색인이 입력보다 새롭다"])


def commands(level):
    if level == LEVEL_FULL:
        return list(FULL_STEPS) + list(INDEX_STEPS) + list(CHECK_STEPS)
    if level == LEVEL_INDEX:
        return list(INDEX_STEPS) + list(CHECK_STEPS)
    return []


# ---------------------------------------------------------------- 사실 수집 (git·파일 읽기만)
def git(*args, check=True):
    r = subprocess.run(["git", "-C", repo_root()] + list(args), capture_output=True)
    if check and r.returncode != 0:
        raise SystemExit("git %s 실패: %s" % (" ".join(args[:2]), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout.decode("utf-8", "replace")


def file_mtime(path):
    return os.path.getmtime(path) if os.path.exists(path) else None


def build_time():
    """(unix 초, 출처 문구)."""
    path = C.p("data", "template-index.json")
    idx = C.load_json(path)
    if not idx:
        raise SystemExit("data/template-index.json 없음 — 데이터가 한 번도 만들어지지 않았다(FINAL 5절 순서로 전체 재생성)")
    if idx.get("updatedAt"):
        return datetime.datetime.fromisoformat(idx["updatedAt"]).timestamp(), "data/template-index.json updatedAt"
    return os.path.getmtime(path), "data/template-index.json mtime"


def committed_changes(t):
    """(base 설명, HEAD 이동 목록, 바뀐 경로). reflog 가 t 에 닿지 않으면 커밋 시각 기준(근사)."""
    reflog = parse_reflog(git("log", "-g", "--date=unix", "--format=%H%x09%gd%x09%gs", "HEAD", check=False))
    base, after = head_at(reflog, t)
    how = "reflog"
    if base is None:
        base = git("rev-list", "-1", "--before=@%d" % int(t), "HEAD", check=False).strip() or None
        how = "커밋 시각(근사 — reflog 가 빌드 시각까지 없음)"
    if base is None:
        return "없음", after, None
    names = git("diff", "--name-only", "-z", "--no-renames", base, "HEAD", "--", *WATCH_PATHSPECS)
    return "%s (%s)" % (base[:11], how), after, [p for p in names.split("\0") if p]


def worktree_changes(t):
    raw = git("status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all", "--", *WATCH_PATHSPECS)
    return dirty_after(parse_status_z(raw), t, lambda rel: file_mtime(os.path.join(repo_root(), rel)))


def output_paths():
    return [os.path.join(repo_root(), *DOCS_DIR.split("/"), name) for name, _why, _by in COMMIT_FILES]


def index_state():
    """(색인 시각 = 있는 생성물 mtime 최솟값 또는 None, 없는 생성물 이름, 입력 [(이름, 경로, mtime)])."""
    outs = output_paths()
    missing = [os.path.basename(p) for p in outs if not os.path.exists(p)]
    have = [os.path.getmtime(p) for p in outs if os.path.exists(p)]
    index_at = min(have) if have else None
    inputs = [(label, rel, file_mtime(C.p(*rel.split("/")))) for label, rel in INDEX_INPUTS]
    return index_at, missing, inputs


def unity_processes():
    """실행 중인 Unity.exe 수(CIM). 확인 못 하면 None. tasklist 는 0 으로 오보해 쓰지 않는다."""
    cmd = "@(Get-CimInstance Win32_Process -Filter \"Name='Unity.exe'\").Count"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
        return int(r.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def gather_plan():
    t, t_src = build_time()
    base, moves, committed = committed_changes(t)
    dirty, unknown = worktree_changes(t)
    index_at, missing, inputs = index_state()
    newer = newer_inputs(inputs, index_at)
    changes = sorted(set((committed or []) + dirty))
    level, reasons = decide(changes, newer, missing)
    if committed is None:
        level, reasons = LEVEL_FULL, ["빌드 시각의 HEAD 를 찾지 못했다 — 변경을 판정할 수 없어 전체 재생성"]
    return dict(t=t, t_src=t_src, base=base, moves=moves, committed=committed or [], dirty=dirty, unknown=unknown,
                index_at=index_at, missing=missing, newer=newer, level=level, reasons=reasons, changes=changes)


# ---------------------------------------------------------------- 출력
def fmt_time(ts):
    return "-" if ts is None else datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def path_summary(title, paths):
    by = collections.defaultdict(list)
    for p in paths:
        by[category(p) or "other"].append(p)
    L = ["%s: %d" % (title, len(paths)) + ("" if paths else " (없음)")]
    for c in CATEGORIES + ("other",):
        if by[c]:
            more = len(by[c]) - SAMPLE_PATHS
            L.append("  %s %d — %s%s" % (c, len(by[c]), ", ".join(by[c][:SAMPLE_PATHS]), " 외 %d" % more if more > 0 else ""))
    return L


def step_lines(steps):
    return ["  %2d. %s%s   # %s" % (i, s.cmd, "   [Unity 배치 — GUI 를 닫은 뒤]" if s.unity else "", s.note)
            for i, s in enumerate(steps, 1)]


def commit_lines():
    files = " ".join("%s/%s" % (DOCS_DIR, name) for name, _w, _b in COMMIT_FILES)
    return ["  git add -f " + files, "  git add AGENTS.md   # 안내 줄이 바뀐 경우만",
            "  git commit -m \"docs(ui-design-system): ...\" -- " + files + " [AGENTS.md]"]


def print_plan(s, unity=None):
    L = ["데이터 빌드 시각: %s (%s)" % (fmt_time(s["t"]), s["t_src"]),
         "그때 HEAD: %s · 그 뒤 HEAD 이동 %d건" % (s["base"], len(s["moves"]))]
    L += ["  %s %s %s" % (fmt_time(ts), sha[:11], msg) for sha, ts, msg in s["moves"][:SAMPLE_PATHS]]
    L += path_summary("커밋 변경(빌드 뒤, 감시 경로)", s["committed"])
    L += path_summary("작업 트리 변경(빌드 뒤 수정, 감시 경로)", s["dirty"])
    if s["unknown"]:
        L.append("  ⚠ 지워져 시각을 알 수 없는 작업 트리 변경 %d — 판정에 넣지 않았다: %s" % (
            len(s["unknown"]), ", ".join(s["unknown"][:SAMPLE_PATHS])))
    L.append("색인 시각(생성물 mtime 최솟값): %s%s" % (fmt_time(s["index_at"]),
                                               " · 없는 파일 " + ", ".join(s["missing"]) if s["missing"] else ""))
    L += ["", "판정: %s" % LEVEL_LABELS[s["level"]]] + ["  - " + r for r in s["reasons"]]
    steps = commands(s["level"])
    if steps:
        L += ["", "명령 (ui-audit/ 에서, 위에서부터):"] + step_lines(steps)
    if s["level"] == LEVEL_FULL:
        L.append("  Unity.exe 실행 중: %s — 배치 단계 전에 0 이어야 한다 (확인: PowerShell `%s`, tasklist 는 오보, -nographics 금지)"
                 % ("확인 실패" if unity is None else unity, UNITY_CHECK))
    if s["level"] == LEVEL_INDEX:
        L.append("  → `python scripts/ds_publish.py --run-index` 가 위 색인 단계와 ds_index --check 를 실행한다")
    if steps:
        L += ["", "검사 통과 뒤 커밋(사람 승인, 저장소 루트에서 — 실행하지 않음):"] + commit_lines()
    print("\n".join(L))


def plan():
    s = gather_plan()
    print_plan(s, unity_processes() if s["level"] == LEVEL_FULL else None)
    return 0


def run_steps(steps, runner):
    """각 단계를 차례로 실행. 실패하면 멈추고 1."""
    for s in steps:
        assert not s.unity, "Unity 단계는 실행하지 않는다: " + s.cmd
        print("\n$ " + s.cmd, flush=True)
        if runner(s.cmd.split()[1:]) != 0:
            print("실패: %s — 여기서 멈춘다" % s.cmd)
            return 1
    return 0


def subprocess_runner(args):
    return subprocess.run([sys.executable] + args, cwd=C.ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8")).returncode


def run_index(runner=subprocess_runner, level=None):
    if level is None:
        level = gather_plan()["level"]
    if level == LEVEL_FULL:
        print("⚠ 판정이 '전체 재생성'이다 — 색인은 지금 데이터(낡았을 수 있음) 기준으로 만든다. Unity 단계는 실행하지 않는다:")
        print("\n".join(step_lines([s for s in FULL_STEPS if s.unity])))
        print("  전체 순서는 `python scripts/ds_publish.py --plan`")
    rc = run_steps(list(INDEX_STEPS) + [CHECK_STEPS[0]], runner)
    if rc == 0:
        print("\n색인 단계 완료. 다음: `%s` → 커밋(사람 승인, UPDATE.md 5절)" % CHECK_STEPS[1].cmd)
    return rc


# ---------------------------------------------------------------- 공유 문서 (ds_index.py --run 이 쓴다)
GEN_NOTE = "> 자동 생성 — `ui-audit/scripts/ds_publish.py`(쓰기는 `ds_index.py --run`). 손으로 고치지 말 것(다시 만들면 덮어쓴다)."


def render_update():
    files = ["%s/%s" % (DOCS_DIR, n) for n, _w, _b in COMMIT_FILES]
    shared = ["\"%s\"" % p if "*" in p else p for p, _w in SHARED_DATA]
    L = [
        "# UI 디자인 시스템 색인 — 갱신·공유 절차",
        "",
        GEN_NOTE,
        "> 이 폴더(`%s/`)는 `ui-audit/` 작업 공간 데이터의 **요약**이다. 설계·카탈로그에 쓰는 원본(배치·렌더·흐름·토큰·카탈로그 HTML)은"
        " %sgit 으로 공유한다(4절) — 팀 PC 는 pull 후 `ui-audit/catalog/*.html` 을 파일로 열고, 피드백만 %s에서 남긴다."
        % (DOCS_DIR, SHARED_SINCE + " 부터 " if SHARED_SINCE else "", REVIEW_SERVER),
        "",
        "## 1. 누가",
        "- **`ui-audit/` 작업 공간이 있는 체크아웃의 담당자.** 데이터 재생성에 그 작업 공간과 Unity 가 필요하다.",
        "- 다른 팀원·팀 에이전트는 이 폴더를 **읽기만** 한다. 내용이 틀렸으면 담당자에게 알린다(생성물이라 손으로 고치면 다음 갱신에 덮어쓴다).",
        "",
        "## 2. 언제",
        "| 계기 | 범위 |",
        "|---|---|",
        "| `git pull` 등으로 HEAD 가 움직여 프리팹(`*.prefab`)·씬(`*.unity`)·스크립트(%s 의 `*.cs`)·Addressable 그룹이 바뀜 | 전체 재생성(Unity 배치 포함) |"
        % "·".join("`%s`" % r for r in WATCH_CODE_ROOTS),
        "| 작업 트리에서 위 파일이 데이터 빌드 뒤에 수정됨 | 전체 재생성 |",
        "| 표준 결정 기록(`decisions.json`) · 역할 승인(`ds/roles.json`) · 토큰 이름 확정(`ds/token-names.json`) | 색인만 |",
        "| 색인 생성 스크립트·데이터가 색인 파일보다 새로움 | 색인만 |",
        "",
        "판정은 손으로 하지 않는다: `python scripts/ds_publish.py --plan` 이 데이터 빌드 시각"
        "(`ui-audit/data/template-index.json` 의 `updatedAt`, INDEX.md 머리에도 찍힘)의 HEAD(reflog)와 지금을 비교해 범위와 명령을 낸다.",
        "",
        "## 3. 순서",
        "명령은 모두 `ui-audit/` 에서 실행한다(5단계 커밋만 저장소 루트).",
        "1. **pull (사람)** — 로컬 변경을 stash·폐기하지 않는다. 충돌하면 멈추고 사람에게 넘긴다.",
        "2. **판정** — `python scripts/ds_publish.py --plan`",
        "3. **재생성** — 판정대로.",
        "   - 전체 재생성: Unity GUI 를 닫고(5절 'Unity 배치 조건') 아래를 위에서부터. `[Unity]` 단계가 배치 모드로 Unity 를 띄운다.",
        "```",
    ]
    L += ["%s%s   # %s" % (s.cmd, "   [Unity]" if s.unity else "", s.note) for s in FULL_STEPS + INDEX_STEPS]
    L += [
        "```",
        "   - 색인만: `python scripts/ds_publish.py --run-index` (= %s → `%s`)" % (
            " · ".join("`%s`" % s.cmd for s in INDEX_STEPS), CHECK_STEPS[0].cmd),
        "4. **검사** — 모두 통과해야 커밋한다.",
        "```",
    ]
    L += ["%s   # %s" % (s.cmd, s.note) for s in CHECK_STEPS]
    L += [
        "python scripts/build_catalog.py --check   # 전체 재생성 때만 — 깨진 링크 0",
        "```",
        "5. **커밋 (사람 승인 뒤, 저장소 루트에서)** — allowlist 만. 경로를 붙인 `git commit -- <파일>` 로 다른 세션이 스테이지한 파일을 섞지 않는다.",
        "```",
        "git add -f " + " ".join(files),
        "git add AGENTS.md          # 안내 줄이 바뀐 경우만",
        "git commit -m \"docs(ui-design-system): refresh index (data <updatedAt>)\" -- " + " ".join(files),
        "```",
        "   전체 재생성이면 공유 데이터(4절)도 따로 커밋한다 — 경로 한정 `--all` 로 지워진 파일까지 반영한다.",
        "```",
        "git add -f --all -- " + " ".join(shared + ["'%s'" % x for x in SHARED_EXCLUDES]),
        "git commit -m \"chore(ui-audit): refresh shared design data (data <updatedAt>)\" -- " + " ".join(shared),
        "```",
        "   푸시도 사람이 승인한다." + (" " + AFTER_PUSH_NOTE if AFTER_PUSH_NOTE else ""),
        "",
        "## 4. 커밋 대상 (allowlist)",
        "| 파일 | 이유 | 만드는 스크립트 |",
        "|---|---|---|",
    ]
    L += ["| `%s/%s` | %s | %s |" % (DOCS_DIR, n, why, by) for n, why, by in COMMIT_FILES]
    L += ["| " + AGENTS_NOTE + " | 팀 에이전트가 공통으로 읽는 진입점 | 사람 |", "",
          "공유 데이터(전체 재생성 때, 별도 커밋):", "| 경로 | 내용 |", "|---|---|"]
    L += ["| `%s` | %s |" % row for row in SHARED_DATA]
    L += ["", "커밋하지 않는 것:", "| 대상 | 이유 |", "|---|---|"]
    L += ["| %s | %s |" % row for row in NOT_COMMITTED]
    L += [
        "",
        "## 5. 주의",
        "- **공유 트리.** 같은 체크아웃에서 세션 여럿이 일한다. `git stash`·`reset`·`checkout --`·`clean` 으로 남의 변경을 건드리지 않는다.",
        "- **`git add -A` · `git add .` · `git commit -a` 금지.** 4절 allowlist 만 올린다(공유 데이터의 `--all` 은 경로 한정이라 예외).",
        "- **`Docs/` 는 gitignore** 라 `git add -f` 가 필요하다(팀 관례 — 공유 문서만 force-add).",
        "- **`.unity` · `.playable` 은 커밋하지 않는다.**",
        "- **Unity 배치 조건**: 같은 프로젝트를 연 Unity GUI 가 없어야 한다. 확인은 PowerShell `%s` — `tasklist` 는 Unity.exe 를 0 으로 오보한다. 렌더가 필요하므로 `-nographics` 금지." % UNITY_CHECK,
        "- 색 **토큰** 결정을 기록하면 노드 카탈로그(A5·A6)가 무효가 된다 — 그때는 `ui-audit/reports/FINAL.md` 2절 절차로 노드 카탈로그도 다시 빌드한다.",
        "- 생성물의 `ui-audit/...` 경로(썸네일·배치 맵)는 공유 데이터를 pull 한 체크아웃이면 열린다. 카탈로그의 스프라이트는 `Assets/` 를 상대 경로로 읽으므로 Unity 체크아웃에서 파일로 열면 된다.",
    ]
    return "\n".join(L) + "\n"


SKILL_NAME = "ui-new-screen"
SKILL_DESCRIPTION = ("새 UI 화면(View)·팝업(Popup)·UI 프리팹 빌드 툴을 만들 때 기존 프리팹 템플릿·골격 레시피·연결 체크리스트를 쓰게 하는 절차. "
                     "'새 화면 만들어', '새 팝업 추가', '목업대로 UI 구성', 'View/Popup 프리팹 생성', '빌드 툴로 UI 만들기' 같은 요청에 사용.")
READ_ORDER = tuple(x for x in (
    ("INDEX.md", "규칙·금지·많이 쓰는 템플릿·표준 미정 지점. 맨 먼저 전부 읽는다"),
    ("skeletons.md", "골격 형(View 기본형·목록+탭형·Popup Tall·Wide형)을 고른다"),
    ("screens.jsonl", "쓸 템플릿·형으로 grep 해 `cleanReference=true` 인 참고 화면을 찾는다"),
    (CHECKLIST["file"], CHECKLIST["read_why"]) if CHECKLIST else None,
    ("templates.jsonl", "필요한 템플릿 카드만 grep 한다(통째로 읽지 않는다)"),
) if x)
WORK_ORDER = (
    ("`INDEX.md` → 참고 화면(`cleanReference=true`)·골격 레시피 선택", None),
    ("조합안 제시: 와이어(노드 트리) + 재사용 템플릿 목록(slug·standard) + 새로 만들 것 목록 + 표준이 없는 지점", "승인"),
    ("빌드 툴로 프리팹 생성 + %s연결 코드" % ("`%s` 대로 " % CHECKLIST["file"] if CHECKLIST else ""), None),
    ("렌더 → 참고 화면과 나란히 대조 보고", "육안 확인"),
    ("리뷰", "커밋 승인"),
)
PROHIBITED = (
    "`PrefabUnpackMode.Completely` 언팩 — 중첩 템플릿 링크가 전부 끊겨 같은 이름의 사본이 된다. 복제는 `PrefabUtility.LoadPrefabContents`(또는 `OutermostRoot`)",
    "기존 화면 프리팹 수정 — 새 화면은 새 프리팹으로",
    "템플릿과 같은 모양을 Image·TMP 로 다시 조립 — 템플릿을 인스턴스로 넣는다. 맞는 템플릿이 없으면 '새로 만들 것'에 적고 승인받는다",
    "새 스프라이트 · 토큰 밖 색",
    "`standard` 가 `폐기→X` 인 템플릿 — X 를 쓴다. `미정` 이면 고른 근거를 조합안에 적고 사람 확인",
    "`cleanReference=false` 화면의 구조를 따라 하기",
    "사람 승인 없는 커밋 · `git add -A` · `.unity`/`.playable` 커밋",
    "이 폴더(`%s/`)의 파일을 손으로 고치기 — 생성물이다([`UPDATE.md`](UPDATE.md))" % DOCS_DIR,
)


def render_skill():
    L = [
        "---",
        "name: " + SKILL_NAME,
        "description: " + SKILL_DESCRIPTION,
        "---",
        "",
        "# 새 UI 화면 만들기 (팀 에이전트용)",
        "",
        GEN_NOTE,
        "> 저장소 문서다(`.claude/` 는 git 밖이라 팀에 공유되지 않는다). Claude Code 스킬로 쓰려면 이 파일을 "
        "`.claude/skills/%s/SKILL.md` 로 복사한다. 복사하지 않아도 `AGENTS.md` → `INDEX.md` → 이 파일로 이어진다." % SKILL_NAME,
        "> 경로는 저장소 루트 기준. 이 폴더는 `%s/`." % DOCS_DIR,
        "",
        "## 언제 쓰나",
        "- 새 View·Popup 화면, 새 UI 프리팹, UI 프리팹을 만드는 에디터 빌드 툴(`%s/**`)을 만들 때." % DC.EDITOR_REL,
        "- HTML 목업·기획서를 받아 화면을 구성할 때.",
        "- 쓰지 않는 때: 기존 화면 하나의 버그·문구 수정(이 절차의 '기존 프리팹 수정 금지'는 새 화면 작업에 대한 것이다).",
        "",
        "## 읽는 순서",
    ]
    L += ["%d. [`%s`](%s) — %s" % (i, n, n, why) for i, (n, why) in enumerate(READ_ORDER, 1)]
    L += [
        "",
        "## 지시 템플릿 (사용자 → 에이전트)",
        "지시에 빈 칸이 있으면 작업 전에 빈 칸을 **한 메시지로 묶어** 묻는다. 모르는 데이터는 '미정'으로 두고 진행한다.",
        "```",
    ]
    L += list(INSTRUCTION_TEMPLATE)
    L += ["```", "", "## 작업 순서 (◆ = 사람 확인 — 확인 전에는 다음 단계로 넘어가지 않는다)"]
    L += ["%d. %s%s" % (i, what, " ◆" + gate if gate else "") for i, (what, gate) in enumerate(WORK_ORDER, 1)]
    L += [
        "",
        "- 산출 범위가 '와이어까지'면 2에서, '프리팹까지'면 3의 프리팹까지에서 멈춘다.",
        "- 2의 조합안은 `skeletons.md` 레시피 트리 모양으로 쓰고, 노드마다 템플릿이면 `[slug]`, 아니면 '새로 만들 것'으로 표시한다. 표준 미정 지점은 고르지 말고 ⚠ 로 표시한다.",
        "- 4의 자동 렌더 대조 도구는 아직 없다(계획 P2-2). Unity 에서 새 프리팹과 참고 화면을 캡처해 나란히 보고한다.",
        "",
        "## 금지",
    ]
    L += ["- " + x for x in PROHIBITED]
    L += [
        "",
        "## 로컬 작업 공간이 없을 때",
        "- 문서 안의 `ui-audit/...` 경로(썸네일·배치 맵 페이지)는 작업 공간이 있는 체크아웃에서만 열린다. 없으면 이 폴더의 문서·jsonl 만으로 한다.",
        "- 색인이 낡았다고 보이면(새 화면이 `screens.jsonl` 에 없음 등) 고치지 말고 담당자에게 갱신을 요청한다([`UPDATE.md`](UPDATE.md)).",
    ]
    return "\n".join(L) + "\n"


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--run-index", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.plan:
        return plan()
    if a.run_index:
        return run_index()
    ap.print_help()
    return 2


# ---------------------------------------------------------------- 자체 테스트
def selftest():
    B = 1_000_000  # 가짜 빌드 시각
    assert [category(p) for p in ("Assets/UI/A.prefab", "Assets/S/T.unity", "Assets/Game/Scripts/X.cs",
                                  "Assets/AddressableAssetsData/AssetGroups/UI.asset", "Docs/x.md")] == \
        ["prefab", "scene", "code", "addressable", None]
    reflog = parse_reflog("c3\tHEAD@{%d}\tcommit: docs\nc2\tHEAD@{%d}\tpull: Merge\nc1\tHEAD@{%d}\tcommit: x\nbad line\n"
                          % (B + 200, B + 100, B - 50))
    assert [e[0] for e in reflog] == ["c3", "c2", "c1"]
    base, after = head_at(reflog, B)
    assert base == "c1" and [e[0] for e in after] == ["c3", "c2"], (base, after)
    assert head_at(reflog, B + 150)[0] == "c2" and head_at(reflog, B - 100)[0] is None  # reflog 가 빌드 시각까지 닿지 않음
    entries = parse_status_z(" M Assets/A.prefab\0?? Assets/New Folder/B.prefab\0 D Assets/Gone.unity\0")
    assert entries == [(" M", "Assets/A.prefab"), ("??", "Assets/New Folder/B.prefab"), (" D", "Assets/Gone.unity")]
    mt = {"Assets/A.prefab": B - 1, "Assets/New Folder/B.prefab": B + 1}
    changed, unknown = dirty_after(entries, B, mt.get)
    assert changed == ["Assets/New Folder/B.prefab"] and unknown == ["Assets/Gone.unity"], (changed, unknown)
    inputs = [("결정 기록", "decisions.json", B + 10), ("역할 승인", "ds/roles.json", None), ("데이터 빌드", "d.json", B - 10)]
    assert newer_inputs(inputs, B) == [("결정 기록", "decisions.json")]
    assert newer_inputs(inputs, None) == []
    # 판정 4가지
    lv, why = decide(["Assets/X.cs", "Assets/AddressableAssetsData/AssetGroups/G.asset", "Assets/Y.cs"], [("결정 기록", "decisions.json")], [])
    assert lv == LEVEL_FULL and why == ["데이터 빌드 뒤 바뀐 파일: code 2 · addressable 1"], why
    lv, why = decide([], [("결정 기록", "decisions.json")], [])
    assert lv == LEVEL_INDEX and "decisions.json(결정 기록)" in why[0]
    lv, why = decide([], [], ["UPDATE.md"])
    assert lv == LEVEL_INDEX and why == ["색인 파일 없음: UPDATE.md"]
    assert decide([], [], [])[0] == LEVEL_NONE
    # 명령 목록: 전체 = FINAL 5절 → 7절 → 색인 → 검사, 색인만엔 Unity 없음
    full = commands(LEVEL_FULL)
    cmds = [s.cmd for s in full]
    assert cmds[0] == "python scripts/parse_prefab.py --reindex" and cmds[-1] == "python scripts/a0_setup.py --check"
    order = [cmds.index(c) for c in ("python scripts/thumbs.py --list --run --collect", "python scripts/templates.py --assemble",
                                     "python scripts/layout_map.py --list --run --collect", "python scripts/ds_index.py --run")]
    assert order == sorted(order), order
    extra = with_project_steps((Step("a", False, ""), Step("c", False, "")),
                               [{"after": "a", "cmd": "python scripts/common.py --x", "note": "있음"},
                                {"after": "a", "cmd": "python scripts/no_such_producer.py", "note": "없음"}])
    assert [s.cmd for s in extra] == ["a", "python scripts/common.py --x", "c"], extra
    assert [s.cmd.split()[1] for s in full if s.unity] == ["scripts/thumbs.py", "scripts/layout_map.py"]
    assert not any(s.unity for s in commands(LEVEL_INDEX)) and commands(LEVEL_NONE) == []
    assert all(not any(x in s.cmd for x in ("git ", "-nographics")) for s in full)
    # --run-index: 색인 3단계 + check 만, Unity 단계 없음, 실패하면 멈춤
    calls, sink = [], io.StringIO()
    with contextlib.redirect_stdout(sink):
        assert run_index(lambda a: calls.append(a) or 0, level=LEVEL_FULL) == 0
    assert "thumbs.py" in sink.getvalue() and "layout_map.py --list" in sink.getvalue()  # Unity 단계는 안내만
    assert calls == [s.cmd.split()[1:] for s in INDEX_STEPS] + [["scripts/ds_index.py", "--check"]], calls
    calls2 = []
    with contextlib.redirect_stdout(io.StringIO()):
        assert run_index(lambda a: calls2.append(a) or (1 if "ds_skeletons" in a[0] else 0), level=LEVEL_INDEX) == 1
    assert len(calls2) == 2
    # 문서
    up = render_update()
    for name, _w, _b in COMMIT_FILES:
        assert "`%s/%s`" % (DOCS_DIR, name) in up, name
    assert "git add -f " + " ".join("%s/%s" % (DOCS_DIR, n) for n, _w, _b in COMMIT_FILES) in up
    for s in FULL_STEPS + INDEX_STEPS + CHECK_STEPS:
        assert s.cmd in up, s.cmd
    for must in ("`git add -A`", "`.unity` · `.playable`", "Get-CimInstance Win32_Process", "-nographics", "`tasklist`",
                 "ds_publish.py --plan", "ds_publish.py --run-index", "이미지(PNG)", "AGENTS.md", "gitignore"):
        assert must in up, must
    assert up.count("   [Unity]   # ") == 2
    sk = render_skill()
    head = sk.split("\n")
    assert head[0] == "---" and head[1] == "name: " + SKILL_NAME and head[2].startswith("description: ") and head[3] == "---"
    pos = [sk.index("](%s)" % n) for n, _w in READ_ORDER]
    assert pos == sorted(pos) and [n for n, _w in READ_ORDER][0] == "INDEX.md" and READ_ORDER[-1][0] == "templates.jsonl"
    assert all(line in sk for line in INSTRUCTION_TEMPLATE)
    assert sk.count("◆") == 4 and "◆승인" in sk.replace(" ◆", "◆") and ".claude/skills/%s/SKILL.md" % SKILL_NAME in sk
    assert "Completely" in sk and "LoadPrefabContents" in sk and "AGENTS.md" in sk
    print("ds_publish.py selftest ok · 판정 4 · 명령 전체 %d(Unity 2)/색인 %d · UPDATE %d줄 · SKILL %d줄" % (
        len(full), len(commands(LEVEL_INDEX)), up.count("\n"), sk.count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
