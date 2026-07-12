from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.providers.multi.olx.scraper import scrape

class OlxBgProvider:
    name = "olx_bg"
    countries = ["BG"]
    def search(self, req: SearchRequest) -> list[Listing]:
        return scrape("bg", req)
