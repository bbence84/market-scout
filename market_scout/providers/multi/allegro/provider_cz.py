from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.providers.multi.allegro.scraper import scrape


class AllegroCzProvider:
    name = "allegro_cz"
    countries = ["CZ"]

    def search(self, req: SearchRequest) -> list[Listing]:
        return scrape("cz", req)
