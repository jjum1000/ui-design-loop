"""Run the whole ui-design-loop pipeline on the sample Unity project, without an LLM.

Usage (from the repository root):
  python examples/run_demo.py                 install the toolkit into examples/sample-project/ui-audit and run:
                                              A0 setup → every batch H1 → A1 … A6 → F, template catalog, explorer pages,
                                              design-system index, review viewer page
  python examples/run_demo.py --with-unity    also render template thumbnails and screen layout maps with Unity in
                                              batch mode (close any editor that has the sample project open first)
  python examples/run_demo.py --clean         delete everything the demo generated (keeps project.json, spec/batch-plan.json,
                                              design/) and exit

In real use the gates (H1–H3), the classification of ambiguous nodes (A2), the review of samples (A6) and the final
report (F) are done by Claude agents and you; here they are answered by fixed rules so the run is reproducible.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(REPO, "examples", "sample-project")
WS = os.path.join(SAMPLE, "ui-audit")
KEEP = {"project.json", "spec", "design"}            # project inputs; everything else in ui-audit/ is generated
KEEP_SPEC = {"batch-plan.json"}


def run(*args, check=True, quiet=False):
    """Run a workspace script from ui-audit/. Returns (returncode, output)."""
    r = subprocess.run([sys.executable] + list(args), cwd=WS, capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    out = (r.stdout or "") + (r.stderr or "")
    if not quiet:
        print("$ python %s%s" % (" ".join(args), "" if r.returncode == 0 else "   → exit %d" % r.returncode))
    if check and r.returncode != 0:
        print(out[-3000:])
        raise SystemExit("step failed: python %s" % " ".join(args))
    return r.returncode, out


def p(*parts):
    return os.path.join(WS, *parts)


def load(*parts):
    with open(p(*parts), encoding="utf-8") as f:
        return json.load(f)


def clean():
    for name in os.listdir(WS):
        full = p(name)
        if name in KEEP and name != "spec":
            continue
        if name == "spec":
            for f in os.listdir(full):
                if f not in KEEP_SPEC:
                    os.remove(os.path.join(full, f))
            continue
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)
    docs = os.path.join(SAMPLE, "Docs")  # design-system index written next to Assets/ by ds_index.py
    if os.path.isdir(docs):
        shutil.rmtree(docs)
    print("cleaned %s" % WS)


def chunks(b, s):
    return list(load("manifest.json")["batches"][b]["steps"][s]["chunks"])


def answer_pending(b, screen):
    """A2 stand-in for the agent: answer every node the rules left open as 'other' (medium confidence)."""
    pend = p("data", ".work", b, "A2", screen + ".pending.json")
    lines = load("data", ".work", b, "A2", screen + ".pending.json") if os.path.exists(pend) else []
    paths = {x.split(" | ", 1)[0] for x in lines}
    inv = load("data", "inventory", b, screen + ".json")
    ans = {n["id"]: {"kind": "other", "basis": "demo default", "confidence": "medium"}
           for n in inv["nodes"] if n["path"] in paths}
    path = p("data", ".work", b, "A2", screen + ".answers-demo.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ans, f, ensure_ascii=False)
    return path


def audit_batch(b, folders):
    run("scripts/batch.py", "create", b, *folders)
    run("scripts/state.py", "gate-done", b, "H1")
    run("scripts/state.py", "start", b, "A1")
    for s in chunks(b, "A1"):
        run("scripts/parse_prefab.py", "--batch", b, "--screen", s, quiet=True)
        run("scripts/validate.py", "--rename", p("data", "inventory", b, s + ".json.tmp"), quiet=True)
        run("scripts/state.py", "chunk-done", b, "A1", s, quiet=True)
    run("scripts/state.py", "step-done", b, "A1")
    run("scripts/state.py", "start", b, "A2")
    for s in chunks(b, "A2"):
        rc, _out = run("scripts/classify_rules.py", "--batch", b, "--screen", s, check=False, quiet=True)
        if rc == 3:
            run("scripts/classify_rules.py", "--batch", b, "--screen", s, "--answers", answer_pending(b, s), quiet=True)
        run("scripts/validate.py", "--rename", p("data", "classified", b, s + ".json.tmp"), quiet=True)
        run("scripts/state.py", "chunk-done", b, "A2", s, quiet=True)
    run("scripts/state.py", "step-done", b, "A2")
    run("scripts/state.py", "start", b, "A3")
    for c in chunks(b, "A3"):
        kind = load("manifest.json")["batches"][b]["steps"]["A3"]["chunks"][c]["kind"]
        run("scripts/group.py", "run", "--batch", b, "--chunk", c, quiet=True)
        run("scripts/validate.py", "--rename", *[p("data", d, kind + ".json.tmp") for d in ("groups", "registry", "metrics")],
            quiet=True)
        run("scripts/state.py", "chunk-done", b, "A3", c, quiet=True)
    run("scripts/state.py", "step-done", b, "A3")
    run("scripts/state.py", "gate-done", b, "H2")
    run("scripts/state.py", "start", b, "A4")
    for c in chunks(b, "A4"):
        run("scripts/cluster_values.py", "run", "--batch", b, "--chunk", c, quiet=True)
        run("scripts/validate.py", "--rename", p("data", "tokens", c + ".json.tmp"), p("data", "token-registry", c + ".json.tmp"),
            quiet=True)
        run("scripts/state.py", "chunk-done", b, "A4", c, quiet=True)
    run("scripts/state.py", "step-done", b, "A4")
    run("scripts/state.py", "gate-done", b, "H3")
    run("scripts/state.py", "start", b, "A5")
    for c in chunks(b, "A5"):
        run("scripts/build_catalog.py", "--page", c, quiet=True)
        run("scripts/validate.py", "--rename", p("catalog"), quiet=True)
        run("scripts/state.py", "chunk-done", b, "A5", c, quiet=True)
    run("scripts/build_catalog.py", "--check")
    run("scripts/state.py", "step-done", b, "A5")
    run("scripts/state.py", "start", b, "A6")
    text = ""
    for c in chunks(b, "A6"):
        run("scripts/build_catalog.py", "--samples", c, quiet=True)
        text += "## %s\n" % c + "".join("- 표본 %d: demo run | OK\n" % i for i in range(1, 6))
    os.makedirs(p("reports"), exist_ok=True)
    with open(p("reports", "review-%s.md.tmp" % b), "w", encoding="utf-8") as f:
        f.write(text)
    run("scripts/validate.py", "--rename", p("reports", "review-%s.md.tmp" % b), quiet=True)
    for c in chunks(b, "A6"):
        run("scripts/state.py", "chunk-done", b, "A6", c, quiet=True)
    run("scripts/state.py", "step-done", b, "A6")


def final_report():
    os.makedirs(p("reports"), exist_ok=True)
    with open(p("reports", "FINAL.md"), "w", encoding="utf-8") as f:
        f.write("# Final report (demo)\n\nGenerated by examples/run_demo.py. In real use the F agent writes this report "
                "from data/, decisions.json and the A6 reviews (see agents/F.md).\n")
    with open(p("handoff", "DONE"), "w", encoding="utf-8") as f:
        f.write("demo\n")


def have_playwright():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001 — not installed or no browser
        return False


def explorer(with_unity):
    run("scripts/parse_prefab.py", "--reindex")
    run("scripts/scene_enum.py", "--run")
    run("scripts/usage_graph.py", "--prefabs")
    run("scripts/usage_graph.py", "--scenes")
    run("scripts/templates.py", "--select", "--overrides", "--lookalikes")
    run("scripts/thumbs.py", "--list")
    if with_unity:
        run("scripts/thumbs.py", "--run")
        run("scripts/thumbs.py", "--collect")
    run("scripts/templates.py", "--assemble")
    # data/app-flow.json comes from a project producer that understands your UI framework (docs/architecture.md);
    # the sample ships a hand-written one instead
    shutil.copyfile(os.path.join(SAMPLE, "app-flow.sample.json"), p("data", "app-flow.json"))
    run("scripts/validate.py", p("data", "app-flow.json"))
    run("scripts/layout_map.py", "--list")
    if with_unity:
        run("scripts/layout_map.py", "--run")
        run("scripts/layout_map.py", "--collect")
        run("scripts/layout_map.py", "--check-samples")
    run("scripts/feedback.py", "build")  # feedback/state.js from design/registry.json (+ empty log) for the viewer badges
    run("scripts/build_catalog.py", "--all")
    run("scripts/validate.py", "--rename", "catalog")
    if have_playwright():  # component crops + per-state keys for the review dock (headless Chromium)
        run("scripts/catalog_library.py", "--build")
    else:
        print("(review dock crops need python playwright + chromium — skipped)")
    run("scripts/build_catalog.py", "--check")
    run("scripts/ds_index.py", "--run")
    if with_unity:
        run("scripts/ds_skeletons.py", "--run")  # needs the rendered layout maps
    else:
        print("(skeletons.md needs layout maps — run with --with-unity)")
    run("scripts/ds_index.py", "--check")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--with-unity", action="store_true", help="also render thumbnails and layout maps with Unity")
    ap.add_argument("--clean", action="store_true", help="delete generated files and exit")
    a = ap.parse_args(argv)
    if a.clean:
        clean()
        return 0
    if os.path.exists(p("manifest.json")):
        print("previous demo output found — cleaning first")
        clean()
    rc = subprocess.run([sys.executable, os.path.join(REPO, "install.py"), "--target", WS]).returncode
    if rc:
        return rc
    run("scripts/a0_setup.py")
    run("scripts/a0_setup.py", "--check")
    plan = load("spec", "batch-plan.json")
    for e in plan["batches"]:
        print("\n== batch %s — %s" % (e["batch"], e.get("title", "")))
        audit_batch(e["batch"], e["folders"])
    final_report()
    _rc, out = run("scripts/state.py", "render", quiet=True)
    print(next((x for x in out.splitlines() if "다음 행동" in x), out.splitlines()[0]))
    print("\n== explorer, template catalog, design-system index")
    explorer(a.with_unity)
    print("\nDone. Open in a browser:\n  %s\n  %s\nReview viewer (needs the local server):\n  python %s\n"
          "  → http://127.0.0.1:8770/ui-audit/catalog/review.html?screen=ShopView&stage=wire" % (
              p("catalog", "index.html"), p("catalog", "app-flow.html"), os.path.join("examples", "sample-project", "ui-audit",
                                                                                      "scripts", "review_server.py")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
