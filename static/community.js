'use strict';
(() => {
  // These filters were verified on Restockd's public page. They select a chain,
  // never an individual store or a radius around the user's location.
  const retailers = Object.freeze({
    target: {name: 'Target', slug: 'target'},
    walmart: {name: 'Walmart', slug: 'walmart'},
    bestbuy: {name: 'Best Buy', slug: 'best-buy'},
    cvs: {name: 'CVS', slug: 'cvs'},
    dollargeneral: {name: 'Dollar General', slug: 'dollar-general'},
    costco: {name: 'Costco', slug: 'costco'},
  });
  const base = 'https://restockd.app/pokemon-in-store';
  function retailerLink(chain) {
    const key = typeof chain === 'string' ? chain.toLowerCase().replace(/[^a-z]/g, '') : '';
    if (!Object.hasOwn(retailers, key)) return null;
    const retailer = retailers[key];
    return {name: retailer.name, url: `${base}?retailer=${retailer.slug}`};
  }
  window.PokeWatchCommunity = Object.freeze({retailerLink});
  const select = document.getElementById('community-retailer');
  const link = document.getElementById('community-open');
  if (!select || !link) return;
  select.addEventListener('change', () => {
    const retailer = retailerLink(select.value);
    link.href = retailer?.url || base;
    link.textContent = retailer ? `Open ${retailer.name} sightings ↗` : 'Open public sightings ↗';
  });
})();
