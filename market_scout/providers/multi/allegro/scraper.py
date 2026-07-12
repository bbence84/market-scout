"""
Shared Allegro scraper — used by allegro_pl, allegro_cz, allegro_sk.

All three domains run the same platform (same DataDome fingerprint, same HTML
structure, same embedded JSON payload format). Only the domain, UI language,
and price currency differ.

Anti-bot: Allegro uses DataDome, which blocks plain HTTP clients with 403.
Strategy: Playwright with a persistent browser profile stored at
  ~/.market-scout/allegro-profile/
On first run (or if DataDome blocks again), the browser is launched visibly
so the user can solve the CAPTCHA once. The solved cookie persists in the
profile for subsequent runs.

Primary data extraction: JSON blob embedded in <script type="application/json">
containing "listing_StoreState" key — returns clean structured data.
Fallback: BeautifulSoup HTML parsing of article elements.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_PROFILE_DIR = Path.home() / ".market-scout" / "allegro-profile"
_PAGE_SIZE_APPROX = 60  # Allegro shows ~60 items per page

# Currency per domain
_DOMAIN_CURRENCY = {
    "pl": "PLN",
    "cz": "CZK",
    "sk": "EUR",
}

# Consent/cookie banner dismiss selectors (tried in order)
_CONSENT_SELECTORS = [
    'button[data-role="accept-consent"]',
    'button:has-text("Zgadzam się")',
    'button:has-text("Souhlasím")',
    'button:has-text("Súhlasím")',
    'button:has-text("Accept")',
]

# DataDome block detection
_BLOCK_MARKERS = [
    "datadome",
    "geo.captcha-delivery.com",
    "ct.captcha-delivery.com",
    "You have been blocked",
    "Access denied",
]


def _is_blocked(html: str) -> bool:
    lower = html[:2000].lower()
    return any(m.lower() in lower for m in _BLOCK_MARKERS)


def _extract_from_json(html: str, domain: str, req: SearchRequest) -> list[Listing]:
    """
    Extract listings from the embedded listing_StoreState JSON blob.
    This is the primary extraction path and returns the richest data.
    """
    results = []
    # Find all <script type="application/json"> blocks
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script", type="application/json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, ValueError):
            continue

        # Look for the listing state — it may be the top-level object or nested
        tiles = _find_tiles(data)
        if not tiles:
            continue

        currency = _DOMAIN_CURRENCY.get(domain, "")
        base_url = f"https://allegro.{domain}"

        for tile in tiles[:req.max_results]:
            lst = _parse_tile(tile, base_url, currency, domain)
            if lst:
                results.append(lst)

        if results:
            break  # found the right script block

    return results


def _find_tiles(data) -> list:
    """Recursively find the list of offer tiles inside the JSON blob."""
    if isinstance(data, list):
        # If list of dicts with 'title' or 'offerId', that's it
        if data and isinstance(data[0], dict) and ("offerId" in data[0] or "title" in data[0]):
            return data
        for item in data:
            found = _find_tiles(item)
            if found:
                return found
    elif isinstance(data, dict):
        # Common key patterns seen in allegro JSON
        for key in ("items", "tiles", "offers", "listing", "products"):
            if key in data:
                found = _find_tiles(data[key])
                if found:
                    return found
        for v in data.values():
            if isinstance(v, (dict, list)):
                found = _find_tiles(v)
                if found:
                    return found
    return []


def _parse_tile(tile: dict, base_url: str, currency: str, domain: str) -> Listing | None:
    try:
        # Title
        title_block = tile.get("title") or {}
        title = (
            title_block.get("text") or
            tile.get("name") or
            tile.get("productName") or ""
        ).strip()
        if not title:
            return None

        # URL
        url = tile.get("url") or tile.get("offerUrl") or ""
        if url and not url.startswith("http"):
            url = base_url + url
        offer_id = tile.get("offerId") or tile.get("id") or ""
        if not url and offer_id:
            url = f"{base_url}/oferta/{offer_id}"

        # Price — several possible structures
        price_str = ""
        cur = currency
        for price_path in [
            ("price", "mainPrice"),
            ("mainPrice",),
            ("price",),
            ("sellingMode", "price"),
        ]:
            node = tile
            for k in price_path:
                node = node.get(k, {}) if isinstance(node, dict) else {}
            if isinstance(node, dict):
                amount = node.get("amount") or node.get("value")
                cur = node.get("currency") or node.get("currencyCode") or currency
                if amount is not None:
                    try:
                        price_str = str(int(float(amount))) if float(amount) == int(float(amount)) else str(amount)
                    except (ValueError, TypeError):
                        price_str = str(amount)
                    break

        # Location — Allegro doesn't expose seller city in search results
        location = ""

        # Image
        image_url = ""
        for img_path in [("mainThumbnail",), ("thumbnail",), ("image",)]:
            node = tile
            for k in img_path:
                node = node.get(k, {}) if isinstance(node, dict) else {}
            if isinstance(node, dict):
                image_url = (
                    node.get("url") or node.get("medium") or
                    node.get("thumbnail") or node.get("src") or ""
                )
                if image_url:
                    break
            elif isinstance(node, str):
                image_url = node
                break

        # Seller
        seller_block = tile.get("seller") or {}
        seller = seller_block.get("login") or seller_block.get("name") or ""

        # Condition — from parameters array
        condition = ""
        for param in tile.get("parameters") or []:
            if isinstance(param, dict) and param.get("name") in ("Stan", "Stav", "Stav tovaru"):
                condition = param.get("value", "")
                break

        return Listing(
            provider=f"allegro_{domain}",
            provider_country=domain.upper(),
            title=title,
            price=price_str,
            currency=cur,
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


def _extract_from_html(html: str, domain: str, req: SearchRequest) -> list[Listing]:
    """
    Fallback HTML extraction when JSON blob is not found.
    Uses BeautifulSoup article element parsing.
    """
    soup = BeautifulSoup(html, "lxml")
    results = []
    base_url = f"https://allegro.{domain}"
    currency = _DOMAIN_CURRENCY.get(domain, "")

    for article in soup.select("article"):
        try:
            link = article.select_one(f'a[href*="allegro.{domain}/oferta/"]') or \
                   article.select_one('a[href*="/oferta/"]')
            if not link:
                continue
            url = link.get("href", "")
            if url and not url.startswith("http"):
                url = base_url + url

            h2 = article.select_one("h2")
            title = h2.get_text(strip=True) if h2 else link.get_text(strip=True)
            if not title:
                continue

            # Price from aria-label
            price_str = ""
            for el in article.select('[aria-label]'):
                lbl = el.get("aria-label", "")
                if "cena" in lbl.lower() or "price" in lbl.lower():
                    price_str = re.sub(r'[^\d,.]', '', lbl.split(":")[-1]).strip()
                    break

            img = article.select_one('img[src*="allegroimg"]')
            image_url = img.get("src", "") if img else ""

            seller_a = article.select_one('a[href*="/uzytkownik/"]')
            seller = seller_a.get_text(strip=True) if seller_a else ""

            results.append(Listing(
                provider=f"allegro_{domain}",
                provider_country=domain.upper(),
                title=title,
                price=price_str,
                currency=currency,
                location="",
                url=url,
                image_url=image_url,
                description="",
                seller=seller,
                condition="",
                posted="",
            ))
        except Exception:
            continue

    return results


async def _dismiss_consent(page: Page) -> None:
    for sel in _CONSENT_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await asyncio.sleep(1)
                return
        except Exception:
            pass


async def _run_search(domain: str, req: SearchRequest) -> list[Listing]:
    base_url = f"https://allegro.{domain}"
    profile_dir = _PROFILE_DIR / domain
    profile_dir.mkdir(parents=True, exist_ok=True)

    results: list[Listing] = []
    seen_urls: set[str] = set()

    async with async_playwright() as p:
        # Persistent context keeps DataDome cookies between runs
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=req.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="pl-PL" if domain == "pl" else ("cs-CZ" if domain == "cz" else "sk-SK"),
            viewport={"width": 1280, "height": 900},
        )

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        page_num = 1
        while len(results) < req.max_results:
            url = f"{base_url}/listing?string={quote_plus(req.query)}&p={page_num}"
            if req.min_price:
                url += f"&price_from={req.min_price}"
            if req.max_price:
                url += f"&price_to={req.max_price}"

            if req.debug:
                print(f"[allegro_{domain}] GET {url}", flush=True)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(random.uniform(1.5, 2.5))
            except Exception as exc:
                print(f"[allegro_{domain}] Navigation error: {exc}", flush=True)
                break

            await _dismiss_consent(page)
            html = await page.content()

            if _is_blocked(html):
                if req.headless:
                    print(
                        f"\n[allegro_{domain}] DataDome CAPTCHA detected.\n"
                        f"  Run once with --no-headless to solve the CAPTCHA in the browser.\n"
                        f"  The solved cookie is saved to: {profile_dir}\n"
                        f"  Subsequent headless runs will reuse it.\n",
                        flush=True,
                    )
                    break
                else:
                    print(
                        f"\n[allegro_{domain}] CAPTCHA detected — please solve it in the browser window.\n"
                        f"  Waiting up to 3 minutes...\n",
                        flush=True,
                    )
                    try:
                        # Wait for results container to appear after CAPTCHA solved
                        await page.wait_for_selector('[data-box-name="Items Container"]', timeout=180_000)
                        await asyncio.sleep(2)
                        html = await page.content()
                    except Exception:
                        print(f"[allegro_{domain}] Timed out waiting for CAPTCHA solution.", flush=True)
                        break

            if req.debug:
                print(f"[allegro_{domain}] HTML size: {len(html)} bytes", flush=True)

            # Primary: JSON extraction
            page_listings = _extract_from_json(html, domain, req)

            # Fallback: HTML extraction
            if not page_listings:
                page_listings = _extract_from_html(html, domain, req)

            if req.debug:
                first = page_listings[0].title[:60] if page_listings else "(none)"
                print(f"[allegro_{domain}] Page {page_num}: {len(page_listings)} listing(s)  First: {first}", flush=True)

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

            if new_on_page == 0:
                break
            if len(results) >= req.max_results:
                break

            page_num += 1
            await asyncio.sleep(random.uniform(1.5, 3.0))

        await ctx.close()

    return results[: req.max_results]


def scrape(domain: str, req: SearchRequest) -> list[Listing]:
    """Entry point called by the thin provider wrappers."""
    return asyncio.run(_run_search(domain, req))
