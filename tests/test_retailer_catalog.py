import unittest

import bot
from retailer_catalog import dollar_general_products


# Trimmed structurally faithful card from data/probes/dg-oct8.txt, lines 3823–3852.
CARD = '''<div class="product-card">
<a class="product-card__navigation" href="/p/pokemon-30th-celebration-poster-collection-with-cards/196214157385">
<div class="product-card__image-container"><img class="product--image" src="https://s7d1.scene7.com/is/image/dolgen/dg-44433901-1" alt="Pokemon 30th Celebration Poster Collection with Cards" loading="lazy"/></div>
<div class="product-card__add-button-wrapper"><button aria-label="Add to Cart" type="button" class="product--add-button"><span class="global-icon plus-black icon-addToCart"></span></button></div>
<div class="product-card__details"><div class="product--info"><div class="product--info-price-section">
<span class="product-price product-card__current-price">$16.00</span>
</div></div><div class="product-details-info">
<a class="product--title " style="text-decoration: none;" href="/p/pokemon-30th-celebration-poster-collection-with-cards/196214157385">Pokemon 30th Celebration Poster Collection with Cards</a>
</div><div class="product--availability"></div></div></a></div>'''
SOURCE = {"id": "dollargeneral", "name": "Dollar General"}


class DollarGeneralCatalogTests(unittest.TestCase):
    def parse(self, body=CARD):
        return dollar_general_products(body, SOURCE, bot.sealed_english)

    def test_real_card_extracts_associated_catalog_price_and_identity(self):
        item, = self.parse()
        self.assertEqual(item["id"], "dollargeneral:196214157385")
        self.assertEqual(item["price_cents"], 1600)
        self.assertEqual(item["availability"], "Unknown")
        self.assertEqual(item["currency"], "USD")
        self.assertEqual(item["url"], "https://www.dollargeneral.com/p/pokemon-30th-celebration-poster-collection-with-cards/196214157385")
        self.assertIsNone(item["reference_cents"])

    def test_stock_labels_and_buttons_cannot_establish_shipping_stock(self):
        body = CARD.replace('class="product--availability">', 'class="product--availability">In stock. Pickup available.')
        body += '<script type="application/ld+json">{"availability":"https://schema.org/InStock"}</script>'
        self.assertEqual(self.parse(body)[0]["availability"], "Unknown")

    def test_outside_price_and_regular_price_are_not_current_price_or_msrp(self):
        body = '<span class="product-card__current-price">$99.00</span>' + CARD.replace('product-card__current-price', 'product-card__regular-price')
        item, = self.parse(body)
        self.assertIsNone(item["price_cents"])
        self.assertIsNone(item["reference_cents"])

    def test_multiple_current_prices_are_ambiguous(self):
        body = CARD.replace('$16.00</span>', '$16.00</span><span class="product-card__current-price">$12.00</span>')
        self.assertIsNone(self.parse(body)[0]["price_cents"])

    def test_duplicate_card_is_deduplicated(self):
        self.assertEqual(len(self.parse(CARD + CARD)), 1)

    def test_unsafe_product_url_and_unreadable_catalog_raise(self):
        for body in ('<html>Challenge</html>', CARD.replace('href="/p/', 'href="https://bad.example/p/')):
            with self.subTest(body=body[:60]), self.assertRaises(ValueError):
                self.parse(body)

    def test_toys_are_excluded_and_unsafe_images_removed(self):
        toy = CARD.replace('Pokemon 30th Celebration Poster Collection with Cards', 'Pokemon Pikachu Plush')
        with self.assertRaises(ValueError):
            self.parse(toy)
        self.assertIsNone(self.parse(CARD.replace('https://s7d1.scene7.com/', 'https://bad.example/'))[0]["image"])

    def test_html_entities_and_nested_title_markup_are_preserved(self):
        body = CARD.replace('Pokemon 30th Celebration Poster Collection with Cards</a>', 'Pokémon <strong>Scarlet &amp; Violet</strong> Booster Pack</a>')
        self.assertEqual(self.parse(body)[0]["title"], 'Pokémon Scarlet & Violet Booster Pack')


if __name__ == '__main__':
    unittest.main()
