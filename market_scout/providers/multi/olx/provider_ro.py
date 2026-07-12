from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.providers.multi.olx.scraper import scrape

class OlxRoProvider:
    name = "olx_ro"
    countries = ["RO"]
    def search(self, req: SearchRequest) -> list[Listing]:
        return scrape("ro", req)
