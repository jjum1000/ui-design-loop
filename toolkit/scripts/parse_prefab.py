"""uGUI 프리팹(YAML)에서 UI 노드를 뽑는다. 중첩 프리팹(PrefabInstance)은 원본을 읽어 펼치고
수정값(m_Modifications)을 적용한다. Unity 프로젝트는 읽기만 한다.

사용:
  python scripts/parse_prefab.py --batch b1 --screen <화면 슬러그>
      → batches/<batch>.json 의 그 화면 프리팹을 읽어 data/inventory/<batch>/<화면>.json.tmp 를 쓴다.
        이어서 python scripts/validate.py --rename data/inventory/<batch>/<화면>.json.tmp
  python scripts/parse_prefab.py --show <Assets/...prefab>     노드 요약만 출력 (쓰지 않음)
  python scripts/parse_prefab.py --reindex                     GUID 색인(cache/guid-index.json) 다시 만들기
  python scripts/parse_prefab.py --selftest                    실제 UI 프리팹 3개(서로 다른 폴더)로 검사
"""
import argparse
import copy
import os
import re
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

MASK = 0x7FFFFFFFFFFFFFFF
HEADER_RE = re.compile(r"^--- !u!(\d+) &(-?\d+)( stripped)?[^\n]*$", re.M)
GUID_RE = re.compile(r"(guid: )([0-9a-f]{32})")
CLASS_NAMES = {1: "GameObject", 4: "Transform", 95: "Animator", 114: "MonoBehaviour", 198: "ParticleSystem",
               199: "ParticleSystemRenderer", 212: "SpriteRenderer", 222: "CanvasRenderer", 223: "Canvas",
               224: "RectTransform", 225: "CanvasGroup", 1001: "PrefabInstance", 320: "PlayableDirector", 1660057539: "SortingGroup"}
TRANSITIONS = {0: "None", 1: "ColorTint", 2: "SpriteSwap", 3: "Animation"}
IMAGE_TYPES = {0: "Simple", 1: "Sliced", 2: "Tiled", 3: "Filled"}
FLAG_SCRIPTS = {"SafeArea": "safeArea", "Mask": "mask", "RectMask2D": "mask", "ScrollRect": "scroll",
                "ResourcesLoader": "runtimeLoader", "WrapContent": "wrapContent", "DOTweenAnimation": "tween",
                "UIParticle": "particle", "LocalizationSupport": "localized", "LocalizeStringEvent": "localized",
                "ToggleGroup": "toggleGroup", "ContentSizeFitter": "sizeFitter", "LayoutElement": "layoutElement",
                "Outline": "outline", "Shadow": "shadow", "UIEffect": "uiEffect", "CanvasScaler": "canvasScaler",
                "GraphicRaycaster": "raycaster", "AspectRatioFitter": "aspectFitter"}
BUILTIN_GUIDS = {"0000000000000000f000000000000000": "builtin/unity_builtin_extra",
                 "0000000000000000e000000000000000": "builtin/unity default resources"}
BUILTIN_NAMES = {10905: "UISprite", 10907: "Background", 10909: "UIMask", 10911: "DropdownArrow",
                 10913: "InputFieldBackground", 10915: "Knob", 10917: "Checkmark", 10102: "Arial"}
EMPTY_KEY_RE = re.compile(r"^(\s*(?:- )?): ", re.M)
NAME_RE = re.compile(r"^(\s*m_Name: )([^'\"\n].*)$", re.M)


class _Loader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    """Unity YAML 용: YAML 1.1 의 bool(On/Off/Yes/No)·timestamp 암시 변환을 끈다."""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag not in ("tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp")]
    for k, v in _Loader.yaml_implicit_resolvers.items()}
YAML_LOADER = _Loader


def unity_yaml_text(text):
    """libyaml 이 못 읽는 Unity 표기를 고친다: 빈 키, 따옴표 없는 GUID·이름."""
    text = EMPTY_KEY_RE.sub(r'\1"": ', text)
    text = GUID_RE.sub(r'\1"\2"', text)
    return NAME_RE.sub(lambda m: m.group(1) + "'" + m.group(2).replace("'", "''") + "'", text)


# ---------------------------------------------------------------- GUID 색인
class GuidIndex:
    def __init__(self):
        self.path = C.p("cache", "guid-index.json")
        self.map = None
        self.rebuilt = False

    def _build(self):
        proj = C.project()
        root = C.unity_root()
        exts = tuple(proj.get("guid_index_exts") or [])
        rx = re.compile(rb"guid: ([0-9a-f]{32})")
        m = {}
        t = time.time()
        for sub in proj["guid_index_roots"]:
            base = os.path.join(root, sub)
            for dp, _dn, fn in os.walk(base):
                for f in fn:
                    if not f.endswith(".meta"):
                        continue
                    asset = f[:-5]
                    if exts and not asset.lower().endswith(exts):
                        continue
                    full = os.path.join(dp, f)
                    with open(full, "rb") as fh:
                        mm = rx.search(fh.read(256))
                    if mm:
                        m[mm.group(1).decode()] = os.path.relpath(full[:-5], root).replace("\\", "/")
        C.write_json_atomic(self.path, {"builtAt": C.now_iso(), "count": len(m), "map": m})
        self.map = m
        self.rebuilt = True
        print("GUID 색인 생성: %d개 (%.1fs)" % (len(m), time.time() - t), file=sys.stderr)

    def get(self, guid):
        if not guid:
            return None
        if guid in BUILTIN_GUIDS:
            return BUILTIN_GUIDS[guid]
        if self.map is None:
            data = C.load_json(self.path)
            if data:
                self.map = data["map"]
            else:
                self._build()
        hit = self.map.get(guid)
        if hit is None and not self.rebuilt and time.time() - os.path.getmtime(self.path) > 3600:
            self._build()  # 1시간 넘은 색인이면 새 에셋일 수 있으니 한 번만 다시 만든다
            hit = self.map.get(guid)
        return hit


INDEX = GuidIndex()


# ---------------------------------------------------------------- YAML
def load_docs(abs_path):
    """{fileID: {"cls", "stripped", "body"}}"""
    with open(abs_path, "r", encoding="utf-8") as f:
        text = f.read()
    heads = [(int(m.group(1)), int(m.group(2)), bool(m.group(3))) for m in HEADER_RE.finditer(text)]
    body = HEADER_RE.sub("---", text)
    body = unity_yaml_text("\n".join(l for l in body.split("\n") if not l.startswith("%")))
    try:
        docs = [d for d in yaml.load_all(body, Loader=YAML_LOADER)]
    except yaml.YAMLError as e:
        raise ValueError("YAML 파싱 실패: %s (%s)" % (abs_path, getattr(e, "problem_mark", e)))
    docs = [d for d in docs if d is not None]
    if len(docs) != len(heads):
        raise ValueError("YAML 문서 수 불일치: %s (%d vs %d)" % (abs_path, len(docs), len(heads)))
    out = {}
    for (cls, fid, stripped), d in zip(heads, docs):
        (_k, b), = d.items()
        out[fid] = {"cls": cls, "stripped": stripped, "body": b or {}}
    return out


def ref_id(r):
    return r.get("fileID", 0) if isinstance(r, dict) else 0


def ref_guid(r):
    return r.get("guid") if isinstance(r, dict) else None


# ---------------------------------------------------------------- 수정값 적용
def _coerce(old, value):
    if isinstance(old, bool):
        return bool(int(value))
    if isinstance(old, int) and not isinstance(old, bool):
        # 원본이 정수(202)여도 수정값이 소수(202.5)면 소수를 지킨다. int(202.5) 는 202 로 잘린다.
        if isinstance(value, float):
            return int(value) if value.is_integer() else value
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return float(value)
            except (TypeError, ValueError):
                return value
    if isinstance(old, float) or (old is None and isinstance(value, str) and re.match(r"^-?[0-9.]+(e-?\d+)?$", value)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value if value is not None else ""


def apply_mod(body, prop, value, objref):
    parts = re.sub(r"\.Array\.data\[(\d+)\]", r".#\1", prop).split(".")
    if parts and parts[-1] == "Array" or prop.endswith("Array.size"):
        return
    cur = body
    for i, key in enumerate(parts):
        last = i == len(parts) - 1
        if key.startswith("#"):
            idx = int(key[1:])
            if not isinstance(cur, list):
                return
            while len(cur) <= idx:
                cur.append({} if not last else None)
            if last:
                cur[idx] = objref if ref_id(objref) or ref_guid(objref) else _coerce(cur[idx], value)
            else:
                if cur[idx] is None:
                    cur[idx] = {}
                cur = cur[idx]
            continue
        if not isinstance(cur, dict):
            return
        if last:
            old = cur.get(key)
            if isinstance(old, dict) and ("fileID" in old) or ref_id(objref) or ref_guid(objref):
                cur[key] = objref
            else:
                cur[key] = _coerce(old, value)
        else:
            nxt = parts[i + 1]
            if key not in cur or cur[key] is None:
                cur[key] = [] if nxt.startswith("#") else {}
            cur = cur[key]


INTERNAL_REF_KEYS = ("m_GameObject", "m_Father", "m_PrefabInstance")


def remap_body(body, f):
    b = copy.deepcopy(body)
    for k in INTERNAL_REF_KEYS:
        if isinstance(b.get(k), dict) and ref_id(b[k]) and not ref_guid(b[k]):
            b[k] = {"fileID": f(b[k]["fileID"])}
    if isinstance(b.get("m_Children"), list):
        b["m_Children"] = [{"fileID": f(ref_id(c))} for c in b["m_Children"] if ref_id(c)]
    if isinstance(b.get("m_Component"), list):
        b["m_Component"] = [{"component": {"fileID": f(ref_id(c.get("component")))}}
                            for c in b["m_Component"] if isinstance(c, dict)]
    for k in ("m_Content", "m_TargetGraphic", "m_FillRect", "m_HandleRect"):
        if isinstance(b.get(k), dict) and ref_id(b[k]) and not ref_guid(b[k]):
            b[k] = {"fileID": f(b[k]["fileID"])}
    return b


# ---------------------------------------------------------------- 펼치기
class Expanded:
    """한 프리팹을 중첩까지 펼친 객체 집합. objs: id -> {cls, body, owner}"""

    def __init__(self, rel):
        self.rel = rel
        self.objs = {}
        self.unresolved = []
        self.alias = {}  # 공식((인스턴스 ^ 원본) & MASK)과 다른 stripped id → 공식 id


_CACHE = {}


def _subtree(objs, gos):
    """제거된 GameObject 들의 하위 트리 전체(GO·Transform·컴포넌트) ID."""
    out, todo = set(), list(gos)
    while todo:
        go = todo.pop()
        if go in out:
            continue
        out.add(go)
        for oid, o in objs.items():
            if ref_id(o["body"].get("m_GameObject")) != go:
                continue
            out.add(oid)
            if o["cls"] in (224, 4):
                for cid, c in objs.items():
                    if c["cls"] in (224, 4) and ref_id(c["body"].get("m_Father")) == oid:
                        todo.append(ref_id(c["body"].get("m_GameObject")))
    return out


def expand(rel, stack=()):
    if rel in _CACHE:
        return _CACHE[rel]
    if rel in stack:
        raise ValueError("중첩 순환: " + " -> ".join(stack + (rel,)))
    abs_path = os.path.join(C.unity_root(), rel)
    docs = load_docs(abs_path)
    ex = Expanded(rel)
    for fid, d in docs.items():  # Unity 가 재저장한 파일은 stripped id 가 공식과 다를 수 있다 — 참조를 공식 id 로 돌린다
        if d["stripped"]:
            inst, src = ref_id(d["body"].get("m_PrefabInstance")), ref_id(d["body"].get("m_CorrespondingSourceObject"))
            if inst and src and (inst ^ src) & MASK != fid:
                ex.alias[fid] = (inst ^ src) & MASK
    g = (lambda x: ex.alias.get(x, x))
    for fid, d in docs.items():
        if d["stripped"] or d["cls"] == 1001:
            continue
        ex.objs[fid] = {"cls": d["cls"], "body": remap_body(d["body"], g) if ex.alias else d["body"], "owner": None}
    for inst_id, d in docs.items():
        if d["cls"] != 1001 or d["stripped"]:
            continue
        b = d["body"]
        src_guid = ref_guid(b.get("m_SourcePrefab"))
        src_rel = INDEX.get(src_guid)
        mod = b.get("m_Modification") or {}
        parent = g(ref_id(mod.get("m_TransformParent")))
        if not src_rel or not src_rel.endswith(".prefab"):
            ex.unresolved.append(("nested-missing", inst_id, "중첩 프리팹 원본 GUID 해석 실패: %s" % src_guid))
            continue
        sub = expand(src_rel, stack + (rel,))
        f = (lambda x, i=inst_id: (i ^ x) & MASK)
        mods = {}
        for m in mod.get("m_Modifications") or []:
            mods.setdefault(ref_id(m.get("target")), []).append(m)
        removed = {ref_id(r) for r in (mod.get("m_RemovedComponents") or [])}
        removed |= _subtree(sub.objs, {ref_id(r) for r in (mod.get("m_RemovedGameObjects") or [])})
        root_tf = [f(sid) for sid, o in sub.objs.items()
                   if o["cls"] in (224, 4) and ref_id(o["body"].get("m_Father")) == 0]
        for sid, o in sub.objs.items():
            if sid in removed:
                continue
            body = remap_body(o["body"], f)
            for m in mods.get(sid, []):
                apply_mod(body, m.get("propertyPath", ""), m.get("value"), m.get("objectReference"))
            if o["cls"] in (224, 4) and ref_id(o["body"].get("m_Father")) == 0:
                body["m_Father"] = {"fileID": parent}
            if o["owner"]:
                owner = dict(o["owner"], rootTransform=f(o["owner"]["rootTransform"]))
            else:
                owner = {"prefab": src_rel, "guid": src_guid, "rootTransform": root_tf[0] if root_tf else 0}
            ex.objs[f(sid)] = {"cls": o["cls"], "body": body, "owner": owner}
        for kind, sid, detail in sub.unresolved:
            ex.unresolved.append((kind, f(sid), detail))
    _CACHE[rel] = ex
    return ex


# ---------------------------------------------------------------- 메타 (스프라이트 이름·border)
_META = {}


def sprite_info(r):
    if not r or not ref_guid(r):
        return None
    guid = ref_guid(r)
    fid = ref_id(r)
    path = INDEX.get(guid)
    info = {"guid": guid, "fileID": fid, "path": path, "name": None, "border": None}
    if not path:
        return info
    if path.startswith("builtin/"):
        info["name"] = BUILTIN_NAMES.get(fid, str(fid))
        return info
    if path not in _META:
        meta_path = os.path.join(C.unity_root(), path + ".meta")
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                txt = unity_yaml_text(f.read())
            _META[path] = (yaml.load(txt, Loader=YAML_LOADER) or {}).get("TextureImporter")
        except (OSError, yaml.YAMLError):
            _META[path] = None
    ti = _META[path]
    base = os.path.splitext(os.path.basename(path))[0]
    if not ti:
        info["name"] = base
        return info
    if fid == 21300000:
        info["name"] = base
        bd = ti.get("spriteBorder") or {}
        info["border"] = [bd.get("x", 0), bd.get("y", 0), bd.get("z", 0), bd.get("w", 0)]
        return info
    for s in ((ti.get("spriteSheet") or {}).get("sprites") or []):
        if s.get("internalID") == fid:
            bd = s.get("border") or {}
            info["name"] = s.get("name")
            info["border"] = [bd.get("x", 0), bd.get("y", 0), bd.get("z", 0), bd.get("w", 0)]
            return info
    return info


# ---------------------------------------------------------------- 노드 만들기
def color_hex(c):
    if not isinstance(c, dict):
        return "#FFFFFFFF"
    vals = []
    for k in ("r", "g", "b", "a"):
        try:
            v = float(c.get(k, 1))
        except (TypeError, ValueError):
            v = 1.0
        vals.append(max(0, min(255, int(round(v * 255)))))
    return "#%02X%02X%02X%02X" % tuple(vals)


def vec(d, keys=("x", "y"), default=0.0):
    d = d if isinstance(d, dict) else {}
    out = []
    for k in keys:
        try:
            out.append(round(float(d.get(k, default)), 3))
        except (TypeError, ValueError):
            out.append(default)
    return out


# com.unity.ugui(uGUI·TextMeshPro) 스크립트 GUID → 클래스 이름. GUID 색인(Library/PackageCache)이 없는 체크아웃
# (Unity 로 한 번도 안 연 클론)에서도 컴포넌트 종류를 알아보도록 색인에 없을 때만 쓴다. 패키지 2.0 기준(1.x 와 같은 GUID).
BUILTIN_SCRIPTS = {
    "c67ac6e40bbb6fe47a095b949b609ce0": "AnimationTriggers", "86710e43de46f6f4bac7c8e50813a599": "AspectRatioFitter",
    "91f495459b6e34f419ac123740d798b1": "BaseEventData", "1511ccae7919cfc46b603b9b337fdc94": "BaseInput",
    "1ea10891dd782154ca0fb67bce9e6f72": "BaseInputModule", "718966f960cb50643986195e5fe953ca": "BaseMeshEffect",
    "426106349a0ff964fa4e7178c1d3a4f5": "BaseRaycaster", "4e29b1a8efbd4b44bb3f3716e73f07ff": "Button",
    "0cd44c1031e13a943bb63640046fad76": "CanvasScaler", "bfb788a43e03363419155b8af77da971": "CanvasUpdateRegistry",
    "9f1026265f8e3d54fb6e9f082c43debf": "ClipperRegistry", "3245ec927659c4140ac4f8d17403cc18": "ContentSizeFitter",
    "bf87e20fb5440ec498f441167b5291f8": "DefaultControls", "0d0b652f32a2cc243917e4028fa0f046": "Dropdown",
    "76c392e42b5098c458856cdf6ecaaaa1": "EventSystem", "d0b148fe25e99eb48b9724523833bab1": "EventTrigger",
    "a6238e9452bfc704f82ff36791fe1a45": "Graphic", "dc42784cf147c0c48a680349fa168899": "GraphicRaycaster",
    "445cdcfc747eba94288b97f5869aa2fb": "GraphicRebuildTracker",
    "69e3979b7029e8a4da2d96b714ba5c3a": "GraphicRegistry", "8a8695521f0d02e499659fee002a26c2": "GridLayoutGroup",
    "30649d3a9faa99c48a7b1166b86bf2a0": "HorizontalLayoutGroup",
    "a5c214e5846a99242b348c37e49b2f59": "HorizontalOrVerticalLayoutGroup",
    "fe87c0e1cc204ed48ad3b37840f39efc": "Image", "d199490a83bb2b844b9695cbf13b01ef": "InputField",
    "306cc8c2b49d7114eaa3623786fc2126": "LayoutElement", "cb7c939a806f03341b682c180dc13f08": "LayoutGroup",
    "006633c8a6f4ae94aa9babf72234e1a2": "LayoutRebuilder", "31a19414c41e5ae4aae2af33fee712f6": "Mask",
    "976acc75bfafe594cb01142ba21947be": "MaskableGraphic", "e19747de3f5aca642ab2be37e372fb86": "Outline",
    "8a410b213209442fb15a69799f0240a5": "PanelEventHandler", "7a79c4e23d4d4b64bfa5fa9e6671a460": "PanelRaycaster",
    "c49b4cc203aa6414fae5c798d1d0e7d6": "PhysicsRaycaster", "75df57ccb1e44c64085399277405e1ca": "PointerEventData",
    "cbab8835092323a4389f2dc7d8f6c781": "PointerInputModule", "020ee4c1798a3d243a4b8cbfee6cac2d": "PositionAsUV1",
    "1344c3c82d62a2a41a3576d8abb8e3ea": "RawImage", "26570be2af04195458e6f1ac1f5c48e0": "RaycasterManager",
    "3312d7739989d2b4e91e6319e9a96d76": "RectMask2D", "fcae021c30eccf74790a4e816ba97c19": "ReflectionMethodsCache",
    "1aa08ab6e0800fa44ae55d278d1423e3": "ScrollRect", "2a4db7a114972834c8e4117be1d82ba3": "Scrollbar",
    "7a98125502f715b4b83cfb77b434e436": "Selectable", "cfabb0440166ab443bba8876756fdfa9": "Shadow",
    "67db9e8f0e2ae9c40bc1e2b64352a6b4": "Slider", "4f231c4fb786f3946a6b90b886c48677": "StandaloneInputModule",
    "69ae55f76840b2849ba56cfb53a17df0": "StencilMaterial", "3bda1886f58f4e0ab1139400b160c3ee": "TMP_Asset",
    "4ac5b6a65aaeb59478e3b78660e9f134": "TMP_Character", "322392995be44d23a3c86cfd972f838f": "TMP_DefaultControls",
    "7b743370ac3e4ec2a1668f5455a8ef8a": "TMP_Dropdown",
    "aaf9006568d76504f982305b517fb490": "TMP_DynamicFontAssetUtilities",
    "71c1514a6bd24e1e882cebbe1904ce04": "TMP_FontAsset",
    "0a017569bfe174e4890797b4d64cbabc": "TMP_FontAssetUtilities",
    "2da0c512f12947e489f739169773d7ca": "TMP_InputField", "6d9df2bc198c417db00037803568139c": "TMP_MaterialManager",
    "34e150112c1c42ac83170b52d898e322": "TMP_ScrollbarEventHandler",
    "ca819640f53b48919bf7774744f7f15e": "TMP_SelectionCaret", "968a09f153574430a6e15ae975145768": "TMP_Sprite",
    "6366ee97f6b541449155028b9487355a": "TMP_SpriteAnimator", "84a92b25f83d49b9bc132d206b370281": "TMP_SpriteAsset",
    "202d758d102b6854a9710c8b93db742c": "TMP_SpriteCharacter", "30bed781e402439ab8ce4e3357708115": "TMP_Style",
    "ab2114bdc8544297b417dfefe9f1e410": "TMP_StyleSheet", "07994bfe8b0e4adb97d706de5dea48d5": "TMP_SubMesh",
    "058cba836c1846c3aa1c5fd2e28aea77": "TMP_SubMeshUI", "5143f58107604835ab1a5efa2d8818fd": "TMP_Text",
    "543674eec776b1442a192c932e6cd9b3": "TMP_TextElement",
    "87ab1bebe13f41f89d5427e7d2c34d58": "TMP_TextElement_Legacy", "4ae64f3f72004807a9f919f9c27af0db": "TMP_TextInfo",
    "6ad632cbcc87f634d9b86006cdffdaf5": "TMP_TextParsingUtilities",
    "4f0ca6874aa74540bb3d4fe5a0f86bcc": "TMP_TextUtilities", "691db8cb70c4426a8ae718465c21345f": "TMP_UpdateManager",
    "5f7201a12d95ffc409449d95f23cf332": "Text", "32d40088a6124c578ad6b428df586e2e": "TextContainer",
    "9541d86e2fd84c1d9990edf0852d74ab": "TextMeshPro", "f4688fdb7df04437aeb418b961361dc5": "TextMeshProUGUI",
    "9085046f02f69544eb97fd06b6048fe2": "Toggle", "2fafe2cfe61f6974895a912c3755e8f1": "ToggleGroup",
    "2d49b7c1bcd2e07499844da127be038d": "TouchInputModule", "0aaa057ce5566e940b18a0ccd0344693": "UIBehaviour",
    "c459424081436584c8cec10767f9ac38": "VertexHelper", "59f8146938fff824cb5fd77236b75775": "VerticalLayoutGroup",
    "2c727e4c005e5114fb3348a38c4cebbf": "WorldDocumentRaycaster",
}


def script_name(body, unresolved, node_id):
    r = body.get("m_Script")
    guid = ref_guid(r)
    if not guid:
        unresolved.append({"id": node_id, "reason": "missing-script", "detail": "m_Script 비어 있음 (Missing Script)"})
        return "MissingScript"
    path = INDEX.get(guid)
    if not path and guid in BUILTIN_SCRIPTS:
        return BUILTIN_SCRIPTS[guid]
    if not path:
        unresolved.append({"id": node_id, "reason": "guid-unresolved", "detail": "스크립트 GUID %s" % guid})
        return "Script:" + guid[:8]
    name = os.path.splitext(os.path.basename(path))[0]
    if path.endswith(".dll"):
        return "%s.dll:%s" % (name, ref_id(r))
    return name


def selectable_info(name, b):
    tr = b.get("m_Transition")
    if tr is None or "m_Colors" not in b:
        return None
    tr = int(tr)
    states = ["Normal"]
    if tr == 1:
        cols = b.get("m_Colors") or {}
        normal = color_hex(cols.get("m_NormalColor"))
        for key, st in (("m_PressedColor", "Pressed"), ("m_DisabledColor", "Disabled"),
                        ("m_HighlightedColor", "Hover"), ("m_SelectedColor", "Focused")):
            if key in cols and color_hex(cols[key]) != normal:
                states.append(st)
    elif tr == 2:
        ss = b.get("m_SpriteState") or {}
        for key, st in (("m_PressedSprite", "Pressed"), ("m_DisabledSprite", "Disabled"),
                        ("m_HighlightedSprite", "Hover"), ("m_SelectedSprite", "Focused")):
            if ref_guid(ss.get(key)):
                states.append(st)
    elif tr == 3:
        states += ["Pressed", "Disabled", "Hover", "Focused"]
    return {"type": name, "transition": TRANSITIONS.get(tr, str(tr)), "states": states}


def build_nodes(rel, screen):
    ex = expand(rel)
    objs = ex.objs
    unresolved = []
    ref = (C.project() or {}).get("reference_resolution", {"width": 1920, "height": 1080})
    go_tf, comps_by_go = {}, {}
    for oid, o in objs.items():
        go = ref_id(o["body"].get("m_GameObject"))
        if o["cls"] == 1 or not go:
            continue
        comps_by_go.setdefault(go, []).append(oid)
        if o["cls"] in (224, 4):
            go_tf[go] = oid
    tf_go = {tf: go for go, tf in go_tf.items()}
    children = {}
    for tf, go in tf_go.items():
        father = ref_id(objs[tf]["body"].get("m_Father"))
        children.setdefault(father, [])
    for tf in tf_go:
        listed = [ref_id(c) for c in (objs[tf]["body"].get("m_Children") or [])]
        children[tf] = [c for c in listed if c in tf_go]
    for tf in tf_go:
        father = ref_id(objs[tf]["body"].get("m_Father"))
        if father and father in tf_go and tf not in children.get(father, []):
            children.setdefault(father, []).append(tf)
    roots = [tf for tf in tf_go if ref_id(objs[tf]["body"].get("m_Father")) == 0]
    orphans = [tf for tf in tf_go if ref_id(objs[tf]["body"].get("m_Father")) not in tf_go and tf not in roots]
    if len(roots) != 1:
        raise ValueError("%s: 루트 Transform %d개 (1개여야 함)" % (rel, len(roots)))
    scroll_contents = set()
    for o in objs.values():
        if o["cls"] == 114 and isinstance(o["body"].get("m_Content"), dict):
            scroll_contents.add(ref_id(o["body"]["m_Content"]))
    nodes = []
    by_tf = {}

    def walk(tf, parent_path, parent_size, depth):
        go = tf_go[tf]
        gob = objs[go]["body"] if go in objs else {}
        name = str(gob.get("m_Name", "?"))
        siblings = children.get(ref_id(objs[tf]["body"].get("m_Father")), [])
        same = [s for s in siblings if str(objs.get(tf_go[s], {}).get("body", {}).get("m_Name", "?")) == name]
        label = name if len(same) <= 1 or same.index(tf) == 0 else "%s[%d]" % (name, same.index(tf))
        path = label if parent_path is None else parent_path + "/" + label
        nid = "%s#%s" % (rel, path)
        tb = objs[tf]["body"]
        comp_names, graphic, text, layout, selectable, canvas, flags = [], None, None, None, None, None, []
        ordered = [ref_id(c.get("component")) for c in (gob.get("m_Component") or []) if isinstance(c, dict)]
        comp_ids = [c for c in ordered if c in objs] + [c for c in comps_by_go.get(go, []) if c not in ordered]
        for cid in comp_ids:
            o = objs[cid]
            b = o["body"]
            if o["cls"] == 114:
                cname = script_name(b, unresolved, nid)
            else:
                cname = CLASS_NAMES.get(o["cls"], "class%d" % o["cls"])
            comp_names.append(cname)
            if cname in FLAG_SCRIPTS:
                flags.append(FLAG_SCRIPTS[cname])
            if o["cls"] == 225:
                flags.append("canvasGroup")
            if o["cls"] == 95:
                flags.append("animator")
            if o["cls"] == 223:
                canvas = canvas or {"scaler": None, "referenceResolution": [0, 0], "match": 0}
            if o["cls"] != 114:
                continue
            if "m_UiScaleMode" in b:
                canvas = {"scaler": {0: "ConstantPixelSize", 1: "ScaleWithScreenSize", 2: "ConstantPhysicalSize"}
                          .get(int(b.get("m_UiScaleMode", 0)), str(b.get("m_UiScaleMode"))),
                          "referenceResolution": vec(b.get("m_ReferenceResolution")),
                          "match": float(b.get("m_MatchWidthOrHeight", 0) or 0)}
            if "m_fontAsset" in b or "m_FontData" in b:
                if "m_fontAsset" in b:
                    font = INDEX.get(ref_guid(b.get("m_fontAsset")))
                    if ref_guid(b.get("m_fontAsset")) and not font:
                        unresolved.append({"id": nid, "reason": "guid-unresolved",
                                           "detail": "폰트 GUID %s" % ref_guid(b.get("m_fontAsset"))})
                    text = {"component": cname, "font": font, "size": float(b.get("m_fontSize", 0) or 0),
                            "color": color_hex(b.get("m_fontColor")),
                            "autoSize": bool(int(b.get("m_enableAutoSizing", 0) or 0)),
                            "sizeMin": float(b.get("m_fontSizeMin", 0) or 0),
                            "sizeMax": float(b.get("m_fontSizeMax", 0) or 0),
                            "bold": bool(int(b.get("m_fontStyle", 0) or 0) & 1),
                            "content": str(b.get("m_text", ""))[:60]}
                else:
                    fd = b.get("m_FontData") or {}
                    text = {"component": cname, "font": INDEX.get(ref_guid(fd.get("m_Font"))),
                            "size": float(fd.get("m_FontSize", 0) or 0), "color": color_hex(b.get("m_Color")),
                            "autoSize": bool(int(fd.get("m_BestFit", 0) or 0)),
                            "sizeMin": float(fd.get("m_MinSize", 0) or 0), "sizeMax": float(fd.get("m_MaxSize", 0) or 0),
                            "bold": bool(int(fd.get("m_FontStyle", 0) or 0) & 1),
                            "content": str(b.get("m_Text", ""))[:60]}
            elif graphic is None and "m_Color" in b and "m_RaycastTarget" in b:
                sp = sprite_info(b.get("m_Sprite")) if "m_Sprite" in b else None
                # 스프라이트가 있으면 그게 실제 텍스처(예: ParticleImage.mainTexture). m_Texture 는 스프라이트가 없을 때만.
                if not sp and "m_Texture" in b and ref_guid(b.get("m_Texture")):
                    sp = {"guid": ref_guid(b["m_Texture"]), "fileID": ref_id(b["m_Texture"]),
                          "path": INDEX.get(ref_guid(b["m_Texture"])), "name": None, "border": None}
                if sp and not sp["path"]:
                    unresolved.append({"id": nid, "reason": "guid-unresolved", "detail": "스프라이트 GUID %s" % sp["guid"]})
                graphic = {"type": cname, "color": color_hex(b.get("m_Color")), "sprite": sp,
                           "imageType": IMAGE_TYPES.get(int(b["m_Type"])) if "m_Type" in b else None,
                           "raycast": bool(int(b.get("m_RaycastTarget", 0) or 0)),
                           "material": INDEX.get(ref_guid(b.get("m_Material")))}
                if "m_Sprite" in b and sp is None and graphic["color"][-2:] != "00":
                    unresolved.append({"id": nid, "reason": "sprite-missing",
                                       "detail": "m_Sprite 비어 있음 — 코드에서 지정하거나 단색 패널"})
            if "m_Spacing" in b and ("m_Padding" in b):
                pd = b.get("m_Padding") or {}
                sp = b.get("m_Spacing")
                layout = {"type": cname, "spacing": vec(sp) if isinstance(sp, dict) else float(sp or 0),
                          "padding": [pd.get("m_Left", 0), pd.get("m_Right", 0), pd.get("m_Top", 0), pd.get("m_Bottom", 0)]}
                if "m_CellSize" in b:
                    layout["cellSize"] = vec(b.get("m_CellSize"))
            sel = selectable_info(cname, b)
            if sel and selectable is None:
                selectable = sel
        rect = None
        size = parent_size
        if objs[tf]["cls"] == 224:
            amin, amax = vec(tb.get("m_AnchorMin")), vec(tb.get("m_AnchorMax"))
            sd = vec(tb.get("m_SizeDelta"))
            w = parent_size[0] * (amax[0] - amin[0]) + sd[0]
            h = parent_size[1] * (amax[1] - amin[1]) + sd[1]
            size = (w, h)
            sc = vec(tb.get("m_LocalScale"), default=1.0)
            rect = {"w": round(w, 1), "h": round(h, 1), "sizeDelta": sd, "anchorMin": amin, "anchorMax": amax,
                    "pivot": vec(tb.get("m_Pivot")), "pos": vec(tb.get("m_AnchoredPosition")), "scale": sc}
        owner = objs[tf].get("owner")
        nested = None
        if owner:
            nested = {"prefab": owner["prefab"], "guid": owner["guid"],
                      "instanceRoot": by_tf.get(owner.get("rootTransform"), path)}
        kids = children.get(tf, [])
        node = {"id": nid, "name": name, "path": path,
                "parent": None if parent_path is None else "%s#%s" % (rel, parent_path),
                "depth": depth, "active": bool(int(gob.get("m_IsActive", 1) or 0)), "children": len(kids),
                "components": comp_names, "rect": rect, "graphic": graphic, "text": text, "layout": layout,
                "selectable": selectable, "nested": nested, "canvas": canvas, "flags": sorted(set(flags)),
                "screen": screen}
        by_tf[tf] = path
        if not kids and (layout or "wrapContent" in flags or "runtimeLoader" in flags or tf in scroll_contents):
            detail = "자식 없는 컨테이너 (%s)" % ", ".join(
                x for x, ok in (("LayoutGroup", layout), ("WrapContent", "wrapContent" in flags),
                                ("ResourcesLoader", "runtimeLoader" in flags), ("ScrollRect.content", tf in scroll_contents)) if ok)
            unresolved.append({"id": nid, "reason": "runtime-container", "detail": detail})
        nodes.append(node)
        for k in kids:
            walk(k, path, size, depth + 1)

    walk(roots[0], None, (float(ref["width"]), float(ref["height"])), 0)
    seen = set()
    for kind, oid, detail in ex.unresolved:
        key = (kind, oid)
        if key not in seen:
            seen.add(key)
            unresolved.append({"id": "%s#(instance %s)" % (rel, oid), "reason": kind, "detail": detail})
    for tf in orphans:
        unresolved.append({"id": "%s#(transform %s)" % (rel, tf), "reason": "nested-missing",
                           "detail": "부모를 찾지 못한 Transform (중첩 원본 누락 추정)"})
    return nodes, unresolved


def inventory(batch, screen, rel):
    nodes, unresolved = build_nodes(rel, screen)
    return {"batch": batch, "screen": screen, "prefab": rel, "parsedAt": C.now_iso(),
            "nodes": nodes, "unresolved": unresolved}


# ---------------------------------------------------------------- CLI
def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch")
    ap.add_argument("--screen")
    ap.add_argument("--show")
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.reindex:
        INDEX._build()
        return 0
    if a.show:
        nodes, unresolved = build_nodes(a.show.replace("\\", "/"), "show")
        for n in nodes[:200]:
            r = n["rect"] or {}
            print("%s%s  %s  %sx%s" % ("  " * n["depth"], n["name"], ",".join(n["components"]),
                                       r.get("w"), r.get("h")))
        print("노드 %d, unresolved %d" % (len(nodes), len(unresolved)))
        return 0
    if not (a.batch and a.screen):
        ap.print_help()
        return 2
    b = C.load_json(C.p("batches", a.batch + ".json"))
    if not b:
        print("batches/%s.json 없음 — H1(batch.py create)이 먼저 필요" % a.batch)
        return 1
    scr = [s for s in b["screens"] if s["slug"] == a.screen]
    if not scr:
        print("배치 %s 에 화면 '%s' 없음" % (a.batch, a.screen))
        return 1
    inv = inventory(a.batch, a.screen, scr[0]["prefab"])
    out = C.p("data", "inventory", a.batch, a.screen + ".json")
    tmp = C.write_tmp(out, inv)
    print("노드 %d, unresolved %d → %s" % (len(inv["nodes"]), len(inv["unresolved"]), tmp))
    print("다음: python scripts/validate.py --rename %s" % os.path.relpath(tmp, C.ROOT).replace("\\", "/"))
    return 0


def _pick(folder, want_nested=False):
    base = os.path.join(C.unity_root(), C.project()["ui_root"], folder)
    cands = []
    for dp, _dn, fn in os.walk(base):
        for f in sorted(fn):
            if f.endswith(".prefab"):
                cands.append(os.path.join(dp, f))
    cands.sort()
    for c in cands:
        if not want_nested:
            return c
        with open(c, "r", encoding="utf-8") as fh:
            if "--- !u!1001 " in fh.read():
                return c
    return cands[0] if cands else None


def _selftest_picks():
    """ui_root 아래 서로 다른 폴더의 프리팹 3개 — 첫째는 중첩 프리팹(PrefabInstance)이 있는 것."""
    base = os.path.join(C.unity_root(), C.project()["ui_root"])
    dirs = sorted({os.path.relpath(dp, base) for dp, _dn, fn in os.walk(base) if any(f.endswith(".prefab") for f in fn)})
    nested = next((p for d in dirs for p in [_pick(d, want_nested=True)] if p and "--- !u!1001 " in open(p, encoding="utf-8").read()), None)
    picks = [nested] if nested else []
    for d in dirs:
        p = _pick(d)
        if p and len(picks) < 3 and os.path.dirname(p) not in {os.path.dirname(x) for x in picks}:
            picks.append(p)
    return picks


def selftest():
    import validate
    root = C.unity_root()
    picks = _selftest_picks()
    assert len(picks) == 3, "서로 다른 폴더의 UI 프리팹 3개(하나는 중첩 포함)가 필요: %s" % picks
    rels = [os.path.relpath(x, root).replace("\\", "/") for x in picks]
    assert len({r.split("/")[-3] for r in rels}) == 3 or len(set(os.path.dirname(r) for r in rels)) == 3
    nested_seen = xor_ok = 0
    for rel in rels:
        inv = inventory("b1", "selftest", rel)
        nodes = inv["nodes"]
        assert nodes, "%s: 노드 0개" % rel
        ids = [n["id"] for n in nodes]
        assert len(ids) == len(set(ids)), "%s: 노드 ID 중복" % rel
        assert nodes[0]["depth"] == 0 and nodes[0]["parent"] is None
        errs = validate.validate_obj(inv, "inventory")
        assert not errs, "%s: 스키마 오류 %s" % (rel, errs[:3])
        docs = load_docs(os.path.join(root, rel))
        ex = expand(rel)
        for fid, d in docs.items():
            if d["stripped"]:
                inst = ref_id(d["body"].get("m_PrefabInstance"))
                src = ref_id(d["body"].get("m_CorrespondingSourceObject"))
                xor_ok += (inst ^ src) & MASK == fid  # Unity 가 만든 id 는 대개 이 공식이지만 재저장 뒤엔 아닐 수 있다
                assert ex.alias.get(fid, fid) in ex.objs, "%s: stripped 객체 %s 가 펼친 결과에 없음" % (rel, fid)
        n_nested = sum(1 for n in nodes if n["nested"])
        nested_seen += n_nested
        print("  %s: 노드 %d (중첩 %d), unresolved %d" % (rel, len(nodes), n_nested, len(inv["unresolved"])))
    assert nested_seen > 0, "중첩 프리팹 노드를 하나도 펼치지 못함"
    body = {"m_SizeDelta": {"x": 1, "y": 2}, "m_Children": []}
    apply_mod(body, "m_SizeDelta.x", "337", {"fileID": 0})
    apply_mod(body, "m_Name", "Btn", {"fileID": 0})
    assert body["m_SizeDelta"]["x"] == 337 and body["m_Name"] == "Btn"
    print("parse_prefab.py selftest ok (stripped id 공식 일치 %d)" % xor_ok)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
