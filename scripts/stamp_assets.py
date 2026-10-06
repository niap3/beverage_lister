"""Cache-bust the CSS and JS in a built site: assets/x.css -> assets/x.css?v=<hash>.

Usage:  python scripts/stamp_assets.py _site      (run by CI on the assembled site)

Why: GitHub Pages lets browsers keep a file for 10 minutes (max-age=600).
Right after a deploy a browser could pair new HTML with the old cached
stylesheet; that once rendered the search icon at full screen width. A
query string that changes with the file's content makes every deploy's HTML
ask for its own CSS and JS. Only the copy in the given folder is changed,
never the source files, so there are no hash diffs in git.

It also renames the service worker's cache to include the hash, so each
deploy starts a fresh offline cache.
"""

import hashlib
import re
import sys
from pathlib import Path

ASSETS = ["assets/style.css", "assets/app.js", "assets/search.js", "assets/meta.js"]


def main():
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "_site")
    hashes = {a: hashlib.sha256((site / a).read_bytes()).hexdigest()[:10] for a in ASSETS}
    pattern = re.compile(r'(["/])(' + "|".join(re.escape(a) for a in ASSETS) + r')"')
    pages = 0
    for page in site.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        new = pattern.sub(lambda m: f'{m.group(1)}{m.group(2)}?v={hashes[m.group(2)]}"', text)
        if new != text:
            page.write_text(new, encoding="utf-8")
            pages += 1
    combined = hashlib.sha256("".join(sorted(hashes.values())).encode()).hexdigest()[:10]
    sw = site / "sw.js"
    text = sw.read_text(encoding="utf-8")
    text, n = re.subn(r"var CACHE = 'prices-[^']*';", f"var CACHE = 'prices-{combined}';", text)
    if n != 1:
        raise SystemExit("sw.js: CACHE line not found")
    sw.write_text(text, encoding="utf-8")
    print(f"Stamped {pages} pages; sw cache prices-{combined}; " +
          ", ".join(f"{Path(a).name}={h}" for a, h in hashes.items()))


if __name__ == "__main__":
    main()
