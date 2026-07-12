from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Listing:
    provider: str = ""
    provider_country: str = ""  # ISO code of the site's country, e.g. "HU", or "*" for global
    title: str = ""
    price: str = ""
    currency: str = ""
    location: str = ""
    url: str = ""
    image_url: str = ""
    description: str = ""
    seller: str = ""
    condition: str = ""
    posted: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "provider_country": self.provider_country,
            "title": self.title,
            "price": self.price,
            "currency": self.currency,
            "location": self.location,
            "url": self.url,
            "image_url": self.image_url,
            "description": self.description,
            "seller": self.seller,
            "condition": self.condition,
            "posted": self.posted,
            "scraped_at": self.scraped_at,
        }
