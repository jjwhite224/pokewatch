"""Local Pokémon release and MSRP tracker. Python 3.11+, standard library only."""
from __future__ import annotations

import argparse
import copy
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import ssl
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("pokewatch")
USER_AGENT = "PokeWatch/1.0 (personal release and retail-price monitor)"
MAX_BODY = 6_000_000
BUYABLE = {"InStock", "PreOrder", "PreSale", "LimitedAvailability"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cents(value):
    try:
        amount = Decimal(str(value).replace("$", "").replace(",", "").strip())
        if not amount.is_finite() or amount <= 0:
            return None
        return int((amount * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError, TypeError):
        return None


def norm(text):
    text = unicodedata.normalize("NFKD", html.unescape(str(text)))
    return " ".join(re.findall(r"[a-z0-9]+", text.encode("ascii", "ignore").decode().lower()))


def reference_key(title):
    title = re.sub(r"\(Limit\s+\d+\)", "", title, flags=re.I)
    title = re.sub(r"\s*[—–-]\s*New$", "", title, flags=re.I)
    return norm(title)


def sealed_english(title):
    value = norm(title)
    if "pokemon" not in value:
        return False
    if re.search(r"\((?:J|JP|KR|CN)\)", title, re.I) or any(word in value.split() for word in ("japanese", "japan", "korean", "chinese", "german", "french", "italian", "spanish", "unsealed", "empty", "sleeves", "figurine", "plush", "primers", "primer", "book", "books", "manga", "coloring", "puzzle", "puzzles")):
        return False
    if "epic sticker" in value:
        return False
    if re.search(r"\b(?:booster|trainer box|tin|battle deck|theme deck|blister|build battle|build and battle|ex box|v box|toolkit|collector chest)\b", value):
        return True
    return "collection" in value and ("tcg" in value.split() or "trading card game" in value or bool(re.search(r"\b(?:premium|figure|illustration|binder|poster|tech sticker|pin|knock out|knockout) collection\b", value)))


def walk_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)


def next_data(body):
    match = re.search(r'<script\b[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', body, re.S)
    if not match:
        raise ValueError("Page did not include readable catalog data.")
    return json.loads(match.group(1))


def storepass_products(body, source):
    payload = json.loads(body)
    if not isinstance(payload.get("products"), list):
        raise ValueError("Game Nerdz catalog format changed.")
    result = []
    for p in payload["products"]:
        title = html.unescape(p.get("display_name") or p.get("name", ""))
        if not sealed_english(title) or p.get("active") is False or p.get("isVisible") is False:
            continue
        variants = p.get("variant_info", [])
        if len(variants) != 1 or variants[0].get("option_values"):
            continue  # Do not mix variant-level quantities, prices or MSRP.
        variant = variants[0]
        url = p.get("url", "")
        if urllib.parse.urlsplit(url).hostname != "www.gamenerdz.com":
            continue
        stock = p.get("stock")
        available = p.get("availability") == "available" and variant.get("purchasing_disabled") is False
        status = "InStock" if available and isinstance(stock, (int, float)) and stock > 0 else "OutOfStock" if stock == 0 or not available else "Unknown"
        if p.get("availability") == "preorder" and variant.get("purchasing_disabled") is False:
            status = "PreOrder"
        reference = cents(p.get("msrp"))
        result.append({"id": f"{source['id']}:{variant['id']}", "source_id": source["id"], "store": source["name"],
                       "title": title, "url": url, "image": p.get("image_url"), "price_cents": cents(p.get("price")),
                       "currency": p.get("currency", ""), "availability": status,
                       "listed_at": p.get("createdAt"), "sku": variant.get("sku", ""),
                       "reference_cents": reference, "reference_kind": "Retailer-reported MSRP" if reference else None,
                       "reference_url": url if reference else None})
    return result, len(payload["products"])


def walmart_products(body, source):
    result = {}
    for p in walk_objects(next_data(body)):
        if not all(k in p for k in ("sellerName", "priceInfo", "canonicalUrl", "availabilityStatus")):
            continue
        title = html.unescape(p.get("name", ""))
        if not sealed_english(title):
            continue
        url = urllib.parse.urljoin("https://www.walmart.com", p["canonicalUrl"]).split("?")[0]
        if urllib.parse.urlsplit(url).hostname != "www.walmart.com":
            continue
        seller = p.get("sellerName") or "Unknown seller"
        stock = p.get("availabilityStatus")
        status = "InStock" if stock == "IN_STOCK" and p.get("showAtc") is True else "OutOfStock" if stock == "OUT_OF_STOCK" else "Unknown"
        if status == "InStock" and (p.get("preOrder") or {}).get("isPreOrder") is True:
            status = "PreOrder"
        pid = f"{source['id']}:{p.get('usItemId') or p.get('id')}:{p.get('sellerId') or seller}"
        result[pid] = {"id": pid, "source_id": source["id"], "store": source["name"], "title": title, "url": url,
                       "image": (p.get("imageInfo") or {}).get("thumbnailUrl"), "price_cents": cents(p["priceInfo"].get("linePrice")),
                       "currency": "USD", "availability": status, "seller": seller,
                       "seller_verified": norm(seller) in {"walmart", "walmart com"},
                       "listed_at": None, "reference_cents": None, "reference_kind": None, "reference_url": None}
    if not result:
        raise ValueError("No readable Pokémon catalog offers; page format or assortment changed.")
    return list(result.values())


def safe_url(value):
    """Reject nonpublic HTTP targets, including redirects to private addresses."""
    p = urllib.parse.urlsplit(str(value))
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError("Use a public HTTPS product or reference URL.")
    if p.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise ValueError("Local network URLs are not supported.")
    addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private network URLs are not supported.")
    return value


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    safe_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html"})
    try:
        with urllib.request.build_opener(PublicRedirect()).open(req, timeout=20) as response:
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise ValueError("Source response is too large.")
            body = raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429, 503):
            raise ValueError(f"Store blocked or rate-limited the request (HTTP {exc.code}); will retry later.") from exc
        raise ValueError(f"Source returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise ValueError("Secure connection could not be validated; automatic stock checks are unavailable.") from exc
        raise ValueError("Store connection failed; will retry on the next scheduled check.") from exc
    except TimeoutError as exc:
        raise ValueError("Store did not respond in time; will retry on the next scheduled check.") from exc
    if len(body) < 40_000 and any(s in body.lower() for s in (
        "pardon our interruption", "incapsula incident", "verify you are human", "just a moment...", "captcha")):
        raise ValueError("Store returned a bot-check page; price and stock are unknown.")
    return body


class Page(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.links, self.scripts, self.texts = [], [], []
        self.anchor = None
        self.script = None
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.anchor = {"href": a["href"], "title": a.get("title", ""), "text": ""}
        if tag == "img" and self.anchor and a.get("alt"):
            self.anchor["text"] += " " + a["alt"]
        if tag == "script":
            self.script = {"type": a.get("type", ""), "text": ""}

    def handle_data(self, data):
        if self.script is not None:
            self.script["text"] += data
        else:
            self.texts.append(data)
            if self.anchor:
                self.anchor["text"] += " " + data

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor:
            self.links.append(self.anchor)
            self.anchor = None
        if tag == "script" and self.script is not None:
            self.scripts.append(self.script)
            self.script = None

    def structured(self):
        result = []
        def walk(value):
            if isinstance(value, list):
                for child in value:
                    walk(child)
            elif isinstance(value, dict):
                result.append(value)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        walk(child)
        for script in self.scripts:
            if "ld+json" in script["type"]:
                try:
                    walk(json.loads(script["text"]))
                except json.JSONDecodeError:
                    pass
        return result


def releases(body, base):
    items = {}
    for a in Page(body).links:
        url = urllib.parse.urljoin(base, a["href"]).split("#")[0].rstrip("/")
        if "/pokemon-tcg/product-gallery/" not in url or not url.startswith("https://www.pokemon.com/"):
            continue
        title = " ".join((a["title"] or a["text"]).split())
        if title and (url not in items or len(title) > len(items[url]["title"])):
            items[url] = {"id": url, "title": title, "url": url}
    if not items:
        raise ValueError("Official gallery layout changed or returned no product links.")
    return list(items.values())


def shopify_products(body, source):
    payload = json.loads(body)
    if not isinstance(payload.get("products"), list):
        raise ValueError("Catalog response did not contain a product list.")
    origin = "https://" + urllib.parse.urlsplit(source["url"]).netloc
    result = []
    for product in payload["products"]:
        title = product.get("title", "")
        if not sealed_english(title):
            continue
        for variant in product.get("variants", []):
            variant_title = variant.get("title", "")
            full_title = title if variant_title in ("Default Title", "") else f"{title} — {variant_title}"
            image = (product.get("images") or [{}])[0].get("src")
            result.append({
                "id": f"{source['id']}:{variant['id']}", "source_id": source["id"],
                "store": source["name"], "title": full_title,
                "url": f"{origin}/products/{product['handle']}?variant={variant['id']}",
                "image": image, "price_cents": cents(variant.get("price")),
                "currency": "USD", "availability": "InStock" if variant.get("available") is True else "OutOfStock" if variant.get("available") is False else "Unknown",
                "listed_at": product.get("published_at"), "sku": variant.get("sku", ""),
                "reference_cents": None, "reference_kind": None, "reference_url": None,
            })
    return result, len(payload["products"])


def product_page(body, url, source_id, store, item_id=None):
    page = Page(body)
    products = [v for v in page.structured() if "Product" in ([v.get("@type")] if isinstance(v.get("@type"), str) else v.get("@type", []))]
    if not products:
        raise ValueError("No readable product data; this store may need a supported feed.")
    # Only a single primary Product is safe; recommendations can have different prices.
    if len(products) > 1:
        exact = [p for p in products if str(p.get("url", "")).rstrip("/") == url.split("?")[0].rstrip("/")]
        if len(exact) != 1:
            raise ValueError("Multiple products found; cannot safely select the requested product.")
        products = exact
    p = products[0]
    offers = p.get("offers", [])
    if isinstance(offers, dict):
        offers = [offers]
    if len(offers) != 1 or offers[0].get("@type") == "AggregateOffer":
        raise ValueError("Multiple or aggregated offers; price and seller need manual verification.")
    offer = offers[0]
    availability = str(offer.get("availability", "Unknown")).rsplit("/", 1)[-1]
    # Best Buy's general schema stock flag can include in-store-only merchandise.
    # Require online fulfillment rather than turning a local stock hint into a deal.
    if urllib.parse.urlsplit(url).hostname == "www.bestbuy.com":
        visible = " ".join(" ".join(page.texts).split())
        if re.search(r"\bin[ -]store only\b", visible, re.I):
            availability = "InStoreOnly"
    image = p.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    title = html.unescape(str(p.get("name", "Untitled product")))
    reference = None
    # Game Nerdz explicitly labels this amount MSRP. Never treat compare_at_price
    # or a crossed-out selling price from an arbitrary store as MSRP.
    if source_id == "gamenerdz":
        # BigCommerce's dedicated primary-product RRP field, not related items.
        match = re.search(r'<span\b[^>]*\bdata-product-rrp-price-without-tax(?:\s*=\s*[\"\'][^\"\']*[\"\'])?[^>]*>\s*\$\s*([\d,]+\.\d{2})\s*</span>', body, re.I)
        if match:
            reference = cents(match.group(1))
    seller = offer.get("seller")
    seller_name = seller.get("name", "") if isinstance(seller, dict) else str(seller or "")
    return {"id": item_id or f"{source_id}:{p.get('sku') or url}", "source_id": source_id, "store": store,
            "title": title, "url": url, "image": image, "price_cents": cents(offer.get("price")),
            "currency": str(offer.get("priceCurrency", "")).upper(), "availability": availability,
            "seller": seller_name, "sku": str(p.get("sku", "")), "listed_at": None,
            "reference_cents": reference, "reference_kind": "Retailer-reported MSRP" if reference else None,
            "reference_url": url if reference else None}


def gamenerdz_links(body, base, limit):
    page = Page(body)
    result = []
    for a in page.links:
        url = urllib.parse.urljoin(base, a["href"]).split("?")[0]
        slug = urllib.parse.urlsplit(url).path.strip("/")
        if urllib.parse.urlsplit(url).hostname != "www.gamenerdz.com" or "/" in slug:
            continue
        if "pokemon-" in slug and any(t in slug for t in ("booster", "trainer", "collection", "tin", "deck", "blister", "battle")):
            if not any(t in slug for t in ("japanese", "korean", "chinese")) and url not in result:
                result.append(url)
    if not result:
        raise ValueError("Store catalog layout changed; no product links found.")
    return result[:limit]


def eligible(item, max_age_seconds=1800):
    price, ref = item.get("price_cents"), item.get("reference_cents")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(item["checked_at"])).total_seconds()
    except (KeyError, ValueError, TypeError):
        return False
    return (item.get("currency") == "USD" and item.get("availability") in BUYABLE
            and isinstance(price, int) and isinstance(ref, int) and 0 < price <= ref
            and bool(item.get("reference_url")) and not item.get("error") and not item.get("stale")
            and item.get("seller_verified", True)
            and 0 <= age <= max_age_seconds)


class Tracker:
    def __init__(self, config, data_dir, fetcher=fetch):
        self.config, self.data_dir, self.fetcher = config, Path(data_dir), fetcher
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "state.json"
        self.lock, self.scan_lock, self.stop = threading.RLock(), threading.Lock(), threading.Event()
        self.scanning = False
        self.next_check = None
        self.token = secrets.token_urlsafe(32)
        catalog_path = ROOT / "price-catalog.json"
        self.price_catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else []
        self.state = {"products": {}, "releases": {}, "sources": {}, "alerts": [], "references": {}, "watches": [], "last_scan": None}
        if self.state_path.exists():
            # A corrupt file must be reported rather than silently lose references.
            self.state.update(json.loads(self.state_path.read_text(encoding="utf-8")))
        for item in self.state["products"].values():
            item["stale"] = True
        self.state["alerts"] = [a for a in self.state["alerts"] if a.get("kind") == "release" or sealed_english(a["title"])]
        self.seed()

    def seed(self):
        path = ROOT / "references.json"
        if path.exists():
            for ref in json.loads(path.read_text(encoding="utf-8")):
                self.state["references"].setdefault(ref["product_id"], ref)

    def save(self):
        with self.lock:
            temp = self.state_path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, self.state_path)

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.state)
        result.update(scanning=self.scanning, next_check=self.next_check, interval_seconds=self.config["interval_seconds"], token=self.token)
        result["products"] = {k: v for k, v in result["products"].items() if sealed_english(v["title"])}
        result["alerts"] = [a for a in result["alerts"] if a.get("kind") == "release" or sealed_english(a["title"])]
        for item in result["products"].values():
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(item["checked_at"])).total_seconds()
                item["stale"] = item.get("stale", False) or age > self.config["interval_seconds"] * 2
            except (KeyError, TypeError, ValueError):
                item["stale"] = True
            item["qualifies"] = eligible(item, self.config["interval_seconds"] * 2)
        return result

    def apply_product(self, item, stamp):
        with self.lock:
            old = self.state["products"].get(item["id"], {})
            item["first_seen"] = old.get("first_seen", stamp)
            item["checked_at"], item["stale"] = stamp, False
            ref = self.state["references"].get(item["id"])
            if not ref and not item.get("reference_cents"):
                key = reference_key(item["title"])
                ref = next((r for r in self.price_catalog if key in [reference_key(a) for a in r["exact_titles"]]), None)
            if ref:
                item.update(reference_cents=ref["cents"], reference_kind=ref["kind"], reference_url=ref["url"])
            qualifies = eligible(item)
            # Preserve last known eligibility across temporary network failures.
            prior = old.get("last_eligible", False)
            if qualifies and (not prior or item["price_cents"] < old.get("last_alert_price", 10**12)):
                alert = {"id": secrets.token_hex(10), "kind": "deal", "at": stamp,
                         "title": item["title"], "store": item["store"], "url": item["url"],
                         "price_cents": item["price_cents"], "reference_cents": item["reference_cents"], "reference_kind": item["reference_kind"]}
                self.state["alerts"].append(alert)
                item["last_alert_price"] = item["price_cents"]
                LOG.info("AT/BELOW REFERENCE: %s $%.2f %s", item["title"], item["price_cents"] / 100, item["url"])
            else:
                item["last_alert_price"] = old.get("last_alert_price")
            item["last_eligible"] = qualifies
            self.state["products"][item["id"]] = item

    def run_source(self, source):
        stamp, count, errors = now(), 0, []
        sid = source["id"]
        with self.lock:
            # Older rows remain visible, but never count as current matches.
            for item in self.state["products"].values():
                if item["source_id"] == sid:
                    item["stale"] = True
        try:
            body = self.fetcher(source["url"])
            if source["kind"] == "releases":
                found = releases(body, source["url"])
                with self.lock:
                    initial = not self.state["releases"]
                    for item in found:
                        if item["id"] not in self.state["releases"]:
                            item["first_seen"] = stamp
                            self.state["releases"][item["id"]] = item
                            if not initial:
                                self.state["alerts"].append({"id": secrets.token_hex(10), "kind": "release", "at": stamp, "title": item["title"], "url": item["url"]})
                    count = len(found)
            elif source["kind"] == "shopify":
                pages = max(1, min(8, int(source.get("pages", 4))))
                capped = False
                for page in range(1, pages + 1):
                    if page > 1:
                        time.sleep(1)
                        query = urllib.parse.parse_qs(urllib.parse.urlsplit(source["url"]).query)
                        query["page"] = [str(page)]
                        body = self.fetcher(urllib.parse.urlunsplit(urllib.parse.urlsplit(source["url"])._replace(query=urllib.parse.urlencode(query, doseq=True))))
                    items, raw_count = shopify_products(body, source)
                    for item in items:
                        self.apply_product(item, stamp)
                    count += len(items)
                    if raw_count < 250:
                        break
                    if page == pages:
                        capped = True
                if capped:
                    errors.append(f"Coverage limited to {pages * 250} catalog entries; older pages were not scanned.")
            elif source["kind"] == "gamenerdz":
                links = gamenerdz_links(body, source["url"], source.get("products_per_scan", 12))
                for url in links:
                    try:
                        time.sleep(1)
                        item = product_page(self.fetcher(url), url, sid, source["name"])
                        self.apply_product(item, stamp)
                        count += 1
                    except Exception as exc:
                        errors.append(str(exc))
                if not count:
                    raise ValueError(errors[0] if errors else "No readable products.")
            elif source["kind"] == "storepass":
                max_pages = max(1, min(5, int(source.get("pages", 3))))
                for number in range(1, max_pages + 1):
                    if number > 1:
                        time.sleep(1)
                        body = self.fetcher(re.sub(r"([?&])page=\d+", r"\g<1>page=" + str(number), source["url"]))
                    items, raw_count = storepass_products(body, source)
                    for item in items:
                        self.apply_product(item, stamp)
                    count += len(items)
                    if raw_count < 100:
                        break
                    if number == max_pages:
                        errors.append(f"Checked the newest {max_pages} catalog pages; older pages are outside this scan.")
                if not count:
                    raise ValueError("Catalog returned no matching sealed Pokémon products on the scanned pages.")
            elif source["kind"] == "walmart":
                items = walmart_products(body, source)
                for item in items:
                    self.apply_product(item, stamp)
                count = len(items)
                errors.append("Featured catalog only. Marketplace sellers are labeled and excluded from automatic deal alerts.")
            elif source["kind"] == "catalog_watch":
                links = []
                host = urllib.parse.urlsplit(source["url"]).hostname
                for anchor in Page(body).links:
                    url = urllib.parse.urljoin(source["url"], anchor["href"]).split("#")[0]
                    title = anchor["title"] or anchor["text"]
                    if source["product_pattern"] in url and urllib.parse.urlsplit(url).hostname == host and sealed_english(title) and url not in links:
                        links.append(url)
                if not links:
                    raise ValueError("Catalog requires browser-loaded data; automatic stock checks are unavailable.")
                for url in links[:source.get("products_per_scan", 8)]:
                    try:
                        time.sleep(1)
                        item = product_page(self.fetcher(url), url, sid, source["name"])
                        if source.get("seller") and norm(item.get("seller")) != norm(source["seller"]):
                            raise ValueError("The page did not confirm the required direct retailer seller.")
                        self.apply_product(item, stamp)
                        count += 1
                    except Exception as exc:
                        errors.append(str(exc))
                if not count:
                    raise ValueError(errors[0] if errors else "No readable product offers.")
            elif source["kind"] == "watch":
                item = product_page(body, source["url"], sid, source["name"], source["product_id"])
                # Marketplace offers require an explicitly recorded seller.
                host = urllib.parse.urlsplit(source["url"]).hostname or ""
                if any(host == domain or host.endswith("." + domain) for domain in ("amazon.com", "walmart.com", "bestbuy.com", "target.com")):
                    if not source.get("seller") or norm(item.get("seller")) != norm(source["seller"]):
                        raise ValueError("Marketplace seller was absent or did not match the seller specified for this watch.")
                self.apply_product(item, stamp)
                count = 1
            else:
                raise ValueError("Unsupported source type.")
            status = {"name": source["name"], "url": source["url"], "status": "partial" if errors else "ok", "checked_at": stamp, "count": count, "message": f"{len(errors)} issue(s): {errors[0]}" if errors else "Check completed"}
        except Exception as exc:
            LOG.warning("%s: %s", source["name"], exc)
            status = {"name": source["name"], "url": source["url"], "status": "error", "checked_at": stamp, "count": count, "message": str(exc)}
        with self.lock:
            status["url"] = source.get("display_url", status["url"])
            status["coverage"] = "One specific product" if source["kind"] == "watch" else "Catalog scan"
            self.state["sources"][sid] = status

    def scan(self):
        if not self.scan_lock.acquire(blocking=False):
            return False
        self.scanning = True
        try:
            with self.lock:
                sources = copy.deepcopy(self.config["sources"] + self.state["watches"])
            # One sequential request stream per source; no aggressive store polling.
            with ThreadPoolExecutor(max_workers=3) as pool:
                for result in as_completed([pool.submit(self.run_source, s) for s in sources]):
                    result.result()
            with self.lock:
                self.state["last_scan"] = now()
                self.state["alerts"] = self.state["alerts"][-500:]
                self.save()
            return True
        finally:
            self.scanning = False
            self.next_check = time.time() + self.config["interval_seconds"]
            self.scan_lock.release()

    def loop(self):
        while not self.stop.is_set():
            if self.next_check is None or time.time() >= self.next_check:
                try:
                    self.scan()
                except Exception:
                    LOG.exception("Scan failed; stored data was retained")
            self.stop.wait(1)

    def set_reference(self, data):
        amount = cents(data.get("price"))
        if amount is None or amount > 1_000_000:
            raise ValueError("Enter a positive reference price below $10,000.")
        url = str(data.get("url", ""))
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Add the HTTPS page documenting this exact product's reference price.")
        kind = data.get("kind")
        if kind not in {"Manufacturer MSRP", "Retailer-reported MSRP", "Distributor-reported MSRP", "Official store price", "My price limit"}:
            raise ValueError("Select a reference type.")
        with self.lock:
            pid = data["product_id"]
            if pid not in self.state["products"]:
                raise ValueError("Product no longer exists.")
            self.state["references"][pid] = {"product_id": pid, "cents": amount, "url": url, "kind": kind, "verified_at": now()}
            self.state["products"][pid].update(reference_cents=amount, reference_url=url, reference_kind=kind)
            self.save()

    def add_watch(self, data):
        url = str(data.get("url", "")).strip()
        safe_url(url)
        with self.lock:
            if len(self.state["watches"]) >= 30:
                raise ValueError("Limit is 30 individual watches.")
            if any(w["url"] == url for w in self.state["watches"]):
                raise ValueError("This URL is already being watched.")
            sid = "watch-" + secrets.token_hex(6)
            self.state["watches"].append({"id": sid, "kind": "watch", "product_id": sid, "name": urllib.parse.urlsplit(url).hostname, "url": url, "seller": str(data.get("seller", "")).strip()[:150]})
            self.save()


def make_handler(tracker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            LOG.debug(fmt, *args)

        def send(self, code, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' https: data:; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host", "") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, {"error": "Local access only"})
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/state":
                return self.send(200, tracker.snapshot())
            files = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/hosting.js": ("hosting.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
            if path in files:
                filename, mime = files[path]
                return self.send(200, (ROOT / "static" / filename).read_bytes(), mime)
            self.send(404, {"error": "Not found"})

        def do_POST(self):
            if not self.valid_host() or not secrets.compare_digest(self.headers.get("X-PokeWatch-Token", ""), tracker.token):
                return self.send(403, {"error": "Refresh the local dashboard and try again."})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length < 0 or length > 16000:
                    raise ValueError("Request is too large.")
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("Expected an object.")
                if self.path == "/api/scan":
                    if tracker.scanning:
                        return self.send(202, {"message": "A check is already running."})
                    if tracker.state["last_scan"] and tracker.next_check and tracker.next_check - time.time() > tracker.config["interval_seconds"] - 60:
                        return self.send(429, {"error": "Wait a minute between manual checks."})
                    threading.Thread(target=tracker.scan, daemon=True).start()
                elif self.path == "/api/reference":
                    tracker.set_reference(data)
                elif self.path == "/api/watch":
                    tracker.add_watch(data)
                else:
                    return self.send(404, {"error": "Not found"})
                self.send(200, {"ok": True})
            except (ValueError, KeyError, TypeError, OSError) as exc:
                self.send(400, {"error": str(exc)})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Check sources once and exit")
    parser.add_argument("--no-scan", action="store_true", help="Serve stored data without a background checker")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-dir", default=str(ROOT / "data"))
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    config["interval_seconds"] = max(300, int(config.get("interval_seconds", 900)))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    tracker = Tracker(config, args.data_dir)
    if args.once:
        tracker.scan()
        snapshot = tracker.snapshot()
        print(json.dumps({"products": len(snapshot["products"]), "releases": len(snapshot["releases"]), "matches": sum(p["qualifies"] for p in snapshot["products"].values()), "sources": snapshot["sources"]}, indent=2, ensure_ascii=True))
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port or config["port"]), make_handler(tracker))
    if not args.no_scan:
        threading.Thread(target=tracker.loop, daemon=True).start()
    LOG.info("PokeWatch dashboard: http://127.0.0.1:%d — Ctrl+C to stop", server.server_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        tracker.stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
