from market_scout.providers.worldwide.facebook.provider import FacebookProvider
from market_scout.providers.hu.hardverapro.provider import HardveraproProvider
from market_scout.providers.hu.jofogas.provider import JofogasProvider
from market_scout.providers.hu.vatera.provider import VateraProvider
from market_scout.providers.cz.bazos.provider import BazosCzProvider
from market_scout.providers.sk.bazos.provider import BazosSkProvider

PROVIDERS: dict = {
    "facebook":    FacebookProvider(),
    "hardverapro": HardveraproProvider(),
    "jofogas":     JofogasProvider(),
    "vatera":      VateraProvider(),
    "bazos_cz":    BazosCzProvider(),
    "bazos_sk":    BazosSkProvider(),
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
            ]
            # Also include global providers (countries == ["*"]) only when
            # a country code is given alongside specific providers — skip "*"
            # here so --provider HU doesn't silently pull in Facebook.
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
