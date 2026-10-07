# PokéWatch

A local US Pokémon TCG release and retail-price tracker, with a dashboard and Windows desktop notifications. Requires Python 3.11 or later. There are no Python packages to install.

## GitHub Pages

The project also includes a read-only hosted dashboard at [jjwhite224.github.io/pokewatch](https://jjwhite224.github.io/pokewatch/). Source code and deployment status are in [jjwhite224/pokewatch](https://github.com/jjwhite224/pokewatch). The website is available after its first successful Pages deployment.

GitHub Pages serves the website files; **GitHub Actions runs the Python store checker separately**. The included `.github/workflows/pages.yml` requests a scan at minutes 7, 22, 37, and 52 of each hour, then publishes the latest results. Your PC can be off. GitHub can delay or skip scheduled jobs, and public-repository schedules are disabled after 60 days without repository activity. This is a periodic tracker, not a guaranteed instant restock alert service. See [GitHub Pages hosting](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) and [scheduled workflow limits](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

Moving the site does not repair store readers or guarantee access to blocked stores. The first cloud scan will establish which sources GitHub can reach. Stock expires after two polling intervals, including in an already-open browser. Source failures remain visible rather than being presented as sold-out inventory.

The hosted dashboard supports search, filters, links, and alert history. **Refresh data** reloads the published results; it does not trigger a new store scan. Change shared sources and exact price references in `config.json` and `price-catalog.json`. The local app still supports interactive product watches, personal limits, and Windows desktop notifications. Those local settings and notifications do not automatically transfer to Pages.

To deploy:

1. Create or open `jjwhite224/pokewatch` on GitHub. Put only this application's source files at the repository root. Use `main` as the default branch for the included workflow.
2. In repository **Settings → Pages → Build and deployment**, select **GitHub Actions** as the source.
3. Upload/push the reviewed source files, including the hidden `.github/workflows/pages.yml` and `.gitignore`. Do not upload `data/`, `_site/`, `__pycache__/`, or logs. Saving files to GitHub creates a version in project history.
4. Open **Actions → Update and publish PokéWatch → Run workflow**, if the initial push did not start it. Check that both build and deploy succeed, then open the website URL shown by the deployment.

The workflow only publishes `_site/`: the dashboard assets and an allowlisted public snapshot. It does not publish the local server token, private watch list, manually entered references, raw store responses, or logs. Cloud scan state is kept in the Actions cache so alert history can survive between runs; cache eviction can reset that history. No code commits are created by scheduled scans.

Preview the hosted layout from the last saved local scan without contacting stores:

```powershell
python build_pages.py --data-dir data --output _site
python -m http.server 8766 --bind 127.0.0.1 --directory _site
```

Then visit `http://127.0.0.1:8766/`. For a separate fresh cloud-style scan, run `python build_pages.py --scan`; it uses the isolated `data/pages/` directory. It never shares a state writer with the running local bot.

## Start and stop

Double-click **Start PokeWatch.cmd**, then visit **http://127.0.0.1:8765/**. The launcher starts the checker and a Windows tray icon in the background. The bot checks every 15 minutes and continues when you close the browser. Your PC must remain awake and connected. It does not automatically start after a reboot; run the launcher again.

Double-click **Stop PokeWatch.cmd** to stop this bot and its notifier. Saved products, price references, and alerts are retained. Right-click the tray icon for **Test desktop notification**. Windows notification settings can suppress the pop-up; the dashboard always keeps the alert history.

## What it tracks

- Newly discovered announcements on Pokémon's official product gallery. The first scan establishes a baseline without announcing every old product.
- Store catalog listings with separate price and stock status for each variant. An initial catalog may include older products; a newly listed item is not necessarily a new Pokémon release.
- Products available at or below an exact recorded price reference, including explicit preorders. Alerts fire when a product first qualifies, restocks, or gets cheaper. An unchanged qualifying listing does not send repeated alerts.
- Specific product URLs added using **Watch a product**, when the page publishes a single readable product offer. Marketplace watches require a seller name that matches the page's data.

**A reference is required.** MSRP means manufacturer's suggested retail price. The app distinguishes manufacturer MSRP, retailer-reported MSRP, the official store's price, and a personal price limit. A store's crossed-out or “compare at” price is never assumed to be MSRP. Current product-specific references and their evidence links live in `price-catalog.json`; additional references can be entered in the dashboard. Exact title aliases preserve edition, pack count, and quantity—no approximate title matching is used for prices.

Prices exclude shipping and tax. A stock indicator is the retailer's public online signal, not a checkout guarantee or a local-store inventory check. No purchases are made.

## Source coverage and failures

Configured on October 4, 2026:

- **Smoke & Mirrors Hobby:** public Pokémon catalog, up to four 250-product pages.
- **Game Nerdz:** its storefront's public Storepass catalog, up to three 100-product pages, Pokémon query, newest first. Uses the explicit `msrp` field. Retail selling price is separate from the store's buyback offer.
- **Zulu's Games:** Pokémon collection, up to two pages.
- **Josh's Cards:** Pokémon catalog, up to four pages; individual cards and non-card merchandise are filtered out.
- **Walmart:** featured trading-card catalog. Sellers are displayed. Automatic price alerts require Walmart or Walmart.com as seller; third-party offers remain visible for comparison.
- **Best Buy:** one seeded Pitch Black Booster Bundle product watch (SKU 6678359), requiring Best Buy as seller. This is not whole-store coverage. In-store-only items do not generate online-stock alerts.
- **Target, GameStop, and Pokémon Center:** attempted public-page readers. Live checks encountered browser-only data, blocking, or connection issues. They are not reliable live inventory sources until a successful read is reported.
- **Pokémon official announcements:** initially imported 56 product pages; later checks intermittently returned a bot challenge. Saved announcements are retained and source failures are visible.

Major-store automatic discovery is limited; these connections are not a claim of complete US retailer coverage. Add specific product watches where supported. No accounts, paid feeds, or API keys are required by the sources that work today.

`config.json` controls the sources, local port, and interval. Each source appears in **Source health** with its last check and any limitation. The code reads public catalogs and product metadata; it does not solve CAPTCHAs, bypass queues, sign into accounts, or use private credentials. A blocked source or unreadable seller is **unknown**, never “sold out.”

Shopify feeds are paginated with an explicit configured cap. A partial status means the cap was reached or some requests failed. Previously seen products that are no longer in the scanned pages become stale. Add an exact product URL watch if you want to keep following an older product independently of a catalog's newest page.

All saved stock is treated as stale on restart until rechecked. Data also expires after two polling intervals. The first edition is US/USD and filters out explicitly labeled foreign-language catalog products.

## Files and privacy

- `bot.py`: public-source readers, matching, saved state, local server.
- `static/`: local dashboard.
- `build_pages.py`: public-only snapshot export and hosted dashboard build.
- `.github/workflows/pages.yml`: scheduled cloud scans, tests, and Pages deployment.
- `config.json`: source selection and polling interval (minimum five minutes).
- `price-catalog.json`: documented exact-product reference prices.
- `data/state.json`: products, user references, individual watches, alert history.
- `data/bot-errors.log`: diagnostic messages from the running checker.
- `notify.ps1`: Windows tray notifications; `data/notification-seen.json` remembers delivered alerts.
- `tests/test_bot.py`: matching, variant safety, freshness, persistence, and alert checks.
- `tests/test_pages.py` and `tests/frontend.test.cjs`: export privacy, asset paths, and hosted/local behavior.

The local server listens only on your own computer (`127.0.0.1`). The bot contacts configured public retailer sources; product images load from retailer image servers when you open the dashboard. No external alert service is configured.

## Commands

Run from this folder:

```powershell
# Start the background checker and desktop alerts
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1

# Run in a terminal; Ctrl+C stops it (do not run alongside the background copy)
python bot.py

# One live scan, then exit (stop the background copy first)
python bot.py --once

# Run automated checks without contacting stores
python -m unittest discover -s tests -v
node --check static/app.js
node --test tests/frontend.test.cjs

# Stop the managed checker and desktop alerts
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\stop.ps1
```

Only one checker should write a given data directory. Use `--data-dir PATH --port PORT` for a separate test instance. If the default port is in use, set another port in `config.json` and restart using the launcher.
