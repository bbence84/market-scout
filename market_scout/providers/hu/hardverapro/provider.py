"""
Hardverapro.hu provider — Hungarian tech classifieds.

Uses Playwright (headless Chromium) to establish session cookies through
the JS-based cookie challenge, then fetches search pages and parses HTML
with BeautifulSoup. No login required; only anonymous session cookies.

The site is Hungarian-only; titles and locations will be in Hungarian.
"""
from __future__ import annotations

import asyncio
import random
import re

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_BASE = "https://hardverapro.hu"
_SEARCH = f"{_BASE}/aprok/keres.php"
_PAGE_SIZE = 100


def _parse_price(raw: str) -> tuple[str, str]:
    """Return (amount, currency). Strips whitespace thousands separators."""
    raw = raw.strip()
    if not raw or raw.lower() in ("ingyenes", "0 ft"):
        return raw, "HUF"
    # "14 990 Ft" → "14990" / "1,25M Ft" → "1,25M"
    amount = re.sub(r"\s+", "", re.sub(r"\bFt\b", "", raw, flags=re.I)).strip()
    return amount, "HUF"


def _parse_listing(li) -> Listing | None:
    try:
        title_a = li.select_one(".uad-col-title h1 a")
        if not title_a:
            return None
        title = title_a.get_text(strip=True)
        url = title_a.get("href", "")
        if url and not url.startswith("http"):
            url = _BASE + url

        price_span = li.select_one(".uad-col-title .uad-price .text-nowrap")
        if not price_span:
            price_span = li.select_one(".uad-price .text-nowrap")
        raw_price = price_span.get_text(strip=True) if price_span else ""
        amount, currency = _parse_price(raw_price)

        cities_div = li.select_one(".uad-cities")
        location = cities_div.get_text(strip=True) if cities_div else ""

        seller_a = li.select_one(".uad-user-text a")
        seller = seller_a.get_text(strip=True) if seller_a else ""

        img = li.select_one(".uad-image img")
        image_url = ""
        if img:
            image_url = img.get("data-retina-url") or img.get("src", "")
            if image_url.startswith("//"):
                image_url = "https:" + image_url

        time_el = li.select_one(".uad-col-info .uad-time time")
        posted = time_el.get_text(strip=True) if time_el else ""

        return Listing(
            provider="hardverapro",
            provider_country="HU",
            title=title,
            price=amount,
            currency=currency,
            location=location,
            url=url,
            image_url=image_url,
            description="",
            seller=seller,
            condition="",
            posted=posted,
        )
    except Exception:
        return None


def _parse_page(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for li in soup.select("li.media[data-uadid]"):
        classes = li.get("class", [])
        # Skip paid promoted listings — unrelated to the search query
        if "featured" in classes:
            continue
        # Skip frozen/inactive listings (belt-and-suspenders alongside noiced=1 param)
        if "uad-status-iced" in classes:
            continue
        listing = _parse_listing(li)
        if listing:
            results.append(listing)
    return results


def _has_next_page(html: str, offset: int, page_size: int) -> bool:
    soup = BeautifulSoup(html, "lxml")
    next_offset = offset + page_size
    for a in soup.select("ul.pagination a, .pager a"):
        if f"offset={next_offset}" in a.get("href", ""):
            return True
    return False


def _build_url(query: str, offset: int, min_price: int | None, max_price: int | None) -> str:
    # Send the full form parameter set — keres.php silently redirects to the index
    # page (dropping the query) when extra anchor fields are absent.
    # Both buying=0 and __buying=0 are included for compatibility.
    params = [
        f"stext={query.replace(' ', '+')}",
        "stext_none=",
        "buying=0",
        "__buying=0",
        "noiced=1",
        "horder=time",
        "hdir=d",
        f"offset={offset}",
        "stcid_text=",
        "stcid=",
        "stmid_text=",
        "stmid=",
        "cmpid_text=",
        "cmpid=",
        "usrid_text=",
        "usrid=",
    ]
    if min_price:
        params.append(f"minprice={min_price}")
    else:
        params.append("minprice=")
    if max_price:
        params.append(f"maxprice={max_price}")
    else:
        params.append("maxprice=")
    return f"{_SEARCH}?{'&'.join(params)}"


async def _run_search(req: SearchRequest) -> list[Listing]:
    results: list[Listing] = []
    seen_urls: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="hu-HU",
        )
        page = await ctx.new_page()

        # Step 1: visit homepage and wait for networkidle so the JS cookie
        # challenge completes fully before we attempt any search requests
        if req.debug:
            print(f"[hardverapro] Loading homepage to establish session...", flush=True)
        await page.goto(_BASE + "/", wait_until="networkidle", timeout=30_000)
        await asyncio.sleep(random.uniform(0.3, 0.8))

        # Step 2: paginate through search results
        offset = 0
        while len(results) < req.max_results:
            url = _build_url(req.query, offset, req.min_price, req.max_price)

            if req.debug:
                print(f"[hardverapro] GET {url}", flush=True)

            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await asyncio.sleep(random.uniform(0.3, 0.8))

            final_url = page.url
            if req.debug:
                print(f"[hardverapro] Final URL: {final_url}", flush=True)

            # Detect if the search was redirected away (cookie/session failure)
            if "keres.php" not in final_url:
                print(
                    f"[hardverapro] Redirected to {final_url} — search did not execute.\n"
                    f"  This usually means the session cookie challenge failed.",
                    flush=True,
                )
                break

            html = await page.content()

            if req.debug:
                print(f"[hardverapro] Response size: {len(html)} bytes", flush=True)
                soup_check = BeautifulSoup(html, "lxml")
                first = soup_check.select_one("li.media[data-uadid] .uad-col-title h1 a")
                print(
                    f"[hardverapro] First result: "
                    f"{first.get_text(strip=True)[:80] if first else '(none)'}",
                    flush=True,
                )
                print(flush=True)

            page_listings = _parse_page(html)
            if not page_listings:
                break

            for lst in page_listings:
                if lst.url not in seen_urls:
                    seen_urls.add(lst.url)
                    results.append(lst)
                if len(results) >= req.max_results:
                    break

            if not _has_next_page(html, offset, _PAGE_SIZE):
                break

            offset += _PAGE_SIZE

        await browser.close()

    return results[: req.max_results]


class HardveraproProvider:
    name = "hardverapro"
    countries = ["HU"]

    def search(self, req: SearchRequest) -> list[Listing]:
        return asyncio.run(_run_search(req))
