from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.providers.multi.olx.scraper import scrape

class OlxPlProvider:
    name = "olx_pl"
    countries = ["PL"]
    def search(self, req: SearchRequest) -> list[Listing]:
        return scrape("pl", req)
