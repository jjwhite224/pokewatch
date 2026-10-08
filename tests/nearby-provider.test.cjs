const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '..', 'static', 'nearby-provider.js'), 'utf8');
function setup(payload = {elements: []}, status = 200, implementation) {
  let provider, clock = Date.parse('2026-10-08T12:00:00Z'), nextTimer = 0;
  const calls = [], timers = new Map();
  class Clock extends Date {
    constructor(...args) { super(...(args.length ? args : [clock])); }
    static now() { return clock; }
  }
  const context = {window: {PokeWatchNearby: {setProvider(value) { provider = value; }}},
    URLSearchParams, AbortController, DOMException, Date: Clock,
    setTimeout(callback, delay) { const id = ++nextTimer; timers.set(id, {callback, at: clock + delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    fetch: async (url, options) => {calls.push({url, options}); return implementation
      ? implementation(url, options) : {ok: status === 200, status, json: async () => payload};}};
  vm.runInNewContext(code, context);
  return {provider, calls, timers, advance(ms) {
    clock += ms;
    for (const [id, timer] of timers) if (timer.at <= clock) { timers.delete(id); timer.callback(); }
  }};
}
const location = {latitude: 40.75123456, longitude: -73.99432123, radiusMiles: 20};
function place(id, name, shop, extra = {}) {
  return {id, type: 'node', lat: 40.75 + id / 1000, lon: -73.99, tags: {name, shop, ...extra}};
}
test('does not request location or network on load; rounds outbound location and reuses all radii', async () => {
  const {provider, calls} = setup();
  assert.equal(calls.length, 0);
  await provider.search(location);
  const query = calls[0].options.body.get('data');
  assert.match(query, /40\.45,-74\.39,41\.05,-73\.59/);
  assert.doesNotMatch(query, /75123456|99432123/);
  assert.equal(calls[0].options.credentials, 'omit');
  assert.equal(calls[0].options.referrerPolicy, 'origin');
  await provider.search({...location, radiusMiles: 10});
  await provider.search({...location, radiusMiles: 15});
  assert.equal(calls.length, 1);
  provider.clear();
  await assert.rejects(provider.search(location), /wait one minute/);
});
test('classifies requested chains and rejects closed, unrelated and duplicate locations', async () => {
  const places = [place(1, 'CVS Pharmacy', 'chemist'), place(2, 'Dollar General', 'variety_store'),
    place(3, 'Costco Wholesale', 'wholesale'), place(4, 'Target', 'department_store'),
    place(5, 'Walmart Supercenter', 'supermarket'), place(6, 'Best Buy', 'electronics'),
    place(7, 'GameStop', 'video_games'), place(8, 'Neighborhood Card Games', 'games'),
    place(9, 'Costco Gas', 'fuel'), place(10, 'CVS', 'chemist', {disused: 'yes'}),
    place(11, 'Canada CVS', 'chemist', {brand: 'CVS', 'addr:country': 'CA'}),
    {type: 'way', id: 100, center: {lat: 40.751, lon: -73.99}, tags: {name: 'CVS Pharmacy', shop: 'chemist'}},
    place(12, 'Other store', 'convenience')];
  const {provider} = setup({elements: places});
  const result = await provider.search(location);
  assert.deepEqual(Array.from(result.stores, s => s.chain), ['cvs', 'dollargeneral', 'costco', 'target', 'walmart', 'bestbuy', 'gamestop', 'cardshop']);
  assert.match(result.attribution.url, /openstreetmap.org\/copyright/);
  for (const store of result.stores) {
    assert.equal(store.availability, undefined);
    assert.match(store.url, /^https:\/\/www.openstreetmap.org\/(node|way)\/\d+$/);
  }
});
test('partial results and HTTP failures never become an empty successful directory', async () => {
  for (const [payload, status] of [[{elements: [], remark: 'timeout'}, 200], [{}, 200], [{elements: []}, 429], [{elements: []}, 500]]) {
    const {provider} = setup(payload, status);
    await assert.rejects(provider.search(location));
  }
});
test('invalid locations, radius and cancelled requests never reach the provider', async () => {
  const {provider, calls} = setup();
  const controller = new AbortController(); controller.abort();
  for (const values of [{latitude: NaN}, {longitude: 181}, {radiusMiles: 21}, {latitude: '40.75'}, {signal: controller.signal}]) {
    await assert.rejects(provider.search({...location, ...values}));
  }
  assert.equal(calls.length, 0);
});
test('forgiving location erases the cache, cancels active work, and retains the request cooldown', async () => {
  let finish;
  const {provider, calls, advance} = setup(undefined, 200, () => new Promise(resolve => {finish = resolve;}));
  const pending = provider.search(location);
  provider.clear();
  assert.equal(calls[0].options.signal.aborted, true);
  await assert.rejects(provider.search(location), /wait one minute/);
  finish({ok: true, json: async () => ({elements: [place(1, 'CVS Pharmacy', 'chemist')]})});
  await assert.rejects(pending, {name: 'AbortError'});
  advance(60001);
  const next = provider.search(location);
  assert.equal(calls.length, 2, 'An ignored late result must not repopulate the cleared cache');
  finish({ok: true, json: async () => ({elements: []})});
  await next;
});
test('one-hour cache retention expires without further searches and requires a fresh request', async () => {
  const {provider, calls, advance, timers} = setup();
  await provider.search(location);
  advance(3599999);
  await provider.search(location);
  assert.equal(calls.length, 1);
  assert.equal(timers.size, 1, 'A retention timer must clear location-derived data while the tab is idle');
  advance(1);
  assert.equal(timers.size, 0);
  await provider.search(location);
  assert.equal(calls.length, 2);
  provider.clear();
  assert.equal(timers.size, 0);
});
test('aborts during response parsing and request timeouts cannot cache successful-looking results', async () => {
  for (const mode of ['caller', 'timeout']) {
    let finishJson;
    const {provider, calls, advance} = setup(undefined, 200, async () => ({ok: true,
      json: () => new Promise(resolve => {finishJson = resolve;})}));
    const controller = new AbortController();
    const pending = provider.search({...location, signal: controller.signal});
    await new Promise(resolve => setImmediate(resolve));
    if (mode === 'caller') controller.abort(); else advance(35000);
    finishJson({elements: []});
    await assert.rejects(pending, {name: 'AbortError'});
    assert.equal(calls[0].options.signal.aborted, true);
  }
});
test('lifecycle tags exclude closed shops and pharmacies; malformed elements are ignored', async () => {
  const records = [null, {}, place(0, 'CVS', 'chemist'), place(1, 'CVS', 'chemist')];
  for (const [offset, tag] of ['closed:shop', 'demolished:shop', 'removed:amenity', 'disused:amenity', 'construction:shop'].entries()) {
    records.push(place(10 + offset, 'CVS Pharmacy', 'chemist', {[tag]: 'pharmacy'}));
  }
  records.push(place(30, 'Target', 'department_store', {closed: 'YES'}));
  records.push(place(31, 'Costco', 'wholesale', {abandoned: 'true'}));
  const {provider} = setup({elements: records});
  const result = await provider.search(location);
  assert.deepEqual(Array.from(result.stores, store => store.id), ['node/1']);
});
test('node, way and relation mappings collapse by branch while nearby separate branches survive', async () => {
  const address = {'addr:housenumber': '10', 'addr:street': 'Main Street'};
  const records = [
    {type: 'node', id: 1, lat: 40.75, lon: -73.99, tags: {name: 'CVS Pharmacy', shop: 'chemist', ...address}},
    {type: 'way', id: 2, center: {lat: 40.7512, lon: -73.99}, tags: {name: 'CVS/pharmacy', brand: 'CVS', shop: 'chemist', ...address}},
    {type: 'relation', id: 3, center: {lat: 40.7501, lon: -73.99}, tags: {name: 'CVS', shop: 'chemist', ...address}},
    {type: 'node', id: 4, lat: 40.7501, lon: -73.99, tags: {name: 'CVS Pharmacy', shop: 'chemist', ...address, 'addr:housenumber': '11'}},
    {type: 'node', id: 5, lat: 40.76, lon: -73.99, tags: {name: 'Costco', shop: 'wholesale', ref: '100'}},
    {type: 'way', id: 6, center: {lat: 40.7601, lon: -73.99}, tags: {name: 'Costco Wholesale', shop: 'wholesale', ref: '100'}},
    {type: 'node', id: 7, lat: 40.7601, lon: -73.99, tags: {name: 'Costco', shop: 'wholesale', ref: '101'}},
  ];
  const {provider} = setup({elements: records});
  const result = await provider.search(location);
  assert.deepEqual(Array.from(result.stores, store => store.id), ['node/1', 'node/4', 'node/5', 'node/7']);
});
