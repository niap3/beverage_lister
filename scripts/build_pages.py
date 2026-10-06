"""Generate the static brand pages, the catalogue and the sitemap.

Usage:  python scripts/build_pages.py
(parse_pdf.py and configure_site.py run this for you; CI runs it on deploy.)

Writes, all generated and git-ignored:
  p/<ID>.html              one page per brand (ID = its lowest product code)
  catalogue.html           every type, with counts
  catalogue/<type>.html    every brand of that type, A to Z
  sitemap.xml              every page above plus index.html and about.html

Static pages, not a JS-rendered product view, so each brand has a real URL
that loads without the 116 KB data file, works with scripts off, and gets
its own title and share preview.

Inputs: data/products.json + data/products.meta.json (current list),
data/history/*.json (every list, for price history), data/media.json
(licensed photos and sourced descriptions, see scripts/fetch_media.py) and
site.config.json (absolute URLs).
"""

import html
import json
import shutil
from urllib.parse import quote
from collections import OrderedDict, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CATEGORY_ORDER = ["whisky", "brandy", "rum", "vodka", "gin", "beer", "wine",
                  "liqueur", "tequila", "other"]
CAT_LABEL = {"whisky": "Whisky", "brandy": "Brandy", "rum": "Rum", "vodka": "Vodka",
             "gin": "Gin", "beer": "Beer", "wine": "Wine", "liqueur": "Liqueur",
             "tequila": "Tequila", "other": "Other"}
CAT_NOTE = {"other": "Items whose name does not say what they are, mostly wines, "
                     "coolers and beers listed without the word in their name."}

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='6' fill='%238A3B1E'/%3E%3Ctext x='16' y='24' "
           "font-size='22' font-family='sans-serif' font-weight='700' text-anchor='middle' "
           "fill='%23FFFDF8'%3E%E2%82%B9%3C/text%3E%3C/svg%3E")

e = html.escape


def inr(n):
    """Indian digit grouping: 125000 -> 1,25,000."""
    s = str(int(round(n)))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def plural(n, word):
    return f"{inr(n)} {word}{'' if n == 1 else 's'}"


def money(n):
    return "₹" + inr(n)


def nice_date(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B')} {d.year}"


def load_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


# --------------------------------------------------------------- data model

def brands_from(products):
    """Group bottles into brands, same grouping and id as build_site_data."""
    groups = OrderedDict()
    for p in products:
        g = groups.setdefault(p["brand"], {"name": p["brand"], "supplier": p["supplier"],
                                           "category": p["category"], "sizes": []})
        g["sizes"].append(p)
    out = []
    for g in groups.values():
        g["sizes"].sort(key=lambda p: p["volume_ml"])
        g["id"] = min(p["id"] for p in g["sizes"])
        out.append(g)
    return out


def history_index():
    """product code -> [(version meta, price)] across every saved list, oldest first.
    Also (brand, ml) -> same, as a fallback if a code changed between lists."""
    by_code, by_name = defaultdict(list), defaultdict(list)
    versions = []
    for f in sorted((DATA / "history").glob("*.json")):
        h = load_json(f)
        versions.append(h["meta"])
        for p in h["products"]:
            by_code[p["id"]].append((h["meta"], p["shop_price"]))
            by_name[(p["brand"], p["volume_ml"])].append((h["meta"], p["shop_price"]))
    versions.sort(key=lambda m: (m["effective"], m["printed"]))
    return versions, by_code, by_name


# ----------------------------------------------------------------- template

def page(*, title, description, canonical, og_image, root, body, site_name, foot, active=""):
    nav = [("catalogue.html", "Catalogue"), ("about.html", "About")]   # the site name links to search
    links = " ".join(
        f'<a href="{root}{href}"{" aria-current=\"page\"" if label == active else ""}>{label}</a>'
        for href, label in nav)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{e(site_name)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(canonical)}">
<meta property="og:image" content="{e(og_image)}">
<meta property="og:locale" content="en_IN">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#FFFFFF">
<meta name="color-scheme" content="light">
<link rel="icon" href="{FAVICON}">
<link rel="preload" href="{root}assets/fonts/barlow-semi-condensed-latin-700-normal.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{root}assets/fonts/fraunces-latin-600-normal.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{root}assets/style.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="masthead">
  <div class="wrap masthead-row">
    <p class="site-name"><a href="{root}./"><span class="logo-mark" aria-hidden="true">₹</span>{e(site_name)}</a></p>
    <nav aria-label="Site" class="site-nav">{links}</nav>
  </div>
  <div class="wrap"><p class="age">For adults only. The legal drinking age in Kerala is 23.</p></div>
</header>
<main class="wrap page" id="main" tabindex="-1">
{body}
</main>
{foot.replace("{root}", root)}
</body>
</html>
"""


def footer(meta):
    return f"""<footer class="footer">
  <div class="wrap">
    <p><strong>Source:</strong> {e(meta['source'])}, {e(meta['title'])}.</p>
    <p>Prices effective from <strong>{nice_date(meta['effective'])}</strong>. List printed on <strong>{nice_date(meta['printed'])}</strong>.</p>
    <p><a href="{{root}}source/pricelist.pdf">Open the original price list (PDF)</a><br><a href="{{root}}about.html">About this site and reporting an error</a></p>
    <p>This is an unofficial lookup, not run by or connected to KSBC (Bevco). It is for information only. It does not sell or deliver alcohol, and it has no ads or affiliate links. Prices are the FL-1 shop price after tax, copied from the list above. If that list has changed since, a shop may charge a different price, and the shop’s price applies.</p>
  </div>
</footer>"""


# ------------------------------------------------------------- brand pages

def size_cells(sizes):
    """Price cells; with 2+ sizes, the lowest price per litre gets a sticker."""
    ppl = [p["shop_price"] * 1000 / p["volume_ml"] for p in sizes]
    best = min(ppl) if len(sizes) > 1 else None
    return "".join(
        f'<li{" class=\"best\"" if v == best else ""}><span class="ml">{p["volume_ml"]} ml</span>'
        f'<span class="price-tag">{money(p["shop_price"])}</span>'
        f'<span class="per-litre">{money(v)} per litre</span>'
        f'{"<span class=\"sticker\">Best value</span>" if v == best else ""}</li>'
        for p, v in zip(sizes, ppl))


def history_section(b, versions, by_code, by_name):
    if len(versions) < 2:
        first = versions[0] if versions else None
        when = f" ({nice_date(first['effective'])})" if first else ""
        return ("<section><h2>Price history</h2>"
                f"<p>Price history starts with the list this site was built from{when}. "
                "Changes will show here once KSBC publishes a new list.</p></section>")
    head = "".join(f'<th scope="col">{p["volume_ml"]} ml</th>' for p in b["sizes"])
    rows = []
    for v in versions:
        cells = []
        for p in b["sizes"]:
            series = by_code.get(p["id"]) or by_name.get((p["brand"], p["volume_ml"]), [])
            price = next((pr for m, pr in series if m["version"] == v["version"]), None)
            cells.append(f"<td>{money(price)}</td>" if price is not None
                         else '<td class="none">Not listed</td>')
        rows.append(f'<tr><th scope="row">{nice_date(v["effective"])}</th>{"".join(cells)}</tr>')
    return ("<section><h2>Price history</h2>"
            '<div class="table-scroll"><table class="cmp-table history">'
            f'<caption class="visually-hidden">Shop price by list date and bottle size</caption>'
            f'<thead><tr><th scope="col">List from</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></section>')


def photo_figure(media, root):
    if not media:
        return ""
    credit = (f'Photo: {e(media["artist"])}, <a href="{e(media["license_url"])}">{e(media["license"])}</a>, '
              f'via <a href="{e(media["source_url"])}">Wikimedia Commons</a>')
    if media["tier"] == "family":
        credit = ("<strong>Photo of the brand, not necessarily this exact variant.</strong> " + credit)
    else:
        credit += ". The label or bottle size may differ from what the shop has"
    return (f'<figure class="product-photo"><img src="{root}{e(media["path"])}" '
            f'alt="{e(media["alt"])}" width="{media["width"]}" height="{media["height"]}" loading="lazy">'
            f"<figcaption>{credit}</figcaption></figure>")


def description_section(desc):
    if not desc:
        return ""
    return (f'<section class="about-brand"><h2>About {e(desc["label"])}</h2>'
            f'<p>{e(desc["extract"])}</p>'
            f'<p class="small">{"Shortened from" if desc.get("shortened") else "From"} '
            f'<a href="{e(desc["url"])}">Wikipedia</a>, '
            f'<a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>. '
            f'This describes the brand, not necessarily this exact bottle.</p></section>')


def brand_page(b, meta, cfg, versions, by_code, by_name, media, foot):
    site = cfg["site_url"]
    root = "../"
    cat = b["category"]
    photo = media.get("photos", {}).get(b["id"])
    desc = next((d for d in media.get("descriptions", [])
                 if any(m in b["name"] for m in d["match"])), None)
    cheapest = min(b["sizes"], key=lambda p: p["shop_price"])
    sizes_txt = ", ".join(f'{p["volume_ml"]} ml {money(p["shop_price"])}' for p in b["sizes"])
    title = f'{b["name"]} price in Kerala: from {money(cheapest["shop_price"])}'
    description = (f'Bevco FL-1 shop price for {b["name"]}: {sizes_txt}. '
                   f'Prices as of {nice_date(meta["effective"])}. Unofficial lookup.')
    codes = "".join(f'<li>{p["volume_ml"]} ml: <code>{e(p["id"])}</code></li>' for p in b["sizes"])
    report = e(cfg["repo_url"] + "/issues/new?title=" + quote(f"Price error: {b['name']}") +
               "&body=" + quote("Bottle size:\nPrice on this site:\nPrice in the PDF or at the shop:\n"))
    body = f"""<nav aria-label="Breadcrumb" class="crumbs"><a href="{root}catalogue.html">Catalogue</a> › <a href="{root}catalogue/{cat}.html">{CAT_LABEL[cat]}</a></nav>
<article class="product" data-cat="{cat}">
  <h1>{e(b["name"])}</h1>
  <p class="asof">Prices as of <time datetime="{meta['effective']}">{nice_date(meta['effective'])}</time>, from the Bevco price list</p>
  <div class="product-main">
    <div class="card product-prices">
      <ul class="sizes" aria-label="Sizes and prices">{size_cells(b["sizes"])}</ul>
    </div>
    {photo_figure(photo, root)}
  </div>
  <p class="actions"><a class="button-link" href="{root}?cmp={e(b['id'])}">Compare with other brands</a> <a href="{root}?cat={cat}&amp;sort=price-asc">Cheapest {CAT_LABEL[cat].lower()}</a></p>
  <section>
    <h2>Details</h2>
    <dl class="facts">
      <dt>Type</dt><dd>{CAT_LABEL[cat]}<span class="small"> (from the name; the list has no type column)</span></dd>
      <dt>Supplier</dt><dd>{e(b["supplier"])}</dd>
      <dt>Product codes</dt><dd><ul class="codes">{codes}</ul></dd>
    </dl>
  </section>
  {description_section(desc)}
  {history_section(b, versions, by_code, by_name)}
  <p class="small"><a href="{report}">Report a wrong price or name</a> (needs a free GitHub account)</p>
</article>"""
    og = site + photo["path"] if photo else site + "assets/og-image.png"
    return page(title=title, description=description, canonical=f'{site}p/{b["id"]}.html',
                og_image=og, root=root, body=body, site_name="Kerala liquor prices", foot=foot)


# --------------------------------------------------------------- catalogue

def catalogue_pages(brands, meta, cfg, foot):
    site = cfg["site_url"]
    by_cat = defaultdict(list)
    for b in brands:
        by_cat[b["category"]].append(b)
    cats = [c for c in CATEGORY_ORDER if c in by_cat]

    tiles = "".join(
        f'<li data-cat="{c}"><a href="catalogue/{c}.html"><span class="cat-name">{CAT_LABEL[c]}</span>'
        f'<span class="cat-count">{plural(len(by_cat[c]), "brand")}</span>'
        f'<span class="cat-big">from {money(min(p["shop_price"] for b in by_cat[c] for p in b["sizes"]))}</span></a></li>'
        for c in cats)
    overview = page(
        title="Catalogue: every brand in the Kerala price list",
        description=f'Browse all {inr(len(brands))} brands in the Bevco price list by type, A to Z.',
        canonical=f"{site}catalogue.html", og_image=site + "assets/og-image.png", root="",
        site_name="Kerala liquor prices", active="Catalogue", foot=foot,
        body=f"""<h1>Catalogue</h1>
<p>All {inr(len(brands))} brands in the Bevco price list from {nice_date(meta['effective'])}, by type. Type is read from the brand name, because the list itself has no type column.</p>
<ul class="cat-tiles">{tiles}</ul>""")

    pages = {"catalogue.html": overview}
    for c in cats:
        items = sorted(by_cat[c], key=lambda b: b["name"])
        groups = OrderedDict()
        for b in items:
            first = b["name"][0]
            groups.setdefault(first if first.isalpha() else "0-9", []).append(b)
        jump = " ".join(f'<a href="#l-{k}">{k}</a>' for k in groups)
        lists = "".join(
            f'<h2 id="l-{k}">{k}</h2><ul class="brand-list">' + "".join(
                f'<li><a href="../p/{e(b["id"])}.html">{e(b["name"])}</a>'
                f'<span class="brand-sizes">{" · ".join(str(p["volume_ml"]) for p in b["sizes"])} ml</span>'
                f'<span class="brand-from">from {money(min(p["shop_price"] for p in b["sizes"]))}</span></li>'
                for b in bs) + "</ul>"
            for k, bs in groups.items())
        note = f'<p>{CAT_NOTE[c]}</p>' if c in CAT_NOTE else ""
        pages[f"catalogue/{c}.html"] = page(
            title=f"{CAT_LABEL[c]} prices in Kerala: all {len(items)} brands",
            description=f"Every {CAT_LABEL[c].lower()} in the Bevco price list, A to Z, with sizes and the lowest price.",
            canonical=f"{site}catalogue/{c}.html", og_image=site + "assets/og-image.png", root="../",
            site_name="Kerala liquor prices", active="Catalogue", foot=foot,
            body=f"""<nav aria-label="Breadcrumb" class="crumbs"><a href="../catalogue.html">Catalogue</a></nav>
<h1>{CAT_LABEL[c]} <span class="small">({plural(len(items), "brand")})</span></h1>
{note}
<p class="jump" aria-label="Jump to letter">{jump}</p>
{lists}""")
    return pages


# -------------------------------------------------------------------- main

def main():
    products = load_json(DATA / "products.json")
    meta = load_json(DATA / "products.meta.json")
    cfg = load_json(ROOT / "site.config.json")
    media = load_json(DATA / "media.json", {})
    foot = footer(meta)
    brands = brands_from(products)
    versions, by_code, by_name = history_index()

    for d in ("p", "catalogue"):
        shutil.rmtree(ROOT / d, ignore_errors=True)
        (ROOT / d).mkdir()
    for b in brands:
        (ROOT / "p" / f'{b["id"]}.html').write_text(
            brand_page(b, meta, cfg, versions, by_code, by_name, media, foot), encoding="utf-8")
    cat_pages = catalogue_pages(brands, meta, cfg, foot)
    for rel, text in cat_pages.items():
        (ROOT / rel).write_text(text, encoding="utf-8")

    site = cfg["site_url"]
    lastmod = max(meta["effective"], meta["printed"])
    urls = ["", "about.html"] + list(cat_pages) + [f'p/{b["id"]}.html' for b in brands]
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
        "".join(f"  <url><loc>{site}{u}</loc><lastmod>{lastmod}</lastmod></url>\n" for u in urls) +
        "</urlset>\n", encoding="utf-8")
    print(f"Wrote {len(brands)} brand pages, {len(cat_pages)} catalogue pages, "
          f"sitemap with {len(urls)} URLs ({len(versions)} list version(s) in history, "
          f"{len(media.get('photos', {}))} photos, {len(media.get('descriptions', []))} descriptions)")


if __name__ == "__main__":
    main()
