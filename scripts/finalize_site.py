"""Last step on a built site: cache-bust CSS/JS, and add the visit counter.

Usage:  python scripts/finalize_site.py _site      (run by CI on the assembled site)

1. assets/x.css -> assets/x.css?v=<hash>, in every page.

Why: GitHub Pages lets browsers keep a file for 10 minutes (max-age=600).
Right after a deploy a browser could pair new HTML with the old cached
stylesheet; that once rendered the search icon at full screen width. A
query string that changes with the file's content makes every deploy's HTML
ask for its own CSS and JS. Only the copy in the given folder is changed,
never the source files, so there are no hash diffs in git.

It also renames the service worker's cache to include the hash, so each
deploy starts a fresh offline cache.

2. If site.config.json has a "goatcounter" code, adds GoatCounter's script
to every page. GoatCounter sets no cookies and stores no IP addresses; the
counts feed the "Most looked up" sort (scripts/fetch_popularity.py). With
no code configured, nothing is added.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

ASSETS = ["assets/style.css", "assets/app.js", "assets/search.js", "assets/meta.js"]


def main():
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "_site")
    cfg = json.loads((Path(__file__).resolve().parent.parent / "site.config.json").read_text(encoding="utf-8"))
    code = (cfg.get("goatcounter") or "").strip()
    if code and not re.fullmatch(r"[a-z0-9-]+", code):
        raise SystemExit(f"goatcounter code {code!r} looks wrong (letters, digits and dashes only)")
    counter = (f'<script data-goatcounter="https://{code}.goatcounter.com/count" '
               f'async src="//gc.zgo.at/count.js"></script>\n</body>') if code else None
    hashes = {a: hashlib.sha256((site / a).read_bytes()).hexdigest()[:10] for a in ASSETS}
    pattern = re.compile(r'(["/])(' + "|".join(re.escape(a) for a in ASSETS) + r')"')
    pages = 0
    for page in site.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        new = pattern.sub(lambda m: f'{m.group(1)}{m.group(2)}?v={hashes[m.group(2)]}"', text)
        if counter:
            new = new.replace("</body>", counter, 1)
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
    print(f"Stamped {pages} pages; counter {'on (' + code + ')' if code else 'off'}; sw cache prices-{combined}; " +
          ", ".join(f"{Path(a).name}={h}" for a, h in hashes.items()))


if __name__ == "__main__":
    main()
