"""Data tests. Run from the repo root:

    python -m unittest discover -s tests -v

No third-party packages. The PDF re-parse test needs `pdftotext` on PATH and
is skipped without it (it is not installed in CI; see README).
"""

import copy
import json
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_pages  # noqa: E402
import build_site_data  # noqa: E402
import fetch_media  # noqa: E402
import fetch_popularity  # noqa: E402
import finalize_site  # noqa: E402
import parse_pdf  # noqa: E402

SPOT = json.loads((ROOT / "tests" / "spot_checks.json").read_text(encoding="utf-8"))


def load(name):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def find(products, words, ml):
    return [p for p in products
            if p["volume_ml"] == ml and all(w in p["brand"] for w in words)]


class SpotCheckPrices(unittest.TestCase):
    """The hand-checked prices from step 1, against the published data."""

    def setUp(self):
        self.products = load("products.json")
        self.version = load("products.meta.json")["version"]

    def test_current_version_has_spot_checks(self):
        self.assertIn(self.version, SPOT,
                      f"No hand-checked prices for list {self.version}. Read 4 prices off the "
                      f"new PDF and add them to tests/spot_checks.json.")

    def test_spot_check_prices(self):
        for c in SPOT.get(self.version, []):
            with self.subTest(item=" ".join(c["words"]), ml=c["ml"]):
                hits = find(self.products, c["words"], c["ml"])
                self.assertEqual(len(hits), 1, f"expected exactly one match, got {[h['brand'] for h in hits]}")
                self.assertEqual(hits[0]["shop_price"], c["price"])

    def test_spot_check_prices_reach_the_site(self):
        site = load("site.json")
        for c in SPOT.get(self.version, []):
            with self.subTest(item=" ".join(c["words"]), ml=c["ml"]):
                rows = [b for b in site["brands"] if all(w in b[1] for w in c["words"])]
                self.assertEqual(len(rows), 1)
                prices = dict((ml, price) for ml, price in rows[0][4])
                self.assertEqual(prices.get(c["ml"]), c["price"])


class DataInvariants(unittest.TestCase):
    def setUp(self):
        self.products = load("products.json")

    def test_sl_no_has_no_gaps(self):
        sls = sorted(p["sl_no"] for p in self.products)
        self.assertEqual(sls, list(range(1, len(sls) + 1)))

    def test_codes_unique_and_prices_positive(self):
        self.assertEqual(len({p["id"] for p in self.products}), len(self.products))
        self.assertTrue(all(p["shop_price"] > 0 for p in self.products))

    def test_categories_known(self):
        known = {c for c, _ in parse_pdf.CATEGORY_RULES} | {"other"}
        self.assertLessEqual({p["category"] for p in self.products}, known)

    def test_site_json_is_up_to_date(self):
        """site.json must be rebuilt after products.json changes."""
        media = load("media.json") if (ROOT / "data" / "media.json").exists() else None
        expected = build_site_data.build(self.products, load("products.meta.json"), media)
        self.assertEqual(load("site.json"), expected,
                         "data/site.json is stale: run python scripts/build_site_data.py")

    def test_history_has_current_version(self):
        meta = load("products.meta.json")
        hist = ROOT / "data" / "history" / f"{meta['version']}.json"
        self.assertTrue(hist.exists(), f"missing {hist}")
        self.assertEqual(json.loads(hist.read_text(encoding="utf-8"))["products"], self.products)


class Validation(unittest.TestCase):
    """The checks parse_pdf runs before writing must actually catch problems."""

    def setUp(self):
        self.products = load("products.json")

    def test_clean_data_passes(self):
        self.assertEqual(parse_pdf.validate([], self.products), [])

    def test_missing_row_is_caught(self):
        broken = [p for p in self.products if p["sl_no"] != 100]
        self.assertTrue(any("missing Sl.No" in m for m in parse_pdf.validate([], broken)))

    def test_zero_price_is_caught(self):
        broken = copy.deepcopy(self.products)
        broken[5]["shop_price"] = 0
        self.assertTrue(any("zero shop price" in m for m in parse_pdf.validate([], broken)))


class Diff(unittest.TestCase):
    def test_diff_reports_new_removed_changed_renamed(self):
        old = load("products.json")[:50]
        new = copy.deepcopy(old)
        removed = new.pop(0)
        new[0]["shop_price"] += 20
        new[1]["brand"] = "RENAMED " + new[1]["brand"]
        added = dict(new[2], id="ZZZZZZZZZ")
        new.append(added)
        a, r, c, n = parse_pdf.diff(old, new)
        self.assertEqual([p["id"] for p in a], ["ZZZZZZZZZ"])
        self.assertEqual([p["id"] for p in r], [removed["id"]])
        self.assertEqual([(x["id"], y["shop_price"] - x["shop_price"]) for x, y in c], [(new[0]["id"], 20)])
        self.assertEqual([y["id"] for x, y in n], [new[1]["id"]])

    def test_same_list_has_no_diff(self):
        p = load("products.json")
        self.assertEqual(parse_pdf.diff(p, p), ([], [], [], []))


@unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
class ParsePdf(unittest.TestCase):
    """Re-parse the source PDF from scratch and check it against the data."""

    @classmethod
    def setUpClass(cls):
        cls.meta, cls.rows, cls.products, cls.problems = \
            parse_pdf.parse_pdf_file(ROOT / "source" / "pricelist.pdf")

    def test_no_validation_problems(self):
        self.assertEqual(self.problems, [])

    def test_matches_committed_data(self):
        self.assertEqual(self.products, load("products.json"))

    def test_header_dates(self):
        self.assertEqual(self.meta["version"], load("products.meta.json")["version"])

    def test_spot_checks_from_pdf(self):
        for c in SPOT[self.meta["version"]]:
            with self.subTest(item=" ".join(c["words"]), ml=c["ml"]):
                hits = find(self.products, c["words"], c["ml"])
                self.assertEqual([h["shop_price"] for h in hits], [c["price"]])


class BrandPages(unittest.TestCase):
    """The generated brand pages, built in memory."""

    @classmethod
    def setUpClass(cls):
        cls.products = load("products.json")
        cls.meta = load("products.meta.json")
        cls.cfg = json.loads((ROOT / "site.config.json").read_text(encoding="utf-8"))
        cls.media = load("media.json") if (ROOT / "data" / "media.json").exists() else {}
        cls.brands = {b["id"]: b for b in build_pages.brands_from(cls.products)}
        cls.hist = build_pages.history_index()

    def render(self, b):
        return build_pages.brand_page(b, self.meta, self.cfg, *self.hist, self.media,
                                      build_pages.footer(self.meta))

    def test_every_brand_gets_a_page_id(self):
        self.assertEqual(len(self.brands), len({p["brand"] for p in self.products}))

    def test_spot_check_prices_on_brand_pages(self):
        for c in SPOT.get(self.meta["version"], []):
            with self.subTest(item=" ".join(c["words"])):
                b = next(b for b in self.brands.values() if all(w in b["name"] for w in c["words"]))
                page = self.render(b)
                self.assertIn(f'<span class="ml">{c["ml"]} ml</span>'
                              f'<span class="price-tag">{build_pages.money(c["price"])}</span>', page)

    def test_photos_are_free_and_credited(self):
        for bid, p in self.media.get("photos", {}).items():
            with self.subTest(id=bid):
                self.assertIn(bid, self.brands, "photo for a brand id not in the current list")
                self.assertRegex(p["license"], fetch_media.FREE)
                for k in ("artist", "license_url", "source_url", "alt"):
                    self.assertTrue(p[k], k)
                self.assertTrue((ROOT / p["path"]).exists(), p["path"])
                page = self.render(self.brands[bid])
                self.assertIn(p["source_url"].replace("&", "&amp;"), page)

    def test_descriptions_never_state_alcohol_strength(self):
        for d in self.media.get("descriptions", []):
            with self.subTest(label=d["label"]):
                self.assertIsNone(fetch_media.STRENGTH.search(d["extract"]), d["extract"])

    def test_history_table_with_two_lists(self):
        """Synthetic data, in memory only: one older list with a lower price."""
        b = next(iter(self.brands.values()))
        p = b["sizes"][0]
        old = {"version": "2025-01-27_2025-09-01", "effective": "2025-01-27", "printed": "2025-09-01"}
        new = {"version": self.meta["version"], "effective": self.meta["effective"], "printed": self.meta["printed"]}
        by_code = {p["id"]: [(old, p["shop_price"] - 10), (new, p["shop_price"])]}
        html_out = build_pages.history_section(b, [old, new], by_code, {})
        self.assertIn("27 January 2025", html_out)
        self.assertIn(build_pages.money(p["shop_price"] - 10), html_out)
        self.assertIn(build_pages.money(p["shop_price"]), html_out)

    def test_indian_number_format(self):
        self.assertEqual(build_pages.inr(15300), "15,300")
        self.assertEqual(build_pages.inr(125000), "1,25,000")
        self.assertEqual(build_pages.inr(980), "980")


class Popularity(unittest.TestCase):
    def test_tally_counts_brand_pages_and_compare_events(self):
        rows = [
            {"path": "/beverage_lister/p/12702731X.html", "count": 7},
            {"path": "/beverage_lister/p/12702731X.html", "count": 3},   # second path variant
            {"path": "compare/12702731X", "count": 2, "event": True},
            {"path": "/beverage_lister/", "count": 99},                  # home page: not a brand
            {"path": "/beverage_lister/p/ZZZZZZZZZ.html", "count": 5},   # not in the list
            {"path": "compare/../etc", "count": 1, "event": True},
        ]
        self.assertEqual(fetch_popularity.tally(rows, {"12702731X"}),
                         {"12702731X": {"views": 10, "compares": 2}})

    def test_rank_orders_by_week_then_month_and_drops_noise(self):
        c = lambda v: {"views": v, "compares": 0}
        week = {"A": c(5), "B": c(5), "C": c(1)}
        month = {"A": c(6), "B": c(20), "C": c(9), "D": c(2)}   # D below the noise floor
        self.assertEqual(fetch_popularity.rank(week, month), ["B", "A", "C"])

    def test_no_token_writes_an_empty_ranking(self):
        import os, tempfile
        out = Path(tempfile.mkdtemp()) / "p.json"
        old = os.environ.pop("GOATCOUNTER_TOKEN", None)
        argv = sys.argv
        try:
            sys.argv = ["x", str(out)]
            self.assertEqual(fetch_popularity.main(), 0)
        finally:
            sys.argv = argv
            if old is not None:
                os.environ["GOATCOUNTER_TOKEN"] = old
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["ranked"], [])


class FinalizeSite(unittest.TestCase):
    def test_stamps_assets_and_renames_cache(self):
        import tempfile
        site = Path(tempfile.mkdtemp())
        (site / "assets").mkdir()
        for a in finalize_site.ASSETS:
            (site / a).write_text("x", encoding="utf-8")
        (site / "index.html").write_text('<link href="assets/style.css"><script src="assets/app.js"></script></body>',
                                         encoding="utf-8")
        (site / "sw.js").write_text("var CACHE = 'prices-v3';", encoding="utf-8")
        argv = sys.argv
        try:
            sys.argv = ["x", str(site)]
            finalize_site.main()
        finally:
            sys.argv = argv
        page = (site / "index.html").read_text(encoding="utf-8")
        self.assertRegex(page, r'assets/style\.css\?v=[0-9a-f]{10}"')
        self.assertRegex(page, r'assets/app\.js\?v=[0-9a-f]{10}"')
        self.assertNotIn("prices-v3", (site / "sw.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
