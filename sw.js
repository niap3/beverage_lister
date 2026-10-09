/* Offline fallback for people in a shop queue with patchy signal.
 *
 * Network first, always: a fresh price list must win the moment it is
 * deployed. The cache is only used when the network fails, so the worst case
 * is the last list this phone saw, never a stale list over a working
 * connection. Same-origin GETs only.
 */
var CACHE = 'prices-v3';
var CORE = ['./', 'index.html', 'about.html', 'catalogue.html', 'assets/style.css', 'assets/meta.js', 'assets/search.js',
            'assets/app.js', 'assets/logo.svg', 'assets/favicon.svg', 'assets/fonts/barlow-semi-condensed-latin-700-normal.woff2',
            'data/site.json', 'data/meta.json'];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(CORE); }));
  self.skipWaiting();
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; })
      .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  if (/\.pdf$/i.test(new URL(req.url).pathname)) return;   // 1.5 MB, not worth caching
  e.respondWith(
    // no-cache: always revalidate with the server (cheap 304s), never trust a
    // possibly stale HTTP-cache copy while online.
    fetch(req, { cache: 'no-cache' }).then(function (res) {
      if (res.ok) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
      }
      return res;
    }).catch(function () {
      return caches.match(req, { ignoreSearch: true });   // ?v= stamps and ?q= searches
    })
  );
});
