// Search behaviour against the real data. Run: node --test tests/search.test.js
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');

const S = require(path.join(__dirname, '..', 'assets', 'search.js'));
const D = require(path.join(__dirname, '..', 'data', 'site.json'));

const sizes = [...new Set(D.brands.flatMap((b) => b[4].map((s) => s[0])))];
const items = D.brands.map((b) => Object.assign(S.prepare(b[1]), { name: b[1] }));

function run(q) {
  const pq = S.parseQuery(q, sizes);
  const res = S.search(items, pq.text);
  res.hits.sort((a, b) => a.rank - b.rank);
  return { names: res.hits.map((h) => h.item.name), exact: res.exact, size: pq.size };
}

test('spacing and case are ignored', () => {
  for (const q of ['royalstag', 'Royal Stag', 'ROYAL-STAG']) {
    const r = run(q);
    assert.ok(r.exact, q);
    assert.strictEqual(r.names[0], "SEAGRAM'S ROYAL STAG DELUXE WHISKY", q);
  }
});

test('typos find the brand but are flagged as not exact', () => {
  const r = run('royl stag');
  assert.strictEqual(r.exact, false);
  assert.ok(r.names.includes("SEAGRAM'S ROYAL STAG DELUXE WHISKY"));
});

test('a number in the query becomes a bottle size', () => {
  assert.strictEqual(run('royal stag 750').size, 750);
  assert.strictEqual(run('royalstag 1 litre').size, 1000);
});

test('brands not in the list return nothing, never a near guess', () => {
  for (const q of ['Baileys', 'teachers', 'chivas', 'jameson', 'captain morgan']) {
    assert.deepStrictEqual(run(q).names, [], q);
  }
});

test('"and" is not matched inside other words', () => {
  const r = run('black and white');
  assert.strictEqual(r.exact, false);
  assert.ok(r.names.every((n) => /\bBLACK\b/.test(n) && /\bWHITE\b/.test(n)));
});
