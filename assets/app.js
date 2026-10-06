/* Kerala liquor prices: page logic.
 *
 * Loads data/site.json (one entry per brand, sizes grouped), filters and
 * sorts in memory, and keeps every bit of state in the URL so a result can
 * be shared, including the compare tray. Search itself lives in search.js.
 */
(function () {
  'use strict';

  var PAGE = 30;            // cards rendered per "Show more"
  var DEBOUNCE_MS = 80;
  var MAX_COMPARE = 3;

  var CAT_LABEL = {
    whisky: 'Whisky', brandy: 'Brandy', rum: 'Rum', vodka: 'Vodka', gin: 'Gin',
    beer: 'Beer', wine: 'Wine', liqueur: 'Liqueur', tequila: 'Tequila', other: 'Other'
  };
  var SORTS = { '': 1, 'price-asc': 1, 'price-desc': 1, litre: 1, az: 1, trending: 1 };
  var TRENDING_BADGE = 3;   // "#1 trending in Whisky" badge for the top N of each type

  var $ = function (id) { return document.getElementById(id); };
  var el = {
    q: $('q'), clear: $('clear'), form: $('search-form'), filters: $('filters'),
    count: $('filter-count'), countN: $('filter-count-n'),
    catChips: $('cat-chips'), sizeChips: $('size-chips'),
    min: $('min'), max: $('max'), sup: $('sup'), sort: $('sort'), reset: $('reset'),
    summary: $('summary'), notice: $('notice'), results: $('results'),
    empty: $('empty'), more: $('more'),
    tray: $('tray'), trayText: $('tray-text'), trayClear: $('tray-clear'), trayOpen: $('tray-open'),
    dialog: $('compare'), compareBody: $('compare-body'), compareClose: $('compare-close')
  };

  var data = null;          // { meta, suppliers, categories, brands }
  var brands = [];          // prepared brand objects
  var byId = {};            // brand id (lowest product code) -> brand
  var photos = {};          // brand id -> thumbnail path (licensed photos only)
  var trendPos = null;      // brand id -> position in the trending order (0 = top); null when not set up
  var catRank = {};         // brand id -> rank within its own type, for the badge
  var sizes = [];           // every bottle size in the list, ascending
  var state = blankState();
  var shown = PAGE;
  var expanded = {};        // brand index -> true when "show all sizes" was tapped
  var lastList = [];
  var trayNote = '';        // one-off message, e.g. "the tray is full"

  var rupees = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

  function blankState() {
    return { q: '', cat: '', size: '', min: '', max: '', sup: '', sort: '', cmp: [] };
  }

  // ---------------------------------------------------------------- URL

  function readUrl() {
    var p = new URLSearchParams(location.search);
    var s = blankState();
    s.q = (p.get('q') || '').slice(0, 100);
    s.cat = data.categories.indexOf(p.get('cat')) !== -1 ? p.get('cat') : '';
    s.size = sizes.indexOf(+p.get('size')) !== -1 ? String(+p.get('size')) : '';
    s.min = /^\d+$/.test(p.get('min') || '') ? p.get('min') : '';
    s.max = /^\d+$/.test(p.get('max') || '') ? p.get('max') : '';
    s.sup = data.suppliers.indexOf(p.get('sup')) !== -1 ? p.get('sup') : '';
    s.sort = SORTS[p.get('sort')] ? p.get('sort') : '';
    (p.get('cmp') || '').split(',').forEach(function (id) {
      if (byId[id] && s.cmp.indexOf(id) === -1 && s.cmp.length < MAX_COMPARE) s.cmp.push(id);
    });
    return s;
  }

  function writeUrl() {
    var p = new URLSearchParams();
    Object.keys(state).forEach(function (k) {
      var v = Array.isArray(state[k]) ? state[k].join(',') : state[k];
      if (v) p.set(k, v);
    });
    var qs = p.toString().replace(/%2C/g, ',');
    var url = location.pathname + (qs ? '?' + qs : '');
    if (url !== location.pathname + location.search) history.replaceState(null, '', url);
  }

  // ---------------------------------------------------------- controls

  function chip(name, value, label, checked) {
    var id = name + '-' + (value || 'all');
    return '<label class="chip" for="' + id + '"><input type="radio" id="' + id +
      '" name="' + name + '" value="' + value + '"' + (checked ? ' checked' : '') +
      '><span>' + label + '</span></label>';
  }

  // Welcome block: type links with counts, from the data.
  function buildIntro() {
    var counts = {};
    brands.forEach(function (b) { counts[b.cat] = (counts[b.cat] || 0) + 1; });
    $('type-links').innerHTML = data.categories.map(function (c) {
      return '<li><a href="?cat=' + c + '" data-cat="' + c + '">' + (CAT_LABEL[c] || c) +
        ' <span class="n">' + rupees.format(counts[c] || 0) + '</span></a></li>';
    }).join('');
  }

  function buildControls() {
    el.catChips.innerHTML = chip('cat', '', 'All', true) + data.categories.map(function (c) {
      return chip('cat', c, CAT_LABEL[c] || c, false);
    }).join('');
    el.sizeChips.innerHTML = chip('size', '', 'All', true) + sizes.map(function (s) {
      return chip('size', String(s), s + ' ml', false);
    }).join('');
    var frag = document.createDocumentFragment();
    data.suppliers.forEach(function (s) {
      var o = document.createElement('option');
      o.value = s; o.textContent = s;
      frag.appendChild(o);
    });
    el.sup.appendChild(frag);
  }

  function setRadio(name, value) {
    var r = document.querySelector('input[name="' + name + '"][value="' + value + '"]');
    if (r) r.checked = true;
  }

  // Push state into the form (on load and on back/forward).
  function syncControls() {
    el.q.value = state.q;
    setRadio('cat', state.cat);
    setRadio('size', state.size);
    el.min.value = state.min;
    el.max.value = state.max;
    el.sup.value = state.sup;
    el.sort.value = state.sort;
    syncCount();
  }

  function activeFilters() {
    return (state.cat ? 1 : 0) + (state.size ? 1 : 0) +
      (state.min || state.max ? 1 : 0) + (state.sup ? 1 : 0);
  }

  function syncCount() {
    var quick = document.querySelectorAll('#price-quick [data-max]');
    for (var i = 0; i < quick.length; i++) {
      quick[i].setAttribute('aria-pressed', !state.min && state.max === quick[i].getAttribute('data-max'));
    }
    var n = activeFilters();
    el.count.hidden = !n;
    el.countN.textContent = n;
    el.clear.hidden = !state.q;
  }

  // ----------------------------------------------------------- compute

  function compute() {
    var pq = PriceSearch.parseQuery(state.q, sizes);
    var hits = null, exact = true;
    if (pq.text.length) {
      var res = PriceSearch.search(brands, pq.text);
      hits = {};
      res.hits.forEach(function (h) { hits[h.item.i] = h.rank; });
      exact = res.exact;
    }

    var lo = state.min ? +state.min : 0;
    var hi = state.max ? +state.max : Infinity;
    if (lo > hi) { var t = lo; lo = hi; hi = t; }
    var wantSize = state.size ? +state.size : null;
    var nameMatches = hits ? Object.keys(hits).length : brands.length;

    var list = [];
    for (var i = 0; i < brands.length; i++) {
      var b = brands[i];
      if (hits && !(i in hits)) continue;
      if (state.cat && b.cat !== state.cat) continue;
      if (state.sup && b.sup !== state.sup) continue;
      var vis = b.sizes.filter(function (s) {
        return (wantSize === null || s.ml === wantSize) &&
          (pq.size === null || s.ml === pq.size) &&
          s.price >= lo && s.price <= hi;
      });
      if (!vis.length) continue;
      list.push({ b: b, vis: vis, rank: hits ? hits[i] : 0 });
    }

    var byName = function (a, b) { return a.b.name < b.b.name ? -1 : a.b.name > b.b.name ? 1 : 0; };
    var minOf = function (r, key) { return Math.min.apply(null, r.vis.map(function (s) { return s[key]; })); };
    var maxOf = function (r, key) { return Math.max.apply(null, r.vis.map(function (s) { return s[key]; })); };
    var cmp = {
      '': hits ? function (a, b) { return a.rank - b.rank || byName(a, b); } : byName,
      'price-asc': function (a, b) { return minOf(a, 'price') - minOf(b, 'price') || byName(a, b); },
      'price-desc': function (a, b) { return maxOf(b, 'price') - maxOf(a, 'price') || byName(a, b); },
      litre: function (a, b) { return minOf(a, 'ppl') - minOf(b, 'ppl') || byName(a, b); },
      trending: function (a, b) { return trendOf(a.b) - trendOf(b.b) || byName(a, b); },
      az: byName
    }[state.sort];
    list.sort(cmp);

    return { list: list, exact: exact, querySize: pq.size, nameMatches: nameMatches, hasText: !!pq.text.length };
  }

  // ------------------------------------------------------------ render

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function money(n) { return '₹' + rupees.format(n); }

  // Brands not in the ranking sort after every ranked one.
  function trendOf(b) {
    return trendPos && b.id in trendPos ? trendPos[b.id] : Infinity;
  }

  function cmpButton(b) {
    var on = state.cmp.indexOf(b.id) !== -1;
    var full = !on && state.cmp.length >= MAX_COMPARE;
    return '<button type="button" class="cmp-btn" data-cmp="' + esc(b.id) + '" aria-pressed="' + on + '"' +
      (full ? ' aria-disabled="true"' : '') + '><span class="plus" aria-hidden="true">+</span>Compare<span class="visually-hidden"> ' +
      esc(b.name) + '</span></button>';
  }

  function card(r) {
    var b = r.b;
    var all = expanded[b.i];
    var cells = (all ? b.sizes : r.vis).map(function (s) {
      return '<li><span class="ml">' + s.ml + ' ml</span>' +
        '<span class="price-tag">' + money(s.price) + '</span>' +
        '<span class="per-litre">' + money(s.ppl) + ' per litre</span></li>';
    }).join('');
    var hidden = b.sizes.length - r.vis.length;
    var toggle = '';
    if (hidden > 0) {
      toggle = '<button type="button" class="link-button hidden-sizes" data-expand="' + b.i +
        '" aria-expanded="' + (all ? 'true' : 'false') + '">' +
        (all ? 'Show only matching sizes'
             : 'Show all ' + b.sizes.length + ' sizes (' + hidden + ' hidden by filters)') +
        '</button>';
    }
    var thumb = photos[b.id] ? '<img class="thumb" src="' + esc(photos[b.id]) + '" alt="" width="44" height="56" loading="lazy">' : '';
    var badge = catRank[b.id] ? '<p class="badge">#' + catRank[b.id] + ' trending in ' +
      (CAT_LABEL[b.cat] || b.cat) + '</p>' : '';
    return '<article class="card" data-cat="' + esc(b.cat) + '"><h2' + (thumb ? ' class="has-thumb"' : '') + '>' + thumb +
      '<a class="card-link" href="p/' + esc(b.id) + '.html">' + esc(b.name) + '</a></h2>' + badge +
      '<ul class="sizes" aria-label="Sizes and prices">' + cells + '</ul>' + toggle +
      '<div class="card-foot"><p class="meta"><span class="cat">' + (CAT_LABEL[b.cat] || b.cat) +
      '</span> · ' + esc(b.sup) + '</p>' + cmpButton(b) + '</div></article>';
  }

  function plural(n, one, many) { return rupees.format(n) + ' ' + (n === 1 ? one : many); }

  function render() {
    var out = compute();
    var list = out.list;
    lastList = list;

    el.notice.hidden = true;
    el.empty.hidden = true;

    if (!list.length) {
      el.results.innerHTML = '';
      el.more.hidden = true;
      el.summary.textContent = 'No results';
      document.documentElement.classList.add('has-query');
      renderEmpty(out);
      return;
    }

    var bottles = list.reduce(function (n, r) { return n + r.vis.length; }, 0);
    var bare = !state.q.trim() && !activeFilters();
    document.documentElement.classList.toggle('has-query', !bare);
    el.summary.textContent = (bare ? 'All ' : '') + plural(list.length, 'brand', 'brands') + ', ' +
      plural(bottles, 'bottle size', 'bottle sizes') + (bare && !state.sort ? ', A to Z' : '') +
      (state.sort === 'litre' ? ', best value (lowest price per litre) first' : '') +
      (state.sort === 'trending' && trendPos ? ', trending this week first' : '');

    if (!out.exact) {
      el.notice.hidden = false;
      el.notice.textContent = 'No exact match for “' + state.q.trim() +
        '”. These are the closest names in the list, so check the name before you buy.';
    }

    el.results.innerHTML = list.slice(0, shown).map(card).join('');
    el.more.hidden = list.length <= shown;
    el.more.textContent = 'Show more (' + (list.length - shown) + ' left)';
  }

  function renderEmpty(out) {
    var q = esc(state.q.trim());
    var html;
    if (out.hasText && out.nameMatches === 0) {
      html = '<h2>“' + q + '” is not in this price list</h2>' +
        '<p>It is not among the brands in the Bevco price list from ' +
        esc(window.formatMetaDate(data.meta.effective)) + ', so this site has no price for it. ' +
        'Ask at the shop whether they have it and what it costs.</p>' +
        '<p>If you think it is listed, try fewer letters, like the first word of the name.</p>';
    } else if (out.hasText) {
      html = '<h2>Nothing matches “' + q + '” with these filters</h2>' +
        '<p>The name is in the list, but not with the type, size, price or supplier you picked.</p>' +
        '<p><button type="button" class="link-button" data-reset>Clear filters</button></p>';
    } else if (out.querySize !== null) {
      html = '<h2>No ' + out.querySize + ' ml bottles match these filters</h2>' +
        '<p><button type="button" class="link-button" data-reset>Clear filters</button></p>';
    } else {
      html = '<h2>No bottles match these filters</h2>' +
        '<p>Try a wider price range or a different size.</p>' +
        '<p><button type="button" class="link-button" data-reset>Clear filters</button></p>';
    }
    el.empty.innerHTML = html;
    el.empty.hidden = false;
  }

  // ----------------------------------------------------------- compare

  function toggleCompare(id) {
    var at = state.cmp.indexOf(id);
    trayNote = '';
    if (at !== -1) {
      state.cmp.splice(at, 1);
    } else if (state.cmp.length >= MAX_COMPARE) {
      trayNote = 'You can compare ' + MAX_COMPARE + ' at a time. Remove one first.';
      renderTray();
      return;
    } else {
      state.cmp.push(id);
      // Interest signal for "Most looked up"; only when the counter is on.
      if (window.goatcounter && window.goatcounter.count) {
        window.goatcounter.count({ path: 'compare/' + id, title: byId[id].name, event: true });
      }
    }
    writeUrl();
    syncCompareButtons();
    renderTray();
    if (el.dialog.open) renderCompare();
  }

  // Update the buttons already on screen instead of re-rendering the list,
  // so picking an item never resets paging or focus.
  function syncCompareButtons() {
    var full = state.cmp.length >= MAX_COMPARE;
    var btns = el.results.querySelectorAll('[data-cmp]');
    for (var i = 0; i < btns.length; i++) {
      var on = state.cmp.indexOf(btns[i].getAttribute('data-cmp')) !== -1;
      btns[i].setAttribute('aria-pressed', on);
      if (full && !on) btns[i].setAttribute('aria-disabled', 'true');
      else btns[i].removeAttribute('aria-disabled');
    }
  }

  function renderTray() {
    var n = state.cmp.length;
    el.tray.hidden = !n;
    document.body.classList.toggle('has-tray', n > 0);
    if (!n) return;
    var text = n + ' of ' + MAX_COMPARE + ' picked. ';
    if (trayNote) text = trayNote;
    else if (n === 1) text += 'Pick one more to compare.';
    else if (n === MAX_COMPARE) text += 'That is the most.';
    el.trayText.textContent = text;
    el.trayOpen.disabled = n < 2;
    el.trayOpen.textContent = n < 2 ? 'Compare' : 'Compare ' + n;
  }

  function renderCompare() {
    var cols = state.cmp.map(function (id) { return byId[id]; });
    if (!cols.length) { el.dialog.close(); return; }

    var mls = [];
    cols.forEach(function (b) {
      b.sizes.forEach(function (s) { if (mls.indexOf(s.ml) === -1) mls.push(s.ml); });
    });
    mls.sort(function (a, b) { return a - b; });

    var head = '<tr><th scope="col" class="size-col"><span class="visually-hidden">Size</span></th>' +
      cols.map(function (b) {
        return '<th scope="col"><a class="card-link" href="p/' + esc(b.id) + '.html">' + esc(b.name) + '</a><span class="cmp-cat">' + (CAT_LABEL[b.cat] || b.cat) +
          '</span><button type="button" class="link-button" data-uncmp="' + esc(b.id) +
          '">Remove<span class="visually-hidden"> ' + esc(b.name) + '</span></button></th>';
      }).join('') + '</tr>';

    var lowestTag = '<span class="lowest">Lowest</span>';
    var rows = mls.map(function (ml) {
      var cells = cols.map(function (b) {
        return b.sizes.filter(function (s) { return s.ml === ml; })[0] || null;
      });
      var present = cells.filter(Boolean);
      var low = present.length > 1 ? Math.min.apply(null, present.map(function (s) { return s.price; })) : null;
      return '<tr><th scope="row">' + ml + ' ml</th>' + cells.map(function (s) {
        if (!s) return '<td class="none">Not in list</td>';
        return '<td><span class="cmp-price">' + money(s.price) + '</span>' +
          '<span class="per-litre">' + money(s.ppl) + ' per litre</span>' +
          (s.price === low ? lowestTag : '') + '</td>';
      }).join('') + '</tr>';
    }).join('');

    // Across sizes, the fairest comparison is each brand's best price per litre.
    var bests = cols.map(function (b) {
      return b.sizes.reduce(function (m, s) { return !m || s.ppl < m.ppl ? s : m; }, null);
    });
    var lowPpl = cols.length > 1 ? Math.min.apply(null, bests.map(function (s) { return s.ppl; })) : null;
    var overall = '<tr class="overall"><th scope="row">Best per litre</th>' + bests.map(function (s) {
      return '<td><span class="cmp-price">' + money(s.ppl) + '</span><span class="per-litre">in the ' +
        s.ml + ' ml</span>' + (s.ppl === lowPpl ? lowestTag : '') + '</td>';
    }).join('') + '</tr>';

    el.compareBody.innerHTML =
      '<p>Shop price for one bottle. “Lowest” marks the cheapest in each row.</p>' +
      '<div class="table-scroll"><table class="cmp-table"><caption class="visually-hidden">' +
      'Prices by bottle size</caption><thead>' + head + '</thead><tbody>' + rows + overall +
      '</tbody></table></div>';
  }

  function openCompare() {
    if (state.cmp.length < 2) return;
    renderCompare();
    if (typeof el.dialog.showModal === 'function') el.dialog.showModal();
    else el.dialog.setAttribute('open', '');
    el.compareClose.focus();
  }

  function closeCompare() {
    if (typeof el.dialog.close === 'function') el.dialog.close();
    else el.dialog.removeAttribute('open');
  }

  // ----------------------------------------------------------- updates

  var timer = null;
  function update(immediate) {
    clearTimeout(timer);
    var run = function () {
      shown = PAGE;
      expanded = {};
      writeUrl();
      syncCount();
      render();
    };
    if (immediate) run(); else timer = setTimeout(run, DEBOUNCE_MS);
  }

  function clearFilters() {
    state.cat = state.size = state.min = state.max = state.sup = '';
    syncControls();
    update(true);
  }

  function bind() {
    el.q.addEventListener('input', function () { state.q = el.q.value; el.clear.hidden = !state.q; update(); });
    el.form.addEventListener('submit', function (e) { e.preventDefault(); el.q.blur(); update(true); });
    el.clear.addEventListener('click', function () {
      state.q = ''; el.q.value = ''; el.q.focus(); update(true);
    });
    document.addEventListener('change', function (e) {
      var t = e.target;
      if (t.name === 'cat') state.cat = t.value;
      else if (t.name === 'size') state.size = t.value;
      else if (t === el.sup) state.sup = t.value;
      else if (t === el.sort) state.sort = t.value;
      else return;
      update(true);
    });
    [el.min, el.max].forEach(function (inp) {
      inp.addEventListener('input', function () {
        var v = inp.value.replace(/\D/g, '');
        state[inp.id] = v ? String(+v) : '';
        update();
      });
    });
    el.reset.addEventListener('click', clearFilters);
    $('filters-done').addEventListener('click', function () {
      el.filters.open = false;
      el.summary.focus();
    });
    $('price-quick').addEventListener('click', function (e) {
      var b = e.target.closest('[data-max]');
      if (!b) return;
      state.min = '';
      state.max = state.max === b.getAttribute('data-max') ? '' : b.getAttribute('data-max');
      syncControls();
      update(true);
    });
    el.empty.addEventListener('click', function (e) {
      if (e.target.closest('[data-reset]')) clearFilters();
    });
    el.results.addEventListener('click', function (e) {
      var cmpBtn = e.target.closest('[data-cmp]');
      if (cmpBtn) { toggleCompare(cmpBtn.getAttribute('data-cmp')); return; }
      var btn = e.target.closest('[data-expand]');
      if (!btn) return;
      var i = +btn.getAttribute('data-expand');
      expanded[i] = !expanded[i];
      var r = lastList.filter(function (x) { return x.b.i === i; })[0];
      btn.closest('.card').outerHTML = card(r);
      var again = el.results.querySelector('[data-expand="' + i + '"]');
      if (again) again.focus();
    });
    el.more.addEventListener('click', function () {
      var first = shown;
      shown += PAGE;
      render();
      // Move focus to the first new card so keyboard users keep their place.
      var cards = el.results.querySelectorAll('.card h2');
      if (cards[first]) { cards[first].setAttribute('tabindex', '-1'); cards[first].focus(); }
    });

    // Welcome-block links change the view in place instead of reloading.
    $('intro').addEventListener('click', function (e) {
      var a = e.target.closest('a');
      if (!a) return;
      e.preventDefault();
      // Apply every parameter in the link (q, cat, size, max, sort...).
      var p = new URLSearchParams(a.getAttribute('href').split('?')[1] || '');
      ['q', 'cat', 'size', 'min', 'max', 'sup', 'sort'].forEach(function (k) {
        if (p.has(k)) state[k] = p.get(k);
      });
      syncControls();
      update(true);
      el.summary.focus();
    });

    el.trayOpen.addEventListener('click', openCompare);
    el.trayClear.addEventListener('click', function () {
      state.cmp = []; trayNote = '';
      writeUrl(); syncCompareButtons(); renderTray();
    });
    el.compareClose.addEventListener('click', closeCompare);
    el.dialog.addEventListener('click', function (e) {
      if (e.target === el.dialog) { closeCompare(); return; }   // tap on the backdrop
      var rm = e.target.closest('[data-uncmp]');
      if (rm) {
        toggleCompare(rm.getAttribute('data-uncmp'));
        if (el.dialog.open) el.compareClose.focus();
      }
    });
    el.dialog.addEventListener('close', function () { (el.tray.hidden ? el.q : el.trayOpen).focus(); });

    window.addEventListener('popstate', function () {
      state = readUrl(); syncControls(); shown = PAGE; render(); renderTray();
    });
  }

  // -------------------------------------------------------------- load

  function prepare(d) {
    data = d;
    var seen = {};
    byId = {};
    brands = d.brands.map(function (row, i) {
      var b = PriceSearch.prepare(row[1]);
      b.i = i;
      b.id = row[0];
      b.name = row[1];
      b.sup = d.suppliers[row[2]];
      b.cat = d.categories[row[3]];
      b.sizes = row[4].map(function (s) {
        seen[s[0]] = true;
        return { ml: s[0], price: s[1], ppl: Math.round(s[1] * 1000 / s[0]) };
      });
      byId[b.id] = b;
      return b;
    });
    sizes = Object.keys(seen).map(Number).sort(function (a, b) { return a - b; });
    photos = d.photos || {};
  }

  var bound = false;
  function load() {
    el.summary.textContent = 'Loading prices…';
    fetch('data/site.json')
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        prepare(d);
        window.fillMeta(d.meta);
        buildControls();
        buildIntro();
        state = readUrl();
        syncControls();
        if (!bound) { bind(); bound = true; }
        render();
        renderTray();
        loadPopularity();
      })
      .catch(function () {
        el.summary.innerHTML = '<span class="error">Could not load the price list. ' +
          'Check your connection.</span> <button type="button" class="link-button" id="retry">Try again</button>';
        $('retry').addEventListener('click', load);
      });
  }

  // Optional: only exists once GoatCounter has data. It is an ORDER of brand
  // ids (no counts). Adds the sort option and badges and re-renders; a
  // missing file changes nothing.
  function loadPopularity() {
    fetch('data/popularity.json')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (p) {
        var ranked = (p && p.ranked || []).filter(function (id) { return byId[id]; });
        if (!ranked.length) { dropPopularSort(); return; }
        trendPos = {};
        var perCat = {};
        ranked.forEach(function (id, i) {
          trendPos[id] = i;
          var c = byId[id].cat;
          perCat[c] = (perCat[c] || 0) + 1;
          if (perCat[c] <= TRENDING_BADGE) catRank[id] = perCat[c];
        });
        var o = document.createElement('option');
        o.value = 'trending';
        o.textContent = 'Trending this week';
        el.sort.insertBefore(o, el.sort.options[1]);
        el.sort.value = state.sort;
        render();
      })
      .catch(dropPopularSort);
  }

  // A shared ?sort=trending link on a site without ranking data falls back
  // to the default order instead of a blank sort menu.
  function dropPopularSort() {
    if (state.sort !== 'trending') return;
    state.sort = '';
    el.sort.value = '';
    writeUrl();
    render();
  }

  load();

  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost')) {
    window.addEventListener('load', function () { navigator.serviceWorker.register('sw.js'); });
  }
})();
