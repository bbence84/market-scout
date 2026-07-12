"""
Kleinanzeigen.de provider — Germany's largest classifieds site.

Uses the private mobile JSON API (api.kleinanzeigen.de) with Chrome TLS
fingerprint impersonation via curl_cffi. No login required; uses baked-in
Android app credentials from the APK.

Credit/reference:
  monkrel/kleinanzeigen-api (MIT) — API discovery and auth headers

Location IDs are resolved lazily on first use via the site's autocomplete
endpoint and cached in-process so repeated calls to the same location avoid
extra requests.
"""
from __future__ import annotations

import re
import time
import random
import uuid
from html import unescape
from functools import lru_cache

try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_API_BASE = "https://api.kleinanzeigen.de/api"
_LOC_SUGGEST = "https://www.kleinanzeigen.de/s-ort-empfehlungen.json"
_PAGE_SIZE = 25
_ADS_KEY = "{http://www.ebayclassifiedsgroup.com/schema/ad/v1}ads"

# Baked-in Android app credentials (from APK, public across all reference repos)
_AUTH = ("android", "TaR60pEttY")

# In-process location cache: name → location_id string
_loc_cache: dict[str, str] = {}


def _app_id() -> str:
    """Generate a plausible X-EBAYK-APP header: uuid4 + 13-digit timestamp."""
    ts = str(int(time.time() * 1000))
    return f"{uuid.uuid4()}{ts}"


def _make_headers() -> dict:
    return {
        "X-EBAYK-APP": _app_id(),
        "X-ECG-USER-AGENT": "ebayk-android-app-2026.25.0",
        "X-ECG-USER-VERSION": "2026.25.0",
        "User-Agent": "Kleinanzeigen/2026.25.0 (Android 13; Pixel 7)",
        "Accept": "application/json",
        "Accept-Language": "de-DE",
    }


def _session():
    """Return a curl_cffi session impersonating Chrome."""
    if not _HAS_CURL_CFFI:
        raise ImportError(
            "curl_cffi is required for the Kleinanzeigen provider.\n"
            "Install it: pip install curl_cffi"
        )
    s = cffi_requests.Session(impersonate="chrome120")
    return s


def _resolve_location(query: str, session) -> str | None:
    """
    Resolve a location name/zip to a Kleinanzeigen location ID.
    Returns the ID string or None if not found.
    """
    if not query:
        return None
    key = query.lower().strip()
    if key in _loc_cache:
        return _loc_cache[key]
    try:
        resp = session.get(
            _LOC_SUGGEST,
            params={"query": query},
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=10,
        )
        data = resp.json()
        # Response format: {"_12345": "Berlin", "_67890": "Berlin Mitte", ...}
        for k, v in data.items():
            loc_id = k.lstrip("_")
            if loc_id.isdigit():
                _loc_cache[key] = loc_id
                return loc_id
    except Exception:
        pass
    return None


def _v(field: dict | None) -> str:
    """Unwrap {"value": x} → str. Returns "" for missing/empty."""
    if not field:
        return ""
    val = field.get("value")
    if val is None:
        return ""
    return str(val).strip()


def _parse_listing(ad: dict) -> Listing | None:
    try:
        title = unescape(_v(ad.get("title")))
        if not title:
            return None

        ad_id = str(ad.get("id", ""))

        # URL — prefer the public website link
        url = ""
        for link in ad.get("link", []):
            if link.get("rel") == "self-public-website":
                url = link.get("href", "")
                break
        if not url and ad_id:
            url = f"https://www.kleinanzeigen.de/s-anzeige/{ad_id}"

        # Price — all sub-fields are {"value": x} wrapped
        price_block = ad.get("price", {})
        amount_block = price_block.get("amount", {})
        raw_amount = amount_block.get("value") if amount_block else None
        price_type = _v(price_block.get("price-type"))

        if raw_amount is not None:
            try:
                amount_num = float(raw_amount)
                price_str = str(int(amount_num)) if amount_num == int(amount_num) else str(amount_num)
            except (ValueError, TypeError):
                price_str = str(raw_amount)
            if price_type in ("NEGOTIABLE", "PLEASE_CONTACT"):
                price_str += " VB"
        elif price_type == "FREE":
            price_str = "0"
        else:
            price_str = price_type or ""
        currency = "EUR" if price_type != "FREE" else ""

        # Location
        addr = ad.get("ad-address", {})
        city = _v(addr.get("state"))
        zip_code = _v(addr.get("zip-code"))
        location = f"{city}, {zip_code}".strip(", ") if (city or zip_code) else ""

        # Image — prefer largest: look for 'extra-large', 'large', 'teaser', 'thumbnail'
        image_url = ""
        for pic in ad.get("pictures", {}).get("picture", [])[:1]:
            for size_pref in ("extra-large", "large", "teaser", "thumbnail"):
                for link in pic.get("link", []):
                    if link.get("rel", "").lower() == size_pref:
                        image_url = link.get("href", "")
                        break
                if image_url:
                    break
            if not image_url and pic.get("link"):
                image_url = pic["link"][-1].get("href", "")

        description = _v(ad.get("description"))

        posted = _v(ad.get("start-date-time"))
        if posted:
            posted = posted[:10]  # "2026-07-12"

        return Listing(
            provider="kleinanzeigen",
            provider_country="DE",
            title=title,
            price=price_str,
            currency=currency,
            location=location,
            url=url,
            image_url=image_url,
            description=description,
            seller="",
            condition="",
            posted=posted,
        )
    except Exception:
        return None


class KleinanzeigenProvider:
    name = "kleinanzeigen"
    countries = ["DE"]

    def search(self, req: SearchRequest) -> list[Listing]:
        results: list[Listing] = []
        seen_urls: set[str] = set()

        session = _session()
        session.auth = _AUTH

        # Resolve location ID from the first location token (if any)
        location_id = None
        if req.locations:
            loc_token = req.locations[0]
            # Numeric IDs can be passed directly
            if loc_token.isdigit():
                location_id = loc_token
            else:
                location_id = _resolve_location(loc_token, session)
                if req.debug and location_id:
                    print(f"[kleinanzeigen] Resolved location '{loc_token}' → ID {location_id}", flush=True)
                elif req.debug:
                    print(f"[kleinanzeigen] Could not resolve location '{loc_token}', searching nationwide", flush=True)

        page = 0
        while len(results) < req.max_results:
            params: dict = {
                "q": req.query,
                "page": page,
                "size": _PAGE_SIZE,
                "sortType": "DATE_DESCENDING",
                "adType": "OFFERED",
            }
            if location_id:
                params["locationId"] = location_id
                params["distance"] = 50  # km radius around location
            if req.min_price:
                params["minPrice"] = req.min_price
            if req.max_price:
                params["maxPrice"] = req.max_price

            url = f"{_API_BASE}/ads.json"
            if req.debug:
                qs = "&".join(f"{k}={v}" for k, v in params.items())
                print(f"[kleinanzeigen] GET {url}?{qs}", flush=True)

            try:
                resp = session.get(
                    url,
                    params=params,
                    headers=_make_headers(),
                    timeout=20,
                )
                resp.raise_for_status()
            except Exception as exc:
                print(f"[kleinanzeigen] HTTP error on page {page}: {exc}", flush=True)
                break

            data = resp.json()
            ads_value = data.get(_ADS_KEY, {}).get("value", {})

            if req.debug:
                paging = ads_value.get("paging", {})
                total = paging.get("numFound", "?")
                print(f"[kleinanzeigen] Page {page}: status={resp.status_code} total={total}", flush=True)

            ads = ads_value.get("ad", [])
            if not ads:
                break

            for ad in ads:
                lst = _parse_listing(ad)
                if lst and lst.url not in seen_urls:
                    seen_urls.add(lst.url)
                    results.append(lst)
                if len(results) >= req.max_results:
                    break

            # Check if there are more pages
            paging = ads_value.get("paging", {})
            num_found = int(paging.get("numFound", 0) or 0)
            if (page + 1) * _PAGE_SIZE >= num_found:
                break
            if len(results) >= req.max_results:
                break

            page += 1
            time.sleep(random.uniform(1.0, 2.0))

        return results[: req.max_results]
