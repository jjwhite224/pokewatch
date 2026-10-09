---
name: pokewatch-regression-testing
description: Create and run deterministic Python and JavaScript tests for PokéWatch scanners, parsers, alerts, hosted exports, nearby stores, and UI behavior when implementation changes.
---

# Testing and regression protection

## Read first
Read `AGENTS.md`, `README.md`, changed files, and existing `tests/test_bot.py`, `tests/test_pages.py`, `tests/test_retailer_api.py`, `tests/test_retailer_catalog.py`, and `tests/*.test.cjs` as appropriate.

## Test method
1. State the expected invariant before writing tests.
2. Reproduce bugs with the smallest synthetic fixture. Stub network, clock, browser or filesystem boundaries; never depend on live retailer uptime.
3. Cover happy, malformed, absent, stale, unauthorized, partial, and repeated-event cases.
4. Test normalization and exact variant matching independently from alerts, then integration paths when needed.
5. Confirm public snapshots exclude private watch lists, limits, coordinates, tokens, and raw diagnostics.
6. Confirm hosted read-only controls cannot mutate local state; nearby results never imply confirmed inventory.
7. Keep fixtures minimal, deterministic, and free of keys, personal data, or captured third-party content without permission.
8. Run checks and report exact command output and failures; don't alter product logic merely to make a test pass.

## Baseline
```sh
python -m unittest discover -s tests -v
node --check static/app.js
node --test tests/*.test.cjs
```

## Output
Test case / invariant / fixture / result / file modified. Distinguish executed tests from recommended manual tests.
