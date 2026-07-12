from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.providers.multi.olx.scraper import scrape

class OlxUaProvider:
    name = "olx_ua"
    countries = ["UA"]
    def search(self, req: SearchRequest) -> list[Listing]:
        return scrape("ua", req)
