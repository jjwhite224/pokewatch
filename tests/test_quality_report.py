"""Offline quality-audit regression tests."""
import unittest
from datetime import datetime, timezone
from quality_report import audit

AT = datetime(2026, 10, 8, 20, 0, tzinfo=timezone.utc)

def record(**changes):
    p = {"checked_at": AT.isoformat(), "availability": "InStock",
         "price_cents": 2499, "reference_cents": 2694,
         "seller_verified": True, "qualifies": True}
    p.update(changes)
    return p

class QualityAuditTests(unittest.TestCase):
    def check(self, products, sources=None):
        return audit({"products": products, "sources": sources or {}, "interval_seconds": 900}, at=AT)

    def test_clean_qualifying_offer(self):
        r = self.check({"one": record()})
        self.assertEqual(r["issue_count"], 0)
        self.assertEqual(r["totals"]["claimed_matches"], 1)

    def test_stale_qualifying_offer_is_flagged(self):
        r = self.check({"one": record(stale=True)})
        self.assertEqual(r["issues"][0]["type"], "unsafe_qualifying_claim")

    def test_unknown_stock_is_not_sellable(self):
        r = self.check({"one": record(availability="Unknown", qualifies=False)})
        self.assertEqual(r["issue_count"], 0)
        self.assertEqual(r["totals"]["unknown_stock"], 1)

    def test_unverified_seller_with_alert_is_flagged(self):
        r = self.check({"one": record(seller_verified=False)})
        self.assertEqual(r["issues"][0]["type"], "unsafe_qualifying_claim")

    def test_missing_price_and_reference(self):
        r = self.check({"one": record(price_cents=None, reference_cents=None, qualifies=False)})
        self.assertEqual(r["totals"]["missing_reference"], 1)
        self.assertEqual(r["issue_count"], 0)

    def test_invalid_price_is_flagged(self):
        r = self.check({"one": record(price_cents=-10, qualifies=False)})
        self.assertEqual(r["issues"][0]["type"], "invalid_price")

    def test_future_timestamp_is_stale(self):
        r = self.check({"one": record(checked_at="2099-01-01T00:00:00+00:00", qualifies=False)})
        self.assertEqual(r["totals"]["stale"], 1)

    def test_manual_source_not_counted_stale(self):
        r = self.check({}, {"cvs": {"status": "manual"}})
        self.assertEqual(r["totals"].get("stale_sources", 0), 0)

    def test_rejects_malformed_snapshots(self):
        with self.assertRaises(ValueError):
            audit({"products": [], "sources": {}})

if __name__ == "__main__":
    unittest.main()
