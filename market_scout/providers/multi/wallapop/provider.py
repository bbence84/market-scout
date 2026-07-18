"""
Wallapop provider — European classifieds (Spain, Italy, Portugal, UK).

Wallapop runs a single global listing pool across all its country subdomains.
Country filtering is purely geographic: pass lat/lng + distance_in_km.
Items in the API response include location.country_code (ES/IT/PT/GB).

When location tokens are given as country codes (e.g. --provider ES or
--location ES in the market-scout sense), we expand them to a centre
coordinate + radius that covers the country. Items are then post-filtered
by country_code to avoid cross-border noise.

Without location tokens, the global pool is searched and no post-filter
is applied.

References:
  jswapping/WallapopScraper  — headers, endpoint, response structure
  danielhuici/Wallamonitor   — condition filter, pagination pattern
  z0r3f/wallbot              — field mapping
"""
from __future__ import annotations

import re
import time
import random

import httpx

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_API = "https://api.wallapop.com/api/v3/search"
_BASE_URL = "https://es.wallapop.com"

# Centre coordinates for each country — used as search anchor.
# distance_in_km is NOT passed; the API returns global results anchored
# to these coordinates, and we post-filter by country_code.
_COUNTRY_GEO: dict[str, tuple[float, float]] = {
    "ES": (40.4168, -3.7038),   # Madrid
    "IT": (41.9028, 12.4964),   # Rome
    "PT": (38.7169, -9.1395),   # Lisbon
    "GB": (51.5074, -0.1278),   # London
}


def _make_headers() -> dict:
    return {
        "X-DeviceOS": "0",
        "deviceos": "0",
        "x-appversion": "88570",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/138.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es,es-ES;q=0.9,en;q=0.8",
        "Origin": "https://es.wallapop.com",
        "Referer": "https://es.wallapop.com/",
    }


def _parse_item(item: dict, country_filter: set[str] | None) -> Listing | None:
    try:
        title = (item.get("title") or "").strip()
        if not title:
            return None

        item_country = (item.get("location") or {}).get("country_code", "").upper()
        if country_filter and item_country and item_country not in country_filter:
            return None

        web_slug = item.get("web_slug") or item.get("id") or ""
        url = f"{_BASE_URL}/item/{web_slug}" if web_slug else ""

        price_block = item.get("price") or {}
        amount = price_block.get("amount")
        currency = price_block.get("currency") or "EUR"
        if amount is not None:
            try:
                price_str = str(int(float(amount))) if float(amount) == int(float(amount)) else str(amount)
            except (ValueError, TypeError):
                price_str = str(amount)
        else:
            price_str = ""

        loc = item.get("location") or {}
        city = loc.get("city") or loc.get("region") or ""
        country_code = loc.get("country_code") or ""
        location = f"{city}, {country_code}".strip(", ") if (city or country_code) else ""

        # Image — prefer medium size
        image_url = ""
        for img in (item.get("images") or [])[:1]:
            urls = img.get("urls") or {}
            image_url = urls.get("medium") or urls.get("big") or urls.get("small") or ""
            if image_url:
                break

        description = (item.get("description") or "").strip()
        seller = str(item.get("user_id") or "")
        condition = item.get("condition") or ""
        posted = (item.get("creation_date") or "")[:10]  # "YYYY-MM-DD" or ""

        # Skip sold/reserved items
        flags = item.get("flags") or {}
        if flags.get("sold") or flags.get("reserved") or flags.get("banned"):
            return None

        return Listing(
            provider="wallapop",
            provider_country=country_code.upper() or "*",
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


class WallapopProvider:
    name = "wallapop"
    countries = ["ES", "IT", "PT", "GB"]
    no_location_ok = True  # searches all countries when no location is given

    def search(self, req: SearchRequest) -> list[Listing]:
        """
        Search Wallapop. Location tokens (from req.locations) can be:
          - Country codes (ES, IT, PT, GB) → expanded to lat/lng + distance
          - Empty → global search, no country filter

        Multiple country codes run as separate API calls; results are merged
        and deduplicated.
        """
        results: list[Listing] = []
        seen_urls: set[str] = set()

        # Determine which country/geo targets to search
        country_codes = [
            t.upper() for t in req.locations
            if len(t) == 2 and t.isalpha() and t.upper() in _COUNTRY_GEO
        ]

        if country_codes:
            # One API call per country — anchor to centre coords, post-filter by country_code
            targets = [(cc, _COUNTRY_GEO[cc], {cc}) for cc in country_codes]
        else:
            # No location given — search all supported countries explicitly.
            # Without lat/lng the API anchors to the user's IP location which may
            # have no Wallapop listings (e.g. Hungary). Looping all countries
            # ensures results from ES/IT/PT/GB regardless of where the user is.
            targets = [(cc, geo, {cc}) for cc, geo in _COUNTRY_GEO.items()]

        with httpx.Client(headers=_make_headers(), follow_redirects=True, timeout=20) as client:
            for target_cc, geo, country_filter in targets:
                lat, lng = geo if geo else (None, None)
                self._search_one(
                    client, req, lat, lng, None, country_filter,
                    results, seen_urls,
                )
                if len(results) >= req.max_results:
                    break
                if target_cc is not None:
                    time.sleep(random.uniform(0.5, 1.0))

        return results[: req.max_results]

    def _search_one(
        self,
        client: httpx.Client,
        req: SearchRequest,
        lat: float | None,
        lng: float | None,
        dist_km: int | None,  # kept in signature for API compat but not used
        country_filter: set[str] | None,
        results: list[Listing],
        seen_urls: set[str],
    ) -> None:
        params: dict = {
            "keywords": req.query,
            "source": "search_box",
            "order_by": "most_relevance",
        }
        if lat is not None:
            # Pass centre coords as anchor — omit distance_in_km so the API
            # returns global results (post-filtered by country_code below)
            params["latitude"] = lat
            params["longitude"] = lng
        if req.min_price:
            params["min_sale_price"] = req.min_price
        if req.max_price:
            params["max_sale_price"] = req.max_price

        next_page_token: str | None = None

        while len(results) < req.max_results:
            if next_page_token:
                params["next_page"] = next_page_token
            elif "next_page" in params:
                del params["next_page"]

            if req.debug:
                qs = "&".join(f"{k}={v}" for k, v in params.items())
                print(f"[wallapop] GET {_API}?{qs}", flush=True)

            try:
                resp = client.get(_API, params=params)
                resp.raise_for_status()
            except Exception as exc:
                print(f"[wallapop] HTTP error: {exc}", flush=True)
                break

            data = resp.json()
            items = (
                (data.get("data") or {})
                .get("section") or {}
            ).get("payload", {}).get("items") or []

            if req.debug:
                total = (data.get("data") or {}).get("section", {}).get("payload", {}).get("total_count", "?")
                print(f"[wallapop] items={len(items)} total={total}", flush=True)

            if not items:
                break

            new_on_page = 0
            for item in items:
                lst = _parse_item(item, country_filter)
                if lst and lst.url not in seen_urls:
                    seen_urls.add(lst.url)
                    results.append(lst)
                    new_on_page += 1
                if len(results) >= req.max_results:
                    break

            if new_on_page == 0:
                break

            # Pagination token
            next_page_token = (data.get("data") or {}).get("next_page") or None
            if not next_page_token:
                break
            if len(results) >= req.max_results:
                break

            time.sleep(random.uniform(0.5, 1.0))
