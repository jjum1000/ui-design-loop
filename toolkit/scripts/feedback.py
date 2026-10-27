"""설계 단계 피드백 루프 — Claude 쪽 CLI (T4).

정본 = feedback/CONTRACT.md, 특히 4.4(이 CLI의 명세·크롭 샷 규칙)·6절(권한 경계).
이 스크립트가 쓰는 모든 이벤트는 feedback_core.append(event, "claude") 를 통해서만 기록된다
(by=claude 로 허용되는 type 은 comment·claim·release·revision 뿐 — CONTRACT 6절. open·close·reopen 은
사용자가 서버(review_server.py)를 거쳐서만 남기므로 이 CLI에는 해당 명령이 없다).

사용(ui-audit/ 에서):
  python scripts/feedback.py list [--screen S] [--status open,reopened] [--json]
  python scripts/feedback.py show <id>
  python scripts/feedback.py claim <id...>
  python scripts/feedback.py release <id...> --reason "..."
  python scripts/feedback.py revise <id...> --summary "..." [--new-version V] [--no-shots]
  python scripts/feedback.py comment <id> "text"
  python scripts/feedback.py keys <screen> [--stage wire|mockup] [--version V] [--top 15]
  python scripts/feedback.py build
  python scripts/feedback.py --selftest

크롭 샷(claim 의 before, revise 의 after)과 keys 는 headless Chromium(python playwright)을 그 명령 동안
한 번만 띄워 여러 페이지/샷을 처리한다. claim·revise 의 무거운 작업(파일 복사·스크린샷·diff 계산)은
feedback_core.lock() 밖(임시 폴더)에서 먼저 끝내고, id 발급과 최종 파일 이동·append 만 락 안에서 한다
(CONTRACT 4.2 — 락을 길게 잡지 않아 다른 프로세스의 append 가 10초 타임아웃에 걸리지 않게 한다).

한계 / 판단한 지점(오케스트레이터 보고 ③과 동일 — 코드에도 남겨 둔다):
- 바이너리 파일의 diff 표시는 CONTRACT 1절 표의 한국어 "바이너리 변경"과 오케스트레이터 지시의
  "Binary files differ" 표현이 다르다. 이 구현은 뒤쪽(영문, GNU diff 관례와 동일)을 따른다 — 의미는
  같고(두 쪽 다 "내용 비교 없이 한 줄로만 표시") 어느 쪽 문자열을 쓰든 계약 위반은 아니라고 판단했다.
- "키 없는 큰 요소" 판정은 오케스트레이터가 이 작업 지시에서 고정한 정의(#canvas 또는 body, 자기 면적
  2% 이상, 가장 가까운 data-area 조상이 없거나 그 조상이 캔버스의 40% 이상, 자손에 data-area 없음,
  bbox 중복 제거)를 그대로 코드로 옮겼다 — CONTRACT 5절은 "셀렉터로 앵커된 피드백이 쌓이면 보강 대상을
  보고한다" 정도로만 적어 구체 정의가 없어 모순은 아니지만, 정의 자체는 이 구현이 고정한 것이다.
- claim/revise 의 상태 선택: 피드백의 state 필드가 있으면 그 state 의 steps, 없으면 등록부의 첫 state.
  steps 가 전혀 없는 stage(states: [])는 아무 호출 없이 페이지를 그대로 둔다.

R1 리뷰 반영(경로 컨테인먼트·예외 처리·CSS 이스케이프):
- registry 의 files(글롭 포함)·entry 는 claim 복사·revise diff·list 소스grep 전에 _safe_abs() 로
  ui-audit 루트 밖(..·드라이브 문자·절대경로·역슬래시·심링크 탈출)을 거부한다 — 위반이면 이벤트 없이
  CliError 로 즉시 끝난다.
- claim/revise 의 락 안 append 는 FeedbackError 뿐 아니라 어떤 예외(BaseException)에도 옮긴 폴더/파일을
  지우고 재발생시킨다. shutil.move 전에는 목적지(snap/<cl>, revisions/<rev>, <rev>.diff)가 이미 있으면
  (로그에 없는 고아) 지우고 옮긴다 — move 가 기존 디렉터리 안으로 들어가 중첩되는 것을 막는다.
- _crop_shot 의 [data-idx="..."] 보간은 CSS 문자열 이스케이프(백슬래시·인용부호)를 거친다.

개정 V 반영(2026-10-23, 시안 풀다운 — CONTRACT 2·3·4.4절):
- 등록부 조회(_stage_entry)는 (screen, stage, version) 기준이다. 같은 stage 에 시안(variant)이 여러 개
  있을 수 있고, 등록부 순서의 첫 항목이 그 stage 의 기본 시안이다. 조회는 feedback_core._stage_variants
  (코어가 이미 개정 V 를 반영해 둔 비공개 헬퍼)를 재사용한다 — feedback_core.py 는 수정하지 않는다.
- claim 은 ids 의 screen·stage·version 이 모두 같아야 하고, 그 (screen, stage, version) 이 등록부에
  없으면 CliError 로 거부한다(이벤트 없음). revise 는 같은 claim 의 ids 라 screen/stage/version 이 이미
  claim 시점에 동일함이 보장돼 있으므로 그 값을 그대로 쓴다.
- list 는 등록부에서 찾은 시안의 label 을 버전 옆에 보여 주고, 등록부에 없는 시안이면 entry 칸에
  "(등록부에 없음)"(이전부터 있던 동작 — version 을 반영해 재확인했다).
- keys 에 --version 을 추가했다. 기본(필터 없음)은 등록된 모든 (stage, version) — 이전부터 "그 stage 의
  모든 항목"을 돌던 루프가 이제는 등록부에 쌓인 시안 전부를 자연히 순회한다.

개정 L 반영(2026-10-23, 하단 도크·템플릿 교체 제안 — CONTRACT 7.3절):
- list·show 가 item 의 path·suggest(core 가 이미 접어 둔 값, 검증은 feedback_core 몫)를 7.3 형식의 줄로
  덧붙인다: path 가 있으면 "- 경로: <항목> › ...", suggest 가 있으면 "- 교체 제안: <현재> → <제안> ...".
  둘 다 CONTRACT 4.4 열거 순서대로 리비전 요약 다음, 빈 줄 전에 온다.
- 키트 정보는 catalog/library/index.json(N1 생성물)을 읽는다 — 이 CLI 는 그 파일을 만들지 않고 읽기만
  한다(없으면 "키트 정보 없음(라이브러리 미빌드)", 제안 slug 에 kit 행이 없으면 "키트에 없음").

R4 LOW 반영: catalog/library/index.json 이 JSON 파싱 실패이거나 templates 가 dict 가 아니면(손상)
_load_lib_index() 가 AttributeError 를 내지 않고 False 를 돌려주고, _kit_tail 이 그걸 "키트 정보
없음(라이브러리 손상)" 으로 안내한다(미빌드=None 과 구분).
"""
import argparse
import difflib
import fnmatch
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import feedback_core as FC  # noqa: E402

CROP_MARGIN = 16
VIEWPORT = {"width": 1920, "height": 1080}


class CliError(Exception):
    """사용자/구현 레벨 오류(core 의 FeedbackError 와 별도) — main() 에서 공통으로 처리."""


# ================================================================ registry·파일 도우미
def _validate_rel(rel, what="경로"):
    """registry 의 상대 경로(files·entry) 문자열 검사 — ui-audit 루트를 벗어날 수 있는 형태를 거부한다.
    절대경로·드라이브 문자·역슬래시·'.'/'..' 세그먼트를 막는다. 통과하면 그대로 돌려준다."""
    if not rel or "\\" in rel:
        raise CliError("안전하지 않은 %s(역슬래시/빈 값 금지): %r" % (what, rel))
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise CliError("안전하지 않은 %s(절대/드라이브 경로 금지): %r" % (what, rel))
    if any(seg in ("", ".", "..") for seg in rel.split("/")):
        raise CliError("안전하지 않은 %s(.. 세그먼트 금지): %r" % (what, rel))
    return rel


def _safe_abs(rel, what="경로"):
    """_validate_rel 통과 후 realpath 가 ui-audit 루트 안인지 재확인(심링크 탈출 등 방어). 통과하면 조인된 경로."""
    _validate_rel(rel, what)
    joined = C.p(*rel.split("/"))
    root_real = os.path.realpath(C.ROOT)
    full_real = os.path.realpath(joined)
    try:
        inside = os.path.commonpath([root_real, full_real]) == root_real
    except ValueError:  # 다른 드라이브 등 — commonpath 가 비교 불가
        inside = False
    if not inside:
        raise CliError("안전하지 않은 %s(ui-audit 루트 밖): %r" % (what, rel))
    return joined


def _entry_abs(stage_entry):
    """registry stage 의 entry 를 안전성 검사 뒤 절대경로로."""
    return _safe_abs(stage_entry.get("entry", ""), "entry")


def _clear_orphan(path):
    """목적지가 이미 있으면(로그에 없는 고아 — 이전 실패·수동 생성 등) 지운다.
    shutil.move 는 목적지가 이미 있는 디렉터리면 그 "안으로" 옮겨 한 단계 중첩시키므로, claim/revise 가
    snap/<cl>·revisions/<rev>(.diff) 를 만들기 직전에 반드시 불러 선점 상태를 치운다."""
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.exists(path):
        os.remove(path)


def _stage_entry(registry, screen, stage, version=None, required=True):
    """(screen, stage, version) 으로 등록부 항목(시안)을 찾는다(개정 V — 같은 stage 에 시안이 여러 개일
    수 있고, 등록부 순서의 첫 항목이 기본 시안). version 을 안 주면 기본 시안. feedback_core._stage_variants
    를 재사용한다(코어가 이미 개정 V 를 반영해 둔 같은 로직 — feedback_core.py 는 수정 금지 대상)."""
    variants = FC._stage_variants(registry, screen, stage)  # noqa: SLF001 — 코어의 동일 조회 재사용
    if variants is None:
        if required:
            raise CliError("없는 screen: %s" % screen)
        return None
    if not variants:
        if required:
            raise CliError("%s 화면에 없는 stage: %s" % (screen, stage))
        return None
    if version is None:
        return variants[0]  # 첫 항목 = 기본 시안
    for s in variants:
        if s.get("version") == version:
            return s
    if required:
        raise CliError("%s/%s 에 없는 version(시안): %s" % (screen, stage, version))
    return None


def _expand_registry_files(patterns):
    """registry 의 files(글롭 가능, 하위 폴더 미포함) → 실제 존재하는 상대 경로 목록(중복 제거, 순서 유지).
    각 패턴(글롭이면 디렉터리 부분)은 _safe_abs 로 ui-audit 루트 컨테인먼트를 통과해야 한다 — 위반이면
    CliError(이벤트 없이 즉시 거부)."""
    out = []
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            if "/" in pat:
                d, base_pat = pat.rsplit("/", 1)
            else:
                d, base_pat = "", pat
            if d:
                _safe_abs(d, "files 글롭 경로")
            dirpath = C.p(*d.split("/")) if d else C.p()
            if os.path.isdir(dirpath):
                for name in sorted(os.listdir(dirpath)):  # os.listdir 는 "."·".." 를 돌려주지 않는다
                    full = os.path.join(dirpath, name)
                    if os.path.isfile(full) and fnmatch.fnmatch(name, base_pat):
                        out.append((d + "/" + name) if d else name)
        else:
            _safe_abs(pat, "files")
            out.append(pat)
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _walk_rel(base):
    out = []
    if not os.path.isdir(base):
        return out
    for dp, _dn, fn in os.walk(base):
        for f in fn:
            full = os.path.join(dp, f)
            out.append(os.path.relpath(full, base).replace("\\", "/"))
    return out


def _lookup_items(state, ids):
    items, missing = [], []
    for i in ids:
        it = state["items"].get(i)
        (items if it is not None else missing).append(it if it is not None else i)
    if missing:
        raise CliError("모르는 id: %s" % ", ".join(missing))
    return items


def _common_claim(items, ids):
    claims = {it["claim"] for it in items}
    if len(claims) != 1 or None in claims:
        detail = ", ".join("%s(claim=%s)" % (it["id"], it["claim"]) for it in items)
        raise CliError("ids 가 같은 claim 으로 claimed 상태가 아님: %s" % detail)
    return claims.pop()


def _grep_component(files, component, limit=10):
    """registry files 안에서 data-area="<component>" 또는 '<component>'/"<component>" 를 찾아 경로:줄 목록.
    files 는 보통 이미 _expand_registry_files 를 거쳤지만, 방어적으로 다시 한 번 컨테인먼트를 확인해
    벗어나는 항목은(raise 하지 않고) 조용히 건너뛴다 — 이 함수는 표시용 최선 노력 조회라 CliError 로
    list 전체를 막지 않는다."""
    if not component:
        return []
    pat1 = re.compile(r'data-area\s*=\s*["\']%s["\']' % re.escape(component))
    pat2 = re.compile(r'''(['"])%s\1''' % re.escape(component))
    hits = []
    for rel in files:
        try:
            _validate_rel(rel, "소스 위치 경로")
        except CliError:
            continue
        full = C.p(*rel.split("/"))
        if not os.path.isfile(full):
            continue
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if pat1.search(line) or pat2.search(line):
                hits.append("%s:%d" % (rel, i))
                if len(hits) >= limit:
                    return hits
    return hits


# ================================================================ path·suggest 다이제스트(7.3, 개정 L)
def _load_lib_index():
    """catalog/library/index.json(N1 생성물, 7.4) 읽기. 반환: None(파일 없음) · False(손상 — JSON 파싱
    실패이거나 templates 가 dict 가 아님) · dict(정상). list/show 가 각각 '미빌드'·'손상' 으로 안내한다
    (R4 LOW — 전엔 깨진 파일이 AttributeError 로 새 나갔다)."""
    path = C.p("catalog", "library", "index.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            index = json.load(f)
    except ValueError:  # json.JSONDecodeError 포함
        return False
    if not isinstance(index, dict) or not isinstance(index.get("templates"), dict):
        return False
    return index


def _path_item_label(item):
    """7.3 — 항목 라벨(area→template→selector:앞40자) + 대괄호((area 가 라벨이면 template)·variant·#idx)."""
    area = item.get("area")
    template = item.get("template")
    bracket = []
    if area:
        label = area
        if template:
            bracket.append(template)
    elif template:
        label = template
    else:
        label = "selector:%s" % (item.get("selector") or "")[:40]
    if item.get("variant"):
        bracket.append(item["variant"])
    if item.get("idx") is not None:
        bracket.append("#%s" % item["idx"])
    return "%s[%s]" % (label, " · ".join(bracket)) if bracket else label


def _path_digest_line(path):
    """7.3 — '- 경로: <항목> › <항목> › ...'. path 가 없거나 빈 배열이면 None."""
    if not path:
        return None
    return "- 경로: %s" % " › ".join(_path_item_label(it) for it in path)


def _kit_tail(lib_index, slug):
    """7.3 — '키트: 묶음/요소 `클래스`; ...' 또는 없음/미빌드/손상 안내.
    lib_index 는 _load_lib_index() 의 반환값 그대로(None=미빌드, False=손상, dict=정상) 받는다."""
    if lib_index is None:
        return "키트 정보 없음(라이브러리 미빌드)"
    if lib_index is False:
        return "키트 정보 없음(라이브러리 손상)"
    entry = lib_index.get("templates", {}).get(slug)
    kit = entry.get("kit") if isinstance(entry, dict) else None
    if not isinstance(kit, list) or not kit:
        return "키트에 없음"
    rows = ["%s/%s `%s`" % (k.get("group", ""), k.get("element", ""), k.get("kitClass", ""))
            for k in kit if isinstance(k, dict)]
    if not rows:
        return "키트에 없음"
    return "키트: %s" % "; ".join(rows)


def _suggest_digest_line(item, lib_index):
    """7.3 — '- 교체 제안: <현재 템플릿> → <제안 slug> (variant: X)? · <키트 꼬리>'. suggest 없으면 None.
    현재 템플릿 = item.template → 없으면 path 마지막 항목의 template → 없으면 '—'."""
    suggest = item.get("suggest")
    if not suggest:
        return None
    current = item.get("template")
    if not current:
        path = item.get("path") or []
        current = path[-1].get("template") if path else None
    current = current or "—"
    target = suggest.get("template")
    variant_part = " (variant: %s)" % suggest["variant"] if suggest.get("variant") else ""
    return "- 교체 제안: %s → %s%s · %s" % (current, target, variant_part, _kit_tail(lib_index, target))


# ================================================================ 크롭 샷(claim before · revise after · keys)
def _run_steps(page, steps):
    """registry states[].steps 실행. 없는 함수는 optional 이면 건너뛰고 아니면 False. eval 금지(함수명 조회만)."""
    for step in steps or []:
        call = step.get("call")
        args = step.get("args", [])
        optional = bool(step.get("optional"))
        try:
            exists = page.evaluate("(n) => typeof window[n] === 'function'", call)
        except Exception:
            exists = False
        if not exists:
            if optional:
                continue
            return False
        try:
            page.evaluate("(a) => window[a.name].apply(null, a.args)", {"name": call, "args": args})
        except Exception:
            if optional:
                continue
            return False
    return True


def _steps_for_item(stage_entry, item):
    states = stage_entry.get("states") or []
    state_id = item.get("state")
    for s in states:
        if s.get("id") == state_id:
            return s.get("steps", [])
    return states[0].get("steps", []) if states else []


def _query_box(page, selector):
    try:
        el = page.query_selector(selector)
    except Exception:
        return None
    if not el:
        return None
    try:
        return el.bounding_box()
    except Exception:
        return None


def _css_attr_escape(value):
    """CSS 속성 셀렉터의 "..." 문자열 리터럴 안에 그대로 넣을 수 있게 이스케이프(백슬래시 먼저, 그다음 인용부호)."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _crop_shot(page, item):
    box = None
    component = item.get("component")
    if component:
        sel = '[data-area="%s"]' % _css_attr_escape(component)
        if item.get("idx") is not None:
            sel += '[data-idx="%s"]' % _css_attr_escape(item["idx"])
        box = _query_box(page, sel)
    if box is None and item.get("selector"):
        box = _query_box(page, item["selector"])
    if box is None and item.get("bbox"):
        b = item["bbox"]
        box = {"x": b["x"], "y": b["y"], "width": b["w"], "height": b["h"]}
    if box is None:
        return None
    m = CROP_MARGIN
    clip = {"x": max(0.0, box["x"] - m), "y": max(0.0, box["y"] - m),
            "width": box["width"] + 2 * m, "height": box["height"] + 2 * m}
    if clip["width"] <= 0 or clip["height"] <= 0:
        return None
    try:
        return page.screenshot(clip=clip)
    except Exception:
        return None


def _shoot_for_item(browser, entry_abs, stage_entry, item):
    """실패하면 None(명령은 계속) — CONTRACT 4.4 크롭 샷 규칙."""
    try:
        page = browser.new_page(viewport=VIEWPORT)
    except Exception:
        return None
    try:
        page.goto(pathlib.Path(entry_abs).resolve().as_uri())
        page.wait_for_load_state("networkidle")
        if not _run_steps(page, _steps_for_item(stage_entry, item)):
            return None
        return _crop_shot(page, item)
    except Exception:
        return None
    finally:
        try:
            page.close()
        except Exception:
            pass


# ================================================================ diff
def _read_variant(path):
    """(존재 여부, 바이너리 여부, 내용[str|bytes|None])."""
    if not os.path.isfile(path):
        return False, False, None
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return True, False, raw.decode("utf-8")
    except UnicodeDecodeError:
        return True, True, raw


def _diff_for_file(rel, snap_root, live_root):
    """unified diff 블록(경로 머리 a/<rel> b/<rel>) 또는 변경 없으면 None.
    rel 은 보통 호출 전에 이미 안전성을 검증받지만(_expand_registry_files·_walk_rel), 여기서도
    방어적으로 다시 확인한다 — diff 는 claim 복사·grep 과 함께 컨테인먼트가 필요한 세 지점 중 하나다."""
    _validate_rel(rel, "diff 대상 경로")
    snap_path = os.path.join(snap_root, *rel.split("/"))
    live_path = os.path.join(live_root, *rel.split("/"))
    s_exists, s_bin, s_content = _read_variant(snap_path)
    l_exists, l_bin, l_content = _read_variant(live_path)
    if not s_exists and not l_exists:
        return None
    a, b = "a/" + rel, "b/" + rel
    if s_bin or l_bin:
        if s_exists and l_exists and s_content == l_content:
            return None
        return "--- %s\n+++ %s\nBinary files differ\n" % (a, b)
    s_text = s_content if s_exists else ""
    l_text = l_content if l_exists else ""
    if s_text == l_text:
        return None
    lines = list(difflib.unified_diff(s_text.splitlines(keepends=True), l_text.splitlines(keepends=True),
                                       fromfile=a, tofile=b, lineterm="\n"))
    return "".join(lines) if lines else None


# ================================================================ list · show
def _attachments_disp(atts):
    """개정 F(9.5) — 첨부 경로를 클라이언트 저장소 루트 기준(`ui-audit/feedback/attachments/…`)으로, Read 로 바로 열게.
    이름이 있으면 괄호, 파일이 이 디스크에 없으면 `[파일 없음]`."""
    out = []
    for a in atts:
        abs_path = C.p(*a["path"].split("/"))
        disp = os.path.relpath(abs_path, os.path.dirname(C.ROOT)).replace(os.sep, "/")
        if a.get("name"):
            disp += " (%s)" % a["name"]
        if not os.path.isfile(abs_path):
            disp += " [파일 없음]"
        out.append(disp)
    return ", ".join(out)


def cmd_list(screen, statuses, as_json):
    registry = FC.load_registry()
    state = FC.fold(FC.read_log(), registry)
    lib_index = _load_lib_index()  # 개정 L(7.3) — catalog/library/index.json, 없으면 None
    items = [it for it in state["items"].values()
             if (screen is None or it["screen"] == screen) and it["status"] in statuses]
    items.sort(key=lambda it: it["id"])
    if as_json:
        print(json.dumps(items, ensure_ascii=False, indent=1, sort_keys=True))
        return 0
    lines = ["# 피드백 목록 (screen=%s status=%s)" % (screen or "(전체)", ",".join(statuses)), ""]
    if not items:
        lines.append("(없음)")
    for it in items:
        # 개정 V: 등록부 조회는 (screen, stage, version) 기준 — 그 피드백이 달린 시안을 그대로 찾는다.
        stage_entry = _stage_entry(registry, it["screen"], it["stage"], version=it.get("version"), required=False)
        entry = stage_entry["entry"] if stage_entry else "(등록부에 없음)"
        try:
            files = _expand_registry_files(stage_entry.get("files", [])) if stage_entry else []
        except CliError:
            files = []  # 이 명령은 읽기 전용 표시라 등록부 files 가 불안전해도 전체를 막지 않는다
        src = _grep_component(files, it["component"])
        extra = []
        if it.get("idx") is not None:
            extra.append("idx=%s" % it["idx"])
        if it.get("template"):
            extra.append("template=%s" % it["template"])
        comp_disp = (it["component"] or "(키 없음)") + (" (%s)" % ", ".join(extra) if extra else "")
        version_disp = it["version"]
        if stage_entry and stage_entry.get("label"):
            version_disp += " — %s" % stage_entry["label"]  # 시안 라벨(개정 V)
        lines.append("## %s — %s · %s" % (it["id"], it["status"], it["kind"]))
        lines.append("- 화면/단계/시안: %s / %s / %s" % (it["screen"], it["stage"], version_disp))
        if it.get("state"):
            lines.append("- state: %s" % it["state"])
        lines.append("- 컴포넌트: %s" % comp_disp)
        if it.get("selector"):
            lines.append("- selector: %s" % it["selector"])
        lines.append("- 원문: %s" % it["text"])
        opener = (it.get("history") or [{}])[0].get("author")  # 개정 A
        if opener:
            lines.append("- 작성: %s" % opener)
        open_atts = (it.get("history") or [{}])[0].get("attachments")  # 개정 F(9.5)
        if open_atts:
            lines.append("- 첨부: %s" % _attachments_disp(open_atts))
        lines.append("- 산출물: %s" % entry)
        lines.append("- 소스 위치: %s" % (", ".join(src) if src else "(없음)"))
        comments = [h for h in it["history"] if h["type"] == "comment"]
        if comments:
            lines.append("- 코멘트:")
            for c in comments:
                who = c["by"] + (":" + c["author"] if c.get("author") else "")  # 개정 A
                att = " (첨부: %s)" % _attachments_disp(c["attachments"]) if c.get("attachments") else ""
                lines.append("  - [%s] %s%s" % (who, c["text"], att))
        if it.get("revisions"):
            lines.append("- 이전 리비전:")
            for rev_id in it["revisions"]:
                rev = state["revisions"].get(rev_id)
                lines.append("  - %s: %s" % (rev_id, rev.get("summary", "") if rev else ""))
        path_line = _path_digest_line(it.get("path"))  # 개정 L(7.3)
        if path_line:
            lines.append(path_line)
        suggest_line = _suggest_digest_line(it, lib_index)
        if suggest_line:
            lines.append(suggest_line)
        lines.append("")
    print("\n".join(lines))
    return 0


def cmd_show(fb_id):
    registry = FC.load_registry()
    state = FC.fold(FC.read_log(), registry)
    it = state["items"].get(fb_id)
    if it is None:
        raise CliError("모르는 id: %s" % fb_id)
    print("# %s" % fb_id)
    for k in ("screen", "stage", "version", "kind", "status", "claim", "component", "idx",
              "template", "selector", "bbox", "state", "openedAt", "updatedAt", "revisions", "text"):
        print("- %s: %s" % (k, it.get(k)))
    path_line = _path_digest_line(it.get("path"))  # 개정 L(7.3) — list 와 같은 줄
    if path_line:
        print(path_line)
    suggest_line = _suggest_digest_line(it, _load_lib_index())
    if suggest_line:
        print(suggest_line)
    print("\n## 이력")
    for h in it["history"]:
        rest = {k: v for k, v in h.items() if k not in ("type", "by", "at")}
        print("- [%s] by=%s at=%s %s" % (h["type"], h["by"], h["at"], json.dumps(rest, ensure_ascii=False)))
    return 0


# ================================================================ claim
def cmd_claim(ids):
    registry = FC.load_registry()
    state = FC.fold(FC.read_log(), registry)
    items = _lookup_items(state, ids)
    screens = {it["screen"] for it in items}
    stages = {it["stage"] for it in items}
    versions = {it["version"] for it in items}  # 개정 V — 시안도 같아야 한다
    if len(screens) > 1 or len(stages) > 1 or len(versions) > 1:
        raise CliError("서로 다른 화면/단계/시안의 id 를 섞을 수 없음: screens=%s stages=%s versions=%s" %
                        (screens, stages, versions))
    bad = [it["id"] for it in items if it["status"] not in ("open", "reopened")]
    if bad:
        raise CliError("claim 불가(open/reopened 아님): %s" % ", ".join(bad))
    screen, stage, version = items[0]["screen"], items[0]["stage"], items[0]["version"]
    # (screen, stage, version) 조회 — 그 시안이 등록부에 없으면 _stage_entry 가 CliError 로 거부한다(개정 V).
    stage_entry = _stage_entry(registry, screen, stage, version=version)
    files = _expand_registry_files(stage_entry.get("files", []))
    entry_abs = _entry_abs(stage_entry)

    tmp_dir = tempfile.mkdtemp(prefix="uia-claim-")
    try:
        for rel in files:
            src = C.p(*rel.split("/"))
            if not os.path.isfile(src):
                continue
            dst = os.path.join(tmp_dir, "files", *rel.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        before_dir = os.path.join(tmp_dir, "before")
        os.makedirs(before_dir, exist_ok=True)

        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for it in items:
                    png = _shoot_for_item(browser, entry_abs, stage_entry, it)
                    if png:
                        with open(os.path.join(before_dir, "%s.png" % it["id"]), "wb") as f:
                            f.write(png)
            finally:
                browser.close()

        with FC.lock():
            events2 = FC.read_log()
            cl_id = FC.next_id("cl", events2)
            final_dir = C.p("feedback", "snap", cl_id)
            os.makedirs(os.path.dirname(final_dir), exist_ok=True)
            _clear_orphan(final_dir)  # 로그에 없는 고아 폴더가 선재하면 지운다(안으로 중첩되는 move 방지)
            shutil.move(tmp_dir, final_dir)
            try:
                ev = FC.append({"type": "claim", "ids": ids}, "claude")
            except BaseException:  # noqa: BLE001 — 어떤 예외든 옮긴 폴더를 지우고 재발생
                shutil.rmtree(final_dir, ignore_errors=True)
                raise
    finally:
        if os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
    print("claim %s: %s" % (ev["claim"], ", ".join(ids)))
    return 0


# ================================================================ release
def cmd_release(ids, reason):
    registry = FC.load_registry()
    state = FC.fold(FC.read_log(), registry)
    items = _lookup_items(state, ids)
    claim_id = _common_claim(items, ids)
    FC.append({"type": "release", "ids": ids, "claim": claim_id, "text": reason}, "claude")
    print("release %s: %s" % (claim_id, ", ".join(ids)))
    return 0


# ================================================================ revise
def cmd_revise(ids, summary, new_version, no_shots):
    registry = FC.load_registry()
    state = FC.fold(FC.read_log(), registry)
    items = _lookup_items(state, ids)
    claim_id = _common_claim(items, ids)
    bad = [it["id"] for it in items if it["status"] != "claimed"]
    if bad:
        raise CliError("claimed 상태가 아님: %s" % ", ".join(bad))
    # 같은 claim 의 ids 는 claim 시점에 이미 같은 (screen, stage, version) 이었음이 보장된다(cmd_claim).
    screen, stage, version = items[0]["screen"], items[0]["stage"], items[0]["version"]
    stage_entry = _stage_entry(registry, screen, stage, version=version)

    snap_files_dir = C.p("feedback", "snap", claim_id, "files")
    current = _expand_registry_files(stage_entry.get("files", []))
    snapped = _walk_rel(snap_files_dir)
    all_rel = sorted(set(current) | set(snapped))

    blocks, changed = [], []
    for rel in all_rel:
        block = _diff_for_file(rel, snap_files_dir, C.ROOT)
        if block:
            blocks.append(block)
            changed.append(rel)
    if not changed:
        raise CliError("바뀐 파일이 없음 — revise 거부")
    diff_text = "".join(blocks)

    after_dir = tempfile.mkdtemp(prefix="uia-revise-")
    try:
        if not no_shots:
            entry_abs = _entry_abs(stage_entry)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    for it in items:
                        png = _shoot_for_item(browser, entry_abs, stage_entry, it)
                        if png:
                            with open(os.path.join(after_dir, "after-%s.png" % it["id"]), "wb") as f:
                                f.write(png)
                finally:
                    browser.close()

        with FC.lock():
            events2 = FC.read_log()
            rev_id = FC.next_id("rev", events2)
            final_diff = C.p("feedback", "revisions", "%s.diff" % rev_id)
            final_after_dir = C.p("feedback", "revisions", rev_id)
            os.makedirs(os.path.dirname(final_diff), exist_ok=True)
            _clear_orphan(final_diff)  # 로그에 없는 고아 .diff 가 선재하면 지운다
            with open(final_diff, "w", encoding="utf-8", newline="\n") as f:
                f.write(diff_text)
            moved_after = False
            if os.path.isdir(after_dir) and os.listdir(after_dir):
                _clear_orphan(final_after_dir)  # 로그에 없는 고아 폴더가 선재하면 지운다(중첩 move 방지)
                shutil.move(after_dir, final_after_dir)
                moved_after = True

            shots = []
            for it in items:
                before_rel = "feedback/snap/%s/before/%s.png" % (claim_id, it["id"])
                before = before_rel if os.path.isfile(C.p(*before_rel.split("/"))) else None
                after_rel = "feedback/revisions/%s/after-%s.png" % (rev_id, it["id"])
                after = after_rel if os.path.isfile(C.p(*after_rel.split("/"))) else None
                shots.append({"id": it["id"], "before": before, "after": after})

            event = {"type": "revision", "ids": ids, "claim": claim_id, "files": changed,
                      "summary": summary, "shots": shots}
            if new_version:
                event["newVersion"] = new_version
            try:
                ev = FC.append(event, "claude")
            except BaseException:  # noqa: BLE001 — 어떤 예외든 쓰거나 옮긴 것을 지우고 재발생
                try:
                    os.remove(final_diff)
                except OSError:
                    pass
                if moved_after:
                    shutil.rmtree(final_after_dir, ignore_errors=True)
                raise
    finally:
        shutil.rmtree(after_dir, ignore_errors=True)
    print("revision %s (claim %s): %s — files=%s" % (ev["rev"], claim_id, ", ".join(ids), ", ".join(changed)))
    return 0


# ================================================================ comment
def cmd_comment(fb_id, text):
    FC.append({"type": "comment", "id": fb_id, "text": text}, "claude")
    print("comment 기록: %s" % fb_id)
    return 0


# ================================================================ keys
KEYS_DEF = ("키 없는 큰 요소 정의: #canvas(없으면 body) 안에서 — 자신에게 data-area 가 없고 · "
            "가장 가까운 data-area 조상이 없거나 그 조상 면적이 캔버스의 40% 이상이며 · "
            "자기 면적이 캔버스의 2% 이상이고 · 자기 안에 data-area 자손이 없는 요소. "
            "면적 내림차순, 같은 bbox 중복 제거.")

KEYS_JS = r"""
(top) => {
  const canvas = document.querySelector('#canvas') || document.body;
  const cRect = canvas.getBoundingClientRect();
  const cArea = cRect.width * cRect.height;
  const keyCounts = {};
  for (const el of document.querySelectorAll('[data-area]')) {
    const k = el.getAttribute('data-area');
    if (!keyCounts[k]) keyCounts[k] = {count: 0, withIdx: 0};
    keyCounts[k].count++;
    if (el.hasAttribute('data-idx')) keyCounts[k].withIdx++;
  }
  const bigNokey = [];
  if (cArea > 0) {
    const seen = new Set();
    for (const el of canvas.querySelectorAll('*')) {
      if (el.hasAttribute('data-area')) continue;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      const area = r.width * r.height;
      if (area < cArea * 0.02) continue;
      const anc = el.closest('[data-area]');
      if (anc) {
        const ar = anc.getBoundingClientRect();
        if (ar.width * ar.height < cArea * 0.40) continue;
      }
      if (el.querySelector('[data-area]')) continue;
      const key = Math.round(r.x) + ',' + Math.round(r.y) + ',' + Math.round(r.width) + ',' + Math.round(r.height);
      if (seen.has(key)) continue;
      seen.add(key);
      bigNokey.push({tag: el.tagName.toLowerCase(), id: el.id || null,
                      cls: (el.className || '').toString().slice(0, 60),
                      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
                      area: Math.round(area), pct: +(area / cArea * 100).toFixed(1)});
    }
  }
  bigNokey.sort((a, b) => b.area - a.area);
  return {keys: keyCounts, nokey: bigNokey.slice(0, top)};
}
"""


def _keys_for_state(browser, entry_abs, steps, top):
    try:
        page = browser.new_page(viewport=VIEWPORT)
    except Exception:
        return None
    try:
        page.goto(pathlib.Path(entry_abs).resolve().as_uri())
        page.wait_for_load_state("networkidle")
        if not _run_steps(page, steps):
            return None
        return page.evaluate(KEYS_JS, top)
    except Exception:
        return None
    finally:
        try:
            page.close()
        except Exception:
            pass


def cmd_keys(screen, stage_filter, version_filter, top):
    """기본(필터 없음) = 등록된 모든 (stage, version) — 같은 stage 의 시안 전부(개정 V)."""
    registry = FC.load_registry()
    scr = registry.get("screens", {}).get(screen)
    if scr is None:
        raise CliError("없는 screen: %s" % screen)
    stages = [s for s in scr.get("stages", []) if stage_filter is None or s.get("stage") == stage_filter]
    if not stages:
        raise CliError("%s 화면에 stage 없음(filter=%s)" % (screen, stage_filter))
    if version_filter is not None:
        stages = [s for s in stages if s.get("version") == version_filter]
        if not stages:
            raise CliError("%s 화면에 없는 (stage, version): stage=%s version=%s" %
                            (screen, stage_filter, version_filter))

    lines = ["# %s 키 현황" % screen, "", KEYS_DEF, ""]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for stage_entry in stages:
                entry_abs = _entry_abs(stage_entry)
                states = stage_entry.get("states") or [{"id": "(default)", "label": "기본", "steps": []}]
                lines.append("## stage=%s (%s)" % (stage_entry["stage"], stage_entry.get("version")))
                for s in states:
                    result = _keys_for_state(browser, entry_abs, s.get("steps", []), top)
                    lines.append("### state=%s — %s" % (s["id"], s.get("label", "")))
                    if result is None:
                        lines.append("- (상태 진입 실패 — 함수 없음 또는 오류)")
                        continue
                    lines.append("- data-area 키 %d종" % len(result["keys"]))
                    for k in sorted(result["keys"]):
                        c = result["keys"][k]
                        lines.append("  - %s: %d개 (idx 있음 %d)" % (k, c["count"], c["withIdx"]))
                    lines.append("- 키 없는 큰 요소 상위 %d" % top)
                    if not result["nokey"]:
                        lines.append("  - (없음)")
                    for n in result["nokey"]:
                        cls = (" ." + n["cls"].split()[0]) if n["cls"] else ""
                        idd = ("#" + n["id"]) if n["id"] else ""
                        lines.append("  - <%s>%s%s %dx%d @ (%d,%d) — 캔버스의 %.1f%%" %
                                      (n["tag"], idd, cls, n["w"], n["h"], n["x"], n["y"], n["pct"]))
                lines.append("")
        finally:
            browser.close()
    print("\n".join(lines))
    return 0


# ================================================================ build
def cmd_build():
    FC.write_state_js()
    print("state.js 갱신 완료: %s" % C.p("feedback", "state.js"))
    return 0


# ================================================================ 자체 테스트
def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _capture(fn):
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue()


def check(results, name, fn):
    try:
        detail = fn()
        results.append((name, True, detail or ""))
    except Exception as e:  # noqa: BLE001 — 항목별 FAIL 로 모으고 계속 진행
        results.append((name, False, "%s: %s" % (type(e).__name__, e)))
        traceback.print_exc()


WIRE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>wire</title>
<style>
  body{margin:0;padding:0;}
  #canvas{position:relative;width:1280px;height:720px;background:#eee;}
  .header{position:absolute;left:0;top:0;width:1280px;height:80px;background:#ccc;}
  .deco{position:absolute;left:0;top:100px;width:1280px;height:400px;background:#ddd;}
  .row{position:absolute;left:20px;width:400px;height:40px;background:#fff;border:1px solid #999;}
</style></head>
<body>
<div id="canvas">
  <div class="header" data-area="header">헤더</div>
  <div class="deco"></div>
  <div class="row" style="top:520px" data-area="feed-row" data-idx="0">row0 <span id="markA">A</span></div>
  <div class="row" style="top:565px" data-area="feed-row" data-idx="1">row1</div>
</div>
<script>
function loadState(id){
  document.getElementById("markA").textContent = "loaded:" + id;
}
</script>
</body></html>
"""

MOCKUP_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>mockup</title>
<link rel="stylesheet" href="mockup.css">
</head>
<body>
<div id="canvas">
  <div class="header" data-area="header">헤더</div>
  <div class="row" data-area="feed-row" data-idx="0">row0 <span id="markB">B</span></div>
</div>
<script>
function loadState(id){
  document.getElementById("markB").textContent = "loaded:" + id;
}
</script>
</body></html>
"""

MOCKUP_CSS = """#canvas{position:relative;width:1280px;height:720px;background:#f4f4f4;}
.header{position:absolute;left:0;top:0;width:1280px;height:80px;background:#ccd;}
.row{position:absolute;left:20px;top:120px;width:400px;height:40px;background:#fff;border:1px solid #999;}
"""

TEST_REGISTRY = {
    "version": 1,
    "screens": {
        "TestScreen": {
            "app": "Test", "label": "테스트",
            "stages": [
                {"stage": "wire", "version": "w1", "label": "와이어", "status": "wip",
                 "entry": "design/testscreen/wire.html", "files": ["design/testscreen/wire.html"],
                 "states": [{"id": "s1", "label": "상태1",
                             "steps": [{"call": "loadState", "args": ["s1"]},
                                       {"call": "stopTimers", "args": [], "optional": True}]}]},
                {"stage": "mockup", "version": "m1", "label": "목업", "status": "wip",
                 "entry": "design/testscreen/mockup.html",
                 "files": ["design/testscreen/mockup.html", "design/testscreen/mockup.css"],
                 "states": [{"id": "team", "label": "팀",
                             "steps": [{"call": "loadState", "args": ["team"]},
                                       {"call": "stopTimers", "args": [], "optional": True}]}]},
                # 개정 V: 같은 stage("mockup")의 두 번째 시안 — m1 이 기본(첫 항목), m2 는 files 범위가
                # 전혀 다르다(wire.html 뿐) — claim 의 시안별 files 범위 분리를 확인하는 데 쓴다.
                {"stage": "mockup", "version": "m2", "label": "목업 2안", "status": "wip",
                 "entry": "design/testscreen/wire.html", "files": ["design/testscreen/wire.html"],
                 "states": [{"id": "s1", "label": "상태1",
                             "steps": [{"call": "loadState", "args": ["s1"]}]}]}
            ]
        },
        "TestScreen2": {
            "app": "Test", "label": "테스트2",
            "stages": [
                {"stage": "wire", "version": "w1", "label": "와이어", "status": "wip",
                 "entry": "design/testscreen/wire.html", "files": ["design/testscreen/wire.html"],
                 "states": [{"id": "s1", "label": "상태1",
                             "steps": [{"call": "loadState", "args": ["s1"]}]}]}
            ]
        },
        # feedback_core.py 의 --worker-open(동시성 자체 테스트용 내부 헬퍼, 수정 금지 대상)이
        # "ShopView"/"mockup"/"feed-row" 를 하드코딩해 둬서, 이 임시 루트에서도 그 open 이
        # 검증을 통과하도록 더미 화면을 하나 맞춰 둔다(9번 동시성 검사에서만 쓰고, claim/revise 는
        # 걸지 않는다).
        "ShopView": {
            "app": "Test", "label": "더미(동시성 테스트용)",
            "stages": [
                {"stage": "mockup", "version": "x1", "label": "더미", "status": "wip",
                 "entry": "design/testscreen/mockup.html", "files": ["design/testscreen/mockup.html"],
                 "states": []}
            ]
        },
        # R1 리뷰 10번: files 에 ui-audit 루트 밖(../outside.txt)을 가리키는 항목이 있으면 claim 이
        # 거부돼야 한다(이벤트 없이, 루트 밖에 아무것도 만들지 않고).
        "TestScreenEscape": {
            "app": "Test", "label": "경로 탈출 테스트",
            "stages": [
                {"stage": "wire", "version": "e1", "label": "탈출", "status": "wip",
                 "entry": "design/testscreen/wire.html",
                 "files": ["design/testscreen/wire.html", "../outside.txt"],
                 "states": [{"id": "s1", "label": "상태1", "steps": [{"call": "loadState", "args": ["s1"]}]}]}
            ]
        },
        # R1 리뷰 11번: claim 목적지(snap/<cl>)가 이미 있는 고아 폴더일 때도 안으로 중첩되지 않고
        # 정상 구조로 대체돼야 한다.
        "TestScreenOrphan": {
            "app": "Test", "label": "고아 폴더 테스트",
            "stages": [
                {"stage": "wire", "version": "o1", "label": "고아", "status": "wip",
                 "entry": "design/testscreen/wire.html", "files": ["design/testscreen/wire.html"],
                 "states": [{"id": "s1", "label": "상태1", "steps": [{"call": "loadState", "args": ["s1"]}]}]}
            ]
        }
    }
}


def selftest():
    results = []
    root = C.selftest_dir("feedback-cli")
    _write(os.path.join(root, "design", "testscreen", "wire.html"), WIRE_HTML)
    _write(os.path.join(root, "design", "testscreen", "mockup.html"), MOCKUP_HTML)
    _write(os.path.join(root, "design", "testscreen", "mockup.css"), MOCKUP_CSS)
    _write(os.path.join(root, "design", "registry.json"), json.dumps(TEST_REGISTRY, ensure_ascii=False, indent=1))
    os.makedirs(os.path.join(root, "feedback"), exist_ok=True)
    # 개정 L(7.3) — suggest.template 실존 검사(코어)와 list/show 의 키트 줄이 읽는 두 인덱스.
    tmpl_index = C.load_json(C.p("feedback", "fixtures", "sample-template-index.json"))
    _write(os.path.join(root, "data", "template-index.json"), json.dumps(tmpl_index, ensure_ascii=False, indent=1))
    lib_index = C.load_json(C.p("feedback", "fixtures", "sample-lib-index.json"))
    _write(os.path.join(root, "catalog", "library", "index.json"),
           json.dumps(lib_index, ensure_ascii=False, indent=1))

    with FC._use_root(root):  # noqa: SLF001 — feedback_core 의 동일 루트 교체 도우미를 재사용
        fb1 = FC.append({"type": "open", "screen": "TestScreen", "stage": "mockup", "kind": "visual",
                          "text": "행 높이가 낮다", "component": "feed-row", "idx": "0", "state": "team"}, "user")["id"]
        fb2 = FC.append({"type": "open", "screen": "TestScreen", "stage": "mockup", "kind": "copy",
                          "text": "헤더 문구 수정", "component": "header", "state": "team"}, "user")["id"]
        fb3 = FC.append({"type": "open", "screen": "TestScreen2", "stage": "wire", "kind": "bug",
                          "text": "다른 화면", "component": "feed-row", "idx": "0", "state": "s1"}, "user")["id"]
        fb4 = FC.append({"type": "open", "screen": "TestScreen", "stage": "wire", "kind": "bug",
                          "text": "동시성 테스트용", "component": "header", "state": "s1"}, "user")["id"]
        fb5 = FC.append({"type": "open", "screen": "TestScreen", "stage": "mockup", "kind": "other",
                          "text": "release 테스트용", "component": "header", "state": "team"}, "user")["id"]
        fb_escape = FC.append({"type": "open", "screen": "TestScreenEscape", "stage": "wire", "kind": "bug",
                                "text": "탈출 테스트", "component": "feed-row", "idx": "0", "state": "s1"},
                               "user")["id"]
        fb_orphan = FC.append({"type": "open", "screen": "TestScreenOrphan", "stage": "wire", "kind": "bug",
                                "text": "고아 폴더 테스트", "component": "feed-row", "idx": "1", "state": "s1"},
                               "user")["id"]
        # 개정 V: m2 시안(fb1/fb2/fb5 는 version 생략 → 등록부 기본 시안 m1 로 채워진다)
        fb_m2 = FC.append({"type": "open", "screen": "TestScreen", "stage": "mockup", "version": "m2",
                            "kind": "bug", "text": "m2 시안 테스트", "component": "feed-row", "idx": "0",
                            "state": "s1"}, "user")["id"]
        # 개정 L(7.1·7.3): path·suggest 가 있는 open — list/show 다이제스트 줄 확인용.
        fb_tpl = FC.append({"type": "open", "screen": "TestScreen", "stage": "mockup", "kind": "template",
                             "text": "교체 제안 테스트", "component": "feed-row", "state": "team",
                             "template": "thumbnailcharacterunit",
                             "path": [{"area": "feed-row", "template": "friendlistunit",
                                       "variant": "shop-list"},
                                      {"template": "thumbnailcharacterunit",
                                       "variant": "ShopItemSlotUnit"}],
                             "suggest": {"template": "thumbnailemptyunit"}}, "user")["id"]

        state_holder = {}

        def t1():
            out = _capture(lambda: main(["list", "--screen", "TestScreen"]))
            assert fb1 in out and "행 높이가 낮다" in out, out[:300]
            assert "feed-row" in out, out[:300]
            assert "design/testscreen/mockup.html" in out, out[:300]
            assert re.search(r"design/testscreen/mockup\.html:\d+", out), out
            out2 = _capture(lambda: main(["list", "--screen", "TestScreen", "--status", "closed"]))
            assert fb1 not in out2, out2
            return "원문·컴포넌트 키·entry 경로·소스 위치(경로:줄) 확인, --status 필터로 0건"
        check(results, "1 list", t1)

        def t2():
            before = len(FC.read_log())
            rc = main(["claim", fb1, fb2])
            assert rc in (0, None), rc
            state = FC.fold(FC.read_log(), FC.load_registry())
            cl = state["items"][fb1]["claim"]
            assert cl and state["items"][fb2]["claim"] == cl, state["items"]
            state_holder["claim"] = cl
            b1 = C.p("feedback", "snap", cl, "before", "%s.png" % fb1)
            b2 = C.p("feedback", "snap", cl, "before", "%s.png" % fb2)
            assert os.path.isfile(b1) and os.path.getsize(b1) > 0, b1
            assert os.path.isfile(b2) and os.path.getsize(b2) > 0, b2
            assert os.path.isfile(C.p("feedback", "snap", cl, "files", "design", "testscreen", "mockup.html"))
            assert os.path.isfile(C.p("feedback", "snap", cl, "files", "design", "testscreen", "mockup.css"))
            rc2 = main(["claim", fb3, fb4])  # 서로 다른 화면(TestScreen2/TestScreen), 둘 다 아직 open
            assert rc2 not in (0, None), "다른 화면 id 섞기가 거부되지 않음"
            assert len(FC.read_log()) == before + 1, "거부 시도가 로그를 늘림"
            return "claim=%s, before 샷 2개 + files 스냅샷 확인, 다른 화면 섞기 거부(로그 불변)" % cl
        check(results, "2 claim", t2)

        def t3():
            if "claim" not in state_holder:
                raise RuntimeError("2단계(claim)가 실패해 진행 불가")
            before = len(FC.read_log())
            rc = main(["revise", fb1, fb2, "--summary", "변경 없음"])
            assert rc not in (0, None), "변경 없이 revise 가 성공함"
            assert len(FC.read_log()) == before, "거부됐는데 로그 줄 수가 바뀜"
            return "변경 없이 revise → 거부, 로그 불변"
        check(results, "3 revise(변경없음) 거부", t3)

        def t4():
            css_path = C.p("design", "testscreen", "mockup.css")
            with open(css_path, "a", encoding="utf-8") as f:
                f.write("\n.row{background:#ffef9c;} /* bumped-marker */\n")
            rc = main(["revise", fb1, fb2, "--summary", "row 배경색 변경", "--new-version", "m2"])
            assert rc in (0, None), rc
            state = FC.fold(FC.read_log(), FC.load_registry())
            r1, r2 = state["items"][fb1]["revisions"], state["items"][fb2]["revisions"]
            assert r1 and r1 == r2, (r1, r2)
            rev_id = r1[-1]
            diff_text = open(C.p("feedback", "revisions", "%s.diff" % rev_id), encoding="utf-8").read()
            assert "bumped-marker" in diff_text, diff_text
            assert "a/design/testscreen/mockup.css" in diff_text and "b/design/testscreen/mockup.css" in diff_text
            a1 = C.p("feedback", "revisions", rev_id, "after-%s.png" % fb1)
            a2 = C.p("feedback", "revisions", rev_id, "after-%s.png" % fb2)
            assert os.path.isfile(a1) and os.path.getsize(a1) > 0, a1
            assert os.path.isfile(a2) and os.path.getsize(a2) > 0, a2
            assert state["items"][fb1]["status"] == "fixed" and state["items"][fb2]["status"] == "fixed"
            return "rev=%s, diff에 변경 줄 포함, after 샷 2개, 두 항목 모두 fixed + 같은 rev 공유" % rev_id
        check(results, "4-5 revise(수정 반영·묶음 공유)", t4)

        def t6():
            rc = main(["claim", fb5])
            assert rc in (0, None), rc
            st = FC.fold(FC.read_log(), FC.load_registry())
            assert st["items"][fb5]["status"] == "claimed"
            rc2 = main(["release", fb5, "--reason", "보류"])
            assert rc2 in (0, None), rc2
            st2 = FC.fold(FC.read_log(), FC.load_registry())
            assert st2["items"][fb5]["status"] == "open" and st2["items"][fb5]["claim"] is None, st2["items"][fb5]
            rc3 = main(["comment", fb5, "확인 중"])
            assert rc3 in (0, None), rc3
            st3 = FC.fold(FC.read_log(), FC.load_registry())
            comments = [h for h in st3["items"][fb5]["history"] if h["type"] == "comment"]
            assert comments and comments[-1]["text"] == "확인 중" and comments[-1]["by"] == "claude", comments
            return "claim → release(open 복귀) → comment 기록"
        check(results, "6 release·comment", t6)

        def t7():
            out = _capture(lambda: main(["keys", "TestScreen"]))
            assert "feed-row" in out and "header" in out, out[:500]
            assert "deco" in out, out
            return "상태별 data-area 키 목록 + 키 없는 큰 요소(deco) 보고"
        check(results, "7 keys", t7)

        def t8():
            path = C.p("feedback", "state.js")
            if os.path.exists(path):
                os.remove(path)
            rc = main(["build"])
            assert rc in (0, None), rc
            assert os.path.isfile(path)
            text = open(path, encoding="utf-8").read()
            assert text.startswith("window.UIA_FEEDBACK = ")
            return "state.js 생성 확인"
        check(results, "8 build", t8)

        def t9():
            before = len(FC.read_log())
            result = {}

            def worker():
                env = dict(os.environ, UIAUDIT_ROOT=root, PYTHONIOENCODING="utf-8")
                try:
                    r = subprocess.run(
                        [sys.executable, os.path.join(C.SCRIPTS, "feedback_core.py"), "--worker-open", "1"],
                        env=env, capture_output=True, text=True, encoding="utf-8", timeout=15)
                    result["rc"] = r.returncode
                    result["out"] = (r.stdout or "") + (r.stderr or "")
                except Exception as e:  # noqa: BLE001
                    result["exc"] = str(e)

            th = threading.Thread(target=worker)
            th.start()
            rc = main(["claim", fb4])
            th.join(timeout=10)
            assert not th.is_alive(), "동시 append 가 10초 내 끝나지 않음(워커가 아직 살아있음)"
            assert "exc" not in result, result
            assert result.get("rc") == 0, result.get("out")
            assert rc in (0, None), rc
            after = len(FC.read_log())
            assert after == before + 2, "claim 1 + worker open 1 = 2줄 기대, 실제 %d" % (after - before)
            return "claim 진행 중(샷 촬영 동안) 다른 프로세스의 append 가 10초 내 성공 — 락이 짧게 유지됨"
        check(results, "9 동시 append(락 짧음)", t9)

        def t10():
            outside_path = os.path.normpath(os.path.join(root, "..", "outside.txt"))
            assert not os.path.exists(outside_path), "사전 조건 깨짐: outside.txt 가 이미 존재함"
            before = len(FC.read_log())
            rc = main(["claim", fb_escape])
            assert rc not in (0, None), "경로 탈출(../outside.txt) files 를 가진 claim 이 거부되지 않음"
            assert len(FC.read_log()) == before, "거부됐는데 로그가 늘어남"
            assert not os.path.exists(outside_path), "루트 밖에 파일이 생성됨: %s" % outside_path
            return "files=[.., ../outside.txt] → claim 거부(이벤트 없음), 루트 밖 파일 생성 0"
        check(results, "10 경로 탈출(files) 거부", t10)

        def t11():
            next_cl = FC.next_id("cl", FC.read_log())
            orphan_dir = C.p("feedback", "snap", next_cl)
            os.makedirs(os.path.join(orphan_dir, "leftover"), exist_ok=True)
            _write(os.path.join(orphan_dir, "leftover", "junk.txt"), "stale")
            rc = main(["claim", fb_orphan])
            assert rc in (0, None), rc
            st = FC.fold(FC.read_log(), FC.load_registry())
            cl = st["items"][fb_orphan]["claim"]
            assert cl == next_cl, (cl, next_cl)
            files_dir = C.p("feedback", "snap", cl, "files")
            assert os.path.isdir(files_dir), files_dir
            assert os.path.isfile(os.path.join(files_dir, "design", "testscreen", "wire.html"))
            # 중첩됐다면 snap/<cl>/<cl>/... 혹은 snap/<cl>/leftover/... 가 남는다 — 둘 다 없어야 한다
            assert not os.path.isdir(os.path.join(C.p("feedback", "snap", cl), cl)), "목적지 안으로 중첩됨"
            assert not os.path.isdir(os.path.join(C.p("feedback", "snap", cl), "leftover")), \
                "고아 폴더의 잔존물이 남음(중첩 move)"
            return "고아 폴더(snap/%s) 선재 → claim 이 정상 files/ 구조로 대체(중첩 없음)" % cl
        check(results, "11 claim 목적지 고아 폴더 선재 → 중첩 없이 대체", t11)

        def t12():
            # 개정 V (a): 같은 stage 의 다른 시안(m2)은 그 시안의 files 범위만 스냅샷한다
            # (m1 쪽 — fb1/fb2 → mockup.html/css 만 — 은 2번 체크가 이미 확인했다. 여기선 m2 쪽을 본다).
            rc = main(["claim", fb_m2])
            assert rc in (0, None), rc
            st = FC.fold(FC.read_log(), FC.load_registry())
            cl = st["items"][fb_m2]["claim"]
            assert st["items"][fb_m2]["version"] == "m2", st["items"][fb_m2]
            files_dir = C.p("feedback", "snap", cl, "files")
            assert os.path.isfile(os.path.join(files_dir, "design", "testscreen", "wire.html")), files_dir
            assert not os.path.exists(os.path.join(files_dir, "design", "testscreen", "mockup.html")), \
                "m2 시안 claim 이 m1 의 files(mockup.html) 까지 스냅샷함"
            assert not os.path.exists(os.path.join(files_dir, "design", "testscreen", "mockup.css")), \
                "m2 시안 claim 이 m1 의 files(mockup.css) 까지 스냅샷함"
            return "m2 시안 claim=%s → files 범위가 wire.html 뿐(m1 의 mockup.html/css 와 안 섞임)" % cl
        check(results, "12 시안별 files 범위 분리(개정 V)", t12)

        def t13():
            # 개정 V (b): 같은 화면/stage 지만 시안(version)이 다른 id 를 섞으면 거부한다.
            before = len(FC.read_log())
            rc = main(["claim", fb5, fb_m2])  # fb5=기본 시안 m1, fb_m2=m2 — screen·stage 는 같다
            assert rc not in (0, None), "서로 다른 시안의 id 를 섞은 claim 이 거부되지 않음"
            assert len(FC.read_log()) == before, "거부됐는데 로그가 늘어남"
            return "같은 screen/stage, 다른 version(시안) id 섞기 거부(이벤트 없음, 개정 V)"
        check(results, "13 시안(version) 섞기 거부(개정 V)", t13)

        def t14():
            # 개정 V (c): keys --version 이 그 시안만 걸러서 보여준다.
            out_all = _capture(lambda: main(["keys", "TestScreen", "--stage", "mockup"]))
            assert "(m1)" in out_all and "(m2)" in out_all, out_all[:400]  # 필터 없으면 등록된 시안 전부
            out_m2 = _capture(lambda: main(["keys", "TestScreen", "--stage", "mockup", "--version", "m2"]))
            assert "(m2)" in out_m2 and "(m1)" not in out_m2, out_m2[:400]
            return "--version 없음 → m1·m2 모두, --version m2 → m2 만"
        check(results, "14 keys --version(개정 V)", t14)

        def t15():
            out = _capture(lambda: main(["list", "--screen", "TestScreen"]))
            assert ("- 경로: feed-row[friendlistunit · shop-list] › "
                    "thumbnailcharacterunit[ShopItemSlotUnit]") in out, out
            assert ("- 교체 제안: thumbnailcharacterunit → thumbnailemptyunit · "
                    "키트: 썸네일/빈 슬롯 `(스니펫)`") in out, out
            return "7.3 경로·교체 제안(+키트) 다이제스트 줄 확인(list)"
        check(results, "15 list 의 path·suggest 다이제스트(개정 L)", t15)

        def t16():
            out = _capture(lambda: main(["show", fb_tpl]))
            assert ("- 경로: feed-row[friendlistunit · shop-list] › "
                    "thumbnailcharacterunit[ShopItemSlotUnit]") in out, out
            assert ("- 교체 제안: thumbnailcharacterunit → thumbnailemptyunit · "
                    "키트: 썸네일/빈 슬롯 `(스니펫)`") in out, out
            return "show 도 list 와 같은 다이제스트 줄 출력"
        check(results, "16 show 의 path·suggest 다이제스트(개정 L)", t16)

        def t17():
            assert _kit_tail(None, "x") == "키트 정보 없음(라이브러리 미빌드)", _kit_tail(None, "x")
            assert _kit_tail(False, "x") == "키트 정보 없음(라이브러리 손상)", _kit_tail(False, "x")
            assert _kit_tail({"templates": {}}, "x") == "키트에 없음"
            assert _kit_tail({"templates": {"friendlistunit": {"kit": []}}}, "friendlistunit") == "키트에 없음"
            assert _kit_tail({"templates": {"x": "garbage"}}, "x") == "키트에 없음"  # entry 가 dict 아님
            assert _kit_tail({"templates": {"x": {"kit": "garbage"}}}, "x") == "키트에 없음"  # kit 가 list 아님
            return "라이브러리 미빌드/손상/키트 없음 폴백 확인(단위)"
        check(results, "17 _kit_tail 폴백(단위, 개정 L·R4 LOW)", t17)

        def t18():
            """R4 LOW — catalog/library/index.json 이 실제로 깨져 있을 때 _load_lib_index 가 예외 없이
            False(손상) 를 돌려주는지(파일 I/O 경로 — t17 은 이미 메모리상의 값으로 _kit_tail 만 본다)."""
            lib_path = os.path.join(root, "catalog", "library", "index.json")
            good = open(lib_path, encoding="utf-8").read()
            try:
                _write(lib_path, "{not valid json")
                with FC._use_root(root):  # noqa: SLF001
                    assert _load_lib_index() is False, _load_lib_index()
                _write(lib_path, json.dumps({"templates": ["not", "a", "dict"]}))
                with FC._use_root(root):  # noqa: SLF001
                    assert _load_lib_index() is False, _load_lib_index()
            finally:
                _write(lib_path, good)  # 15·16 번이 참조하는 정상 인덱스로 복원
            return "JSON 파싱 실패·templates 가 dict 아님 → False(손상), 예외 없음"
        check(results, "18 _load_lib_index 손상 폴백(파일 I/O, R4 LOW)", t18)

        def t19():
            """개정 F(9.5) — open·comment 첨부가 list 에 저장소 루트 기준 경로로 나온다. 없는 파일은 [파일 없음]."""
            rel = "feedback/attachments/%s.png" % ("c" * 20)
            _write(os.path.join(root, *rel.split("/")), "png")
            fb_att = FC.append({"type": "open", "screen": "TestScreen", "stage": "mockup", "kind": "visual",
                                "text": "이 그림대로", "component": "header", "state": "team",
                                "attachments": [{"path": rel, "name": "ref.png"}]}, "user")["id"]
            FC.append({"type": "comment", "id": fb_att, "text": "하나 더", "attachments": [{"path": rel}]}, "user")
            out = _capture(lambda: main(["list", "--screen", "TestScreen"]))
            disp = "%s/%s" % (os.path.basename(root), rel)
            assert "- 첨부: %s (ref.png)" % disp in out, out
            assert "  - [user] 하나 더 (첨부: %s)" % disp in out, out
            os.remove(os.path.join(root, *rel.split("/")))
            out = _capture(lambda: main(["list", "--screen", "TestScreen"]))
            assert "- 첨부: %s (ref.png) [파일 없음]" % disp in out, out
            return "open 첨부 줄·코멘트 첨부 꼬리·파일 없음 표시"
        check(results, "19 list 의 첨부 줄(개정 F)", t19)

    bad = 0
    for name, ok, detail in results:
        bad += not ok
        print("%s  %s  %s" % ("PASS" if ok else "FAIL", name, detail))
    print("결과: %d/%d PASS" % (len(results) - bad, len(results)))
    return 1 if bad else 0


# ================================================================ CLI 진입점
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true", help="임시 루트에서 전 명령 자체 테스트")
    sub = ap.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="피드백 목록(마크다운/JSON)")
    p_list.add_argument("--screen")
    p_list.add_argument("--status", default="open,reopened")
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="피드백 1건 전체 이력")
    p_show.add_argument("id")

    p_claim = sub.add_parser("claim", help="피드백을 claim(스냅샷+before 샷)")
    p_claim.add_argument("ids", nargs="+")

    p_release = sub.add_parser("release", help="claim 해제")
    p_release.add_argument("ids", nargs="+")
    p_release.add_argument("--reason", required=True)

    p_revise = sub.add_parser("revise", help="수정 반영(diff+after 샷)")
    p_revise.add_argument("ids", nargs="+")
    p_revise.add_argument("--summary", required=True)
    p_revise.add_argument("--new-version")
    p_revise.add_argument("--no-shots", action="store_true")

    p_comment = sub.add_parser("comment", help="코멘트 추가")
    p_comment.add_argument("id")
    p_comment.add_argument("text")

    p_keys = sub.add_parser("keys", help="화면의 data-area 키 현황 보고")
    p_keys.add_argument("screen")
    p_keys.add_argument("--stage", choices=["wire", "mockup"])
    p_keys.add_argument("--version", help="시안 버전(개정 V). 생략하면 등록된 모든 (stage, version)")
    p_keys.add_argument("--top", type=int, default=15)

    sub.add_parser("build", help="feedback/state.js 재생성")
    return ap


def main(argv):
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    try:
        if a.cmd == "list":
            statuses = [s.strip() for s in a.status.split(",") if s.strip()]
            return cmd_list(a.screen, statuses, a.json)
        if a.cmd == "show":
            return cmd_show(a.id)
        if a.cmd == "claim":
            return cmd_claim(a.ids)
        if a.cmd == "release":
            return cmd_release(a.ids, a.reason)
        if a.cmd == "revise":
            return cmd_revise(a.ids, a.summary, a.new_version, a.no_shots)
        if a.cmd == "comment":
            return cmd_comment(a.id, a.text)
        if a.cmd == "keys":
            return cmd_keys(a.screen, a.stage, a.version, a.top)
        if a.cmd == "build":
            return cmd_build()
    except (CliError, FC.FeedbackError) as e:
        print("오류: %s" % e, file=sys.stderr)
        return 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
