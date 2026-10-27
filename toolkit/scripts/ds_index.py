"""P0-1 에이전트용 디자인 시스템 색인: Docs/ui-design-system/{templates.jsonl, screens.jsonl, INDEX.md} 를 데이터에서 만든다.

사용:
  python scripts/ds_index.py --run        data/templates/*.json · data/template-index.json · data/layout/{screen,template}/*.json ·
                                          data/app-flow.json · decisions.json · ds/roles.json(있으면)
                                          → <저장소>/Docs/ui-design-system/{templates.jsonl, screens.jsonl, INDEX.md}
                                          + UPDATE.md · SKILL.md (갱신·공유 절차 / 팀 에이전트 지침 — 내용은 ds_publish.py)
  python scripts/ds_index.py --check      생성물이 현재 데이터와 같은지, 행 수 = template-index 수·화면 배치 수인지, 썸네일·카탈로그·맵·렌더 경로 존재 집계
  python scripts/ds_index.py --selftest   가짜 템플릿으로 행 생성·정렬·standard 판정·roles 파일 유무 검사 + ds_screens.selftest()(실데이터 수정 없음)
screens.jsonl(화면 → 템플릿 역색인·깨끗한 참고 화면 판정)의 행은 ds_screens.py 가 만든다.
규칙: data/·decisions.json·manifest.json 은 읽기만 한다. ds/roles.json 이 없으면 role 은 null 이고 파일을 만들지 않는다.
     INDEX.md 의 수치·표는 모두 여기서 계산한다(손으로 쓴 수치 금지). 이미지는 복사하지 않고 ui-audit 기준 경로만 적는다.
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalog_templates as CT  # noqa: E402
import common as C  # noqa: E402
import ds_colors as DC  # noqa: E402
import ds_publish as DP  # noqa: E402
import ds_screens as DSS  # noqa: E402
import template_scope as TS  # noqa: E402

TOP_PROPS = 5
SAMPLE_SCREENS = 3
TOP_TABLE = 15
UNDECIDED = "미정"
FIELD_ORDER = ("name", "slug", "tier", "kind", "role", "standard", "usageTotal", "screenCount", "folder", "path",
               "address", "topProps", "styledRate", "sampleScreens", "lookalikeWarning", "contains", "thumbnail", "catalog")
OPEN_PAIRS = [("주 버튼", "button-yellow", "button-yellow-new"), ("정렬 버튼", "sortingbuttonunit", "sortingbuttonunitv2")]
TAB_TEMPLATE = "togglebuttonunit"
HASH_TOKEN_RE = re.compile(r"^color-[0-9a-f]{4,}$")


def out_dir():
    return os.path.normpath(os.path.join(C.ROOT, "..", "Docs", "ui-design-system"))


# ---------------------------------------------------------------- 입력
def load_roles(path):
    """{slug: role}. 파일이 없으면 None (만들지 않는다)."""
    if not os.path.exists(path):
        return None
    return C.load_json(path) or {}


def folder(path):
    """공통 폴더면 common, 아니면 UI/ 아래 기능 폴더(UI/Contents/<기능> 이면 <기능>).
    catalog_templates.folder 는 Contents 아래를 모두 'Contents' 로 묶어서 쓰지 않는다."""
    if TS.is_common(path):
        return "common"
    parts = path.split("/")[:-1]
    i = parts.index("UI") + 1 if "UI" in parts else len(parts) - 1
    if i < len(parts) - 1 and parts[i] == "Contents":
        i += 1
    return parts[min(i, len(parts) - 1)]


def screen_instance_counts():
    """{template slug: {screen slug: (정적 인스턴스, 예시·로더 인스턴스)}} — 배치 맵의 템플릿 인스턴스 루트 박스."""
    res = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for f in C.iter_json(C.p("data", "layout", "screen")):
        lay = C.load_json(f)
        for b in lay["boxes"]:
            if b.get("template"):
                res[b["template"]][lay["slug"]][1 if (b.get("sample") or b.get("loader")) else 0] += 1
    return res


# ---------------------------------------------------------------- 행 만들기
def standard_of(t, decisions):
    """by user 결정 중 이 템플릿(slug·path·guid·'template:<slug>')을 대상으로 한 마지막 것. 없으면 미정."""
    keys = {t["slug"], t["path"], t.get("guid"), "template:" + t["slug"]}
    val = UNDECIDED
    for d in decisions or []:
        if d.get("by") == "user" and d.get("target") in keys:
            to = (d.get("to") or "").replace("template:", "", 1)
            val = d["status"] + ("→" + to if d.get("status") == "폐기" and to else "")
    return val


OUT_PREFAB_RE = re.compile(r'"/([A-Za-z0-9_]+)\.prefab"')


def completely_outputs(editor_dir=None):
    """`PrefabUnpackMode.Completely` 를 쓰는 빌드 툴이 만드는 프리팹 이름 집합.
    출력 경로는 `<폴더 상수> + "/X.prefab"` 꼴이라 '/' 로 시작하는 리터럴만 출력으로 본다(원본은 전체 경로 리터럴)."""
    editor_dir = editor_dir or os.path.normpath(os.path.join(C.unity_root(), *DC.EDITOR_REL.split("/")))
    names = set()
    for base, _dirs, files in os.walk(editor_dir):
        for fn in files:
            if fn.endswith(".cs"):
                with open(os.path.join(base, fn), encoding="utf-8", errors="replace") as f:
                    code = f.read()
                if "PrefabUnpackMode.Completely" in code:
                    names.update(OUT_PREFAB_RE.findall(code))
    return names


def sample_screens(t, counts, screen_names, avoid=frozenset()):
    """사용 많은 화면 3개(이름). 배치 맵의 정적 인스턴스 수 → 예시·로더 인스턴스 수 → 이름 순.
    avoid(Completely 언팩으로 만든 화면 — 템플릿 링크가 끊긴 반면교사)는 참고 화면으로 권하지 않는다."""
    per = counts.get(t["slug"], {})
    cand = [s for s in t["screens"] if screen_names.get(s, s) not in avoid]
    ranked = sorted(cand, key=lambda s: (-per.get(s, (0, 0))[0], -per.get(s, (0, 0))[1], screen_names.get(s, s)))
    return [screen_names.get(s, s) for s in ranked[:SAMPLE_SCREENS]]


def lookalike_warning(items):
    """exact/near 수와 대표 사본 위치. 둘 다 0 이면 None (borderline 은 세지 않는다)."""
    hits = [x for x in items or [] if x.get("match") in ("exact", "near")]
    if not hits:
        return None
    n = collections.Counter(x["match"] for x in hits)
    best = sorted(hits, key=lambda x: (x["match"] != "exact", -x.get("score", 0), x["node"]))[0]
    where = "%s#%s" % (best.get("screen") or "?", best["node"].split("#", 1)[-1])
    return "exact %d · near %d (화면 %d) — 대표 사본: %s" % (
        n["exact"], n["near"], len({x.get("screen") for x in hits}), where)


def thumbnail_of(t, exists):
    th = t.get("thumbnail")
    return "ui-audit/" + th if th and exists(C.p(th)) else None


def build_row(t, decisions, roles, counts, screen_names, exists=os.path.exists, avoid=frozenset()):
    o = t.get("overrides") or {}
    row = {
        "name": t["name"], "slug": t["slug"], "tier": t["tier"], "kind": t["kind"],
        "role": (roles or {}).get(t["slug"]) if roles is not None else None,
        "standard": standard_of(t, decisions),
        "usageTotal": t["usageTotal"], "screenCount": len(t["screens"]), "folder": folder(t["path"]),
        "path": t["path"], "address": t.get("address"),
        "topProps": [list(x) for x in (o.get("topProps") or [])[:TOP_PROPS]],
        "styledRate": o.get("styledRate"),
        "sampleScreens": sample_screens(t, counts, screen_names, avoid),
        "lookalikeWarning": lookalike_warning(t.get("lookalikes")),
        "contains": list(t.get("contains") or []),
        "thumbnail": thumbnail_of(t, exists),
        "catalog": "ui-audit/catalog/templates/%s.html" % t["slug"],
    }
    return {k: row[k] for k in FIELD_ORDER}


def build_rows(temps, decisions, roles, counts, screen_names, exists=os.path.exists, avoid=frozenset()):
    rows = [build_row(t, decisions, roles, counts, screen_names, exists, avoid) for t in temps]
    return sorted(rows, key=lambda r: (-r["usageTotal"], -r["screenCount"], r["name"].lower()))


def jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows)


# ---------------------------------------------------------------- INDEX.md
def pct(x):
    return "-" if x is None else "%d%%" % round(x * 100)


def pair_line(by, slug):
    r = by.get(slug)
    if not r:
        return "`%s` 없음" % slug
    return "%s(사용 %d · 화면 %d · 스타일 변경 %s · 표준 %s)" % (r["name"], r["usageTotal"], r["screenCount"],
                                                       pct(r["styledRate"]), r["standard"])


def open_points(rows, color_tokens):
    by = {r["slug"]: r for r in rows}
    out = ["- **%s**: %s 대 %s" % (label, pair_line(by, a), pair_line(by, b)) for label, a, b in OPEN_PAIRS]
    tabs = [r for r in rows if r["kind"] == "tab"]
    out.append("- **탭**: 종류가 `tab` 인 템플릿 %d개. 가장 가까운 것은 %s — 표준 없음(예: InventoryView 카테고리 탭은 Toggle 을 복사해 붙였다)"
               % (len(tabs), pair_line(by, TAB_TEMPLATE)))
    st = collections.Counter(t["status"] for t in color_tokens)
    hashed = sum(1 for t in color_tokens if HASH_TOKEN_RE.match(t["id"]))
    out.append("- **색 토큰**: %d개, 상태 %s, 이름이 해시(`color-xxxx`)인 것 %d개 — 의미 이름(`ink`·`paper`·`accent`…) 없음"
               % (len(color_tokens), " · ".join("%s %d" % kv for kv in st.most_common()) or "-", hashed))
    other = sum(1 for r in rows if r["kind"] == "other")
    roled = sum(1 for r in rows if r["role"])
    out.append("- **역할 라벨**: role 이 있는 템플릿 %d / %d. kind 가 `other` 인 것 %d개(%s) — kind 만으로 용도를 고르지 말 것"
               % (roled, len(rows), other, pct(other / len(rows)) if rows else "-"))
    return out


def top_table(rows):
    lines = ["| # | name | slug | tier | kind | 사용 | 화면 | 스타일 변경 | 표준 | 대표 화면 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows[:TOP_TABLE], 1):
        lines.append("| %d | %s | `%s` | %s | %s | %d | %d | %s | %s | %s |" % (
            i, r["name"], r["slug"], r["tier"], r["kind"], r["usageTotal"], r["screenCount"], pct(r["styledRate"]),
            r["standard"], ", ".join(r["sampleScreens"]) or "-"))
    return lines


def pair_hits(screens, a, b):
    """INDEX grep 예와 같은 조건: 깨끗한 Popup 이고 정적 템플릿에 a·b 가 둘 다 있는 화면 수."""
    return sum(1 for s in screens if s["kind"] == "Popup" and s["cleanReference"]
               and a in (s.get("templates") or {}) and b in (s.get("templates") or {}))


def screens_section(screens):
    """screens.jsonl 필드 표·grep 예·집계."""
    clean = collections.Counter(s["cleanReference"] for s in screens)
    rec = collections.Counter(s["recipe"] for s in screens)
    L = [
        "## screens.jsonl 필드 (한 줄 = 화면 하나, 이름순) — 비슷한 참고 화면 찾기",
        "| 필드 | 뜻 |",
        "|---|---|",
        "| `name` / `slug` | 화면 프리팹 이름 / 배치 맵 키 |",
        "| `kind` | `View` / `Popup` / `other`(루트 이름·스크립트로 판정) |",
        "| `recipe` | [`skeletons.md`](skeletons.md) 형: `list-tab`(목록+탭형, View 기본형의 부분집합이라 먼저 고른다) · `view-basic` · `popup-tall` · `popup-wide` · `none` |",
        "| `templates` | 쓰는 템플릿 `{slug: 정적 인스턴스 수}`, 많은 순. 다른 템플릿 안에 든 것 포함, 예시·로더 아이템 제외 |",
        "| `loadedTemplates` | 예시·로더 아이템으로만 나오는 템플릿 slug(목록 아이템 Unit 등) |",
        "| `lookalikeCopies` | 템플릿 사본 노드 수 — `template: null` 인데 이름이 템플릿 이름과 같고 컴포넌트가 템플릿 루트와 겹치는 노드"
        " ∪ 템플릿 카드 lookalikes 의 exact/near. 템플릿 인스턴스 안에 화면이 덧붙인 노드도 본다 |",
        "| `looseButtons` | 템플릿 밖 Button 수 — 화면 몫이고 `Button` 컴포넌트가 있는데 템플릿 인스턴스·사본이 아닌 노드(TouchMask 제외, 안쪽 Button 은 한 번만) |",
        "| `cleanReference` / `cleanReason` | 참고 화면으로 권할 수 있나 / 이유(아래 규칙) |",
        "| `app` | 앱 흐름(`app-flow`)에서 이 화면이 나오는 앱 ContentsType, 앱 첫 화면에서 가까운 순. 없으면 `null` |",
        "| `map` / `image` | 배치 맵 페이지 / 렌더 PNG(로컬 `ui-audit/`, 없으면 `null`) |",
        "",
        "**cleanReference 규칙**: `Completely` 언팩 빌드 툴 출력 → `false` · 사본 0 → `true` · 사본 ≤%d 이고 "
        "사본 / (사본 + 정적 템플릿 인스턴스) ≤%d%% → `true` · 그 밖 → `false`. "
        "`looseButtons` 는 판정에 넣지 않는다(맞는 템플릿이 없는 버튼일 수 있다) — 이유 끝에 '템플릿 밖 Button N' 으로만 붙는다."
        % (DSS.COPY_TOLERANCE, round(DSS.COPY_SHARE * 100)),
        "",
        "grep 예 (필드 순서가 kind → templates → cleanReference 라 grep 두 번으로 된다. 0건이면 조건을 하나씩 뺀다):",
        "```",
        "# button-yellow 와 filtergroup 을 둘 다 쓰는 깨끗한 Popup (현재 %d건)" % pair_hits(screens, "button-yellow", "filtergroup"),
        "grep -E '\"kind\":\"Popup\".*\"button-yellow\":' Docs/ui-design-system/screens.jsonl | grep -E '\"filtergroup\":.*\"cleanReference\":true'",
        "# popup-bg-tall 과 button-yellow 를 둘 다 쓰는 깨끗한 Popup (현재 %d건)" % pair_hits(screens, "popup-bg-tall", "button-yellow"),
        "grep -E '\"kind\":\"Popup\".*\"popup-bg-tall\":' Docs/ui-design-system/screens.jsonl | grep -E '\"button-yellow\":.*\"cleanReference\":true'",
        "grep '\"recipe\":\"list-tab\"' Docs/ui-design-system/screens.jsonl | grep '\"cleanReference\":true'   # 깨끗한 목록+탭형 View",
        "grep '\"thumbnailcharacterunit\"' Docs/ui-design-system/screens.jsonl     # 정적·로더 어느 쪽이든 이 Unit 을 쓰는 화면",
        "```",
        "- 집계: 화면 %d · cleanReference true %d / false %d · recipe %s" % (
            len(screens), clean[True], clean[False], " · ".join("%s %d" % kv for kv in rec.most_common())),
        "",
    ]
    return L


def render_index(rows, idx, color_tokens, roles_present, screens=()):
    tiers = collections.Counter(r["tier"] for r in rows)
    std = collections.Counter(r["standard"] for r in rows)
    n_th = sum(1 for r in rows if r["thumbnail"])
    n_lk = sum(1 for r in rows if r["lookalikeWarning"])
    L = [
        "# UI 디자인 시스템 색인 (에이전트용)",
        "",
        "> 자동 생성 — `ui-audit/scripts/ds_index.py --run`. 손으로 고치지 말 것(다시 만들면 덮어쓴다).",
        "> 데이터 기준: `%s` · 템플릿 %d개(atom %d · composite %d) · 화면 %d개" % (
            idx.get("updatedAt", "?"), len(rows), tiers["atom"], tiers["composite"], len(idx.get("screens") or [])),
        "",
        "## 목적",
        "새 UI 화면·팝업을 만들 때 **기존 프리팹 템플릿을 재사용**하게 하는 진입점이다. 무엇이 있고, 얼마나 쓰이고,",
        "표준이 정해졌는지를 여기서 보고 고른다. 새로 만들기 전에 반드시 여기서 찾는다.",
        "",
        "## 읽는 순서",
        "새 화면을 만드는 절차(지시 템플릿·작업 순서·사람 확인 지점)는 [`SKILL.md`](SKILL.md), "
        "이 폴더를 다시 만들고 커밋하는 절차는 [`UPDATE.md`](UPDATE.md).",
        "",
        "1. 이 파일 `INDEX.md` — 규칙·금지·많이 쓰는 템플릿·표준 미정 지점",
        "2. [`skeletons.md`](skeletons.md) — View·Popup 골격 레시피(노드 경로·좌표·템플릿)",
        "3. [`screens.jsonl`](screens.jsonl) — 화면 %d줄: 화면 → 템플릿 역색인 + 깨끗한 참고 화면 표시. 쓸 템플릿·형으로 **grep** 해 비슷한 화면을 찾는다"
        % len(screens),
    ] + ([
        "4. [`%s`](%s) — %s" % (DP.CHECKLIST["file"], DP.CHECKLIST["file"], DP.CHECKLIST["commit_why"]),
    ] if DP.CHECKLIST else []) + [
        "%d. [`templates.jsonl`](templates.jsonl) — 템플릿 카드 %d줄. **통째로 읽지 말고 grep** 한다"
        % (5 if DP.CHECKLIST else 4, len(rows)),
        "",
        "## templates.jsonl 필드 (한 줄 = 템플릿 하나, 사용 수 내림차순)",
        "| 필드 | 뜻 |",
        "|---|---|",
        "| `name` | 프리팹 이름(줄 맨 앞) |",
        "| `slug` | 카탈로그·데이터 키 |",
        "| `tier` | `atom`(다른 템플릿을 안 품음) / `composite`(품음) |",
        "| `kind` | 자동 분류 종류(button·icon·decor… 대부분 `other` — 아래 참고) |",
        "| `role` | 역할 라벨(사람 승인본). `ui-audit/ds/roles.json` 이 없으면 `null` |",
        "| `standard` | 표준 여부 — 사용자 결정(`표준`·`폐기→<대체>`·`예외`), 결정 없으면 `미정` |",
        "| `usageTotal` / `screenCount` | 사용처 수(중첩·코드 로드·씬 합산) / 쓰는 화면 수 |",
        "| `folder` | `common`(공통 폴더) 또는 기능 폴더 |",
        "| `path` / `address` | 프리팹 경로 / Addressable 주소(없으면 `null` — 중첩으로만 쓰임) |",
        "| `topProps` | 인스턴스에서 자주 바꾸는 속성 상위 %d `[속성, 횟수]` — 인스턴스에서 바꿔도 되는 곳의 힌트 |" % TOP_PROPS,
        "| `styledRate` | 인스턴스 중 스프라이트·색을 바꾼 비율(높으면 원본 모양 그대로 쓰는 일이 드묾) |",
        "| `sampleScreens` | 대표 화면 %d개(배치 맵 인스턴스가 많은 순. `Completely` 언팩 빌드 툴이 만든 화면은 반면교사라 뺀다) |" % SAMPLE_SCREENS,
        "| `lookalikeWarning` | 이 템플릿을 풀어 복붙한 듯한 사본(exact/near) 수와 대표 위치. `null` = 없음 |",
        "| `contains` | 품고 있는 하위 템플릿 slug |",
        "| `thumbnail` | 렌더 이미지(저장소 루트 기준, 로컬 `ui-audit/` — 없으면 `null`) |",
        "| `catalog` | 템플릿 배치 맵 페이지(로컬 `ui-audit/`) |",
        "",
        "grep 예:",
        "```",
        "grep -i '\"name\":\"Button_' Docs/ui-design-system/templates.jsonl      # 버튼 템플릿",
        "grep '\"kind\":\"button\"' Docs/ui-design-system/templates.jsonl         # 종류로",
        "grep '\"folder\":\"common\"' Docs/ui-design-system/templates.jsonl       # 공통 폴더 것만",
        "grep '\"standard\":\"표준\"' Docs/ui-design-system/templates.jsonl        # 표준으로 정해진 것",
        "grep -i 'popup-bg' Docs/ui-design-system/templates.jsonl              # slug·경로 일부로",
        "```",
        "",
    ]
    L += screens_section(screens)
    L += [
        "## 규칙·금지",
        "- **참고 화면은 `screens.jsonl` 의 `cleanReference=true` 에서 고른다.** `false` 화면(사본·Completely 출력)의 구조는 따르지 않는다.",
        "- **복제는 `PrefabUtility.LoadPrefabContents`(또는 `PrefabUnpackMode.OutermostRoot`)로.** "
        "`PrefabUnpackMode.Completely` 언팩 금지 — 중첩 템플릿 링크가 전부 끊겨 같은 이름의 사본이 된다%s."
        % ("(%s)" % DP.COMPLETELY_CASE if DP.COMPLETELY_CASE else ""),
        "- **기존 화면 프리팹 수정 금지.** 새 화면은 새 프리팹으로 만든다.",
        "- **템플릿을 인스턴스로 넣는다.** 같은 모양을 Image·TMP 로 다시 조립하지 않는다. 없으면 '새로 만들 것' 목록에 적고 승인받는다.",
        "- **새 스프라이트 금지 · 토큰 밖 색 금지.** 색은 `ui-audit/data/tokens/color.json` 의 값만(현재 전부 `미검토` — 아래 참고).",
        "- `standard` 가 `폐기→X` 면 X 를 쓴다. `미정` 이면 후보를 고른 근거를 조합안에 적고 사람 확인을 받는다.",
        "- 커밋은 사람이 승인한다.",
        "",
        "## 많이 쓰는 템플릿 상위 %d" % TOP_TABLE,
    ]
    L += top_table(rows)
    L += [
        "",
        "## 표준 미정 지점 (판단하지 말고 조합안에 표시)",
    ]
    L += open_points(rows, color_tokens)
    L += [
        "",
        "## 집계",
        "- standard: %s" % " · ".join("%s %d" % kv for kv in sorted(std.items(), key=lambda kv: -kv[1])),
        "- 썸네일 있음 %d / %d · 복붙 사본 경고 있음 %d · role 파일 %s" % (
            n_th, len(rows), n_lk, "있음" if roles_present else "없음(`ui-audit/ds/roles.json`, P1-2 에서 만든다)"),
        "",
        "## 원본 데이터 위치 (로컬 `ui-audit/` — gitignore, 팀에 공유되지 않음)",
        "- 템플릿 상세(사용처 목록·오버라이드·유사품): `ui-audit/data/templates/<slug>.json`, 목록 `ui-audit/data/template-index.json`",
        "- 화면·템플릿 배치(노드 좌표): `ui-audit/data/layout/<screen|template>/<slug>.json`",
        "- 앱 → 화면 흐름: `ui-audit/data/app-flow.json` · 토큰 초안: `ui-audit/data/tokens/<종류>.json`",
        "- 렌더: `ui-audit/previews/templates/<slug>.png`, `ui-audit/previews/layout/<screen|template>/<slug>.png`",
        "- 사람이 보는 탐색기: `ui-audit/catalog/app-flow.html`(홈) · `catalog/map/<screen>.html` · `catalog/templates/<slug>.html`",
        "- 이 경로들이 없는 PC 에서는 이 폴더(`Docs/ui-design-system/`)만 쓸 수 있다.",
        "",
        "## 작업 지시 템플릿 (사용자 → 에이전트)",
        "```",
    ]
    L += list(DP.INSTRUCTION_TEMPLATE)
    L += [
        "```",
        "작업 순서와 사람 확인 지점은 [`SKILL.md`](SKILL.md).",
        "",
        "## 다시 만들기",
        "갱신·공유 절차(누가·언제·순서·커밋 allowlist·주의)는 [`UPDATE.md`](UPDATE.md).",
        "```",
        "cd ui-audit",
        "python scripts/ds_publish.py --plan   # 무엇을 다시 돌려야 하나(전체 재생성 / 색인만 / 할 일 없음)",
        "python scripts/ds_index.py --run      # templates.jsonl · screens.jsonl · INDEX.md · UPDATE.md · SKILL.md 재생성",
        "python scripts/ds_index.py --check    # 현재 데이터와 일치·경로 존재 확인",
        "```",
        "데이터 자체를 새로 만드는 순서는 `ui-audit/reports/FINAL.md` 5·7절.",
    ]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 실행
def gather():
    idx = C.load_json(C.p("data", "template-index.json"))
    if not idx:
        raise SystemExit("data/template-index.json 없음 — templates.py --select 가 먼저 필요")
    temps = [C.load_json(C.p("data", "templates", s + ".json")) for s in idx["templates"]]
    missing = [s for s, t in zip(idx["templates"], temps) if t is None]
    if missing:
        raise SystemExit("data/templates 에 없는 slug %d개: %s" % (len(missing), ", ".join(missing[:5])))
    decisions = C.load_json(C.p("decisions.json"), [])
    roles = load_roles(C.p("ds", "roles.json"))
    screen_names = {s["slug"]: s["name"] for s in idx["screens"]}
    colors = (C.load_json(C.p("data", "tokens", "color.json")) or {"tokens": []})["tokens"]
    avoid = completely_outputs()
    rows = build_rows(temps, decisions, roles, screen_instance_counts(), screen_names, avoid=avoid)
    layouts, tlayouts, flow = DSS.load_inputs()
    screens = DSS.build_rows(layouts, temps, tlayouts, avoid, flow, CT.flow_levels)
    return idx, rows, colors, roles is not None, screens


def outputs(idx, rows, colors, roles_present, screens):
    return (("templates.jsonl", jsonl(rows)), ("screens.jsonl", DSS.jsonl(screens)),
            ("INDEX.md", render_index(rows, idx, colors, roles_present, screens)),
            ("UPDATE.md", DP.render_update()), ("SKILL.md", DP.render_skill()))


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def run():
    idx, rows, colors, roles_present, screens = gather()
    od = out_dir()
    for name, text in outputs(idx, rows, colors, roles_present, screens):
        write_text(os.path.join(od, name), text)
    std = collections.Counter(r["standard"] for r in rows)
    print("색인: %s — templates.jsonl %d줄 · 썸네일 %d · 사본 경고 %d · standard %s · role %s" % (
        od, len(rows), sum(1 for r in rows if r["thumbnail"]), sum(1 for r in rows if r["lookalikeWarning"]),
        dict(std), "있음" if roles_present else "없음"))
    clean = collections.Counter(s["cleanReference"] for s in screens)
    print("screens.jsonl %d줄 · cleanReference true %d / false %d · recipe %s · 사본 있는 화면 %d · app 있음 %d" % (
        len(screens), clean[True], clean[False], dict(collections.Counter(s["recipe"] for s in screens)),
        sum(1 for s in screens if s["lookalikeCopies"]), sum(1 for s in screens if s["app"])))
    return 0


def check():
    idx, rows, colors, roles_present, screens = gather()
    od = out_dir()
    bad = 0
    for name, want in outputs(idx, rows, colors, roles_present, screens):
        path = os.path.join(od, name)
        have = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        state = "없음" if have is None else ("일치" if have == want else "불일치(--run 필요)")
        bad += state != "일치"
        print("%s: %s" % (name, state))
    n_idx = len(idx["templates"])
    print("행 수 %d / template-index %d %s" % (len(rows), n_idx, "OK" if len(rows) == n_idx else "불일치"))
    repo = os.path.dirname(os.path.dirname(od))
    th = sum(1 for r in rows if r["thumbnail"] and os.path.exists(os.path.join(repo, r["thumbnail"])))
    cat = sum(1 for r in rows if os.path.exists(os.path.join(repo, r["catalog"])))
    print("thumbnail 경로 존재 %d / %d (null %d) · catalog 페이지 존재 %d / %d" % (
        th, len(rows), sum(1 for r in rows if not r["thumbnail"]), cat, len(rows)))
    n_lay = len(C.iter_json(C.p("data", "layout", "screen")))
    print("screens 행 수 %d / 화면 배치 %d %s" % (len(screens), n_lay, "OK" if len(screens) == n_lay else "불일치"))
    mp = sum(1 for s in screens if os.path.exists(os.path.join(repo, s["map"])))
    im = sum(1 for s in screens if s["image"] and os.path.exists(os.path.join(repo, s["image"])))
    print("map 페이지 존재 %d / %d · image 경로 존재 %d / %d (null %d)" % (
        mp, len(screens), im, len(screens), sum(1 for s in screens if not s["image"])))
    return 1 if bad or len(rows) != n_idx or len(screens) != n_lay else 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.run:
        return run()
    if a.check:
        return check()
    ap.print_help()
    return 2


# ---------------------------------------------------------------- 자체 테스트
def selftest():
    with TS.test_scope():
        return _selftest()


def _selftest():
    import tempfile

    def T(slug, name, usage, screens, path=None, **kw):
        t = {"slug": slug, "name": name, "path": path or "Assets/Game/UI/Contents/Shop/X/%s.prefab" % name,
             "guid": "g-" + slug, "address": None, "tier": "atom", "kind": "button", "usageTotal": usage,
             "screens": screens, "contains": [], "overrides": None, "lookalikes": None, "thumbnail": None}
        t.update(kw)
        return t
    ov = {"styledRate": 0.25, "topProps": [["a", 9], ["b", 8], ["c", 7], ["d", 6], ["e", 5], ["f", 4]]}
    lk = [{"node": "P.prefab#P/A/Copy", "screen": "shopview", "score": 0.9, "match": "near"},
          {"node": "Q.prefab#Q/B/Copy", "screen": "bagview", "score": 1.0, "match": "exact"},
          {"node": "R.prefab#R/C", "screen": "rview", "score": 0.7, "match": "borderline"}]
    temps = [T("small", "Small", 2, ["shopview"]),
             T("big", "Big", 50, ["shopview", "bagview", "aview", "zview"], path="Assets/Game/UI/Common/Big.prefab",
               tier="composite", contains=["small"], overrides=ov, lookalikes=lk, thumbnail="previews/templates/big.png",
               address="UI_Big_prefab"),
             T("tie-b", "TieB", 10, ["aview"]), T("tie-a", "TieA", 10, ["aview"]),
             T("onlyborder", "OnlyBorder", 1, [], lookalikes=[lk[2]], thumbnail="previews/templates/gone.png")]
    decisions = [{"by": "user", "target": "big", "status": "표준", "to": None},
                 {"by": "agent", "target": "small", "status": "표준", "to": None},           # agent 결정은 무시
                 {"by": "user", "target": "g-tie-a", "status": "표준", "to": None},
                 {"by": "user", "target": "template:tie-a", "status": "폐기", "to": "template:big"},  # 나중 user 결정이 이긴다
                 {"by": "agent", "target": "tie-b", "status": "폐기", "to": None}]
    counts = {"big": {"zview": [5, 0], "bagview": [1, 7], "aview": [1, 2]}}
    names = {"shopview": "ShopView", "bagview": "BagView", "aview": "AView", "zview": "ZView"}
    exists = lambda path: path.endswith("big.png")  # noqa: E731
    with tempfile.TemporaryDirectory(prefix="ds-index-") as d:
        roles_path = os.path.join(d, "ds", "roles.json")
        assert load_roles(roles_path) is None and not os.path.exists(os.path.join(d, "ds")), "roles 파일·폴더를 만들면 안 됨"
        rows = build_rows(temps, decisions, None, counts, names, exists)
        assert [r["slug"] for r in rows] == ["big", "tie-a", "tie-b", "small", "onlyborder"], [r["slug"] for r in rows]
        by = {r["slug"]: r for r in rows}
        assert list(by["big"]) == list(FIELD_ORDER) and list(by["big"])[0] == "name"
        assert by["big"]["standard"] == "표준" and by["small"]["standard"] == UNDECIDED, "agent 결정은 standard 가 아님"
        assert by["tie-a"]["standard"] == "폐기→big" and by["tie-b"]["standard"] == UNDECIDED
        assert all(r["role"] is None for r in rows)
        big = by["big"]
        assert big["topProps"] == [["a", 9], ["b", 8], ["c", 7], ["d", 6], ["e", 5]] and big["styledRate"] == 0.25
        assert big["sampleScreens"] == ["ZView", "BagView", "AView"], big["sampleScreens"]  # 정적 5 > 1(예시 7) > 1(예시 2)
        assert big["lookalikeWarning"].startswith("exact 1 · near 1 (화면 2) — 대표 사본: bagview#Q/B/Copy"), big["lookalikeWarning"]
        assert by["onlyborder"]["lookalikeWarning"] is None and by["small"]["lookalikeWarning"] is None
        assert big["folder"] == "common" and by["small"]["folder"] == "Shop" and big["contains"] == ["small"]
        assert big["thumbnail"] == "ui-audit/previews/templates/big.png" and by["onlyborder"]["thumbnail"] is None
        assert big["catalog"] == "ui-audit/catalog/templates/big.html" and big["address"] == "UI_Big_prefab"
        assert by["small"]["sampleScreens"] == ["ShopView"] and by["onlyborder"]["sampleScreens"] == []
        assert sample_screens(temps[1], counts, names, {"ZView"}) == ["BagView", "AView", "ShopView"]  # 반면교사 화면 제외
        ed = os.path.join(d, "Editor")
        os.makedirs(ed)
        with open(os.path.join(ed, "XBuildTool.cs"), "w", encoding="utf-8") as f:
            f.write('const string Src = "Assets/UI/Src/SrcView.prefab";\nconst string Out = Folder + "/XView.prefab";\n'
                    'PrefabUtility.UnpackPrefabInstance(r, PrefabUnpackMode.Completely, a);\n')
        with open(os.path.join(ed, "YBuildTool.cs"), "w", encoding="utf-8") as f:
            f.write('const string Out = Folder + "/YView.prefab";\nPrefabUtility.LoadPrefabContents(p);\n')
        assert completely_outputs(ed) == {"XView"}, completely_outputs(ed)
        text = jsonl(rows)
        assert text.count("\n") == 5 and text.startswith('{"name":"Big","slug":"big"'), text[:60]
        assert all(json.loads(line)["slug"] for line in text.splitlines())
        os.makedirs(os.path.dirname(roles_path))
        with open(roles_path, "w", encoding="utf-8") as f:
            json.dump({"big": "primary-button"}, f)
        roles = load_roles(roles_path)
        rows2 = build_rows(temps, decisions, roles, counts, names, exists)
        assert rows2[0]["role"] == "primary-button" and rows2[1]["role"] is None
        idx = {"updatedAt": "2026-01-01", "screens": [{"slug": s} for s in names]}
        colors = [{"id": "color-1a2b", "status": "미검토"}, {"id": "ink", "status": "표준"}]
        scr = [{"name": "AView", "slug": "aview", "kind": "View", "recipe": "list-tab", "cleanReference": True},
               {"name": "BPopup", "slug": "bpopup", "kind": "Popup", "recipe": "none", "cleanReference": False}]
        md = render_index(rows2, idx, colors, True, scr)
        assert "3. [`screens.jsonl`](screens.jsonl) — 화면 2줄" in md
        assert "%d. [`templates.jsonl`]" % (5 if DP.CHECKLIST else 4) in md
        assert "## screens.jsonl 필드" in md and "cleanReference true 1 / false 1 · recipe list-tab 1 · none 1" in md
        assert "**참고 화면은 `screens.jsonl` 의 `cleanReference=true` 에서 고른다.**" in md
        assert "사본 ≤%d 이고" % DSS.COPY_TOLERANCE in md and "`looseButtons` 는 판정에 넣지 않는다" in md
        ex = [x for x in md.splitlines() if x.startswith("grep -E '\"kind\":\"Popup\"")][0]
        pat1, pat2 = re.findall(r"grep -E '([^']+)'", ex)
        good = DSS.jsonl([{"name": "P", "kind": "Popup", "templates": {"filtergroup": 1, "button-yellow": 2},
                           "cleanReference": True}])
        bad = good.replace('"cleanReference":true', '"cleanReference":false')
        assert re.search(pat1, good) and re.search(pat2, good) and not re.search(pat2, bad), "INDEX 의 grep 예가 동작해야 함"
        assert "button-yellow-new" not in pat1 and "(현재 0건)" in md
        assert pair_hits([json.loads(good), dict(json.loads(good), kind="View"), json.loads(bad)], "filtergroup", "button-yellow") == 1
        assert [n for n, _t in outputs(idx, rows2, colors, True, scr)] == [
            "templates.jsonl", "screens.jsonl", "INDEX.md", "UPDATE.md", "SKILL.md"]
        assert "[`SKILL.md`](SKILL.md)" in md and "[`UPDATE.md`](UPDATE.md)" in md and "ds_publish.py --plan" in md
        assert md.index("[`SKILL.md`]") < md.index("1. 이 파일") and all(x in md for x in DP.INSTRUCTION_TEMPLATE)
        assert "| 1 | Big | `big` | composite | button | 50 | 4 | 25% | 표준 | ZView, BagView, AView |" in md
        assert "색 토큰**: 2개" in md and "해시(`color-xxxx`)인 것 1개" in md and "role 이 있는 템플릿 1 / 5" in md
        assert "`button-yellow` 없음" in md and "skeletons.md" in md and "Completely" in md
        assert "LoadPrefabContents" in md and "OutermostRoot" in md
    print("ds_index.py selftest ok · %s" % DSS.selftest())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
