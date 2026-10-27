"""T3 — 설계 단계 피드백 루프의 로컬 리뷰 서버(표준 라이브러리만).
정본 = feedback/CONTRACT.md 4.3(서버 API, 이 파일의 유일한 명세) · 6절(권한 경계).
이 파일은 scripts/feedback_core.py(T2, 수정 금지)를 그대로 import 해서 쓴다 — 등록부 읽기, 로그 읽기,
검증·접기·append 는 전부 feedback_core 책임이고 이 서버는 HTTP 겉옷만 입힌다.

사용:
  python ui-audit/scripts/review_server.py [--port 8770] [--host 127.0.0.1]
    → http://127.0.0.1:8770/ui-audit/catalog/app-flow.html
  팀 공유(상시 서버): --host 에 그 머신의 사내 IP(예: 192.0.2.10)를 준다 — 그 주소로 바인딩하고,
  Origin 허용 목록에 http://<host>:<port> 를 더한다(개정 A). 0.0.0.0 은 Origin 을 정할 수 없어 거부.
  python ui-audit/scripts/review_server.py --selftest

API(4.3 그대로):
  GET  /api/feedback[?screen=X]   200, state.js 와 같은 모양
                                   ({"generatedAt","registry","items","revisions","counts","versionCounts"})
  POST /api/feedback              본문 JSON(open|comment|close|reopen 만) → 201 {"ok":true,"event","item"} /
                                   FeedbackError.status 그대로 {"ok":false,"error"}
  그 밖 경로(GET/HEAD)             정적 서빙. 루트 = common.ROOT 의 부모(클라이언트 저장소).
                                   허용 접두사 = ui-audit/ · Assets/ 뿐, 그 밖·탈출 시도는 403.

한계:
- CORS 헤더를 내지 않는다(뷰어는 같은 오리진에서만 쓴다는 전제). Origin 헤더가 있으면 127.0.0.1/localhost 의
  같은 포트(--host 를 줬으면 그 주소도)만 허용하고, 그 밖은 403 — 브라우저가 아닌 클라이언트가 Origin 을
  안 보내는 것도 허용(그대로 통과).
- 인증은 없다. 사내망 공유 시 누구나 open·comment·close·reopen 을 쓸 수 있다. 작성자는 본문의 선택 필드
  author(개정 A)로 남는다 — 자기 신고 값이라 신원 보증은 아니다.
- POST 는 서버가 by=user·at·id(open) 을 강제한다. open 의 version 은 이 서버가 손대지 않는다 — 클라이언트가
  보내면 core(feedback_core.append)가 그 (stage, version) 이 등록돼 있는지 검증하고, 안 보내면 core 가 그
  stage 의 기본 시안으로 채운다(2026-10-23 개정 V). claim·release·revision(by=claude) 은 이 서버가 아니라
  scripts/feedback.py(T4, CLI) 몫 — 이 서버에 오면 type 허용 목록에 없어 403.
- feedback_core.lock() 은 스레드 안전하다(threading.local 로 재진입 깊이를 스레드별로 추적 + threading.Lock
  으로 같은 프로세스 안 스레드 간 배타, feedback/.lock 파일로 프로세스 간 배타 — 2026-10-23 개정). 이 서버가
  모듈 전역 _STATE_LOCK 으로 feedback_core 호출 구간을 한 번 더 직렬화하는 건 이제는 불필요한 중복이지만
  해롭지는 않아 그대로 둔다(ThreadingHTTPServer 의 동시 요청을 서버 레이어에서도 순차 처리하게 만들 뿐).
- GET 응답의 versionCounts 는 core 의 fold() 결과에 그 키가 아직 없으면(개정 V 미반영 구간) `{}` 로 안전하게
  채운다(`state.get("versionCounts", {})`) — core 가 그 키를 채워 주기 시작하면 그대로 흘러간다.
- 개정 L(7.2): 허용 type 목록은 그대로(open|comment|close|reopen). open 본문의 path·suggest 는 이 서버가
  따로 거르거나 손대지 않고 body 전체를 그대로 `F.append(body, "user")`에 넘긴다 — 1~12단 길이·문자열
  상한·component↔path·kind↔suggest 결합·suggest.template 실존 검사는 전부 feedback_core.check/append 몫.
- 개정 F(9.3): POST /api/attachments — 본문 = 이미지 바이트 그대로(png·jpeg·gif·webp, 10 MiB 이하). 앞 바이트로
  형식을 확인해 feedback/attachments/<sha256 앞 20자>.<ext> 에 원자적으로 쓰고 path 를 돌려준다. 로그는 안 쓴다 —
  이벤트에 붙이는 건 그다음 POST /api/feedback(open·comment) 의 attachments, 검증은 코어 몫.
"""
import argparse
import contextlib
import hashlib
import http.server
import json
import mimetypes
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import feedback_core as F  # noqa: E402

DEFAULT_PORT = 8770
MAX_BODY = 64 * 1024  # 64 KiB
ALLOWED_PREFIXES = ("ui-audit", "Assets")
ALLOWED_POST_TYPES = {"open", "comment", "close", "reopen"}

# 개정 F(9.3) — 첨부 업로드
MAX_ATTACHMENT = 10 * 1024 * 1024        # 10 MiB / 파일
MAX_ATTACHMENTS_TOTAL = 1024 * 1024 * 1024  # 1 GiB / feedback/attachments 전체
ATTACHMENT_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon",
    ".woff": "font/woff", ".woff2": "font/woff2", ".otf": "font/otf", ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8", ".diff": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}

# feedback_core 호출 구간 전체(읽기·쓰기 공통)를 이 락으로 직렬화한다. 위 docstring "한계" 참조.
_STATE_LOCK = threading.Lock()


def static_root():
    """정적 서빙 루트 = common.ROOT(ui-audit) 의 부모 = 클라이언트 저장소. 호출 시점의 C.ROOT 를 본다."""
    return os.path.dirname(C.ROOT)


def _safe_static_path(raw_path):
    """요청 경로(쿼리 제거됨) -> static_root() 밑의 실제 파일 절대경로, 또는 None(거부).
    순서: 퍼센트 디코딩 → 역슬래시·콜론(드라이브 문자, `C:` 등) 거부 → 세그먼트 분해 후 `..`/`.` 처리 →
    허용 접두사(ui-audit/ · Assets/) 확인 → 조인 → realpath 로 루트 밖 탈출(심볼릭 링크 포함) 재확인."""
    try:
        decoded = urllib.parse.unquote(raw_path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    if "\\" in decoded or ":" in decoded:
        return None
    segments = [seg for seg in decoded.split("/") if seg not in ("", ".")]
    if not segments or any(seg == ".." for seg in segments):
        return None
    if segments[0] not in ALLOWED_PREFIXES:
        return None
    root = os.path.realpath(static_root())
    candidate = os.path.realpath(os.path.join(root, *segments))
    if candidate != root and not candidate.startswith(root + os.sep):
        return None
    return candidate


def _content_type(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in CONTENT_TYPES:
        return CONTENT_TYPES[ext]
    guessed = mimetypes.guess_type(path)[0]
    return guessed or "application/octet-stream"


def _sniff_image(data):
    """앞 바이트(시그니처)로 이미지 형식 판정 -> MIME 또는 None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _dir_size(path):
    total = 0
    with os.scandir(path) as it:
        for e in it:
            if e.is_file(follow_symlinks=False):
                total += e.stat(follow_symlinks=False).st_size
    return total


def _store_attachment(data, mime):
    """개정 F(9.1·9.3) — 내용 주소로 저장. (status, payload) 를 돌려준다. 같은 내용이 있으면 다시 쓰지 않는다."""
    name = "%s.%s" % (hashlib.sha256(data).hexdigest()[:20], ATTACHMENT_TYPES[mime])
    rel = "feedback/attachments/" + name
    folder = C.p("feedback", "attachments")
    target = os.path.join(folder, name)
    os.makedirs(folder, exist_ok=True)
    if not os.path.isfile(target):
        if _dir_size(folder) + len(data) > MAX_ATTACHMENTS_TOTAL:
            return 507, {"ok": False, "error": "첨부 저장 공간(1GiB)이 찼음 — 관리자에게 알린다"}
        tmp = "%s.%d.%d.tmp" % (target, os.getpid(), threading.get_ident())
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        except OSError:
            with contextlib.suppress(OSError):  # 쓰다 실패한 조각이 총량에 남지 않게
                os.remove(tmp)
            raise
    return 201, {"ok": True, "attachment": {"path": rel, "type": mime, "size": len(data)}}


def _build_payload(state, registry, screen=None):
    """순수 함수(IO 없음) — fold() 결과 state 를 GET 응답 모양으로 조립·필터(4.1·4.3).
    screen 이 있으면 items·revisions·counts·versionCounts 를 그 화면 것만. core 가 아직 versionCounts 를
    주지 않으면(개정 V 미반영) 빈 dict 로 안전하게 처리한다 — selftest 의 합성 state 로 단위 테스트 가능."""
    items, revisions, counts = state["items"], state["revisions"], state["counts"]
    version_counts = state.get("versionCounts", {})
    if screen:
        items = {k: v for k, v in items.items() if v.get("screen") == screen}
        keep = set(items)
        revisions = {r: ev for r, ev in revisions.items() if set(ev.get("ids") or []) & keep}
        counts = {screen: counts[screen]} if screen in counts else {}
        version_counts = {screen: version_counts[screen]} if screen in version_counts else {}
    return {"generatedAt": C.now_iso(), "registry": registry, "items": items,
            "revisions": revisions, "counts": counts, "versionCounts": version_counts}


def _fold_payload(screen=None):
    """load_registry()·read_log()·fold() 를 실제로 돌려 _build_payload 에 넘기는 IO 래퍼."""
    registry = F.load_registry()
    state = F.fold(F.read_log(), registry)
    return _build_payload(state, registry, screen)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "UIAuditReview/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # 요청 본문 원문은 찍지 않는다 — 메서드·경로·상태코드 한 줄 요약만.
        sys.stderr.write("%s %s\n" % (self.address_string(), (fmt % args)))

    # ---------------------------------------------------------------- 공통 응답 도우미
    def _send_json(self, status, payload, write_body=True, no_store=True, close=False):
        if close:
            self.close_connection = True
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _error(self, status, message, write_body=True):
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _allowed_origins(self):
        port = self.server.server_port
        allowed = {"http://127.0.0.1:%d" % port, "http://localhost:%d" % port}
        host = getattr(self.server, "public_host", None)  # 개정 A — --host 로 띄운 공유 서버
        if host:
            allowed.add("http://%s:%d" % (host, port))
        return allowed

    # ---------------------------------------------------------------- GET/HEAD
    def do_GET(self):
        self._dispatch_get(write_body=True)

    def do_HEAD(self):
        self._dispatch_get(write_body=False)

    def _dispatch_get(self, write_body):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/feedback":
            self._api_get(parsed, write_body)
        elif parsed.path.startswith("/api/"):
            self._send_json(404, {"ok": False, "error": "없는 API"}, write_body=write_body)
        else:
            self._static_get(parsed.path, write_body)

    def _api_get(self, parsed, write_body):
        qs = urllib.parse.parse_qs(parsed.query)
        screen = (qs.get("screen") or [None])[0]
        try:
            with _STATE_LOCK:
                payload = _fold_payload(screen)
        except F.FeedbackError as e:
            return self._send_json(e.status, {"ok": False, "error": str(e)}, write_body=write_body)
        self._send_json(200, payload, write_body=write_body)

    def _static_get(self, raw_path, write_body):
        candidate = _safe_static_path(raw_path)
        if candidate is None:
            return self._error(403, "허용되지 않은 경로", write_body)
        if not os.path.isfile(candidate):
            return self._error(404, "파일 없음", write_body)
        try:
            with open(candidate, "rb") as f:
                data = f.read()
        except OSError:
            return self._error(404, "파일 없음", write_body)
        self.send_response(200)
        self.send_header("Content-Type", _content_type(candidate))
        self.send_header("Content-Length", str(len(data)))
        # candidate 는 realpath 다 — 루트도 realpath 로 맞춰야 8.3 짧은 이름(예: LONGNA~1) 경로에서 어긋나지 않는다
        rel = os.path.relpath(candidate, os.path.realpath(static_root())).replace(os.sep, "/")
        if rel == "ui-audit/feedback/state.js":
            self.send_header("Cache-Control", "no-store")
        if rel.startswith("ui-audit/feedback/attachments/"):  # 개정 F — 사용자 업로드는 선언 형식으로만 해석
            self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if write_body:
            self.wfile.write(data)

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/feedback":
            return self._api_post()
        if parsed.path == "/api/attachments":
            return self._api_attach()
        return self._send_json(404, {"ok": False, "error": "없는 API"}, close=True)

    def _api_attach(self):
        """개정 F(9.3). 거부 순서: Content-Type 415 → Content-Length 400 → 0 바이트 400 → 10MiB 413 → Origin 403
        → (본문 읽기) 시그니처 불일치 400 → 총량 507. 읽기 전 거부는 연결을 닫는다(남은 본문을 버리지 않으므로)."""
        mime = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if mime not in ATTACHMENT_TYPES:
            return self._send_json(415, {"ok": False, "error": "첨부는 png·jpeg·gif·webp 이미지만 받음"}, close=True)
        try:
            length = int(self.headers.get("Content-Length"))
        except (TypeError, ValueError):
            return self._send_json(400, {"ok": False, "error": "Content-Length 헤더가 필요함"}, close=True)
        if length <= 0:
            return self._send_json(400, {"ok": False, "error": "빈 첨부"}, close=True)
        if length > MAX_ATTACHMENT:
            return self._send_json(413, {"ok": False, "error": "첨부가 10MiB 를 넘음"}, close=True)
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self._allowed_origins():
            return self._send_json(403, {"ok": False, "error": "허용되지 않은 Origin: %s" % origin}, close=True)
        data = self.rfile.read(length)
        if len(data) != length:
            return self._send_json(400, {"ok": False, "error": "본문이 Content-Length 보다 짧음"}, close=True)
        if _sniff_image(data) != mime:
            return self._send_json(400, {"ok": False, "error": "파일 내용이 %s 형식이 아님" % mime})
        try:
            with _STATE_LOCK:
                status, payload = _store_attachment(data, mime)
        except OSError as e:
            return self._send_json(500, {"ok": False, "error": "첨부 저장 실패: %s" % e})
        self._send_json(status, payload)

    def _api_post(self):
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._send_json(415, {"ok": False, "error": "Content-Type 은 application/json 이어야 함"},
                                    close=True)
        cl_header = self.headers.get("Content-Length")
        try:
            length = int(cl_header)
        except (TypeError, ValueError):
            return self._send_json(400, {"ok": False, "error": "Content-Length 헤더가 필요함"}, close=True)
        if length < 0:
            return self._send_json(400, {"ok": False, "error": "Content-Length 가 음수"}, close=True)
        if length > MAX_BODY:  # 본문을 읽지 않고 거부
            return self._send_json(413, {"ok": False, "error": "본문이 64KiB 를 넘음"}, close=True)
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self._allowed_origins():
            return self._send_json(403, {"ok": False, "error": "허용되지 않은 Origin: %s" % origin}, close=True)

        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError) as e:
            return self._send_json(400, {"ok": False, "error": "JSON 파싱 실패: %s" % e})
        if not isinstance(body, dict):
            return self._send_json(400, {"ok": False, "error": "JSON 객체가 아님"})
        if body.get("type") not in ALLOWED_POST_TYPES:
            return self._send_json(403, {"ok": False, "error": "허용되지 않은 type: %r" % body.get("type")})

        try:
            with _STATE_LOCK:
                ev = F.append(body, "user")
                item = F.fold(F.read_log(), F.load_registry())["items"].get(ev.get("id"))
        except F.FeedbackError as e:
            return self._send_json(e.status, {"ok": False, "error": str(e)})
        self._send_json(201, {"ok": True, "event": ev, "item": item})


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # socketserver 기본값(5)은 listen() 의 backlog 다 — 도크가 크롭·썸네일·산출물 자원을 한꺼번에 여러
    # 개 요청하면(동시 연결이 짧게 몰림) Windows 에서 더 쌓을 자리가 없어 연결 자체가 거절된다
    # (브라우저엔 ERR_CONNECTION_FAILED, 서버 쪽엔 로그도 안 남는다 — accept 전에 커널이 끊기 때문).
    # ThreadingHTTPServer 는 연결마다 스레드를 바로 띄워 빠르게 비우므로 64 로 올려도 안전하다.
    request_queue_size = 64


def run_server(port, host="127.0.0.1"):
    httpd = Server((host, port), Handler)
    httpd.public_host = host
    url = "http://%s:%d/ui-audit/catalog/app-flow.html" % (host, httpd.server_port)
    print("UI 리뷰 서버 시작: %s  (Ctrl+C 로 종료)" % url, flush=True)
    try:
        httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


# ================================================================ 자체 테스트
def _make_test_root():
    """임시 static_root 를 만든다:
       <tmp>/ui-audit/{schemas, design/registry.json(sample-registry 사본), feedback/, catalog/app-flow.html}
       <tmp>/Assets/icon.txt           (허용 접두사 Assets/ 예시)
       <tmp>/ProjectSettings/secret.txt (허용 접두사 밖 예시)
    반환: ui-audit 디렉터리 경로(= 테스트 중 common.ROOT 로 쓸 값)."""
    import atexit
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="uiaudit-review-server-")
    atexit.register(shutil.rmtree, tmp, True)

    root = os.path.join(tmp, "ui-audit")
    os.makedirs(root)
    shutil.copytree(C.p("schemas"), os.path.join(root, "schemas"))
    os.makedirs(os.path.join(root, "design"))
    registry = C.load_json(C.p("feedback", "fixtures", "sample-registry.json"))
    with open(os.path.join(root, "design", "registry.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=1)
    os.makedirs(os.path.join(root, "feedback"))
    # 개정 L — suggest.template 실존 검사가 읽는 data/template-index.json(sample-template-index 사본).
    os.makedirs(os.path.join(root, "data"))
    tmpl_index = C.load_json(C.p("feedback", "fixtures", "sample-template-index.json"))
    with open(os.path.join(root, "data", "template-index.json"), "w", encoding="utf-8") as f:
        json.dump(tmpl_index, f, ensure_ascii=False, indent=1)
    os.makedirs(os.path.join(root, "catalog"))
    with open(os.path.join(root, "catalog", "app-flow.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><html><body>stub-app-flow</body></html>")

    os.makedirs(os.path.join(tmp, "Assets"))
    with open(os.path.join(tmp, "Assets", "icon.txt"), "w", encoding="utf-8") as f:
        f.write("stub-asset")
    os.makedirs(os.path.join(tmp, "ProjectSettings"))
    with open(os.path.join(tmp, "ProjectSettings", "secret.txt"), "w", encoding="utf-8") as f:
        f.write("secret")
    return root


@contextlib.contextmanager
def _running_server(root, host=None):
    """같은 프로세스 안에서 common.ROOT 를 root 로 바꾸고, 임시 포트에 서버를 띄운다.
    host 를 주면 run_server(--host) 처럼 그 주소로 바인딩하고 public_host 를 단다(개정 A)."""
    old = C.ROOT
    C.ROOT = root
    httpd = Server((host or "127.0.0.1", 0), Handler)
    if host:
        httpd.public_host = host
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield "http://%s:%d" % (host or "127.0.0.1", httpd.server_port)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
        C.ROOT = old


def _raw_request(base, method, path, data=None, headers=None):
    """urllib 로 요청 1개. (status, body_bytes) 를 돌려준다(예외를 던지지 않음)."""
    for attempt in range(3):
        req = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # 거부(403·413) 응답 뒤 서버가 본문을 다 받기 전에 연결을 닫으면 Windows 는 쓰기 쪽에서 10053 을 낸다 — 다시 시도
            if attempt == 2:
                raise


def _post_json(base, path, obj, headers=None):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    return _raw_request(base, "POST", path, data=data, headers=h)


def _open_body(**overrides):
    body = {"type": "open", "screen": "ShopView", "stage": "mockup", "kind": "bug",
            "text": "셀프테스트 피드백", "component": "feed-row"}
    body.update(overrides)
    return body


def selftest():
    results = []

    def run(name, fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — 항목별로 모아 보고하고 다음 항목을 계속 실행한다
            results.append((name, False, "%s: %s" % (type(e).__name__, e)))
            print("[FAIL] %s — %s" % (name, results[-1][2]))
        else:
            results.append((name, True, ""))
            print("[PASS] %s" % name)

    root = _make_test_root()
    with _running_server(root) as base:

        def check_bind():
            # 바인딩 자체는 _running_server 가 Server(("127.0.0.1", 0), ...) 로 이미 했다 — 주소를 재확인한다.
            parsed = urllib.parse.urlsplit(base)
            assert parsed.hostname == "127.0.0.1", base

        def check_open():
            status, body = _post_json(base, "/api/feedback", _open_body())
            assert status == 201, (status, body)
            j = json.loads(body)
            assert j["ok"] is True, j
            assert j["event"]["id"] == "fb-0001", j["event"]
            assert j["event"]["by"] == "user", j["event"]
            with _STATE_LOCK:
                lines = F.read_log()
            assert len(lines) == 1, lines

        def check_reject():
            status, body = _post_json(base, "/api/feedback", _open_body(kind="pretty"))
            assert status == 400, (status, body)
            status, body = _post_json(base, "/api/feedback", {"type": "reopen", "id": "fb-0001", "text": "x"})
            assert status == 409, (status, body)

        def check_forged_fields():
            forged = _open_body(by="claude", id="fb-9999", at="2000-01-01T00:00:00+09:00",
                                 text="위조 필드 테스트")
            status, body = _post_json(base, "/api/feedback", forged)
            assert status == 201, (status, body)
            j = json.loads(body)
            ev = j["event"]
            assert ev["by"] == "user", ev
            assert ev["id"] != "fb-9999", ev
            assert ev["at"] != "2000-01-01T00:00:00+09:00", ev

        def check_claude_types_forbidden():
            for t, extra in (
                ("claim", {"ids": ["fb-0001"], "claim": "cl-0001", "snap": "feedback/snap/cl-0001"}),
                ("revision", {"rev": "rev-0001", "ids": ["fb-0001"], "claim": "cl-0001",
                               "files": ["a"], "diff": "feedback/revisions/rev-0001.diff",
                               "summary": "x", "shots": []}),
                ("release", {"ids": ["fb-0001"], "claim": "cl-0001", "text": "x"}),
            ):
                payload = {"type": t}
                payload.update(extra)
                status, body = _post_json(base, "/api/feedback", payload)
                assert status == 403, (t, status, body)

        def check_static():
            status, _ = _raw_request(base, "GET", "/ui-audit/catalog/app-flow.html")
            assert status == 200, status
            cases = [
                "/ui-audit/../../../../etc/passwd",            # ../
                "/ui-audit/%2e%2e/%2e%2e/ProjectSettings/secret.txt",  # %2e%2e
                "/etc/passwd",                                   # 절대경로(허용 범위 밖)
                "/C:/Windows/system.ini",                        # 드라이브 문자
                "/ui-audit/..%5c..%5cProjectSettings/secret.txt",  # %5c(역슬래시 퍼센트 인코딩)
                "/ProjectSettings/secret.txt",                    # 허용 접두사 밖
            ]
            for path in cases:
                status, _ = _raw_request(base, "GET", path)
                assert status == 403, (path, status)

        def check_open_path_suggest():
            """개정 L — open 본문의 path·suggest 를 서버가 그대로 코어에 넘긴다(필터링 없음)."""
            path = [{"area": "feed-row", "template": "friendlistunit", "selector": "div.row"},
                    {"template": "thumbnailcharacterunit", "selector": "button.slot"}]
            status, body = _post_json(base, "/api/feedback", _open_body(
                kind="template", text="교체 제안 테스트", path=path,
                suggest={"template": "thumbnailemptyunit"}))
            assert status == 201, (status, body)
            j = json.loads(body)
            assert j["event"]["path"] == path, j["event"]
            assert j["event"]["suggest"] == {"template": "thumbnailemptyunit"}, j["event"]
            assert j["item"]["path"] == path, j["item"]
            assert j["item"]["suggest"] == {"template": "thumbnailemptyunit"}, j["item"]

        def check_reject_suggest_unknown_slug():
            status, body = _post_json(base, "/api/feedback", _open_body(
                kind="template", suggest={"template": "no-such-template"}))
            assert status == 400, (status, body)

        def check_reject_kind_template_without_suggest():
            status, body = _post_json(base, "/api/feedback", _open_body(kind="template"))
            assert status == 400, (status, body)

        def check_reject_path_too_long():
            long_path = [{"selector": "div:nth-of-type(%d)" % i} for i in range(13)]
            status, body = _post_json(base, "/api/feedback", _open_body(path=long_path))
            assert status == 400, (status, body)

        def check_burst_static_connections():
            """오케 지시 — socketserver 기본 request_queue_size(5)면 도크가 크롭·썸네일·산출물 자원을
            한꺼번에 요청할 때 Windows 에서 연결 자체가 거절된다(ERR_CONNECTION_FAILED, 서버 로그도 없음
            — accept 전에 커널이 끊는다). 스레드 40개가 동시에 정적 파일을 GET → 전부 200이어야 한다."""
            import concurrent.futures
            n = 40

            def one(_i):
                return _raw_request(base, "GET", "/ui-audit/catalog/app-flow.html")

            with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
                outs = list(ex.map(one, range(n)))
            statuses = [s for s, _ in outs]
            assert all(s == 200 for s in statuses), statuses

        def check_author():
            # 개정 A — author 는 서버가 손대지 않고 그대로 저장, 상한 초과는 코어가 400
            status, body = _post_json(base, "/api/feedback", _open_body(author="홍길동"))
            assert status == 201, (status, body)
            ev = json.loads(body)["event"]
            assert ev["author"] == "홍길동" and ev["by"] == "user", ev
            status, body = _post_json(base, "/api/feedback",
                                      {"type": "comment", "id": ev["id"], "text": "x", "author": "가" * 41})
            assert status == 400, (status, body)

        def check_post_guards():
            big = json.dumps(_open_body(text="x" * (MAX_BODY + 500))).encode("utf-8")
            status, body = _raw_request(base, "POST", "/api/feedback", data=big,
                                         headers={"Content-Type": "application/json"})
            assert status == 413, (status, body)
            status, body = _raw_request(base, "POST", "/api/feedback", data=b"{}",
                                         headers={"Content-Type": "text/plain"})
            assert status == 415, (status, body)
            status, body = _post_json(base, "/api/feedback", _open_body(),
                                       headers={"Origin": "http://evil.example"})
            assert status == 403, (status, body)

        def check_versioncounts_filter_unit():
            """_build_payload 의 versionCounts 필터만 떼어 합성 state 로 검증 — core 의 개정 V(versionCounts
            실제 채움) 진행과 무관하게 이 서버의 필터 로직 자체가 맞는지 보는 단위 테스트(실제 HTTP 왕복 없음)."""
            fake_state = {
                "items": {}, "revisions": {}, "counts": {},
                "versionCounts": {
                    "ShopView": {"mockup": {"cp-r2": {s: 0 for s in F.STATUSES},
                                                 "c": {s: 0 for s in F.STATUSES}}},
                    "ShopBuyPopup": {"wire": {"r1": {s: 0 for s in F.STATUSES}}},
                },
            }
            out_all = _build_payload(fake_state, {}, None)
            assert out_all["versionCounts"] == fake_state["versionCounts"], out_all["versionCounts"]
            out_a = _build_payload(fake_state, {}, "ShopView")
            assert set(out_a["versionCounts"]) == {"ShopView"}, out_a["versionCounts"]
            assert out_a["versionCounts"]["ShopView"] == fake_state["versionCounts"]["ShopView"]
            out_none = _build_payload(fake_state, {}, "NoSuchScreen")
            assert out_none["versionCounts"] == {}, out_none["versionCounts"]
            # core 가 아직 versionCounts 를 안 주는 경우(fold 결과에 키 자체가 없음)에도 죽지 않아야 한다.
            out_missing = _build_payload({"items": {}, "revisions": {}, "counts": {}}, {}, "ShopView")
            assert out_missing["versionCounts"] == {}, out_missing["versionCounts"]

        def check_get_matches_fold():
            with _STATE_LOCK:
                direct = _fold_payload(None)
            status, body = _raw_request(base, "GET", "/api/feedback")
            assert status == 200, (status, body)
            via_http = json.loads(body)
            assert "versionCounts" in via_http, "GET 응답에 versionCounts 키가 없음"
            da, db = dict(direct), dict(via_http)
            da.pop("generatedAt", None)
            db.pop("generatedAt", None)
            assert json.dumps(da, ensure_ascii=False, sort_keys=True) == \
                json.dumps(db, ensure_ascii=False, sort_keys=True), "GET 결과가 직접 fold 와 다름"

            status, body = _post_json(base, "/api/feedback", _open_body(
                screen="ShopBuyPopup", stage="wire", component="popup-root",
                text="다른 화면 피드백"))
            assert status == 201, (status, body)

            status, body = _raw_request(base, "GET", "/api/feedback?screen=ShopView")
            j = json.loads(body)
            assert all(it["screen"] == "ShopView" for it in j["items"].values()), j["items"]
            assert set(j["counts"]) == {"ShopView"}, j["counts"]
            # versionCounts 는 core 가 아직 비워 줄 수 있다(개정 V 반영 중) — 비었든 채워졌든 다른 화면이
            # 섞여 들어오지 않는다는 것만 확인(부분집합 검사).
            assert set(j["versionCounts"]) <= {"ShopView"}, j["versionCounts"]

            status, body = _raw_request(base, "GET", "/api/feedback?screen=ShopBuyPopup")
            j = json.loads(body)
            assert set(j["items"]) and all(it["screen"] == "ShopBuyPopup" for it in j["items"].values()), \
                j["items"]
            assert set(j["counts"]) == {"ShopBuyPopup"}, j["counts"]
            assert set(j["versionCounts"]) <= {"ShopBuyPopup"}, j["versionCounts"]

        png = b"\x89PNG\r\n\x1a\n" + b"selftest-png"

        def upload(data, ctype, headers=None):
            h = {"Content-Type": ctype}
            h.update(headers or {})
            status, body = _raw_request(base, "POST", "/api/attachments", data=data, headers=h)
            return status, json.loads(body)

        def check_attach_upload():
            """개정 F(9.3) — 업로드 → 내용 주소 path, 같은 내용은 같은 path, 정적 GET 으로 그대로 받는다."""
            status, j = upload(png, "image/png")
            assert status == 201 and j["ok"] is True, (status, j)
            att = j["attachment"]
            assert re.match(r"^feedback/attachments/[0-9a-f]{20}\.png$", att["path"]), att
            assert att["type"] == "image/png" and att["size"] == len(png), att
            status2, j2 = upload(png, "image/png")
            assert status2 == 201 and j2["attachment"]["path"] == att["path"], j2
            req = urllib.request.Request(base + "/ui-audit/" + att["path"])
            with urllib.request.urlopen(req, timeout=5) as r:
                assert r.status == 200 and r.read() == png, r.status
                assert r.headers.get("X-Content-Type-Options") == "nosniff", dict(r.headers)
                assert r.headers.get("Content-Type") == "image/png", r.headers.get("Content-Type")
            for data, ctype, ext in ((b"\xff\xd8\xff\xe0jpeg", "image/jpeg", "jpg"), (b"GIF89a....", "image/gif", "gif"),
                                     (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp", "webp")):
                status, j = upload(data, ctype)
                assert status == 201 and j["attachment"]["path"].endswith("." + ext), (ctype, status, j)

        def check_attach_reject():
            for data, ctype, headers, want in (
                (png, "image/svg+xml", None, 415),                 # 이미지 4종 밖
                (png, "application/json", None, 415),
                (b"<svg/>", "image/png", None, 400),               # 시그니처 불일치
                (b"", "image/png", None, 400),                     # 빈 본문
                (png, "image/png", {"Origin": "http://evil.example"}, 403),
            ):
                status, j = upload(data, ctype, headers)
                assert status == want and j["ok"] is False, (ctype, want, status, j)
            # 413 — 본문을 읽지 않고 거부하므로 10MiB 를 실제로 보내면 클라이언트 쪽 쓰기가 끊긴다.
            # 헤더의 Content-Length 만 상한+1 로 주고 본문은 조금만 보낸다.
            import http.client
            parsed = urllib.parse.urlsplit(base)
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            try:
                conn.putrequest("POST", "/api/attachments")
                conn.putheader("Content-Type", "image/png")
                conn.putheader("Content-Length", str(MAX_ATTACHMENT + 1))
                conn.endheaders()
                conn.send(png)
                resp = conn.getresponse()
                assert resp.status == 413 and json.loads(resp.read())["ok"] is False, resp.status
            finally:
                conn.close()
            global MAX_ATTACHMENTS_TOTAL
            old_total = MAX_ATTACHMENTS_TOTAL
            MAX_ATTACHMENTS_TOTAL = 0  # 새 파일은 무조건 총량 초과
            try:
                status, j = upload(b"\x89PNG\r\n\x1a\n" + b"new-content", "image/png")
                assert status == 507, (status, j)
                status, j = upload(png, "image/png")  # 이미 있는 내용은 다시 쓰지 않으므로 통과
                assert status == 201, (status, j)
            finally:
                MAX_ATTACHMENTS_TOTAL = old_total
            assert not [n for n in os.listdir(C.p("feedback", "attachments")) if n.endswith(".tmp")], "tmp 잔여"

        def check_attach_events():
            """업로드한 path 를 open·comment 에 붙여 저장 · 없는 path 는 코어가 400."""
            _, j = upload(png, "image/png")
            att = {"path": j["attachment"]["path"], "name": "참고.png"}
            status, body = _post_json(base, "/api/feedback", _open_body(attachments=[att]))
            assert status == 201, (status, body)
            ev = json.loads(body)["event"]
            assert ev["attachments"] == [att], ev
            status, body = _post_json(base, "/api/feedback",
                                      {"type": "comment", "id": ev["id"], "text": "추가", "attachments": [att]})
            assert status == 201, (status, body)
            ghost = {"path": "feedback/attachments/%s.png" % ("0" * 20)}
            status, body = _post_json(base, "/api/feedback", _open_body(attachments=[ghost]))
            assert status == 400 and "첨부 파일 없음" in json.loads(body)["error"], (status, body)

        run("[1] 127.0.0.1 바인딩", check_bind)
        run("[2] 정상 open -> 201 + id fb-0001 + 로그 1줄", check_open)
        run("[3] 스키마 위반 400 / 상태 전이 위반 409", check_reject)
        run("[4] by·id·at 위조 무시", check_forged_fields)
        run("[5] claim/revision/release -> 403", check_claude_types_forbidden)
        run("[5a] 개정 L: open 의 path·suggest 통과(필터 없음)", check_open_path_suggest)
        run("[5b] 개정 L: suggest.template 이 인덱스에 없으면 400", check_reject_suggest_unknown_slug)
        run("[5c] 개정 L: kind=template 인데 suggest 없으면 400", check_reject_kind_template_without_suggest)
        run("[5d] 개정 L: path 13단이면 400", check_reject_path_too_long)
        run("[6] 정적 파일 접근 제어", check_static)
        run("[6a] 정적 파일 동시 연결 버스트(스레드 %d개) -> 전부 200" % 40, check_burst_static_connections)
        run("[7] 크기·Content-Type·Origin 거부", check_post_guards)
        run("[7a] 개정 A: author 통과·상한 초과 400", check_author)
        run("[7b] 개정 F: 첨부 업로드 4종·같은 내용 같은 path·정적 GET", check_attach_upload)
        run("[7c] 개정 F: 첨부 415·400·403·413·507 거부", check_attach_reject)
        run("[7d] 개정 F: open·comment 에 첨부 저장·없는 path 400", check_attach_events)
        run("[8a] versionCounts 필터 단위 테스트(합성 state)", check_versioncounts_filter_unit)
        run("[8] GET == fold 직접 비교 + screen 필터(+versionCounts)", check_get_matches_fold)

    # [9] 동시 POST — 별도의 깨끗한 임시 루트로 (앞의 로그 상태와 섞이지 않게)
    croot = _make_test_root()
    with _running_server(croot) as cbase:
        def check_concurrent():
            import concurrent.futures
            n = 20

            def one(_i):
                return _post_json(cbase, "/api/feedback", _open_body(text="동시성 테스트"))

            with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
                outs = list(ex.map(one, range(n)))
            statuses = [s for s, _ in outs]
            assert all(s == 201 for s in statuses), statuses
            ids = [json.loads(b)["event"]["id"] for _, b in outs]
            assert len(ids) == n and len(set(ids)) == n, ("중복 id", ids)
            nums = sorted(int(i.split("-")[1]) for i in ids)
            assert nums == list(range(1, n + 1)), ("빈 번호", nums)
            old = C.ROOT
            C.ROOT = croot
            try:
                lines_raw = open(C.p("feedback", "log.jsonl"), encoding="utf-8").read().splitlines()
            finally:
                C.ROOT = old
            assert len(lines_raw) == n, len(lines_raw)
            for ln in lines_raw:
                json.loads(ln)  # 전 줄 JSON 파싱 성공

        run("[9] 동시 POST %d개(스레드)" % 20, check_concurrent)

    # [10] 개정 L(R4 HIGH) — 템플릿 인덱스가 깨졌을 때 500/연결 끊김(RemoteDisconnected) 대신
    # 400 JSON 응답이 나오는지. 앞의 로그 상태와 섞이지 않게 또 별도의 깨끗한 임시 루트로.
    broot = _make_test_root()
    with open(os.path.join(broot, "data", "template-index.json"), "w", encoding="utf-8") as f:
        f.write("{not valid json")
    with _running_server(broot) as bbase:
        def check_corrupt_template_index():
            status, body = _post_json(bbase, "/api/feedback", _open_body(
                kind="template", suggest={"template": "thumbnailemptyunit"}))
            assert status == 400, (status, body)  # RemoteDisconnected 로 예외가 났다면 여기서 이미 실패
            j = json.loads(body)
            assert j["ok"] is False, j
            assert "템플릿 인덱스 손상" in j["error"], j

        run("[10] 개정 L(R4 HIGH): 템플릿 인덱스 손상 -> 400 JSON(연결 끊김 아님)", check_corrupt_template_index)

    # 개정 A — --host 로 띄우면 그 주소의 Origin 도 허용(127.0.0.2 = 루프백 별칭으로 사내 IP 를 흉내)
    hroot = _make_test_root()
    with _running_server(hroot, host="127.0.0.2") as hbase:
        def check_host_origin():
            status, body = _post_json(hbase, "/api/feedback", _open_body(), headers={"Origin": hbase})
            assert status == 201, (status, body)
            status, body = _post_json(hbase, "/api/feedback", _open_body(),
                                      headers={"Origin": "http://evil.example"})
            assert status == 403, (status, body)

        run("[11] 개정 A: --host 주소의 Origin 허용·그 밖 403", check_host_origin)

    ok = all(r[1] for r in results)
    print("review_server.py selftest %s (%d/%d PASS)" %
          ("OK" if ok else "FAIL", sum(1 for r in results if r[1]), len(results)))
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1",
                    help="바인딩 주소. 팀 공유 시 이 머신의 사내 IP(Origin 허용에도 쓴다). 0.0.0.0 불가")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.host in ("", "0.0.0.0", "::"):
        ap.error("--host 에는 구체 주소를 준다(브라우저가 여는 주소와 같아야 Origin 검사를 통과한다)")
    run_server(a.port, a.host)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
