# Design plan: Kerala liquor price lookup

> **Current look (Oct 2026): elegant and simple, light mode only.** Warm
> white page, white cards, thin hairlines, soft shadows and one quiet green
> accent. Fraunces (serif) for headings, the system font for text, Barlow
> Semi Condensed for prices, which stay the largest thing on screen. Drink
> types show only as a small coloured dot; "Best value" is a small green
> tag. A short Malayalam line (എന്താ വില?) sits above the home heading.
> Contrast: ink 16:1+, muted 5.6:1+, accent 8.4:1+. Between the first
> version and this one there was a louder "sticker" theme, since replaced.
> The palette and type sections below describe the first version; the
> rules on prices, layout, behaviour and accessibility still hold.

## Who and where
Someone in a Bevco queue on a cheap Android phone, one hand, patchy data,
bright light or a dim shop. They want one number, fast: what does this bottle
cost. Everything else is secondary.

## Palette
Taken from the printed price list and Kerala itself, not from a SaaS kit.

| Token | Light | Dark | Use |
|---|---|---|---|
| paper | `#F6F1E7` warm off-white | `#14120F` | page |
| card | `#FFFDF8` | `#1E1B17` | result card |
| ink | `#1C1B19` | `#F3EEE4` | prices, names |
| muted | `#5E574C` | `#B5AC9C` | labels, per-litre |
| laterite | `#8A3B1E` laterite red | `#E8956F` | accents, selected chips, links |
| leaf | `#1F4D3A` deep paddy green | `#86C3A3` | focus ring, header band |
| rule | `#D9CFBD` | `#3A342C` | hairlines |

Every text colour on every background, in both themes, is at least 6.3:1
(computed, WCAG formula), so all of it passes AA for small text. The lowest
is muted on paper in light mode; ink on paper is 15.3:1. Selected state is never colour alone: selected
chips also get a filled background and a check mark.

## Type
- Prices: **Barlow Semi Condensed 700**, tabular figures. Condensed so a
  four-digit price can be big (32px on a 360px phone) and still fit three
  sizes in a row. It reads like a printed tariff, not an app.
- Everything else: the phone's own system font. No download, no delay.
- One web font family, two weights, `font-display: swap`, so a slow
  connection shows system text at once and never blocks prices.
- Brand names stay in the list's own capitals: they match the PDF and the
  shop's printed board, and title-casing would mangle names like "VSOP",
  "XXX" or "MK-82 HD".

## Layout (mobile first, 360px baseline)
1. Thin green header band: site name and "Prices from 11 May 2026".
2. Sticky search box, full width, 48px tall, with a clear button.
3. "Filters" row: a single toggle that opens a panel with category chips,
   size chips, a min/max price pair and a supplier select, plus the sort
   select beside it. A count shows how many filters are on.
4. Result summary line ("42 brands, 118 bottles"), announced politely to
   screen readers.
5. Cards, one per brand: name, then a grid of sizes. Each size cell is
   `750 ml` (small) / **₹1,420** (largest thing on screen) / `₹1,893 per
   litre` (small). Supplier and category in a muted line at the bottom.
6. 30 cards at a time with a "Show more" button, so a cheap phone never
   renders 1,300 cards.
7. Footer: source, effective date, print date, PDF link, unofficial note.

On wider screens the cards flow into two or three columns; nothing else
changes.

## Behaviour
- Search is hand-written, not Fuse.js: names and query are lowercased and
  stripped of spaces and punctuation, then matched as an approximate
  substring (edit distance 0 for 1 to 3 letters, 1 for 4 to 9, 2 for 10
  and up). So "royalstag", "Royal Stag" and "royl stag" all land. Words in
  any order also match, each from a word start. A bare number like "750" or
  "1 litre" in the query acts as a size. No dependency, and the spacing rule
  is the default rather than a workaround.
- Only the best tier of matches is shown. If none is an exact phrase match,
  a note says these are the closest names, so a typo match is never passed
  off as the bottle asked for. (Two edits at 8 letters let "teachers" show
  "SUNNY BEACHES" beer; that is why the threshold is 10.)
- Offline: a network-first service worker keeps the last list seen, for a
  queue with no signal. A working connection always gets the fresh list.
- Filters narrow sizes within a card. If a card has sizes hidden by a
  filter, it says so.
- All state lives in the URL (`?q=&cat=&size=&min=&max=&sup=&sort=`),
  updated with `replaceState` so typing does not flood the back button.
- Empty state names the search, says it is not in this price list and to
  check with the shop. It never shows a "closest guess" price. If filters
  are on, it offers to clear them.
- Motion: none needed. The only transition (panel open) is disabled under
  `prefers-reduced-motion`.
- Focus: 3px leaf-green outline with offset on every interactive element.

## Check against the brief
| Brief | Plan |
|---|---|
| Static, GitHub Pages | Plain HTML/CSS/JS, relative paths, `.nojekyll`. No build step needed to serve. |
| Mobile first, cheap phone | System font for text, one font for prices, ~1 compact JSON, 30 cards at a time. |
| Search as you type, typos, case, spacing | Normalised approximate substring matching, debounced 80ms. |
| Filters: category, size, price, supplier | Chips, chips, two number inputs, select. |
| Sort: low/high, per litre, A to Z | One select. |
| Group sizes per brand | One card per brand, sizes in a grid. |
| Price per litre | Under every price. |
| State in URL | All filters and the query. |
| Empty state, no guessing | Explicit "not in this price list" message. |
| Footer with source, dates, PDF, unofficial | Every page (the site is one page). |
| Not generic SaaS, no alcohol imagery | Paper, laterite and paddy green, tariff numerals, no bottles or glasses anywhere. |
| Prices largest | 32px condensed bold, largest type on the page. |
| Focus, reduced motion, contrast | Covered above. |
| No em dashes, plain copy | Checked with a grep before finishing. |
