"""
Resolves CLI location tokens → list of (location_key, radius_km) pairs.

location_key is whatever goes into the FB URL path segment:
  - numeric fb_id   if the DB entry has one  (always works)
  - slug            otherwise                (works for major cities only)
  - ""              for auto-detect

Resolution order per token:
  1. Two-letter uppercase country code  → all cities for that country from locations.json
  2. Bare city slug / numeric ID        → passed through as-is

Examples:
  resolve_locations(["HU"], 0)            → [("budapest",150), ("debrecen",100),
                                             ("110889042346085",80), ...]
  resolve_locations(["gyor"], 50)         → [("gyor", 50)]   ← fb_id NOT injected
                                                                 (use --location HU
                                                                  or find-location)
  resolve_locations(["HU"], 200)          → all HU cities with radius 200
  resolve_locations([], 0)               → [("", 0)]  — auto-detect from cookies
"""
from __future__ import annotations

import json
from pathlib import Path

_DB_PATH = Path(__file__).parent / "locations.json"
_db: dict | None = None


def _load() -> dict:
    global _db
    if _db is None:
        _db = json.loads(_DB_PATH.read_text(encoding="utf-8"))
    return _db


def _is_country_code(token: str) -> bool:
    return len(token) == 2 and token.upper() == token and token.isalpha()


def resolve_locations(tokens: list[str], radius_override: int) -> list[tuple[str, int]]:
    """
    Returns a deduplicated list of (location_key, radius_km) pairs.
    location_key is fb_id when the DB has one, otherwise the slug.

    radius_override:
      > 0  → use this value for every city (including DB cities)
      == 0 → use DB-defined radius for country expansions; 0 for bare tokens
    """
    if not tokens:
        return [("", 0)]

    db = _load()
    seen: dict[str, int] = {}  # location_key → radius (first wins)

    # Build a slug→city lookup across all countries for bare-slug resolution
    slug_index: dict[str, dict] = {}
    for country_data in db.values():
        for city in country_data["cities"]:
            slug_index[city["slug"]] = city

    for token in tokens:
        upper = token.upper()
        if _is_country_code(upper) and upper in db:
            for city in db[upper]["cities"]:
                key = city.get("fb_id") or city["slug"]
                r = radius_override if radius_override > 0 else city["radius_km"]
                if key not in seen:
                    seen[key] = r
        else:
            raw = token.strip()
            # If the slug is in the DB and has an fb_id, use that
            city = slug_index.get(raw)
            key = (city.get("fb_id") or raw) if city else raw
            r = radius_override if radius_override > 0 else (city["radius_km"] if city else 0)
            if key not in seen:
                seen[key] = r

    return list(seen.items())


def list_countries() -> list[dict]:
    """Return [{code, name, city_count}] sorted by code."""
    db = _load()
    return [
        {"code": code, "name": data["name"], "city_count": len(data["cities"])}
        for code, data in sorted(db.items())
    ]


def list_cities(country_code: str) -> list[dict]:
    """Return city entries for a country, or [] if unknown."""
    db = _load()
    upper = country_code.upper()
    if upper not in db:
        return []
    return db[upper]["cities"]
