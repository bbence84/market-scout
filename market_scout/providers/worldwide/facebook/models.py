from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FbListing:
    title: str = ""
    price: str = ""
    location: str = ""
    url: str = ""
    image_url: str = ""
    seller: str = ""
    posted: str = ""
    condition: str = ""
    delivery: str = ""
    description: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "price": self.price,
            "location": self.location,
            "url": self.url,
            "image_url": self.image_url,
            "seller": self.seller,
            "posted": self.posted,
            "condition": self.condition,
            "delivery": self.delivery,
            "description": self.description,
            "scraped_at": self.scraped_at,
        }
