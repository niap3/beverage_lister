"""Build the "Trending this week" ranking from GoatCounter.

Usage:  GOATCOUNTER_TOKEN=... python scripts/fetch_popularity.py [out.json]
        (CI runs this on deploy and weekly; default out is data/popularity.json)

What it ranks: interest on this site. A brand's interest is the number of
visitors to its page (p/<id>.html) plus the times it was added to the
compare tray. Brands are ordered by the last 7 days, ties broken by the last
30. It is not sales; the site says "trending", never "best selling".

Only the ORDER is published (a list of brand ids), never the counts.
Brands with fewer than MIN_30D look-ups in 30 days are left out as noise.

Needs "goatcounter" (the site code) in site.config.json and an API token
that can read statistics in GOATCOUNTER_TOKEN. Without either, or if the
API fails, it writes nothing and exits 0: a stats problem never blocks a
price update, and the site simply shows no trending sort.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_30D = 3
PAGE_RE = re.compile(r"/p/([0-9A-Z]{9})\.html$")
EVENT_RE = re.compile(r"^/?compare/([0-9A-Z]{9})$")


def tally(hits, known_ids):
    """GoatCounter hit rows -> {brand id: {"views": n, "compares": n}}. Pure, for tests."""
    out = {}
    for h in hits:
        path = h.get("path") or ""
        m = EVENT_RE.match(path) if h.get("event") else PAGE_RE.search(path)
        if not m or m.group(1) not in known_ids:
            continue
        rec = out.setdefault(m.group(1), {"views": 0, "compares": 0})
        rec["compares" if h.get("event") else "views"] += int(h.get("count") or 0)
    return out


def rank(week, month, min_month=MIN_30D):
    """Brand ids ordered by 7-day interest, then 30-day. Pure, for tests."""
    total = lambda c: c["views"] + c["compares"]
    ids = [i for i, c in month.items() if total(c) >= min_month]
    return sorted(ids, key=lambda i: (-total(week.get(i, {"views": 0, "compares": 0})),
                                      -total(month[i]), i))


def fetch_hits(code, token, days):
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    start = end - timedelta(days=days)
    seen, rows = [], []
    while True:
        q = [("start", start.strftime("%Y-%m-%dT%H:%M:%SZ")), ("end", end.strftime("%Y-%m-%dT%H:%M:%SZ")),
             ("limit", "100")] + [("exclude_paths", str(i)) for i in seen]
        req = urllib.request.Request(
            f"https://{code}.goatcounter.com/api/v0/stats/hits?" + urllib.parse.urlencode(q),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "User-Agent": "beverage_lister"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"HTTP {e.code} from /api/v0/stats/hits: {body}") from None
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
        print("Trending: no GoatCounter code or token configured; skipping.")
        return 0
    known = {p["id"] for p in json.loads((ROOT / "data" / "products.json").read_text(encoding="utf-8"))}
    try:
        week = tally(fetch_hits(code, token, 7), known)
        month = tally(fetch_hits(code, token, 30), known)
    except Exception as e:  # a stats outage must never block a price deploy
        print(f"Trending: GoatCounter request failed ({e}); skipping.")
        return 0
    ranked = rank(week, month)
    if not ranked:
        print(f"Trending: no brand has {MIN_30D}+ look-ups in 30 days yet; skipping.")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"updated": datetime.now(timezone.utc).date().isoformat(),
                               "window_days": 7, "ranked": ranked}, separators=(",", ":")),
                   encoding="utf-8")
    print(f"Trending: ranked {len(ranked)} brands -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
