import copy
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urljoin, urlsplit

import bot
import build_pages


CHECK_TIME = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return CHECK_TIME.astimezone(tz) if tz else CHECK_TIME.replace(tzinfo=None)


def product(identifier="public:1", **changes):
    value = {
        "id": identifier,
        "source_id": "public",
        "store": "Public store",
        "title": "Pokemon Test Booster Bundle",
        "url": "https://example.com/products/" + identifier,
        "price_cents": 2694,
        "reference_cents": 2694,
        "reference_kind": "Manufacturer MSRP",
        "reference_url": "https://example.com/msrp",
        "currency": "USD",
        "availability": "InStock",
        "checked_at": CHECK_TIME.isoformat(),
        "stale": False,
        "qualifies": True,
    }
    value.update(changes)
    return value


def state_with(*products):
    return {
        "products": {item["id"]: item for item in products},
        "sources": {},
        "releases": {},
        "alerts": [],
        "references": {},
        "watches": [],
        "last_scan": CHECK_TIME.isoformat(),
    }


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.config = {"interval_seconds": 900, "sources": [{"id": "public", "kind": "shopify"}]}
        for module in (build_pages, bot):
            replacement = patch.object(module, "datetime", FixedDateTime)
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_private_state_is_not_published_and_input_is_unchanged(self):
        public = product(debug_notes="PRIVATE_PRODUCT_NOTES", last_alert_price=1234)
        manual = product("public:manual", reference_url="https://private.example/MANUAL_REFERENCE")
        limit = product("public:limit", reference_kind="My price limit", reference_url="https://private.example/PERSONAL_LIMIT")
        watch = product("watch:private", source_id="watch:private", title="Pokemon PRIVATE_WATCH Booster Bundle")
        state = state_with(public, manual, limit, watch)
        state["token"] = "PRIVATE_API_TOKEN"
        state["references"] = {manual["id"]: {"notes": "PRIVATE_MANUAL_REFERENCE"}}
        state["watches"] = [{"url": "https://private.example/PRIVATE_WATCH_URL"}]
        state["sources"] = {
            "public": {"name": "Public store", "url": "https://example.com", "status": "ok", "token": "PRIVATE_SOURCE_TOKEN"},
            "watch:private": {"name": "PRIVATE_SOURCE", "url": "https://private.example"},
        }
        state["alerts"] = [
            {"id": "public-alert", "kind": "deal", "title": public["title"], "url": public["url"], "price_cents": 2694, "notes": "PRIVATE_ALERT_NOTES"},
            {"id": "PRIVATE_MANUAL_ALERT", "kind": "deal", "title": manual["title"], "url": manual["url"]},
            {"id": "PRIVATE_LIMIT_ALERT", "kind": "deal", "title": limit["title"], "url": limit["url"], "reference_kind": "My price limit"},
            {"id": "PRIVATE_WATCH_ALERT", "kind": "deal", "title": watch["title"], "url": watch["url"]},
        ]
        before = copy.deepcopy(state)

        result = build_pages.public_snapshot(state, self.config)

        self.assertEqual(state, before)
        self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertNotIn("private.example", json.dumps(result))
        self.assertEqual(set(result["products"]), {public["id"], manual["id"], limit["id"]})
        self.assertEqual(set(result["sources"]), {"public"})
        self.assertEqual([alert["id"] for alert in result["alerts"]], ["public-alert"])
        self.assertTrue(result["products"][public["id"]]["qualifies"])
        for item in (manual, limit):
            exported = result["products"][item["id"]]
            self.assertFalse(exported["qualifies"])
            for key in ("reference_cents", "reference_kind", "reference_url"):
                self.assertIsNone(exported[key])
        for key in ("token", "references", "watches"):
            self.assertNotIn(key, result)
        self.assertNotIn("last_alert_price", result["products"][public["id"]])

    def test_unconfigured_sources_and_nonsealed_products_are_excluded(self):
        accepted = product()
        removed_source = product("removed:1", source_id="removed")
        japanese = product("public:japanese", title="Pokemon Japanese Booster Box")
        toy = product("public:toy", title="Pokemon Dream Painting Figurine Blind Box")
        result = build_pages.public_snapshot(state_with(accepted, removed_source, japanese, toy), self.config)
        self.assertEqual(list(result["products"]), [accepted["id"]])

    def test_private_alert_cannot_publish_through_a_shared_public_product_url(self):
        public = product()
        cases = (
            product("watch:private", source_id="watch:private", url=public["url"]),
            product("public:manual", url=public["url"]),
        )
        for private in cases:
            with self.subTest(private_id=private["id"]):
                state = state_with(public, private)
                state["references"][private["id"]] = {"cents": 12345, "kind": "Manufacturer MSRP"}
                state["alerts"] = [{
                    "id": "PRIVATE_SHARED_URL_ALERT",
                    "kind": "deal",
                    "title": private["title"],
                    "url": private["url"],
                    "price_cents": 2694,
                    "reference_cents": 12345,
                    "reference_kind": "Manufacturer MSRP",
                }]
                result = build_pages.public_snapshot(state, self.config)
                self.assertEqual(result["alerts"], [])

    def test_releases_and_release_alerts_require_a_configured_release_source(self):
        state = state_with()
        release = {"id": "release:1", "title": "New official expansion", "url": "https://www.pokemon.com/us/pokemon-tcg/product-gallery/new", "first_seen": CHECK_TIME.isoformat(), "notes": "PRIVATE_RELEASE_NOTES"}
        state["releases"] = {release["id"]: release}
        state["alerts"] = [
            {"id": "announcement", "kind": "release", "title": release["title"], "url": release["url"]},
            {"id": "unlisted", "kind": "release", "url": "https://private.example/announcement"},
        ]
        without_feed = build_pages.public_snapshot(state, self.config)
        self.assertEqual(without_feed["releases"], {})
        self.assertEqual(without_feed["alerts"], [])

        self.config["sources"].append({"id": "official", "kind": "releases"})
        with_feed = build_pages.public_snapshot(state, self.config)
        self.assertEqual(list(with_feed["releases"]), [release["id"]])
        self.assertEqual([alert["id"] for alert in with_feed["alerts"]], ["announcement"])
        self.assertNotIn("PRIVATE_RELEASE_NOTES", json.dumps(with_feed))

    def test_expired_future_missing_and_invalid_checks_never_qualify(self):
        cases = {
            "expired": (CHECK_TIME - timedelta(seconds=1801)).isoformat(),
            "future": (CHECK_TIME + timedelta(seconds=1)).isoformat(),
            "invalid": "not a date",
            "null": None,
            "naive": "2026-10-05T12:00:00",
            "missing": None,
        }
        for label, checked_at in cases.items():
            with self.subTest(label=label):
                item = product(checked_at=checked_at)
                if label == "missing":
                    del item["checked_at"]
                result = build_pages.public_snapshot(state_with(item), self.config)["products"][item["id"]]
                self.assertTrue(result["stale"])
                self.assertFalse(result["qualifies"])

    def test_explicit_stale_or_unverified_seller_cannot_become_a_match(self):
        for changes in ({"stale": True}, {"seller_verified": False}, {"availability": "OutOfStock"}, {"error": "read failed"}):
            with self.subTest(changes=changes):
                item = product(**changes)
                result = build_pages.public_snapshot(state_with(item), self.config)
                self.assertFalse(result["products"][item["id"]]["qualifies"])

    def test_freshness_uses_configured_interval_with_a_five_minute_minimum(self):
        for interval, age, expected in ((900, 1800, True), (900, 1801, False), (300, 600, True), (300, 601, False), (10, 599, True)):
            with self.subTest(interval=interval, age=age):
                self.config["interval_seconds"] = interval
                item = product(checked_at=(CHECK_TIME - timedelta(seconds=age)).isoformat())
                result = build_pages.public_snapshot(state_with(item), self.config)
                self.assertEqual(result["products"][item["id"]]["qualifies"], expected)
                self.assertEqual(result["interval_seconds"], max(300, interval))


class DocumentLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        attribute = "href" if tag in ("a", "link") else "src" if tag in ("script", "img") else None
        if attribute and values.get(attribute):
            self.links.append(values[attribute])


class SiteOutputTests(unittest.TestCase):
    def test_existing_unrelated_files_are_refused_before_any_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            index = output / "index.html"
            index.write_text("Existing page", encoding="utf-8")
            private = output / "private-notes.txt"
            private.write_text("Do not publish", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unrelated file"):
                build_pages.write_site({"mode": "pages"}, output)

            self.assertEqual(index.read_text(encoding="utf-8"), "Existing page")
            self.assertEqual(private.read_text(encoding="utf-8"), "Do not publish")
            self.assertEqual({path.name for path in output.iterdir()}, {"index.html", "private-notes.txt"})

    def test_output_subdirectory_is_refused_even_with_an_asset_name(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "app.js").mkdir()
            with self.assertRaisesRegex(ValueError, "unrelated file"):
                build_pages.write_site({}, output)
            self.assertFalse((output / "state.json").exists())

    def test_exported_assets_resolve_inside_github_project_path(self):
        snapshot = {"mode": "pages", "products": {}, "releases": {}, "sources": {}, "alerts": []}
        base = "https://jjwhite224.github.io/pokewatch/"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            build_pages.write_site(snapshot, output)
            self.assertEqual(json.loads((output / "state.json").read_text(encoding="utf-8")), snapshot)
            self.assertTrue((output / ".nojekyll").is_file())

            document = DocumentLinks()
            document.feed((output / "index.html").read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(document.links), 5)
            for href in document.links:
                with self.subTest(href=href):
                    resolved = urlsplit(urljoin(base, href))
                    self.assertEqual(resolved.netloc, "jjwhite224.github.io")
                    self.assertTrue(resolved.path.startswith("/pokewatch/"), resolved.path)
                    relative = resolved.path.removeprefix("/pokewatch/") or "index.html"
                    self.assertTrue((output / relative).is_file(), relative)

            hosting = (output / "hosting.js").read_text(encoding="utf-8")
            self.assertRegex(hosting, r'mode:\s*[\"\x27]pages[\"\x27]')
            state_url = re.search(r'stateUrl:\s*[\"\x27]([^\"\x27]+)', hosting)
            self.assertIsNotNone(state_url)
            self.assertEqual(urljoin(base, state_url.group(1)), base + "state.json")


if __name__ == "__main__":
    unittest.main()
