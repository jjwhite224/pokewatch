# PokéWatch — repository guidance for coding agents

PokéWatch is a Python 3.11+ Pokémon TCG release, retailer-price, and stock-signal tracker. It uses Python standard-library code, a static JavaScript/CSS dashboard, GitHub Actions and GitHub Pages, and optional local Windows notifications.

## Operating principles
- Read `README.md`, relevant implementation files, and existing tests before editing.
- Use the applicable skill in `.agents/skills/` for specialized work. Skills are development instructions, **not runtime features**.
- Treat retailer data as fallible. Unknown, blocked, stale, partial, or unverified never means in stock or sold out.
- Online availability is not local store inventory. Catalog appearance is not stock evidence.
- Keep manufacturer MSRP, retailer-reported MSRP, official store price, and personal price limits distinct. Never fabricate MSRP, discounts, seller verification, stock, or release dates.
- Match exact product variants: edition, language, set, bundle quantity, and pack count. Do not silently conflate a case, ETB, Pokémon Center ETB, booster bundle, or single pack.
- Keep local personal watches, private price references, precise location, credentials, and tokens out of hosted public snapshots.
- Never bypass retailer CAPTCHAs, paywalls, queues, or access controls. Respect API terms and rate limits; use documented/authorized interfaces.
- Make narrowly scoped changes; keep Python standard-library-only unless a new dependency is justified and documented.
- Do not run parallel checkers against the same data directory; do not trigger live retailer scans in automated tests.
- Never claim a scan, test, security finding, or UX evaluation occurred unless it actually did.

## Architecture map
- `bot.py`: scanner, normalization, matching, alerts, local server and persistence.
- `retailer_api.py`, `retailer_catalog.py`: retailer-specific adapters.
- `config.json`, `price-catalog.json`: sources and evidence-backed price references.
- `build_pages.py`: allowlisted, read-only public export.
- `static/`: dashboard, location finder, and community links.
- `.github/workflows/pages.yml`: scheduled scan, tests, and site deployment.
- `tests/`: Python and Node regression tests.
- `data/` and `_site/`: generated/local outputs; do not commit private state.

## Verification commands
```sh
python -m unittest discover -s tests -v
node --check static/app.js
node --test tests/*.test.cjs
```
If a tool is unavailable, say so; never describe an unrun check as passing.

## Completion standard
Explain changed paths, supported evidence, limitations, and exact test commands/results. Review security/privacy before modifying cloud export, external URLs, API handling, or location logic. Avoid unrelated refactors.

## Skills
- `pokewatch-retailer-reliability`: source trust, parsing, product variants, status.
- `pokewatch-ux-design`: hierarchy, responsive UI, accessibility.
- `pokewatch-price-intelligence`: historical metrics, evidence, charts.
- `pokewatch-regression-testing`: deterministic test design.
- `pokewatch-security-privacy`: credentials, public export, URL/location safety.

Skill format: each folder contains a `SKILL.md` with YAML `name` and `description` followed by instructions. Invoke a skill by its name when your coding environment supports it, or explicitly ask the agent to follow its `SKILL.md`.
