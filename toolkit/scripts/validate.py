"""산출 파일 검증. 사용:
  python scripts/validate.py <파일|폴더...>            스키마 검증만 (*.tmp 는 최종 이름 기준으로 스키마 추정)
  python scripts/validate.py --rename <파일|폴더...>   전부 통과하면 준 순서대로 .tmp → 최종 이름 rename
  python scripts/validate.py --schema inventory <파일>  스키마를 직접 지정
  python scripts/validate.py --selftest
폴더를 주면 그 아래 *.tmp (없으면 *.json) 를 모두 대상으로 한다.
리포트(reports/review-<batch>.md)는 '## <조각>' 절마다 '- 표본' 줄이 5개 이상인지 본다.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

_SCHEMAS = {}

SCHEMA_BY_DIR = [
    ("data/inventory/", "inventory"), ("data/classified/", "classified"), ("data/groups/", "groups"),
    ("data/registry/", "registry"), ("data/metrics/", "metrics"), ("data/tokens/", "tokens"),
    ("data/token-registry/", "token-registry"), ("batches/", "batch"),
    ("data/scenes/ui/", "scene-ui"), ("data/usage/parts/", "usage-part"), ("data/templates/", "template"), ("data/layout/", "layout"),
]
SCHEMA_BY_PATH = {"data/scenes/reachable.json": "scenes", "data/usage/edges.json": "usage",
                  "data/code-usage.json": "code-usage", "data/template-index.json": "template-index",
                  "data/usage/overrides.json": "template-ext", "data/usage/lookalikes.json": "template-ext",
                  "data/app-flow.json": "app-flow"}
SCHEMA_BY_FILE = {"manifest.json": "manifest", "project.json": "project", "decisions.json": "decisions",
                  "questions.json": "questions"}
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list,
         "object": dict, "null": type(None)}


def load_schema(name):
    if name not in _SCHEMAS:
        path = C.p("schemas", name + ".json")
        if not os.path.exists(path):
            raise SystemExit("스키마 없음: " + path)
        _SCHEMAS[name] = C.load_json(path)
    return _SCHEMAS[name]


def _type_ok(v, t):
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, TYPES[t])


def check(v, s, path, errs):
    """JSON Schema 부분집합: type, enum, required, properties, additionalProperties, items,
    minItems, maxItems, minimum, minLength, pattern, anyOf."""
    if len(errs) > 50:
        return
    if "anyOf" in s:
        if not any(not check_list(v, sub, path) for sub in s["anyOf"]):
            errs.append("%s: anyOf 불일치" % path)
        return
    t = s.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(_type_ok(v, x) for x in ts):
            errs.append("%s: 타입 %s 기대, %s" % (path, t, type(v).__name__))
            return
    if "enum" in s and v not in s["enum"]:
        errs.append("%s: %r 는 %s 중 하나여야 함" % (path, v, s["enum"]))
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                errs.append("%s: 필수 키 '%s' 없음" % (path, k))
        props = s.get("properties", {})
        for k, sub in props.items():
            if k in v:
                check(v[k], sub, "%s.%s" % (path, k), errs)
        ap = s.get("additionalProperties")
        if isinstance(ap, dict):
            for k, sub in v.items():
                if k not in props:
                    check(sub, ap, "%s.%s" % (path, k), errs)
        elif ap is False:
            for k in v:
                if k not in props:
                    errs.append("%s: 허용되지 않은 키 '%s'" % (path, k))
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]:
            errs.append("%s: 항목 %d개 이상 필요" % (path, s["minItems"]))
        if "maxItems" in s and len(v) > s["maxItems"]:
            errs.append("%s: 항목 %d개 이하여야 함" % (path, s["maxItems"]))
        if "items" in s:
            for i, x in enumerate(v):
                check(x, s["items"], "%s[%d]" % (path, i), errs)
    if isinstance(v, str):
        if "minLength" in s and len(v) < s["minLength"]:
            errs.append("%s: 빈 문자열" % path)
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append("%s: %r 가 패턴 %s 와 안 맞음" % (path, v[:80], s["pattern"]))
    if isinstance(v, (int, float)) and not isinstance(v, bool) and "minimum" in s and v < s["minimum"]:
        errs.append("%s: %s 미만" % (path, s["minimum"]))


def check_list(v, s, path):
    e = []
    check(v, s, path, e)
    return e


def validate_obj(obj, schema_name):
    return check_list(obj, load_schema(schema_name), "$")


def final_name(path):
    return path[:-4] if path.endswith(".tmp") else path


def infer_schema(path):
    rel = os.path.relpath(os.path.abspath(final_name(path)), C.ROOT).replace("\\", "/")
    base = os.path.basename(rel)
    if base in SCHEMA_BY_FILE and "/" not in rel:
        return SCHEMA_BY_FILE[base]
    if rel in SCHEMA_BY_PATH:
        return SCHEMA_BY_PATH[rel]
    for prefix, name in SCHEMA_BY_DIR:
        if rel.startswith(prefix) and rel.endswith(".json"):
            return name
    if re.match(r"^reports/review-b[0-9]+\.md$", rel):
        return "@report"
    if rel.startswith("catalog/") and rel.endswith(".html"):
        return "@html"
    return None


def validate_report(text):
    errs = []
    sections = re.split(r"^## +", text, flags=re.M)[1:]
    if not sections:
        errs.append("'## <조각>' 절이 없음")
    for sec in sections:
        title = sec.splitlines()[0].strip()
        n = len(re.findall(r"^- 표본", sec, flags=re.M))
        if n < 5:
            errs.append("절 '%s': 표본 %d개 (5개 이상 필요)" % (title, n))
    return errs


def report_chunks(text):
    """리포트의 절 제목 -> 표본 수."""
    out = {}
    for sec in re.split(r"^## +", text, flags=re.M)[1:]:
        out[sec.splitlines()[0].strip()] = len(re.findall(r"^- 표본", sec, flags=re.M))
    return out


def validate_file(path, schema=None):
    schema = schema or infer_schema(path)
    if schema is None:
        return ["스키마를 추정할 수 없음 (--schema 로 지정)"]
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if schema == "@report":
        return validate_report(text)
    if schema == "@html":
        return [] if "<html" in text.lower() and "</html>" in text.lower() else ["HTML 문서가 아님"]
    try:
        obj = json.loads(text)
    except ValueError as e:
        return ["JSON 파싱 실패: %s" % e]
    return validate_obj(obj, schema)


def expand(paths):
    out = []
    for x in paths:
        if os.path.isdir(x):
            tmps, jsons = [], []
            for dp, _dn, fn in os.walk(x):
                for f in sorted(fn):
                    full = os.path.join(dp, f)
                    if f.endswith(".tmp"):
                        tmps.append(full)
                    elif f.endswith(".json"):
                        jsons.append(full)
            out.extend(sorted(tmps) if tmps else sorted(jsons))
        else:
            out.append(x)
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--rename", action="store_true")
    ap.add_argument("--schema")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    files = expand(a.paths)
    if not files:
        print("검증할 파일 없음")
        return 1
    bad = 0
    for f in files:
        if not os.path.exists(f):
            print("FAIL %s: 파일 없음" % f)
            bad += 1
            continue
        errs = validate_file(f, a.schema)
        if errs:
            bad += 1
            print("FAIL %s" % f)
            for e in errs[:10]:
                print("   - " + e)
        else:
            print("ok   %s" % f)
    if bad:
        print("검증 실패 %d건 — rename 하지 않음" % bad)
        return 1
    if a.rename:
        for f in files:
            if f.endswith(".tmp"):
                os.replace(f, final_name(f))
                print("rename %s" % final_name(f))
    return 0


def selftest():
    load_schema("manifest")
    good_q = [{"id": "q-0001", "gate": "H2", "batch": "b1", "status": "open", "target": "x",
               "text": "t", "options": [{"label": "a", "action": "a 표준"}], "evidence": []}]
    assert validate_obj(good_q, "questions") == []
    bad_q = [dict(good_q[0], gate="H9", options=[])]
    errs = validate_obj(bad_q, "questions")
    assert len(errs) >= 2, errs
    assert validate_obj({"kind": "button"}, "groups"), "필수 키 누락을 못 잡음"
    rep_ok = "## button\n" + "".join("- 표본 %d: x\n" % i for i in range(5))
    assert validate_report(rep_ok) == []
    assert validate_report("## slot\n- 표본 1: x\n")
    d = C.selftest_dir("validate")
    f = os.path.join(d, "questions.json.tmp")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(good_q, fh)
    assert validate_file(f, "questions") == []
    for name in ["manifest", "project", "batch", "inventory", "classified", "groups", "registry", "metrics",
                 "tokens", "token-registry", "decisions", "questions", "scenes", "scene-ui", "usage-part", "usage",
                 "code-usage", "template", "template-index", "template-ext", "app-flow"]:
        load_schema(name)
    assert infer_schema(C.p("data", "usage", "edges.json")) == "usage"
    assert infer_schema(C.p("data", "templates", "x.json")) == "template"
    print("validate.py selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
