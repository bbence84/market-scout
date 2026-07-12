from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.providers.multi.bazos.scraper import scrape


class BazosCzProvider:
    name = "bazos_cz"
    countries = ["CZ"]

    def search(self, req: SearchRequest) -> list[Listing]:
        return scrape("cz", req)
