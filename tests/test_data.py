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

import build_site_data  # noqa: E402
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
        expected = build_site_data.build(self.products, load("products.meta.json"))
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


if __name__ == "__main__":
    unittest.main()
