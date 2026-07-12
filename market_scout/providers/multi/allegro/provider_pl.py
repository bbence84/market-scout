from market_scout.models import Listing
from market_scout.providers.base import SearchRequest
from market_scout.providers.multi.allegro.scraper import scrape


class AllegroPlProvider:
    name = "allegro_pl"
    countries = ["PL"]

    def search(self, req: SearchRequest) -> list[Listing]:
        return scrape("pl", req)
