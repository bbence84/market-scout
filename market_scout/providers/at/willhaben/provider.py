"""
Willhaben.at provider — Austria's largest classifieds marketplace.

Uses the public JSON API at willhaben.at/webapi/iad/search.
The only required non-standard header is x-wh-client.
No login, no cookies, no auth tokens required.

References:
  Ceirced/willhaben — API endpoint, x-wh-client header, field mapping
  xaver-lab/willhaben-agent — BODY_DYN description, pagination
  pasogott/whcli — SEO URL construction, price format
"""
from __future__ import annotations

import time
import random

import httpx

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_API = "https://www.willhaben.at/webapi/iad/search/atz/seo/kaufen-und-verkaufen/marktplatz"
_BASE = "https://www.willhaben.at"
_ROWS = 30  # items per page


def _make_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
        "x-wh-client": "api@willhaben.at;responsive_web;server;1.0.0;desktop",
        "Referer": "https://www.willhaben.at/iad",
    }


def _attr(attributes: list[dict], name: str) -> str:
    """Extract the first value of a named attribute from the attributes array."""
    for attr in attributes:
        if attr.get("name") == name:
            vals = attr.get("values") or []
            return vals[0] if vals else ""
    return ""


def _parse_ad(ad: dict) -> Listing | None:
    try:
        title = (ad.get("description") or "").strip()
        if not title:
            return None

        attrs = (ad.get("attributes") or {}).get("attribute") or []

        # Price — prefer PRICE/AMOUNT (float string), fall back to PRICE (int string)
        raw_price = _attr(attrs, "PRICE/AMOUNT") or _attr(attrs, "PRICE")
        price_str = ""
        if raw_price:
            try:
                f = float(raw_price)
                price_str = str(int(f)) if f == int(f) else str(f)
            except (ValueError, TypeError):
                price_str = raw_price

        # URL — prefer SEO URL, fall back to adId-based URL
        seo_url = _attr(attrs, "SEO_URL")
        ad_id = str(ad.get("id") or "")
        if seo_url:
            url = f"{_BASE}/iad/{seo_url.lstrip('/')}"
        elif ad_id:
            url = f"{_BASE}/iad/object?adId={ad_id}"
        else:
            # Try contextLinkList
            for cl in ((ad.get("contextLinkList") or {}).get("contextLink") or []):
                if cl.get("id") == "iadShareLink":
                    url = cl.get("uri", "")
                    break
            else:
                url = ""

        # Location
        location = _attr(attrs, "LOCATION")
        postcode = _attr(attrs, "POSTCODE")
        if postcode and location:
            location = f"{location}, {postcode}"
        elif postcode:
            location = postcode

        # Image — first from advertImageList
        image_url = ""
        imgs = (ad.get("advertImageList") or {}).get("advertImage") or []
        if imgs:
            image_url = imgs[0].get("mainImageUrl") or imgs[0].get("thumbnailImageUrl") or ""

        # Description (body text)
        description = (_attr(attrs, "BODY_DYN") or "").strip()

        # Seller — private or dealer
        seller = ""
        is_private = _attr(attrs, "ISPRIVATE") == "1"
        if not is_private:
            seller = "dealer"

        # Condition
        condition = _attr(attrs, "CONDITION")

        # Posted date — ISO string preferred, fall back to epoch ms
        posted = ""
        published_str = _attr(attrs, "PUBLISHED_String")
        if published_str:
            posted = published_str[:10]  # "YYYY-MM-DD"
        else:
            published_ms = _attr(attrs, "PUBLISHED")
            if published_ms:
                try:
                    from datetime import datetime, timezone
                    ts = int(published_ms) / 1000
                    posted = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    pass

        return Listing(
            provider="willhaben",
            provider_country="AT",
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


class WillhabenProvider:
    name = "willhaben"
    countries = ["AT"]

    def search(self, req: SearchRequest) -> list[Listing]:
        results: list[Listing] = []
        seen_urls: set[str] = set()

        with httpx.Client(headers=_make_headers(), follow_redirects=True, timeout=20) as client:
            page = 1
            while len(results) < req.max_results:
                params: dict = {
                    "keyword": req.query,
                    "rows": _ROWS,
                    "page": page,
                    "isNavigation": "true",
                    "sort": 1,  # newest first
                }
                if req.min_price:
                    params["PRICE_FROM"] = req.min_price
                if req.max_price:
                    params["PRICE_TO"] = req.max_price

                if req.debug:
                    qs = "&".join(f"{k}={v}" for k, v in params.items())
                    print(f"[willhaben] GET {_API}?{qs}", flush=True)

                try:
                    resp = client.get(_API, params=params)
                    resp.raise_for_status()
                except Exception as exc:
                    print(f"[willhaben] HTTP error on page {page}: {exc}", flush=True)
                    break

                data = resp.json()
                ads = (data.get("advertSummaryList") or {}).get("advertSummary") or []
                rows_found = data.get("rowsFound", 0)

                if req.debug:
                    print(f"[willhaben] page={page} ads={len(ads)} total={rows_found}", flush=True)

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
                # Stop if we've fetched all available results
                if page * _ROWS >= rows_found:
                    break

                page += 1
                time.sleep(random.uniform(0.5, 1.2))

        return results[: req.max_results]
