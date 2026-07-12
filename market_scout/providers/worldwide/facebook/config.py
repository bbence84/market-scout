from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


@dataclass
class FbScraperConfig:
    location: str = ""
    search_query: str = ""
    max_listings: int = 50
    max_scrolls: int = 10
    headless: bool = True
    scrape_details: bool = False
    max_detail_pages: int = 10
    cookies_file: Path = field(default_factory=lambda: Path("cookies.json"))
    max_retries: int = 3
    min_price: int = 0
    max_price: int = 0
    sort_by: str = ""
    radius_km: int = 0

    @property
    def marketplace_url(self) -> str:
        loc = f"/{self.location}" if self.location else ""
        params = []
        if self.search_query:
            params.append(f"query={quote(self.search_query)}")
        if self.min_price:
            params.append(f"minPrice={self.min_price}")
        if self.max_price:
            params.append(f"maxPrice={self.max_price}")
        if self.sort_by:
            params.append(f"sortBy={self.sort_by}")
        if self.radius_km:
            params.append(f"radiusKm={self.radius_km}")
        qs = "&".join(params)
        base = f"https://www.facebook.com/marketplace{loc}"
        return f"{base}/search/?{qs}" if qs else base
