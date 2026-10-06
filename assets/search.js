/* Typo-tolerant, case- and spacing-insensitive brand search.
 *
 * Names and the query are lowercased and stripped of everything but a-z0-9,
 * so "royalstag", "Royal Stag" and "ROYAL-STAG" are the same string. The
 * query is then matched as an approximate substring of the name (Sellers'
 * edit-distance variant: the match may start and end anywhere in the name).
 *
 * Allowed edits grow with length, because one wrong letter in "gin" is a
 * different word but one wrong letter in "smirnof" is a typo. Two edits
 * start at 10 letters: at 8, "teachers" reached "SUNNY BEACHES" and showed
 * a beer for a whisky that is not in the list.
 *
 * search() keeps only the best tier and reports whether it is an exact
 * phrase match, so the page can say when it is showing close spellings and
 * never presents a typo match as the thing searched for.
 *
 * Plain script, no dependencies. Exposes window.PriceSearch, and
 * module.exports for testing in Node.
 */
(function (root) {
  'use strict';

  function norm(s) {
    return s.toLowerCase().replace(/[^a-z0-9]/g, '');
  }

  function maxEdits(len) {
    if (len <= 3) return 0;
    if (len <= 9) return 1;
    return 2;
  }

  var rowA = new Int16Array(128);
  var rowB = new Int16Array(128);

  // Fewest edits needed to make `p` appear somewhere inside `t`.
  // Returns k + 1 as soon as it is clear no match within k exists.
  function approxSubstring(p, t, k) {
    if (t.indexOf(p) !== -1) return 0;
    var m = p.length;
    if (k === 0 || m > 120) return k + 1;
    var prev = rowA, cur = rowB, i, j;
    for (i = 0; i <= m; i++) prev[i] = i;
    var best = m;
    for (j = 0; j < t.length; j++) {
      var c = t.charCodeAt(j);
      cur[0] = 0;
      for (i = 1; i <= m; i++) {
        var sub = prev[i - 1] + (p.charCodeAt(i - 1) === c ? 0 : 1);
        var del = prev[i] + 1;
        var ins = cur[i - 1] + 1;
        cur[i] = sub < del ? (sub < ins ? sub : ins) : (del < ins ? del : ins);
      }
      if (cur[m] < best) best = cur[m];
      if (best === 0) break;
      var tmp = prev; prev = cur; cur = tmp;
    }
    return best <= k ? best : k + 1;
  }

  // "750", "750ml", "1l", "1 litre" (already split on spaces) -> 750, 1000.
  var SIZE_RE = /^(\d+(?:\.\d+)?)(ml|l|ltr|litre|liter|lt)?$/;
  function sizeOf(token, knownSizes) {
    var m = SIZE_RE.exec(token);
    if (!m) return null;
    var v = parseFloat(m[1]);
    if (m[2] && m[2] !== 'ml') v *= 1000;
    v = Math.round(v);
    return knownSizes.indexOf(v) !== -1 ? v : null;
  }

  /* Split a raw query into text tokens and at most one size.
   * "royal stag 750" -> { text: ['royal', 'stag'], size: 750 }
   * "1 litre" is joined first so the unit is not treated as a word. */
  function parseQuery(raw, knownSizes) {
    var words = raw.toLowerCase()
      .replace(/(\d)\s+(ml|l|ltr|litre|liter|lt)\b/g, '$1$2')
      .split(/\s+/).filter(Boolean);
    var text = [], size = null;
    for (var i = 0; i < words.length; i++) {
      var s = sizeOf(words[i], knownSizes);
      if (s !== null && size === null) size = s;
      else {
        var n = norm(words[i]);
        if (n) text.push(n);
      }
    }
    return { text: text, size: size };
  }

  // Fewest edits between `p` and the best-matching START of `t`.
  function approxPrefix(p, t, k) {
    if (t.lastIndexOf(p, 0) === 0) return 0;
    var m = p.length;
    if (k === 0 || m > 120) return k + 1;
    var prev = rowA, cur = rowB, i, j;
    for (i = 0; i <= m; i++) prev[i] = i;
    var best = m;
    for (j = 0; j < t.length; j++) {
      var c = t.charCodeAt(j), rowMin = j + 1;
      cur[0] = j + 1;
      for (i = 1; i <= m; i++) {
        var sub = prev[i - 1] + (p.charCodeAt(i - 1) === c ? 0 : 1);
        var del = prev[i] + 1;
        var ins = cur[i - 1] + 1;
        cur[i] = sub < del ? (sub < ins ? sub : ins) : (del < ins ? del : ins);
        if (cur[i] < rowMin) rowMin = cur[i];
      }
      if (cur[m] < best) best = cur[m];
      if (rowMin > k) break;
      var tmp = prev; prev = cur; cur = tmp;
    }
    return best <= k ? best : k + 1;
  }

  // Ignored when words are matched one by one, so "black and white" does
  // not match the "and" inside "BRANDY".
  var STOP = { and: 1, the: 1, of: 1, n: 1 };

  /* Match one prepared item against parsed text tokens.
   * Returns null, or { edits, exact, rank } where lower rank is better.
   *
   * 1. Whole query, spacing ignored, anywhere in the name. This is what
   *    makes "royalstag" find "ROYAL STAG". `exact` means 0 edits here.
   * 2. Otherwise each word separately, in any order ("stag royal"), each
   *    one starting at a word boundary. Never `exact`: the words were found
   *    but not as the phrase typed, so the page labels these as close. */
  function score(item, tokens) {
    if (!tokens.length) return { edits: 0, exact: true, rank: 0 };
    var whole = tokens.join('');
    var k = maxEdits(whole.length);
    var d = approxSubstring(whole, item.n, k);
    if (d <= k) return { edits: d, exact: d === 0, rank: d * 10 + bonus(item, tokens[0], d) };

    var words = tokens.filter(function (t) { return !STOP[t]; });
    if (words.length < 2) return null;
    var total = 0;
    for (var i = 0; i < words.length; i++) {
      var w = words[i], tk = maxEdits(w.length), best = tk + 1;
      if (/^\d+$/.test(w)) {
        best = item.n.indexOf(w) !== -1 ? 0 : 1;   // "no 1": digits anywhere, exactly
        tk = 0;
      } else {
        for (var s = 0; s < item.s.length && best > 0; s++) {
          var e = approxPrefix(w, item.s[s], tk);
          if (e < best) best = e;
        }
      }
      if (best > tk) return null;
      total += best;
    }
    return { edits: total, exact: false, rank: 5 + total * 10 + bonus(item, words[0], total) };
  }

  // Tie-breakers inside one edit count: the first word typed as a whole
  // word ("gin" in "DRY GIN") beats it as a word start ("GINGER"), which
  // beats it mid-word; then shorter names (closest to what was typed).
  function bonus(item, first, edits) {
    var b = 2;
    if (edits === 0) {
      if ((item.w + ' ').indexOf(' ' + first + ' ') !== -1) b = 0;
      else if (item.w.indexOf(' ' + first) !== -1) b = 1;
    }
    return b + Math.min(item.n.length, 99) / 100;
  }

  /* Run a query over prepared items. Keeps only the best tier: exact
   * phrase matches if there are any, otherwise the fewest-edit matches.
   * Returns { hits: [{ item, rank }], exact }. */
  function search(items, tokens) {
    var hits = [], anyExact = false, minEdits = Infinity, i, r;
    for (i = 0; i < items.length; i++) {
      r = score(items[i], tokens);
      if (!r) continue;
      hits.push({ item: items[i], r: r });
      if (r.exact) anyExact = true;
      if (r.edits < minEdits) minEdits = r.edits;
    }
    var kept = [];
    for (i = 0; i < hits.length; i++) {
      r = hits[i].r;
      if (anyExact ? r.exact : r.edits === minEdits) kept.push({ item: hits[i].item, rank: r.rank });
    }
    return { hits: kept, exact: anyExact || !tokens.length };
  }

  // Precompute what scoring needs: normalised name, a spaced word string,
  // and the normalised name from each word start onwards.
  function prepare(name) {
    var parts = name.toLowerCase().split(/\s+/).map(norm).filter(Boolean);
    var suffixes = [];
    for (var i = 0; i < parts.length; i++) suffixes.push(parts.slice(i).join(''));
    return { n: norm(name), w: ' ' + parts.join(' '), s: suffixes };
  }

  var api = { norm: norm, parseQuery: parseQuery, score: score, search: search,
              prepare: prepare, approxSubstring: approxSubstring,
              approxPrefix: approxPrefix, maxEdits: maxEdits };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PriceSearch = api;
})(this);
