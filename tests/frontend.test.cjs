const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const staticDir = path.join(__dirname, '..', 'static');
const appScript = fs.readFileSync(path.join(staticDir, 'app.js'), 'utf8');
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const start = Date.parse('2026-10-05T12:00:00Z');
const stamp = new Date(start).toISOString();

function snapshot() {
  return {
    interval_seconds: 900, generated_at: stamp, last_scan: stamp, scanning: false,
    token: 'local-test-token', alerts: [], releases: {},
    sources: {shop: {name: 'Test Shop', url: 'https://example.com/collections/pokemon/products.json',
      status: 'ok', checked_at: stamp, count: 1}},
    products: {box: {id: 'box', title: 'Pokémon Booster Box', store: 'Test Shop',
      url: 'https://example.com/products/box', image: null, currency: 'USD',
      price_cents: 4999, reference_cents: 5999, reference_kind: 'Manufacturer MSRP',
      reference_url: 'https://example.com/reference', availability: 'InStock',
      checked_at: stamp, first_seen: stamp, stale: false, qualifies: true}},
  };
}

// A small DOM substitute lets the real application run without packages or a browser.
// It records visible output, event handlers, and network requests rather than mocking
// application helpers such as renderResults(), fresh(), or api().
class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.children = []; this.attributes = {}; this.listeners = {};
    this.dataset = {}; this.value = ''; this.checked = false;
    this.hidden = false; this.disabled = false; this._text = '';
    this.classList = {toggle: (name, enabled) => {
      const names = new Set((this.attributes.class || '').split(' ').filter(Boolean));
      enabled ? names.add(name) : names.delete(name);
      this.attributes.class = [...names].join(' ');
    }};
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent ?? String(child)).join(''); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  querySelectorAll(selector) {
    return this.children.flatMap(child => {
      if (!(child instanceof Element)) return [];
      const matches = selector.startsWith('.')
        ? (child.attributes.class || '').split(' ').includes(selector.slice(1))
        : child.tagName === selector.toUpperCase();
      return [...(matches ? [child] : []), ...child.querySelectorAll(selector)];
    });
  }
  reset() { this.formData = {}; }
  close() { this.open = false; }
  showModal() { this.open = true; }
}

async function dashboard(mode, data = snapshot()) {
  let clock = start, failing = false;
  const calls = [], timers = [], nodes = new Map();
  for (const match of html.matchAll(/<([a-z]+)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const el = new Element(match[1]);
    el.hidden = /\bhidden\b/.test(match[0]);
    nodes.set('#' + match[2], el);
  }
  const tabs = new Element('nav');
  for (const name of ['matches', 'all', 'unverified', 'releases']) {
    const button = new Element('button'); button.dataset.view = name; tabs.append(button);
  }
  nodes.set('.tabs', tabs);
  for (const name of ['reference', 'watch']) {
    nodes.set(`#${name}-form .form-error`, new Element('p'));
    nodes.get(`#${name}-form`).elements = Object.fromEntries(
      ['product_id', 'price', 'url', 'kind'].map(key => [key, {value: ''}]));
  }
  let registeredTool;
  const document = {
    createElement: tag => new Element(tag),
    querySelector: selector => { assert.ok(nodes.has(selector), `Unexpected selector: ${selector}`); return nodes.get(selector); },
    querySelectorAll: selector => { assert.equal(selector, '.close'); return []; },
    modelContext: {registerTool: tool => { registeredTool = tool; }},
  };
  class ClockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock])); }
    static now() { return clock; }
  }
  class FormData {
    constructor(form) { this.entries = Object.entries(form.formData || {}); }
    [Symbol.iterator]() { return this.entries[Symbol.iterator](); }
  }
  const window = {addEventListener() {}};
  if (mode === 'pages') window.POKEWATCH_HOSTING = {mode: 'pages', stateUrl: './state.json'};
  const context = vm.createContext({window, document, Date: ClockDate, URL, Intl,
    AbortController, FormData, console,
    setInterval: (callback, delay) => { timers.push({callback, delay}); },
    fetch: async (url, options = {}) => {
      calls.push({url, options});
      if (failing) throw new Error('Offline');
      return {ok: true, json: async () => options.method === 'POST' ? {ok: true} : structuredClone(data)};
    },
  });
  if (mode !== 'pages') vm.runInContext(fs.readFileSync(path.join(staticDir, 'hosting.js'), 'utf8'), context);
  vm.runInContext(appScript, context);
  await new Promise(resolve => setImmediate(resolve));
  return {
    nodes, calls, timers, tool: registeredTool,
    get: selector => nodes.get(selector),
    advance: milliseconds => { clock += milliseconds; },
    fail: () => { failing = true; },
    age: () => timers.find(timer => timer.delay === 15000).callback(),
    view: name => tabs.listeners.click({target: {dataset: {view: name}}}),
    availableOnly: () => { nodes.get('#stock').checked = true; nodes.get('#stock').listeners.input(); },
    cards: () => nodes.get('#results').querySelectorAll('.product'),
    submit: async (name, formData) => {
      const form = nodes.get(`#${name}-form`); form.formData = formData;
      await form.onsubmit({preventDefault() {}, target: form});
    },
  };
}

test('Pages mode only reads its snapshot, hides mutations, and rejects hidden form submissions', async () => {
  const app = await dashboard('pages');
  assert.equal(app.get('#matches').textContent, '1');
  assert.equal(app.get('#add-watch').hidden, true);
  assert.equal(app.get('#watch-dialog').hidden, true);
  assert.equal(app.get('#reference-dialog').hidden, true);
  assert.equal(app.cards()[0].querySelectorAll('button').length, 0);
  assert.equal(app.get('#check').textContent, 'Refresh data');
  await app.get('#check').onclick();
  assert.equal(app.calls.length, 2);
  await app.submit('watch', {url: 'https://example.com/products/other'});
  await app.submit('reference', {product_id: 'box', price: '59.99'});
  assert.equal(app.calls.length, 2, 'Read-only controls must never send mutations');
  assert.ok(app.calls.every(call => call.url === './state.json' && !call.options.method));
  assert.match(app.get('#watch-form .form-error').textContent, /read-only/);
  assert.match(app.get('#reference-form .form-error').textContent, /read-only/);
  assert.ok(app.timers.some(timer => timer.delay === 60000));
});

test('Local mode retains scan, watch, and reference API requests with the session token', async () => {
  const app = await dashboard('local');
  assert.equal(app.calls[0].url, './api/state');
  assert.equal(app.get('#add-watch').hidden, false);
  assert.equal(app.cards()[0].querySelectorAll('button').length, 1);
  await app.get('#check').onclick();
  await app.submit('watch', {url: 'https://example.com/products/other'});
  await app.submit('reference', {product_id: 'box', price: '59.99', kind: 'Manufacturer MSRP'});
  const posts = app.calls.filter(call => call.options.method === 'POST');
  assert.deepEqual(posts.map(call => call.url), ['./api/scan', './api/watch', './api/reference']);
  assert.ok(posts.every(call => call.options.headers['X-PokeWatch-Token'] === 'local-test-token'));
  assert.deepEqual(JSON.parse(posts[1].options.body), {url: 'https://example.com/products/other'});
  assert.equal(app.get('#check').textContent, 'Check now');
  assert.ok(app.timers.some(timer => timer.delay === 5000));
});

for (const mode of ['pages', 'local']) {
  test(`${mode}: elapsed time expires matches, source health, available-only results, and tool queries`, async () => {
    const app = await dashboard(mode);
    assert.equal(app.get('#matches').textContent, '1');
    assert.equal(app.get('#sources-count').textContent, '1 / 1');
    assert.equal(app.tool.execute({matchesOnly: true}).length, 1);
    app.advance(30 * 60 * 1000 + 1);
    app.age();
    assert.equal(app.calls.length, 1, 'Age checks must work without another successful fetch');
    assert.equal(app.get('#matches').textContent, '0');
    assert.equal(app.get('#sources-count').textContent, '0 / 1');
    assert.match(app.get('#sources').textContent, /Needs recheck/);
    assert.equal(app.tool.execute({matchesOnly: true}).length, 0);
    assert.equal(app.tool.execute({})[0].stale, true);
    app.view('all');
    assert.equal(app.cards().length, 1, 'Expired rows remain visible for inspection');
    assert.match(app.cards()[0].textContent, /Needs recheck/);
    app.availableOnly();
    assert.equal(app.cards().length, 0);
    await app.get('#check').onclick();
    assert.equal(app.get('#matches').textContent, '0', 'Reading the same old snapshot must not renew its stock claims');
    assert.equal(app.cards().length, 0);
  });

  test(`${mode}: losing the data connection still expires retained stock`, async () => {
    const app = await dashboard(mode);
    app.fail();
    const poll = app.timers.find(timer => timer.delay === (mode === 'pages' ? 60000 : 5000));
    await poll.callback();
    assert.equal(app.get('#notice').hidden, false);
    app.advance(31 * 60 * 1000); app.age();
    assert.equal(app.get('#matches').textContent, '0');
    assert.equal(app.get('#sources-count').textContent, '0 / 1');
    assert.equal(app.get('#scan-state').textContent, mode === 'pages' ? 'Refresh failed' : 'Disconnected');
  });
}

test('Missing, invalid, future, or server-stale check times do not produce available matches', async () => {
  const data = snapshot(), original = data.products.box;
  data.products = Object.fromEntries([
    ['missing', {checked_at: null}], ['invalid', {checked_at: 'invalid'}],
    ['future', {checked_at: new Date(start + 60000).toISOString()}], ['server-stale', {stale: true}],
  ].map(([id, extra]) => [id, {...original, id, ...extra}]));
  const app = await dashboard('pages', data);
  assert.equal(app.get('#matches').textContent, '0');
  app.view('all'); assert.equal(app.cards().length, 4);
  app.availableOnly(); assert.equal(app.cards().length, 0);
});

test('All local dashboard assets resolve under a GitHub Pages project subpath', () => {
  const assets = [...html.matchAll(/(?:src|href)="([^"]+)"/g)].map(match => match[1]);
  assert.ok(assets.length >= 5);
  for (const asset of assets) {
    const resolved = new URL(asset, 'https://example.github.io/pokewatch/');
    assert.ok(resolved.pathname.startsWith('/pokewatch/'), `${asset} escaped the project path`);
    if (asset !== './') assert.ok(fs.existsSync(path.join(staticDir, asset)));
  }
});
