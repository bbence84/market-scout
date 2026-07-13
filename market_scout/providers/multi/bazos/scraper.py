"""
Shared scraper for bazos.cz and bazos.sk.

Both sites have identical HTML structure, CSS classes, and URL patterns.
Differences: TLD, currency (CZK vs EUR), Accept-Language header.

Strategy: httpx + BeautifulSoup. No login, no JS, no cookies required.
Pagination: offset in URL path — /0/, /20/, /40/ …  (20 listings per page).
Search: https://{category}.bazos.{tld}/{offset}/?hledat={query}&cenaod=&cenado=…

Sources / credit:
  zenisjan/Bazos-listings  — selectors and async approach
  peter115342/bazos_alert_bot — dual-site support and URL params
  pepab0t/bazos_scraper — Sec-Fetch headers for camouflage
"""
from __future__ import annotations

import re
import time
import random
from urllib.parse import urlencode, quote_plus

import httpx
from bs4 import BeautifulSoup

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.dates import normalise as normalise_date

_PAGE_SIZE = 20

# Price patterns for each TLD
_PRICE_CZ = re.compile(r"([\d\s]+)\s*K[cč]", re.I)
_PRICE_SK = re.compile(r"([\d\s]+)\s*(?:EUR|€)", re.I)
_DIGITS   = re.compile(r"\d")


def _make_headers(tld: str) -> dict:
    lang = "cs,sk;q=0.9,en;q=0.8" if tld == "cz" else "sk,cs;q=0.9,en;q=0.8"
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": lang,
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


def _build_url(tld: str, offset: int, query: str,
               min_price: int | None, max_price: int | None) -> str:
    """
    Bazos search URL (discovered from site's ld+json SearchAction):
      https://www.bazos.{tld}/search.php?hledat={query}&rubriky=www&...
    Pagination adds offset as a query param: &start={offset}
    """
    params: dict[str, str] = {
        "hledat": query,
        "rubriky": "www",
        "hlokalita": "",
        "humkreis": "25",
        "cenaod": str(min_price) if min_price else "",
        "cenado": str(max_price) if max_price else "",
        "Submit": "Hledat" if tld == "cz" else "Hladať",
        "kitx": "ano",
    }
    if offset > 0:
        params["start"] = str(offset)
    qs = urlencode(params, encoding="utf-8")
    return f"https://www.bazos.{tld}/search.php?{qs}"


def _parse_price(text: str, tld: str) -> tuple[str, str]:
    """Return (amount_str, currency). Amount has no spaces (thousands stripped).
    Non-numeric prices ("Dohodou", "V textu") are returned with empty currency
    so the output layer doesn't prepend a currency code to them.
    """
    text = text.strip()
    rx = _PRICE_CZ if tld == "cz" else _PRICE_SK
    m = rx.search(text)
    if m:
        amount = m.group(1).replace(" ", "").replace("\xa0", "").strip()
        currency = "CZK" if tld == "cz" else "EUR"
        return amount, currency
    # Non-numeric — return raw text with no currency marker
    return text, ""


def _parse_card(card, base_url: str, tld: str) -> Listing | None:
    try:
        title_a = card.select_one("h2.nadpis > a")
        if not title_a:
            return None
        title = title_a.get_text(strip=True)
        href = title_a.get("href", "")
        url = href if href.startswith("http") else base_url.rstrip("/") + href

        # Image — skip placeholder "no-image" thumbnails
        img = card.select_one("img.obrazek")
        image_url = ""
        if img:
            src = img.get("src", "")
            if src and "no-image" not in src and "no_photo" not in src:
                image_url = src if src.startswith("http") else "https:" + src if src.startswith("//") else base_url + src

        description = ""
        desc_div = card.select_one("div.popis")
        if desc_div:
            description = desc_div.get_text(strip=True)

        price_div = card.select_one("div.inzeratycena")
        raw_price = price_div.get_text(strip=True) if price_div else ""
        price, currency = _parse_price(raw_price, tld)

        loc_div = card.select_one("div.inzeratylok")
        raw_loc = loc_div.get_text(strip=True) if loc_div else ""
        # Site concatenates city + postal code without separator: "Náchod549 32"
        # Split on the first digit run to separate city from postal code
        m_loc = re.match(r"^(.*?)(\d[\d\s]+)$", raw_loc)
        if m_loc and m_loc.group(1).strip():
            location = f"{m_loc.group(1).strip()}, {m_loc.group(2).strip()}"
        else:
            location = raw_loc

        date_span = card.select_one("span.velikost10")
        posted = ""
        if date_span:
            text = date_span.get_text(strip=True)
            m = re.search(r"\[(\d{1,2}\.\d{1,2}\.\s*\d{4})\]", text)
            if m:
                posted = normalise_date(m.group(1).replace(" ", ""))

        return Listing(
            provider=f"bazos_{tld}",
            provider_country=tld.upper(),
            title=title,
            price=price,
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


def _parse_page(html: str, base_url: str, tld: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select("div.inzeraty.inzeratyflex"):
        lst = _parse_card(card, base_url, tld)
        if lst:
            results.append(lst)
    return results


def _has_next_page(html: str, tld: str) -> bool:
    """Check for a 'next page' link in the pagination strip."""
    soup = BeautifulSoup(html, "lxml")
    next_text = "Další" if tld == "cz" else "Ďalšie"
    # Check pagination div for a link containing next-page offset
    pager = soup.select_one("div.strankovani")
    if pager:
        for a in pager.select("a"):
            if next_text in a.get_text() or ">" in a.get_text():
                return True
    return False


def scrape(tld: str, req: SearchRequest) -> list[Listing]:
    """
    Run a paged search on bazos.{tld} and return up to req.max_results listings.
    tld: "cz" or "sk"
    """
    base_url = f"https://www.bazos.{tld}"
    results: list[Listing] = []
    seen_urls: set[str] = set()

    with httpx.Client(
        headers=_make_headers(tld),
        follow_redirects=True,
        timeout=20,
    ) as client:
        offset = 0
        while len(results) < req.max_results:
            url = _build_url(tld, offset, req.query, req.min_price, req.max_price)

            if req.debug:
                print(f"[bazos_{tld}] GET {url}", flush=True)

            try:
                resp = client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                print(f"[bazos_{tld}] HTTP error at offset {offset}: {exc}", flush=True)
                break

            if req.debug:
                print(f"[bazos_{tld}] Status: {resp.status_code}  Size: {len(resp.text)} bytes", flush=True)

            page_listings = _parse_page(resp.text, base_url, tld)

            if req.debug:
                first = page_listings[0].title[:60] if page_listings else "(none)"
                print(f"[bazos_{tld}] Page listings: {len(page_listings)}  First: {first}", flush=True)

            if not page_listings:
                break

            new_on_page = 0
            for lst in page_listings:
                if lst.url not in seen_urls:
                    seen_urls.add(lst.url)
                    results.append(lst)
                    new_on_page += 1
                if len(results) >= req.max_results:
                    break

            if len(results) >= req.max_results:
                break
            # Stop if no new listings on this page (all were TOP duplicates or already seen)
            if new_on_page == 0:
                break
            if not _has_next_page(resp.text, tld):
                break

            offset += _PAGE_SIZE
            time.sleep(random.uniform(0.8, 1.5))

    return results[: req.max_results]
