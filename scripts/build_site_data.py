"""Build the compact, grouped data file the site loads: data/site.json.

Usage:  python scripts/build_site_data.py
(scripts/parse_pdf.py runs this automatically after writing products.json.)

data/products.json is one object per bottle with repeated keys (~1.3 MB).
The site only needs one entry per brand with its sizes, so this writes:

  {
    "meta": {...},
    "suppliers": ["UNIBEV JSM, GOA", ...],
    "categories": ["whisky", ...],
    "brands": [[id, name, supplier_index, category_index, [[ml, price], ...]], ...]
  }

`id` is the brand's lowest product code. The compare tray puts it in the URL,
so a shared comparison survives a rebuild that reorders brands.

It also writes data/meta.json (the "meta" block alone) for pages that need the
dates but not the whole list, such as the About page.

Sizes are sorted by volume. Each brand has exactly one supplier and no size
appears twice in this list; both are asserted rather than assumed.
"""

import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "products.json"
SRC_META = ROOT / "data" / "products.meta.json"   # written by parse_pdf.py from the PDF header
MEDIA = ROOT / "data" / "media.json"              # written by fetch_media.py; optional
OUT = ROOT / "data" / "site.json"
META_OUT = ROOT / "data" / "meta.json"

# Display order for filter chips; categories with no products are dropped.
CATEGORY_ORDER = ["whisky", "brandy", "rum", "vodka", "gin", "beer", "wine",
                  "liqueur", "tequila", "other"]


def build(products, src_meta, media=None):
    """Pure: product list + list metadata (+ media) -> the site.json object."""
    groups = OrderedDict()
    for p in products:
        g = groups.setdefault(p["brand"], {"supplier": p["supplier"],
                                           "category": p["category"],
                                           "sizes": [], "codes": []})
        assert g["supplier"] == p["supplier"], f"{p['brand']}: more than one supplier"
        assert g["category"] == p["category"], f"{p['brand']}: more than one category"
        assert all(ml != p["volume_ml"] for ml, _ in g["sizes"]), \
            f"{p['brand']}: {p['volume_ml']} ml listed twice"
        assert p["shop_price"] == int(p["shop_price"]), f"{p['id']}: non-integer price"
        g["sizes"].append([p["volume_ml"], int(p["shop_price"])])
        g["codes"].append(p["id"])

    suppliers = sorted({g["supplier"] for g in groups.values()})
    present = {g["category"] for g in groups.values()}
    categories = [c for c in CATEGORY_ORDER if c in present]
    assert present <= set(categories), f"unknown categories {present - set(categories)}"
    s_idx = {s: i for i, s in enumerate(suppliers)}
    c_idx = {c: i for i, c in enumerate(categories)}

    brands = [
        [min(g["codes"]), name, s_idx[g["supplier"]], c_idx[g["category"]], sorted(g["sizes"])]
        for name, g in groups.items()
    ]
    ids = [b[0] for b in brands]
    assert len(set(ids)) == len(ids), "brand ids are not unique"

    meta = {k: src_meta[k] for k in ("source", "title", "effective", "printed", "version", "pdf")}
    meta.update(bottles=len(products), brands=len(brands))
    # Thumbnail path per brand id, only for brands in this list.
    photos = {i: p["path"] for i, p in ((media or {}).get("photos") or {}).items() if i in set(ids)}
    return {"meta": meta, "suppliers": suppliers, "categories": categories, "brands": brands,
            "photos": photos}


def main():
    products = json.loads(SRC.read_text(encoding="utf-8"))
    src_meta = json.loads(SRC_META.read_text(encoding="utf-8"))
    media = json.loads(MEDIA.read_text(encoding="utf-8")) if MEDIA.exists() else None
    out = build(products, src_meta, media)
    brands, meta = out["brands"], out["meta"]
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    META_OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {len(brands)} brands / {len(products)} bottles to "
          f"{OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB) and {META_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
