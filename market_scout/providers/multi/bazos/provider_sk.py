from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.providers.multi.bazos.scraper import scrape


class BazosSkProvider:
    name = "bazos_sk"
    countries = ["SK"]

    def search(self, req: SearchRequest) -> list[Listing]:
        return scrape("sk", req)
