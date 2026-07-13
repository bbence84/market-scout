"""
Shpock provider — Austria focus (shpock.com).

Shpock runs a single global listing pool but is strongest in Austria.
Uses the public GraphQL endpoint; no auth, no cookies required.

Location filtering: centre coordinates of Austria are always sent so results
are anchored to AT. Client-side locality post-filter keeps only AT items.

References:
  descipar/marktcrawler — GraphQL query, field mapping, image URL pattern
"""
from __future__ import annotations

import json
import time
import random

import httpx

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_GRAPHQL = "https://www.shpock.com/graphql"
_BASE_URL = "https://www.shpock.com"
_IMG_BASE = "https://m1.secondhandapp.at/full"

# Austria centre (Vienna) — anchors results to AT
_AT_LAT = 48.2082
_AT_LNG = 16.3738
# Large radius (meters) to cover all of Austria
_AT_RADIUS_M = 400_000

# Austrian postal code prefixes and locality keywords for client-side filtering
# (API distance filter is unreliable per marktcrawler notes)
_AT_POSTCODE_PREFIXES = tuple(str(i) for i in range(1000, 10000))

_GRAPHQL_QUERY = """
query ItemSearch($serializedFilters: String, $pagination: Pagination, $trackingSource: TrackingSource!) {
  itemSearch(
    serializedFilters: $serializedFilters
    pagination: $pagination
    trackingSource: $trackingSource
  ) {
    od
    offset
    limit
    count
    total
    itemResults {
      items {
        __typename
        ... on ItemSummary {
          id
          title
          description
          price
          currency
          locality
          distance
          distanceUnit
          path
          isSold
          isFree
          media { id }
        }
      }
    }
  }
}
"""


def _make_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _is_austria(locality: str) -> bool:
    """Best-effort check whether a locality string is from Austria."""
    if not locality:
        return False
    # Austrian postcodes are 4-digit starting with 1-9 (1000-9999)
    # e.g. "1220 Wien", "6923 Lauterach", "4020 Linz"
    parts = locality.strip().split()
    if parts and len(parts[0]) == 4 and parts[0].isdigit():
        code = int(parts[0])
        return 1000 <= code <= 9999
    return False


def _parse_item(item: dict) -> Listing | None:
    try:
        if item.get("__typename") != "ItemSummary":
            return None
        if item.get("isSold"):
            return None

        title = (item.get("title") or "").strip()
        if not title:
            return None

        locality = (item.get("locality") or "").strip()

        # Client-side Austria filter
        if locality and not _is_austria(locality):
            return None

        item_id = item.get("id") or ""
        path = item.get("path") or ""
        url = f"{_BASE_URL}{path}" if path else (f"{_BASE_URL}/en-gb/i/{item_id}" if item_id else "")

        # Price
        raw_price = item.get("price")
        if item.get("isFree") or raw_price == 0:
            price_str = "0"
            currency = (item.get("currency") or "EUR").upper()
        elif raw_price is not None:
            try:
                price_str = str(int(float(raw_price))) if float(raw_price) == int(float(raw_price)) else str(raw_price)
            except (ValueError, TypeError):
                price_str = str(raw_price)
            currency = (item.get("currency") or "EUR").upper()
        else:
            price_str = ""
            currency = "EUR"

        # Image — first media ID
        image_url = ""
        media = item.get("media") or []
        if media and media[0].get("id"):
            image_url = f"{_IMG_BASE}/{media[0]['id']}"

        description = (item.get("description") or "").strip()

        return Listing(
            provider="shpock",
            provider_country="AT",
            title=title,
            price=price_str,
            currency=currency,
            location=locality,
            url=url,
            image_url=image_url,
            description=description,
            seller="",
            condition="",
            posted="",
        )
    except Exception:
        return None


class ShpockProvider:
    name = "shpock"
    countries = ["AT"]

    def search(self, req: SearchRequest) -> list[Listing]:
        results: list[Listing] = []
        seen_urls: set[str] = set()

        # Serialised filters — anchor to Austria
        filters: dict = {
            "q": req.query,
            "distance": {
                "lat": _AT_LAT,
                "lng": _AT_LNG,
                "radius": _AT_RADIUS_M,
            },
        }
        if req.max_price:
            filters["price"] = {"max": req.max_price}
        serialized_filters = json.dumps(filters, separators=(",", ":"))

        limit = 40
        offset = 0

        with httpx.Client(headers=_make_headers(), follow_redirects=True, timeout=20) as client:
            while len(results) < req.max_results:
                payload = {
                    "query": _GRAPHQL_QUERY,
                    "variables": {
                        "serializedFilters": serialized_filters,
                        "pagination": {"limit": limit, "offset": offset},
                        "trackingSource": "Search",
                    },
                }

                if req.debug:
                    print(f"[shpock] POST {_GRAPHQL} offset={offset} limit={limit}", flush=True)

                try:
                    resp = client.post(_GRAPHQL, json=payload)
                    resp.raise_for_status()
                except Exception as exc:
                    print(f"[shpock] HTTP error at offset {offset}: {exc}", flush=True)
                    break

                data = resp.json()
                search = (data.get("data") or {}).get("itemSearch") or {}
                item_results = search.get("itemResults") or []
                count = search.get("count") or 0

                # Flatten items from itemResults array
                all_items: list[dict] = []
                for group in item_results:
                    all_items.extend(group.get("items") or [])

                if req.debug:
                    print(f"[shpock] offset={offset} count={count} raw_items={len(all_items)}", flush=True)

                if not all_items:
                    break

                new_on_page = 0
                for item in all_items:
                    lst = _parse_item(item)
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
                # total is always null — stop when fewer items than requested
                if count < limit:
                    break

                offset += limit
                time.sleep(random.uniform(0.5, 1.0))

        return results[: req.max_results]
