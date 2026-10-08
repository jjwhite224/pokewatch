import json
import traceback
import unittest
import urllib.error
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import bot
import retailer_api


def api_product(sku=6678359, **changes):
    value = {
        "sku": sku, "name": "Pokemon Pitch Black Booster Bundle", "salePrice": 26.94,
        "regularPrice": 79.99, "onlineAvailability": True, "inStoreAvailability": True,
        "url": f"https://api.bestbuy.com/click/-/{sku}/pdp",
        "image": "https://pisces.bbystatic.com/image2/BestBuy_US/images/products/test.jpg",
        "startDate": "2026-09-04", "active": True,
    }
    value.update(changes)
    return value


def page(*products, **changes):
    value = {"products": list(products), "currentPage": 1, "totalPages": 1, "partial": False}
    value.update(changes)
    return value


class BestBuyCatalogTests(unittest.TestCase):
    def setUp(self):
        replacement = patch.object(retailer_api.time, "sleep")
        replacement.start()
        self.addCleanup(replacement.stop)

    def fetch(self, payload, **kwargs):
        return retailer_api.fetch_bestbuy_catalog(
            title_filter=bot.sealed_english, api_key="fixture-key-only",
            fetcher=Mock(return_value=payload), **kwargs,
        )

    def test_uses_current_sale_price_without_inventing_msrp_or_seller(self):
        products, partial, message = self.fetch(page(api_product()))
        self.assertFalse(partial)
        self.assertEqual(len(products), 1)
        item = products[0]
        self.assertEqual(item["id"], "bestbuy:6678359")
        self.assertEqual(item["price_cents"], 2694)
        self.assertEqual(item["availability"], "InStock")
        self.assertEqual(item["currency"], "USD")
        self.assertFalse(item["seller_verified"])
        for key in ("reference_cents", "reference_kind", "reference_url"):
            self.assertIsNone(item[key])
        self.assertIn("seller", message)

    def test_in_store_or_pickup_flags_never_establish_online_stock(self):
        for online, expected in ((True, "InStock"), (False, "OutOfStock"), (None, "Unknown"), ("true", "Unknown"), (1, "Unknown")):
            with self.subTest(online=online):
                products, _, _ = self.fetch(page(api_product(onlineAvailability=online, inStoreAvailability=True, inStorePickup=True)))
                self.assertEqual(products[0]["availability"], expected)

    def test_unknown_or_invalid_sale_price_does_not_fall_back_to_regular_price(self):
        for price in (None, True, "NaN", "Infinity", 0, -1, "free"):
            with self.subTest(price=price):
                products, _, _ = self.fetch(page(api_product(salePrice=price)))
                self.assertIsNone(products[0]["price_cents"])
                self.assertIsNone(products[0]["reference_cents"])

    def test_root_filter_excludes_toys_foreign_language_and_inactive_products(self):
        products, _, _ = self.fetch(page(
            api_product(1), api_product(2, name="Pokemon Japanese Booster Bundle"),
            api_product(3, name="Pokemon Plush"), api_product(4, active=False),
            api_product(5, name="Pokemon Epic Sticker Collection"),
        ))
        self.assertEqual([item["id"] for item in products], ["bestbuy:1"])

    def test_product_links_require_https_correct_host_and_matching_sku(self):
        invalid = (
            "http://www.bestbuy.com/product/test/6678359",
            "https://www.bestbuy.com.evil.example/product/test/6678359",
            "https://www.bestbuy.com@evil.example/product/test/6678359",
            "https://name:password@www.bestbuy.com/product/test/6678359",
            "https://www.bestbuy.com:444/product/test/6678359",
            "https://api.bestbuy.com/v1/products/6678359.json?apiKey=private",
            "https://api.bestbuy.com/click/-/999999/pdp",
            "https://www.bestbuy.com/site/test/6678359.p?skuId=999999",
            "https://www.bestbuy.com/redirect?url=https://evil.example",
        )
        for url in invalid:
            with self.subTest(url=url):
                products, _, _ = self.fetch(page(api_product(url=url)))
                self.assertEqual(products, [])

    def test_only_normalized_fields_and_safe_product_links_leave_adapter(self):
        raw = api_product(url="https://www.bestbuy.com/site/test/6678359.p?skuId=6678359&apiKey=PRIVATE#PRIVATE", apiKey="PRIVATE", seller="Best Buy", marketplace=False)
        payload = page(raw, canonicalUrl="https://api.bestbuy.com/v1/products?apiKey=PRIVATE")
        products, _, _ = self.fetch(json.dumps(payload))
        self.assertEqual(products[0]["url"], "https://www.bestbuy.com/site/test/6678359.p?skuId=6678359")
        self.assertNotIn("PRIVATE", json.dumps(products))
        # Undocumented fields cannot silently promote an unverified offer.
        self.assertFalse(products[0]["seller_verified"])

    def test_missing_key_makes_no_request(self):
        fetcher = Mock()
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(retailer_api.BestBuyAPIError, "BESTBUY_API_KEY"):
                retailer_api.fetch_bestbuy_catalog(title_filter=bot.sealed_english, fetcher=fetcher)
        fetcher.assert_not_called()

    def test_environment_key_is_used_only_in_fixed_official_requests(self):
        fetcher = Mock(return_value=page(api_product()))
        with patch.dict("os.environ", {"BESTBUY_API_KEY": "fixture-not-a-real-key"}):
            result = retailer_api.fetch_bestbuy_catalog(title_filter=bot.sealed_english, fetcher=fetcher)
        url = fetcher.call_args.args[0]
        self.assertEqual(urlsplit(url).hostname, "api.bestbuy.com")
        self.assertIn("search=pokemon&active=true", urlsplit(url).path)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["apiKey"], ["fixture-not-a-real-key"])
        self.assertEqual(query["pageSize"], ["100"])
        self.assertNotIn("fixture-not-a-real-key", json.dumps(result))

    def test_first_page_errors_do_not_expose_secret_urls_or_response_bodies(self):
        private_key = "PRIVATE"
        for error in (
            urllib.error.HTTPError("https://api.bestbuy.com/?apiKey=PRIVATE", 403, "PRIVATE", {}, None),
            urllib.error.URLError("https://api.bestbuy.com/?apiKey=PRIVATE"),
            ValueError("PRIVATE invalid response body"),
        ):
            with self.subTest(error_type=type(error).__name__):
                try:
                    retailer_api.fetch_bestbuy_catalog(title_filter=bot.sealed_english, api_key=private_key, fetcher=Mock(side_effect=error))
                except retailer_api.BestBuyAPIError as safe:
                    self.assertNotIn("PRIVATE", str(safe))
                    self.assertNotIn("PRIVATE", "".join(traceback.format_exception(safe)))
                else:
                    self.fail("Expected a sanitized API error")

    def test_two_page_limit_retains_two_hundred_items_and_reports_partial(self):
        responses = [page(*(api_product(sku) for sku in range(1, 101)), totalPages=3),
                     page(*(api_product(sku) for sku in range(101, 201)), currentPage=2, totalPages=3)]
        fetcher = Mock(side_effect=responses)
        products, partial, message = retailer_api.fetch_bestbuy_catalog(title_filter=bot.sealed_english, api_key="fixture", fetcher=fetcher, max_pages=999)
        self.assertEqual(len(products), 200)
        self.assertEqual(fetcher.call_count, 2)
        self.assertTrue(partial)
        self.assertIn("capped", message)
        self.assertEqual([parse_qs(urlsplit(call.args[0]).query)["page"] for call in fetcher.call_args_list], [["1"], ["2"]])

    def test_later_failure_keeps_prior_page_and_reports_sanitized_partial(self):
        fetcher = Mock(side_effect=[page(api_product(), totalPages=2), RuntimeError("PRIVATE URL")])
        products, partial, message = retailer_api.fetch_bestbuy_catalog(title_filter=bot.sealed_english, api_key="PRIVATE", fetcher=fetcher)
        self.assertEqual(len(products), 1)
        self.assertTrue(partial)
        self.assertIn("Page 2", message)
        self.assertNotIn("PRIVATE", message)

    def test_incomplete_pagination_and_upstream_partial_are_not_reported_complete(self):
        for payload in (page(api_product(), partial=True), {"products": [api_product()]}):
            with self.subTest(payload=payload):
                products, partial, _ = self.fetch(payload)
                self.assertEqual(len(products), 1)
                self.assertTrue(partial)

    def test_duplicate_skus_are_deduplicated_and_invalid_collections_fail_safely(self):
        products, _, _ = self.fetch(page(api_product(), api_product()))
        self.assertEqual(len(products), 1)
        for payload in ({"errors": "PRIVATE"}, [], "not JSON PRIVATE"):
            with self.subTest(payload=payload):
                with self.assertRaises(retailer_api.BestBuyAPIError) as raised:
                    self.fetch(payload)
                self.assertNotIn("PRIVATE", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
