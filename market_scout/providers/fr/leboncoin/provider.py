"""
Leboncoin.fr provider — France's largest classifieds marketplace.

Uses the public mobile JSON API at api.leboncoin.fr/finder/search.
The only requirement is a mobile app User-Agent — no auth, no cookies.
Full description is returned in the search results (no detail-page fetch needed).

References:
  etienne-hd/lbc — endpoint, mobile UA format, request body, field mapping
  etienne-hd/lbc-finder — pagination, filter structure
"""
from __future__ import annotations

import uuid
import time
import random

import httpx

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_API = "https://api.leboncoin.fr/finder/search"
_BASE_URL = "https://www.leboncoin.fr"


def _mobile_ua() -> str:
    """Generate a random Leboncoin iOS mobile app User-Agent."""
    device_id = str(uuid.uuid4()).upper()
    return f"LBC;iOS;18.5;iPhone;phone;{device_id};wifi;101.44.0"


def _make_headers() -> dict:
    return {
        "User-Agent": _mobile_ua(),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }


def _attr_value(attributes: list[dict], key: str) -> str:
    """Extract the value_label of a named attribute from the attributes list."""
    for attr in attributes:
        if attr.get("key") == key:
            return attr.get("value_label") or attr.get("value") or ""
    return ""


def _parse_ad(ad: dict) -> Listing | None:
    try:
        title = (ad.get("subject") or "").strip()
        if not title:
            return None

        ad_id = ad.get("list_id") or ""
        url = ad.get("url") or (f"{_BASE_URL}/ad/{ad_id}" if ad_id else "")

        # Price — prefer price_cents / 100, fall back to price array
        price_str = ""
        price_cents = ad.get("price_cents")
        if price_cents is not None:
            euros = price_cents / 100
            price_str = str(int(euros)) if euros == int(euros) else f"{euros:.2f}"
        else:
            price_list = ad.get("price") or []
            if price_list:
                try:
                    price_str = str(int(price_list[0]))
                except (ValueError, TypeError):
                    price_str = str(price_list[0])

        # Location
        loc = ad.get("location") or {}
        city = loc.get("city") or ""
        zipcode = loc.get("zipcode") or ""
        dept = loc.get("department_name") or ""
        if city and zipcode:
            location = f"{city}, {zipcode}"
        elif city and dept:
            location = f"{city}, {dept}"
        else:
            location = city or dept

        # Image — first large URL
        image_url = ""
        images = ad.get("images") or {}
        urls_large = images.get("urls_large") or []
        if urls_large:
            image_url = urls_large[0]
        elif images.get("thumb_url"):
            image_url = images["thumb_url"]

        description = (ad.get("body") or "").strip()

        # Seller
        owner = ad.get("owner") or {}
        seller = owner.get("name") or ""

        # Condition from attributes
        attributes = ad.get("attributes") or []
        condition = _attr_value(attributes, "condition")

        # Posted date
        posted = (ad.get("first_publication_date") or "")[:10]  # "YYYY-MM-DD"

        # Skip sold/inactive
        if ad.get("status") not in (None, "active", ""):
            return None

        return Listing(
            provider="leboncoin",
            provider_country="FR",
            title=title,
            price=price_str,
            currency="EUR",
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


class LeboncoinProvider:
    name = "leboncoin"
    countries = ["FR"]

    def search(self, req: SearchRequest) -> list[Listing]:
        results: list[Listing] = []
        seen_urls: set[str] = set()

        limit = 35
        offset = 0

        with httpx.Client(follow_redirects=True, timeout=20) as client:
            while len(results) < req.max_results:
                body: dict = {
                    "filters": {
                        "keywords": {
                            "text": req.query,
                            "type": "subject",
                        },
                        "enums": {"ad_type": ["offer"]},
                    },
                    "limit": limit,
                    "offset": offset,
                    "sort_by": "time",
                    "sort_order": "desc",
                    "owner_type": "private",
                    "extend": True,
                    "listing_source": "direct-search",
                    "disable_total": True,
                }
                if req.min_price or req.max_price:
                    price_range: dict = {}
                    if req.min_price:
                        price_range["min"] = req.min_price
                    if req.max_price:
                        price_range["max"] = req.max_price
                    body["filters"]["ranges"] = {"price": price_range}

                if req.debug:
                    print(f"[leboncoin] POST {_API} offset={offset}", flush=True)

                try:
                    resp = client.post(_API, json=body, headers=_make_headers())
                    if resp.status_code == 403:
                        # Datadome blocked — rotate UA and retry once
                        if req.debug:
                            print(f"[leboncoin] 403 at offset {offset}, retrying with new UA", flush=True)
                        time.sleep(random.uniform(2.0, 4.0))
                        resp = client.post(_API, json=body, headers=_make_headers())
                    resp.raise_for_status()
                except Exception as exc:
                    print(f"[leboncoin] HTTP error at offset {offset}: {exc}", flush=True)
                    break

                data = resp.json()
                ads = data.get("ads") or []
                max_pages = data.get("max_pages") or 0

                if req.debug:
                    print(f"[leboncoin] offset={offset} ads={len(ads)} max_pages={max_pages}", flush=True)

                if not ads:
                    break

                new_on_page = 0
                for ad in ads:
                    lst = _parse_ad(ad)
                    if lst and lst.url not in seen_urls:
                        seen_urls.add(lst.url)
                        results.append(lst)
                        new_on_page += 1
                    if len(results) >= req.max_results:
                        break

                if new_on_page == 0:
                    break
                if len(results) >= req.max_results:
                    break

                current_page = offset // limit + 1
                if max_pages and current_page >= max_pages:
                    break

                offset += limit
                time.sleep(random.uniform(1.0, 2.5))

        return results[: req.max_results]
