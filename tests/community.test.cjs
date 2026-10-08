const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

test('Community filter links use verified destinations without network, storage, or location access', () => {
  const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'community.js'), 'utf8');
  const listeners = {}, select = {value: '', addEventListener: (name, fn) => { listeners[name] = fn; }}, link = {};
  const forbidden = new Proxy({}, {get() { throw new Error('Community links must not access location or storage'); }});
  const window = {};
  vm.runInNewContext(script, {window, navigator: forbidden, localStorage: forbidden, sessionStorage: forbidden,
    fetch() { throw new Error('Opening the dashboard must not contact a community site'); },
    document: {getElementById: id => id === 'community-retailer' ? select : link}});
  for (const [key, slug] of Object.entries({target:'target', walmart:'walmart', bestbuy:'best-buy', cvs:'cvs', dollargeneral:'dollar-general', costco:'costco'})) {
    select.value = key; listeners.change();
    assert.equal(link.href, `https://restockd.app/pokemon-in-store?retailer=${slug}`);
    assert.match(link.textContent, /^Open .+ sightings/);
  }
  for (const value of ['', 'gamestop', 'cardshop', 'constructor', 'javascript:alert(1)', null]) {
    select.value = value; listeners.change();
    assert.equal(link.href, 'https://restockd.app/pokemon-in-store');
    assert.equal(window.PokeWatchCommunity.retailerLink(value), null);
  }
  assert.equal(window.PokeWatchCommunity.retailerLink('Dollar General').url,
    'https://restockd.app/pokemon-in-store?retailer=dollar-general');
});
