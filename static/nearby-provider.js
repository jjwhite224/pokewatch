'use strict';
(() => {
  // This directory returns places, never product inventory. No request runs on page load.
  const endpoint = 'https://overpass-api.de/api/interpreter';
  const cacheMs = 60 * 60 * 1000;
  const chains = [
    ['target', /^target(?:\b|$)/i], ['walmart', /^wal[ -]?mart(?:\b|$)/i],
    ['bestbuy', /^best\s?buy(?:\b|$)/i], ['gamestop', /^game\s?stop(?:\b|$)/i],
    ['cvs', /^cvs(?:\b|\/)/i], ['dollargeneral', /^dollar general(?:\b|$)/i],
    ['costco', /^costco(?:\b|$)/i],
  ];
  let cached = null, cacheTimer = null, nextRequestAt = 0, generation = 0;
  const activeRequests = new Set();
  function error(message) {
    const value = new Error(message); value.publicMessage = message; return value;
  }
  function dropCache() {
    cached = null;
    if (cacheTimer !== null) clearTimeout(cacheTimer);
    cacheTimer = null;
  }
  function normalized(value) {
    return typeof value === 'string' ? value.trim().toLowerCase().replace(/\s+/g, ' ') : '';
  }
  function metresBetween(first, second) {
    const rad = degrees => degrees * Math.PI / 180;
    const dlat = rad(second.latitude - first.latitude), dlon = rad(second.longitude - first.longitude);
    const square = Math.sin(dlat / 2) ** 2 + Math.cos(rad(first.latitude))
      * Math.cos(rad(second.latitude)) * Math.sin(dlon / 2) ** 2;
    return 6371008.8 * 2 * Math.asin(Math.sqrt(Math.min(1, square)));
  }
  function sameBranch(first, second) {
    if (first.store.id === second.store.id) return true;
    if (first.store.chain !== second.store.chain) return false;
    const sameName = normalized(first.store.name) === normalized(second.store.name);
    if (first.store.chain === 'cardshop' && !sameName) return false;
    // Nearby branches on opposite sides of a street can be distinct stores.
    if (first.ref && second.ref && first.ref !== second.ref) return false;
    if (first.street && second.street && first.street !== second.street) return false;
    const distance = metresBetween(first.store, second.store);
    if (distance > 300) return false;
    if (first.ref && second.ref && first.ref === second.ref) return true;
    if (first.street && second.street && first.street === second.street) return true;
    // Building centres and entrance points need not have identical names/coordinates.
    return sameName && distance < 40
      || first.type !== second.type && first.store.chain !== 'cardshop' && distance < 100;
  }
  function storesFrom(payload) {
    if (!payload || !Array.isArray(payload.elements) || payload.remark) {
      throw error('The store directory returned incomplete data. Try again later or use the retailer links below.');
    }
    const branches = [];
    for (const item of payload.elements) {
      if (!item || typeof item !== 'object') continue;
      const tags = item.tags || {};
      if (!['node', 'way', 'relation'].includes(item.type) || !Number.isSafeInteger(item.id) || item.id <= 0) continue;
      const inactive = ['disused', 'abandoned', 'closed', 'demolished', 'removed', 'razed', 'proposed', 'construction'];
      if (inactive.some(prefix => ['yes', 'true', '1'].includes(normalized(tags[prefix]))
          || tags[`${prefix}:shop`] || tags[`${prefix}:amenity`])
          || ['vacant', 'closed', 'no', 'disused', 'abandoned'].includes(normalized(tags.shop))) continue;
      if (tags['addr:country'] && normalized(tags['addr:country']) !== 'us') continue;
      const name = (typeof tags.name === 'string' && tags.name.trim() ? tags.name : tags.brand)?.trim?.();
      if (typeof name !== 'string' || !name.trim()) continue;
      const chain = chains.find(([, pattern]) => pattern.test(tags.brand || '') || pattern.test(name))?.[0];
      // Do not include a chain's fuel station, optical office or ATM as a card retailer.
      if (chain && !['supermarket', 'department_store', 'wholesale', 'electronics', 'video_games', 'games', 'chemist', 'variety_store', 'convenience', 'general'].includes(tags.shop)
          && tags.amenity !== 'pharmacy') continue;
      if (!chain && !['games', 'collector', 'hobby'].includes(tags.shop)) continue;
      const latitude = item.lat ?? item.center?.lat, longitude = item.lon ?? item.center?.lon;
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) continue;
      const address = [
        [tags['addr:housenumber'], tags['addr:street']].filter(Boolean).join(' '),
        tags['addr:city'], [tags['addr:state'], tags['addr:postcode']].filter(Boolean).join(' '),
      ].filter(Boolean).join(', ');
      const store = {id: `${item.type}/${item.id}`, name, chain: chain || 'cardshop', address,
        latitude, longitude, url: `https://www.openstreetmap.org/${item.type}/${item.id}`};
      const branch = {store, type: item.type, ref: normalized(tags.ref),
        street: tags['addr:housenumber'] && tags['addr:street']
          ? normalized(`${tags['addr:housenumber']} ${tags['addr:street']}`) : ''};
      const previous = branches.find(other => sameBranch(other, branch));
      if (previous) {
        if (!previous.store.address && address) previous.store.address = address;
        continue;
      }
      branches.push(branch);
    }
    return branches.map(branch => branch.store);
  }
  async function search({latitude, longitude, radiusMiles, signal}) {
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90
        || Math.abs(longitude) > 180 || ![10, 15, 20].includes(radiusMiles)) throw error('Choose a valid location and a 10-, 15-, or 20-mile radius.');
    if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError');
    // Two decimals disclose an approximate area. A 1 km buffer covers rounding at the edge.
    const lat = latitude.toFixed(2), lon = longitude.toFixed(2), key = `${lat},${lon}`;
    if (cached?.key === key && Date.now() - cached.at < cacheMs) return cached.value;
    if (Date.now() < nextRequestAt) throw error('Please wait one minute before another directory request. You can still use the retailer links below.');
    nextRequestAt = Date.now() + 60000;
    const requestGeneration = generation;
    // A rectangular map query is much cheaper than repeating circular geometry
    // searches in dense cities. The UI applies the exact chosen distance.
    const latSpan = 33187 / 111000;
    const lonSpan = latSpan / Math.cos((Math.abs(Number(lat)) + latSpan) * Math.PI / 180);
    const down = value => (Math.floor(value * 100) / 100).toFixed(2);
    const up = value => (Math.ceil(value * 100) / 100).toFixed(2);
    const area = Math.abs(Number(lat)) < 85 && Number(lon) - lonSpan >= -180 && Number(lon) + lonSpan <= 180
      ? `(${down(Number(lat) - latSpan)},${down(Number(lon) - lonSpan)},${up(Number(lat) + latSpan)},${up(Number(lon) + lonSpan)})`
      : `(around:33187,${lat},${lon})`;
    const names = '[~"^(name|brand)$"~"^(Target|Wal[ -]?mart|Best ?Buy|Game ?Stop|CVS|Dollar General|Costco)($|[^a-z])",i]';
    const query = `[out:json][timeout:25][maxsize:134217728];(nwr${area}[shop]${names};nwr${area}[amenity=pharmacy]${names};nwr${area}[shop~"^(games|collector|hobby)$"];);out center tags;`;
    const controller = new AbortController();
    activeRequests.add(controller);
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, {once: true});
    const timer = setTimeout(abort, 35000);
    try {
      const response = await fetch(endpoint, {method: 'POST', body: new URLSearchParams({data: query}),
        signal: controller.signal, credentials: 'omit', referrerPolicy: 'origin', cache: 'no-store'});
      if (!response.ok) throw error(response.status === 429
        ? 'The directory is busy. Wait a minute and try again, or use the retailer links below.'
        : 'The store directory is temporarily unavailable. Use the retailer links below or try again later.');
      const payload = await response.json();
      // A request can finish despite an abort (for example, while parsing JSON).
      if (controller.signal.aborted || signal?.aborted || generation !== requestGeneration) {
        throw new DOMException('Cancelled', 'AbortError');
      }
      const value = {stores: storesFrom(payload), checkedAt: new Date().toISOString(),
        attribution: {text: '© OpenStreetMap contributors · Directory coverage may be incomplete. Games and hobby shops may not carry Pokémon.', url: 'https://www.openstreetmap.org/copyright'}};
      dropCache();
      cached = {key, at: Date.now(), value};
      // Clear location-derived data even when the user does not search again.
      cacheTimer = setTimeout(dropCache, cacheMs);
      return value;
    } finally {
      clearTimeout(timer); signal?.removeEventListener('abort', abort); activeRequests.delete(controller);
    }
  }
  window.PokeWatchNearby?.setProvider({search,
    privacyNotice: 'Your approximate location is sent to the OpenStreetMap Overpass directory to find stores. Directory requests are cached in this tab for up to one hour.',
    clear() {
      dropCache(); generation += 1;
      for (const controller of activeRequests) controller.abort();
      activeRequests.clear();
      // Keep nextRequestAt: forgetting a location must not bypass the cooldown.
    },
  });
})();
