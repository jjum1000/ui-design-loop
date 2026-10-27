"""schemas/*.json 의 원본 정의. a0_setup.py 가 이 정의로 schemas/ 를 다시 쓴다 (JSON Schema 부분집합)."""


def build():
    """{이름: 스키마 dict}"""
    S = "string"; N = "number"; I = "integer"; B = "boolean"


    def obj(props, req=None):
        o = {"type": "object", "properties": props}
        if req:
            o["required"] = req
        return o


    def arr(items, mn=None):
        a = {"type": "array", "items": items}
        if mn is not None:
            a["minItems"] = mn
        return a


    def nullable(t):
        return {"type": [t, "null"]} if isinstance(t, str) else {"anyOf": [t, {"type": "null"}]}


    SLUG = {"type": S, "pattern": "^[a-z0-9][a-z0-9_.-]*$"}
    BATCH = {"type": S, "pattern": "^b[0-9]+$"}
    KIND = {"enum": ["button", "tab", "toggle", "popup", "slot", "gauge", "currency", "reddot", "tooltip",
                     "toast", "listcell", "icon", "textstyle", "decor", "other"]}
    CAT = {"enum": ["color", "type", "spacing", "nineslice", "size"]}
    ITEM_STATUS = {"enum": ["미검토", "후보"]}
    STEP_STATUS = {"enum": ["대기", "진행", "완료", "무효", "실패"]}
    COLOR = {"type": S, "pattern": "^#[0-9A-F]{8}$"}
    VEC2 = {"type": "array", "items": {"type": N}, "minItems": 2, "maxItems": 2}
    schemas = {}

    schemas["project"] = obj({
        "name": {"type": S}, "unity_root": {"type": S}, "unity_version": {"type": S},
        "render_pipeline": {"type": S}, "ui_system": {"enum": ["uGUI", "UI Toolkit"]},
        "ui_packages": arr({"type": S}), "ui_root": {"type": S},
        "reference_resolution": obj({"width": {"type": I}, "height": {"type": I}}, ["width", "height"]),
        "platforms": arr({"type": S}, 1), "screenshot_ratios": arr({"type": S}, 1),
        "touch_min_px": {"type": N}, "guid_index_roots": arr({"type": S}, 1)},
        ["name", "unity_root", "ui_system", "ui_root", "reference_resolution", "platforms",
         "screenshot_ratios", "touch_min_px", "guid_index_roots"])

    chunk = obj({"status": {"enum": ["대기", "완료", "보류"]}, "limitHits": {"type": I, "minimum": 0},
                 "calls": {"type": I, "minimum": 0}, "kind": {"type": S}, "targets": {"type": S}},
                ["status", "limitHits", "calls"])
    step = obj({"status": STEP_STATUS, "attempts": {"type": I}, "failures": {"type": I}, "crashes": {"type": I},
                "resets": {"type": I}, "skipped": nullable(S),
                "failedBy": nullable(S), "startedAt": nullable(S), "finishedAt": nullable(S),
                "reopen": nullable(obj({"chunks": arr({"type": S}), "reason": {"type": S}, "by": {"type": S}},
                                       ["chunks", "reason", "by"])),
                "lastCheck": nullable(S),
                "chunks": {"type": "object", "additionalProperties": chunk}},
               ["status", "attempts", "failures", "crashes", "chunks"])
    schemas["manifest"] = obj({
        "version": {"type": I},
        "current": obj({"batch": BATCH, "next": {"type": S}}, ["batch", "next"]),
        "batchOrder": arr(BATCH, 1),
        "ack": obj({"H2": arr({"type": S}), "H3": arr({"type": S})}, ["H2", "H3"]),
        "batches": {"type": "object", "additionalProperties": obj({
            "gates": obj({g: {"enum": ["대기", "완료"]} for g in ["H1", "H2", "H3"]}, ["H1", "H2", "H3"]),
            "steps": obj({s: step for s in ["A1", "A2", "A3", "A4", "A5", "A6"]},
                         ["A1", "A2", "A3", "A4", "A5", "A6"])},
            ["gates", "steps"])}},
        ["version", "current", "batchOrder", "ack", "batches"])

    schemas["batch"] = obj({
        "batch": BATCH, "title": {"type": S}, "createdAt": {"type": S},
        "screens": arr(obj({"slug": SLUG, "name": {"type": S},
                            "prefab": {"type": S, "pattern": "^Assets/.*\\.prefab$"}},
                           ["slug", "name", "prefab"]), 1)},
        ["batch", "screens", "createdAt"])

    sprite = obj({"guid": {"type": S}, "fileID": {"type": I}, "path": nullable(S), "name": nullable(S),
                  "border": nullable(arr({"type": N}))}, ["guid", "path"])
    node = obj({
        "id": {"type": S, "pattern": "^Assets/.+\\.prefab#.+$"}, "name": {"type": S}, "path": {"type": S},
        "parent": nullable(S), "depth": {"type": I}, "active": {"type": B}, "children": {"type": I},
        "components": arr({"type": S}),
        "rect": nullable(obj({"w": {"type": N}, "h": {"type": N}, "sizeDelta": VEC2, "anchorMin": VEC2,
                              "anchorMax": VEC2, "pivot": VEC2, "pos": VEC2, "scale": VEC2},
                             ["w", "h", "anchorMin", "anchorMax"])),
        "graphic": nullable(obj({"type": {"type": S}, "color": COLOR, "sprite": nullable(sprite),
                                 "imageType": nullable(S), "raycast": {"type": B}, "material": nullable(S)},
                                ["type", "color"])),
        "text": nullable(obj({"component": {"type": S}, "font": nullable(S), "size": {"type": N}, "color": COLOR,
                              "autoSize": {"type": B}, "sizeMin": {"type": N}, "sizeMax": {"type": N},
                              "bold": {"type": B}, "content": {"type": S}},
                             ["component", "font", "size", "color"])),
        "layout": nullable(obj({"type": {"type": S}, "spacing": {"anyOf": [{"type": N}, VEC2]},
                                "padding": arr({"type": N}), "cellSize": VEC2}, ["type"])),
        "selectable": nullable(obj({"type": {"type": S}, "transition": {"type": S},
                                    "states": arr({"enum": ["Normal", "Pressed", "Disabled", "Hover", "Focused"]})},
                                   ["type", "states"])),
        "nested": nullable(obj({"prefab": nullable(S), "guid": {"type": S}, "instanceRoot": {"type": S}},
                               ["guid", "instanceRoot"])),
        "canvas": nullable(obj({"scaler": nullable(S), "referenceResolution": VEC2, "match": {"type": N}})),
        "flags": arr({"type": S}), "screen": SLUG},
        ["id", "name", "path", "depth", "active", "components", "rect", "graphic", "text", "layout",
         "selectable", "nested", "flags", "screen"])
    schemas["inventory"] = obj({
        "batch": BATCH, "screen": SLUG, "prefab": {"type": S}, "parsedAt": {"type": S},
        "nodes": arr(node, 1),
        "unresolved": arr(obj({"id": {"type": S},
                               "reason": {"enum": ["guid-unresolved", "sprite-missing", "runtime-container",
                                                   "missing-script", "nested-missing"]},
                               "detail": {"type": S}}, ["id", "reason", "detail"]))},
        ["batch", "screen", "prefab", "parsedAt", "nodes", "unresolved"])

    schemas["classified"] = obj({
        "batch": BATCH, "screen": SLUG, "updatedAt": {"type": S},
        "nodes": arr(obj({"id": {"type": S}, "kind": KIND, "basis": {"type": S, "minLength": 1},
                          "confidence": {"enum": ["high", "medium", "low"]},
                          "by": {"enum": ["rule", "decision", "agent"]}, "structural": {"type": B},
                          "questionId": nullable(S)}, ["id", "kind", "basis", "confidence", "by"]))},
        ["batch", "screen", "updatedAt", "nodes"])

    group = obj({"id": {"type": S, "pattern": "^[a-z]+-[0-9a-f]{4,40}$"}, "sigKey": {"type": S},
                 "signature": {"type": "object"}, "members": arr({"type": S}, 1), "screens": arr({"type": S}),
                 "count": {"type": I}, "status": ITEM_STATUS, "candidateReason": nullable(S)},
                ["id", "sigKey", "signature", "members", "screens", "count", "status"])
    schemas["groups"] = obj({"kind": KIND, "updatedAt": {"type": S}, "groups": arr(group)},
                            ["kind", "updatedAt", "groups"])

    retired = obj({"at": {"type": S}, "reason": {"type": S}, "successors": arr({"type": S})},
                  ["at", "reason", "successors"])
    schemas["registry"] = obj({
        "kind": KIND,
        "groups": {"type": "object", "additionalProperties": obj(
            {"sigKey": {"type": S}, "createdAt": {"type": S}, "createdBatch": BATCH},
            ["sigKey", "createdAt", "createdBatch"])},
        "aliases": {"type": "object", "additionalProperties": {"type": S}},
        "retired": {"type": "object", "additionalProperties": retired}},
        ["kind", "groups", "aliases", "retired"])

    schemas["metrics"] = obj({
        "kind": KIND, "updatedAt": {"type": S}, "groupCount": {"type": I}, "nodeCount": {"type": I},
        "screenCount": {"type": I}, "uniqueSprites": {"type": I}, "uniqueColors": {"type": I},
        "uniqueSizes": {"type": I}, "fontSizes": arr({"type": N}), "candidateShare": {"type": N},
        "stateCoverage": {"type": "object"}, "smallTouchTargets": {"type": I}, "topGroups": arr({"type": "object"})},
        ["kind", "updatedAt", "groupCount", "nodeCount", "screenCount", "uniqueColors", "uniqueSizes"])

    token = obj({"id": {"type": S, "pattern": "^[a-z]+-[0-9a-f]{4,40}$"}, "value": {}, "valueKey": {"type": S},
                 "family": {"enum": ["base", "grade", "attribute"]}, "members": arr({"type": S}, 1),
                 "count": {"type": I}, "status": ITEM_STATUS, "samples": arr({"type": S})},
                ["id", "value", "valueKey", "family", "members", "count", "status"])
    schemas["tokens"] = obj({
        "category": CAT, "updatedAt": {"type": S}, "tokens": arr(token),
        "mapping": {"type": "object", "additionalProperties": {"type": S}},
        "exceptions": arr(obj({"value": {"type": S}, "reason": {"type": S}, "count": {"type": I}},
                              ["value", "reason"]))},
        ["category", "updatedAt", "tokens", "mapping", "exceptions"])
    schemas["token-registry"] = obj({
        "category": CAT,
        "tokens": {"type": "object", "additionalProperties": obj(
            {"valueKey": {"type": S}, "createdAt": {"type": S}, "createdBatch": BATCH},
            ["valueKey", "createdAt", "createdBatch"])},
        "aliases": {"type": "object", "additionalProperties": {"type": S}},
        "retired": {"type": "object", "additionalProperties": retired},
        "families": {"type": "object", "additionalProperties": {"enum": ["base", "grade", "attribute"]}},
        "exceptions": {"type": "object", "additionalProperties": {"type": S}}},
        ["category", "tokens", "aliases", "retired"])

    schemas["decisions"] = arr(obj({
        "id": {"type": S, "pattern": "^d-[0-9]{4,}$"}, "type": {"enum": ["그룹", "토큰", "분류", "템플릿"]},
        "target": {"type": S}, "status": {"enum": ["표준", "폐기", "예외", "분류"]}, "to": nullable(S),
        "kind": nullable(S), "reason": nullable(S), "supersedes": nullable(S),
        "memberSnapshot": arr({"type": S}), "by": {"enum": ["user", "agent"]}, "at": {"type": S}, "batch": BATCH,
        "questionId": nullable(S)},
        ["id", "type", "target", "status", "to", "supersedes", "memberSnapshot", "by", "at", "batch", "questionId"]))

    schemas["questions"] = arr(obj({
        "id": {"type": S, "pattern": "^q-[0-9]{4,}$"}, "gate": {"enum": ["H1", "H2", "H3"]}, "batch": BATCH,
        "status": {"enum": ["open", "answered", "dropped"]}, "target": {"type": S}, "text": {"type": S},
        "options": arr(obj({"label": {"type": S}, "action": {"type": S}}, ["label", "action"]), 1),
        "evidence": arr({"type": S}), "answer": nullable(S), "createdAt": {"type": S}},
        ["id", "gate", "batch", "status", "target", "text", "options", "evidence"]))

    # ---- 템플릿 카탈로그(T 트랙)
    ASSET = {"type": S, "pattern": "^Assets/"}
    src = obj({"file": {"type": S}, "key": {"type": S}, "kind": {"type": S}}, ["file", "key", "kind"])
    schemas["scenes"] = obj({
        "updatedAt": {"type": S},
        "scenes": arr(obj({"name": {"type": S}, "address": nullable(S), "path": ASSET, "exists": {"type": B},
                           "matchedBy": {"type": S}, "sources": arr(src, 1)}, ["name", "path", "exists", "sources"])),
        "unreferenced": arr(obj({"name": {"type": S}, "address": nullable(S), "path": {"type": S}}, ["name", "path"])),
        "missing": arr(obj({"name": {"type": S}, "sources": arr(src, 1)}, ["name", "sources"])),
        "chains": arr({"type": "object"}), "stats": {"type": "object"}},
        ["updatedAt", "scenes", "unreferenced", "missing", "stats"])

    schemas["scene-ui"] = obj({
        "scene": {"type": S}, "path": ASSET, "updatedAt": {"type": S},
        "canvases": arr(obj({"root": {"type": S}, "nodes": arr(obj(
            {"path": {"type": S}, "name": {"type": S}, "components": arr({"type": S}), "nested": nullable(S)},
            ["path", "name", "components", "nested"]))}, ["root", "nodes"]))},
        ["scene", "path", "updatedAt", "canvases"])

    USAGE_KIND = {"enum": ["nested", "variant", "scene", "field", "code-ui", "code-loader", "code-wrap", "code-local"]}
    edge = obj({"template": nullable(S), "templateGuid": nullable(S), "kind": USAGE_KIND, "user": {"type": S},
                "userType": {"enum": ["prefab", "scene", "code"]}, "path": {"type": S}, "overrides": arr({"type": S})},
               ["template", "templateGuid", "kind", "user", "userType", "path", "overrides"])
    schemas["usage-part"] = obj({
        "source": {"enum": ["prefab", "scene", "code"]}, "updatedAt": {"type": S}, "edges": arr(edge),
        "unresolved": arr(obj({"ref": {"type": S}, "reason": {"type": S}, "detail": {"type": S}}, ["ref", "reason"]))},
        ["source", "updatedAt", "edges", "unresolved"])
    schemas["usage"] = obj({"updatedAt": {"type": S}, "edges": arr(edge),
                            "counts": {"type": "object", "additionalProperties": {"type": I}}},
                           ["updatedAt", "edges", "counts"])

    schemas["code-usage"] = obj({
        "updatedAt": {"type": S},
        "uiTypes": arr(obj({"uiType": {"type": S}, "controller": nullable(S), "prefabName": nullable(S),
                            "address": nullable(S), "prefab": nullable(S), "file": nullable(S), "line": nullable(I)},
                           ["uiType", "prefab"])),
        "loaderKeys": arr(obj({"key": {"type": S}, "prefab": nullable(S), "users": arr({"type": "object"})}, ["key", "prefab"])),
        "wrapContent": arr(obj({"user": {"type": S}, "guid": {"type": S}, "prefab": nullable(S)}, ["user", "guid", "prefab"])),
        "localResourceUI": arr(obj({"name": {"type": S}, "prefab": nullable(S)}, ["name", "prefab"])),
        "unresolved": arr({"type": "object"}), "stats": {"type": "object"}},
        ["updatedAt", "uiTypes", "loaderKeys", "wrapContent", "localResourceUI", "unresolved", "stats"])

    TIER = {"enum": ["atom", "composite", "screen"]}
    schemas["template"] = obj({
        "slug": SLUG, "name": {"type": S}, "path": ASSET, "guid": nullable(S), "address": nullable(S),
        "rule": {"enum": ["A", "B"]}, "kind": KIND, "kindBasis": {"type": S}, "tier": TIER,
        "counts": {"type": "object", "additionalProperties": {"type": I}}, "usageTotal": {"type": I},
        "users": arr(obj({"user": {"type": S}, "userType": {"type": S}, "kind": USAGE_KIND, "path": {"type": S}},
                         ["user", "userType", "kind", "path"])),
        "screens": arr({"type": S}), "scenes": arr({"type": S}), "contains": arr({"type": S}),
        "variants": arr({"type": S}), "overrides": nullable("object"), "lookalikes": nullable("array"),
        "thumbnail": nullable(S)},
        ["slug", "name", "path", "guid", "rule", "kind", "kindBasis", "tier", "counts", "usageTotal", "users",
         "screens", "scenes", "contains", "variants", "overrides", "lookalikes", "thumbnail"])
    schemas["template-index"] = obj({
        "updatedAt": {"type": S}, "templates": arr(SLUG),
        "screens": arr(obj({"slug": SLUG, "name": {"type": S}, "path": ASSET, "templates": arr({"type": S})},
                           ["slug", "name", "path", "templates"])),
        "unused": arr(obj({"path": ASSET, "name": {"type": S}, "suffix": {"type": S}}, ["path", "name", "suffix"])),
        "excluded": arr(obj({"path": ASSET, "reason": {"type": S}}, ["path", "reason"])),
        "rules": {"type": "object"}, "counts": {"type": "object"}},
        ["updatedAt", "templates", "screens", "unused", "excluded", "rules", "counts"])
    schemas["template-ext"] = obj({"updatedAt": {"type": S}, "what": {"enum": ["overrides", "lookalikes"]},
                                   "templates": {"type": "object"}, "stats": {"type": "object"}},
                                  ["updatedAt", "what", "templates"])
    schemas["app-flow"] = obj({
        "updatedAt": {"type": S}, "appScreen": {"type": S},
        "apps": arr(obj({"contentsType": {"type": S}, "value": {"type": I}, "label": {"type": S}, "enabled": {"type": B},
                         "hidden": nullable(S), "manual": {"type": B}, "icon": nullable(S), "iconPath": nullable(S),
                         "screens": arr({"type": S})}, ["contentsType", "value", "enabled", "hidden", "screens"])),
        "screens": {"type": "object", "additionalProperties": obj({
            "uiType": {"type": S}, "controller": nullable(S), "prefab": nullable(S), "slug": nullable(S),
            "next": arr(obj({"uiType": {"type": S}, "file": {"type": S}, "line": {"type": I}, "via": {"type": S}},
                            ["uiType", "file", "line", "via"]))}, ["uiType", "controller", "prefab", "next"])},
        "unresolved": arr({"type": "object"}), "stats": {"type": "object"}},
        ["updatedAt", "appScreen", "apps", "screens", "unresolved", "stats"])

    # ---- 화면 배치 맵(S 트랙): Unity 가 계산한 배치. 좌표는 image 픽셀, 왼쪽 위 원점
    box = obj({"id": {"type": S}, "path": {"type": S}, "name": {"type": S}, "depth": {"type": I, "minimum": 0},
               "x": {"type": N}, "y": {"type": N}, "w": {"type": N, "minimum": 0}, "h": {"type": N, "minimum": 0},
               "template": nullable(S), "nested": nullable(S), "active": {"type": B}, "sample": {"type": B},
               "loader": {"type": B}, "comps": {"type": S}},
              ["id", "path", "name", "depth", "x", "y", "w", "h", "template", "nested", "active", "sample", "loader"])
    schemas["layout"] = obj({
        "slug": SLUG, "kind": {"enum": ["screen", "template"]}, "path": ASSET, "image": {"type": S},
        "thumb": nullable(S), "width": {"type": I, "minimum": 1}, "height": {"type": I, "minimum": 1},
        "blank": {"type": B}, "boxes": arr(box, 1), "stats": {"type": "object"}},
        ["slug", "kind", "path", "image", "width", "height", "boxes"])
    return schemas
