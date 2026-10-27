"""P1-2 역할 라벨: 템플릿 213개에 '새 UI 를 조립하는 에이전트가 고를 때 쓰는 역할'을 붙인다.

사용:
  python scripts/ds_roles.py --draft      규칙(이름·경로·kind·contains·컴포넌트) → 안 되면 AGENT_LABELS 표
                                          → ds/roles.draft.json {"vocabulary", "roles": {slug: {role, basis, confidence}}}
  python scripts/ds_roles.py --review     ds/roles.draft.json → ds/roles-review.md (역할별, low 먼저 — 사람 승인용)
  python scripts/ds_roles.py --approve [--set slug=role ...]
                                          ds/roles.draft.json (+수정분) → ds/roles.json {slug: role}  ※ 사람 승인 뒤에만
  python scripts/ds_roles.py --selftest   규칙·초안 조립·review·approve(임시 폴더) 검사. 실제 ds/roles.json 은 만들지 않는다
규칙: data/ 는 읽기만 한다. 생성물은 이 스크립트로 재현한다(손으로 쓴 JSON 금지) — 규칙으로 안 되는 것은 AGENT_LABELS 에 적는다.
     AGENT_LABELS 의 slug 가 규칙에도 걸리면 --draft 가 실패한다(두 근거가 섞이지 않게). 시각·순서가 없는 결정적 출력.
"""
import argparse
import collections
import os
import re
import sys
from typing import Callable, NamedTuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

# ---------------------------------------------------------------- 어휘
VOCABULARY = collections.OrderedDict([
    ("button-primary", "주 행동 버튼(확인·구매·진행). 화면/팝업당 보통 하나 — 노랑 계열"),
    ("button-secondary", "보조 행동 버튼(취소·보조 확인·정보). 파랑·크림·하늘·검정·라인·홀로 계열"),
    ("button-danger", "되돌릴 수 없거나 주의가 필요한 행동 버튼(삭제·포기·나가기) — 빨강"),
    ("button-close", "팝업 우상단 닫기(X) 버튼"),
    ("button-back", "View 좌상단 뒤로 가기 버튼"),
    ("button-icon", "글자 CTA 가 아닌 아이콘·이미지형 기능 버튼(액션 버튼, 말 걸기, 상호작용)"),
    ("tab", "같은 화면 안 카테고리 전환 탭(하나만 선택). 표준 탭 템플릿은 아직 없음"),
    ("toggle", "켜기/끄기·체크 상태 컨트롤(체크박스, ON/OFF 스위치, 토글 버튼)"),
    ("title", "View 상단 제목 띠·팝업 제목·섹션 머리 띠"),
    ("popup-frame", "팝업 바탕 틀(배경 판·사각 틀). 팝업 골격의 바깥 상자"),
    ("panel", "여러 요소를 묶은 기능 전용 정보 블록·화면 조각(팀 정보, 보상 목록, 도움말 페이지 등)"),
    ("list-item", "스크롤 목록·격자에 반복 배치되는 한 칸(행 또는 카드)"),
    ("thumbnail", "캐릭터·아이템·보상 등의 공용 썸네일 슬롯과 그 부품(선택 테두리 등)"),
    ("icon", "작은 단일 아이콘(속성·클래스·스탯·재화 아이콘). 상호작용 없음"),
    ("badge", "다른 요소 위에 얹는 작은 상태 표시(레드닷, 이벤트 배지, 별·초월 등급)"),
    ("currency", "재화 보유량 표시(아이콘+수량, 충전 + 버튼 포함 가능)"),
    ("gauge", "진행도·게이지·홀드 진행 표시"),
    ("text", "글자 전용 줄·스탯 줄(라벨+값)·본문 문단"),
    ("input", "숫자·글자 입력 컨트롤(수량 선택 등)"),
    ("scroll", "스크롤 목록 틀(배경+내용 영역, 탭이 붙을 수 있음)과 스크롤바"),
    ("sort-filter", "목록 정렬·필터 버튼과 그 항목"),
    ("speech-bubble", "캐릭터 말풍선·감정 풍선·채팅 말풍선"),
    ("decor", "상호작용 없는 배경·장식·FX·영상 레이어"),
    ("hud", "전투·마을 인게임 오버레이, 컷씬·대화 오버레이, 튜토리얼 포인터 — 메뉴 화면 조립에는 쓰지 않음"),
])
CONFIDENCES = ("high", "low")


# ---------------------------------------------------------------- 사실(facts)
class Facts(NamedTuple):
    slug: str
    name: str
    path: str
    kind: str
    tier: str
    contains: tuple
    root_comps: frozenset
    comps: frozenset      # 템플릿 안 모든 노드의 컴포넌트 합집합
    boxes: int            # 배치 노드 수(배치 데이터 없으면 0)


def facts_of(t, layout):
    boxes = (layout or {}).get("boxes") or []
    split = lambda s: frozenset(x for x in (s or "").split(",") if x)  # noqa: E731
    allc = frozenset().union(*[split(b.get("comps")) for b in boxes]) if boxes else frozenset()
    return Facts(t["slug"], t["name"], t["path"], t.get("kind") or "other", t.get("tier") or "atom",
                 tuple(t.get("contains") or ()), split(boxes[0].get("comps")) if boxes else frozenset(), allc, len(boxes))


# ---------------------------------------------------------------- 규칙 (위에서부터 처음 맞는 것)
class Rule(NamedTuple):
    name: str
    test: Callable[[Facts], bool]
    role: str
    confidence: str


def _rx(pattern, field="name"):
    r = re.compile(pattern)
    return lambda f: bool(r.search(getattr(f, field)))


RULES = [
    Rule("close-button", lambda f: f.kind == "button" and "close" in f.slug, "button-close", "high"),
    Rule("back-button", lambda f: f.name == "BackButton" or "BackButtonUnit" in f.root_comps, "button-back", "high"),
    Rule("button-red", _rx(r"^Button_Red"), "button-danger", "high"),
    Rule("button-yellow-new", _rx(r"^Button_Yellow_New$"), "button-primary", "low"),
    Rule("button-yellow", _rx(r"^Button_Yellow"), "button-primary", "high"),
    Rule("common-button-accent", lambda f: "/Common_Button/" in f.path and re.search(r"Orange|Holo|_New$", f.name) is not None,
         "button-secondary", "low"),
    Rule("common-button", lambda f: "/Common_Button/" in f.path, "button-secondary", "high"),
    Rule("popup-bg", _rx(r"^Popup_(BG|Rect)"), "popup-frame", "high"),
    Rule("title-name", lambda f: f.name in ("Popup_Title", "ContentTitle") or f.name.endswith("HeaderBand"), "title", "high"),
    Rule("help-section-template", lambda f: "/HelpTooltipPopup/Sections/" in f.path and f.name.endswith("Template"),
         "panel", "high"),
    Rule("help-section-text", lambda f: "/HelpTooltipPopup/Sections/" in f.path
         and (f.kind == "textstyle" or re.search(r"BulletText|Callout", f.name) is not None), "text", "high"),
    Rule("tutorial", _rx(r"(?i)tu[tr]orial"), "hud", "high"),
    Rule("bubble", _rx(r"Bubble"), "speech-bubble", "high"),
    Rule("reddot-badge", _rx(r"RedDot|Badge"), "badge", "high"),
    Rule("grade-badge", _rx(r"Star|Transcendence"), "badge", "high"),
    Rule("toggle-comp", lambda f: bool({"Toggle", "CompositeToggle"} & f.root_comps) or re.search(r"^(OnOff|CheckBox)", f.name) is not None,
         "toggle", "high"),
    Rule("sort-filter-name", _rx(r"^(Sorting|Filter)"), "sort-filter", "high"),
    Rule("scroll-comp", lambda f: "Scrollbar" in f.root_comps or f.name == "ScrollBackground", "scroll", "high"),
    Rule("currency-icon", _rx(r"^CurrencyIconUnit$"), "icon", "high"),
    Rule("currency-name", lambda f: "Currency" in f.name and not f.name.startswith("Thumbnail"), "currency", "high"),
    Rule("thumbnail-folder", lambda f: "/Common/Thumbnail/" in f.path, "thumbnail", "high"),
    Rule("icon-small", lambda f: f.kind == "icon" or f.name.startswith("Icon_")
         or (f.name.endswith("IconUnit") and 0 < f.boxes <= 3 and "Battle" not in f.path), "icon", "high"),
    Rule("gauge-name", _rx(r"Gauge|Progress"), "gauge", "high"),
    Rule("stat-text", _rx(r"^(Next)?Stat(Unit)?$|StatGroupUnit$"), "text", "high"),
    Rule("input-comp", lambda f: "TMP_InputField" in f.comps and 0 < f.boxes < 40, "input", "high"),
    Rule("list-item-comp", lambda f: "LoopListViewItem2" in f.root_comps or f.name.endswith("ListItemUnit"), "list-item", "high"),
    Rule("decor-kind", lambda f: f.kind == "decor" and f.tier == "atom", "decor", "high"),
    Rule("decor-name", _rx(r"(^|_)(BackGround|Blur|Noise|FX)(_|$)|BG_"), "decor", "high"),
]


def apply_rules(f, rules=RULES):
    """처음 맞는 규칙 → (role, 규칙명, confidence). 없으면 None."""
    for r in rules:
        if r.test(f):
            return r.role, r.name, r.confidence
    return None


# ---------------------------------------------------------------- 에이전트 판단 (규칙에 안 걸리는 것만)
# 메타(이름·경로·크기·컴포넌트)와 썸네일(previews/templates·layout/template)을 보고 정했다. AGENT_LOW 는 사람이 꼭 볼 것.
AGENT_LABELS = {
    # 앱(휴대폰) 홈
    "applicationunit": "list-item", "applicationslotunit": "list-item",
    "applicationpageunit": "panel", "applicationbottomunit": "panel", "pagedotunit": "badge",
    # 아레나·랭킹
    "arenamainplayerinfounit": "panel", "arenaplayerinfounit": "list-item",
    "toprankingunit": "list-item", "licensetoprankingunit": "panel",
    # 전투 HUD
    "battleactionbutton": "hud", "battleallyinfopanel": "hud", "battleatackcombojudgeiconunit": "icon",
    "battlebossinfoui": "hud", "battlecharmainslotbuffunit": "hud", "battleexecutionslotunit": "hud",
    "battleinputguidefocusui": "hud", "battlemissioninfopanel": "hud", "battlenumberui": "hud",
    "battleplayercharacterslotunit": "hud", "battleskilliconunit": "hud", "battlestatetimeunit": "hud",
    "battletargetinfoui": "hud", "battletextui": "hud", "battletriggerskilliconunit": "hud",
    "battleresultpanel": "panel",
    "battlestatisticsallycharinfounit": "list-item", "battlestatisticsenemycharinfounit": "list-item",
    # 버튼류(공용 버튼 폴더 밖)
    "button-skip-unit": "button-secondary", "housingcommonbutton": "button-secondary",
    "codehubunit": "list-item", "housingdistrictbuttonunit": "list-item",
    "skillmaterialdungeondifficultybutton": "list-item", "stagedungeonstepunit": "list-item",
    "towntalkbutton": "button-icon", "petinteractbutton": "button-icon", "netminingbuttonunit": "button-icon",
    # 카드·행
    "cashshopproductunit": "list-item", "characterstorycardunit": "list-item", "reelcardunit": "list-item",
    "licensedungeonunit": "list-item", "stagedungeonlobbychapterunit": "list-item",
    "stagedungeonrewardunit": "list-item", "gachamileagerewardunit": "list-item", "gacharesultunit": "list-item",
    "charactergetresultunit": "panel", "friendlistunit": "list-item", "naviichatdmunit": "list-item",
    "chattingunit": "list-item", "housingactorinfounit": "list-item", "housingobjectlistunit": "scroll",
    "levelsyncmaincharacterslotunit": "list-item", "characterskillslotunit": "list-item",
    "characterskilldetailslotunit": "panel", "enemyskillslotunit": "list-item", "equipmentslotunit": "list-item",
    "simplerewardunit": "list-item", "lobbyrewardunit": "list-item", "lobbyrewardscrollunit": "scroll",
    "groundpassattendanceunit": "list-item", "missionlistunit": "scroll", "missionpointrewardgroupunit": "gauge",
    "guildmemberlistunit": "scroll", "useitemunit": "panel", "goodsgroupunit": "currency",
    "stagedungeonenergyunit": "currency", "housingresourceunit": "gauge",
    # 정보 블록
    "teaminfounit": "panel", "stageinfounit": "panel", "myteamunit": "panel", "teamsdpreview": "panel",
    "naviichatprofileunit": "panel", "rechargeeventbarunit": "panel", "weaknessgroup": "panel",
    "housingactorthumbnailunit": "thumbnail", "housingcategoryunit": "tab",
    "section-classcard": "panel", "section-elementdiagram": "panel", "section-elementdiagram2": "panel",
    "gmskillpanel": "hud",  # GM 디버그 도구(코드 로드)
    # 대화·컷씬·마을 오버레이
    "cutscenedialogueui": "hud", "questdialogueui": "hud", "cutscene-interaction-color": "hud",
    "cutsceneinteractionunit": "hud", "instanttalkmessagegroupunit": "list-item", "instanttalkmessageunit": "speech-bubble",
    "instanttalknpcunit": "thumbnail", "elevatorfloorselectui": "hud", "fieldmapnameunit": "hud",
    "townobjecttagunit": "hud", "stagedungeonnetminingspotunit": "icon",
    # 장식·미디어
    "videoplayerunit": "decor",
}
AGENT_LOW = {
    "applicationslotunit", "applicationpageunit", "applicationbottomunit", "pagedotunit",
    "battleatackcombojudgeiconunit", "battleresultpanel", "battlecharmainslotbuffunit",
    "button-skip-unit", "housingcommonbutton", "netminingbuttonunit",
    "housingdistrictbuttonunit", "skillmaterialdungeondifficultybutton", "stagedungeonstepunit",
    "stagedungeonrewardunit", "gacharesultunit", "charactergetresultunit", "chattingunit",
    "housingobjectlistunit", "lobbyrewardscrollunit", "missionlistunit", "guildmemberlistunit",
    "missionpointrewardgroupunit", "housingresourceunit", "stagedungeonenergyunit", "goodsgroupunit",
    "rechargeeventbarunit", "weaknessgroup", "housingactorthumbnailunit", "housingcategoryunit",
    "section-classcard", "section-elementdiagram", "section-elementdiagram2", "gmskillpanel",
    "instanttalkmessagegroupunit", "instanttalkmessageunit", "instanttalknpcunit",
    "stagedungeonnetminingspotunit", "videoplayerunit", "useitemunit", "characterskilldetailslotunit",
}


# ---------------------------------------------------------------- 초안 조립
def label_all(facts, agent=AGENT_LABELS, agent_low=AGENT_LOW, rules=RULES):
    """{slug: {role, basis, confidence}} 와 오류 목록. 규칙 우선, 없으면 agent 표."""
    roles, errs = {}, []
    for f in sorted(facts, key=lambda x: x.slug):
        hit = apply_rules(f, rules)
        if hit and f.slug in agent:
            errs.append("%s: 규칙 %s 와 AGENT_LABELS 에 모두 있음 — 한쪽만 남길 것" % (f.slug, hit[1]))
        if hit:
            roles[f.slug] = {"role": hit[0], "basis": "rule:" + hit[1], "confidence": hit[2]}
        elif f.slug in agent:
            roles[f.slug] = {"role": agent[f.slug], "basis": "agent",
                             "confidence": "low" if f.slug in agent_low else "high"}
        else:
            errs.append("%s: 규칙·AGENT_LABELS 어디에도 없음" % f.slug)
    known = {f.slug for f in facts}
    errs += ["AGENT_LABELS 의 %s 는 템플릿 목록에 없음" % s for s in sorted(set(agent) - known)]
    errs += ["AGENT_LOW 의 %s 는 AGENT_LABELS 에 없음" % s for s in sorted(set(agent_low) - set(agent))]
    errs += ["%s: 어휘에 없는 역할 %s" % (s, r["role"]) for s, r in roles.items() if r["role"] not in VOCABULARY]
    return roles, errs


def draft_doc(roles):
    return {"vocabulary": dict(VOCABULARY), "roles": roles}


def load_facts():
    idx = C.load_json(C.p("data", "template-index.json"))
    if not idx:
        raise SystemExit("data/template-index.json 없음")
    out = []
    for s in idx["templates"]:
        t = C.load_json(C.p("data", "templates", s + ".json"))
        if t is None:
            raise SystemExit("data/templates/%s.json 없음" % s)
        out.append((t, facts_of(t, C.load_json(C.p("data", "layout", "template", s + ".json")))))
    return out


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def summary(roles, kinds=None):
    by_role = collections.Counter(r["role"] for r in roles.values())
    basis = collections.Counter("rule" if r["basis"].startswith("rule:") else "agent" for r in roles.values())
    low = sum(1 for r in roles.values() if r["confidence"] == "low")
    print("역할 %d개 · 템플릿 %d · basis %s · low %d" % (len(by_role), len(roles), dict(basis), low))
    print("역할별: " + " · ".join("%s %d" % (k, by_role[k]) for k in VOCABULARY if by_role[k]))
    if kinds:
        other = collections.Counter(roles[s]["role"] for s, k in kinds.items() if k == "other")
        print("kind=other %d → %s" % (sum(other.values()), " · ".join("%s %d" % kv for kv in other.most_common())))


def draft():
    pairs = load_facts()
    roles, errs = label_all([f for _t, f in pairs])
    if errs:
        raise SystemExit("초안 오류 %d건:\n  %s" % (len(errs), "\n  ".join(errs)))
    path = C.p("ds", "roles.draft.json")
    write_text(path, C.dump_json(draft_doc(roles)))
    print("초안: %s" % path)
    summary(roles, {t["slug"]: t["kind"] for t, _f in pairs})
    return 0


# ---------------------------------------------------------------- review
def review_md(doc, meta):
    """meta: {slug: {name, kind, usageTotal, screens}}. 역할(어휘 순)별, 그 안에서 low 먼저·사용 수 내림차순."""
    roles = doc["roles"]
    vocab = doc["vocabulary"]
    by = collections.defaultdict(list)
    for s, r in roles.items():
        by[r["role"]].append(s)
    n_low = sum(1 for r in roles.values() if r["confidence"] == "low")
    basis = collections.Counter("rule" if r["basis"].startswith("rule:") else "agent" for r in roles.values())
    L = ["# 역할 라벨 초안 검토 (P1-2)", "",
         "> 자동 생성 — `ui-audit/scripts/ds_roles.py --review` (원본 `ds/roles.draft.json`). 손으로 고치지 말 것.",
         "> 고칠 것은 `python scripts/ds_roles.py --approve --set <slug>=<role> ...` 로 반영한다(승인 뒤 실행).", "",
         "템플릿 %d · 역할 %d · basis rule %d / agent %d · **confidence low %d** (각 역할 안에서 low 먼저)" % (
             len(roles), len(by), basis["rule"], basis["agent"], n_low), "",
         "## 어휘", "", "| 역할 | 설명 | 수 | low |", "|---|---|---|---|"]
    for k, desc in vocab.items():
        L.append("| `%s` | %s | %d | %d |" % (k, desc, len(by.get(k, [])),
                                              sum(1 for s in by.get(k, []) if roles[s]["confidence"] == "low")))
    for k in vocab:
        items = by.get(k)
        if not items:
            continue
        items = sorted(items, key=lambda s: (roles[s]["confidence"] != "low", -meta[s]["usageTotal"], s))
        L += ["", "## `%s` (%d)" % (k, len(items)), "", vocab[k], "",
              "| conf | slug | name | kind | 사용 | 화면 | basis | 썸네일 |", "|---|---|---|---|---|---|---|---|"]
        for s in items:
            r, m = roles[s], meta[s]
            img = "[png](../%s)" % m["img"] if m.get("img") else "-"
            L.append("| %s | `%s` | %s | %s | %d | %d | %s | %s |" % (
                "**low**" if r["confidence"] == "low" else "high", s, m["name"], m["kind"], m["usageTotal"],
                len(m["screens"]), r["basis"], img))
    return "\n".join(L) + "\n"


def image_of(t):
    """썸네일 → 배치 렌더 → None (ui-audit 기준 상대 경로)."""
    for rel in (t.get("thumbnail"), "previews/layout/template/%s.png" % t["slug"]):
        if rel and os.path.exists(C.p(rel)):
            return rel
    return None


def review():
    doc = C.load_json(C.p("ds", "roles.draft.json"))
    if not doc:
        raise SystemExit("ds/roles.draft.json 없음 — --draft 먼저")
    meta = {t["slug"]: {"name": t["name"], "kind": t["kind"], "usageTotal": t["usageTotal"], "screens": t["screens"],
                        "img": image_of(t)} for t, _f in load_facts()}
    missing = sorted(set(doc["roles"]) - set(meta))
    if missing:
        raise SystemExit("초안에 있는데 템플릿 목록에 없는 slug: %s — --draft 다시" % ", ".join(missing[:5]))
    path = C.p("ds", "roles-review.md")
    write_text(path, review_md(doc, meta))
    print("검토표: %s" % path)
    return 0


# ---------------------------------------------------------------- approve
def parse_sets(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit("--set 형식은 slug=role: %r" % it)
        s, r = it.split("=", 1)
        out[s.strip()] = r.strip()
    return out


def approve(draft_path, out_path, sets=None):
    """초안 + 수정분 → {slug: role} (slug 정렬). 잘못된 slug·역할이면 아무것도 쓰지 않고 실패."""
    doc = C.load_json(draft_path)
    if not doc:
        raise SystemExit("%s 없음 — --draft 먼저" % draft_path)
    vocab = doc["vocabulary"]
    roles = {s: r["role"] for s, r in doc["roles"].items()}
    errs = ["--set 의 slug %s 는 초안에 없음" % s for s in sets or {} if s not in roles]
    errs += ["--set %s=%s: 어휘에 없는 역할" % (s, r) for s, r in (sets or {}).items() if r not in vocab]
    errs += ["초안 %s: 어휘에 없는 역할 %s" % (s, r) for s, r in roles.items() if r not in vocab]
    if errs:
        raise SystemExit("승인 중단:\n  " + "\n  ".join(errs))
    changed = {s: (roles[s], r) for s, r in (sets or {}).items() if roles[s] != r}
    final = dict(sorted({**roles, **(sets or {})}.items()))
    write_text(out_path, C.dump_json(final))
    print("확정: %s — %d개, 수정 %d건%s" % (out_path, len(final), len(changed),
                                       "".join("\n  %s: %s → %s" % (s, a, b) for s, (a, b) in sorted(changed.items()))))
    return final


# ---------------------------------------------------------------- 실행
def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--set", nargs="*", default=[], metavar="SLUG=ROLE")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.set and not a.approve:
        ap.error("--set 은 --approve 와 함께만")
    if a.draft:
        return draft()
    if a.review:
        return review()
    if a.approve:
        approve(C.p("ds", "roles.draft.json"), C.p("ds", "roles.json"), parse_sets(a.set))
        return 0
    ap.print_help()
    return 2


# ---------------------------------------------------------------- 자체 테스트
def selftest():
    import tempfile

    def F(name, path="Assets/Game/UI/Contents/Shop/X.prefab", kind="other", tier="atom",
          root=(), comps=(), boxes=5, contains=(), slug=None):
        return Facts(slug or C.slugify(name), name, path, kind, tier, tuple(contains), frozenset(root),
                     frozenset(comps) | frozenset(root), boxes)
    cb = "Assets/Game/UI/Contents/Common/Common_Button/%s.prefab"
    cases = [
        (F("Button_Close", cb % "Button_Close", kind="button"), ("button-close", "close-button", "high")),
        (F("BackButton", root=("BackButtonUnit",)), ("button-back", "back-button", "high")),
        (F("Button_Red", cb % "Button_Red", kind="button"), ("button-danger", "button-red", "high")),
        (F("Button_Yellow", cb % "Button_Yellow", kind="button"), ("button-primary", "button-yellow", "high")),
        (F("Button_Yellow_New", cb % "Button_Yellow_New", kind="button"), ("button-primary", "button-yellow-new", "low")),
        (F("Button_Blue", cb % "Button_Blue", kind="button"), ("button-secondary", "common-button", "high")),
        (F("Btn_Holo_Orange", cb % "Btn_Holo_Orange", kind="button"), ("button-secondary", "common-button-accent", "low")),
        (F("Popup_BG_Tall", kind="button"), ("popup-frame", "popup-bg", "high")),
        (F("ContentTitle", kind="decor"), ("title", "title-name", "high")),
        (F("Section_HeaderBand", "X/HelpTooltipPopup/Sections/Section_HeaderBand.prefab", kind="decor"),
         ("title", "title-name", "high")),
        (F("AttackTemplate", "X/HelpTooltipPopup/Sections/AttackTemplate.prefab"), ("panel", "help-section-template", "high")),
        (F("Section_Callout", "X/HelpTooltipPopup/Sections/Section_Callout.prefab", kind="decor"),
         ("text", "help-section-text", "high")),
        (F("Turorial_Part_Mouse_Click_Unit"), ("hud", "tutorial", "high")),
        (F("SpeechBubbleLoader"), ("speech-bubble", "bubble", "high")),
        (F("RedDotUnit"), ("badge", "reddot-badge", "high")),
        (F("ThumbnailStarUnit", "X/Common/Thumbnail/ThumbnailStarUnit.prefab"), ("badge", "grade-badge", "high")),
        (F("CheckBox", root=("Toggle",), kind="toggle"), ("toggle", "toggle-comp", "high")),
        (F("HousingCheckUnit", root=("CompositeToggle", "Button"), kind="button"), ("toggle", "toggle-comp", "high")),
        (F("SortingItemUnitV2", kind="button"), ("sort-filter", "sort-filter-name", "high")),
        (F("Scrollbar", root=("Image", "Scrollbar")), ("scroll", "scroll-comp", "high")),
        (F("CurrencyIconUnit", boxes=2), ("icon", "currency-icon", "high")),
        (F("CurrencyUnit_NoFrame"), ("currency", "currency-name", "high")),
        (F("ThumbnailCurrencyUnit", "X/Common/Thumbnail/ThumbnailCurrencyUnit.prefab"), ("thumbnail", "thumbnail-folder", "high")),
        (F("ClassIconUnit", kind="icon", boxes=1), ("icon", "icon-small", "high")),
        (F("AppIconUnit", boxes=2), ("icon", "icon-small", "high")),
        (F("HoldProgressUnit"), ("gauge", "gauge-name", "high")),
        (F("StatUnit"), ("text", "stat-text", "high")),
        (F("EquipmentStatGroupUnit"), ("text", "stat-text", "high")),
        (F("SelectNumberUnit", comps=("TMP_InputField",), boxes=23), ("input", "input-comp", "high")),
        (F("EventPassLevelUnit", root=("LoopListViewItem2",), boxes=900), ("list-item", "list-item-comp", "high")),
        (F("GuildListItemUnit"), ("list-item", "list-item-comp", "high")),
        (F("Noise", kind="decor"), ("decor", "decor-kind", "high")),
        (F("ChainLinkBG_NewUnit"), ("decor", "decor-name", "high")),
    ]
    for f, want in cases:
        got = apply_rules(f)
        assert got == want, (f.name, got, want)
    # 규칙에 안 걸려야 하는 것: 큰 전투 아이콘, 큰 입력 묶음, composite 장식, 일반 유닛
    for f in (F("BattleSkillIconUnit", "X/Battle/Common/BattleSkillIconUnit.prefab", boxes=34),
              F("BattleAtackComboJudgeIconUnit", "X/Battle/P/BattleAtackComboJudgeIconUnit.prefab", boxes=3),
              F("UseItemUnit", comps=("TMP_InputField",), boxes=590),
              F("RechargeEventBarUnit", kind="decor", tier="composite"), F("TeamInfoUnit")):
        assert apply_rules(f) is None, (f.name, apply_rules(f))
    assert all(r.role in VOCABULARY and r.confidence in CONFIDENCES for r in RULES)
    assert len({r.name for r in RULES}) == len(RULES), "규칙명 중복"
    assert all(v in VOCABULARY for v in AGENT_LABELS.values()) and AGENT_LOW <= set(AGENT_LABELS)
    assert 15 <= len(VOCABULARY) <= 25

    # facts_of: 배치 없으면 boxes 0 · 루트/전체 컴포넌트 분리
    t = {"slug": "x", "name": "X", "path": "p", "kind": "other", "tier": "atom", "contains": ["y"]}
    lay = {"boxes": [{"comps": "A,B"}, {"comps": "C"}, {"comps": None}]}
    fx = facts_of(t, lay)
    assert fx.root_comps == {"A", "B"} and fx.comps == {"A", "B", "C"} and fx.boxes == 3 and fx.contains == ("y",)
    assert facts_of(t, None).boxes == 0 and facts_of(t, None).root_comps == frozenset()

    # label_all: 규칙 우선·agent·누락·중복·낡은 slug·어휘 밖
    fs = [F("Button_Red", cb % "Button_Red", kind="button"), F("TeamInfoUnit"), F("Mystery")]
    roles, errs = label_all(fs, {"teaminfounit": "panel", "mystery": "decor"}, {"mystery"})
    assert not errs, errs
    assert roles["button-red"] == {"role": "button-danger", "basis": "rule:button-red", "confidence": "high"}
    assert roles["teaminfounit"] == {"role": "panel", "basis": "agent", "confidence": "high"}
    assert roles["mystery"]["confidence"] == "low" and list(roles) == sorted(roles)
    _r, errs = label_all(fs, {"button-red": "panel", "teaminfounit": "nope", "gone": "decor"}, {"ghost"})
    joined = "\n".join(errs)
    for frag in ("button-red: 규칙 button-red 와 AGENT_LABELS", "mystery: 규칙·AGENT_LABELS 어디에도 없음",
                 "gone 는 템플릿 목록에 없음", "ghost 는 AGENT_LABELS 에 없음", "teaminfounit: 어휘에 없는 역할 nope"):
        assert frag in joined, (frag, joined)

    # review: low 먼저, 같은 conf 안에서는 사용 수 내림차순, 빈 역할 섹션 없음
    doc = draft_doc({"a": {"role": "panel", "basis": "agent", "confidence": "high"},
                     "b": {"role": "panel", "basis": "agent", "confidence": "low"},
                     "c": {"role": "panel", "basis": "rule:x", "confidence": "high"},
                     "d": {"role": "icon", "basis": "rule:icon-small", "confidence": "high"}})
    meta = {s: {"name": s.upper(), "kind": "other", "usageTotal": u, "screens": ["s"] * u,
                "img": "previews/templates/%s.png" % s if s != "a" else None}
            for s, u in (("a", 1), ("b", 2), ("c", 9), ("d", 3))}
    md = review_md(doc, meta)
    sec = md.split("## `panel` (3)")[1]
    assert sec.index("`b`") < sec.index("`c`") < sec.index("`a`"), sec
    assert "## `tab`" not in md and "## `icon` (1)" in md and "confidence low 1" in md
    assert md.index("## `panel`") < md.index("## `icon`") and "[png](../previews/templates/d.png)" in md
    assert "| high | `a` | A | other | 1 | 1 | agent | - |" in md

    # approve: 임시 폴더에서만. 실제 ds/roles.json 은 건드리지 않는다
    real = C.p("ds", "roles.json")
    real_before = os.path.exists(real)
    assert parse_sets(["a=icon", " b = tab "]) == {"a": "icon", "b": "tab"}
    with tempfile.TemporaryDirectory(prefix="ds-roles-") as d:
        dp, op = os.path.join(d, "roles.draft.json"), os.path.join(d, "out", "roles.json")
        write_text(dp, C.dump_json(doc))
        final = approve(dp, op, {"a": "icon"})
        assert final == {"a": "icon", "b": "panel", "c": "panel", "d": "icon"} and C.load_json(op) == final
        assert list(C.load_json(op)) == ["a", "b", "c", "d"]
        os.remove(op)
        for bad in ({"zz": "icon"}, {"a": "not-a-role"}):
            try:
                approve(dp, op, bad)
                raise AssertionError("잘못된 --set 이 통과함: %r" % bad)
            except SystemExit:
                pass
            assert not os.path.exists(op), "실패한 승인이 파일을 썼다"
        assert approve(dp, op, None) == {"a": "panel", "b": "panel", "c": "panel", "d": "icon"}
    assert os.path.exists(real) == real_before, "selftest 가 실제 ds/roles.json 을 바꿨다"
    print("ds_roles.py selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
