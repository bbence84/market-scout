from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from market_scout.models import Listing


@dataclass
class SearchRequest:
    query: str
    locations: list[str] = field(default_factory=list)
    min_price: int | None = None
    max_price: int | None = None
    max_results: int = 30
    cookies_file: Path | None = None
    headless: bool = True
    scrape_details: bool = False
    radius_km: int = 0
    debug: bool = False


@runtime_checkable
class BaseProvider(Protocol):
    name: str
    countries: list[str]  # ISO-3166-1 alpha-2 codes, or ["*"] for global/multi-country

    def search(self, req: SearchRequest) -> list[Listing]:
        ...
