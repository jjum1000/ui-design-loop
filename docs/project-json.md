# `ui-audit/project.json` reference

`project.json` sits at the root of the installed workspace (`<unity-project>/ui-audit/project.json`) and holds everything project-specific that the toolkit scripts need: where the Unity project and its UI prefabs are, which folders count as shared, how scenes and code load UI, and a few presentation options. You write it once during A0 (see the `ui-audit` skill and `skills/ui-audit/references/kickoff-a0.md`).

- Paths marked "Unity-relative" are relative to the Unity project root, with `/` separators (`Assets/...`, `Packages/...`).
- `unity_root` is relative to `ui-audit/` itself (normally `".."`).
- The JSON schema `ui-audit/schemas/project.json` (generated from `scripts/schema_defs.py`) checks the **required** keys and the types of the basic keys; `python scripts/validate.py project.json` and `python scripts/a0_setup.py --check` run it. Extra keys are allowed (the schema has no `additionalProperties: false`), and the optional keys below are read with defaults by the scripts that use them.
- Values in this document were collected from the toolkit scripts (`C.project()` / `project.json` reads in `toolkit/scripts/*.py`). If a script and this page disagree, the script wins; please open an issue.

## Required keys (schema)

| Key | Type | Default | Read by | Description |
|---|---|---|---|---|
| `name` | string | - (required) | schema only | Display name of the project. |
| `unity_root` | string | `".."` when `project.json` is missing | `common.py` (`C.unity_root()`), therefore every script that reads the Unity project | Unity project root, relative to `ui-audit/`. |
| `ui_system` | `"uGUI"` \| `"UI Toolkit"` | - (required) | schema only | UI system of the project. The parsers support **uGUI** (+ TextMeshPro) prefabs; UI Toolkit is not parsed. |
| `ui_root` | string, Unity-relative | - (required) | `batch.py` (candidate folders for H1 are `ui_root/<folder>` from `spec/batch-plan.json`; `create` accepts paths relative to it), `parse_prefab.py` (self-test picks), `state_selftest.py` (fallback test prefabs), `template_scope.py` (fallback for `ui_roots`) | Main UI prefab folder. |
| `reference_resolution` | object `{"width": int, "height": int}` | `{"width": 1920, "height": 1080}` in `parse_prefab.py` when missing | `parse_prefab.py` (anchor/rect resolution of nodes) | Canvas Scaler reference resolution. |
| `platforms` | array of string (min 1) | - (required) | schema only | Target platforms, e.g. `["mobile", "steam"]`. Informational. |
| `screenshot_ratios` | array of string (min 1) | - (required) | `batch.py create` (warns about missing screenshots), `build_catalog.py` (screen pages show `input/screenshots/<batch>/<screen>_<ratio>.png` and list missing ratios) | Aspect-ratio labels used in screenshot file names, e.g. `["16x9", "20x9", "4x3"]`. Screenshots are optional in autonomous mode. |
| `touch_min_px` | number | `100` (`.get` default in `group.py`, `build_catalog.py`) | `group.py` (flags touch targets below it in group metrics), `build_catalog.py` (screen pages) | Minimum touch target size in reference-resolution pixels. |
| `guid_index_roots` | array of string (min 1), Unity-relative | - (required) | `parse_prefab.py` (`GuidIndex` walks these folders for `.meta` files -> `cache/guid-index.json`) | Folders whose assets can be referenced by UI prefabs, typically `["Assets", "Library/PackageCache", "Packages"]`. |

## Optional keys in the schema

| Key | Type | Default | Read by | Description |
|---|---|---|---|---|
| `unity_version` | string | none | schema only | Informational. The render scripts read the real version from `ProjectSettings/ProjectVersion.txt`. |
| `render_pipeline` | string | none | schema only | Informational, e.g. `"URP 17"`. |
| `ui_packages` | array of string | none | schema only | Informational, e.g. `["com.unity.ugui 2.0.0", "TextMeshPro"]`. |

## Optional keys read by scripts (not in the schema)

| Key | Type | Default | Read by | Description |
|---|---|---|---|---|
| `guid_index_exts` | array of string | `[]` = every extension | `parse_prefab.py` (`GuidIndex`) | Limit the GUID index to these asset extensions (lower-case, with dot), e.g. `[".png", ".prefab", ".asset", ".cs", ".mat", ".ttf", ".otf", ".spriteatlas", ".spriteatlasv2", ".shader"]`. Speeds up indexing on large projects. |
| `ui_roots` | array of string, Unity-relative | `[ui_root]` | `template_scope.py` (and through it `code_usage.py`, `templates.py`, `usage_graph.py`, ...) | Every folder that holds UI prefabs in scope for the template catalog (for example a main folder, a dev folder and a `Resources` UI folder). |
| `common_dirs` | array of string, Unity-relative, trailing `/` | `[]` | `template_scope.py` | Shared-component folders. Every prefab in them is a template candidate (rule A of template selection); templates there are tagged `folder: common`. |
| `exclude` | array of `{"pattern": regex, "reason": string}` | `[]` | `template_scope.py` | Prefabs whose Unity-relative path matches `pattern` are out of scope (third-party UI kits, old copies, ...). `reason` is shown in reports. |
| `code` | object | `{}` | `code_usage.py` | How C# code loads UI prefabs (see below). |
| `code.roots` | array of string, Unity-relative | `["Assets"]` | `code_usage.py` | C# folders to scan for prefab names and load calls. |
| `code.resources_dir` | string, Unity-relative | `"Assets/Resources"` | `code_usage.py` | Folder that `Resources.Load` paths are resolved against first. |
| `code.loader_scripts.resources_loader` | string, Unity-relative `.cs` path | none | `code_usage.py` | Script of a component that loads a prefab by address at runtime (a "loader" component inside prefabs). Its GUID identifies loader nodes; loaded prefabs become `code-loader` usages. |
| `code.loader_scripts.wrap_content` | string, Unity-relative `.cs` path | none | `code_usage.py` | Script of a list/scroll component that instantiates an item prefab (`code-wrap` usages). |
| `scenes` | object | `{}` | `scene_enum.py` | Where scene keys come from, to find reachable scenes (see below). |
| `scenes.sources` | array of source objects | `[]` | `scene_enum.py` | Data files that name scenes. Each source: `kind` (label), `glob` (Unity-relative glob, `**` allowed), `regex` (group 1 = scene key, multiline); optional `block` (search `regex` only inside group 1 of this regex), `split` (split keys on this string), `prefix` (keep only keys with this prefix), `ignore_prefix` + `ignore_reason` (record such keys as ignored). The self-test fails if no scene is reachable. |
| `scenes.code_roots` | array of string, Unity-relative | `["Assets"]` | `scene_enum.py` | Runtime C# folders scanned for `const string *Scene* = "..."` (kind `hardcoded`). |
| `scenes.string_define` | string, Unity-relative `.cs` path, or none | none | `scene_enum.py` | A constants file scanned for `const string *SCENE* = "..."` (kind `stringdefine`). |
| `scenes.preferred_dir` | string (path fragment) or none | none | `scene_enum.py` | When several scene files share a file name, prefer the one whose path contains this fragment. |
| `scenes.chain_globs` | array of git pathspecs | `["*.unity", "*.playable", ":(glob)Assets/**/*.asset"]` | `scene_enum.py` | Files searched for chained references from reachable scenes/data to otherwise unreferenced scenes (kind `chain`). |
| `editor_build_tool_dir` | string, Unity-relative | `"Assets/Editor"` | `ds_colors.py`, `ds_index.py` | Folder of editor scripts that build UI prefabs (`PrefabUtility.SaveAsPrefabAsset`). Colors written there are collected for semantic token names. |
| `bridge_dir` | string, Unity-relative | `"Assets/Editor/ClaudeBridge"` | `ds_publish.py` | Where the batch renderers (`UIThumbnailRenderer`, `UILayoutRenderer`) live; only used in the generated `UPDATE.md` text. |
| `render_font` | string, Unity-relative TMP font asset path | none | `thumbs.py` | Fallback font passed to the renderer as `-uiAuditFont <path>` for thumbnails. |
| `selftest_prefabs` | array of string (relative to `ui_root`) | first prefabs of two different folders under `ui_root` | `state_selftest.py` | The two UI prefabs used by the state-machine flow test. |
| `design` | object | `{}` | `catalog_library.py` | Design-track settings. |
| `design.kit_dir` | string, relative to `ui-audit/` | `"design/kit"` | `catalog_library.py` | Kit folder whose `components.md` (kit <-> Unity template table) and `rules.md` feed the review-viewer dock library (alternatives, kit rows, rule excerpts) and the `feedback.py list` kit tail. |
| `publish` | object | `{}` | `ds_publish.py` (and `ds_index.py` through it) | Refresh-and-share settings for `Docs/ui-design-system/`. |
| `publish.watch_code_roots` | array of string, Unity-relative | `["Assets"]` | `ds_publish.py` | C# folders whose changes since the data build trigger a full regeneration in `ds_publish.py --plan`. |
| `publish.team_server` | string (URL) or none | none | `catalog_review.py` (embedded into `review.html` as `#rv-config`, read by `catalog/assets/review.js`) | Address of the shared review server, e.g. `"http://192.0.2.10:8770"`. A viewer opened from disk (read-only) links there so feedback goes to the shared log. |
| `publish.review_server` | string | `"리뷰 서버"` ("review server") | `ds_publish.py` | What the generated `UPDATE.md` calls the team server where feedback is left. |
| `publish.shared_since` | string (date) or none | none | `ds_publish.py` | Date the team started sharing workspace data through git (text in `UPDATE.md`). |
| `publish.after_push_note` | string or none | none | `ds_publish.py` | Sentence appended after the push step in `UPDATE.md` (for example how the team server picks up pushes). |
| `publish.completely_case` | string or none | none | `ds_publish.py` -> `ds_index.py` | A project example appended to the "never unpack `Completely`" rule in `INDEX.md`. |
| `project_producers` | object | `{}` | `a0_setup.py`, `ds_publish.py` | Project-specific producer scripts that are not part of the toolkit (see below). |
| `project_producers.selftests` | array of script file names | `[]` | `a0_setup.py --check` | Extra `scripts/<name>` self-tests to run, only if the file exists in `ui-audit/scripts/`. |
| `project_producers.full_steps` | array of `{"after", "cmd", "note", "unity"?}` | `[]` | `ds_publish.py` | Steps inserted into the full-regeneration list right after the step whose `cmd` equals `after`. `cmd` is `python scripts/<name>.py ...`; the step is included only if that script exists. `unity: true` marks a Unity batch step. |
| `project_producers.index_steps` | same as above | `[]` | `ds_publish.py` | Steps inserted into the index-only refresh (`--run-index`). |
| `catalog` | object | `{}` | `catalog_assets.py` | Catalog presentation. |
| `catalog.fonts.family` | string | none (system fonts) | `catalog_assets.py` | Display font family for the catalog (`@font-face` + first entry of the display font stack). |
| `catalog.fonts.files` | array of `{"name", "src", "weight"}` | `[]` | `catalog_assets.py` | Font files copied from the Unity project (`src`, Unity-relative) to `catalog/assets/vendor/<name>` at build time, so pages work when opened from disk. Only use fonts whose license allows this. |

## Project producers (optional inputs)

Some data comes from producers that depend on a project's own framework and are therefore **not** shipped with the toolkit (for example an app-flow tracer, a new-screen wiring checklist generator, or one-off pilot scripts). The toolkit only consumes their output:

- `data/app-flow.json` - app icon -> screen flow. Schema: `ui-audit/schemas/app-flow.json`. Optional: without it, `layout_map.py` renders only template-index screens, the catalog home is the screen list, and design skills pick reference flows by hand.
- A new-screen checklist in `Docs/ui-design-system/` - optional; the `ui-design-system` skill follows it when present.

Register such scripts under `project_producers` so `a0_setup.py --check` runs their self-tests and `ds_publish.py --plan` lists them in the right place.

## Example

```json
{
 "name": "My Game",
 "unity_root": "..",
 "unity_version": "6000.0.0f1",
 "render_pipeline": "URP 17",
 "ui_system": "uGUI",
 "ui_packages": ["com.unity.ugui 2.0.0", "TextMeshPro"],
 "ui_root": "Assets/Game/UI",
 "reference_resolution": {"width": 1920, "height": 1080},
 "platforms": ["mobile", "steam"],
 "screenshot_ratios": ["16x9", "20x9", "4x3"],
 "touch_min_px": 100,
 "guid_index_roots": ["Assets", "Library/PackageCache", "Packages"],
 "guid_index_exts": [".cs", ".png", ".jpg", ".psd", ".asset", ".prefab", ".mat", ".ttf", ".otf", ".spriteatlas", ".spriteatlasv2", ".shader"],
 "ui_roots": ["Assets/Game/UI", "Assets/Game/Resources/UI"],
 "common_dirs": ["Assets/Game/UI/Common/"],
 "exclude": [{"pattern": "^Assets/Game/UI/ThirdParty/", "reason": "third-party UI kit"}],
 "code": {
  "roots": ["Assets/Game/Scripts"],
  "resources_dir": "Assets/Game/Resources",
  "loader_scripts": {
   "resources_loader": "Assets/Game/Scripts/UI/PrefabLoader.cs",
   "wrap_content": "Assets/Game/Scripts/UI/RecycleList.cs"
  }
 },
 "scenes": {
  "code_roots": ["Assets/Game/Scripts"],
  "string_define": "Assets/Game/Scripts/Constants/SceneNames.cs",
  "chain_globs": ["*.unity", "*.playable", ":(glob)Assets/Game/**/*.asset"],
  "sources": [
   {"kind": "stage", "glob": "Assets/Game/Data/Stages/*.asset", "regex": "^\\s*sceneName: (\\S+)\\s*$"}
  ]
 },
 "editor_build_tool_dir": "Assets/Game/Editor",
 "publish": {"watch_code_roots": ["Assets/Game/Scripts"]},
 "design": {"kit_dir": "design/kit"}
}
```

Related: `spec/batch-plan.json` (batch order for H1, written next to `project.json` during A0) has the form `{"batches": [{"batch": "b1", "title": "...", "folders": ["<folder under ui_root>", ...], "questions": ["..."]}]}`; `folders` are relative to `ui_root`, `questions` is optional.
