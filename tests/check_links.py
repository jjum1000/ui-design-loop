"""Check that relative links in the repository's Markdown files point at files that exist.

Usage: python tests/check_links.py      (exit 1 when a link is broken)
Skips http(s)/mailto links, pure #anchors, links inside fenced code blocks and placeholders like <slug>.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_DIRS = {".git", "__pycache__", "Library", "Temp", "Logs", "ui-audit", "Docs"}


def md_files():
    for dp, dn, fn in os.walk(REPO):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if f.endswith(".md"):
                yield os.path.join(dp, f)


def main():
    bad = 0
    for path in md_files():
        fence = False
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if line.lstrip().startswith("```"):
                    fence = not fence
                    continue
                if fence:
                    continue
                for target in LINK.findall(re.sub(r"`[^`]*`", "", line)):  # inline code is not a link
                    if re.match(r"^(https?:|mailto:|#)", target) or "<" in target:
                        continue
                    rel = target.split("#", 1)[0]
                    if rel and not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(path), rel))):
                        print("%s:%d broken link %s" % (os.path.relpath(path, REPO), i, target))
                        bad += 1
    print("broken links: %d" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
