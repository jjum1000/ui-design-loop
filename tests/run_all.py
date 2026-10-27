"""Run every test: installer tests, the sample demo (which runs all script selftests via a0_setup --check),
the feedback-loop selftests, the review viewer smoke test and an installer drift check.

Usage (from the repository root):  python tests/run_all.py [--with-unity]
Exit code 0 only when everything passed (skipped optional cases do not fail the run).
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = os.path.join(REPO, "examples", "sample-project", "ui-audit")
EXTRA_SELFTESTS = ["feedback_core.py", "feedback.py", "review_server.py", "catalog_library.py"]


def step(title, args, cwd=REPO):
    print("\n=== %s" % title, flush=True)
    r = subprocess.run([sys.executable] + args, cwd=cwd, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    print("--- %s: %s" % (title, "ok" if r.returncode == 0 else "FAILED (exit %d)" % r.returncode), flush=True)
    return r.returncode == 0


def main(argv):
    results = []
    results.append(step("installer tests", ["-m", "unittest", "-v", "tests.test_install"]))
    results.append(step("markdown links", ["tests/check_links.py"]))
    demo = ["examples/run_demo.py"] + (["--with-unity"] if "--with-unity" in argv else [])
    results.append(step("sample demo (A0 → F, explorer, design-system index; includes a0_setup --check)", demo))
    for s in EXTRA_SELFTESTS:
        results.append(step("selftest " + s, [os.path.join("scripts", s), "--selftest"], cwd=WS))
    results.append(step("review viewer smoke test", ["-m", "unittest", "-v", "tests.test_smoke_review"]))
    results.append(step("installed files unchanged by the run (install.py --check)", ["install.py", "--target", WS, "--check"]))
    print("\n%d/%d passed" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
