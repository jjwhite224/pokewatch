# PokéWatch reliability and dashboard overhaul

This iteration applies all five development skills in `.agents/skills/`.

## Delivered
- **Retailer reliability:** `quality_report.py` audits saved state offline. It identifies stale checks, unknown availability, unverified sellers, missing reference prices, malformed prices, and potentially unsafe qualified-price flags. It never contacts retailers or asserts real-time stock.
- **UX:** The dashboard displays four explicit confidence counts: fresh checks, unknown stock, unverified sellers, and expired checks. A separate scan-freshness message explains what the tracker knows.
- **Price intelligence:** The quality report exposes data-readiness metrics for future price-history work. No historical price series or fabricated chart is introduced.
- **Testing:** `tests/test_quality_report.py` includes deterministic stock/freshness/seller/price tests with fixed UTC time and no network requests.
- **Security/privacy:** Audit output is local-only and no new public JSON fields, credentials, exact location, third-party requests, or user settings are published.

## Use the offline data-quality report
Run in the repository directory after you have a local scan:
```sh
python quality_report.py data/state.json
python quality_report.py data/state.json --output quality-summary.json
```
An exit code of 1 means at least one flagged issue. Counts can be nonzero without signaling a software defect (e.g., unknown stock is expected when a retailer does not disclose it). The output is a diagnostic and must not be interpreted as proof of live inventory.

To audit a downloaded GitHub Pages snapshot, supply that saved JSON file as the positional argument.

## Verify before merging
```sh
python -m unittest discover -s tests -v
node --check static/app.js
node --test tests/*.test.cjs
```
Manually inspect desktop and mobile widths, keyboard navigation, and the local/hosted dashboard. The Python checker is otherwise unchanged.

## Next work
- Investigate actual error/partial sources with reproducible permitted fixtures before modifying adapters.
- Design bounded price-history storage, retention, and source provenance, then add genuine historical charts.
- Expand frontend tests for new confidence metrics after browser DOM fixtures are available.
- Conduct accessibility and privacy review with actual browser/device tooling.
