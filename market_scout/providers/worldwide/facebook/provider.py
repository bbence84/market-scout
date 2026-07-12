import asyncio
import re
from pathlib import Path

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from .config import FbScraperConfig
from .location_db import resolve_locations
from .scraper import run_scrape

_CURRENCY_RX = re.compile(
    r'(HUF|PLN|CZK|RON|HRK|BGN|SEK|NOK|DKK|CHF|IDR|Rp|[$€£¥₩])\s*'
)


def _extract_currency(price: str) -> tuple[str, str]:
    """Return (currency_symbol, price_without_symbol)."""
    m = _CURRENCY_RX.search(price)
    if m:
        return m.group(1), _CURRENCY_RX.sub("", price).strip()
    return "", price


class FacebookProvider:
    name = "facebook"
    countries = ["*"]  # operates across all countries via location parameter

    def search(self, req: SearchRequest) -> list[Listing]:
        city_radius_pairs = resolve_locations(req.locations, req.radius_km)
        results: dict[str, Listing] = {}

        for city_slug, radius_km in city_radius_pairs:
            cfg = FbScraperConfig(
                location=city_slug,
                search_query=req.query,
                max_listings=req.max_results,
                min_price=req.min_price or 0,
                max_price=req.max_price or 0,
                headless=req.headless,
                scrape_details=req.scrape_details,
                cookies_file=req.cookies_file or Path("cookies.json"),
                radius_km=radius_km,
            )
            fb_listings = asyncio.run(run_scrape(cfg))

            for fb in fb_listings:
                currency, price_clean = _extract_currency(fb.price)
                normalized = Listing(
                    provider="facebook",
                    provider_country="*",
                    title=fb.title,
                    price=price_clean,
                    currency=currency,
                    location=fb.location,
                    url=fb.url,
                    image_url=fb.image_url,
                    description=fb.description,
                    seller=fb.seller,
                    condition=fb.condition,
                    posted=fb.posted,
                    scraped_at=fb.scraped_at,
                )
                # deduplicate by URL
                if fb.url not in results:
                    results[fb.url] = normalized

        return list(results.values())
