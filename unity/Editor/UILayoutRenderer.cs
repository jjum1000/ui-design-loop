// ui-audit screen layout-map renderer (S1). Editor-only assembly; renders prefabs, never saves assets.
// Instantiates each prefab in an empty scene, renders it and writes the Unity-computed screen rect of every node.
// Run: Unity.exe -batchmode -quit -projectPath <project> -executeMethod ClaudeBridge.UILayoutRenderer.Run -logFile <log>
//      [-uiAuditFont <TMP font asset path>]   (do not pass -nographics — rendering needs a GPU device)
// Input:  ui-audit/previews/layout/_list.json  {items:[{kind,slug,path}], loaderMap:[{key,path}], samples:bool}
// Output: ui-audit/previews/layout/<kind>/<slug>.png + <slug>.raw.json, _render-result.json, _render-log.txt
//         coordinates: saved-PNG pixels, top-left origin, relative to the cropped area
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.UI;
using Object = UnityEngine.Object;

namespace ClaudeBridge
{
    public static class UILayoutRenderer
    {
        #region Coding rule : Value
        private const int RenderWidth = 1920;
        private const int RenderHeight = 1080;
        private const int MaxScreenWidth = 1280;
        private const int MaxTemplateSize = 800;
        private const int UnloadEvery = 25;
        private const int MaxLoaderDepth = 4;
        private const int SampleCount = 3;
        private const string FontArg = "-uiAuditFont";  // optional fallback TMP font for text with a missing font asset
        private static readonly HashSet<string> SkipComps = new HashSet<string> { "Transform", "RectTransform", "CanvasRenderer" };

        [Serializable] private class Item { public string kind; public string slug; public string path; }
        [Serializable] private class LoaderKey { public string key; public string path; }
        [Serializable] private class Input { public Item[] items; public LoaderKey[] loaderMap; public bool samples; }

        [Serializable]
        private class Node
        {
            public string path, name, nested, comps;
            public int depth;
            public bool active, self, loader, sample;
            public float x, y, w, h;
        }

        [Serializable]
        private class Raw
        {
            public string slug, kind, path;
            public int width, height, cropX, cropY, cropW, cropH;
            public float scale;
            public List<Node> nodes = new List<Node>();
        }

        [Serializable]
        private class Result
        {
            public string kind, slug, path, error;
            public bool ok;
            public int w, h, nodes, loaders, loaderFailed, samples, fontsFixed;
            public long ms;
        }

        [Serializable] private class ResultList { public List<Result> results = new List<Result>(); }

        private static string _outDir;
        private static StreamWriter _log;
        private static Dictionary<string, string> _loaderMap;
        private static bool _samples;
        private static HashSet<GameObject> _loaderRoots;
        private static HashSet<GameObject> _sampleRoots;
        #endregion

        #region Coding rule : Function
        public static void Run()
        {
            string root = Path.GetDirectoryName(Application.dataPath);
            _outDir = Path.Combine(root, "ui-audit", "previews", "layout");
            Directory.CreateDirectory(_outDir);
            int exitCode = 0;
            using (_log = new StreamWriter(Path.Combine(_outDir, "_render-log.txt"), false, new UTF8Encoding(false)))
            {
                try
                {
                    var input = JsonUtility.FromJson<Input>(File.ReadAllText(Path.Combine(_outDir, "_list.json")));
                    _loaderMap = new Dictionary<string, string>();
                    foreach (var k in input.loaderMap ?? new LoaderKey[0])
                        _loaderMap[k.key] = k.path;
                    _samples = input.samples;
                    RenderAll(input.items ?? new Item[0]);
                }
                catch (Exception e)
                {
                    Log("FATAL " + e);
                    exitCode = 1;
                }
            }
            EditorApplication.Exit(exitCode);
        }

        private static void Log(string line)
        {
            _log.WriteLine(DateTime.Now.ToString("HH:mm:ss") + " " + line);
            _log.Flush();
        }

        private static void RenderAll(Item[] items)
        {
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var rt = new RenderTexture(RenderWidth, RenderHeight, 24, RenderTextureFormat.ARGB32);
            var camGo = new GameObject("__LayoutCamera");
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0, 0, 0, 0);
            cam.orthographic = true;
            cam.targetTexture = rt;
            cam.enabled = false;
            var results = new ResultList();
            for (int i = 0; i < items.Length; i++)
            {
                var r = RenderOne(items[i], cam, rt);
                results.results.Add(r);
                Log(string.Format("[{0}/{1}] {2} {3}/{4} {5}x{6} nodes {7} loaders {8}/{9} samples {10} {11}ms {12}", i + 1, items.Length,
                    r.ok ? "ok  " : "FAIL", r.kind, r.slug, r.w, r.h, r.nodes, r.loaders - r.loaderFailed, r.loaders, r.samples, r.ms, r.error));
                if ((i + 1) % UnloadEvery == 0)
                    EditorUtility.UnloadUnusedAssetsImmediate();
            }
            Object.DestroyImmediate(camGo);
            rt.Release();
            Object.DestroyImmediate(rt);
            File.WriteAllText(Path.Combine(_outDir, "_render-result.json"), JsonUtility.ToJson(results, true), new UTF8Encoding(false));
            Log(string.Format("끝: 성공 {0} / {1}", results.results.Count(x => x.ok), results.results.Count));
        }

        private static Result RenderOne(Item item, Camera cam, RenderTexture rt)
        {
            var r = new Result { kind = item.kind, slug = item.slug, path = item.path };
            var sw = Stopwatch.StartNew();
            GameObject canvasGo = null;
            GameObject inst = null;
            _loaderRoots = new HashSet<GameObject>();
            _sampleRoots = new HashSet<GameObject>();
            try
            {
                var asset = AssetDatabase.LoadAssetAtPath<GameObject>(item.path);
                if (asset == null)
                    throw new Exception("프리팹 로드 실패");
                canvasGo = new GameObject("__LayoutCanvas", typeof(RectTransform));
                var canvas = canvasGo.AddComponent<Canvas>();
                canvas.renderMode = RenderMode.ScreenSpaceCamera;
                canvas.worldCamera = cam;
                canvas.planeDistance = 10;
                inst = (GameObject)PrefabUtility.InstantiatePrefab(asset);
                inst.name = asset.name;
                inst.SetActive(true);
                var rect = inst.GetComponent<RectTransform>();
                if (rect == null)
                    throw new Exception("RectTransform 없음(UI 프리팹 아님)");
                Place(rect, canvasGo.transform, item.kind == "screen");
                r.loaders = ExpandLoaders(inst, 0, ref r.loaderFailed);
                if (_samples)
                    r.samples = AddSamples(inst, ref r.loaderFailed);
                r.fontsFixed = FixFonts(inst);
                ForceCameras(inst, cam);
                Relayout(rect, inst);
                cam.Render();
                Rect crop = item.kind == "screen" ? new Rect(0, 0, RenderWidth, RenderHeight) : ScreenBounds(rect, inst, cam);
                int maxW = item.kind == "screen" ? MaxScreenWidth : MaxTemplateSize;
                int maxH = item.kind == "screen" ? int.MaxValue : MaxTemplateSize;
                string dir = Path.Combine(_outDir, item.kind);
                Directory.CreateDirectory(dir);
                float scale = SavePng(rt, crop, Path.Combine(dir, item.slug + ".png"), maxW, maxH, out r.w, out r.h);
                var raw = Collect(item, inst, cam, crop, scale, r.w, r.h);
                r.nodes = raw.nodes.Count;
                File.WriteAllText(Path.Combine(dir, item.slug + ".raw.json"), JsonUtility.ToJson(raw), new UTF8Encoding(false));
                r.ok = true;
            }
            catch (Exception e)
            {
                r.error = e.GetType().Name + ": " + e.Message.Replace("\n", " ");
            }
            finally
            {
                if (inst != null) Object.DestroyImmediate(inst);
                if (canvasGo != null) Object.DestroyImmediate(canvasGo);
                r.ms = sw.ElapsedMilliseconds;
            }
            return r;
        }

        private static void ForceCameras(GameObject inst, Camera cam)
        {
            foreach (var c in inst.GetComponentsInChildren<Canvas>(true))
            {
                if (c.renderMode != RenderMode.WorldSpace)
                {
                    c.renderMode = RenderMode.ScreenSpaceCamera;
                    c.worldCamera = cam;
                }
            }
        }

        /// <summary>레이아웃 그룹 계산 → 캔버스 갱신 → 텍스트 메시 갱신을 두 번 돌려 크기 맞춤(ContentSizeFitter)까지 반영한다.</summary>
        private static void Relayout(RectTransform rect, GameObject inst)
        {
            for (int pass = 0; pass < 2; pass++)
            {
                LayoutRebuilder.ForceRebuildLayoutImmediate(rect);
                Canvas.ForceUpdateCanvases();
                ForceTextMeshes(inst);
            }
            LayoutRebuilder.ForceRebuildLayoutImmediate(rect);
            Canvas.ForceUpdateCanvases();
        }

        /// <summary>늘린 앵커면 캔버스를 채운다(화면은 크기와 무관, 템플릿은 큰 것만 — 기존 썸네일 규칙).
        /// 고정 앵커 루트(가운데 팝업 등)는 원래 크기로 가운데 — 게임 캔버스에서와 같은 자리다. 좌표는 렌더 결과에서 재므로 어긋나지 않는다.</summary>
        private static void Place(RectTransform rect, Transform canvas, bool screen)
        {
            Vector2 size = rect.rect.size;
            bool stretch = rect.anchorMin != rect.anchorMax;
            rect.SetParent(canvas, false);
            rect.localScale = Vector3.one;
            rect.localRotation = Quaternion.identity;
            if (stretch && (screen || size.x <= 0 || size.y <= 0 || size.x >= RenderWidth * 0.5f || size.y >= RenderHeight * 0.5f))
            {
                rect.anchorMin = Vector2.zero;
                rect.anchorMax = Vector2.one;
                rect.offsetMin = Vector2.zero;
                rect.offsetMax = Vector2.zero;
                return;
            }
            rect.anchorMin = rect.anchorMax = new Vector2(0.5f, 0.5f);
            rect.sizeDelta = new Vector2(Mathf.Max(size.x, 1), Mathf.Max(size.y, 1));
            rect.anchoredPosition = new Vector2((rect.pivot.x - 0.5f) * rect.sizeDelta.x, (rect.pivot.y - 0.5f) * rect.sizeDelta.y);
        }

        private static GameObject Spawn(GameObject prefab, Transform parent)
        {
            var child = (GameObject)PrefabUtility.InstantiatePrefab(prefab, parent);
            child.name = prefab.name;
            child.SetActive(true);
            return child;
        }

        /// <summary>ResourcesLoader 의 대상 프리팹을 붙인다(guids 우선, 없으면 주소 맵). 반환 = 시도 수.</summary>
        private static int ExpandLoaders(GameObject go, int depth, ref int failed)
        {
            if (depth >= MaxLoaderDepth)
                return 0;
            int tried = 0;
            var loaders = go.GetComponentsInChildren<MonoBehaviour>(true)
                .Where(m => m != null && m.GetType().Name == "ResourcesLoader").ToList();
            foreach (var loader in loaders)
            {
                var so = new SerializedObject(loader);
                if (so.FindProperty("target")?.objectReferenceValue != null)
                    continue;
                tried++;
                string key = so.FindProperty("addressableKey")?.stringValue ?? "";
                string path = FirstGuidPath(so.FindProperty("guids")?.stringValue);
                if (string.IsNullOrEmpty(path) && !_loaderMap.TryGetValue(key, out path))
                    path = null;
                var prefab = string.IsNullOrEmpty(path) ? null : AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab == null)
                {
                    failed++;
                    continue;
                }
                var parent = so.FindProperty("parent")?.objectReferenceValue as Transform;
                var child = Spawn(prefab, parent != null ? parent : loader.transform);
                _loaderRoots.Add(child);
                tried += ExpandLoaders(child, depth + 1, ref failed);
            }
            return tried;
        }

        private static string FirstGuidPath(string guids)
        {
            foreach (var g in (guids ?? "").Split(new[] { ',', ';', ' ', '|' }, StringSplitOptions.RemoveEmptyEntries))
            {
                string path = AssetDatabase.GUIDToAssetPath(g.Trim());
                if (!string.IsNullOrEmpty(path))
                    return path;
            }
            return null;
        }

        /// <summary>WrapContent 의 첫 아이템 프리팹(wrapContentPrefabDatas[0].guids)을 비어 있는 ScrollRect.content 에 예시로 꽂는다.</summary>
        private static int AddSamples(GameObject inst, ref int loaderFailed)
        {
            int added = 0;
            var wraps = inst.GetComponentsInChildren<MonoBehaviour>(true).Where(m => m != null && m.GetType().Name == "WrapContent").ToList();
            foreach (var wrap in wraps)
            {
                var so = new SerializedObject(wrap);
                string path = FirstGuidPath(so.FindProperty("wrapContentPrefabDatas.Array.data[0].guids")?.stringValue);
                var prefab = string.IsNullOrEmpty(path) ? null : AssetDatabase.LoadAssetAtPath<GameObject>(path);
                var sr = wrap.GetComponentInChildren<ScrollRect>(true);
                if (sr == null)
                    sr = wrap.GetComponentInParent<ScrollRect>(true);
                if (prefab == null || sr == null || sr.content == null)
                    continue;
                if (sr.content.Cast<Transform>().Any(t => t.gameObject.activeSelf))
                    continue;
                float pad = so.FindProperty("wrapContentPrefabDatas.Array.data[0].mPadding")?.floatValue ?? 0f;
                bool grid = so.FindProperty("gridView")?.objectReferenceValue != null;
                bool hasLayout = sr.content.GetComponent<LayoutGroup>() != null;
                float viewW = (sr.viewport != null ? sr.viewport : (RectTransform)sr.transform).rect.width;
                float x = 0, y = 0;
                for (int i = 0; i < SampleCount; i++)
                {
                    var child = Spawn(prefab, sr.content);
                    _sampleRoots.Add(child);
                    added++;
                    ExpandLoaders(child, 0, ref loaderFailed);
                    var crt = child.GetComponent<RectTransform>();
                    if (crt == null || hasLayout)
                        continue;
                    Vector2 size = crt.rect.size;
                    crt.anchorMin = crt.anchorMax = new Vector2(0, 1);
                    crt.anchoredPosition = new Vector2(x + crt.pivot.x * size.x, -y - (1 - crt.pivot.y) * size.y);
                    if (!sr.vertical && sr.horizontal)
                        x += size.x + pad;
                    else if (grid && x + 2 * size.x + pad <= viewW)
                        x += size.x + pad;
                    else
                    {
                        x = 0;
                        y += size.y + pad;
                    }
                }
            }
            return added;
        }

        /// <summary>CustomTextMeshProUGUI 폰트가 null 이면 fontPath 의 폰트 에셋(없으면 기본 폰트)으로 채운다.</summary>
        private static int FixFonts(GameObject go)
        {
            int fixedCount = 0;
            Object fallback = null;
            foreach (var m in go.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (m == null || m.GetType().Name != "CustomTextMeshProUGUI")
                    continue;
                var so = new SerializedObject(m);
                var fontProp = so.FindProperty("m_fontAsset");
                if (fontProp == null || fontProp.objectReferenceValue != null)
                    continue;
                string fontPath = so.FindProperty("fontPath")?.stringValue ?? "";
                string name = fontPath.Contains("/") ? fontPath.Substring(fontPath.LastIndexOf('/') + 1) : fontPath;
                Object font = null;
                if (!string.IsNullOrEmpty(name))
                {
                    string guid = AssetDatabase.FindAssets(name + " t:TMP_FontAsset").FirstOrDefault();
                    if (guid != null)
                        font = AssetDatabase.LoadMainAssetAtPath(AssetDatabase.GUIDToAssetPath(guid));
                }
                if (font == null)
                    font = fallback ?? (fallback = LoadFallbackFont());
                if (font == null)
                    continue;
                fontProp.objectReferenceValue = font;
                so.ApplyModifiedPropertiesWithoutUndo();
                fixedCount++;
            }
            return fixedCount;
        }

        /// <summary>Fallback font from the -uiAuditFont command-line argument (null when not given).</summary>
        private static Object LoadFallbackFont()
        {
            var args = Environment.GetCommandLineArgs();
            int i = Array.IndexOf(args, FontArg);
            string path = i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
            return string.IsNullOrEmpty(path) ? null : AssetDatabase.LoadMainAssetAtPath(path);
        }

        private static void ForceTextMeshes(GameObject go)
        {
            foreach (var m in go.GetComponentsInChildren<MonoBehaviour>(true))
            {
                if (m == null) continue;
                var mi = m.GetType().GetMethod("ForceMeshUpdate", BindingFlags.Public | BindingFlags.Instance);
                if (mi == null) continue;
                try
                {
                    var ps = mi.GetParameters();
                    mi.Invoke(m, ps.Select(p => p.HasDefaultValue ? p.DefaultValue : null).ToArray());
                }
                catch (Exception)
                {
                    // 텍스트 갱신 실패는 이미지에서 글자가 비는 것으로 드러난다
                }
            }
        }

        /// <summary>노드마다 월드 모서리 → 화면 좌표 → 잘라낸 영역 기준(왼쪽 위 원점)·저장 PNG 배율로 변환.</summary>
        private static Raw Collect(Item item, GameObject inst, Camera cam, Rect crop, float scale, int w, int h)
        {
            var raw = new Raw
            {
                slug = item.slug, kind = item.kind, path = item.path, width = w, height = h, scale = scale,
                cropX = (int)crop.x, cropY = (int)crop.y, cropW = (int)crop.width, cropH = (int)crop.height
            };
            var corners = new Vector3[4];
            Walk(inst.transform, null, 0, false, false, (t, path, depth, loader, sample) =>
            {
                var node = new Node
                {
                    path = path, name = t.name, depth = depth, active = t.gameObject.activeInHierarchy, self = t.gameObject.activeSelf,
                    loader = loader, sample = sample, comps = Comps(t.gameObject),
                    nested = t != inst.transform && PrefabUtility.IsAnyPrefabInstanceRoot(t.gameObject)
                        ? PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(t.gameObject) : ""
                };
                var rt = t as RectTransform;
                if (rt != null)
                {
                    rt.GetWorldCorners(corners);
                    float xMin = float.MaxValue, yMin = float.MaxValue, xMax = float.MinValue, yMax = float.MinValue;
                    foreach (var c in corners)
                    {
                        Vector3 s = cam.WorldToScreenPoint(c);
                        xMin = Mathf.Min(xMin, s.x); yMin = Mathf.Min(yMin, s.y);
                        xMax = Mathf.Max(xMax, s.x); yMax = Mathf.Max(yMax, s.y);
                    }
                    node.x = (xMin - crop.x) * scale;
                    node.y = (crop.y + crop.height - yMax) * scale;
                    node.w = (xMax - xMin) * scale;
                    node.h = (yMax - yMin) * scale;
                }
                raw.nodes.Add(node);
            });
            return raw;
        }

        private static void Walk(Transform t, string parentPath, int depth, bool loader, bool sample, Action<Transform, string, int, bool, bool> visit)
        {
            loader |= _loaderRoots.Contains(t.gameObject);
            sample |= _sampleRoots.Contains(t.gameObject);
            string path = parentPath == null ? t.name : parentPath + "/" + t.name;
            visit(t, path, depth, loader, sample);
            foreach (Transform c in t)
                Walk(c, path, depth + 1, loader, sample, visit);
        }

        private static string Comps(GameObject go)
        {
            return string.Join(",", go.GetComponents<Component>().Where(c => c != null).Select(c => c.GetType().Name)
                .Where(n => !SkipComps.Contains(n)).Take(6));
        }

        /// <summary>루트 사각형과 보이는 자식(CanvasRenderer)의 화면 경계 합집합 → 렌더 텍스처 안으로 자른 영역.</summary>
        private static Rect ScreenBounds(RectTransform root, GameObject inst, Camera cam)
        {
            float xMin = float.MaxValue, yMin = float.MaxValue, xMax = float.MinValue, yMax = float.MinValue;
            var corners = new Vector3[4];
            var rects = new List<RectTransform> { root };
            rects.AddRange(inst.GetComponentsInChildren<CanvasRenderer>(false).Select(c => c.transform as RectTransform).Where(x => x != null));
            foreach (var rt in rects)
            {
                if (rt.rect.width <= 0 && rt.rect.height <= 0) continue;
                rt.GetWorldCorners(corners);
                foreach (var c in corners)
                {
                    Vector3 s = cam.WorldToScreenPoint(c);
                    xMin = Mathf.Min(xMin, s.x); yMin = Mathf.Min(yMin, s.y);
                    xMax = Mathf.Max(xMax, s.x); yMax = Mathf.Max(yMax, s.y);
                }
            }
            if (xMin > xMax) return new Rect(0, 0, RenderWidth, RenderHeight);
            xMin = Mathf.Clamp(Mathf.Floor(xMin), 0, RenderWidth - 1); yMin = Mathf.Clamp(Mathf.Floor(yMin), 0, RenderHeight - 1);
            xMax = Mathf.Clamp(Mathf.Ceil(xMax), xMin + 1, RenderWidth); yMax = Mathf.Clamp(Mathf.Ceil(yMax), yMin + 1, RenderHeight);
            return new Rect(xMin, yMin, xMax - xMin, yMax - yMin);
        }

        /// <summary>잘라 읽고 최대 크기로 줄여 저장. 반환 = 배율(저장 픽셀 / 렌더 픽셀).</summary>
        private static float SavePng(RenderTexture rt, Rect crop, string file, int maxW, int maxH, out int w, out int h)
        {
            var prev = RenderTexture.active;
            RenderTexture.active = rt;
            var tex = new Texture2D((int)crop.width, (int)crop.height, TextureFormat.RGBA32, false);
            try
            {
                tex.ReadPixels(crop, 0, 0);
                tex.Apply();
                RenderTexture.active = prev;
                float scale = Mathf.Min(1f, Mathf.Min((float)maxW / tex.width, (float)maxH / tex.height));
                if (scale < 1f)
                {
                    int sw = Mathf.Max(1, Mathf.RoundToInt(tex.width * scale)), sh = Mathf.Max(1, Mathf.RoundToInt(tex.height * scale));
                    scale = (float)sw / tex.width;
                    var small = RenderTexture.GetTemporary(sw, sh, 0, RenderTextureFormat.ARGB32);
                    Graphics.Blit(tex, small);
                    RenderTexture.active = small;
                    var t2 = new Texture2D(sw, sh, TextureFormat.RGBA32, false);
                    t2.ReadPixels(new Rect(0, 0, sw, sh), 0, 0);
                    t2.Apply();
                    RenderTexture.active = prev;
                    RenderTexture.ReleaseTemporary(small);
                    Object.DestroyImmediate(tex);
                    tex = t2;
                }
                File.WriteAllBytes(file, tex.EncodeToPNG());
                w = tex.width;
                h = tex.height;
                return scale;
            }
            finally
            {
                RenderTexture.active = prev;
                Object.DestroyImmediate(tex);
            }
        }
        #endregion
    }
}
