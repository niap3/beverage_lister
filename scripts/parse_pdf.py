"""Parse the KSBC (Bevco) IMFL/Beer/Wine price list PDF into data/products.json.

Usage:
  python scripts/parse_pdf.py [new.pdf]        parse, validate, diff, save, rebuild site data
  python scripts/parse_pdf.py --check [x.pdf]  parse and validate only; writes nothing
  Options: --all (print every diff line), --others (list "other"-category items),
           --no-site (skip rebuilding data/site.json), --force (write despite problems)

With no PDF argument it re-parses source/pricelist.pdf, which should report
no changes. A run that writes does all of this:
  1. parses and validates every row (see below); stops on any problem
  2. prints a diff against the current data/products.json: new items,
     removed items, price changes, renamed items
  3. writes data/products.json (the list) and data/products.meta.json (the
     list's dates and title, read from the PDF header)
  4. saves a copy as data/history/<effective>_<printed>.json, so price
     history can be built later, and archives the PDF as
     source/archive/<effective>_<printed>.pdf
  5. copies the PDF to source/pricelist.pdf (what the site links to)
  6. rebuilds data/site.json and data/meta.json for the site

Why `pdftotext -raw` and not `-layout`:
In this PDF the FL1-shop price columns are a separate text block with a
different line pitch from the rest of the row. `-layout` places them by
y-position, so they drift off their rows (two triplets beside one row, none
beside another) and a row's numbers sometimes land on the supplier-header
line. `-raw` emits content-stream order instead, where every product is one
line:

    <code> [description] ml case proof landed excise import wh_bt wh_tax wh_at fl_bt fl_tax fl_at
    <sl_no> <cess>

Two checks prove each FL1 triplet sits on its own row:
  * arithmetic: fl_bt + fl_tax + cess == fl_at and
                wh_bt + wh_tax + cess*case == wh_at, using the row's own cess
  * cross-column: fl_bt / (wh_bt / case) stays in a narrow band, so a triplet
    shifted onto a neighbouring row would stand out.

Every non-blank line must be classified (page furniture, supplier header,
product row, sl/cess line, closing signature block). Anything else aborts the
run, so nothing can be silently dropped.

Tested with xpdf's pdftotext 4.00. Poppler's pdftotext has the same -raw
mode but has not been checked against this file.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = ROOT / "source" / "pricelist.pdf"
DATA = ROOT / "data"
OUT = DATA / "products.json"
META_OUT = DATA / "products.meta.json"
HISTORY = DATA / "history"
ARCHIVE = ROOT / "source" / "archive"

NUM = r"-?\d+(?:\.\d+)?"
ROW_RE = re.compile(
    r"^(?P<code>[0-9A-Z]{9})(?:\s+(?P<desc>.*?))?\s+"
    r"(?P<ml>\d+) (?P<case>\d+) (?P<proof>{n}) (?P<landed>{n}) (?P<excise>{n}) (?P<import>{n}) "
    r"(?P<wh_bt>{n}) (?P<wh_tax>{n}) (?P<wh_at>{n}) "
    r"(?P<fl_bt>{n}) (?P<fl_tax>{n}) (?P<fl_at>{n})$".replace("{n}", NUM)
)
SLCESS_RE = re.compile(r"^(?P<sl>\d+) (?P<cess>\d+\.\d+)$")
SECTION_RE = re.compile(r"^(?P<kind>IMFL|BEER|WINE) Supplier :$")
SUPPLIER_RE = re.compile(r"^(?P<code>\d{3}) (?P<name>.+)$")
PAGE_FOOTER_RE = re.compile(r"^\* Note : Page (\d+)$")

# Column-header and title lines repeated on every page.
PAGE_FURNITURE = {
    "PRICE LIST", "Product", "Code Description", "UOM", "ml", "Bot/",
    "Case Proof", "Landed", "Cost", "Excise", "Duty", "Import", "Fee",
    "Cess", "Amt.", "Sl.No", "Before Tax Tax* After Tax",
    "Selling Price at Warehouse Selling Price at FL1 Shop",
}
TITLE_PREFIX = "Kerala State Beverages (M&M) Corporation Limited Price List"
# Signature block after the last row on the final page.
CLOSING = {"Sd/-", "Managing Director"}
CLOSING_RE = re.compile(r"^Prepared by\s*:")

# Page title, e.g. "... Price List of IMFL/BEER/WINE for Warehouses and FL-1
# Shops With effect from 11-05-2026 (Tender 2026-27 - Quoted Items) 23-Sep-26"
HEADER_RE = re.compile(
    r"^Kerala State Beverages \(M&M\) Corporation Limited (?P<title>Price List of .+?) "
    r"With effect from (?P<eff>\d{2}-\d{2}-\d{4})\s*(?P<tender>\(.+?\))\s+(?P<printed>\d{1,2}-[A-Za-z]{3}-\d{2})$"
)

# Order matters: beer first, because e.g. "STRONG MALT BEER" must not be
# caught by anything else; wine second so "PORT WINE" etc. resolve early.
CATEGORY_RULES = [
    ("beer", r"\bBEERS?\b"),
    ("wine", r"\bWINES?\b"),
    ("whisky", r"\bWHISK(?:E)?Y\b"),
    ("brandy", r"\bBRANDY\b"),
    ("rum", r"\bRUM\b"),
    ("vodka", r"\bVODKA\b"),
    ("gin", r"\bGIN\b"),
    ("liqueur", r"\bLIQUEUR\b"),
    ("tequila", r"\bTEQUILA\b"),
]

# FL1-before-tax / warehouse-before-tax-per-bottle. Observed 1.07-1.33 (top: Rs 80
# 180ml port wine, sl 4019, where Rs 10 rounding is 12%); the
# spread is the after-tax price being rounded to Rs 10 on cheap bottles.
RATIO_BAND = (1.03, 1.35)


class ParseError(Exception):
    pass


def categorize(desc):
    for cat, pat in CATEGORY_RULES:
        if re.search(pat, desc):
            return cat
    return "other"


def extract_text(pdf):
    try:
        out = subprocess.run(
            ["pdftotext", "-raw", "-enc", "UTF-8", str(pdf), "-"],
            check=True, capture_output=True,
        ).stdout
    except FileNotFoundError:
        raise ParseError("pdftotext not found on PATH (xpdf or poppler-utils).")
    return out.decode("utf-8")


def parse_header(text):
    """Effective date, printed date and title, from the page header.
    Every page repeats it; all copies must agree."""
    found = set()
    for line in text.split("\n"):
        m = HEADER_RE.match(line.replace("\f", "").strip())
        if m:
            found.add(m.groups())
    if not found:
        raise ParseError("Could not find the 'With effect from ... <printed date>' page header.")
    if len(found) > 1:
        raise ParseError(f"Page headers disagree: {sorted(found)}")
    title, eff, tender, printed = found.pop()
    effective = datetime.strptime(eff, "%d-%m-%Y").date().isoformat()
    printed_iso = datetime.strptime(printed, "%d-%b-%y").date().isoformat()
    return {
        "source": "Kerala State Beverages (M&M) Corporation Limited",
        "title": f"{title} {tender}",
        "effective": effective,
        "printed": printed_iso,
        "version": f"{effective}_{printed_iso}",
    }


def parse_rows(text):
    rows, unclassified = [], []
    section = supplier = None
    pending_supplier = None   # "NNN NAME" line arrives before its "X Supplier :" line
    last_desc = None
    page = 1
    lines = [l.replace("\f", "").strip() for l in text.split("\n")]
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if (not line or line in PAGE_FURNITURE or line in CLOSING or CLOSING_RE.match(line)
                or line.startswith(TITLE_PREFIX)):
            continue
        m = PAGE_FOOTER_RE.match(line)
        if m:
            page = int(m.group(1)) + 1
            continue
        m = SECTION_RE.match(line)
        if m:
            if pending_supplier is None:
                raise ParseError(f"Section header with no supplier line before it (page {page})")
            section, supplier = m.group("kind"), pending_supplier
            pending_supplier = None
            continue
        m = ROW_RE.match(line)
        if m:
            nxt = lines[i] if i < len(lines) else ""
            sc = SLCESS_RE.match(nxt)
            if not sc:
                raise ParseError(f"Row {m.group('code')} not followed by 'sl cess' line: {nxt!r}")
            i += 1
            if supplier is None:
                raise ParseError(f"Row {m.group('code')} appears before any supplier header")
            desc = (m.group("desc") or "").strip()
            inherited = not desc
            if inherited:
                if last_desc is None or last_desc[1] != supplier:
                    raise ParseError(f"Row {m.group('code')} has blank description and nothing to inherit")
                desc = last_desc[0]
            last_desc = (desc, supplier)
            r = {k: m.group(k) for k in ROW_RE.groupindex}
            r.update(desc=desc, inherited=inherited, sl=int(sc.group("sl")),
                     cess=float(sc.group("cess")), section=section,
                     supplier=supplier, page=page)
            rows.append(r)
            continue
        m = SUPPLIER_RE.match(line)
        if m and i < len(lines) and SECTION_RE.match(lines[i]):
            pending_supplier = m.group("name").strip()
            continue
        unclassified.append((page, line))
    return rows, unclassified


def to_product(r):
    ml = int(r["ml"])
    shop = float(r["fl_at"])
    return {
        "id": r["code"],
        "brand": r["desc"],
        "volume_ml": ml,
        "supplier": r["supplier"],
        "category": categorize(r["desc"]),
        "shop_price": round(shop, 2),
        "shop_price_before_tax": float(r["fl_bt"]),
        "shop_tax": float(r["fl_tax"]),
        "price_per_litre": round(shop * 1000 / ml, 2) if ml else None,
        "sl_no": r["sl"],
    }


def validate(rows, products):
    """Every check that must pass before data is written. Returns problem strings."""
    problems = []
    for r in rows:
        f = {k: float(r[k]) for k in ("wh_bt", "wh_tax", "wh_at", "fl_bt", "fl_tax", "fl_at")}
        case = int(r["case"])
        if abs(f["fl_bt"] + f["fl_tax"] + r["cess"] - f["fl_at"]) > 0.02:
            problems.append(f"sl {r['sl']} {r['code']}: FL1 before+tax+cess != after")
        if abs(f["wh_bt"] + f["wh_tax"] + r["cess"] * case - f["wh_at"]) > 0.05:
            problems.append(f"sl {r['sl']} {r['code']}: warehouse before+tax+cess*case != after")
        if f["wh_bt"] > 0 and case > 0:
            ratio = f["fl_bt"] / (f["wh_bt"] / case)
            if not RATIO_BAND[0] <= ratio <= RATIO_BAND[1]:
                problems.append(f"sl {r['sl']} {r['code']}: FL1/warehouse ratio {ratio:.3f} out of band")

    if not products:
        return problems + ["no products parsed"]
    sls = [p["sl_no"] for p in products]
    missing = sorted(set(range(1, max(sls) + 1)) - set(sls))
    if missing:
        problems.append(f"missing Sl.No (a row was not parsed): {missing[:20]}")
    dup_sl = sorted(k for k, v in Counter(sls).items() if v > 1)
    if dup_sl:
        problems.append(f"duplicate Sl.No: {dup_sl[:20]}")
    dup_id = sorted(k for k, v in Counter(p["id"] for p in products).items() if v > 1)
    if dup_id:
        problems.append(f"duplicate product codes: {dup_id[:20]}")
    for p in products:
        if not p["shop_price"] or not p["shop_price_before_tax"]:
            problems.append(f"sl {p['sl_no']} {p['id']}: missing or zero shop price")
    return problems


def parse_pdf_file(pdf):
    """Parse without writing anything. Returns (meta, rows, products, problems)."""
    text = extract_text(pdf)
    meta = parse_header(text)
    rows, unclassified = parse_rows(text)
    if unclassified:
        shown = "\n".join(f"  p{page}: {line}" for page, line in unclassified[:30])
        raise ParseError(f"{len(unclassified)} unclassified line(s):\n{shown}")
    products = [to_product(r) for r in rows]
    return meta, rows, products, validate(rows, products)


def diff(old, new):
    """Compare two product lists by product code."""
    o = {p["id"]: p for p in old}
    n = {p["id"]: p for p in new}
    added = [n[i] for i in n if i not in o]
    removed = [o[i] for i in o if i not in n]
    changed = [(o[i], n[i]) for i in n if i in o and o[i]["shop_price"] != n[i]["shop_price"]]
    renamed = [(o[i], n[i]) for i in n if i in o and o[i]["brand"] != n[i]["brand"]]
    return added, removed, changed, renamed


def label(p):
    return f"{p['brand']} {p['volume_ml']}ml"


def print_diff(old_version, new_version, d, show_all):
    added, removed, changed, renamed = d
    limit = None if show_all else 25
    print(f"\nChanges from {old_version} to {new_version}:")
    print(f"  {len(added)} new, {len(removed)} removed, {len(changed)} price changes, {len(renamed)} renamed")

    def block(title, items, fmt):
        if not items:
            return
        print(f"\n  {title}:")
        for it in items[:limit]:
            print("   ", fmt(it))
        if limit and len(items) > limit:
            print(f"    ... and {len(items) - limit} more (use --all)")

    block("New", added, lambda p: f"{p['id']}  {label(p)}  Rs {p['shop_price']:.0f}")
    block("Removed", removed, lambda p: f"{p['id']}  {label(p)}  was Rs {p['shop_price']:.0f}")
    up = sum(1 for a, b in changed if b["shop_price"] > a["shop_price"])
    if changed:
        print(f"\n  Price changes: {up} up, {len(changed) - up} down")
    block("Price changes", sorted(changed, key=lambda ab: ab[1]["shop_price"] - ab[0]["shop_price"]),
          lambda ab: f"{ab[1]['id']}  {label(ab[1])}  Rs {ab[0]['shop_price']:.0f} -> Rs {ab[1]['shop_price']:.0f}"
                     f"  ({ab[1]['shop_price'] - ab[0]['shop_price']:+.0f}, "
                     f"{(ab[1]['shop_price'] / ab[0]['shop_price'] - 1) * 100:+.1f}%)")
    block("Renamed (same code)", renamed, lambda ab: f"{ab[1]['id']}  {ab[0]['brand']!r} -> {ab[1]['brand']!r}")


def print_report(meta, rows, products, show_others):
    print(f"Parsed {len(products)} products, list effective {meta['effective']}, printed {meta['printed']}")
    print("  Category counts:", dict(Counter(p["category"] for p in products).most_common()))
    others = {}
    for r, p in zip(rows, products):
        if p["category"] == "other":
            others.setdefault((p["brand"], r["section"]), []).append(p["volume_ml"])
    print(f"  'other' items: {sum(len(v) for v in others.values())} rows, {len(others)} names"
          + ("" if show_others else " (list them with --others)"))
    if show_others:
        for (name, sec), vols in sorted(others.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            print(f"    [{sec}] {name}  ({', '.join(map(str, vols))} ml)")


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", nargs="?", default=str(DEFAULT_PDF))
    ap.add_argument("--check", action="store_true", help="parse and validate only; write nothing")
    ap.add_argument("--all", action="store_true", help="print every diff line")
    ap.add_argument("--others", action="store_true", help="list items categorised as 'other'")
    ap.add_argument("--no-site", action="store_true", help="do not rebuild data/site.json")
    ap.add_argument("--force", action="store_true", help="write even if validation found problems")
    args = ap.parse_args()
    pdf = Path(args.pdf).resolve()
    if not pdf.is_file():
        sys.exit(f"No such file: {pdf}")

    try:
        meta, rows, products, problems = parse_pdf_file(pdf)
    except ParseError as e:
        sys.exit(f"PARSE FAILED: {e}\nNothing was written.")

    print_report(meta, rows, products, args.others)
    if problems:
        print(f"\n{len(problems)} VALIDATION PROBLEM(S):")
        for p in problems:
            print("  ", p)
    else:
        print("  Validation: all checks passed (row arithmetic, FL1/warehouse ratio, "
              "Sl.No sequence, unique codes, no zero prices)")

    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else []
    old_meta = json.loads(META_OUT.read_text(encoding="utf-8")) if META_OUT.exists() else {}
    if old:
        print_diff(old_meta.get("version", "previous data/products.json"), meta["version"],
                   diff(old, products), args.all)
    if old_meta.get("effective") and meta["effective"] < old_meta["effective"]:
        print(f"\nNOTE: this list ({meta['effective']}) is OLDER than the current data "
              f"({old_meta['effective']}).")

    if args.check:
        print("\n--check: nothing written.")
        sys.exit(1 if problems else 0)
    if problems and not args.force:
        sys.exit("\nNot writing anything because of the problems above. "
                 "Fix the parser, or re-run with --force if you have checked them by hand.")

    meta["pdf"] = "source/pricelist.pdf"
    meta["parsed_from"] = pdf.name
    dump(OUT, products)
    dump(META_OUT, meta)
    hist = HISTORY / f"{meta['version']}.json"
    dump(hist, {"meta": meta, "products": products})

    ARCHIVE.mkdir(parents=True, exist_ok=True)
    archived = ARCHIVE / f"{meta['version']}.pdf"
    if not archived.exists():
        shutil.copyfile(pdf, archived)
    if pdf != DEFAULT_PDF.resolve():
        shutil.copyfile(pdf, DEFAULT_PDF)

    print(f"\nWrote {OUT.relative_to(ROOT)}, {META_OUT.relative_to(ROOT)}, {hist.relative_to(ROOT)}")
    print(f"PDF archived as {archived.relative_to(ROOT)}; site links to {DEFAULT_PDF.relative_to(ROOT)}")

    if not args.no_site:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import build_site_data
        build_site_data.main()


if __name__ == "__main__":
    main()
