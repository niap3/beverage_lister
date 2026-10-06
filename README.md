# Kerala liquor prices

A static site for looking up Bevco (KSBC) FL-1 shop prices in Kerala. Search
by brand, filter by type, size, price and supplier, compare up to three
brands side by side. No backend: GitHub Pages serves plain HTML, CSS, JS and
one JSON file.

The data comes from KSBC's price list PDF. This repo turns that PDF into
JSON, checks it, keeps every version, and deploys the site on push.

## Requirements

- Python 3.10 or newer (standard library only)
- `pdftotext` on your PATH. Tested with **xpdf's pdftotext 4.00**, which Git
  for Windows ships in `mingw64/bin`. Poppler's `pdftotext` has the same
  `-raw` mode but has **not** been checked against this PDF; if you use it,
  run `--check` first and compare the result.
- Node 18 or newer, only for the search tests
- Pillow (`pip install pillow`), only for `scripts/fetch_media.py`

## Updating the data when a new price list comes out

1. Download the new PDF from KSBC. Save it anywhere, for example `new.pdf`.

2. Dry run. This parses and validates everything and prints what changed,
   but writes nothing:

   ```bash
   python scripts/parse_pdf.py --check new.pdf
   ```

   Read the diff. It lists new items, removed items, price changes (with the
   largest moves at both ends) and products renamed under the same code. Add
   `--all` to print every line instead of the first 25 per section.

3. If the checks passed and the diff looks believable, run it for real:

   ```bash
   python scripts/parse_pdf.py new.pdf
   ```

   That one command:
   - writes `data/products.json` and `data/products.meta.json` (the list's
     effective date, printed date and title, read from the PDF header)
   - saves a copy to `data/history/<effective>_<printed>.json`
   - archives the PDF as `source/archive/<effective>_<printed>.pdf`
   - copies it to `source/pricelist.pdf`, which the site links to
   - rebuilds `data/site.json` and `data/meta.json`, which the site loads,
     and the brand pages, catalogue and sitemap (`scripts/build_pages.py`)

   If any check fails, nothing is written. Fix the cause, or use `--force`
   only after checking the reported rows against the PDF yourself.

4. **Check a few prices by hand.** Open the new PDF, pick four products
   across different sections (a whisky, a brandy, a beer, a wine is a good
   spread), and add them to `tests/spot_checks.json` under the new version
   key, which the parser printed. The tests fail until you do. That is on
   purpose: every published list gets human eyes on it.

5. Look at the uncategorised items:

   ```bash
   python scripts/parse_pdf.py --check --others
   ```

   Type comes from words in the brand name (`CATEGORY_RULES` in
   `scripts/parse_pdf.py`). Anything without a clear word becomes `other`.
   Change the rules there if a new list brings new patterns.

6. Run the tests (next section), then commit and push. The workflow deploys.

## Validation checks

`parse_pdf.py` runs these on every parse, and refuses to write if any fail:

| Check | Catches |
|---|---|
| Every text line is classified | Rows the parser did not understand being silently dropped |
| FL1 before tax + tax + cess = FL1 after tax, per row | Prices attached to the wrong row |
| Warehouse before tax + tax + cess x case = after tax | Column misreads |
| FL1 price vs warehouse price per bottle stays in 1.03 to 1.35 | A price shifted from a neighbouring row |
| Sl.No runs 1..N with no gaps or repeats | Missed or doubled rows |
| Product codes unique, no zero or missing prices | Broken rows |
| All page headers agree on the dates | A merged or mixed-up PDF |

To run them without writing anything:

```bash
python scripts/parse_pdf.py --check
```

The test suites:

```bash
python -m unittest discover -s tests -v
```

```bash
node --test tests/search.test.js
```

The Python tests cover the hand-checked spot prices (in the data, in the
site file, and from a fresh parse of the PDF), the data invariants above,
that `site.json` is not stale, that the history copy exists, and that the
diff and validation code really catch problems. The re-parse tests skip
when `pdftotext` is missing, which is the case in CI. The Node tests cover
search: spacing and case, typos, sizes in the query, and that brands not in
the list (Baileys, Chivas and others) return nothing rather than a guess.

## Price history

Brand pages show a price table across every list in `data/history/`. To add
an older KSBC list (they are published on bevco.in) without replacing the
current one:

```bash
python scripts/parse_pdf.py --history-only old-list.pdf
```

It runs the same checks, prints the diff against the current list, saves
`data/history/<effective>_<printed>.json`, archives the PDF and rebuilds the
pages. A normal run refuses to replace the current list with an older one.
Older lists may use a slightly different header; if the parser stops on
one, nothing is written.

Each version in `data/history/` is:

```json
{ "meta": { "effective": "2026-05-11", "printed": "2026-09-23", "version": "2026-05-11_2026-09-23", ... },
  "products": [ { "id": "12339021S", "brand": "...", "volume_ml": 750, "shop_price": 1420, ... } ] }
```

Product codes (`id`) are the join key across versions. Nothing reads the
history yet; it is there so a price-history view can be built later.

## Photos and descriptions

`data/media_sources.json` is the hand-curated list: which Wikimedia Commons
photo shows which list entry (`exact`), or only the brand (`family`), and
which Wikipedia article describes which brands. After editing it:

```bash
python scripts/fetch_media.py
```

```bash
python scripts/build_pages.py
```

`fetch_media.py` refuses non-free licences, records author, licence and
source for the credit line, shrinks each photo to a ~25 KB JPEG in
`assets/products/`, drops description sentences about alcohol strength, and
checks every id and match string against the current list. Commit
`data/media.json` and `assets/products/`. Look at a photo's label before
adding it: a photo of a different variant is worse than no photo.

## Trending (optional)

The "Trending this week" sort and the "#1 trending in Whisky" badges (top 3
per type) are off until GoatCounter is set up. GoatCounter counts page views without cookies and
without storing IP addresses. What it measures: visitors to each brand page
plus "Compare" taps on this site, ranked by the last 7 days with the last
30 breaking ties. It is interest, not sales, and the site labels it that
way. Only the order is published, never the counts.

1. Create a free account at goatcounter.com and pick a site code, e.g.
   `beverage-lister` (the site is then `beverage-lister.goatcounter.com`).
2. Tell the site the code, then commit and push:

   ```bash
   python scripts/configure_site.py --goatcounter beverage-lister
   ```

3. In GoatCounter, create an API token that can read statistics, and store
   it as a repository secret (gh prompts for the value; it is never shown):

   ```bash
   gh secret set GOATCOUNTER_TOKEN -R niap3/beverage_lister
   ```

On every deploy, and daily at 03:00 IST, CI runs
`scripts/fetch_popularity.py` into the published `data/popularity.json`.
The sort and badges appear once at least one brand has 3 or more look-ups in 30 days.
To turn counting off: `python scripts/configure_site.py --goatcounter ""`.

## Brand pages and catalogue

`scripts/build_pages.py` writes `p/<id>.html` for every brand, the
`catalogue.html` overview, one `catalogue/<type>.html` per type, and
`sitemap.xml`. They are generated, git-ignored, and rebuilt by CI on every
deploy, so there are no 1,300-file diffs in the repo.

## First-time setup for GitHub Pages

1. Put this folder in a GitHub repository and push to `main`.
2. In the repo: Settings > Pages > Build and deployment > Source: **GitHub
   Actions**.
3. Tell the site its address. Share previews, the sitemap and the
   report-an-error link all need it:

   ```bash
   python scripts/configure_site.py --site-url https://USER.github.io/REPO/ --repo-url https://github.com/USER/REPO
   ```

   Commit and push. Until this is done the workflow prints a warning.

`robots.txt` only counts at the root of a domain, so on a project site
(`USER.github.io/REPO/`) submit `sitemap.xml` in Google Search Console
instead.

## Local preview

```bash
python -m http.server 8000
```

Then open http://localhost:8000/. The offline service worker only registers
on `localhost` or HTTPS.

## Files

| Path | What it is |
|---|---|
| `index.html`, `about.html` | The two pages |
| `assets/app.js` | Filtering, sorting, URL state, compare tray |
| `assets/search.js` | Typo-tolerant search, no dependencies |
| `assets/meta.js` | Fills dates and counts from the data's metadata |
| `assets/style.css` | All styles; see `DESIGN.md` for the reasoning |
| `assets/fonts/` | Barlow Semi Condensed Bold, self-hosted (SIL OFL) |
| `sw.js` | Network-first offline fallback |
| `scripts/build_pages.py` | Brand pages, catalogue, sitemap (generated, not committed) |
| `scripts/fetch_media.py` | Licensed photos and Wikipedia text from `data/media_sources.json` |
| `assets/products/` | Small copies of the licensed photos |
| `scripts/parse_pdf.py` | PDF to `products.json`, checks, diff, history |
| `scripts/build_site_data.py` | `products.json` to the compact `site.json` |
| `scripts/configure_site.py` | Site and repo URLs, GoatCounter code, robots.txt |
| `scripts/fetch_popularity.py` | GoatCounter counts to the trending order in `data/popularity.json` (CI) |
| `scripts/finalize_site.py` | Cache-busts CSS/JS and adds the counter on the built site (CI) |
| `scripts/og-image.html` | Source for the share image `assets/og-image.png` |
| `data/products.json` | One row per bottle (the full data) |
| `data/history/` | Every parsed version |
| `source/pricelist.pdf` | The current list; `source/archive/` has every version |
| `tests/` | Spot checks, data tests, search tests |
| `.github/workflows/deploy.yml` | Tests, then deploys to Pages |

This is an unofficial lookup. It is not run by or connected to KSBC.
