"""T6 — app-flow.html(앱 흐름 홈)에 붙일 설계 단계 배지 + "설계 진행" 표의 HTML 조각 생성.

출처: feedback/CONTRACT.md 2절(registry, 시안 풀다운 '개정 V' 포함) · 4.1(counts 형태) · 4.3(GET /api/feedback) ·
4.6(배지 명세, 개정 V 줄 포함 — 이 모듈이 구현하는 부분).
숫자는 이 모듈이 계산하지 않는다 — 전부 런타임에 catalog/assets/badges.js 가 window.UIA_FEEDBACK.counts(또는
GET /api/feedback)로 채운다. 이 모듈은 자리(``data-uia-count="<키>|<stage 또는 *>|<open|fixed>"``)만 만든다.

개정 V(2026-10-23, registry.json 의 같은 stage 에 시안이 여러 개): registry 의 `stages` 배열에 같은 `stage` 값이
여러 번 나올 수 있고(화면 안에서 유일한 건 (stage, version)), **그 stage 의 첫 항목 = 기본 시안**이다. 이 모듈의
표·배지는 stage 칸/칩마다 기본 시안 하나만 보여 주고, 시안이 2개 이상이면 "외 시안 N"(N = 전체 시안 수 - 1)을
덧붙인다. 리뷰 링크는 stage 당 하나, 기본 시안으로(쿼리에 `v` 를 안 붙인다 — CONTRACT 4.5 "v 가 없으면 그 stage 의
기본 시안"). 숫자(열린·검토 대기)는 여전히 stage 합(`counts`, 시안별이 아니라 `(screen, stage)` 단위)이라 시안이
몇 개든 그대로다 — badges.js 는 바꿀 필요가 없다.

붙이는 법(오케스트레이터 몫 — 이 파일은 catalog_templates.py·build_catalog.py 를 바꾸지 않는다):
  - catalog_templates.build_app_flow() 의 body 조립 앞부분에 ``head_html()`` 과 ``progress_html(E, registry)`` 를 끼운다
    (registry 는 ``feedback_core.load_registry()`` 또는 동등한 ``design/registry.json`` 로드 결과).
  - 같은 함수의 화면 카드 ``scard(B, td, out, slug, ui, "", sub, i)`` 호출에서 ``sub`` 뒤에
    ``screen_badges_html(E, registry, ui)`` 를 붙인다.
  - 앱 아이콘 ``<button class='app' data-app=...>`` 조립부에 ``app_badge_html(E, registry, a["contentsType"])`` 를
    아이콘(``<span class='ic'>``) 안쪽 끝에 붙인다.

한계:
  - "열린"(open+reopened)·"검토 대기"(fixed) 는 화면 전체(모든 stage 합, stage="*")로 집계한다 — stage 별 분해가
    필요하면 리뷰 뷰어(T5, catalog/review.html)를 쓴다. 이 표·배지는 한눈에 보는 요약이다.
  - registry 에 없는 화면/앱은 빈 문자열을 돌려준다(카드·아이콘 모양이 안 바뀐다) — "등록 안 됐다"와 "0건"을 구분한다.
  - E 는 호출자의 ``html.escape``(build_catalog.py 의 E)를 그대로 받는다 — 이 모듈은 이스케이프 방식을 정하지 않는다.
  - R2 LOW(``data-uia-count`` 키에 ``|`` 문자): 키를 quote 하지 않기로 했다(보고에서 판단 근거 설명) — UIType·
    contentsType 은 registry 의 screens 키/``app`` 값으로, C# 쪽 식별자(enum 이름류)라 ``|`` 를 포함하지 않는다.
    포함하게 되면 badges.js 의 ``split('|')`` 가 깨진다(두 번째 구분자부터 밀림) — badges.js 쪽에도 같은 주석을 뒀다.
"""
from urllib.parse import quote

STATUS_LABEL = {"wip": "진행 중", "done": "완료", "confirmed": "확정"}
STAGE_LABEL = {"wire": "와이어", "mockup": "목업"}


def head_html():
    """app-flow.html 본문 앞에 넣는 조각. ``feedback/state.js`` 가 없어도(404) 페이지는 깨지지 않는다 —
    badges.js 가 ``window.UIA_FEEDBACK`` 부재를 전제로 동작한다."""
    return ('<link rel="stylesheet" href="assets/badges.css">'
            '<script src="../feedback/state.js"></script>'
            '<script src="assets/badges.js" defer></script>')


def _stage_variants(info):
    """stage → 그 stage 에 등록된 항목 리스트(registry 순서 그대로, 개정 V: 첫 항목 = 기본 시안).
    dict 순서 = 화면 안에서 그 stage 가 처음 나온 순서(보통 wire → mockup)."""
    groups = {}
    for s in (info or {}).get("stages", []):
        groups.setdefault(s.get("stage"), []).append(s)
    return groups


def _review_href(ui, stage):
    """review.html 쿼리 문자열. R2 LOW: screen·stage 값을 퍼센트 인코딩한다(``safe=""`` — UIType·stage 에
    ``&``·``=`` 같은 구분자 문자가 섞여도 쿼리가 안 깨진다). ``?``·``=``·``&`` 는 구분자라 그대로 둔다."""
    return "review.html?screen=%s&stage=%s" % (quote(ui, safe=""), quote(stage, safe=""))


def _extra_variants(n):
    """시안이 2개 이상일 때만 "· 외 시안 N"(개정 V). n = 그 stage 의 전체 시안 수."""
    return " · <span class='mut'>외 시안 %d</span>" % (n - 1) if n > 1 else ""


def _stage_cell(E, variants):
    """표 안 와이어·목업 칸: "<기본 시안 버전> · <상태>"(+ 시안이 2개 이상이면 "· 외 시안 N", 개정 V) 또는
    그 stage 가 등록 안 됐으면 '—'."""
    if not variants:
        return "<span class='mut'>—</span>"
    default = variants[0]
    status = STATUS_LABEL.get(default.get("status"), default.get("status") or "")
    return "%s · %s%s" % (E(default.get("version") or ""), E(status), _extra_variants(len(variants)))


def _stage_chip(E, stage_key, variants):
    """배지 칩 하나: "와이어 r3 · 완료"(+ "외 시안 N", 개정 V). 기본 시안(variants[0]) 기준."""
    default = variants[0]
    label = STAGE_LABEL.get(stage_key, stage_key or "")
    status = STATUS_LABEL.get(default.get("status"), default.get("status") or "")
    return "<span class='fbchip'>%s %s · %s%s</span>" % (
        E(label), E(default.get("version") or ""), E(status), _extra_variants(len(variants)))


def _review_link(E, ui, stage_key):
    """stage 당 하나, 기본 시안으로 가는 리뷰 링크(개정 V: ``v`` 를 안 붙인다 = 기본 시안)."""
    label = STAGE_LABEL.get(stage_key, stage_key or "")
    return "<a class='fblink' href='%s'>%s 리뷰 ›</a>" % (E(_review_href(ui, stage_key)), E(label))


def progress_html(E, registry):
    """"설계 진행" 표: 화면(라벨·UIType) · 와이어(기본 시안 버전·상태) · 목업(동일, 없으면 '—') · 열린 ·
    검토 대기 · 리뷰 뷰어 링크(stage 당 1개). 시안이 2개 이상이면 그 stage 칸에 "외 시안 N"(개정 V).
    registry 에 화면이 하나도 없으면 빈 문자열."""
    screens = (registry or {}).get("screens") or {}
    if not screens:
        return ""
    rows = []
    for ui, info in screens.items():
        label = info.get("label") or ui
        variants = _stage_variants(info)
        links = "".join(_review_link(E, ui, stage_key) for stage_key in variants) or "<span class='mut'>—</span>"
        rows.append(
            "<tr><td>%s <span class='mut'>%s</span></td><td>%s</td><td>%s</td>"
            "<td><b data-uia-count='%s|*|open'>—</b></td><td><b data-uia-count='%s|*|fixed'>—</b></td>"
            "<td class='fblinks'>%s</td></tr>" % (
                E(label), E(ui), _stage_cell(E, variants.get("wire")), _stage_cell(E, variants.get("mockup")),
                E(ui), E(ui), links))
    return ("<h2>설계 진행</h2><table class='fbprogress'><tr><th>화면</th><th>와이어</th><th>목업</th>"
            "<th>열린</th><th>검토 대기</th><th>리뷰</th></tr>%s</table>" % "".join(rows))


def screen_badges_html(E, registry, ui):
    """화면 카드 sub 에 붙일 배지(stage 별 칩 하나 + 열린/검토 대기 숫자 자리 + stage 당 리뷰 링크 하나).
    시안이 2개 이상인 stage 는 칩에 "외 시안 N"(개정 V). ui 가 등록부에 없으면 빈 문자열."""
    info = ((registry or {}).get("screens") or {}).get(ui)
    if not info:
        return ""
    variants = _stage_variants(info)
    chips = "".join(_stage_chip(E, stage_key, vs) for stage_key, vs in variants.items())
    links = "".join(_review_link(E, ui, stage_key) for stage_key in variants)
    return ("<div class='fbbadges'>%s"
            "<span class='fbcount'>열린 <b data-uia-count='%s|*|open'>—</b></span>"
            "<span class='fbcount'>검토 대기 <b data-uia-count='%s|*|fixed'>—</b></span>%s</div>" % (
                chips, E(ui), E(ui), links))


def app_badge_html(E, registry, contents_type):
    """앱 아이콘에 얹는 작은 숫자 배지(그 앱의 등록 화면 열린 수 합, stage·시안 무관). 등록 화면이 하나도
    없으면 빈 문자열."""
    screens = (registry or {}).get("screens") or {}
    if not any((info or {}).get("app") == contents_type for info in screens.values()):
        return ""
    return "<span class='fbappbadge' data-uia-count='app:%s|*|open'>—</span>" % E(contents_type)
