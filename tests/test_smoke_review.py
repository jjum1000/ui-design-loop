"""Smoke test of the review viewer on the sample project: server API round trip + one browser path.

Needs a sample workspace built by `python examples/run_demo.py` (run_all.py does that first).
The browser case (open review.html → click a component on the deliverable → leave feedback → API shows it open) runs only
when python playwright with Chromium is installed; otherwise it is skipped, not failed.
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = os.path.join(REPO, "examples", "sample-project", "ui-audit")
SCREEN = "ShopView"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def have_playwright():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001 — any import/launch problem means "not available"
        return False


class ReviewSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(os.path.join(WS, "catalog", "review.html")):
            raise unittest.SkipTest("sample workspace not built — run python examples/run_demo.py first")
        cls.port = free_port()
        cls.base = "http://127.0.0.1:%d" % cls.port
        cls.proc = subprocess.Popen([sys.executable, os.path.join(WS, "scripts", "review_server.py"), "--port", str(cls.port)],
                                    cwd=WS, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/api/feedback", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)
        else:
            cls.proc.kill()
            raise RuntimeError("review server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return r.status, r.read()

    def post(self, body):
        req = urllib.request.Request(self.base + "/api/feedback", data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def items(self):
        _s, raw = self.get("/api/feedback?screen=" + SCREEN)
        return json.loads(raw.decode("utf-8"))["items"]

    def test_pages_and_api(self):
        status, html = self.get("/ui-audit/catalog/review.html?screen=%s&stage=wire" % SCREEN)
        self.assertEqual(status, 200)
        self.assertIn(b'id="rv-registry"', html)
        self.assertIn(SCREEN.encode(), html)
        self.assertEqual(self.get("/ui-audit/design/shop/wire.html")[0], 200)
        _s, raw = self.get("/api/feedback?screen=" + SCREEN)
        state = json.loads(raw.decode("utf-8"))
        self.assertIn(SCREEN, state["registry"]["screens"])
        status, out = self.post({"type": "open", "screen": SCREEN, "stage": "wire", "kind": "bug",
                                 "text": "smoke: api open", "component": "buy-button", "author": "smoke"})
        self.assertEqual(status, 201, out)
        fid = out["event"]["id"]
        self.assertEqual(self.items()[fid]["status"], "open")

    def test_browser_leave_feedback(self):
        if not have_playwright():
            self.skipTest("python playwright + chromium not installed (optional)")
        from playwright.sync_api import sync_playwright
        text = "smoke: browser open %d" % int(time.time())
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(self.base + "/ui-audit/catalog/review.html?screen=%s&stage=wire" % SCREEN)
            page.fill("#rv-author", "smoke")
            target = page.frame_locator("#rv-frame").locator('[data-area="buy-button"]')
            target.wait_for(timeout=20000)
            box = target.bounding_box()  # select like a reviewer: click the component on the deliverable
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_function("document.getElementById('rv-formhint').textContent.indexOf('buy-button') >= 0",
                                   timeout=10000)
            page.fill("#rv-text", text)
            page.wait_for_selector("#rv-submit:not([disabled])", timeout=10000)
            page.click("#rv-submit")
            deadline = time.time() + 15
            hit = []
            while time.time() < deadline and not hit:
                hit = [x for x in self.items().values() if x.get("text") == text]
                time.sleep(0.3)
            browser.close()
        self.assertTrue(hit, "feedback left in the browser did not reach the API")
        self.assertEqual(hit[0]["status"], "open")
        self.assertEqual(hit[0]["component"], "buy-button")


if __name__ == "__main__":
    unittest.main()
