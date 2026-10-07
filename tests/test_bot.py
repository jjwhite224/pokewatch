import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import bot


def product(**changes):
    p = {"id": "test:1", "source_id": "test", "store": "Test store", "title": "Pokemon Test Booster Bundle", "url": "https://example.com/test", "price_cents": 2694, "reference_cents": 2694, "reference_kind": "Manufacturer MSRP", "reference_url": "https://example.com/reference", "currency": "USD", "availability": "InStock", "checked_at": bot.now()}
    p.update(changes)
    return p


def product_html(offer=None, extra=""):
    value = {"@context": "https://schema.org", "@type": "Product", "name": "Pokemon Test Booster Bundle", "sku": "TEST", "offers": offer or {"@type": "Offer", "price": "26.94", "priceCurrency": "USD", "availability": "https://schema.org/InStock"}}
    return '<script type="application/ld+json">' + json.dumps(value) + '</script>' + extra


class PriceTests(unittest.TestCase):
    def test_cents_and_invalid_numbers(self):
        self.assertEqual(bot.cents("$26.94"), 2694)
        for value in [None, "NaN", "Infinity", "-1", "0", "free"]:
            self.assertIsNone(bot.cents(value))

    def test_eligibility_boundaries(self):
        self.assertTrue(bot.eligible(product()))
        self.assertTrue(bot.eligible(product(price_cents=2499, availability="PreOrder")))
        for changes in [{"price_cents": 2695}, {"currency": "CAD"}, {"availability": "OutOfStock"}, {"availability": "Unknown"}, {"reference_cents": None}, {"reference_url": None}, {"stale": True}, {"seller_verified": False}, {"checked_at": "2020-01-01T00:00:00+00:00"}, {"checked_at": "bad"}]:
            self.assertFalse(bot.eligible(product(**changes)), changes)

    def test_unrelated_msrp_is_not_used(self):
        body = product_html(extra='<aside>Related product MSRP: $199.99</aside>')
        parsed = bot.product_page(body, "https://www.gamenerdz.com/test", "gamenerdz", "Game Nerdz")
        self.assertIsNone(parsed["reference_cents"])

    def test_explicit_rrp_field(self):
        body = product_html(extra='<span data-product-rrp-price-without-tax class="price price--rrp">$26.94</span>')
        parsed = bot.product_page(body, "https://www.gamenerdz.com/test", "gamenerdz", "Game Nerdz")
        self.assertEqual(parsed["reference_cents"], 2694)
        self.assertEqual(parsed["reference_kind"], "Retailer-reported MSRP")

    def test_empty_rrp_does_not_fall_through_to_related_price(self):
        body = product_html(extra='<span data-product-rrp-price-without-tax></span><div>MSRP: $99.99</div>')
        self.assertIsNone(bot.product_page(body, "https://www.gamenerdz.com/test", "gamenerdz", "Game Nerdz")["reference_cents"])

    def test_multi_offer_rejected(self):
        with self.assertRaisesRegex(ValueError, "Multiple or aggregated"):
            bot.product_page(product_html({"@type": "AggregateOffer", "lowPrice": 1}), "https://example.com", "watch", "Store")

    def test_best_buy_in_store_only_overrides_schema_stock(self):
        parsed=bot.product_page(product_html(extra='<button>In Store Only</button>'), 'https://www.bestbuy.com/product/test/123', 'bestbuy', 'Best Buy')
        self.assertEqual(parsed['availability'], 'InStoreOnly')

    def test_shopify_variants_no_compare_at_msrp(self):
        source = {"id": "store", "name": "Store", "url": "https://example.com/products.json"}
        item = {"title": "Pokémon Booster Bundle", "handle": "bundle", "variants": [{"id": 1, "title": "Default Title", "price": "26.94", "compare_at_price": "99.99", "available": True}, {"id": 2, "title": "Case of 6", "price": "129.99", "available": False}]}
        japanese = {**item, "title": "Pokémon Booster Box (J)"}
        rows, count = bot.shopify_products(json.dumps({"products": [item, japanese]}), source)
        self.assertEqual(count, 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], "store:1")
        self.assertIsNone(rows[0]["reference_cents"])
        self.assertEqual(rows[1]["availability"], "OutOfStock")
        self.assertIn("Case of 6", rows[1]["title"])

    def test_official_links_only_and_deduplicated(self):
        body = '<a href="/us/pokemon-tcg/product-gallery/test">Test</a><a href="/us/pokemon-tcg/product-gallery/test">Test</a><a href="https://bad.example/us/pokemon-tcg/product-gallery/fake">Fake</a>'
        self.assertEqual(len(bot.releases(body, "https://www.pokemon.com")), 1)

    def test_exact_reference_keys_preserve_edition_and_quantity(self):
        expected = bot.reference_key("Pokemon TCG Mega Evolution Pitch Black Booster Bundle")
        self.assertEqual(bot.reference_key("Pokémon TCG: Mega Evolution: Pitch Black - Booster Bundle (Limit 2) — New"), expected)
        self.assertNotEqual(bot.reference_key("Pokemon TCG Mega Evolution Pitch Black Booster Bundle Case"), expected)
        self.assertNotEqual(bot.reference_key("Pokemon TCG Mega Evolution Pitch Black Pokemon Center Booster Bundle"), expected)

    def test_catalog_filter_rejects_collectible_toys_and_open_products(self):
        for title in ["Pokemon Dream Painting Figurine Blind Box", "Pokemon Booster Box (J)", "Pokemon Unsealed Elite Trainer Box", "Pokemon Collection Sleeves", "Pokemon Japanese Booster Bundle", "Pokemon Primers: Pokemon Types Box Set Collection Volume 3", "Pokemon Epic Sticker Collection From Kanto to Paldea"]:
            self.assertFalse(bot.sealed_english(title), title)
        self.assertTrue(bot.sealed_english("Pokemon Mega Lucario ex Figure Collection"))

    def test_storepass_uses_retail_price_not_buyback_offer(self):
        p = {"display_name": "Pokemon Test Booster Bundle", "url": "https://www.gamenerdz.com/pokemon-test", "active": True, "isVisible": True, "stock": 4, "availability": "available", "price": 49.99, "current_price": 10, "offer_price": 10, "msrp": 26.94, "currency": "USD", "variant_info": [{"id": 100, "purchasing_disabled": False, "option_values": []}]}
        rows,pages = bot.storepass_products(json.dumps({"products": [p], "pages": 2}), {"id": "gamenerdz", "name": "Game Nerdz"})
        self.assertEqual(rows[0]["price_cents"], 4999)
        self.assertEqual(rows[0]["reference_cents"], 2694)
        self.assertEqual(rows[0]["availability"], "InStock")
        self.assertEqual(pages, 1)

    def test_walmart_marketplace_is_visible_but_cannot_alert(self):
        p={"name": "Pokemon Booster Bundle", "sellerName": "Reseller", "sellerId": "seller1", "usItemId": "123", "priceInfo": {"linePrice": "$26.94"}, "canonicalUrl": "/ip/test/123?tracking=yes", "availabilityStatus": "IN_STOCK", "showAtc": True}
        body='<script id="__NEXT_DATA__" type="application/json">'+json.dumps({"items":[p]})+'</script>'
        rows=bot.walmart_products(body,{"id":"walmart","name":"Walmart"})
        self.assertFalse(rows[0]["seller_verified"])
        self.assertEqual(rows[0]["url"],"https://www.walmart.com/ip/test/123")
        p["sellerName"]="Walmart.com"
        body='<script id="__NEXT_DATA__">'+json.dumps({"items":[p]})+'</script>'
        self.assertTrue(bot.walmart_products(body,{"id":"walmart","name":"Walmart"})[0]["seller_verified"])


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.tracker = bot.Tracker({"interval_seconds": 900, "sources": []}, self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def apply(self, **changes):
        self.tracker.apply_product(product(**changes), bot.now())

    def test_duplicate_suppression_and_price_drop(self):
        self.apply()
        self.apply()
        self.assertEqual(len(self.tracker.state["alerts"]), 1)
        self.apply(price_cents=2499)
        self.assertEqual(len(self.tracker.state["alerts"]), 2)

    def test_restock_alert(self):
        self.apply()
        self.apply(availability="OutOfStock")
        self.apply()
        self.assertEqual(len(self.tracker.state["alerts"]), 2)

    def test_failure_recovery_not_a_restock(self):
        self.apply()
        self.tracker.state["products"]["test:1"]["stale"] = True
        self.apply()
        self.assertEqual(len(self.tracker.state["alerts"]), 1)

    def test_restart_requires_live_refresh_and_keeps_dedup(self):
        self.apply()
        self.tracker.save()
        restarted = bot.Tracker(self.tracker.config, self.temp.name)
        self.assertFalse(restarted.snapshot()["products"]["test:1"]["qualifies"])
        restarted.apply_product(product(), bot.now())
        self.assertEqual(len(restarted.state["alerts"]), 1)

    def test_snapshot_ages_out(self):
        self.apply()
        self.tracker.state["products"]["test:1"]["checked_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertFalse(self.tracker.snapshot()["products"]["test:1"]["qualifies"])

    def test_initial_release_baseline_then_only_new_alerts(self):
        source = {"id": "official", "kind": "releases", "name": "Official", "url": "https://www.pokemon.com/us/pokemon-tcg/product-gallery"}
        body = '<a href="/us/pokemon-tcg/product-gallery/one">First</a>'
        self.tracker.fetcher = lambda _: body
        self.tracker.run_source(source)
        self.assertEqual(self.tracker.state["alerts"], [])
        body += '<a href="/us/pokemon-tcg/product-gallery/two">Second</a>'
        self.tracker.run_source(source)
        self.tracker.run_source(source)
        self.assertEqual(len(self.tracker.state["alerts"]), 1)

    def test_reference_is_exact_variant(self):
        self.apply(reference_cents=None, reference_url=None)
        self.tracker.set_reference({"product_id": "test:1", "price": "26.94", "kind": "Manufacturer MSRP", "url": "https://example.com/reference"})
        self.apply(reference_cents=None, reference_url=None)
        self.apply(id="test:2", reference_cents=None, reference_url=None)
        self.assertTrue(self.tracker.snapshot()["products"]["test:1"]["qualifies"])
        self.assertFalse(self.tracker.snapshot()["products"]["test:2"]["qualifies"])

    def test_partial_failure_retains_but_marks_old_rows(self):
        self.apply()
        def fail(_):
            raise ValueError("blocked")
        self.tracker.fetcher = fail
        self.tracker.run_source({"id": "test", "name": "Store", "kind": "shopify", "url": "https://example.com/products.json"})
        self.assertEqual(self.tracker.state["sources"]["test"]["status"], "error")
        self.assertFalse(self.tracker.snapshot()["products"]["test:1"]["qualifies"])

    def test_reference_validation(self):
        self.apply()
        with self.assertRaises(ValueError):
            self.tracker.set_reference({"product_id": "test:1", "price": "NaN", "kind": "Manufacturer MSRP", "url": "https://example.com"})


if __name__ == "__main__":
    unittest.main()
