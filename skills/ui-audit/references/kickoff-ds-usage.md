# Kickoff: explain what is ready and how to brief agents (explanation session)

Use this after the catalog, template catalog and layout maps exist, when the user asks: **"With this information (UI inventory, template catalog, screen layout maps), what else should be prepared so agents use the design system when building new content UI? And how should I give them instructions?"** The session explains and proposes; it does not implement.

```
You are a new session. There is no earlier conversation. Communicate in <your language>; code and file names in English.
Work at the Unity project root; ui-audit commands run inside ui-audit/.

[Purpose]
The user's question: "Based on this information (UI inventory, template catalog, screen layout maps), what should be prepared
so agents use this design-system documentation when composing new content UI, and how do I give them instructions?"
This is an explanation and proposal session. Do not implement. Explain, batch the decisions you need into one message,
and write down only what was agreed.

[Read first, in this order]
1. ui-audit/reports/FINAL.md - numbers and open problems: who made the recorded decisions (agent vs. human),
   the template catalog, the layout maps.
2. Open a few data samples directly (2-3 of each, never everything):
   - data/templates/<a primary button slug>.json, data/templates/<a thumbnail/slot slug>.json - template metadata
     (usages, override topProps, look-alikes)
   - data/layout/screen/<a representative screen>.json - screen layout (boxes, template mapping)
   - data/app-flow.json, if the project has it (apps[0], one screens entry)
   - the beginning of data/tokens/color.json
3. The user has already seen ui-audit/catalog/ (app-flow.html or index.html).
4. Check how one real screen is wired in code (screen enum or id, controller, view, prefab location, Addressables group):
   a new content UI needs this wiring, not just a prefab.

[What to explain]
A. What is ready / what makes it hard for agents to use today. State only verified facts. Starting observations to check:
   - The catalog is HTML for humans; there is no short agent entry point ("what to use when") unless Docs/ui-design-system/ exists.
   - Standards may be undecided: if decisions were all made by agents, copy-paste look-alikes and baked copies remain,
     so an agent has weak grounds for "which button should I use".
   - Many templates may have kind "other" - no role (meaning) label.
   - Tokens are drafts (decided by the H3 gate agent); representative value != most used value in places.
   - Screen skeletons (the shared frame of View/Popup: safe area, title, back button) may not be organised as data yet.
   - ui-audit/ may exist only in one checkout (gitignored) - other people's agents cannot see it.
   - Strength: the Unity batch renderer can render prefabs an agent builds and compare them with existing screens.
B. What to prepare next, by priority and dependency. For each item: what to build, how agents use it, what humans decide.
   No effort estimates. Candidates (verify and choose): the agent-facing index (template cards: role, when to use,
   frequently changed properties, representative screens), a human decision queue for standards, role labels, skeleton recipes,
   a new-screen wiring checklist, a generate -> render -> compare loop, a refresh and sharing procedure, packaging as skills.
C. How to brief agents:
   - An instruction template the user fills in when handing over a new content UI: entry point (which app icon or screen opens it),
     reference screens (catalog/map/<slug>.html), required elements, states and data, prohibitions.
   - The agent's order of work (read the index -> pick reference screens -> propose a template composition (wireframe) -> approval
     -> prefab and code -> render comparison -> review) and where humans check.
   - Demonstrate one example with real data (for example "a new storage screen similar to the inventory": which template
     combination comes out of data/layout). The demonstration only reads.

[Rules]
- Explain in short sections, one after another. Batch every question that needs the user's decision into one message.
- When agreed, write it to ui-audit/design/<date>-design-system-for-agents.md (say the path before writing).
  Implementation is a separate track, when the user asks for it.
- The Unity project is read-only. Do not commit. Do not touch existing data, decisions.json or manifest.json.
- Write code and docs with the Write tool (Bash heredocs collapse backslashes).
```

If `Docs/ui-design-system/` already exists, its `INDEX.md` already contains an instruction template; review it with the user instead of inventing a new one.
