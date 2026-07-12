from market_scout.providers.worldwide.facebook.provider import FacebookProvider
from market_scout.providers.hu.hardverapro.provider import HardveraproProvider
from market_scout.providers.hu.jofogas.provider import JofogasProvider
from market_scout.providers.hu.vatera.provider import VateraProvider
from market_scout.providers.multi.bazos.provider_cz import BazosCzProvider
from market_scout.providers.multi.bazos.provider_sk import BazosSkProvider
from market_scout.providers.de.kleinanzeigen.provider import KleinanzeigenProvider
from market_scout.providers.multi.allegro.provider_pl import AllegroPlProvider
from market_scout.providers.multi.allegro.provider_cz import AllegroCzProvider
from market_scout.providers.multi.allegro.provider_sk import AllegroSkProvider
from market_scout.providers.multi.olx.provider_ua import OlxUaProvider
from market_scout.providers.multi.olx.provider_pl import OlxPlProvider
from market_scout.providers.multi.olx.provider_ro import OlxRoProvider
from market_scout.providers.multi.olx.provider_pt import OlxPtProvider
from market_scout.providers.multi.olx.provider_bg import OlxBgProvider

PROVIDERS: dict = {
    "facebook":      FacebookProvider(),
    "hardverapro":   HardveraproProvider(),
    "jofogas":       JofogasProvider(),
    "vatera":        VateraProvider(),
    "bazos_cz":      BazosCzProvider(),
    "bazos_sk":      BazosSkProvider(),
    "kleinanzeigen": KleinanzeigenProvider(),
    "allegro_pl":    AllegroPlProvider(),
    "allegro_cz":    AllegroCzProvider(),
    "allegro_sk":    AllegroSkProvider(),
    "olx_ua":        OlxUaProvider(),
    "olx_pl":        OlxPlProvider(),
    "olx_ro":        OlxRoProvider(),
    "olx_pt":        OlxPtProvider(),
    "olx_bg":        OlxBgProvider(),
}


def resolve_providers(tokens: list[str]) -> list[str]:
    """
    Resolve a list of provider tokens into a list of provider names.
    Each token is either:
      - a provider name (facebook, hardverapro, …) → included as-is
      - a two-letter country code (HU, DE, …) → all providers whose countries list
        contains that code (or "*") are included
    Returns deduplicated names in PROVIDERS registration order.
    Unknown tokens are returned unchanged so the CLI can report the error.
    """
    if not tokens:
        return list(PROVIDERS)

    resolved: list[str] = []
    seen: set[str] = set()

    for token in tokens:
        upper = token.upper()
        # Check if it looks like a country code (2 letters) and matches any provider
        if len(upper) == 2 and upper.isalpha():
            matched = [
                name for name, prov in PROVIDERS.items()
                if upper in [c.upper() for c in prov.countries]
                or "*" in prov.countries  # worldwide providers always included on country expansion
            ]
            if matched:
                for name in PROVIDERS:  # preserve registration order
                    if name in matched and name not in seen:
                        resolved.append(name)
                        seen.add(name)
                continue
        # Fall through: treat as a literal provider name or unknown token
        if token not in seen:
            resolved.append(token)
            seen.add(token)

    return resolved
