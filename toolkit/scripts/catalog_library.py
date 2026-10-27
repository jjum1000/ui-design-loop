"""하단 도크 라이브러리 · 키 데이터 생성기 (N1, M2).

정본 = ui-audit/feedback/CONTRACT.md 7.4(필드표가 이 스크립트의 산출물 계약), 1·2·4.4(등록부·크롭 샷
규칙·소스 위치 grep 규칙 — 이 스크립트는 그 규칙을 독립적으로 다시 구현한다. feedback.py·feedback_core.py 는
다른 태스크가 동시에 고치고 있어 import 하지 않는다).

산출(모두 정적, `file://` 에서도 <script src> 로 읽힌다 — 7.4):
  catalog/library/index.js · index.json   슬러그 213개 메타 + 키트 대응 + 대안(alts) + 묶음(groups)
  catalog/library/<slug>.js (213개)        슬러그별 노드 트리(레이아웃 상자) + 키트 행 + 규칙 발췌 + 쓰는 화면
  catalog/library/keys-<Screen>.js         등록부 화면마다: (stage,version) × state 별 data-area 키 현황
  catalog/library/crops/<Screen>/<stage>-<version>/<state>/<area>.png   키 크롭 썸네일

사용(ui-audit/ 에서):
  python scripts/catalog_library.py --build [--screen S] [--no-keys]
  python scripts/catalog_library.py --selftest

한계 / 판단한 지점(오케스트레이터 보고 ③과 동일 — 코드에도 남겨 둔다):
- 키트 대응표(`<kit_dir>/components.md`)·규칙(`<kit_dir>/rules.md`)은 project.json `design.kit_dir`(기본 `design/kit`)
  한 곳에서 읽는다(화면별이 아니다). 다른 화면이 등록부에 생겨도 키트 데이터는 이 두 파일에서만 온다.
- `index.json`의 `templates` 딕셔너리는 슬러그 알파벳순으로 정렬해 쓴다 — 계약은 순서를 규정하지 않고,
  소비자는 키로 찾으므로 의미상 무해하다(디버깅 편의를 위한 판단).
- JSON/JS 는 `catalog_templates.py` 의 선례를 따라 `separators=(",", ":")` 압축 포맷으로 쓴다 — 계약은
  `ensure_ascii=False`·`</` 이스케이프만 요구하고 들여쓰기는 규정하지 않는다. 512 KiB 상한을 지키는 데도
  유리하다.
- `<slug>.js` 의 512 KiB 상한 초과 시 depth 가 가장 깊은 티어부터 통째로 버린다(`truncated.maxDepth` =
  버리고 남은 노드 중 가장 깊은 depth). `index.js`/`index.json`/`keys-<Screen>.js` 에는 계약이 이 상한을
  규정하지 않아(7.4 는 `<slug>.js` 절에서만 언급) 적용하지 않는다 — 실제 크기는 보고만 한다.
- `keys` 의 `크롭` 은 `data-area` 값이 안전한 파일명 패턴(`^[a-z0-9][a-z0-9-]*$`)일 때만 만든다. 그 밖엔
  `crop: null`(키 자체는 그대로 보고).
- 상태 진입(헤드리스)은 등록부 `states[].steps` 를 `page.evaluate` 로 "함수 이름 존재 확인 → 인자를 JSON
  으로 건네 호출"하는 두 단계로만 한다(eval 문자열 조립 금지 — feedback.py 의 동일 규칙을 독립 구현).
- registry 의 `files`(글롭 포함)·`entry` 는 ui-audit 루트 밖을 가리키면(절대경로·`..`·드라이브 문자·역슬래시)
  거부한다 — `files` 글롭은 조용히 건너뛰고(소스 위치 grep 은 최선 노력 표시), `entry` 는 그 target 의
  모든 state 를 `error` 로 남기고 계속한다(한 화면/타깃 실패가 전체 빌드를 막지 않는다).
"""
import argparse
import collections
import fnmatch
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

MAX_FILE_BYTES = 512 * 1024
CROP_MARGIN = 8
CROP_MAX_SIDE = 320
VIEWPORT = {"width": 1920, "height": 1080}
AREA_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SCREEN_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")  # keys-<Screen>.js 파일명에 쓰기 전 검사(R4 HIGH1)
KIT_DIR = ((C.project() or {}).get("design") or {}).get("kit_dir", "design/kit")  # 디자인 키트 폴더(ui-audit 기준)
KIT_COMPONENTS_REL = KIT_DIR + "/components.md"
KIT_RULES_REL = KIT_DIR + "/rules.md"
RULES_MAX = 8
SRC_MAX = 5
SCREENS_CAP = 8
IDX_MAX = 50


def out_root():
    return C.p("catalog", "library")


# ================================================================ 경로 안전
def _safe_rel(rel, what="경로"):
    """registry 의 상대 경로 문자열(files·entry) 검사 — 루트를 벗어날 수 있는 형태를 거부한다."""
    if not rel or "\\" in rel:
        raise ValueError("안전하지 않은 %s(역슬래시/빈 값 금지): %r" % (what, rel))
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise ValueError("안전하지 않은 %s(절대/드라이브 경로 금지): %r" % (what, rel))
    if any(seg in ("", ".", "..") for seg in rel.split("/")):
        raise ValueError("안전하지 않은 %s(.. 세그먼트 금지): %r" % (what, rel))
    return rel


def _safe_registry_abs(rel, what="경로"):
    _safe_rel(rel, what)
    joined = C.p(*rel.split("/"))
    root_real = os.path.realpath(C.ROOT)
    full_real = os.path.realpath(joined)
    try:
        inside = os.path.commonpath([root_real, full_real]) == root_real
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("안전하지 않은 %s(ui-audit 루트 밖): %r" % (what, rel))
    return joined


def _safe_out(*parts):
    """catalog/library/ 밖으로 못 나가게 — realpath 컨테인먼트 확인 뒤 조인된 경로를 돌려준다."""
    base = os.path.realpath(out_root())
    joined = os.path.join(out_root(), *parts)
    real = os.path.realpath(joined)
    try:
        inside = os.path.commonpath([base, real]) == base
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("안전하지 않은 출력 경로: %r" % (parts,))
    return joined


def _atomic_write(path, text, binary=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    if binary:
        with open(tmp, "wb") as f:
            f.write(text)
    else:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    try:
        os.replace(tmp, path)
    except OSError:
        # R4 LOW2 — os.replace 실패 시(권한·동시 접근 등) .tmp 고아를 남기지 않고 지운 뒤 재발생
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _dump_compact(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _js_escape(json_text):
    """JS `<script>` 안에 안전하게 넣기 위한 이스케이프: `</` 탈출 방지 + U+2028/U+2029(JS 가 문자열
    리터럴 안에서도 줄바꿈으로 취급해 파싱을 깨는 LINE/PARAGRAPH SEPARATOR) 이스케이프(R4 LOW1)."""
    return (json_text.replace("</", "<\\/")
            .replace(" ", "\\u2028")
            .replace(" ", "\\u2029"))


def _byte_len(text):
    return len(text.encode("utf-8"))


# ================================================================ registry files 확장·grep(4.4 규칙 독립 구현)
def _expand_files(patterns):
    out = []
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            if "/" in pat:
                d, base_pat = pat.rsplit("/", 1)
            else:
                d, base_pat = "", pat
            try:
                if d:
                    _safe_rel(d, "files 글롭 경로")
            except ValueError:
                continue
            dirpath = C.p(*d.split("/")) if d else C.p()
            if os.path.isdir(dirpath):
                for name in sorted(os.listdir(dirpath)):
                    full = os.path.join(dirpath, name)
                    if os.path.isfile(full) and fnmatch.fnmatch(name, base_pat):
                        out.append((d + "/" + name) if d else name)
        else:
            try:
                _safe_rel(pat, "files")
            except ValueError:
                continue
            out.append(pat)
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _grep_src(files, area, limit=SRC_MAX):
    """registry files 안에서 data-area="<area>" 또는 '<area>'/"<area>" 를 찾아 경로:줄 목록(최대 limit)."""
    pat1 = re.compile(r'data-area\s*=\s*["\']%s["\']' % re.escape(area))
    pat2 = re.compile(r'''(['"])%s\1''' % re.escape(area))
    hits = []
    for rel in files:
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


# ================================================================ 템플릿 인덱스·메타
def _load_valid_slugs():
    """-> (valid: slug 패턴(C.SLUG_RE) 통과분만 정렬, skipped: 걸러진 원본 값 정렬).
    R4 HIGH1 — 패턴을 안 지키는 슬러그(예: '/'·'..' 가 섞인 값)는 파일명으로 쓸 때 _safe_out 이
    예외를 내므로, 아예 여기서 걸러 index·<slug>.js 생성 대상에서 제외한다(한 항목의 결함이
    나머지 212개를 막지 않게)."""
    idx = C.load_json(C.p("data", "template-index.json")) or {}
    raw = set(idx.get("templates") or [])
    valid = sorted(s for s in raw if C.SLUG_RE.match(s))
    skipped = sorted(raw - set(valid))
    return valid, skipped


def _load_template_meta(slug):
    return C.load_json(C.p("data", "templates", "%s.json" % slug))


def _load_layout(slug):
    return C.load_json(C.p("data", "layout", "template", "%s.json" % slug))


def _thumb_path(slug, meta):
    cand_rel = "previews/layout/template/%s.thumb.png" % slug
    if os.path.isfile(C.p(*cand_rel.split("/"))):
        return cand_rel
    thumb = (meta or {}).get("thumbnail")
    if thumb and os.path.isfile(C.p(*thumb.split("/"))):
        return thumb
    return None


def _page_path(slug):
    rel = "catalog/templates/%s.html" % slug
    return rel if os.path.isfile(C.p(*rel.split("/"))) else None


def _screens_for(meta):
    out = []
    for s in (meta or {}).get("screens", [])[:SCREENS_CAP]:
        rel = "catalog/screens/%s.html" % s
        out.append({"slug": s, "page": rel if os.path.isfile(C.p(*rel.split("/"))) else None})
    return out


# ================================================================ 키트 대응표(components.md 첫 테이블)
BACKTICK_RE = re.compile(r"`([^`]+)`")
SEP_ROW_RE = re.compile(r"^\|[\s:\-|]+\|$")


def _table_rows(cells_line):
    parts = cells_line.split("|")
    if parts and parts[0].strip() == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [c.strip() for c in parts]


def _parse_kit_rows(path):
    """components.md 의 **첫** 마크다운 테이블(묶음·요소·시안클래스/파일·Unity템플릿slug/원본·
    사용수/화면수·9-slice·비고 7칸)을 데이터 행 목록으로 돌려준다. 파일이 없으면 []."""
    if not os.path.isfile(path):
        return []
    lines = open(path, encoding="utf-8").read().splitlines()
    i = 0
    while i < len(lines) and not lines[i].startswith("|"):
        i += 1
    if i >= len(lines):
        return []
    i += 1  # 헤더 행
    if i < len(lines) and SEP_ROW_RE.match(lines[i]):
        i += 1  # 구분선 행
    rows = []
    while i < len(lines) and lines[i].startswith("|"):
        cells = _table_rows(lines[i])
        if len(cells) >= 7:
            rows.append({"group": cells[0], "element": cells[1], "kitClass": cells[2],
                         "slugCell": cells[3], "usage": cells[4], "slice": cells[5], "note": cells[6]})
        i += 1
    return rows


def _row_slugs(cell, valid_slugs):
    """셀 안 백틱 토큰 중 slug 패턴 + 템플릿 인덱스 실존인 것만(스프라이트 경로·'없음' 은 자연히 제외)."""
    found = []
    for m in BACKTICK_RE.finditer(cell):
        tok = m.group(1).strip()
        if C.SLUG_RE.match(tok) and tok in valid_slugs:
            found.append(tok)
    return found


def _build_kit_maps(rows, valid_slugs):
    """-> (kit_index: slug->[{group,element,kitClass}], kit_full: slug->[{...,slugs,usage,slice,note}],
    groups: group->set(slug))"""
    kit_index = collections.defaultdict(list)
    kit_full = collections.defaultdict(list)
    groups = collections.defaultdict(set)
    for row in rows:
        slugs = _row_slugs(row["slugCell"], valid_slugs)
        if not slugs:
            continue
        for s in slugs:
            kit_index[s].append({"group": row["group"], "element": row["element"], "kitClass": row["kitClass"]})
            kit_full[s].append({"group": row["group"], "element": row["element"], "kitClass": row["kitClass"],
                                 "slugs": list(slugs), "usage": row["usage"], "slice": row["slice"],
                                 "note": row["note"]})
            groups[row["group"]].add(s)
    return kit_index, kit_full, groups


def _alts_for(slug, kit_index, groups, usage_of):
    my_groups = {e["group"] for e in kit_index.get(slug, [])}
    pool = set()
    for g in my_groups:
        pool |= groups.get(g, set())
    pool.discard(slug)
    return sorted(pool, key=lambda s: (-usage_of.get(s, 0), s))


# ================================================================ 규칙 발췌(rules.md)
def _rules_excerpt(slug, rules_lines, max_n=RULES_MAX):
    pat1 = re.compile(r"`%s`" % re.escape(slug))
    pat2 = re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(slug))
    out = []
    for i, line in enumerate(rules_lines, 1):
        if pat1.search(line) or pat2.search(line):
            out.append({"file": KIT_RULES_REL, "line": i, "text": line.strip()[:300]})
            if len(out) >= max_n:
                break
    return out


# ================================================================ index.json/js
def _build_index(valid_slugs, kit_index, kit_full, groups, meta_by_slug, layout_slugs):
    usage_of = {s: (meta_by_slug.get(s) or {}).get("usageTotal", 0) for s in valid_slugs}
    templates = {}
    for slug in valid_slugs:
        meta = meta_by_slug.get(slug)
        templates[slug] = {
            "name": (meta or {}).get("name") or slug,
            "thumb": _thumb_path(slug, meta),
            "usage": (meta or {}).get("usageTotal", 0),
            "screens": len((meta or {}).get("screens", []) or []),
            "tier": (meta or {}).get("tier"),
            "kind": (meta or {}).get("kind"),
            "page": _page_path(slug),
            "layout": slug in layout_slugs,
            "groups": sorted({e["group"] for e in kit_index.get(slug, [])}),
            "kit": kit_index.get(slug, []),
            "alts": _alts_for(slug, kit_index, groups, usage_of),
        }
    groups_out = {g: sorted(slugs, key=lambda s: (-usage_of.get(s, 0), s)) for g, slugs in groups.items()}
    return {"generatedAt": C.now_iso(), "templates": templates, "groups": groups_out}


# ================================================================ <slug>.js (노드 트리 + 키트 + 규칙 + 화면)
def _node_list(layout, valid_slugs):
    nodes = []
    for b in (layout or {}).get("boxes", []):
        tmpl = b.get("template")
        if tmpl and tmpl not in valid_slugs:
            tmpl = None
        nodes.append({
            "id": b.get("id"), "name": b.get("name"), "path": b.get("path"), "depth": b.get("depth", 0),
            "x": int(round(b.get("x", 0))), "y": int(round(b.get("y", 0))),
            "w": int(round(b.get("w", 0))), "h": int(round(b.get("h", 0))),
            "template": tmpl, "active": bool(b.get("active", True)),
        })
    return nodes


def _slug_js_text(slug, payload):
    body = _js_escape(_dump_compact(payload))
    return "window.UIA_LIB = window.UIA_LIB || {};\nwindow.UIA_LIB[%s] = %s;\n" % (json.dumps(slug), body)


def _fit_slug_payload(slug, base_fields, nodes_full, kit_full_list, rules_full_list):
    """512 KiB 상한에 맞춰 단계적으로 줄인다(R4 HIGH2 — 이전 버전은 depth 티어가 하나뿐이거나 노드가
    1개뿐이면 아무것도 못 줄이고 초과분을 조용히 truncated=None 으로 돌려주는 결함이 있었다):
      1단계: depth 가 가장 깊은 티어부터 통째로 버린다(노드가 남아 있는 동안, 매번 재측정).
      2단계: 그래도(또는 처음부터 노드가 없는데도) 넘으면 kit 행을 뒤에서부터, 이어서 rules 발췌를
             뒤에서부터 하나씩 버린다 — kit·rules 는 nodes 와 달리 title/path 수준의 부가 정보라
             전부 비워도(화면 식별 자체인 slug·name·path·size 는 건드리지 않음) 원래 목적(노드 트리
             열람)에 지장이 적다고 판단했다.
      3단계: 그래도 넘으면(= slug·name·path·size·screens 자체가 비대한 극단 상황) `overflow: true` 를
             truncated 에 남기고 **그대로 쓴다**(조용히 포기하지 않음 — 호출자가 경고를 찍는다).
    (text, truncated) 를 돌려준다. 아무것도 줄이지 않았으면 truncated=None."""
    total_nodes = len(nodes_full)

    def make(nodes, kit, rules, extra):
        payload = dict(base_fields)
        payload["nodes"] = nodes
        payload["kit"] = kit
        payload["rules"] = rules
        payload["truncated"] = extra
        return payload

    nodes = nodes_full
    kit = kit_full_list
    rules = rules_full_list
    text = _slug_js_text(slug, make(nodes, kit, rules, None))
    if _byte_len(text) <= MAX_FILE_BYTES:
        return text, None

    truncated = None
    if nodes:
        depths = sorted({n["depth"] for n in nodes}, reverse=True)
        for cut in depths:
            candidate = [n for n in nodes if n["depth"] < cut]
            if len(candidate) == len(nodes):
                continue  # 이 depth 에 노드가 이미 없음(선행 cut 에서 같이 빠짐) — 건너뜀
            nodes = candidate
            remaining = {n["depth"] for n in nodes}
            truncated = {"kept": len(nodes), "dropped": total_nodes - len(nodes),
                         "maxDepth": max(remaining) if remaining else -1}
            text = _slug_js_text(slug, make(nodes, kit, rules, truncated))
            if _byte_len(text) <= MAX_FILE_BYTES:
                return text, truncated
    # 노드를 전부 버려도(또는 nodes_full 이 원래 비어 있었는데도) 넘음 — kit·rules 를 줄인다.
    if truncated is None:
        truncated = {"kept": 0, "dropped": total_nodes, "maxDepth": -1}
    while kit and _byte_len(text) > MAX_FILE_BYTES:
        kit = kit[:-1]
        truncated["kitDropped"] = len(kit_full_list) - len(kit)
        text = _slug_js_text(slug, make(nodes, kit, rules, truncated))
    while rules and _byte_len(text) > MAX_FILE_BYTES:
        rules = rules[:-1]
        truncated["rulesDropped"] = len(rules_full_list) - len(rules)
        text = _slug_js_text(slug, make(nodes, kit, rules, truncated))
    if _byte_len(text) > MAX_FILE_BYTES:
        truncated["overflow"] = True  # slug/name/path/size/screens 자체가 비대 — 더 줄일 필드가 없음
        text = _slug_js_text(slug, make(nodes, kit, rules, truncated))
    return text, truncated


def _build_slug_file(slug, meta, layout, valid_slugs, kit_full, rules_lines):
    nodes_full = _node_list(layout, valid_slugs)
    base_fields = {
        "slug": slug,
        "name": (meta or {}).get("name") or slug,
        "path": (meta or {}).get("path"),
        "size": ({"w": int(round(layout.get("width", 0))), "h": int(round(layout.get("height", 0)))}
                 if layout else None),
        "screens": _screens_for(meta),
    }
    kit_full_list = kit_full.get(slug, [])
    rules_full_list = _rules_excerpt(slug, rules_lines)
    return _fit_slug_payload(slug, base_fields, nodes_full, kit_full_list, rules_full_list)


# ================================================================ 헤드리스 상태 진입(steps) — eval 금지, 함수명 조회 + apply
def _run_steps(page, steps):
    for step in steps or []:
        call = step.get("call")
        args = step.get("args", [])
        optional = bool(step.get("optional"))
        try:
            exists = page.evaluate("(n) => typeof window[n] === 'function'", call)
        except Exception as e:
            return (True, None) if optional else (False, "함수 조회 실패(%s): %s" % (call, e))
        if not exists:
            if optional:
                continue
            return False, "함수 없음: %s" % call
        try:
            page.evaluate("(a) => window[a.name].apply(null, a.args)", {"name": call, "args": args})
        except Exception as e:
            if optional:
                continue
            return False, "%s 호출 실패: %s" % (call, e)
    return True, None


KEYS_JS = r"""
() => {
  function visible(el) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  const keys = {};
  for (const el of document.querySelectorAll('[data-area]')) {
    if (!visible(el)) continue;
    const k = el.getAttribute('data-area');
    if (!keys[k]) {
      const r = el.getBoundingClientRect();
      let parent = null, p = el.parentElement;
      while (p) {
        if (p.hasAttribute && p.hasAttribute('data-area')) { parent = p.getAttribute('data-area'); break; }
        p = p.parentElement;
      }
      keys[k] = {
        template: el.getAttribute('data-template') || null,
        variant: el.getAttribute('data-variant') || null,
        new: el.getAttribute('data-new') || null,
        count: 0, idx: [], parent: parent,
        bbox: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}
      };
    }
    keys[k].count++;
    const idxv = el.getAttribute('data-idx');
    if (idxv != null && keys[k].idx.length < %d) keys[k].idx.push(idxv);
  }
  return {keys, doc: {w: document.documentElement.scrollWidth, h: document.documentElement.scrollHeight}};
}
""" % IDX_MAX


def _crop_png(page, bbox, doc, margin=CROP_MARGIN, max_side=CROP_MAX_SIDE):
    x0 = max(0, bbox["x"] - margin)
    y0 = max(0, bbox["y"] - margin)
    x1 = min(doc["w"], bbox["x"] + bbox["w"] + margin)
    y1 = min(doc["h"], bbox["y"] + bbox["h"] + margin)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return None
    try:
        png = page.screenshot(clip={"x": x0, "y": y0, "width": w, "height": h})
    except Exception:
        return None
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png))
        iw, ih = img.size
        if max(iw, ih) > max_side:
            scale = max_side / max(iw, ih)
            img = img.resize((max(1, round(iw * scale)), max(1, round(ih * scale))), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png = buf.getvalue()
    except Exception:
        pass  # 축소 실패해도 원본 크롭은 유지
    return png


def _write_crop(screen, stage, version, state_id, area, png):
    rel = "catalog/library/crops/%s/%s-%s/%s/%s.png" % (screen, stage, version, state_id, area)
    try:
        path = _safe_out("crops", screen, "%s-%s" % (stage, version), state_id, "%s.png" % area)
    except ValueError:
        return None
    try:
        _atomic_write(path, png, binary=True)
    except OSError:
        return None
    return rel


# ================================================================ keys-<Screen>.js
def _keymap_for(scr):
    stages = scr.get("stages") or []
    if not stages:
        return None, {}
    entry = stages[0].get("entry", "")
    parts = entry.split("/")
    if len(parts) < 2:
        return None, {}
    rel = "/".join(parts[:-1]) + "/keymap.json"
    try:
        full = _safe_registry_abs(rel, "keymap 경로")
    except ValueError:
        return None, {}
    data = C.load_json(full)
    if data is None:
        return None, {}
    return rel, dict(data.get("map") or {})


def _build_mockup_use(targets, keymap_map, scr):
    mockup_entries = [se for se in (scr.get("stages") or []) if se.get("stage") == "mockup"]
    if not mockup_entries:
        return {}
    default = mockup_entries[0]
    version = default.get("version")
    mkey = "mockup/%s" % version
    mtarget = targets.get(mkey)
    if not mtarget:
        return {}
    state_order = [s.get("id") for s in (default.get("states") or [])]
    out = {}
    for tkey, tval in targets.items():
        if tkey.split("/", 1)[0] != "wire":
            continue
        wire_areas = set()
        for sval in tval.get("states", {}).values():
            wire_areas |= set(sval.get("keys", {}).keys())
        found = {}
        for wk in sorted(wire_areas):
            mapped = keymap_map.get(wk, wk)
            for sid in state_order:
                sval = mtarget["states"].get(sid)
                if not sval or sval.get("error") is not None:
                    continue
                info = sval["keys"].get(mapped)
                if info:
                    found[wk] = {"version": version, "state": sid, "area": mapped,
                                 "template": info["template"], "variant": info["variant"], "new": info["new"]}
                    break
        if found:
            out[tkey] = found
    return out


def _build_keys_payload(screen, scr, do_crops, browser):
    stages = scr.get("stages") or []
    targets = {}
    crop_count = 0
    for se in stages:
        stage, version = se.get("stage"), se.get("version")
        tkey = "%s/%s" % (stage, version)
        entry_rel = se.get("entry", "")
        states = se.get("states") or [{"id": "(default)", "label": "기본", "steps": []}]
        states_out = {}
        area_union = set()
        try:
            entry_abs = _safe_registry_abs(entry_rel, "entry")
            entry_uri = pathlib.Path(entry_abs).resolve().as_uri()
        except ValueError as e:
            for s in states:
                states_out[s["id"]] = {"error": "entry 경로 불안전: %s" % e, "keys": {}}
            targets[tkey] = {"entry": entry_rel, "states": states_out, "src": {}}
            continue
        for s in states:
            page = None
            try:
                page = browser.new_page(viewport=VIEWPORT)
                page.goto(entry_uri)
                page.wait_for_load_state("networkidle")
                ok, err = _run_steps(page, s.get("steps", []))
                if not ok:
                    states_out[s["id"]] = {"error": err or "상태 진입 실패", "keys": {}}
                    continue
                result = page.evaluate(KEYS_JS)
                raw_keys, doc = result["keys"], result["doc"]
                keys_out = {}
                for area, info in raw_keys.items():
                    crop = None
                    if do_crops and AREA_RE.match(area):
                        png = _crop_png(page, info["bbox"], doc)
                        if png:
                            crop = _write_crop(screen, stage, version, s["id"], area, png)
                            if crop:
                                crop_count += 1
                    keys_out[area] = {
                        "template": info["template"], "variant": info["variant"], "new": info["new"],
                        "count": info["count"], "idx": info["idx"], "parent": info["parent"],
                        "bbox": info["bbox"], "crop": crop,
                    }
                    area_union.add(area)
                states_out[s["id"]] = {"error": None, "keys": keys_out}
            except Exception as e:
                states_out[s["id"]] = {"error": "%s: %s" % (type(e).__name__, e), "keys": {}}
            finally:
                if page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass
        try:
            files = _expand_files(se.get("files", []))
        except Exception:
            files = []
        targets[tkey] = {"entry": entry_rel, "states": states_out,
                          "src": {a: _grep_src(files, a) for a in sorted(area_union)}}

    keymap_source, keymap_map = _keymap_for(scr)
    mockup_use = _build_mockup_use(targets, keymap_map, scr)
    payload = {"screen": screen, "generatedAt": C.now_iso(), "targets": targets,
               "keymap": {"source": keymap_source, "map": keymap_map}, "mockupUse": mockup_use}
    return payload, crop_count


def _keys_js_text(screen, payload):
    body = _js_escape(_dump_compact(payload))
    return ("window.UIA_LIB_KEYS = window.UIA_LIB_KEYS || {};\n"
            "window.UIA_LIB_KEYS[%s] = %s;\n") % (json.dumps(screen), body)


# ================================================================ build
class _Stats:
    def __init__(self):
        self.files = 0
        self.total = 0
        self.max = (None, 0)
        self.truncated_slugs = []
        self.overflow_slugs = []
        self.skipped_slugs = []
        self.skipped_screens = []
        self.key_targets = 0
        self.key_states = 0
        self.crops = 0

    def note(self, rel_path, size):
        self.files += 1
        self.total += size
        if size > self.max[1]:
            self.max = (rel_path, size)


def cmd_build(screen_filter=None, no_keys=False):
    stats = _Stats()
    valid_slugs, skipped_slugs = _load_valid_slugs()
    stats.skipped_slugs.extend(skipped_slugs)
    for bad in skipped_slugs:
        print("건너뜀(template-index.json 슬러그 패턴 위반): %r" % bad)
    meta_by_slug = {s: _load_template_meta(s) for s in valid_slugs}
    layout_slugs = {s for s in valid_slugs if os.path.isfile(C.p("data", "layout", "template", "%s.json" % s))}

    rows = _parse_kit_rows(C.p(*KIT_COMPONENTS_REL.split("/")))
    kit_index, kit_full, groups = _build_kit_maps(rows, set(valid_slugs))
    rules_path = C.p(*KIT_RULES_REL.split("/"))
    rules_lines = open(rules_path, encoding="utf-8").read().splitlines() if os.path.isfile(rules_path) else []

    index_payload = _build_index(valid_slugs, kit_index, kit_full, groups, meta_by_slug, layout_slugs)
    index_json_text = _dump_compact(index_payload)
    index_js_text = "window.UIA_LIB_INDEX = %s;\n" % _js_escape(index_json_text)
    index_json_path = _safe_out("index.json")
    _atomic_write(index_json_path, index_json_text)
    stats.note("index.json", _byte_len(index_json_text))
    index_js_path = _safe_out("index.js")
    _atomic_write(index_js_path, index_js_text)
    stats.note("index.js", _byte_len(index_js_text))

    slug_sizes = []
    for slug in valid_slugs:
        # R4 HIGH1 — _load_valid_slugs 가 이미 slug 패턴으로 걸렀지만, 그래도(컨테인먼트 재확인 실패 등)
        # 이 슬러그 하나에서 예외가 나면 그 슬러그만 건너뛰고 나머지 212개는 계속 쓴다.
        try:
            meta = meta_by_slug.get(slug)
            layout = _load_layout(slug) if slug in layout_slugs else None
            text, truncated = _build_slug_file(slug, meta, layout, set(valid_slugs), kit_full, rules_lines)
            path = _safe_out("%s.js" % slug)
        except Exception as e:  # noqa: BLE001 — 한 슬러그의 결함이 나머지를 막지 않게
            stats.skipped_slugs.append(slug)
            print("건너뜀(%s.js): %s: %s" % (slug, type(e).__name__, e))
            continue
        _atomic_write(path, text)
        size = _byte_len(text)
        stats.note("%s.js" % slug, size)
        slug_sizes.append((slug, size))
        if truncated:
            stats.truncated_slugs.append(slug)
            if truncated.get("overflow"):
                stats.overflow_slugs.append(slug)
                print("경고: %s.js 는 노드·kit·rules 를 전부 비워도 512 KiB 를 넘음(%d bytes) — "
                      "slug/name/path/screens 자체가 비대함" % (slug, size))

    if not no_keys:
        registry = C.load_json(C.p("design", "registry.json")) or {"screens": {}}
        screens = registry.get("screens", {})
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for screen, scr in screens.items():
                    if screen_filter and screen != screen_filter:
                        continue
                    if not SCREEN_NAME_RE.match(screen):
                        stats.skipped_screens.append(screen)
                        print("건너뜀(keys-<Screen>.js 파일명 패턴 위반): %r" % screen)
                        continue
                    try:
                        payload, crop_count = _build_keys_payload(screen, scr, True, browser)
                        text = _keys_js_text(screen, payload)
                        path = _safe_out("keys-%s.js" % screen)
                    except Exception as e:  # noqa: BLE001 — 한 화면의 결함이 나머지 화면을 막지 않게
                        stats.skipped_screens.append(screen)
                        print("건너뜀(keys-%s.js): %s: %s" % (screen, type(e).__name__, e))
                        continue
                    _atomic_write(path, text)
                    stats.note("keys-%s.js" % screen, _byte_len(text))
                    stats.crops += crop_count
                    for tval in payload["targets"].values():
                        stats.key_targets += 1
                        stats.key_states += len(tval.get("states", {}))
            finally:
                browser.close()

    print("=== catalog_library.py --build 결과 ===")
    print("파일 수: %d, 총 크기: %d bytes (%.1f KiB)" % (stats.files, stats.total, stats.total / 1024))
    print("최대 파일: %s (%d bytes, %.1f KiB)" % (stats.max[0], stats.max[1], stats.max[1] / 1024))
    print("잘린 slug: %s" % (", ".join(stats.truncated_slugs) if stats.truncated_slugs else "(없음)"))
    if stats.overflow_slugs:
        print("512 KiB 초과(모두 비워도 못 맞춤): %s" % ", ".join(stats.overflow_slugs))
    if stats.skipped_slugs:
        print("건너뛴 slug: %s" % ", ".join(stats.skipped_slugs))
    if stats.skipped_screens:
        print("건너뛴 화면: %s" % ", ".join(stats.skipped_screens))
    if not no_keys:
        print("키 타깃 수: %d, 상태 수(진입 시도): %d, 크롭 수: %d" %
              (stats.key_targets, stats.key_states, stats.crops))
    print("슬러그별 크기(내림차순):")
    for slug, size in sorted(slug_sizes, key=lambda t: -t[1]):
        print("  %s.js %d bytes%s" % (slug, size, "  [잘림]" if slug in stats.truncated_slugs else ""))
    return 0


# ================================================================ 자체 테스트
def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _write_png(path, w=4, h=4):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    from PIL import Image
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(path)


SELFTEST_WIRE_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>wire</title></head>
<body>
<div id="canvas">
  <div data-area="hdr">제목 <span id="mark">init</span></div>
  <div data-area="feed-row" data-idx="0">row0</div>
  <div data-area="feed-row" data-idx="1">row1</div>
  <div data-area="Bad_Area!">안전하지 않은 키</div>
  <div data-new="신규 항목 설명">신규</div>
  <div style="display:none" data-area="hidden-row">숨김</div>
</div>
<script>
function loadState(id){ document.getElementById("mark").textContent = "loaded:" + id; }
function stopTimers(){}
</script>
</body></html>
"""

SELFTEST_MOCKUP_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>mockup</title></head>
<body>
<div id="canvas">
  <div data-template="tmpl-a" data-area="header-title">제목</div>
  <div data-area="feed-row" data-idx="0">row0</div>
</div>
<script>
function loadState(id){}
function stopTimers(){}
</script>
</body></html>
"""

SELFTEST_COMPONENTS_HEAD = """# 키트 대응표(테스트)

| 묶음 | 요소 | 시안 클래스/파일 | Unity 템플릿 slug/원본 | 사용 수/화면 수 | 9-slice | 비고 |
|---|---|---|---|---|---|---|
| 버튼 | A | .k-a | `tmpl-a` | tmpl-a 10/2 | - | A 안 |
| 버튼 | B | .k-b | `tmpl-b` | tmpl-b 5/1 | - | B 안 |
| 아이콘 | 원본 | - | `_Dev/Some/Sprite.png` | - | - | 슬러그 아님 — 매칭 안 됨 |
"""

# R4 HIGH2 반례 "노드 1개 + kit 2000행" 용 — tmpl-hugekit 하나에 2000행을 몰아줘(묶음을 전용으로 분리해
# tmpl-a/tmpl-b 의 그룹·alts 계산에 영향이 없게 한다), 노드를 비워도 512KiB 를 넘겨 kit 축소 경로를 탄다.
HUGEKIT_ROWS = 2000
HUGEKIT_NOTE_LEN = 160

SELFTEST_COMPONENTS_TAIL = """
이 아래는 두 번째 표(첫 표만 읽혀야 하는지 확인용, 두 번째 표 내용은 무시돼야 한다).

| x | y |
|---|---|
| 1 | 2 |
"""


def _selftest_components_md():
    hugekit_rows = "\n".join(
        "| 테스트큰키트 | E%d | .k-e%d | `tmpl-hugekit` | tmpl-hugekit 1/1 | - | %s |" %
        (i, i, "Y" * HUGEKIT_NOTE_LEN)
        for i in range(HUGEKIT_ROWS))
    return SELFTEST_COMPONENTS_HEAD + hugekit_rows + "\n" + SELFTEST_COMPONENTS_TAIL

SELFTEST_RULES_MD = """# 규칙 로그(테스트)

`tmpl-a` 를 쓸 때 이스케이프 테스트용 </script> 토큰이 포함된 줄.
tmpl-b 는 단어 그대로 등장(백틱 없음). tmpl-b-extra 안에는 포함되지 않아야 한다(경계 검사).
"""


def _make_registry():
    return {
        "version": 1,
        "screens": {
            "TestScreen": {
                "app": "Test", "label": "\xed\x85\x8c\xec\x8a\xa4\xed\x8a\xb8",
                "stages": [
                    {"stage": "wire", "version": "w1", "label": "\xec\x99\x80\xec\x9d\xb4\xec\x96\xb4",
                     "status": "wip", "entry": "design/testscreen/wire.html",
                     "files": ["design/testscreen/wire.html"],
                     "states": [
                         {"id": "s1", "label": "\xec\x83\x81\xed\x83\x9c1",
                          "steps": [{"call": "loadState", "args": ["s1"]},
                                    {"call": "stopTimers", "args": [], "optional": True}]},
                         {"id": "s2", "label": "\xec\x8b\xa4\xed\x8c\xa8",
                          "steps": [{"call": "missingFn", "args": []}]},
                     ]},
                    {"stage": "mockup", "version": "m1", "label": "\xeb\xaa\xa9\xec\x9d\x851",
                     "status": "wip", "entry": "design/testscreen/mockup.html",
                     "files": ["design/testscreen/mockup.html"],
                     "states": [{"id": "team", "label": "\xed\x8c\x80",
                                 "steps": [{"call": "loadState", "args": ["team"]},
                                           {"call": "stopTimers", "args": [], "optional": True}]}]},
                    {"stage": "mockup", "version": "m2", "label": "\xeb\xaa\xa9\xec\x9d\x852",
                     "status": "wip", "entry": "design/testscreen/wire.html",
                     "files": ["design/testscreen/wire.html"],
                     "states": [{"id": "s1", "label": "\xec\x83\x81\xed\x83\x9c1",
                                 "steps": [{"call": "loadState", "args": ["s1"]}]}]},
                ]
            }
        }
    }


def _check(results, name, fn):
    try:
        detail = fn()
        results.append((name, True, detail or ""))
    except Exception as e:  # noqa: BLE001 — 항목별 FAIL 로 모으고 계속 진행
        results.append((name, False, "%s: %s" % (type(e).__name__, e)))
        traceback.print_exc()


def selftest():
    results = []
    root = tempfile.mkdtemp(prefix="uiaudit-catalog-library-")
    old_root = C.ROOT
    old_env = os.environ.get("UIAUDIT_ROOT")
    try:
        C.ROOT = root
        os.environ["UIAUDIT_ROOT"] = root

        _write(C.p("design", "testscreen", "wire.html"), SELFTEST_WIRE_HTML)
        _write(C.p("design", "testscreen", "mockup.html"), SELFTEST_MOCKUP_HTML)
        _write(C.p("design", "testscreen", "keymap.json"), json.dumps({"map": {"hdr": "header-title"}}))
        _write(C.p("design", "registry.json"), json.dumps(_make_registry(), ensure_ascii=False))
        _write(C.p(*KIT_COMPONENTS_REL.split("/")), _selftest_components_md())
        _write(C.p(*KIT_RULES_REL.split("/")), SELFTEST_RULES_MD)

        slugs = ["tmpl-a", "tmpl-b", "tmpl-c", "tmpl-big", "tmpl-hugename", "tmpl-hugekit"]
        bad_slug = "../evil"  # R4 HIGH1 반례 — slug 패턴(C.SLUG_RE) 위반, 걸러져야 하고 나머지를 막지 않아야 함
        _write(C.p("data", "template-index.json"), json.dumps({"templates": slugs + [bad_slug]}))
        metas = {
            "tmpl-a": {"slug": "tmpl-a", "name": "TmplA", "path": "Assets/TmplA.prefab",
                       "usageTotal": 10, "screens": ["scr1", "scr2"], "tier": "atom", "kind": "button"},
            "tmpl-b": {"slug": "tmpl-b", "name": "TmplB", "path": "Assets/TmplB.prefab",
                       "usageTotal": 5, "screens": ["scr1"], "tier": "atom", "kind": "button"},
            "tmpl-c": {"slug": "tmpl-c", "name": "TmplC", "path": "Assets/TmplC.prefab",
                       "usageTotal": 1, "screens": [], "tier": "atom", "kind": "other"},
            "tmpl-big": {"slug": "tmpl-big", "name": "TmplBig", "path": "Assets/TmplBig.prefab",
                         "usageTotal": 1, "screens": [], "tier": "composite", "kind": "other"},
            # R4 HIGH2 반례 1 — 노드 1개뿐이지만 그 name 하나가 512KiB 를 넘김(path/screens 는 비움).
            "tmpl-hugename": {"slug": "tmpl-hugename", "name": "HugeName", "path": "Assets/HugeName.prefab",
                               "usageTotal": 0, "screens": [], "tier": "atom", "kind": "other"},
            # R4 HIGH2 반례 2 — 노드는 1개뿐(비우면 거의 0바이트)이지만 kit 가 2000행이라 그걸로도 넘침.
            "tmpl-hugekit": {"slug": "tmpl-hugekit", "name": "HugeKit", "path": "Assets/HugeKit.prefab",
                              "usageTotal": 0, "screens": [], "tier": "atom", "kind": "other"},
        }
        for slug, meta in metas.items():
            _write(C.p("data", "templates", "%s.json" % slug), json.dumps(meta, ensure_ascii=False))

        _write(C.p("data", "layout", "template", "tmpl-a.json"),
               json.dumps({"width": 100, "height": 50,
                           "boxes": [{"id": "b0", "name": "TmplA", "path": "TmplA", "depth": 0,
                                      "x": 0, "y": 0, "w": 100, "h": 50, "template": None, "active": True}]}))
        _write(C.p("data", "layout", "template", "tmpl-b.json"),
               json.dumps({"width": 80, "height": 40,
                           "boxes": [{"id": "b0", "name": "TmplB", "path": "TmplB", "depth": 0,
                                      "x": 0, "y": 0, "w": 80, "h": 40, "template": None, "active": True},
                                     {"id": "b1", "name": "Nested", "path": "TmplB/Nested", "depth": 1,
                                      "x": 1, "y": 1, "w": 10, "h": 10, "template": "tmpl-a", "active": True},
                                     {"id": "b2", "name": "Unknown", "path": "TmplB/Unknown", "depth": 1,
                                      "x": 2, "y": 2, "w": 5, "h": 5, "template": "no-such-slug",
                                      "active": True}]}))
        big_boxes = []
        for i in range(20000):
            depth = i % 10
            name = ("N%d" % i) + ("</script>alert(1)" if i == 0 else "")
            big_boxes.append({"id": "b%d" % i, "name": name,
                               "path": "/".join("Seg%d" % d for d in range(depth + 1)),
                               "depth": depth, "x": i % 500, "y": i % 300, "w": 20, "h": 10,
                               "template": None, "active": True})
        _write(C.p("data", "layout", "template", "tmpl-big.json"),
               json.dumps({"width": 500, "height": 300, "boxes": big_boxes}))

        _write(C.p("data", "layout", "template", "tmpl-hugename.json"),
               json.dumps({"width": 10, "height": 10,
                           "boxes": [{"id": "b0", "name": "H" * 600000, "path": "Huge", "depth": 0,
                                      "x": 0, "y": 0, "w": 10, "h": 10, "template": None, "active": True}]}))
        _write(C.p("data", "layout", "template", "tmpl-hugekit.json"),
               json.dumps({"width": 10, "height": 10,
                           "boxes": [{"id": "b0", "name": "K", "path": "K", "depth": 0,
                                      "x": 0, "y": 0, "w": 10, "h": 10, "template": None, "active": True}]}))

        _write_png(C.p("previews", "layout", "template", "tmpl-a.thumb.png"))
        _write(C.p("catalog", "templates", "tmpl-a.html"), "<html>tmpl-a</html>")
        _write(C.p("catalog", "screens", "scr1.html"), "<html>scr1</html>")

        def _load_slug_payload(slug):
            prefix = 'window.UIA_LIB = window.UIA_LIB || {};\nwindow.UIA_LIB["%s"] = ' % slug
            text = open(C.p("catalog", "library", "%s.js" % slug), encoding="utf-8").read()
            assert text.startswith(prefix), text[:80]
            return json.loads(text[len(prefix):-2])

        def t1():
            rc = cmd_build()
            assert rc in (0, None), rc
            idx = C.load_json(C.p("catalog", "library", "index.json"))
            assert set(idx["templates"].keys()) == set(slugs), idx["templates"].keys()
            assert idx["templates"]["tmpl-a"]["thumb"] == "previews/layout/template/tmpl-a.thumb.png"
            assert idx["templates"]["tmpl-a"]["page"] == "catalog/templates/tmpl-a.html"
            assert idx["templates"]["tmpl-c"]["thumb"] is None
            for slug in slugs:
                assert os.path.isfile(C.p("catalog", "library", "%s.js" % slug)), slug
            return "index.json %d슬러그 전부(../evil 제외), thumb·page 우선순위 확인" % len(slugs)
        _check(results, "1 index.json 생성", t1)

        def t2():
            idx = C.load_json(C.p("catalog", "library", "index.json"))
            a = idx["templates"]["tmpl-a"]
            b = idx["templates"]["tmpl-b"]
            c = idx["templates"]["tmpl-c"]
            assert a["alts"] == ["tmpl-b"], a["alts"]
            assert b["alts"] == ["tmpl-a"], b["alts"]
            assert c["alts"] == [], c["alts"]  # 키트 행 없음 → 대안 없음(추측 금지)
            assert a["groups"] == ["버튼"], a["groups"]
            assert idx["groups"]["버튼"] == ["tmpl-a", "tmpl-b"], idx["groups"]["버튼"]  # usage desc
            return "alts(키트 묶음 기준)·groups(usage 내림차순) 확인, 키트 행 없는 슬러그는 alts=[]"
        _check(results, "2 alts·groups 정렬", t2)

        def t2b():
            a = _load_slug_payload("tmpl-a")
            b = _load_slug_payload("tmpl-b")
            assert a["kit"] == [{"group": "버튼", "element": "A", "kitClass": ".k-a",
                                  "slugs": ["tmpl-a"], "usage": "tmpl-a 10/2", "slice": "-", "note": "A 안"}], a["kit"]
            assert [r["line"] for r in a["rules"]] == [3], a["rules"]  # `tmpl-a` 백틱 언급 1줄
            assert [r["line"] for r in b["rules"]] == [4], b["rules"]  # tmpl-b 단어 경계 언급(백틱 없음) 1줄
            # tmpl-a 의 노드(b0)·탐지된 중첩 템플릿(b1→tmpl-a)·미등록 템플릿(b2→null) 확인
            bn = b["nodes"]
            assert bn[0] == {"id": "b0", "name": "TmplB", "path": "TmplB", "depth": 0,
                              "x": 0, "y": 0, "w": 80, "h": 40, "template": None, "active": True}, bn[0]
            assert bn[1]["template"] == "tmpl-a", bn[1]
            assert bn[2]["template"] is None, bn[2]  # no-such-slug 는 인덱스에 없어 null
            return "kit 행(4칸 원문 보존)·rules 발췌(백틱/단어경계 각 1줄)·nodes 템플릿 조회(실존/미실존) 확인"
        _check(results, "2b <slug>.js kit·rules·nodes", t2b)

        def t2c():
            # R4 HIGH2 반례 1 — 노드 1개뿐(depth 티어가 하나뿐)인데 그 name 혼자 512KiB 를 넘김.
            # 고친 전 버전은 depth 하나뿐이면 for-cut 루프가 "버릴 게 없다" 고 보고 아무것도 안 줄여
            # truncated=None 인 채로 초과 파일을 그대로 돌려줬다.
            payload = _load_slug_payload("tmpl-hugename")
            tr = payload["truncated"]
            assert tr is not None, "큰 name 노드 1개가 잘리지 않음(truncated=None)"
            assert tr["kept"] == 0 and tr["dropped"] == 1, tr
            assert payload["nodes"] == []
            assert not tr.get("overflow"), "노드만 비워도 되는 상황인데 overflow 로 빠짐: %r" % tr
            size = _byte_len(open(C.p("catalog", "library", "tmpl-hugename.js"), encoding="utf-8").read())
            assert size <= MAX_FILE_BYTES, size
            return "노드 1개(name 600000자)만으로 512KiB 초과 → depth 단일 티어도 드롭(kept=0), %d bytes" % size
        _check(results, "2c 512KiB — 노드 1개(큰 name)", t2c)

        def t2d():
            # R4 HIGH2 반례 2 — 노드는 1개뿐(비우면 거의 0바이트)이지만 kit 가 2000행이라 노드만 비워선
            # 부족하다. 고친 전 버전은 kit·rules 를 전혀 줄이지 않았다.
            payload = _load_slug_payload("tmpl-hugekit")
            tr = payload["truncated"]
            assert tr is not None, tr
            assert tr["kept"] == 0, tr  # 노드부터 비워짐(그래도 부족했음)
            dropped = tr.get("kitDropped", 0)
            assert dropped > 0, "kit 2000행이 넘는데도 kitDropped 기록이 없음: %r" % tr
            assert len(payload["kit"]) == HUGEKIT_ROWS - dropped, (len(payload["kit"]), dropped)
            assert not tr.get("overflow"), tr
            size = _byte_len(open(C.p("catalog", "library", "tmpl-hugekit.js"), encoding="utf-8").read())
            assert size <= MAX_FILE_BYTES, size
            return "노드 1개 + kit %d행 → 노드로 부족해 kit 를 뒤에서부터 %d행 버림, %d bytes" % (
                HUGEKIT_ROWS, dropped, size)
        _check(results, "2d 512KiB — 노드 1개 + kit 2000행", t2d)

        def t2e():
            # R4 HIGH1 반례 3 — 슬러그 패턴(C.SLUG_RE) 위반("../evil")이 걸러져야 하고, 나머지 6개
            # 슬러그의 빌드를 막지 않아야 한다(고친 전 버전은 _safe_out 의 ValueError 가 cmd_build 전체를
            # 끝냈다). 탈출 파일이 ui-audit 루트 밖에 생기지 않았는지도 확인한다.
            valid, skipped = _load_valid_slugs()
            assert bad_slug not in valid, valid
            assert bad_slug in skipped, skipped
            idx = C.load_json(C.p("catalog", "library", "index.json"))
            assert bad_slug not in idx["templates"], idx["templates"].keys()
            for slug in slugs:
                assert slug in idx["templates"], slug
            assert not os.path.isfile(os.path.join(root, "evil.js"))
            assert not os.path.isfile(os.path.normpath(os.path.join(root, "..", "evil.js")))
            return "'../evil' 슬러그 필터링(valid 제외·skipped 포함), 탈출 파일 없음, 나머지 %d개는 정상 빌드" % len(slugs)
        _check(results, "2e 슬러그 패턴 위반('..' 포함) 필터링", t2e)

        def t3():
            text = open(C.p("catalog", "library", "tmpl-big.js"), encoding="utf-8").read()
            assert text.startswith('window.UIA_LIB = window.UIA_LIB || {};\n'), text[:60]
            assert "<\\/script" in text, "</ 이스케이프가 안 됨"
            assert "</script" not in text, "탈출하지 않은 </script 가 남음"
            prefix = 'window.UIA_LIB = window.UIA_LIB || {};\nwindow.UIA_LIB["tmpl-big"] = '
            payload = json.loads(text[len(prefix):-2])
            assert payload["truncated"] is not None, "20000개 박스가 512KiB 아래로 잘리지 않음"
            tr = payload["truncated"]
            assert tr["kept"] + tr["dropped"] == 20000, tr
            assert tr["maxDepth"] < 9, tr  # depth 9(최상위) 부터 버려졌어야 함
            assert len(payload["nodes"]) == tr["kept"], (len(payload["nodes"]), tr)
            size = len(text.encode("utf-8"))
            assert size <= 512 * 1024, size
            return "20000개 박스 → truncated 기록(kept+dropped=20000), </script> 이스케이프, 파일 <= 512KiB(%d bytes)" % size
        _check(results, "3 512KiB 잘라내기 · </ 이스케이프", t3)

        def t4():
            keys_path = C.p("catalog", "library", "keys-TestScreen.js")
            assert os.path.isfile(keys_path), "keys-TestScreen.js 없음"
            text = open(keys_path, encoding="utf-8").read()
            prefix = 'window.UIA_LIB_KEYS = window.UIA_LIB_KEYS || {};\nwindow.UIA_LIB_KEYS["TestScreen"] = '
            assert text.startswith(prefix), text[:80]
            payload = json.loads(text[len(prefix):-2])
            assert set(payload["targets"].keys()) == {"wire/w1", "mockup/m1", "mockup/m2"}, payload["targets"].keys()
            w1 = payload["targets"]["wire/w1"]
            assert w1["states"]["s1"]["error"] is None
            assert "s2" in w1["states"] and w1["states"]["s2"]["error"] is not None, w1["states"].get("s2")
            keys_s1 = w1["states"]["s1"]["keys"]
            assert "hdr" in keys_s1 and "feed-row" in keys_s1 and "hidden-row" not in keys_s1
            assert keys_s1["feed-row"]["count"] == 2 and sorted(keys_s1["feed-row"]["idx"]) == ["0", "1"]
            assert keys_s1["hdr"]["crop"] is not None, "안전한 area(hdr) 의 크롭이 없음"
            assert "Bad_Area!" in keys_s1 and keys_s1["Bad_Area!"]["crop"] is None, \
                "안전하지 않은 area 패턴인데 크롭이 생성됨"
            crop_path = C.p(*keys_s1["hdr"]["crop"].split("/"))
            assert os.path.isfile(crop_path) and os.path.getsize(crop_path) > 0
            assert w1["src"]["hdr"] and w1["src"]["hdr"][0].startswith("design/testscreen/wire.html:")
            return "타깃 3개(wire/w1·mockup/m1·mockup/m2), s2 오류 기록, hdr 크롭 실존, Bad_Area! 크롭 null, src grep"
        _check(results, "4 keys-TestScreen.js 생성·크롭·오류 상태", t4)

        def t5():
            keys_path = C.p("catalog", "library", "keys-TestScreen.js")
            text = open(keys_path, encoding="utf-8").read()
            prefix = 'window.UIA_LIB_KEYS = window.UIA_LIB_KEYS || {};\nwindow.UIA_LIB_KEYS["TestScreen"] = '
            payload = json.loads(text[len(prefix):-2])
            assert payload["keymap"]["source"] == "design/testscreen/keymap.json"
            assert payload["keymap"]["map"] == {"hdr": "header-title"}
            mu = payload["mockupUse"]["wire/w1"]
            assert mu["hdr"]["version"] == "m1" and mu["hdr"]["state"] == "team"
            assert mu["hdr"]["area"] == "header-title" and mu["hdr"]["template"] == "tmpl-a"
            return "keymap(hdr→header-title) 로드 + mockupUse 가 기본 시안 m1/team 에서 tmpl-a 를 찾음"
        _check(results, "5 keymap·mockupUse", t5)

        def t6():
            rc = cmd_build(screen_filter="TestScreen", no_keys=True)
            assert rc in (0, None), rc
            return "--screen·--no-keys 인자가 오류 없이 동작"
        _check(results, "6 --screen·--no-keys", t6)

        def t7():
            # node 가 있으면 생성 JS 를 실제로 파싱(파싱만 — 요구사항 5는 build_catalog_library 실행 뒤
            # 오케스트레이터가 별도로 재확인하지만, 여기서도 최소 1개는 직접 확인해 둔다).
            import subprocess
            node = shutil.which("node")
            if not node:
                return "node 없음 — 생략(해시: 각 파일을 python json.loads 로는 3·4·5 단계가 이미 확인함)"
            script = C.p("catalog", "library", "tmpl-big.js")
            cmd = "global.window={};require(%s);console.log('ok')" % json.dumps(script)
            r = subprocess.run([node, "-e", cmd], capture_output=True, text=True)
            assert r.returncode == 0 and "ok" in r.stdout, (r.returncode, r.stdout, r.stderr)
            return "node 로 tmpl-big.js require 파싱 성공"
        _check(results, "7 node 파싱(tmpl-big.js)", t7)
    finally:
        C.ROOT = old_root
        if old_env is None:
            os.environ.pop("UIAUDIT_ROOT", None)
        else:
            os.environ["UIAUDIT_ROOT"] = old_env
        shutil.rmtree(root, ignore_errors=True)

    bad = 0
    for name, ok, detail in results:
        bad += not ok
        print("%s  %s  %s" % ("PASS" if ok else "FAIL", name, detail))
    print("결과: %d/%d PASS" % (len(results) - bad, len(results)))
    return 1 if bad else 0


# ================================================================ CLI
def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", action="store_true", help="catalog/library/ 전체 생성")
    ap.add_argument("--screen", help="keys-<Screen>.js 를 이 화면만 생성(기본: 등록부의 전 화면)")
    ap.add_argument("--no-keys", action="store_true", help="keys-<Screen>.js 생성을 건너뜀(playwright 불필요)")
    ap.add_argument("--selftest", action="store_true", help="임시 루트에서 자체 테스트")
    return ap


def main(argv):
    a = build_parser().parse_args(argv)
    if a.selftest:
        return selftest()
    if a.build:
        return cmd_build(a.screen, a.no_keys)
    build_parser().print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
