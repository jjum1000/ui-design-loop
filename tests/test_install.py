"""install.py: writes only toolkit files, never project data, and detects local edits via the lock."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(REPO, "install.py")
PROJECT_FILES = {  # workspace files that belong to the project — install must leave them byte-identical
    "project.json": '{"name": "mine"}\n',
    "spec/batch-plan.json": '{"batches": []}\n',
    "data/template-index.json": '{"templates": []}\n',
    "ds/token-names.seed.json": '{"draft": {"color-0000": ["ink", [], "x", null]}}\n',
    "scripts/my_project_producer.py": "print('project producer')\n",
    "decisions.json": "[]\n",
    "feedback/log.jsonl": '{"type": "open"}\n',
}


def run(*args):
    r = subprocess.run([sys.executable, INSTALL] + list(args), capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout + r.stderr


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="udl-install-")
        self.ws = os.path.join(self.tmp, "ui-audit")
        for rel, text in PROJECT_FILES.items():
            p = os.path.join(self.ws, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def assert_project_untouched(self):
        for rel, text in PROJECT_FILES.items():
            with open(os.path.join(self.ws, rel), encoding="utf-8", newline="") as f:
                self.assertEqual(f.read(), text, rel)

    def lock(self):
        with open(os.path.join(self.ws, "toolkit.lock.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_install_check_and_project_files(self):
        rc, out = run("--target", self.ws)
        self.assertEqual(rc, 0, out)
        self.assert_project_untouched()
        lock = self.lock()
        self.assertIn("scripts/common.py", lock["files"])
        for rel in PROJECT_FILES:
            self.assertNotIn(rel, lock["files"])
        self.assertEqual(run("--target", self.ws, "--check")[0], 0)
        # a CRLF checkout of a text file is not a change
        p = os.path.join(self.ws, "scripts", "common.py")
        with open(p, "rb") as f:
            data = f.read()
        with open(p, "wb") as f:
            f.write(data.replace(b"\n", b"\r\n"))
        self.assertEqual(run("--target", self.ws, "--check")[0], 0)
        # a real edit is detected and blocks a plain reinstall
        with open(p, "a", encoding="utf-8") as f:
            f.write("# local edit\n")
        rc, out = run("--target", self.ws, "--check")
        self.assertEqual(rc, 1)
        self.assertIn("modified  scripts/common.py", out)
        rc, out = run("--target", self.ws)
        self.assertEqual(rc, 2, out)
        self.assertIn("modified locally: scripts/common.py", out)
        rc, out = run("--target", self.ws, "--force")
        self.assertEqual(rc, 0, out)
        self.assertEqual(run("--target", self.ws, "--check")[0], 0)
        self.assert_project_untouched()

    def test_existing_tool_files_need_adopt(self):
        p = os.path.join(self.ws, "scripts", "common.py")
        with open(p, "w", encoding="utf-8") as f:
            f.write("# hand-copied older version\n")
        rc, out = run("--target", self.ws)
        self.assertEqual(rc, 2, out)
        self.assertIn("exists but not installed by the toolkit: scripts/common.py", out)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "toolkit.lock.json")))
        rc, out = run("--target", self.ws, "--adopt")
        self.assertEqual(rc, 0, out)
        self.assertEqual(run("--target", self.ws, "--check")[0], 0)
        self.assert_project_untouched()

    def test_dropped_files_removed_only_if_unmodified(self):
        self.assertEqual(run("--target", self.ws)[0], 0)
        lock = self.lock()
        for rel, content in (("scripts/old_tool.py", "old\n"), ("scripts/old_edited.py", "old\n")):
            with open(os.path.join(self.ws, rel), "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            import hashlib
            lock["files"][rel] = hashlib.sha256(content.encode()).hexdigest()
        with open(os.path.join(self.ws, "scripts", "old_edited.py"), "a", encoding="utf-8") as f:
            f.write("edited\n")
        with open(os.path.join(self.ws, "toolkit.lock.json"), "w", encoding="utf-8") as f:
            json.dump(lock, f)
        rc, out = run("--target", self.ws, "--force")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "scripts", "old_tool.py")))
        self.assertTrue(os.path.exists(os.path.join(self.ws, "scripts", "old_edited.py")))
        self.assert_project_untouched()

    def test_toolkit_ships_no_project_paths(self):
        rc, out = run("--list")
        self.assertEqual(rc, 0, out)
        files = out.split()
        for rel in files:
            self.assertFalse(rel in PROJECT_FILES or rel.startswith(("data/", "ds/", "design/")), rel)


if __name__ == "__main__":
    unittest.main()
