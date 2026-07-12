from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.providers.cz.bazos.scraper import scrape


class BazosSkProvider:
    name = "bazos_sk"
    countries = ["SK"]

    def search(self, req: SearchRequest) -> list[Listing]:
        # Uses the same scraper as bazos_cz — only tld="sk" differs
        return scrape("sk", req)
