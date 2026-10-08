'use strict';
(() => {
  const get = id => document.getElementById(id);
  const panel = get('nearby-panel');
  if (!panel) return;
  const locate = get('nearby-locate'), forget = get('nearby-forget');
  const radiusSelect = get('nearby-radius'), status = get('nearby-status');
  const chainSelect = get('nearby-chain');
  const results = get('nearby-results'), source = get('nearby-source');
  const privacy = get('nearby-privacy');
  const initialStatus = "Choose your location to find nearby stores. Check product inventory on the retailer's website or app.";
  const privacyText = "Your precise location stays in this tab's memory and is never published to GitHub. Reloading or forgetting clears it.";
  let position = null, radiusMiles = 20, provider = null, version = 0, pending = null, lastSearch = null;

  function coordinates(value) {
    return value && typeof value.latitude === 'number' && typeof value.longitude === 'number'
      && Number.isFinite(value.latitude) && Number.isFinite(value.longitude)
      && Math.abs(value.latitude) <= 90 && Math.abs(value.longitude) <= 180;
  }
  function radius() {
    const value = Number(radiusSelect.value);
    if (![10, 15, 20].includes(value)) {
      radiusSelect.value = String(radiusMiles);
      status.textContent = 'Choose a radius of 10, 15, or 20 miles.';
      return null;
    }
    radiusMiles = value;
    return value;
  }
  function cancel() {
    version += 1;
    if (pending) pending.abort();
    pending = null;
    return version;
  }
  function clearResults() {
    lastSearch = null;
    results.replaceChildren();
    source.replaceChildren();
    source.hidden = true;
    chainSelect.disabled = true;
  }
  function clear() {
    cancel();
    position = null;
    locate.disabled = false;
    locate.textContent = 'Use my location';
    forget.hidden = true;
    chainSelect.value = '';
    clearResults();
    status.textContent = initialStatus;
    try {
      if (typeof provider?.clear === 'function') Promise.resolve(provider.clear()).catch(() => {});
    } catch { /* The UI must still forget the location if a provider cleanup fails. */ }
  }
  function element(tag, text, className) {
    const item = document.createElement(tag);
    if (text) item.textContent = text;
    if (className) item.className = className;
    return item;
  }
  function publicLink(text, value) {
    try {
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.username || url.password) return null;
      const link = element('a', text);
      link.href = url.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.referrerPolicy = 'no-referrer';
      return link;
    } catch { return null; }
  }
  function distanceMiles(from, to) {
    const rad = value => value * Math.PI / 180;
    const deltaLat = rad(to.latitude - from.latitude), deltaLon = rad(to.longitude - from.longitude);
    const square = Math.sin(deltaLat / 2) ** 2
      + Math.cos(rad(from.latitude)) * Math.cos(rad(to.latitude)) * Math.sin(deltaLon / 2) ** 2;
    return 3958.7613 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, square))));
  }
  function renderStores(response, location, selectedRadius) {
    if (!response || !Array.isArray(response.stores)) throw new Error('Invalid store directory response');
    const seen = new Set(), stores = [];
    for (const store of response.stores) {
      if (!store || !coordinates(store) || typeof store.name !== 'string' || !store.name.trim()) continue;
      const distance = distanceMiles(location, store);
      if (distance > selectedRadius) continue;
      const key = String(store.id || `${store.name}:${store.latitude}:${store.longitude}`);
      if (seen.has(key)) continue;
      seen.add(key);
      stores.push({...store, distance});
    }
    stores.sort((a, b) => a.distance - b.distance);
    const selectedChain = chainSelect.value;
    const chains = [...new Set(stores.map(store => typeof store.chain === 'string' ? store.chain : '').filter(Boolean))].sort();
    const labels = {target:'Target',walmart:'Walmart',bestbuy:'Best Buy',gamestop:'GameStop',cvs:'CVS',dollargeneral:'Dollar General',costco:'Costco',cardshop:'Card shops',cardshops:'Card shops',games:'Games and card shops'};
    clearResults();
    const all = element('option', 'All stores'); all.value = '';
    chainSelect.replaceChildren(all);
    for (const chain of chains) {
      const option = element('option', labels[chain.toLowerCase().replace(/[^a-z]/g, '')] || chain);
      option.value = chain; chainSelect.append(option);
    }
    chainSelect.disabled = !chains.length;
    chainSelect.value = chains.includes(selectedChain) ? selectedChain : '';
    const visibleStores = stores.filter(store => !chainSelect.value || store.chain === chainSelect.value);
    for (const store of visibleStores) {
      const card = element('article', '', 'nearby-store');
      card.append(element('h3', store.name.trim()), element('p', `About ${store.distance.toFixed(1)} miles away · straight-line distance`));
      if (typeof store.address === 'string' && store.address.trim()) card.append(element('p', store.address.trim()));
      card.append(element('span', 'Product inventory not checked', 'badge'));
      const link = publicLink('Store details', store.url);
      if (link) { const paragraph = element('p'); paragraph.append(link); card.append(paragraph); }
      results.append(card);
    }
    status.textContent = visibleStores.length
      ? `${visibleStores.length} store location${visibleStores.length === 1 ? '' : 's'} found within ${selectedRadius} miles${chainSelect.value ? ' for this retailer' : ''}. Confirm the exact product with the store before visiting.`
      : `No store locations were returned within ${selectedRadius} miles. Directory coverage can be incomplete; this is not a stock check.`;
    const checkedAt = Date.parse(response.checkedAt);
    if (Number.isFinite(checkedAt)) source.append(element('span', `Directory checked ${new Date(checkedAt).toLocaleString()}. `));
    if (typeof response.attribution === 'string' && response.attribution) source.append(element('span', response.attribution));
    else if (response.attribution && typeof response.attribution.text === 'string') {
      source.append(publicLink(response.attribution.text, response.attribution.url) || element('span', response.attribution.text));
    }
    source.hidden = !source.textContent;
    lastSearch = {response, location, selectedRadius};
  }
  async function searchStores() {
    if (!position || radius() === null) return;
    const requestVersion = cancel();
    const location = {...position}, selectedRadius = radiusMiles;
    clearResults();
    if (!provider) {
      status.textContent = 'Location is ready. Store discovery is not connected yet. No nearby product inventory has been checked.';
      return;
    }
    const controller = new AbortController();
    pending = controller;
    status.textContent = `Finding store locations within ${selectedRadius} miles…`;
    try {
      const response = await provider.search({...location, radiusMiles: selectedRadius, signal: controller.signal});
      if (version !== requestVersion || controller.signal.aborted) return;
      renderStores(response, location, selectedRadius);
    } catch (error) {
      if (version !== requestVersion || controller.signal.aborted) return;
      clearResults();
      const message = typeof error?.publicMessage === 'string' ? error.publicMessage.trim().slice(0, 300) : '';
      status.textContent = `${message || 'The store directory could not be reached. Try your location again.'} Product inventory has not been checked.`;
    } finally {
      if (version === requestVersion) pending = null;
    }
  }
  locate.addEventListener('click', () => {
    if (radius() === null) return;
    if (!navigator.geolocation || typeof navigator.geolocation.getCurrentPosition !== 'function') {
      status.textContent = 'This browser cannot provide your location. Open this page in a browser with location support.';
      return;
    }
    const requestVersion = cancel();
    position = null;
    clearResults();
    locate.disabled = true;
    locate.textContent = 'Getting location…';
    forget.hidden = false;
    status.textContent = 'Waiting for your browser to share a location. You can allow or deny its location request.';
    const failed = error => {
      if (version !== requestVersion) return;
      locate.disabled = false;
      locate.textContent = 'Use my location';
      forget.hidden = true;
      status.textContent = error?.code === 1
        ? 'Location permission was denied. Allow location for this site in your browser settings, then try again.'
        : error?.code === 3
          ? 'The location request timed out. Try again when your computer can determine its location.'
          : 'Your location is unavailable. Check location services on your computer, then try again.';
    };
    try {
      navigator.geolocation.getCurrentPosition(result => {
        if (version !== requestVersion) return;
        if (!coordinates(result?.coords)) { failed({code: 2}); return; }
        position = {latitude: result.coords.latitude, longitude: result.coords.longitude};
        locate.disabled = false;
        locate.textContent = 'Update my location';
        searchStores();
      }, failed, {enableHighAccuracy: false, timeout: 10000, maximumAge: 300000});
    } catch { failed({code: 2}); }
  });
  radiusSelect.addEventListener('change', () => { if (radius() !== null && position) searchStores(); });
  chainSelect.addEventListener('change', () => { if (lastSearch) renderStores(lastSearch.response, lastSearch.location, lastSearch.selectedRadius); });
  forget.addEventListener('click', clear);
  radiusSelect.value = '20';
  window.PokeWatchNearby = Object.freeze({
    // The provider owns network access. User coordinates are never put in tracker state or storage.
    // search({latitude,longitude,radiusMiles,signal}) -> {stores,checkedAt,attribution}
    setProvider(value) {
      if (!value || typeof value.search !== 'function') throw new TypeError('A store directory search function is required.');
      provider = value;
      privacy.textContent = privacyText + (typeof value.privacyNotice === 'string' ? ` ${value.privacyNotice}` : '');
      if (position) searchStores();
    },
    clear,
  });
})();
