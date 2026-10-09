---
name: pokewatch-retailer-reliability
description: Audit PokéWatch retailer readers, product normalization, source status, seller verification, MSRP provenance, and alert accuracy; use for new sources or fixes to parsing and stock logic.
---

# Retailer reliability and data auditing

## Read first
Read `AGENTS.md`, `README.md`, `config.json`, `price-catalog.json`, and only the affected sections of `bot.py`, `retailer_api.py`, `retailer_catalog.py`, and `tests/`.

## Procedure
1. Identify the exact source, public interface, pagination cap, timestamp, and what its fields *prove*. Document scope before changing behavior.
2. Separate product discovery, price, seller identity, online availability, branch-specific availability, and documented reference prices.
3. Validate required fields, malformed prices, non-finite numbers, duplicate IDs, unsafe URLs, currencies, timestamps, and partial page reads.
4. Verify exact variants: set, pack count, language, edition, bundle/case quantity, and Pokémon Center exclusivity. Do not fuzzy-match prices across variants.
5. Label blocked, stale, missing, ambiguous, and rate-limited data as unknown/partial as appropriate. Never convert source failure to out-of-stock.
6. Require verified seller and an evidence-backed exact-product reference before a qualifying price alert. Crossed-out list price is not automatically MSRP.
7. Use captured synthetic or permitted fixtures in tests. Make no live retailer requests during unit testing.
8. Propose the smallest patch; run relevant tests and review regressions.

## Required edge cases
- HTTP error, CAPTCHA, zero readable products, HTML shape changes, pagination cap, duplicates.
- Seller absent, marketplace offer, preorder, unavailable online but local pickup indicated.
- ETB vs Pokémon Center ETB, bundle vs case, non-US editions.
- Old successful scan followed by blocked scan; unchanged qualifying listing should not repeat an alert.
- Missing price, mismatched reference, and unknown stock.

## Report
Include severity, file/function, observed or simulated evidence, user impact, recommended fix, tests run, and remaining uncertainty. Explicitly distinguish verified observations from assumptions.
