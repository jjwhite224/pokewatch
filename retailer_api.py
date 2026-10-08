"""Optional, read-only Best Buy Products API adapter (standard library only).

Official contract: https://bestbuyapis.github.io/api-documentation/
See Keyword Search Function, Pagination, Availability, Pricing and Product URLs.
Catalog overview: https://developers.bestbuy.com/apis
Marketplace context: https://corporate.bestbuy.com/2025/marketplace-qa/

The published Products API schema does not establish an offer's seller. These
rows therefore remain seller-unverified even when the API reports online stock.
No regular price, sale discount, or marketplace flag is treated as MSRP.
The caller supplies its sealed-English product filter and assigns check times.
API content/links are temporary; refresh them rather than using archived stock.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation


API_ENDPOINT = "https://api.bestbuy.com/v1/products(search=pokemon&active=true)"
PAGE_SIZE = 100
MAX_PAGES = 2
MAX_BODY = 6_000_000
API_FIELDS = "sku,name,salePrice,url,image,onlineAvailability,startDate,active"


class BestBuyAPIError(ValueError):
    """Safe to include in source health: contains neither URL nor API key."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Credentials are in the documented query string; never forward them.
        return None


def _fetch_json(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": "PokeWatch/1.0 (personal retail-price monitor)",
        "Accept": "application/json",
    })
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=25) as response:
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise BestBuyAPIError("Best Buy API response exceeded the size limit.")
        return json.loads(body)


def _safe_failure(error):
    # Never stringify upstream errors: they may echo the authenticated URL.
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403):
            return "Best Buy API access was denied; check the API key and its quota."
        if error.code == 429:
            return "Best Buy API rate limit reached; retry on the next scheduled check."
        if isinstance(error.code, int):
            return f"Best Buy API request failed (HTTP {error.code})."
    return "Best Buy API request failed or returned unreadable data."


def _price_cents(value):
    if isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            return None
        result = int((amount * 100).quantize(Decimal("1")))
        return result if result > 0 else None
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None


def _product_url(value, sku):
    if not isinstance(value, str) or any(ord(char) < 32 for char in value):
        return None
    try:
        url = urllib.parse.urlsplit(value)
        if url.scheme != "https" or url.username or url.password or url.port not in (None, 443):
            return None
        if url.hostname == "api.bestbuy.com":
            # The API documents temporary click links, not just www links.
            if not re.fullmatch(r"/click/[^/]+/" + re.escape(sku) + r"/pdp", url.path):
                return None
            return urllib.parse.urlunsplit(("https", "api.bestbuy.com", url.path, "", ""))
        if url.hostname not in ("www.bestbuy.com", "bestbuy.com") or not url.path.startswith(("/site/", "/product/")):
            return None
        query = urllib.parse.parse_qs(url.query)
        if "skuId" in query and query["skuId"] != [sku]:
            return None
        # Only the product selector may leave this adapter. No tracking/key data.
        clean_query = urllib.parse.urlencode({"skuId": sku}) if "skuId" in query else ""
        return urllib.parse.urlunsplit(("https", "www.bestbuy.com", url.path, clean_query, ""))
    except ValueError:
        return None


def _image_url(value):
    if not isinstance(value, str):
        return None
    try:
        url = urllib.parse.urlsplit(value)
        host = url.hostname or ""
        if (url.scheme == "https" and not url.username and not url.password
                and url.port in (None, 443)
                and (host == "www.bestbuy.com" or host.endswith(".bbystatic.com"))):
            return urllib.parse.urlunsplit(("https", host, url.path, "", ""))
    except ValueError:
        pass
    return None


def _product(raw, title_filter):
    if not isinstance(raw, dict) or raw.get("active") is False:
        return None
    sku = str(raw.get("sku", ""))
    name = raw.get("name")
    if not re.fullmatch(r"[1-9][0-9]*", sku) or not isinstance(name, str):
        return None
    title = html.unescape(name).strip()
    if not title_filter(title):
        return None
    url = _product_url(raw.get("url"), sku)
    if url is None:
        return None
    online = raw.get("onlineAvailability")
    availability = "InStock" if online is True else "OutOfStock" if online is False else "Unknown"
    return {
        "id": f"bestbuy:{sku}", "source_id": "bestbuy", "store": "Best Buy",
        "title": title, "url": url, "image": _image_url(raw.get("image")),
        "price_cents": _price_cents(raw.get("salePrice")), "currency": "USD",
        "availability": availability, "listed_at": raw.get("startDate"),
        "seller": "Seller not confirmed by API", "seller_verified": False,
        "reference_cents": None, "reference_kind": None, "reference_url": None,
    }


def fetch_bestbuy_catalog(*, title_filter, api_key=None, fetcher=None, max_pages=MAX_PAGES):
    """Return (normalized_products, partial, safe_message), up to 200 raw rows.

    Pass bot.sealed_english as title_filter; importing bot here would be circular.
    The optional fetcher(url) returns a parsed dict (or JSON text) for testing.
    With no explicit api_key, use BESTBUY_API_KEY. Missing keys make no request;
    callers may then retain their existing public-product-page fallback.
    A first-page failure raises BestBuyAPIError. Later failures retain good rows
    with partial=True. No authenticated URL or raw error enters the result.
    """
    key = os.environ.get("BESTBUY_API_KEY", "") if api_key is None else api_key
    if not isinstance(key, str) or not key.strip():
        raise BestBuyAPIError("Best Buy API is not configured; set BESTBUY_API_KEY to enable catalog checks.")
    key = key.strip()
    pages = max(1, min(MAX_PAGES, int(max_pages)))
    fetcher = fetcher or _fetch_json
    found, warnings = {}, []
    for number in range(1, pages + 1):
        if number > 1:
            time.sleep(0.25)  # Stay below the documented SDK default of 5/second.
        query = urllib.parse.urlencode({
            "apiKey": key, "format": "json", "show": API_FIELDS,
            "pageSize": PAGE_SIZE, "page": number, "sort": "startDate.dsc",
        })
        try:
            payload = fetcher(API_ENDPOINT + "?" + query)
            if isinstance(payload, (str, bytes, bytearray)):
                payload = json.loads(payload)
            if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
                raise ValueError("Invalid product collection")
        except Exception as error:
            message = _safe_failure(error)
            if number == 1:
                raise BestBuyAPIError(message) from None
            warnings.append(f"Page {number} could not be checked. {message}")
            break
        rows = payload["products"]
        if payload.get("partial") is True:
            warnings.append("The API reported an incomplete response.")
        if len(rows) > PAGE_SIZE:
            warnings.append("The API exceeded the requested page size; extra rows were omitted.")
        for raw in rows[:PAGE_SIZE]:
            item = _product(raw, title_filter)
            if item is not None:
                found[item["id"]] = item
        total_pages = payload.get("totalPages")
        has_pagination = type(total_pages) is int and total_pages >= 0
        if has_pagination and number >= total_pages:
            break
        if not has_pagination:
            warnings.append("The API did not confirm complete pagination.")
            if len(rows) < PAGE_SIZE:
                break
        if number == pages:
            warnings.append(f"Coverage capped at {pages} pages of {PAGE_SIZE} catalog entries.")
    message = " ".join(dict.fromkeys(warnings)) or "Catalog checked; the API does not confirm the offer seller."
    return list(found.values()), bool(warnings), message
