"""Fetch the licensed photos and sourced descriptions listed in data/media_sources.json.

Usage:  python scripts/fetch_media.py      (then python scripts/build_pages.py)

Run by hand after editing media_sources.json; not part of CI. It needs the
network, curl and Pillow (pip install pillow). Writes:
  assets/products/<id>.jpg     a 360px-wide JPEG of each photo, ~20-40 KB (committed)
  data/media.json              attribution and text the pages use (committed)

Rules it enforces, so a mistake in the sources file cannot slip through:
  * photos must be under a free licence (CC0, public domain, CC BY, CC BY-SA);
    anything else is refused
  * every photo keeps author, licence, licence link and source link, which the
    page shows next to it
  * description sentences that state alcohol strength (%, ABV, proof) are
    dropped, because this site does not show alcohol content; the page then
    says the text was shortened
  * every id must exist in the current list, and every description match
    string must hit at least one brand
"""

import html
import io
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "data" / "media_sources.json"
OUT = ROOT / "data" / "media.json"
IMG_DIR = ROOT / "assets" / "products"
WIDTH = 360          # display is at most 320 CSS px; cheap phones are ~2x density at best
UA = "beverage_lister/1.0 (https://github.com/niap3/beverage_lister)"

FREE = re.compile(r"^(CC0|Public domain|PD.*|CC BY(-SA)? [0-9.]+|CC BY(-SA)?)$", re.I)
LICENSE_URLS = {"CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
                "Public domain": "https://en.wikipedia.org/wiki/Public_domain"}
STRENGTH = re.compile(r"\d\s*%|per\s*cent|alcohol by volume|\bABV\b|\bproof\b", re.I)


def get(url):
    return subprocess.run(["curl", "-sS", "--fail", "-L", "-A", UA, url],
                          capture_output=True, check=True).stdout


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def fetch_photo(entry):
    api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo"
           "&iiprop=url|extmetadata&iiurlwidth=600&titles=" + quote(entry["file"]))
    page = next(iter(json.loads(get(api))["query"]["pages"].values()))
    if "imageinfo" not in page:
        raise SystemExit(f"Not found on Commons: {entry['file']}")
    ii = page["imageinfo"][0]
    md = ii["extmetadata"]
    lic = md.get("LicenseShortName", {}).get("value", "")
    if not FREE.match(lic):
        raise SystemExit(f"Refusing {entry['file']}: licence {lic!r} is not free")
    data, (w, h) = shrink(get(ii["thumburl"]))
    return {
        "artist": clean(md.get("Artist", {}).get("value")) or "Unknown author",
        "license": lic,
        "license_url": md.get("LicenseUrl", {}).get("value") or LICENSE_URLS.get(lic, ii["descriptionurl"]),
        "source_url": ii["descriptionurl"],
        "width": w, "height": h,
    }, data


def shrink(raw):
    """Re-encode as a small progressive JPEG on white (PNG transparency)."""
    from PIL import Image
    im = Image.open(io.BytesIO(raw))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    im = im.convert("RGB")
    if im.width > WIDTH:
        im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=78, optimize=True, progressive=True)
    return out.getvalue(), im.size


def fetch_description(entry):
    s = json.loads(get("https://en.wikipedia.org/api/rest_v1/page/summary/" + quote(entry["wikipedia"], safe="")))
    if s.get("type") != "standard":
        raise SystemExit(f"Wikipedia {entry['wikipedia']}: not a normal article ({s.get('type')})")
    sentences = re.split(r"(?<=[.!?])\s+", s["extract"].strip())
    kept = [x for x in sentences if not STRENGTH.search(x)]
    return {
        "label": entry["label"], "match": entry["match"],
        "extract": " ".join(kept),
        "shortened": len(kept) < len(sentences),
        "url": s["content_urls"]["desktop"]["page"],
        "revision": s.get("revision"),
    }


def main():
    src = json.loads(SOURCES.read_text(encoding="utf-8"))
    ids = {p["id"] for p in json.loads((ROOT / "data" / "products.json").read_text(encoding="utf-8"))}
    names = {p["brand"] for p in json.loads((ROOT / "data" / "products.json").read_text(encoding="utf-8"))}

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    for old in IMG_DIR.iterdir():
        old.unlink()
    photos = {}
    for entry in src["photos"]:
        missing = [i for i in entry["ids"] if i not in ids]
        if missing:
            raise SystemExit(f"{entry['file']}: ids not in the current list: {missing}")
        meta, data = fetch_photo(entry)
        name = f"{entry['ids'][0]}.jpg"
        (IMG_DIR / name).write_bytes(data)
        for i in entry["ids"]:
            photos[i] = dict(meta, path=f"assets/products/{name}", alt=entry["alt"],
                             tier=entry["tier"], note=entry["note"])
        print(f"photo  {entry['tier']:6} {meta['license']:12} {len(data) // 1024:4} KB  {entry['file'][5:]}")

    descriptions = []
    for entry in src["descriptions"]:
        hits = [n for n in names if any(m in n for m in entry["match"])]
        if not hits:
            raise SystemExit(f"{entry['wikipedia']}: match {entry['match']} hits no brand")
        d = fetch_description(entry)
        descriptions.append(d)
        print(f"text   {len(hits):3} brands  {'shortened ' if d['shortened'] else ''}{entry['wikipedia']}")

    OUT.write_text(json.dumps({"fetched": date.today().isoformat(), "photos": photos,
                               "descriptions": descriptions}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    covered = len({n for n in names for d in descriptions if any(m in n for m in d["match"])})
    print(f"\n{len(photos)} list entries have a photo, {covered} brands have a description. "
          f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
