"""Point the site at its real address, and write sitemap.xml and robots.txt.

Usage:
  python scripts/configure_site.py --site-url https://USER.github.io/REPO/ \\
                                   --repo-url https://github.com/USER/REPO
  python scripts/configure_site.py          (re-run with the saved values)

Open Graph, canonical links and the sitemap need absolute URLs, and the
report-an-error link needs the repository. Both live in site.config.json.
This replaces the previously saved values wherever they appear in the HTML
pages, saves the new ones, and regenerates sitemap.xml and robots.txt.

Note: crawlers only read robots.txt at the root of a domain. On a project
site (USER.github.io/REPO/) it is ignored; submit sitemap.xml in Google
Search Console instead. It does work on a custom domain or a user site.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "site.config.json"
META = ROOT / "data" / "meta.json"
PAGES = ["index.html", "about.html"]
PLACEHOLDER = "YOUR-GITHUB-USERNAME"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-url")
    ap.add_argument("--repo-url")
    args = ap.parse_args()

    old = json.loads(CONFIG.read_text(encoding="utf-8"))
    new = dict(old)
    if args.site_url:
        new["site_url"] = args.site_url if args.site_url.endswith("/") else args.site_url + "/"
    if args.repo_url:
        new["repo_url"] = args.repo_url.rstrip("/")
    for key in ("site_url", "repo_url"):
        if not new[key].startswith("https://"):
            raise SystemExit(f"{key} must start with https://")

    for page in PAGES:
        path = ROOT / page
        text = path.read_text(encoding="utf-8")
        for key in ("site_url", "repo_url"):
            text = text.replace(old[key], new[key])
        path.write_text(text, encoding="utf-8")

    meta = json.loads(META.read_text(encoding="utf-8"))
    lastmod = max(meta["effective"], meta["printed"])
    urls = "".join(
        f"  <url>\n    <loc>{new['site_url']}{'' if p == 'index.html' else p}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n  </url>\n"
        for p in PAGES
    )
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n", encoding="utf-8")
    (ROOT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {new['site_url']}sitemap.xml\n", encoding="utf-8")

    CONFIG.write_text(json.dumps(new, indent=1) + "\n", encoding="utf-8")
    print(f"site_url = {new['site_url']}\nrepo_url = {new['repo_url']}")
    print("Updated", ", ".join(PAGES), "and wrote sitemap.xml, robots.txt")
    if PLACEHOLDER in new["site_url"] or PLACEHOLDER in new["repo_url"]:
        print("WARNING: still using placeholder URLs. Re-run with --site-url and --repo-url "
              "before publishing, or the share previews, sitemap and error-report link will be broken.")


if __name__ == "__main__":
    main()
