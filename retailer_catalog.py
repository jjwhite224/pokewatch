"""Public retailer catalog discovery; catalog visibility never proves stock."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit


_DG_ORIGIN = "https://www.dollargeneral.com"
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def _product_url(value):
    try:
        parsed = urlsplit(urljoin(_DG_ORIGIN, value or ""))
        match = re.fullmatch(r"/p/[a-zA-Z0-9-]+/([0-9]+)", parsed.path)
        if (parsed.scheme != "https" or parsed.hostname != "www.dollargeneral.com"
                or parsed.username or parsed.password or parsed.port not in (None, 443) or not match):
            return None
        return urlunsplit(("https", "www.dollargeneral.com", parsed.path, "", "")), match.group(1)
    except ValueError:
        return None


def _image_url(value):
    try:
        parsed = urlsplit(value or "")
        if (parsed.scheme == "https" and parsed.hostname in {"s7d1.scene7.com", "dggo.dollargeneral.com"}
                and not parsed.username and not parsed.password and parsed.port in (None, 443)
                and parsed.path and not parsed.path.endswith("/")):
            return urlunsplit(("https", parsed.hostname, parsed.path, parsed.query, ""))
    except ValueError:
        pass
    return None


def _cents(text):
    if not re.fullmatch(r"\$[0-9]+(?:\.[0-9]{1,2})?", text):
        return None
    try:
        value = Decimal(text[1:]) * 100
        return int(value) if value > 0 else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


class _CatalogCards(HTMLParser):
    """Read only title/current-price elements within each product-card div.

    Dollar General's saved HTML nests title anchors within a navigation anchor.
    Using div depth avoids relying on the browser's repair of invalid anchors.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.card = None
        self.div_depth = 0
        self.title_depth = 0
        self.price_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag == "div" and "product-card" in classes:
            # A malformed unclosed card must not absorb a later card's price.
            self.card = {"title": [], "price": [], "urls": [], "image": None, "price_count": 0}
            self.div_depth = 1
            self.title_depth = self.price_depth = 0
            return
        if self.card is None:
            return
        if tag == "div":
            self.div_depth += 1
        if self.title_depth and tag not in _VOID_TAGS:
            self.title_depth += 1
        if self.price_depth and tag not in _VOID_TAGS:
            self.price_depth += 1
        if tag == "a" and "product--title" in classes:
            self.card["urls"].append(attrs.get("href", ""))
            self.title_depth = 1
        if tag == "span" and "product-card__current-price" in classes:
            self.card["price_count"] += 1
            self.price_depth = 1
        if tag == "img" and "product--image" in classes:
            self.card["image"] = _image_url(attrs.get("src"))

    def handle_endtag(self, tag):
        if self.card is None or tag in _VOID_TAGS:
            return
        if self.title_depth:
            self.title_depth -= 1
        if self.price_depth:
            self.price_depth -= 1
        if tag == "div":
            self.div_depth -= 1
            if self.div_depth == 0:
                self.cards.append(self.card)
                self.card = None
                self.title_depth = self.price_depth = 0

    def handle_data(self, data):
        if self.card is not None:
            if self.title_depth:
                self.card["title"].append(data)
            if self.price_depth:
                self.card["price"].append(data)


def dollar_general_products(body, source, title_filter):
    """Return standard bot products from DG's public category HTML.

    Current prices are catalog prices with no selected-store guarantee. All
    availability stays Unknown regardless of buttons, labels, or page JSON-LD.
    MSRP/reference fields remain empty; retail prices are not MSRP evidence.
    Raise ValueError for unreadable/empty catalogs so stale data is not success.
    """
    if not isinstance(body, str):
        raise ValueError("Dollar General returned unreadable catalog data.")
    parser = _CatalogCards()
    parser.feed(body)
    products = {}
    for card in parser.cards:
        title = " ".join(" ".join(card["title"]).split())
        if len(card["urls"]) != 1 or not title_filter(title):
            continue
        product_link = _product_url(card["urls"][0])
        if product_link is None:
            continue
        url, product_id = product_link
        source_id = source.get("id", "dollargeneral")
        pid = f"{source_id}:{product_id}"
        if pid in products:
            continue
        products[pid] = {
            "id": pid, "source_id": source_id, "store": source.get("name", "Dollar General"),
            "title": title, "url": url, "image": card["image"],
            "price_cents": _cents("".join(card["price"]).strip()) if card["price_count"] == 1 else None,
            "currency": "USD", "availability": "Unknown", "listed_at": None,
            "seller": "Dollar General", "seller_verified": True,
            "reference_cents": None, "reference_kind": None, "reference_url": None,
        }
    if not products:
        raise ValueError("No readable Pokémon catalog products; page format or assortment changed.")
    return list(products.values())
