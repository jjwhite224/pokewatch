const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const root = path.join(__dirname, '..');
const script = fs.readFileSync(path.join(root, 'static', 'nearby.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'static', 'index.html'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

class Element {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.listeners = {};
    this.value = ''; this.hidden = false; this.disabled = false; this._text = '';
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
}

function nearby({supported = true, community = false} = {}) {
  const nodes = new Map(), requests = [], window = {};
  for (const match of html.matchAll(/<([a-z]+)\b[^>]*\bid="(nearby-[^"]+)"[^>]*>/g)) {
    const el = new Element(match[1]); el.hidden = /\bhidden\b/.test(match[0]);
    nodes.set(match[2], el);
  }
  const storage = new Proxy({}, {get() { throw new Error('Location must never access browser storage'); }});
  const context = vm.createContext({
    window, URL, AbortController, Date, console,
    navigator: supported ? {geolocation: {getCurrentPosition(success, failure, options) {
      requests.push({success, failure, options});
    }}} : {},
    document: {getElementById: id => nodes.get(id), createElement: tag => new Element(tag)},
    localStorage: storage, sessionStorage: storage,
    fetch() { throw new Error('The nearby UI must leave network access to its provider'); },
  });
  if (community) vm.runInContext(fs.readFileSync(path.join(root, 'static', 'community.js'), 'utf8'), context);
  vm.runInContext(script, context);
  return {
    window, requests, get: id => nodes.get('nearby-' + id),
    setProvider: value => window.PokeWatchNearby.setProvider(value),
    click: () => nodes.get('nearby-locate').listeners.click(),
    forget: () => nodes.get('nearby-forget').listeners.click(),
    radius: async value => { nodes.get('nearby-radius').value = value; nodes.get('nearby-radius').listeners.change(); await settle(); },
    chain: value => { nodes.get('nearby-chain').value = value; nodes.get('nearby-chain').listeners.change(); },
    locate: async (coords = {latitude: 40, longitude: -75}, index = requests.length - 1) => {
      requests[index].success({coords}); await settle();
    },
    cards: () => nodes.get('nearby-results').children,
  };
}

// These are synthetic fixtures only. No test store or coordinates are part of the site.
const store = (id, latitude, chain = 'cvs') => ({id, name: `Test ${id}`, address: `${id} Test Street`,
  latitude, longitude: -75, chain, url: `https://example.com/store/${id}`});
const response = stores => ({stores, checkedAt: '2026-10-08T12:00:00Z',
  attribution: {text: 'Test directory', url: 'https://example.com/directory'}});

test('Location is requested only on click; radius changes and provider setup never prompt', async () => {
  const app = nearby(), searches = [];
  assert.equal(app.get('radius').value, '20');
  app.setProvider({search: input => { searches.push(input); return response([]); },
    privacyNotice: 'Your approximate location is sent to Private.coffee to find stores.'});
  await app.radius('15');
  assert.equal(app.requests.length, 0);
  assert.equal(searches.length, 0);
  assert.match(app.get('privacy').textContent, /precise location stays in this tab/);
  assert.match(app.get('privacy').textContent, /approximate location is sent to Private.coffee/);
  app.click();
  assert.equal(app.requests.length, 1);
  assert.equal(app.requests[0].options.timeout, 10000);
  assert.equal(app.requests[0].options.enableHighAccuracy, false);
  await app.locate();
  assert.equal(searches.length, 1);
  assert.equal(searches[0].radiusMiles, 15);
  assert.deepEqual(Object.keys(app.window), ['PokeWatchNearby']);
  assert.deepEqual(Object.keys(app.window.PokeWatchNearby).sort(), ['clear', 'setProvider']);
});

test('Without a provider, location never creates made-up stores or inventory claims', async () => {
  const app = nearby(); app.click(); await app.locate();
  assert.equal(app.cards().length, 0);
  assert.match(app.get('status').textContent, /Store discovery is not connected/);
  assert.equal(app.get('forget').hidden, false);
  app.forget();
  assert.equal(app.get('forget').hidden, true);
  assert.match(app.get('status').textContent, /Choose your location/);
});

test('Permission denied, unavailable, timeout, and unsupported browsers have actionable states', () => {
  for (const [code, message] of [[1, /permission was denied/], [2, /location is unavailable/], [3, /timed out/]]) {
    const app = nearby(); app.click(); app.requests[0].failure({code});
    assert.match(app.get('status').textContent, message);
    assert.equal(app.get('locate').disabled, false);
    assert.equal(app.get('forget').hidden, true);
    assert.equal(app.cards().length, 0);
  }
  const app = nearby({supported: false}); app.click();
  assert.match(app.get('status').textContent, /cannot provide your location/);
  assert.equal(app.get('locate').disabled, false);
});

test('Invalid coordinates and radii never reach the provider', async () => {
  for (const coords of [{latitude: NaN, longitude: 0}, {latitude: 91, longitude: 0},
    {latitude: 0, longitude: 181}, {latitude: '40', longitude: -75}, null]) {
    const app = nearby(), searches = [];
    app.setProvider({search: input => { searches.push(input); return response([]); }});
    app.click(); await app.locate(coords);
    assert.equal(searches.length, 0);
    assert.match(app.get('status').textContent, /location is unavailable/);
  }
  const app = nearby(); app.get('radius').value = '25'; app.click();
  assert.equal(app.requests.length, 0);
  assert.equal(app.get('radius').value, '20');
  assert.match(app.get('status').textContent, /10, 15, or 20/);
});

test('Only genuine returned, valid, in-radius stores render; chain filtering stays local', async () => {
  const app = nearby(), searches = [];
  const payload = response([store('near', 40.05), store('middle', 40.1, 'dollargeneral'),
    store('further', 40.2, 'costco'), store('outside', 40.5), store('near', 40.05),
    {...store('invalid', 40), latitude: '40'}]);
  app.setProvider({search: input => { searches.push(input); return payload; }});
  app.click(); await app.locate();
  assert.equal(app.cards().length, 3);
  assert.match(app.cards()[0].textContent, /Test near/);
  assert.ok(app.cards().every(card => card.textContent.includes('Product inventory not checked')));
  assert.ok(app.cards().every(card => card.textContent.includes('straight-line distance')));
  assert.match(app.get('chain').textContent, /Dollar General/);
  app.chain('costco');
  assert.equal(app.cards().length, 1);
  assert.match(app.cards()[0].textContent, /Test further/);
  assert.equal(searches.length, 1, 'Retailer filter must not send another location query');
  app.chain(''); await app.radius('10');
  assert.equal(searches.length, 2);
  assert.equal(searches[1].radiusMiles, 10);
  assert.equal(app.cards().length, 2);
  assert.match(app.get('source').textContent, /Test directory/);
});

test('Forgetting location cancels a provider request and rejects a late result', async () => {
  const app = nearby(); let complete, input;
  app.setProvider({search: value => { input = value; return new Promise(resolve => { complete = resolve; }); }});
  app.click(); await app.locate();
  app.forget();
  assert.equal(input.signal.aborted, true);
  complete(response([store('late', 40.01)])); await settle();
  assert.equal(app.cards().length, 0);
  assert.match(app.get('status').textContent, /Choose your location/);
  assert.equal(app.get('forget').hidden, true);
});

test('Forgetting while browser permission is pending ignores a late geolocation response', async () => {
  const app = nearby(), searches = [];
  app.setProvider({search: input => { searches.push(input); return response([]); }});
  app.click(); app.forget(); await app.locate();
  assert.equal(searches.length, 0);
  assert.equal(app.cards().length, 0);
  assert.equal(app.get('locate').disabled, false);
  assert.match(app.get('status').textContent, /Choose your location/);
});

test('A superseded radius request cannot overwrite the current radius results', async () => {
  const app = nearby(), requests = [];
  app.setProvider({search: input => new Promise(resolve => requests.push({input, resolve}))});
  app.click(); await app.locate(); await app.radius('10');
  assert.equal(requests[0].input.signal.aborted, true);
  requests[1].resolve(response([store('current', 40.01)])); await settle();
  requests[0].resolve(response([store('old', 40.2)])); await settle();
  assert.equal(app.cards().length, 1);
  assert.match(app.cards()[0].textContent, /Test current/);
  assert.match(app.get('status').textContent, /within 10 miles/);
});

test('Provider failures do not imply sold-out inventory or preserve mismatched results', async () => {
  const app = nearby(); let failing = false;
  app.setProvider({search: () => { if (failing) throw new Error('failure'); return response([store('first', 40.01)]); }});
  app.click(); await app.locate(); assert.equal(app.cards().length, 1);
  failing = true; await app.radius('10');
  assert.equal(app.cards().length, 0);
  assert.match(app.get('status').textContent, /directory could not be reached/);
  assert.doesNotMatch(app.get('status').textContent, /sold out/i);
});

test('Untrusted store text is rendered as text and unsafe detail links are omitted', async () => {
  const app = nearby();
  app.setProvider({search: () => response([{...store('unsafe', 40.01), name: '<script>alert(1)</script>', url: 'javascript:alert(1)'}])});
  app.click(); await app.locate();
  assert.match(app.cards()[0].textContent, /<script>alert\(1\)<\/script>/);
  assert.ok(app.cards()[0].children.every(child => child.tagName !== 'script'));
  assert.doesNotMatch(app.cards()[0].textContent, /Store details/);
});

test('Forget also drops the provider cache and still clears the UI if cleanup fails', async () => {
  const app = nearby(); let cleared = 0;
  app.setProvider({search: () => response([store('cached', 40.01)]), clear() {
    cleared += 1; throw new Error('cleanup failed');
  }});
  app.click(); await app.locate(); assert.equal(app.cards().length, 1);
  app.forget();
  assert.equal(cleared, 1);
  assert.equal(app.cards().length, 0);
  assert.equal(app.get('forget').hidden, true);
  assert.match(app.get('status').textContent, /Choose your location/);
});

test('Only the provider error publicMessage is shown, never internal error details', async () => {
  const app = nearby(); let exposePublicMessage = true;
  app.setProvider({search() {
    const error = new Error('internal request with sensitive parameters');
    if (exposePublicMessage) error.publicMessage = 'The store directory is busy. Please wait a minute.';
    throw error;
  }});
  app.click(); await app.locate();
  assert.match(app.get('status').textContent, /Please wait a minute/);
  assert.doesNotMatch(app.get('status').textContent, /sensitive parameters/);
  exposePublicMessage = false; await app.radius('15');
  assert.match(app.get('status').textContent, /directory could not be reached/);
  assert.doesNotMatch(app.get('status').textContent, /sensitive parameters/);
});

test('Nearby community links select only a retailer, never imply a branch match or transmit location', async () => {
  const app = nearby({community: true});
  app.setProvider({search: () => response([store('dg', 40.01, 'dollargeneral'), store('shop', 40.02, 'cardshop')])});
  app.click(); await app.locate();
  const [dg, shop] = app.cards();
  const anchors = dg.children.flatMap(child => child.children).filter(child => child.tagName === 'a');
  const report = anchors.find(a => a.href.startsWith('https://restockd.app/'));
  assert.equal(report.href, 'https://restockd.app/pokemon-in-store?retailer=dollar-general');
  assert.equal(report.rel, 'noopener noreferrer');
  assert.equal(report.referrerPolicy, 'no-referrer');
  assert.equal(report.target, '_blank');
  assert.match(dg.textContent, /Retailer-wide reports/);
  assert.match(dg.textContent, /Product inventory not checked/);
  assert.doesNotMatch(shop.textContent, /community sightings/);
  app.forget(); assert.equal(app.cards().length, 0);
});
