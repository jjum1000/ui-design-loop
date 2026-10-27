# ui-design-loop

Audit the UI of a Unity uGUI project, turn it into a browsable catalog and an agent-readable design-system index,
then design new screens on top of it (wireframe → skinned mockup) and collect reviewer feedback on them — with
Claude Code doing the legwork and humans deciding at a few gates.

> [!IMPORTANT]
> **Known limitations (v0.1)**
> - **Generated catalog pages, generated docs and CLI output are Korean-only in v0.1.** Skills, READMEs and the
>   code documentation are in English. Output i18n is planned.
> - Unity **uGUI** only (prefab YAML). UI Toolkit is not supported.
> - Unity batch rendering (thumbnails, layout maps) is tested on **Windows** only. Set `UNITY_EXE` to point at your
>   editor binary on other platforms.
> - The browser end-to-end tests of the review viewer are not part of v0.1 (a smoke test covers the main path).

## What it does

```
your Unity project ──► A1 collect ─► A2 classify ─► A3 group ─► H2 ─► A4 tokens ─► H3 ─► A5 catalog ─► A6 verify ─► F report
   (uGUI prefabs)        (prefab YAML parser, GUID index, nested-prefab expansion)        human gates: H1 · H2 · H3
                    └─► template catalog (which prefabs are reused where, overrides, look-alikes, thumbnails)
                    └─► screen layout maps (rendered screen + every node's rect)            ──► HTML explorer
                    └─► design-system index for agents (Docs/ui-design-system/INDEX.md, templates.jsonl, screens.jsonl)
                                     │
                                     ▼
              /ui-wire-skin: function spec → wireframe → skinned HTML mockup (built from the indexed templates)
                                     │
                                     ▼
              /ui-feedback: reviewers comment per component in the review viewer → Claude claims, fixes, records revisions
```

Everything is plain files: Python scripts (standard library + PyYAML/Pillow), JSON data, static HTML (opens from `file://`), and an
optional tiny local HTTP server for the feedback loop.

## Requirements

- Python 3.10+ with `pip install pyyaml pillow` (prefab YAML parsing; thumbnails and layout maps)
- Unity 2022.3 or 6.x project using uGUI — only for the renderers; the audit itself only reads files
- [Claude Code](https://claude.com/claude-code) for the skills
- Optional: `pip install playwright && python -m playwright install chromium` — measurement scripts of `/ui-wire-skin`,
  claim/revise snapshots of `/ui-feedback`, the component crops of the review dock, and the browser smoke test

## Try it on the sample project

```bash
git clone https://github.com/jjum1000/ui-design-loop
cd ui-design-loop
python examples/run_demo.py            # ~1–2 min: installs the toolkit into examples/sample-project/ui-audit and runs the pipeline
python examples/run_demo.py --with-unity   # ~2–3 min: same, plus thumbnails and screen layout maps rendered by Unity
```

Without `--with-unity` (no Unity needed) the catalog works but every image slot is a placeholder
(«썸네일 없음» = no thumbnail, «배치 맵 없음» = no layout map) and the screen map page stays empty. With Unity
(the editor version in `examples/sample-project/ProjectSettings/ProjectVersion.txt`, found under the default Hub
folder or via `UNITY_EXE`) the same pages show real renders. Close any editor that has the sample project open first.
Re-running the demo (or the tests) regenerates its output from scratch.

Open in a browser, in this order:
1. `examples/sample-project/ui-audit/catalog/app-flow.html` — explorer home: app icons → screens → next screens
2. `.../catalog/templates.html` — which prefabs are reused as templates, where, with which overrides
3. `.../catalog/map.html` — rendered screens with every node's box (needs `--with-unity`)
4. `.../catalog/index.html` — the audit catalog (A5): fragmentation metrics, groups, tokens

Then try the review viewer, which needs the local server:

```bash
python examples/sample-project/ui-audit/scripts/review_server.py      # Ctrl+C to stop; --port N to change the port
# → http://127.0.0.1:8770/ui-audit/catalog/review.html?screen=ShopView&stage=wire     (stage=wire | mockup)
```

Click a component in the wireframe, type your name and a comment, and press 남기기 (leave). With Playwright installed the
demo also builds the bottom dock's component crops («도크» button).

Korean UI labels you will meet: 앱 흐름 = app flow · 화면 맵 = screen map · 템플릿 = templates · 씬 = scenes ·
미사용 = unused · 현황 = status · 토큰 = tokens · 컴포넌트 = components · 결정 = decisions · 미검토 = not reviewed ·
표준 / 폐기 / 예외 = standard / retired / exception · 리뷰 뷰어 = review viewer · 버그 / 미감 / 카피 / 동선 / 기타 =
bug / visual / copy / flow / other.

## Use it on your project

1. **Install the plugin** (skills) in Claude Code:
   ```
   /plugin marketplace add jjum1000/ui-design-loop
   /plugin install ui-design-loop@ui-design-loop
   ```
2. **Vendor the toolkit** into your Unity project (creates `<project>/ui-audit/`):
   ```bash
   python install.py --target <your-unity-project>/ui-audit
   python install.py --target <your-unity-project>/ui-audit --check     # later: verify nothing drifted
   ```
   Re-run from a newer tag to update. The installer only writes the files it owns (recorded in
   `ui-audit/toolkit.lock.json`) and never touches your `project.json`, data or project scripts.
3. **Add the renderer package** (Editor-only) to `Packages/manifest.json`:
   ```json
   "com.ui-design-loop.bridge": "https://github.com/jjum1000/ui-design-loop.git?path=/unity#v0.1.0"
   ```
4. **Configure** `ui-audit/project.json` — see [docs/project-json.md](docs/project-json.md).
5. In Claude Code, run the **`ui-audit`** skill (“start the UI audit”) and follow the gates. `state.py render` always
   prints the next action; `run_audit.ps1` / `run_audit.sh` runs the agent steps unattended.

## Skills

| Skill | Use it to |
|---|---|
| `ui-audit` | set up the workspace and run the audit A0 → F (collect, classify, group, tokens, catalog, verify, report) |
| `ui-design-system` | read the generated design-system index before building a new screen; regenerate it |
| `ui-wire-skin` | design a new screen: function spec → wireframe → skinned mockup → measurement → review |
| `ui-feedback` | process reviewer feedback left in the review viewer: claim → fix → measure → record a revision |

## Repository layout

```
.claude-plugin/   plugin + marketplace manifests
skills/           the four skills
toolkit/          what install.py copies into <project>/ui-audit/ (scripts, schemas, step spec, agent-prompt source, catalog assets)
unity/            Editor-only UPM package: batch renderers for thumbnails and layout maps
install.py        vendoring installer with a SHA-256 lock
examples/         sample uGUI project (original CC0 shapes) + run_demo.py
tests/            installer tests, smoke tests, selftest runner
docs/             architecture, project.json reference, feedback loop, lessons learned
```

## Tests

```bash
python tests/run_all.py                # ~2–3 min: installer tests + every script selftest against the sample project + smoke tests
python tests/run_all.py --with-unity   # same, but the sample demo inside it also renders with Unity
```

The test run regenerates the sample demo output (pass `--with-unity` to keep rendered images).

## License

MIT — see [LICENSE](LICENSE). The sample project's art is original and released under CC0.
