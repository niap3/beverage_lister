/* Fills [data-meta="..."] elements from the data file's metadata, so the
 * "as of" and printed dates on every page come from one place.
 *
 * The HTML carries the same dates as fallback text, so the page still says
 * something true before this runs or with scripts off.
 *
 * index.html calls window.fillMeta() with the meta block of data/site.json.
 * Other pages set data-meta-src on <html> and this fetches that file.
 */
(function () {
  'use strict';

  function formatDate(iso) {
    var p = String(iso).split('-');
    var d = new Date(+p[0], +p[1] - 1, +p[2]);
    if (isNaN(d)) return iso;
    return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' });
  }

  function fillMeta(meta) {
    var els = document.querySelectorAll('[data-meta]');
    for (var i = 0; i < els.length; i++) {
      var el = els[i], key = el.getAttribute('data-meta'), v = meta[key];
      if (v == null) continue;
      if (key === 'effective' || key === 'printed') {
        el.textContent = formatDate(v);
        if (el.tagName === 'TIME') el.setAttribute('datetime', v);
      } else if (typeof v === 'number') {
        el.textContent = v.toLocaleString('en-IN');
      } else {
        el.textContent = v;
      }
    }
  }

  window.fillMeta = fillMeta;
  window.formatMetaDate = formatDate;

  var src = document.documentElement.getAttribute('data-meta-src');
  if (src && window.fetch) {
    fetch(src).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (m) { if (m) fillMeta(m); })
      .catch(function () { /* keep the fallback text */ });
  }
})();
