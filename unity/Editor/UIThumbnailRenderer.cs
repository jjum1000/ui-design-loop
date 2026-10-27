// ui-audit template-catalog thumbnail renderer (T6). Editor-only assembly; renders prefabs, never saves assets.
// Instantiates each prefab in an empty scene, renders it and writes a PNG (prefab and scene assets are not modified).
// Run: Unity.exe -batchmode -quit -projectPath <project> -executeMethod ClaudeBridge.UIThumbnailRenderer.Run -logFile <log>
//      [-uiAuditFont <TMP font asset path>]   (do not pass -nographics — rendering needs a GPU device)
// Input:  ui-audit/previews/templates/_list.json  {items:[{slug,path}], loaderMap:[{key,path}], usageCheck:[path]}
// Output: ui-audit/previews/templates/<slug>.png, _render-result.json, _render-log.txt, _usage-check.json
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
using Object = UnityEngine.Object;

namespace ClaudeBridge
{
    public static class UIThumbnailRenderer
    {
        #region Coding rule : Value
        private const int RenderWidth = 1920;
        private const int RenderHeight = 1080;
        private const int MaxThumbSize = 640;
        private const int UnloadEvery = 50;
        private const int MaxLoaderDepth = 4;
        private const string FontArg = "-uiAuditFont";  // optional fallback TMP font for text with a missing font asset

        [Serializable] private class Item { public string slug; public string path; }
        [Serializable] private class LoaderKey { public string key; public string path; }
        [Serializable] private class Input { public Item[] items; public LoaderKey[] loaderMap; public string[] usageCheck; }

        private class Result
        {
            public string slug, path, error;
            public bool ok;
            public int w, h, loaders, loaderFailed, fontsFixed;
            public long ms;
        }

        private static string _outDir;
        private static StreamWriter _log;
        private static Dictionary<string, string> _loaderMap;
        #endregion

        #region Coding rule : Function
        public static void Run()
        {
            string root = Path.GetDirectoryName(Application.dataPath);
            _outDir = Path.Combine(root, "ui-audit", "previews", "templates");
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
                    if (input.usageCheck != null && input.usageCheck.Length > 0)
                        UsageCheck(input.usageCheck);
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
            var camGo = new GameObject("__ThumbCamera");
            var cam = camGo.AddComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = new Color(0, 0, 0, 0);
            cam.orthographic = true;
            cam.targetTexture = rt;
            cam.enabled = false;
            var results = new List<Result>();
            for (int i = 0; i < items.Length; i++)
            {
                var r = RenderOne(items[i], cam, rt);
                results.Add(r);
                Log(string.Format("[{0}/{1}] {2} {3} {4}x{5} loaders {6}/{7} fonts {8} {9}ms {10}", i + 1, items.Length,
                    r.ok ? "ok  " : "FAIL", r.slug, r.w, r.h, r.loaders - r.loaderFailed, r.loaders, r.fontsFixed, r.ms, r.error));
                if ((i + 1) % UnloadEvery == 0)
                    EditorUtility.UnloadUnusedAssetsImmediate();
            }
            Object.DestroyImmediate(camGo);
            rt.Release();
            WriteResults(results);
            Log(string.Format("끝: 성공 {0} / {1}", results.Count(x => x.ok), results.Count));
        }

        private static Result RenderOne(Item item, Camera cam, RenderTexture rt)
        {
            var r = new Result { slug = item.slug, path = item.path };
            var sw = Stopwatch.StartNew();
            GameObject canvasGo = null;
            GameObject inst = null;
            try
            {
                var asset = AssetDatabase.LoadAssetAtPath<GameObject>(item.path);
                if (asset == null)
                    throw new Exception("프리팹 로드 실패");
                canvasGo = new GameObject("__ThumbCanvas", typeof(RectTransform));
                var canvas = canvasGo.AddComponent<Canvas>();
                canvas.renderMode = RenderMode.ScreenSpaceCamera;
                canvas.worldCamera = cam;
                canvas.planeDistance = 10;
                inst = (GameObject)Object.Instantiate(asset);
                inst.name = asset.name;
                inst.SetActive(true);
                foreach (var c in inst.GetComponentsInChildren<Canvas>(true))
                {
                    if (c.renderMode != RenderMode.WorldSpace)
                    {
                        c.renderMode = RenderMode.ScreenSpaceCamera;
                        c.worldCamera = cam;
                    }
                }
                var rect = inst.GetComponent<RectTransform>();
                if (rect == null)
                    throw new Exception("RectTransform 없음(UI 프리팹 아님)");
                Place(rect, canvasGo.transform);
                r.loaders = ExpandLoaders(inst, 0, ref r.loaderFailed);
                r.fontsFixed = FixFonts(inst);
                Canvas.ForceUpdateCanvases();
                ForceTextMeshes(inst);
                Canvas.ForceUpdateCanvases();
                cam.Render();
                Rect crop = ScreenBounds(rect, inst, cam);
                SavePng(rt, crop, Path.Combine(_outDir, item.slug + ".png"), out r.w, out r.h);
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

        /// <summary>캔버스 가운데에 둔다. 늘린 앵커면 캔버스를 채우고, 아니면 원래 크기로 가운데 정렬.</summary>
        private static void Place(RectTransform rect, Transform canvas)
        {
            Vector2 size = rect.rect.size;
            bool stretch = rect.anchorMin != rect.anchorMax;
            rect.SetParent(canvas, false);
            rect.localScale = Vector3.one;
            rect.localRotation = Quaternion.identity;
            if (stretch && (size.x <= 0 || size.y <= 0 || size.x >= RenderWidth * 0.5f || size.y >= RenderHeight * 0.5f))
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

        /// <summary>ResourcesLoader 의 대상 프리팹을 인스턴스로 붙인다(guids 우선, 없으면 주소 맵). 반환 = 시도 수.</summary>
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
                string guids = so.FindProperty("guids")?.stringValue ?? "";
                string path = null;
                foreach (var g in guids.Split(new[] { ',', ';', ' ', '|' }, StringSplitOptions.RemoveEmptyEntries))
                {
                    path = AssetDatabase.GUIDToAssetPath(g.Trim());
                    if (!string.IsNullOrEmpty(path)) break;
                }
                if (string.IsNullOrEmpty(path) && !_loaderMap.TryGetValue(key, out path))
                    path = null;
                var prefab = string.IsNullOrEmpty(path) ? null : AssetDatabase.LoadAssetAtPath<GameObject>(path);
                if (prefab == null)
                {
                    failed++;
                    continue;
                }
                var parent = so.FindProperty("parent")?.objectReferenceValue as Transform;
                var child = (GameObject)Object.Instantiate(prefab, parent != null ? parent : loader.transform, false);
                child.SetActive(true);
                tried += ExpandLoaders(child, depth + 1, ref failed);
            }
            return tried;
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
                    // 텍스트 갱신 실패는 썸네일에서 글자가 비는 것으로 드러난다
                }
            }
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

        private static void SavePng(RenderTexture rt, Rect crop, string file, out int w, out int h)
        {
            var prev = RenderTexture.active;
            RenderTexture.active = rt;
            var tex = new Texture2D((int)crop.width, (int)crop.height, TextureFormat.RGBA32, false);
            tex.ReadPixels(crop, 0, 0);
            tex.Apply();
            RenderTexture.active = prev;
            float scale = Mathf.Min(1f, (float)MaxThumbSize / Mathf.Max(tex.width, tex.height));
            if (scale < 1f)
            {
                int sw = Mathf.Max(1, Mathf.RoundToInt(tex.width * scale)), sh = Mathf.Max(1, Mathf.RoundToInt(tex.height * scale));
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
            Object.DestroyImmediate(tex);
        }

        /// <summary>T2a 독립 대조: 표본 템플릿마다 AssetDatabase.GetDependencies(직접)로 그것을 쓰는 프리팹 수.</summary>
        private static void UsageCheck(string[] templates)
        {
            var want = new HashSet<string>(templates);
            var users = templates.ToDictionary(t => t, t => new List<string>());
            var all = AssetDatabase.FindAssets("t:Prefab", new[] { "Assets" }).Select(AssetDatabase.GUIDToAssetPath).ToArray();
            foreach (var p in all)
            {
                foreach (var d in AssetDatabase.GetDependencies(p, false))
                    if (d != p && want.Contains(d))
                        users[d].Add(p);
            }
            var sb = new StringBuilder("{\"prefabsScanned\": " + all.Length + ", \"templates\": {");
            sb.Append(string.Join(",", templates.Select(t => "\n \"" + Esc(t) + "\": [" +
                string.Join(", ", users[t].OrderBy(x => x, StringComparer.Ordinal).Select(u => "\"" + Esc(u) + "\"")) + "]")));
            sb.Append("\n}}\n");
            File.WriteAllText(Path.Combine(_outDir, "_usage-check.json"), sb.ToString(), new UTF8Encoding(false));
            Log("usage-check: 프리팹 " + all.Length + "개, 표본 " + templates.Length + "개");
        }

        private static void WriteResults(List<Result> results)
        {
            var sb = new StringBuilder("[");
            sb.Append(string.Join(",", results.Select(r => string.Format(
                "\n {{\"slug\": \"{0}\", \"path\": \"{1}\", \"ok\": {2}, \"error\": {3}, \"w\": {4}, \"h\": {5}, \"loaders\": {6}, \"loaderFailed\": {7}, \"fontsFixed\": {8}, \"ms\": {9}}}",
                Esc(r.slug), Esc(r.path), r.ok ? "true" : "false", r.error == null ? "null" : "\"" + Esc(r.error) + "\"",
                r.w, r.h, r.loaders, r.loaderFailed, r.fontsFixed, r.ms))));
            sb.Append("\n]\n");
            File.WriteAllText(Path.Combine(_outDir, "_render-result.json"), sb.ToString(), new UTF8Encoding(false));
        }

        private static string Esc(string s)
        {
            return (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", " ").Replace("\r", " ").Replace("\t", " ");
        }
        #endregion
    }
}
