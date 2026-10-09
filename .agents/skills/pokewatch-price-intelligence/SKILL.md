---
name: pokewatch-price-intelligence
description: Design and validate PokéWatch historical price tracking, retailer comparisons, discount metrics, and evidence-backed data visualizations, carefully handling missing or stale prices.
---

# Pokémon price intelligence

## Scope
This skill guides design and implementation; it does **not** assert that historical price analytics already exist. Read `AGENTS.md`, `README.md`, `price-catalog.json`, `bot.py`, `build_pages.py`, and relevant tests.

## Workflow
1. Define one narrowly scoped question (e.g., price change for the same verified SKU across seven days).
2. Establish product identity and comparable unit: same language, edition, pack count, seller scope, currency, and listed quantity.
3. Record provenance: source, exact URL/product ID, retrieval time in UTC, price in integer cents, stock signal, seller verification, and reference kind/source.
4. Audit missingness, source interruptions, duplicate snapshots, outliers, and sparse observations before charting.
5. Define aggregation explicitly. Never average across non-equivalent variants; separate price movement from restock signals. Do not interpolate blocked scans as observed prices.
6. Design efficient retention: bounded observations, deduplication of identical timestamps, clear persistence location, and a plan for cloud cache eviction or missing scan intervals.
7. Compute discounts only against a valid exact-product reference, label the reference type, and clarify that shipping/tax are excluded.
8. Present charts with visible timestamps, axis units, source attribution, missing-data gaps, and a plain-language limitation note.
9. Test sample datasets containing gaps, duplicates, stale readings, same-name variants, changed sellers, and unknown references.
10. Review public export allowlists and data volume before publication.

## Deliverables
A proposed data schema, metric definitions, data-quality summary, acceptance tests, mock visualization using **clearly labeled synthetic data** if live history is unavailable, and an implementation plan. Do not fabricate actual trends, savings, stock, or MSRP.
