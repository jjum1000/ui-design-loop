# Architecture

ui-design-loop has three layers. Only the first two ship in this repository.

| Layer | What | Where |
|---|---|---|
| **core** | Engine-agnostic state machine, decision log, validation, token clustering, catalog builder, feedback loop, design-system index consumers | `toolkit/scripts/` |
| **adapter: unity-ugui** | Everything that understands Unity: prefab YAML parser, GUID index, usage graph, template selection, scene enumeration, C#-side loaders, batch renderers | `toolkit/scripts/` + `unity/` (UPM package) |
| **project** | Your data and anything specific to one codebase: `project.json`, `spec/batch-plan.json`, `data/`, `ds/`, `design/`, catalog output, feedback logs, and optional *project producers* (scripts that understand your own framework) | your Unity project's `ui-audit/` |

Core and adapter scripts live in one flat `toolkit/scripts/` folder on purpose: several core scripts import adapter
helpers (catalog pages read prefab paths, the decision recorder re-indexes templates, …). Splitting them into separate
packages would only add import plumbing while v0.1 supports a single engine. The table below is the authoritative
layer assignment.

## Install model

`install.py --target <unity-project>/ui-audit` copies everything under `toolkit/` into the workspace and writes
`toolkit.lock.json` (version + SHA-256 per file). It never writes project files, and `install.py --check` reports
any installed file that was edited locally. Updating is re-running `install.py` from a newer tag. Projects keep their
own producer scripts next to the tool scripts; the installer does not touch files it did not install.

The Unity renderers (`unity/`) are an Editor-only UPM package. Add it to `Packages/manifest.json` as a local path or a
git URL (see the README). The Python side launches Unity in batch mode with
`-executeMethod ClaudeBridge.UIThumbnailRenderer.Run` / `ClaudeBridge.UILayoutRenderer.Run`.

## Script layers

| Layer | Scripts |
|---|---|
| core — state & decisions | `common.py` `state.py` `questions.py` `record_decision.py` `validate.py` `schema_defs.py` `a0_setup.py` `batch.py` `state_selftest.py` |
| core — analysis | `cluster_values.py` `group.py` |
| core — catalog | `build_catalog.py` `catalog_assets.py` `catalog_templates.py` `catalog_library.py` `catalog_review.py` `catalog_flow_badges.py` |
| core — design-system index | `ds_screens.py` `ds_skeletons.py` `layout_map.py` (consumer side) |
| core — feedback loop | `feedback.py` `feedback_core.py` `review_server.py` |
| adapter — Unity uGUI | `parse_prefab.py` `classify_rules.py` `usage_graph.py` `template_scope.py` `templates.py` `thumbs.py` `code_usage.py` `scene_enum.py` `ds_roles.py` `ds_colors.py` `ds_index.py` `ds_publish.py` |

## Extension points (project producers)

Some inputs can only be produced by code that understands *your* framework. The toolkit defines their schema and
consumes them if present; you write (or skip) the producer:

| Input | Schema | Used by | Without it |
|---|---|---|---|
| `data/app-flow.json` — app icon → screen → next screen | `toolkit/schemas/app-flow.json` | catalog home (`app-flow.html`), layout map screen list, design-system index (`app` field) | the catalog home says the file is missing; screens still come from the template index |
| `Docs/ui-design-system/new-screen-checklist.md` — how a new screen is wired into your UI framework | free-form Markdown | the design-system index reading order | the index skips that step |
| extra regeneration steps (e.g. an asset-reference list for a review server) | — | `ds_publish.py --plan` | not listed |

Register producers in `project.json` → `project_producers` (`full_steps` / `index_steps` entries `{after, cmd, note}`,
and `selftests`). A producer step is only listed when its script exists in the workspace.

Other project data the toolkit reads if present: `ds/token-names.seed.json` (draft names for color tokens, see
`ds_colors.py`), `design/registry.json` and the design kit folder (`project.json` → `design.kit_dir`).
