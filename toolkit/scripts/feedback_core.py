"""설계 단계 피드백 루프 — 등록부/로그 읽기, 검증, 접기(fold), append, state.js 렌더.
정본 = feedback/CONTRACT.md(특히 3절 이벤트·검증 규칙, 4.1 접은 상태, 4.2 공개 함수).

이 모듈이 임포트되는 쪽(T3 review_server.py, T4 feedback.py)이 쓰는 공개 함수:
  load_registry() -> dict                    design/registry.json
  read_log() -> list[dict]                    feedback/log.jsonl 전 줄(없으면 [])
  fold(events, registry) -> dict              {"items","revisions","counts","versionCounts"} (4.1). 잘못된 줄이면 FeedbackError
  check(event, state, registry) -> list[str]  3.1 검증 위반 메시지(빈 목록 = 통과)
  append(event, by) -> dict                   락 → 검증 → 한 줄 append → state.js 재생성. 실패 시 FeedbackError(로그 불변)
  next_id(prefix, events) -> str               prefix ∈ fb·cl·rev 의 다음 id
  lock()                                      프로세스 간 배타 락(컨텍스트 매니저). 같은 스레드 재진입 가능,
                                               다른 스레드는 대기(threading.Lock) — T3(ThreadingHTTPServer) 대응
  render_state_js(state, registry) -> str     "window.UIA_FEEDBACK = {...};\\n" (키: generatedAt·registry·items·revisions·counts·versionCounts)
  write_state_js()                            log → fold → feedback/state.js 원자적 재생성
  FeedbackError(Exception)                    .status: 400(검증)·409(상태 전이)·503(락 타임아웃)

경로는 모두 호출 시점의 common.ROOT 기준(C.p(...))으로 계산한다 — 모듈 전역에 경로를 캐시하지 않는다.
그래서 같은 프로세스 안에서 common.ROOT 를 바꿔도(아래 selftest 의 _use_root) 곧바로 반영된다.

사용(ui-audit/ 에서):
  python scripts/feedback_core.py --selftest
한계: files 가 registry 의 files 범위 안인지, ids 중복 여부는 CONTRACT 3.1 의 6개 규칙에 없어 여기서 검사하지 않는다
     (files 범위는 CLI(T4)가 diff 생성 시, ids 중복은 요구되지 않음 — 과설계 방지).

개정 L(2026-10-23, 7.1·7.2) — open 의 선택 필드 path·suggest:
  접은 item 에 path·suggest 키가 항상 있다(open 에 없으면 null). 규칙 7(_path_and_suggest_violations)이
  path 1~12개·항목 문자열 상한(template·variant 200, selector 500)·component↔path area 일치·
  kind=template↔suggest 결합·suggest.template 의 템플릿 인덱스(data/template-index.json) 실존을 검사한다.
  구조(항목당 area/template/selector 중 하나 이상)는 스키마가 이미 막아 여기선 재검사하지 않는다.
"""
import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import validate as V  # noqa: E402

SCHEMA_NAME = "feedback-event.schema"
STATUSES = ["open", "reopened", "claimed", "fixed", "closed"]
TEXT_MAX = 4000
SUMMARY_MAX = 2000
SELECTOR_MAX = 500
AUTHOR_MAX = 40  # 개정 A — user 이벤트 작성자 이름
ATTACHMENT_NAME_MAX = 120  # 개정 F(9.2) — 첨부 원래 파일 이름

# 개정 L(7.1) — path·suggest 문자열 상한. 스키마는 path 의 minItems/maxItems(1~12)까지만 막고 길이는 모른다.
PATH_MAX_ITEMS = 12
PATH_FIELD_MAX = {"template": 200, "variant": 200, "selector": SELECTOR_MAX}
SUGGEST_VARIANT_MAX = 200

BY_ALLOWED = {
    "open": {"user"},
    "comment": {"user", "claude"},
    "claim": {"claude"},
    "release": {"claude"},
    "revision": {"claude"},
    "close": {"user"},
    "reopen": {"user"},
}

# type -> 이 효과가 요구하는 "출발" status 집합 (3.1 규칙 5). open·comment 는 전이 제약이 없다.
EFFECT_FROM = {
    "claim": {"open", "reopened"},
    "release": {"claimed"},
    "revision": {"claimed"},
    "close": set(STATUSES) - {"closed"},
    "reopen": {"fixed", "closed"},
}


class FeedbackError(Exception):
    """.status: 400(검증 실패) · 409(상태 전이 불가) · 503(락 타임아웃)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ================================================================ 읽기
def load_registry():
    path = C.p("design", "registry.json")
    reg = C.load_json(path)
    if reg is None:
        raise FeedbackError("registry 없음: design/registry.json", 400)
    return reg


def read_log():
    path = C.p("feedback", "log.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for i, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError as e:
                raise FeedbackError("log.jsonl:%d: JSON 파싱 실패: %s" % (i, e), 400)
    return out


# ================================================================ 검증 (3.1)
def _length_violations(event):
    errs = []
    if "text" in event:
        t = event["text"]
        if not t.strip():
            errs.append("text 가 공백만 있음")
        elif len(t) > TEXT_MAX:
            errs.append("text 가 %d자를 넘음" % TEXT_MAX)
    if "summary" in event:
        s = event["summary"]
        if not s.strip():
            errs.append("summary 가 공백만 있음")
        elif len(s) > SUMMARY_MAX:
            errs.append("summary 가 %d자를 넘음" % SUMMARY_MAX)
    if "selector" in event and len(event["selector"]) > SELECTOR_MAX:
        errs.append("selector 가 %d자를 넘음" % SELECTOR_MAX)
    if "author" in event:  # 개정 A
        a = event["author"]
        if event.get("by") != "user":
            errs.append("author 는 by=user 이벤트에만 쓸 수 있음")
        elif not a.strip():
            errs.append("author 가 공백만 있음")
        elif len(a) > AUTHOR_MAX:
            errs.append("author 가 %d자를 넘음" % AUTHOR_MAX)
    if "attachments" in event:  # 개정 F(9.2) — 실존은 append 때만(_missing_attachments)
        atts = event["attachments"]
        if event.get("by") != "user":
            errs.append("attachments 는 by=user 이벤트에만 쓸 수 있음")
        paths = [a["path"] for a in atts]
        if len(set(paths)) != len(paths):
            errs.append("attachments 에 같은 path 가 두 번 있음")
        for i, a in enumerate(atts):
            name = a.get("name")
            if name is None:
                continue
            if not name.strip():
                errs.append("attachments[%d].name 이 공백만 있음" % i)
            elif len(name) > ATTACHMENT_NAME_MAX:
                errs.append("attachments[%d].name 이 %d자를 넘음" % (i, ATTACHMENT_NAME_MAX))
    return errs


def _missing_attachments(event):
    """개정 F(9.2) — append 때만 보는 첨부 파일 실존. fold 는 보지 않는다(파일이 나중에 사라져도 로그는 읽힌다).
    경로 형식은 스키마 패턴이 이미 feedback/attachments/<20hex>.<ext> 로 묶었다."""
    return ["첨부 파일 없음: %s" % a["path"] for a in event.get("attachments") or []
            if not os.path.isfile(C.p(*a["path"].split("/")))]


def _load_template_index():
    """data/template-index.json 의 templates 배열(개정 L 7.2) 읽기. 매 호출마다 읽는다(캐시 없음, append
    빈도가 낮고 파일이 작아 과설계 방지). 반환 (ok, templates):
      파일 없음           -> (True, None)   — 호출자가 "템플릿 인덱스 없음" 으로 구분해 거부
      JSON 파싱 실패 ·     -> (False, None)  — 호출자가 "템플릿 인덱스 손상" 으로 거부
      객체가 아님 ·
      templates 가 문자열 리스트가 아님
      정상                -> (True, templates)
    R4 HIGH: 예전엔 templates 가 문자열이면 `in` 이 부분 문자열 매칭으로 실존 검사를 우회하고, 리스트가
    아니면(int 등) `in` 이 TypeError 를 던져 서버가 응답 없이 끊겼다(FeedbackError 로 못 잡힘) — 구조를
    여기서 전부 검증해 호출자가 예외 없이 처리할 수 있게 한다."""
    path = C.p("data", "template-index.json")
    if not os.path.exists(path):
        return True, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            index = json.load(f)
    except ValueError:  # json.JSONDecodeError 포함
        return False, None
    if not isinstance(index, dict):
        return False, None
    templates = index.get("templates")
    if not isinstance(templates, list) or not all(isinstance(t, str) for t in templates):
        return False, None
    return True, templates


def _path_and_suggest_violations(event):
    """3.1 규칙 7(개정 L, 전부 400). open 이 아니면 빈 목록(path·suggest 는 open 전용 — 스키마가 이미 막는다).
    path 의 구조(항목당 area/template/selector 중 하나 이상, 1~12개)는 스키마가 이미 막아 여기선 문자열
    상한과 component↔path, kind↔suggest 결합, suggest.template 실존만 본다."""
    if event.get("type") != "open":
        return []
    errs = []
    path = event.get("path")
    if path is not None:
        if not (1 <= len(path) <= PATH_MAX_ITEMS):
            errs.append("path 는 1~%d개 항목이어야 함" % PATH_MAX_ITEMS)
        for i, item in enumerate(path):
            for field, limit in PATH_FIELD_MAX.items():
                v = item.get(field)
                if v is not None and len(v) > limit:
                    errs.append("path[%d].%s 가 %d자를 넘음" % (i, field, limit))
        component = event.get("component")
        if component is not None and not any(item.get("area") == component for item in path):
            errs.append("component(%s) 가 path 의 어떤 항목의 area 와도 안 맞음" % component)

    kind = event.get("kind")
    suggest = event.get("suggest")
    if kind == "template" and suggest is None:
        errs.append("kind=template 이면 suggest 가 필수")
    if kind != "template" and suggest is not None:
        errs.append("kind 가 template 이 아니면 suggest 를 둘 수 없음")
    if suggest is not None:
        variant = suggest.get("variant")
        if variant is not None and len(variant) > SUGGEST_VARIANT_MAX:
            errs.append("suggest.variant 가 %d자를 넘음" % SUGGEST_VARIANT_MAX)
        template_slug = suggest.get("template")
        ok, templates = _load_template_index()
        if not ok:
            errs.append("템플릿 인덱스 손상")
        elif templates is None:
            errs.append("템플릿 인덱스 없음")
        elif template_slug not in templates:
            errs.append("suggest.template 이 템플릿 인덱스에 없음: %s" % template_slug)
    return errs


def _transition_violation(event, state):
    etype = event["type"]
    if etype not in EFFECT_FROM:
        return None
    ids = event.get("ids") or [event["id"]]
    items = state["items"]
    bad = [i for i in ids if items[i]["status"] not in EFFECT_FROM[etype]]
    if bad:
        return "상태 전이 불가(%s): %s" % (
            etype, ", ".join("%s=%s" % (i, items[i]["status"]) for i in bad))
    if etype in ("release", "revision"):
        claim = event["claim"]
        wrong = [i for i in ids if items[i]["claim"] != claim]
        if wrong:
            return "%s: %s 가 claim %s 로 claimed 상태가 아님" % (etype, ", ".join(wrong), claim)
    return None


def _stage_variants(registry, screen_name, stage_name):
    """등록부에서 그 화면의 그 stage 에 해당하는 항목들(시안 목록), 등록부 순서 그대로.
    첫 항목 = 기본 시안(개정 V). 화면 자체가 없으면 None, 화면은 있는데 그 stage 가 없으면 []."""
    screen = registry.get("screens", {}).get(screen_name)
    if screen is None:
        return None
    return [s for s in screen.get("stages", []) if s.get("stage") == stage_name]


def _violations(event, state, registry):
    """(status, [메시지]) — 3.1 규칙 1→6 순서로 검사해 첫 위반에서 멈춘다. 위반 없으면 (None, [])."""
    errs = V.validate_obj(event, SCHEMA_NAME)
    if errs:
        return 400, errs  # 규칙 1: 스키마 위반

    etype = event["type"]
    if event.get("by") not in BY_ALLOWED.get(etype, set()):
        return 400, ["type=%s 에는 by=%s 가 허용되지 않음" % (etype, event.get("by"))]  # 규칙 2

    if etype == "open":  # 규칙 3: screen·stage·version·그 시안의 state 존재 + component null 이면 selector·bbox 필수
        variants = _stage_variants(registry, event["screen"], event["stage"])
        if variants is None:
            return 400, ["없는 screen: %s" % event["screen"]]
        if not variants:
            return 400, ["%s 화면에 없는 stage: %s" % (event["screen"], event["stage"])]
        version = event.get("version")
        stage_entry = next((s for s in variants if s.get("version") == version), None)
        if stage_entry is None:
            return 400, ["%s/%s 에 없는 version(시안): %s" % (event["screen"], event["stage"], version)]
        if event.get("state") is not None:
            state_ids = {s["id"] for s in stage_entry.get("states", [])}
            if event["state"] not in state_ids:
                return 400, ["%s/%s/%s 에 없는 state: %s" % (
                    event["screen"], event["stage"], version, event["state"])]
        if event.get("component") is None and not (event.get("selector") and event.get("bbox")):
            return 400, ["component 가 null 이면 selector 와 bbox 가 필수"]
    else:  # 규칙 4: 모르는 id·ids (open 은 새로 만드는 id 라 대상이 아니다)
        ids = event.get("ids") or [event["id"]]
        missing = [i for i in ids if i not in state.get("items", {})]
        if missing:
            return 400, ["모르는 id: %s" % ", ".join(missing)]

    trans_msg = _transition_violation(event, state)  # 규칙 5
    if trans_msg:
        return 409, [trans_msg]

    len_errs = _length_violations(event)  # 규칙 6
    if len_errs:
        return 400, len_errs

    path_errs = _path_and_suggest_violations(event)  # 규칙 7 (개정 L)
    if path_errs:
        return 400, path_errs

    return None, []


def check(event, state, registry):
    return _violations(event, state, registry)[1]


# ================================================================ 접기 (4.1)
def _empty_counts(registry):
    """counts — stage 안 모든 시안(version)을 합친 집계."""
    counts = {}
    for screen, data in registry.get("screens", {}).items():
        counts[screen] = {}
        for stage in data.get("stages", []):
            counts[screen].setdefault(stage["stage"], {s: 0 for s in STATUSES})
    return counts


def _empty_version_counts(registry):
    """versionCounts — 등록부의 모든 (screen, stage, version) 을 0 채움으로(개정 V)."""
    vc = {}
    for screen, data in registry.get("screens", {}).items():
        vc[screen] = {}
        for stage in data.get("stages", []):
            vc[screen].setdefault(stage["stage"], {})[stage["version"]] = {s: 0 for s in STATUSES}
    return vc


def _version_bucket(state, screen, stage, version):
    """등록부에서 빠진 (screen, stage, version) 이면 versionCounts 에 그 키를 새로 만들어 넣는다(개정 V)."""
    return state["versionCounts"].setdefault(screen, {}).setdefault(stage, {}) \
        .setdefault(version, {s: 0 for s in STATUSES})


def _bump(state, item, status, delta):
    state["counts"][item["screen"]][item["stage"]][status] += delta
    _version_bucket(state, item["screen"], item["stage"], item["version"])[status] += delta


def _apply(ev, state):
    t = ev["type"]
    if t == "open":
        item = {
            "id": ev["id"], "screen": ev["screen"], "stage": ev["stage"], "version": ev["version"],
            "kind": ev["kind"], "text": ev["text"], "component": ev.get("component"),
            "idx": ev.get("idx"), "template": ev.get("template"), "selector": ev.get("selector"),
            "bbox": ev.get("bbox"), "state": ev.get("state"),
            "path": ev.get("path"), "suggest": ev.get("suggest"),  # 개정 L(4.1) — 없으면 null
            "status": "open", "claim": None,
            "openedAt": ev["at"], "updatedAt": ev["at"],
            "revisions": [], "history": [ev],
        }
        state["items"][ev["id"]] = item
        _bump(state, item, "open", 1)
        return
    if t == "comment":
        item = state["items"][ev["id"]]
        item["history"].append(ev)
        item["updatedAt"] = ev["at"]
        return
    ids = ev.get("ids") or [ev["id"]]
    items = [state["items"][i] for i in ids]
    if t == "claim":
        for item in items:
            _bump(state, item, item["status"], -1)
            state["_preClaim"][item["id"]] = item["status"]
            item["status"] = "claimed"
            item["claim"] = ev["claim"]
            _bump(state, item, "claimed", 1)
            item["history"].append(ev)
            item["updatedAt"] = ev["at"]
    elif t == "release":
        for item in items:
            _bump(state, item, "claimed", -1)
            restored = state["_preClaim"].pop(item["id"], "open")
            item["status"] = restored
            item["claim"] = None
            _bump(state, item, restored, 1)
            item["history"].append(ev)
            item["updatedAt"] = ev["at"]
    elif t == "revision":
        for item in items:
            _bump(state, item, "claimed", -1)
            state["_preClaim"].pop(item["id"], None)
            item["status"] = "fixed"
            item["claim"] = None
            _bump(state, item, "fixed", 1)
            item["revisions"].append(ev["rev"])
            item["history"].append(ev)
            item["updatedAt"] = ev["at"]
        state["revisions"][ev["rev"]] = ev
    elif t == "close":
        for item in items:
            _bump(state, item, item["status"], -1)
            item["status"] = "closed"
            item["claim"] = None
            _bump(state, item, "closed", 1)
            item["history"].append(ev)
            item["updatedAt"] = ev["at"]
    elif t == "reopen":
        for item in items:
            _bump(state, item, item["status"], -1)
            item["status"] = "reopened"
            _bump(state, item, "reopened", 1)
            item["history"].append(ev)
            item["updatedAt"] = ev["at"]


def fold(events, registry):
    state = {"items": {}, "revisions": {}, "counts": _empty_counts(registry),
             "versionCounts": _empty_version_counts(registry), "_preClaim": {}}
    for line_no, ev in enumerate(events, 1):
        status, errs = _violations(ev, state, registry)
        if status is not None:
            raise FeedbackError("log.jsonl:%d: %s" % (line_no, "; ".join(errs)), status)
        _apply(ev, state)
    return {"items": state["items"], "revisions": state["revisions"], "counts": state["counts"],
            "versionCounts": state["versionCounts"]}


# ================================================================ id 발급 · 락
def next_id(prefix, events):
    field, etype = {"fb": ("id", "open"), "cl": ("claim", "claim"), "rev": ("rev", "revision")}[prefix]
    nums = []
    for ev in events:
        if ev.get("type") == etype and field in ev:
            m = re.match(r"^%s-(\d+)$" % re.escape(prefix), ev[field])
            if m:
                nums.append(int(m.group(1)))
    return "%s-%04d" % (prefix, max(nums, default=0) + 1)


_STALE_LOCK_AGE = 30.0  # 이 초보다 오래된 .lock 파일은 비정상 종료로 남은 것으로 보고 정리한다

_local = threading.local()        # 스레드별 재진입 깊이 — 프로세스 전역 카운터는 스레드 간에 새는 버그였다
_thread_lock = threading.Lock()   # 같은 프로세스 안, 스레드 간 배타(T3 ThreadingHTTPServer 대응)


def _acquire_file_lock(deadline):
    """feedback/.lock 를 O_CREAT|O_EXCL 로 잡는다(프로세스 간 배타). deadline 까지 못 잡으면 503."""
    path = C.p("feedback", ".lock")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = None
    while fd is None:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            now = time.time()
            if now >= deadline:
                raise FeedbackError("feedback/.lock 획득 실패(10초 타임아웃)", 503)
            try:  # 오래된(비정상 종료로 남은) 락 파일 정리
                if now - os.path.getmtime(path) > _STALE_LOCK_AGE:
                    os.remove(path)
            except OSError:
                pass
            time.sleep(0.03)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
    except OSError:
        pass
    return fd


def _release_file_lock(fd):
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.remove(C.p("feedback", ".lock"))
    except OSError:
        pass


@contextlib.contextmanager
def lock(timeout=10.0):
    """이중 배타: 프로세스 간은 feedback/.lock(파일), 같은 프로세스의 스레드 간은 threading.Lock.
    재진입은 **같은 스레드에서만** 허용한다(threading.local 깊이) — 다른 스레드는 반드시 대기한다.
    둘 중 하나라도 timeout(기본 10초) 안에 못 잡으면 FeedbackError(status=503)."""
    deadline = time.time() + timeout
    depth = getattr(_local, "depth", 0)
    if depth > 0:  # 이 스레드가 이미 전체 락(스레드 락 + 파일 락)을 쥐고 있다 — 그대로 진행
        _local.depth = depth + 1
        try:
            yield
        finally:
            _local.depth = depth
        return

    if not _thread_lock.acquire(timeout=max(0.0, deadline - time.time())):
        raise FeedbackError("feedback 락 획득 실패(스레드 대기 10초 타임아웃)", 503)
    try:
        _local.depth = 1
        fd = _acquire_file_lock(deadline)
        try:
            yield
        finally:
            _release_file_lock(fd)
    finally:
        _local.depth = 0
        _thread_lock.release()


# ================================================================ append · state.js
def render_state_js(state, registry):
    payload = {
        "generatedAt": C.now_iso(),
        "registry": registry,
        "items": state["items"],
        "revisions": state["revisions"],
        "counts": state["counts"],
        "versionCounts": state.get("versionCounts", {}),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    text = text.replace("</", "<\\/")
    return "window.UIA_FEEDBACK = %s;\n" % text


def write_state_js():
    with lock():
        registry = load_registry()
        state = fold(read_log(), registry)
        text = render_state_js(state, registry)
        path = C.p("feedback", "state.js")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)


def append(event, by):
    """실패 시 FeedbackError(로그 불변). 성공 시 저장된(발급 필드가 채워진) 이벤트를 돌려준다."""
    with lock():
        registry = load_registry()
        events = read_log()
        state = fold(events, registry)

        ev = dict(event)
        ev["by"] = by
        ev["at"] = C.now_iso()
        etype = ev.get("type")

        if etype == "open":
            ev["id"] = next_id("fb", events)
            # 개정 V: 클라이언트가 보낸 version 은 지우지 않는다(등록 여부는 _violations 규칙 3 이 검사).
            # 안 보내면(키 없음 또는 null) 그 stage 의 기본 시안(첫 항목) version 으로 채운다.
            if ev.get("version") is None:
                variants = _stage_variants(registry, ev.get("screen"), ev.get("stage")) or []
                if variants:
                    ev["version"] = variants[0].get("version")
        elif etype == "claim":
            claim_id = next_id("cl", events)
            ev["claim"] = claim_id
            ev["snap"] = "feedback/snap/%s" % claim_id
        elif etype == "revision":
            rev_id = next_id("rev", events)
            ev["rev"] = rev_id
            ev["diff"] = "feedback/revisions/%s.diff" % rev_id

        status, errs = _violations(ev, state, registry)
        if status is not None:
            raise FeedbackError("; ".join(errs), status)
        missing = _missing_attachments(ev)
        if missing:
            raise FeedbackError("; ".join(missing), 400)

        path = C.p("feedback", "log.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

        write_state_js()
        return ev


# ================================================================ 자체 테스트
def _load_fixture_log():
    path = C.p("feedback", "fixtures", "sample-log.jsonl")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@contextlib.contextmanager
def _use_root(root):
    """같은 프로세스 안에서 common.ROOT 를 바꾼다 — C.p(...) 는 호출 시점에 전역을 보므로 곧바로 반영된다."""
    old = C.ROOT
    C.ROOT = root
    try:
        yield root
    finally:
        C.ROOT = old


def _make_bare_registry_root(name):
    """selftest_dir + design/registry.json(sample-registry 사본) + feedback/ 뿐(data/ 없음) — 템플릿
    인덱스가 "없음"/"손상"인 상황을 각각 직접 꾸리는 selftest 전용(_make_temp_root 는 항상 정상 인덱스를
    같이 넣어 이 용도엔 안 맞는다)."""
    root = C.selftest_dir(name)
    registry = C.load_json(C.p("feedback", "fixtures", "sample-registry.json"))
    os.makedirs(os.path.join(root, "design"), exist_ok=True)
    with open(os.path.join(root, "design", "registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=1)
    os.makedirs(os.path.join(root, "feedback"), exist_ok=True)
    return root


def _make_temp_root(name):
    """selftest_dir(schemas·spec·cache 복사) + design/registry.json(sample-registry 사본) + feedback/
    + data/template-index.json(sample-template-index 사본, 개정 L — suggest.template 실존 검사용)."""
    root = C.selftest_dir(name)
    registry = C.load_json(C.p("feedback", "fixtures", "sample-registry.json"))
    os.makedirs(os.path.join(root, "design"), exist_ok=True)
    with open(os.path.join(root, "design", "registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=1)
    os.makedirs(os.path.join(root, "feedback"), exist_ok=True)
    tmpl_index = C.load_json(C.p("feedback", "fixtures", "sample-template-index.json"))
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    with open(os.path.join(root, "data", "template-index.json"), "w", encoding="utf-8") as f:
        json.dump(tmpl_index, f, ensure_ascii=False, indent=1)
    return root


def _strip_ts(obj):
    """at·openedAt·updatedAt 을 재귀적으로 제거(재현 비교용 — append 가 실시간으로 새로 찍는 시각 필드)."""
    if isinstance(obj, dict):
        return {k: _strip_ts(v) for k, v in obj.items() if k not in ("at", "openedAt", "updatedAt")}
    if isinstance(obj, list):
        return [_strip_ts(x) for x in obj]
    return obj


def _spawn_worker(root, n):
    env = dict(os.environ, UIAUDIT_ROOT=root, PYTHONIOENCODING="utf-8")
    script = os.path.join(C.SCRIPTS, "feedback_core.py")
    return subprocess.Popen([sys.executable, script, "--worker-open", str(n)],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8")


def _worker_open(n):
    """하위 프로세스 전용: open 이벤트를 n 번 append 하고 발급된 fb id 를 한 줄씩 출력. --selftest 의 동시성 검사가 쓴다."""
    base = {"type": "open", "screen": "ShopView", "stage": "mockup", "kind": "bug",
            "text": "동시성 테스트", "component": "feed-row"}
    for _ in range(n):
        ev = append(dict(base), "user")
        print(ev["id"])


def _thread_worker(n, by, out, idx):
    """같은 프로세스 안 스레드 동시성 selftest 전용: open 을 n 번 append 하고 id 목록을 out[idx] 에 담는다."""
    base = {"type": "open", "screen": "ShopView", "stage": "mockup", "kind": "bug",
            "text": "스레드 동시성 테스트", "component": "feed-row"}
    out[idx] = [append(dict(base), by)["id"] for _ in range(n)]


def selftest():
    registry = C.load_json(C.p("feedback", "fixtures", "sample-registry.json"))
    raw_events = _load_fixture_log()
    expected = C.load_json(C.p("feedback", "fixtures", "expected-state.json"))

    print("[1] sample-log fold == expected-state.json")
    with _use_root(_make_temp_root("feedback-fold")):  # 작업 공간의 실제 data/template-index.json 에 기대지 않는다
        state1 = fold(raw_events, registry)
    assert json.dumps(state1, ensure_ascii=False, sort_keys=True) == \
        json.dumps(expected, ensure_ascii=False, sort_keys=True), "원본 fold 결과가 expected-state.json 과 다름"
    print("    비교 방법: json.dumps(sort_keys=True) 완전 일치(시간 필드 포함) — 일치")

    print("[2] 빈 임시 루트에 15줄 순서대로 append 재현 == expected-state.json(시간 필드 제외)")
    root = _make_temp_root("feedback-replay")
    reject_cases = C.load_json(C.p("feedback", "fixtures", "reject-cases.json"))
    with _use_root(root):
        for raw in raw_events:
            append(dict(raw), raw["by"])
        state2 = fold(read_log(), load_registry())
    a = json.dumps(_strip_ts(state2), ensure_ascii=False, sort_keys=True)
    b = json.dumps(_strip_ts(expected), ensure_ascii=False, sort_keys=True)
    assert a == b, "재현 fold 결과가 expected-state.json 과 다름(at·openedAt·updatedAt 제외 비교)"
    print("    비교 방법: 양쪽을 재귀적으로 at·openedAt·updatedAt 제거 후 json.dumps(sort_keys=True) 비교 — 일치")

    print("[3] reject-cases.json %d건 — 전부 거부, 로그 줄 수 불변" % len(reject_cases))
    with _use_root(root):
        before = len(read_log())
        for case in reject_cases:
            try:
                append(dict(case["event"]), case["by"])
            except FeedbackError as e:
                assert e.status == case["expect"], \
                    "%s: status 기대 %s, 실제 %s (%s)" % (case["name"], case["expect"], e.status, e)
            else:
                raise AssertionError("%s: 거부돼야 하는데 성공함" % case["name"])
            assert len(read_log()) == before, "%s 처리 후 로그 줄 수가 바뀜" % case["name"]
    print("    %d건 전부 기대한 status 로 거부 · 로그 %d줄로 불변" % (len(reject_cases), before))

    print("[4] state.js 형식")
    with _use_root(root):
        write_state_js()
        text = open(C.p("feedback", "state.js"), encoding="utf-8").read()
    assert text.startswith("window.UIA_FEEDBACK = "), text[:60]
    body = text[len("window.UIA_FEEDBACK = "):].rstrip("\n")
    assert body.endswith(";"), body[-20:]
    parsed = json.loads(body[:-1])
    assert set(parsed) == {"generatedAt", "registry", "items", "revisions", "counts", "versionCounts"}, set(parsed)
    assert "</" not in text, "이스케이프 안 된 '</' 가 state.js 안에 있음"
    escaped = render_state_js({"items": {"fb-0001": {"text": "</script>나쁜 값"}}, "revisions": {}, "counts": {},
                               "versionCounts": {}}, {})
    assert "</script>" not in escaped and "<\\/script>" in escaped, escaped
    print("    'window.UIA_FEEDBACK = ' 로 시작 · 나머지 JSON 파싱 성공 · 키 6개(versionCounts 포함) 일치 · "
          "'</' 없음(이스케이프 단위 확인 포함)")

    print("[5] 동시 append — 하위 프로세스 4개 x open 25회")
    croot = _make_temp_root("feedback-concurrent")
    procs = [_spawn_worker(croot, 25) for _ in range(4)]
    outs = [p.communicate() for p in procs]
    for i, p in enumerate(procs):
        assert p.returncode == 0, "워커 %d 실패(rc=%s):\n%s" % (i, p.returncode, outs[i][1][-2000:])
    with _use_root(croot):
        events = read_log()
    assert len(events) == 100, "로그 100줄 기대, 실제 %d" % len(events)
    for e in events:
        json.dumps(e)  # 이미 read_log 에서 파싱됨 — 전부 dict 인지만 재확인
    ids = [e["id"] for e in events if e["type"] == "open"]
    assert len(ids) == 100 and len(set(ids)) == 100, "fb id 개수 100 또는 중복 없음 위반: %d개, 중복 %d개" % (
        len(ids), len(ids) - len(set(ids)))
    nums = sorted(int(i.split("-")[1]) for i in ids)
    assert nums == list(range(1, 101)), "fb id 번호에 빈 번호가 있음: %s" % nums
    print("    로그 100줄 전부 JSON 파싱 성공 · fb id 100개 중복 0 · 빈 번호 0")

    print("[6] 로그에 잘못된 줄을 섞으면 fold 가 줄 번호와 함께 FeedbackError")
    bad_events = list(raw_events)
    bad_events[4] = {"type": "open"}  # 5번째 줄(1-base)을 필수 키 없는 깨진 이벤트로 교체
    try:
        fold(bad_events, registry)
    except FeedbackError as e:
        assert "log.jsonl:5" in str(e), "줄 번호가 메시지에 없음: %s" % e
        print("    FeedbackError 발생: %s" % e)
    else:
        raise AssertionError("깨진 줄이 있는데 fold 가 예외를 던지지 않음")

    print("[7] 한 프로세스 안 스레드 동시 append(스레드 8개 x open 25회) + 같은 스레드 재진입")
    troot = _make_temp_root("feedback-threads")
    with _use_root(troot):
        results = {}
        threads = [threading.Thread(target=_thread_worker, args=(25, "user", results, i), daemon=True)
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert all(not t.is_alive() for t in threads), "스레드가 끝나지 않음(교착 의심)"
        assert len(results) == 8, "스레드 중 일부가 out 에 결과를 못 남김(예외로 죽었을 가능성): %s" % sorted(results)
        tevents = read_log()
    assert len(tevents) == 200, "스레드 동시성 로그 200줄 기대, 실제 %d" % len(tevents)
    tids = [e["id"] for e in tevents if e["type"] == "open"]
    assert len(tids) == 200 and len(set(tids)) == 200, "스레드 동시성 fb id 200개 또는 중복 없음 위반: %d개, 중복 %d개" % (
        len(tids), len(tids) - len(set(tids)))
    tnums = sorted(int(i.split("-")[1]) for i in tids)
    assert tnums == list(range(1, 201)), "스레드 동시성 fb id 번호에 빈 번호가 있음: %s" % tnums
    print("    스레드 8개 x open 25회 → 로그 200줄 · fb id 중복 0 · 빈 번호 0")

    preroot = _make_temp_root("feedback-reentrant")
    done = {}

    def _reentrant_probe():
        with lock():  # 바깥에서 한 번 더 잡고, 그 안에서 append() 가 다시 lock() 을 잡는다(같은 스레드 재진입)
            done["id"] = append({"type": "open", "screen": "ShopView", "stage": "mockup", "kind": "bug",
                                 "text": "재진입 확인", "component": "feed-row"}, "user")["id"]

    with _use_root(preroot):
        rt = threading.Thread(target=_reentrant_probe, daemon=True)
        rt.start()
        rt.join(timeout=5)
    assert not rt.is_alive(), "같은 스레드 재진입(with lock(): append(...)) 이 끝나지 않음(교착)"
    assert done.get("id"), "재진입 중 append 가 실패함"
    print("    같은 스레드 재진입(with lock(): append(...)) 교착 없이 완료: %s" % done["id"])

    print("[8] open 의 version 생략/명시 (개정 V — 시안 풀다운)")
    vroot = _make_temp_root("feedback-version")
    with _use_root(vroot):
        ev_default = append({"type": "open", "screen": "ShopView", "stage": "mockup", "kind": "bug",
                              "text": "버전 생략 테스트", "component": "feed-row"}, "user")
        assert ev_default["version"] == "cp-r2", \
            "version 생략 시 기본 시안(cp-r2)으로 안 채워짐: %r" % ev_default.get("version")
        ev_c = append({"type": "open", "screen": "ShopView", "stage": "mockup", "version": "c", "kind": "bug",
                       "text": "C 시안 테스트", "component": "feed-row", "state": "board"}, "user")
        assert ev_c["version"] == "c", "명시한 version 이 그대로 저장되지 않음: %r" % ev_c.get("version")
        vstate = fold(read_log(), load_registry())
    vc = vstate["versionCounts"]["ShopView"]["mockup"]
    assert vc["cp-r2"]["open"] == 1, vc
    assert vc["c"]["open"] == 1, vc
    print("    version 생략 → 기본 시안 cp-r2 로 채워짐 · version=\"c\" 명시 → c 로 저장 · versionCounts 반영 확인")

    print("[9] 개정 L — data/template-index.json 자체가 없으면 suggest 가진 open 거부")
    noindex_root = _make_bare_registry_root("feedback-no-template-index")  # data/ 폴더 자체를 안 만든다
    with _use_root(noindex_root):
        try:
            append({"type": "open", "screen": "ShopView", "stage": "mockup", "kind": "template",
                    "text": "인덱스 없음 테스트", "component": "feed-row",
                    "suggest": {"template": "thumbnailemptyunit"}}, "user")
        except FeedbackError as e:
            assert e.status == 400, e
            assert "템플릿 인덱스 없음" in str(e), e
        else:
            raise AssertionError("data/template-index.json 이 없는데 suggest 가진 open 이 성공함")
        assert read_log() == [], "거부됐는데 로그에 줄이 생김"
    print("    data/template-index.json 없음 → suggest 가진 open 400 거부('템플릿 인덱스 없음'), 로그 0줄")

    print("[10] 개정 L(R4 HIGH) — 템플릿 인덱스 구조가 깨졌으면 400('템플릿 인덱스 손상'), 예외가 안 샘")
    corrupt_cases = [
        ("JSON 파싱 실패", "{not valid json"),
        ("templates 가 문자열(부분 문자열 매칭 우회 방지)", json.dumps({"templates": "thumbnailemptyunit"})),
        ("templates 원소가 int(TypeError 방지)", json.dumps({"templates": [1, 2, 3]})),
        ("templates 키 자체가 없음", json.dumps({"foo": 1})),
        ("루트가 객체가 아님(배열)", json.dumps(["thumbnailemptyunit"])),
    ]
    for label, raw in corrupt_cases:
        croot = _make_bare_registry_root("feedback-corrupt-template-index")
        os.makedirs(os.path.join(croot, "data"), exist_ok=True)
        with open(os.path.join(croot, "data", "template-index.json"), "w", encoding="utf-8") as f:
            f.write(raw)
        with _use_root(croot):
            try:
                append({"type": "open", "screen": "ShopView", "stage": "mockup", "kind": "template",
                        "text": "손상 인덱스 테스트", "component": "feed-row",
                        "suggest": {"template": "thumbnailemptyunit"}}, "user")
            except FeedbackError as e:
                assert e.status == 400, (label, e)
                assert "템플릿 인덱스 손상" in str(e), (label, e)
            else:
                raise AssertionError("%s: 손상된 인덱스인데 open 이 성공함" % label)
            assert read_log() == [], "%s: 거부됐는데 로그에 줄이 생김" % label
    print("    %d개 손상 패턴 전부 FeedbackError(400, '템플릿 인덱스 손상') 로만 거부 — 예외가 새지 않음" %
          len(corrupt_cases))

    print("[11] 개정 F — 첨부: 실존 파일이면 open·comment 통과, 없으면 append 만 400, fold 는 실존을 안 본다")
    aroot = _make_temp_root("feedback-attachments")
    att = {"path": "feedback/attachments/%s.png" % ("a" * 20), "name": "참고.png"}
    with _use_root(aroot):
        try:
            append({"type": "open", "screen": "ShopView", "stage": "mockup", "kind": "visual",
                    "text": "첨부 없음 테스트", "component": "feed-row", "attachments": [att]}, "user")
        except FeedbackError as e:
            assert e.status == 400 and "첨부 파일 없음" in str(e), e
        else:
            raise AssertionError("첨부 파일이 없는데 open 이 성공함")
        assert read_log() == [], "거부됐는데 로그에 줄이 생김"
        os.makedirs(C.p("feedback", "attachments"))
        with open(C.p("feedback", "attachments", "a" * 20 + ".png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        ev = append({"type": "open", "screen": "ShopView", "stage": "mockup", "kind": "visual",
                     "text": "첨부 테스트", "component": "feed-row", "attachments": [att]}, "user")
        cev = append({"type": "comment", "id": ev["id"], "text": "추가 참고", "attachments": [{"path": att["path"]}]},
                     "user")
        os.remove(C.p("feedback", "attachments", "a" * 20 + ".png"))
        astate = fold(read_log(), load_registry())  # 파일이 사라져도 접기는 된다
    hist = astate["items"][ev["id"]]["history"]
    assert hist[0]["attachments"] == [att] and hist[1]["attachments"] == cev["attachments"], hist
    assert "attachments" not in astate["items"][ev["id"]], "접은 item 에 attachments 키가 생김(개정 F 는 item 불변)"
    print("    없는 파일 → 400·로그 0줄 · 실존 → open·comment 저장(history 에 그대로) · 파일 삭제 뒤에도 fold 성공")

    print("feedback_core.py selftest OK")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--worker-open", metavar="N", help=argparse.SUPPRESS)  # 내부용: 동시성 selftest 의 하위 프로세스
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.worker_open:
        _worker_open(int(a.worker_open))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
