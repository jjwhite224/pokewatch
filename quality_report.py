"""Deterministic PokéWatch snapshot quality audit. No network access required."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BUYABLE = {"InStock", "PreOrder", "PreSale", "LimitedAvailability"}


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def audit(snapshot, *, at=None):
    """Summarize quality; never infer unavailable stock from missing data."""
    if not isinstance(snapshot, dict):
        raise ValueError("Snapshot must be a JSON object")
    for field in ("products", "sources"):
        if not isinstance(snapshot.get(field), dict):
            raise ValueError(f"Snapshot {field} must be an object")
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        raise ValueError("Audit time must have a timezone")
    interval = snapshot.get("interval_seconds", 900)
    if type(interval) not in (int, float) or not 300 <= interval <= 86400:
        interval = 900
    counts = Counter()
    issues = []
    products = snapshot["products"]
    for key, product in products.items():
        if not isinstance(product, dict):
            issues.append({"severity": "error", "type": "invalid_product", "id": str(key)})
            continue
        counts["products"] += 1
        age = parse_time(product.get("checked_at"))
        stale = bool(product.get("stale")) or age is None or not 0 <= (at - age).total_seconds() <= 2 * interval
        if stale:
            counts["stale"] += 1
        if product.get("availability") in BUYABLE and not stale:
            counts["fresh_buyable_signal"] += 1
        else:
            counts["not_confirmed_buyable"] += 1
        if product.get("availability") in (None, "Unknown"):
            counts["unknown_stock"] += 1
        if product.get("seller_verified") is False:
            counts["unverified_seller"] += 1
        if product.get("reference_cents") is None:
            counts["missing_reference"] += 1
        price = product.get("price_cents")
        if price is not None and (type(price) is not int or price <= 0):
            issues.append({"severity": "error", "type": "invalid_price", "id": str(key)})
        if product.get("qualifies") and (stale or product.get("availability") not in BUYABLE or product.get("seller_verified") is False or price is None or not product.get("reference_cents")):
            issues.append({"severity": "error", "type": "unsafe_qualifying_claim", "id": str(key)})
        elif product.get("qualifies"):
            counts["claimed_matches"] += 1
    for key, source in snapshot["sources"].items():
        if not isinstance(source, dict):
            issues.append({"severity": "error", "type": "invalid_source", "id": str(key)})
            continue
        status = source.get("status", "unknown")
        counts[f"source_{status}"] += 1
        if status != "manual":
            age = parse_time(source.get("checked_at"))
            if age is None or not 0 <= (at-age).total_seconds() <= 2 * interval:
                counts["stale_sources"] += 1
    return {"generated_at": at.isoformat(), "totals": dict(sorted(counts.items())),
            "issues": issues, "issue_count": len(issues),
            "note": "Audit evaluates supplied snapshots only; it does not confirm live retailer inventory."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Local state.json or published snapshot")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    report = audit(json.loads(args.snapshot.read_text(encoding="utf-8")))
    result = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    else:
        print(result)
    raise SystemExit(1 if report["issue_count"] else 0)


if __name__ == "__main__":
    main()
