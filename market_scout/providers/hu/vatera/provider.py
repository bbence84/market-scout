"""
Vatera.hu provider — Hungarian auction and classifieds marketplace.

Strategy:
  Server-rendered HTML. Each listing card is a <div class="gtm-impression prod">
  with data-gtm-* attributes that carry clean, pre-parsed field values (no regex
  needed for price or title). BeautifulSoup extracts the rest.

  No login, no JS rendering, no anti-bot measures for anonymous search.
  Price filter uses p1/p2 (NOT ar_tol/ar_ig which are silently ignored).
  Pagination: &p=N (1-based, page 1 has no param). 50 results per page.
"""
from __future__ import annotations

import math
import time
import random

import httpx
from bs4 import BeautifulSoup

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_BASE   = "https://www.vatera.hu"
_SEARCH = f"{_BASE}/listings/index.php"
_PAGE_SIZE = 50


def _make_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": _BASE + "/",
    }


def _parse_card(card) -> Listing | None:
    try:
        # All core fields come from data-gtm-* attributes — no parsing needed
        title     = card.get("data-gtm-name", "").strip()
        price_raw = card.get("data-gtm-price", "")
        product_id = card.get("data-product-id", "")

        if not title or card.get("data-expired") == "1":
            return None

        price = price_raw.strip() if price_raw else ""

        # URL
        link = card.select_one("a.product_link")
        url = link["href"] if link else ""
        if url and not url.startswith("http"):
            url = _BASE + url

        # Image — use data-original (lazy-loaded), not src (placeholder gif)
        img = card.select_one("img.lazy-load")
        image_url = ""
        if img:
            image_url = img.get("data-original") or img.get("src", "")

        # Condition and location from additional-info divs
        # Labels use accented Hungarian: "Állapot:" and "Termék helye:"
        condition = ""
        location  = ""
        for div in card.select("div.additional-info div.col-12"):
            text = div.get_text(" ", strip=True)
            lower = text.lower()
            if "állapot" in lower or "allapot" in lower:
                condition = text.split(":", 1)[-1].strip()
            elif "termék helye" in lower or "termek helye" in lower:
                location = text.split(":", 1)[-1].strip()

        # Seller name
        seller_a = card.select_one("span.userrating a")
        seller = seller_a.get_text(strip=True) if seller_a else ""

        # Auction type as a hint in condition if blank
        auction_type = card.get("data-gtm-auction-type", "")
        if not condition and auction_type == "bid":
            condition = "auction"

        return Listing(
            provider="vatera",
            provider_country="HU",
            title=title,
            price=price,
            currency="HUF",
            location=location,
            url=url,
            image_url=image_url,
            description="",
            seller=seller,
            condition=condition,
            posted="",
        )
    except Exception:
        return None


def _parse_page(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select("div.gtm-impression.prod"):
        lst = _parse_card(card)
        if lst:
            results.append(lst)
    return results


def _total_pages(html: str) -> int:
    """Extract total page count from pagination widget title attribute."""
    soup = BeautifulSoup(html, "lxml")
    # "1. / 4 oldal" pattern in any page-number title attribute
    for li in soup.select("li.page-number[title]"):
        title = li.get("title", "")
        if " / " in title and " oldal" in title:
            try:
                return int(title.split(" / ")[1].split(" ")[0])
            except ValueError:
                pass
    return 1


class VateraProvider:
    name = "vatera"
    countries = ["HU"]

    def search(self, req: SearchRequest) -> list[Listing]:
        """
        Search vatera.hu. Location tokens are ignored (site is Hungary-only).
        Paginates with &p=N until max_results is reached or pages run out.
        """
        results: list[Listing] = []
        seen_urls: set[str] = set()

        with httpx.Client(headers=_make_headers(), follow_redirects=True, timeout=20) as client:
            page = 1
            total_pages = 1

            while len(results) < req.max_results:
                params: dict[str, str] = {
                    "q": req.query,
                    "ob": "5",   # newest first
                    "obd": "2",
                }
                if req.min_price:
                    params["p1"] = str(req.min_price)
                if req.max_price:
                    params["p2"] = str(req.max_price)
                if page > 1:
                    params["p"] = str(page)

                if req.debug:
                    url_str = _SEARCH + "?" + "&".join(f"{k}={v}" for k, v in params.items())
                    print(f"[vatera] GET {url_str}", flush=True)

                try:
                    resp = client.get(_SEARCH, params=params)
                    resp.raise_for_status()
                except Exception as exc:
                    print(f"[vatera] HTTP error on page {page}: {exc}", flush=True)
                    break

                if req.debug:
                    print(f"[vatera] Final URL: {resp.url}  size: {len(resp.text)} bytes", flush=True)

                # On first page, learn total page count
                if page == 1:
                    total_pages = _total_pages(resp.text)
                    if req.debug:
                        print(f"[vatera] Total pages: {total_pages}", flush=True)

                page_listings = _parse_page(resp.text)
                if req.debug:
                    print(f"[vatera] Page {page}: {len(page_listings)} listing(s)", flush=True)

                if not page_listings:
                    break

                for lst in page_listings:
                    if lst.url not in seen_urls:
                        seen_urls.add(lst.url)
                        results.append(lst)
                    if len(results) >= req.max_results:
                        break

                if page >= total_pages:
                    break

                page += 1
                time.sleep(random.uniform(0.5, 1.2))

        # If --details requested, fetch each listing page for full description
        if req.scrape_details and results:
            if req.debug:
                print(f"[vatera] Fetching detail pages for {len(results)} listing(s)...", flush=True)
            with httpx.Client(headers=_make_headers(), follow_redirects=True, timeout=15) as detail_client:
                for lst in results:
                    if not lst.url or lst.description:
                        continue
                    try:
                        resp = detail_client.get(lst.url)
                        if resp.status_code == 200:
                            detail_soup = BeautifulSoup(resp.text, "lxml")
                            box = detail_soup.select_one(".userprodbox")
                            if box:
                                description_text = ""

                                # Primary: find the "Eladó leírása a termékről" section
                                # Structure: div.tw-mt-6 > div > div.tw-break-words
                                # containing h3 with 'leírás' and sibling div with text
                                for section in box.select("div.tw-mt-6"):
                                    h3 = section.select_one("h3")
                                    if h3 and "leírás" in h3.get_text().lower():
                                        # Get all text from this section, skip the h3 itself
                                        parts = []
                                        for el in section.select("span, p"):
                                            t = el.get_text(" ", strip=True)
                                            if t and t not in (".", ".:.", ":"):
                                                parts.append(t)
                                        if parts:
                                            description_text = " ".join(parts)[:2000]
                                        break

                                # Fallback: <p> tags directly in .userprodbox
                                if not description_text:
                                    parts = [p.get_text(" ", strip=True)
                                             for p in box.select("p") if p.get_text(strip=True)]
                                    if parts:
                                        description_text = " ".join(parts)[:2000]

                                if description_text:
                                    lst.description = description_text
                        time.sleep(random.uniform(0.3, 0.7))
                    except Exception:
                        pass

        return results[: req.max_results]
