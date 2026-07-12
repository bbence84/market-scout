from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.providers.multi.olx.scraper import scrape

class OlxPtProvider:
    name = "olx_pt"
    countries = ["PT"]
    def search(self, req: SearchRequest) -> list[Listing]:
        return scrape("pt", req)
