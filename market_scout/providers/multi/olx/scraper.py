"""
Shared OLX scraper — used by olx_ua, olx_pl, olx_ro, olx_pt, olx_bg.

All five European OLX domains run the same platform (same React SSR build,
same REST API endpoint, same JSON structure). Only the domain and currency differ.

Strategy: public REST API at /api/v1/offers/ with curl_cffi Chrome TLS
impersonation (CloudFront blocks Python's default TLS fingerprint).
No auth, no cookies required.
Pagination: offset-based (?offset=0&limit=40).

Reference:
  Pawikoski/olx-api-wrapper — API endpoint discovery
  lerdem/olx-parser — field selectors and UA headers
"""
from __future__ import annotations

import time
import random

from curl_cffi import requests as cffi_requests

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_LIMIT = 40  # max results per API page

# Per-country config: base URL and fallback display currency
_COUNTRIES: dict[str, dict] = {
    "ua": {"base": "https://www.olx.ua",  "currency": "UAH"},
    "pl": {"base": "https://www.olx.pl",  "currency": "PLN"},
    "ro": {"base": "https://www.olx.ro",  "currency": "RON"},
    "pt": {"base": "https://www.olx.pt",  "currency": "EUR"},
    "bg": {"base": "https://www.olx.bg",  "currency": "BGN"},
}


def _make_headers(country: str) -> dict:
    lang_map = {"ua": "uk-UA,uk;q=0.9", "pl": "pl-PL,pl;q=0.9", "ro": "ro-RO,ro;q=0.9",
                "pt": "pt-PT,pt;q=0.9", "bg": "bg-BG,bg;q=0.9"}
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": lang_map.get(country, "en;q=0.9"),
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }


def _get_price(ad: dict, fallback_currency: str) -> tuple[str, str]:
    """Extract (amount_str, currency) from the params array."""
    for param in ad.get("params", []):
        if param.get("key") == "price":
            val = param.get("value", {})
            if isinstance(val, dict):
                amount = val.get("value")
                currency = val.get("currency") or fallback_currency
                if amount is not None:
                    try:
                        amount_str = str(int(float(amount))) if float(amount) == int(float(amount)) else str(amount)
                    except (ValueError, TypeError):
                        amount_str = str(amount)
                    return amount_str, currency
                # "free" or "exchange" flags
                if val.get("free"):
                    return "0", currency
                label = val.get("label", "")
                return label, currency
    return "", fallback_currency


def _parse_ad(ad: dict, country: str, fallback_currency: str) -> Listing | None:
    try:
        title = (ad.get("title") or "").strip()
        if not title:
            return None

        url = ad.get("url") or ""

        price_str, currency = _get_price(ad, fallback_currency)

        loc = ad.get("location", {})
        city = (loc.get("city") or {}).get("name", "")
        region = (loc.get("region") or {}).get("name", "")
        location = f"{city}, {region}".strip(", ") if (city or region) else ""

        # Image: first photo, replace template placeholder with a usable size
        image_url = ""
        photos = ad.get("photos") or []
        if photos:
            link_tpl = photos[0].get("link", "")
            image_url = link_tpl.replace("{width}x{height}", "800x600")

        seller = (ad.get("user") or {}).get("name", "")
        description = (ad.get("description") or "").strip()

        # Condition from params
        condition = ""
        for param in ad.get("params", []):
            if param.get("key") in ("state", "condition"):
                val = param.get("value", {})
                condition = val.get("label", "") if isinstance(val, dict) else str(val)
                break

        posted = (ad.get("created_time") or "")[:10]  # "YYYY-MM-DD"

        return Listing(
            provider=f"olx_{country}",
            provider_country=country.upper(),
            title=title,
            price=price_str,
            currency=currency,
            location=location,
            url=url,
            image_url=image_url,
            description=description,
            seller=seller,
            condition=condition,
            posted=posted,
        )
    except Exception:
        return None


def scrape(country: str, req: SearchRequest) -> list[Listing]:
    """
    Run a paged search on olx.{country} and return up to req.max_results listings.
    country: one of "ua", "pl", "ro", "pt", "bg"
    """
    cfg = _COUNTRIES[country]
    base = cfg["base"]
    fallback_currency = cfg["currency"]
    api_url = f"{base}/api/v1/offers/"

    results: list[Listing] = []
    seen_urls: set[str] = set()

    # curl_cffi with Chrome TLS impersonation bypasses CloudFront TLS fingerprint check
    session = cffi_requests.Session(impersonate="chrome120")

    try:
        offset = 0
        while len(results) < req.max_results:
            params: dict = {
                "query": req.query,
                "offset": offset,
                "limit": min(_LIMIT, req.max_results - len(results)),
                "sort_by": "created_at:desc",
            }
            if req.min_price:
                params["filter_refiners"] = f"price[from]:{req.min_price}"
            if req.max_price:
                existing = params.get("filter_refiners", "")
                price_to = f"price[to]:{req.max_price}"
                params["filter_refiners"] = f"{existing},{price_to}".strip(",") if existing else price_to

            if req.debug:
                qs = "&".join(f"{k}={v}" for k, v in params.items())
                print(f"[olx_{country}] GET {api_url}?{qs}", flush=True)

            try:
                resp = session.get(api_url, params=params, headers=_make_headers(country), timeout=20)
                resp.raise_for_status()
            except Exception as exc:
                print(f"[olx_{country}] HTTP error at offset {offset}: {exc}", flush=True)
                break

            data = resp.json()
            ads = data.get("data") or []

            if req.debug:
                total = (data.get("metadata") or {}).get("total_elements", "?")
                print(f"[olx_{country}] offset={offset} ads={len(ads)} total={total}", flush=True)

            if not ads:
                break

            for ad in ads:
                lst = _parse_ad(ad, country, fallback_currency)
                if lst and lst.url not in seen_urls:
                    seen_urls.add(lst.url)
                    results.append(lst)
                if len(results) >= req.max_results:
                    break

            links = data.get("links") or {}
            if not links.get("next"):
                break
            if len(results) >= req.max_results:
                break

            offset += _LIMIT
            time.sleep(random.uniform(0.5, 1.0))
    finally:
        session.close()

    return results[: req.max_results]
