"""
Subito.it provider — Italy's largest classifieds marketplace.

No public JSON API exists. Data is extracted from the __NEXT_DATA__ JSON
blob embedded in every search results page.

Requires curl_cffi with Chrome impersonation — plain httpx/requests gets
403 from Akamai's TLS/JA3 fingerprint detection.

References:
  dagdaAle/SubitoWatch — __NEXT_DATA__ path, curl_cffi impersonation, image URL
  alessio9567/subitomonitor — URL structure, pagination, field names
"""
from __future__ import annotations

import json
import re
import time
import random

try:
    from curl_cffi import requests as cffi_requests
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_SEARCH_BASE = "https://www.subito.it/annunci-italia/vendita/usato/"
_BASE_URL = "https://www.subito.it"


def _make_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        "Referer": "https://www.subito.it/",
    }


def _extract_next_data(html: str) -> dict | None:
    """Extract the __NEXT_DATA__ JSON blob from HTML."""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def _feat(features: dict, key: str) -> str:
    """Extract the first value string from a features block."""
    block = features.get(key) or {}
    vals = block.get("values") or []
    if vals:
        return vals[0].get("value") or vals[0].get("key") or ""
    return ""


def _feat_key(features: dict, key: str) -> str:
    """Extract the raw key (numeric) from a features block."""
    block = features.get(key) or {}
    vals = block.get("values") or []
    if vals:
        return vals[0].get("key") or ""
    return ""


def _parse_ad(ad: dict) -> Listing | None:
    try:
        # Skip promoted / banner items
        if ad.get("kind") not in ("AdItem", None, ""):
            return None

        title = (ad.get("subject") or "").strip()
        if not title:
            return None

        features = ad.get("features") or {}

        # Price — use numeric key from /price, fallback to display value
        raw_price_key = _feat_key(features, "/price")   # e.g. "849"
        raw_price_val = _feat(features, "/price")        # e.g. "849 EUR"
        price_str = ""
        if raw_price_key and raw_price_key.isdigit():
            price_str = raw_price_key
        elif raw_price_val:
            # Strip "EUR" and whitespace
            clean = re.sub(r'[^\d.,]', '', raw_price_val.replace('.', '').replace(',', '.'))
            try:
                f = float(clean)
                price_str = str(int(f)) if f == int(f) else str(f)
            except (ValueError, TypeError):
                pass

        # URL
        url = (ad.get("urls") or {}).get("default") or ""

        # Location
        geo = ad.get("geo") or {}
        town = (geo.get("town") or {}).get("value") or ""
        province = (geo.get("city") or {}).get("value") or ""
        region = (geo.get("region") or {}).get("value") or ""
        location = town or province or region
        if province and province != town:
            location = f"{town or province}, {province if town else region}"

        # Image — first image, append required rule param
        image_url = ""
        images = ad.get("images") or []
        if images:
            cdn = images[0].get("cdnBaseUrl") or ""
            if cdn:
                image_url = f"{cdn}?rule=gallery-desktop-2x-auto"

        description = (ad.get("body") or "").strip()

        # Seller
        advertiser = ad.get("advertiser") or {}
        seller = advertiser.get("name") or advertiser.get("shopName") or ""

        # Condition
        condition = _feat(features, "/item_condition")

        # Posted date
        posted = (ad.get("date") or "")[:10]  # "YYYY-MM-DD"

        return Listing(
            provider="subito",
            provider_country="IT",
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


class SubitoProvider:
    name = "subito"
    countries = ["IT"]

    def search(self, req: SearchRequest) -> list[Listing]:
        if not _HAS_CURL_CFFI:
            raise ImportError(
                "curl_cffi is required for the Subito provider (already installed for Kleinanzeigen/OLX). "
                "Install: pip install curl_cffi"
            )

        results: list[Listing] = []
        seen_urls: set[str] = set()

        session = cffi_requests.Session(impersonate="chrome120")

        try:
            page = 1
            while len(results) < req.max_results:
                params: dict = {"q": req.query, "t": "s"}
                if page > 1:
                    params["o"] = page
                # Server-side price filter only works reliably for specific categories,
                # but pass it anyway — worst case it's ignored and we filter client-side.
                if req.max_price:
                    params["pe"] = req.max_price
                if req.min_price:
                    params["ps"] = req.min_price

                if req.debug:
                    qs = "&".join(f"{k}={v}" for k, v in params.items())
                    print(f"[subito] GET {_SEARCH_BASE}?{qs}", flush=True)

                try:
                    resp = session.get(_SEARCH_BASE, params=params, headers=_make_headers(), timeout=20)
                    resp.raise_for_status()
                except Exception as exc:
                    print(f"[subito] HTTP error on page {page}: {exc}", flush=True)
                    break

                next_data = _extract_next_data(resp.text)
                if not next_data:
                    if req.debug:
                        print(f"[subito] __NEXT_DATA__ not found on page {page}", flush=True)
                    break

                state = (next_data.get("props") or {}).get("pageProps", {}).get("initialState", {})
                items_state = state.get("items") or {}
                ads = items_state.get("originalList") or []
                total_pages = items_state.get("totalPages") or 1

                if req.debug:
                    total = items_state.get("total", "?")
                    print(f"[subito] page={page}/{total_pages} ads={len(ads)} total={total}", flush=True)

                if not ads:
                    break

                new_on_page = 0
                for ad in ads:
                    lst = _parse_ad(ad)
                    if lst is None:
                        continue
                    # Client-side price filter (server filter unreliable on generic path)
                    if req.min_price and lst.price:
                        try:
                            if float(lst.price) < req.min_price:
                                continue
                        except ValueError:
                            pass
                    if req.max_price and lst.price:
                        try:
                            if float(lst.price) > req.max_price:
                                continue
                        except ValueError:
                            pass
                    if lst.url not in seen_urls:
                        seen_urls.add(lst.url)
                        results.append(lst)
                        new_on_page += 1
                    if len(results) >= req.max_results:
                        break

                if new_on_page == 0:
                    break
                if len(results) >= req.max_results:
                    break
                if page >= total_pages:
                    break

                page += 1
                time.sleep(random.uniform(1.0, 2.0))
        finally:
            session.close()

        return results[: req.max_results]
