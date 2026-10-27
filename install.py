"""Install (vendor) the ui-design-loop toolkit into a Unity project's ui-audit/ workspace.

Usage:
  python install.py --target <unity-project>/ui-audit            install or update the toolkit files
  python install.py --target <dir> --check                       verify installed files against toolkit.lock.json
  python install.py --target <dir> --adopt                       first install over an existing workspace whose
                                                                 tool files were copied by hand (no lock yet)
  python install.py --target <dir> --force                       also overwrite tool files you modified locally
  python install.py --list                                       print the files that would be installed

What it touches:
  Only the files under toolkit/ of this repository (scripts, schemas, spec templates, ROADMAP, catalog assets,
  feedback contract/tests) plus <target>/toolkit.lock.json. Everything else in the workspace is project data and is
  never written: project.json, spec/batch-plan.json, data/, ds/ (e.g. ds/token-names.seed.json), catalog output,
  feedback logs, and any project-specific producer scripts you keep next to the tool scripts.

The lock records the toolkit version and a SHA-256 per file (text files hashed with LF line endings, so a CRLF
checkout does not count as a change). Files dropped by a newer toolkit version are removed only if unmodified.
Standard library only.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
TOOLKIT = os.path.join(REPO, "toolkit")
LOCK = "toolkit.lock.json"
TEXT_EXT = {".py", ".md", ".json", ".js", ".css", ".ps1", ".sh", ".txt", ".jsonl", ".diff", ".html"}
# Workspace paths that belong to the project. The toolkit must never ship (or overwrite) these.
PROTECTED_FILES = {"project.json", "spec/batch-plan.json", "manifest.json", "decisions.json", "questions.json", LOCK}
PROTECTED_DIRS = ("data/", "ds/", "batches/", "input/", "previews/", "reports/", "handoff/", "design/", "cache/",
                  "feedback/log", "feedback/snap/", "feedback/revisions/", "feedback/attachments/")


def version():
    with open(os.path.join(REPO, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        return json.load(f)["version"]


def digest(path):
    with open(path, "rb") as f:
        data = f.read()
    if os.path.splitext(path)[1].lower() in TEXT_EXT:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def is_protected(rel):
    return rel in PROTECTED_FILES or rel.startswith(PROTECTED_DIRS)


def toolkit_files():
    """{relpath: abspath} of everything under toolkit/ (caches excluded)."""
    out = {}
    for dp, dn, fn in os.walk(TOOLKIT):
        dn[:] = sorted(d for d in dn if d not in ("__pycache__", ".ruff_cache", ".pytest_cache"))
        for f in sorted(fn):
            if f.endswith((".pyc", ".tmp")):
                continue
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, TOOLKIT).replace("\\", "/")
            if is_protected(rel):
                raise SystemExit("toolkit/ must not contain project path: " + rel)
            out[rel] = full
    return out


def read_lock(target):
    path = os.path.join(target, LOCK)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check(target):
    lock = read_lock(target)
    if not lock:
        print("no %s in %s" % (LOCK, target))
        return 1
    bad = 0
    for rel, h in sorted(lock["files"].items()):
        p = os.path.join(target, rel)
        if not os.path.exists(p):
            print("missing   " + rel)
            bad += 1
        elif digest(p) != h:
            print("modified  " + rel)
            bad += 1
    print("%s %s: %d files, %d differ from the lock" % (lock["tool"], lock["version"], len(lock["files"]), bad))
    return 1 if bad else 0


def install(target, force=False, adopt=False):
    files = toolkit_files()
    lock = read_lock(target)
    old = (lock or {}).get("files", {})
    conflicts = []
    for rel in files:
        p = os.path.join(target, rel)
        if not os.path.exists(p):
            continue
        if rel in old:
            if digest(p) != old[rel] and not force:
                conflicts.append("modified locally: " + rel)
        elif not (adopt or force):
            conflicts.append("exists but not installed by the toolkit: " + rel)
    if conflicts:
        print("refused — nothing written:\n  " + "\n  ".join(conflicts))
        print("use --adopt for a first install over hand-copied tool files, --force to overwrite local edits")
        return 2
    os.makedirs(target, exist_ok=True)
    new = {}
    for rel, src in files.items():
        dst = os.path.join(target, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        new[rel] = digest(dst)
    removed, kept = [], []
    for rel, h in old.items():
        if rel in new:
            continue
        p = os.path.join(target, rel)
        if os.path.exists(p) and digest(p) == h:
            os.remove(p)
            removed.append(rel)
        elif os.path.exists(p):
            kept.append(rel)
    lock = {"tool": "ui-design-loop", "version": version(), "files": dict(sorted(new.items()))}
    with open(os.path.join(target, LOCK), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(lock, indent=1) + "\n")
    print("installed ui-design-loop %s → %s (%d files%s%s)" % (
        lock["version"], target, len(new), ", removed %d" % len(removed) if removed else "",
        ", kept %d modified files dropped by this version: %s" % (len(kept), ", ".join(kept)) if kept else ""))
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", help="the ui-audit/ workspace folder inside your Unity project")
    ap.add_argument("--check", action="store_true", help="verify installed files against the lock")
    ap.add_argument("--force", action="store_true", help="overwrite tool files modified locally")
    ap.add_argument("--adopt", action="store_true", help="first install over tool files copied by hand")
    ap.add_argument("--list", action="store_true", help="list the toolkit files")
    a = ap.parse_args(argv)
    if a.list:
        for rel in toolkit_files():
            print(rel)
        return 0
    if not a.target:
        ap.error("--target is required")
    target = os.path.abspath(a.target)
    if a.check:
        return check(target)
    return install(target, force=a.force, adopt=a.adopt)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
