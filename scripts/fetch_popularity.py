"""Pull "most looked up" counts from GoatCounter into a popularity file.

Usage:  GOATCOUNTER_TOKEN=... python scripts/fetch_popularity.py [out.json]
        (CI runs this on deploy and weekly; default out is data/popularity.json)

What it measures, and what it does not: the number of visitors to each
brand page (p/<id>.html) plus the number of times a brand was added to the
compare tray, over the last 30 days, on this site only. It is interest, not
sales; the site labels it "looked up", never "best selling".

Needs "goatcounter" (the site code) in site.config.json and an API token
with permission to read statistics in GOATCOUNTER_TOKEN. Without either it
writes nothing and exits 0, so the site simply has no popularity sort.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOW_DAYS = 30
MIN_SCORE = 3          # below this a brand is noise, not "looked up"
PAGE_RE = re.compile(r"/p/([0-9A-Z]{9})\.html$")
EVENT_RE = re.compile(r"^compare/([0-9A-Z]{9})$")


def tally(hits, known_ids):
    """GoatCounter hit rows -> {brand id: {"views": n, "compares": n}}. Pure, for tests."""
    out = {}
    for h in hits:
        path = h.get("path") or ""
        m = PAGE_RE.search(path) if not h.get("event") else EVENT_RE.match(path)
        if not m or m.group(1) not in known_ids:
            continue
        rec = out.setdefault(m.group(1), {"views": 0, "compares": 0})
        rec["compares" if h.get("event") else "views"] += int(h.get("count") or 0)
    return out


def fetch_hits(code, token):
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=WINDOW_DAYS)
    seen, rows = [], []
    while True:
        q = [("start", start.strftime("%Y-%m-%dT%H:%M:%SZ")), ("end", end.strftime("%Y-%m-%dT%H:%M:%SZ")),
             ("limit", "100")] + [("exclude_paths", str(i)) for i in seen]
        req = urllib.request.Request(
            f"https://{code}.goatcounter.com/api/v0/stats/hits?" + urllib.parse.urlencode(q),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "User-Agent": "beverage_lister"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        page = d.get("hits") or []
        rows += page
        seen += [h["path_id"] for h in page if "path_id" in h]
        if not d.get("more") or not page:
            return rows


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "popularity.json"
    cfg = json.loads((ROOT / "site.config.json").read_text(encoding="utf-8"))
    code, token = cfg.get("goatcounter"), os.environ.get("GOATCOUNTER_TOKEN")
    if not code or not token:
        print("Popularity: no GoatCounter code or token configured; skipping.")
        return 0
    known = {p["id"] for p in json.loads((ROOT / "data" / "products.json").read_text(encoding="utf-8"))}
    try:
        rows = fetch_hits(code, token)
    except Exception as e:  # a stats outage must never block a price deploy
        print(f"Popularity: GoatCounter request failed ({e}); skipping.")
        return 0
    counts = tally(rows, known)
    brands = {i: dict(c, score=c["views"] + c["compares"])
              for i, c in counts.items() if c["views"] + c["compares"] >= MIN_SCORE}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"window_days": WINDOW_DAYS,
                               "updated": datetime.now(timezone.utc).date().isoformat(),
                               "brands": brands}, separators=(",", ":")), encoding="utf-8")
    print(f"Popularity: {len(brands)} brands with {MIN_SCORE}+ look-ups in {WINDOW_DAYS} days -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
