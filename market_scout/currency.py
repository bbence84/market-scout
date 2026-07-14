"""
Currency conversion for market-scout.

Primary source:  Frankfurter API  (ECB rates, no key, no UAH/BGN)
Fallback source: open.er-api.com  (covers UAH and BGN)

Rates are cached in-process for the lifetime of a single run.
All conversions go through EUR as the intermediate currency.
"""
from __future__ import annotations

import re
import time
from functools import lru_cache
from typing import Optional

import httpx

_FRANKFURTER = "https://api.frankfurter.app/latest"
_OPENRATES = "https://open.er-api.com/v6/latest/EUR"

# Currencies not available from Frankfurter that need the fallback
_FALLBACK_CURRENCIES = frozenset(["UAH", "BGN"])

# Cached rates: {currency_code -> rate_to_EUR} (i.e. how many units = 1 EUR)
_rates_to_eur: dict[str, float] = {"EUR": 1.0}
_rates_loaded = False


def _load_rates() -> None:
    global _rates_loaded
    if _rates_loaded:
        return

    try:
        # Primary: Frankfurter (covers HUF, PLN, CZK, RON, GBP, etc.)
        resp = httpx.get(_FRANKFURTER, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # Frankfurter returns rates FROM EUR, so rate = "how many units per 1 EUR"
        for code, rate in data.get("rates", {}).items():
            _rates_to_eur[code.upper()] = float(rate)
    except Exception:
        pass

    # Fallback: open.er-api.com — used for UAH, BGN and as full backup
    missing = _FALLBACK_CURRENCIES - set(_rates_to_eur)
    if missing or len(_rates_to_eur) <= 1:
        try:
            resp2 = httpx.get(_OPENRATES, timeout=10)
            resp2.raise_for_status()
            data2 = resp2.json()
            for code, rate in data2.get("rates", {}).items():
                ucode = code.upper()
                if ucode not in _rates_to_eur:
                    _rates_to_eur[ucode] = float(rate)
        except Exception:
            pass

    _rates_loaded = True


def supported(currency: str) -> bool:
    """Return True if we have a rate for this currency."""
    _load_rates()
    return currency.upper() in _rates_to_eur


def to_eur(amount: float, from_currency: str) -> Optional[float]:
    """Convert amount to EUR. Returns None if currency unknown."""
    _load_rates()
    code = from_currency.upper()
    if code == "EUR":
        return amount
    rate = _rates_to_eur.get(code)
    if rate is None or rate == 0:
        return None
    return amount / rate


def from_eur(amount_eur: float, to_currency: str) -> Optional[float]:
    """Convert EUR amount to target currency. Returns None if unknown."""
    _load_rates()
    code = to_currency.upper()
    if code == "EUR":
        return amount_eur
    rate = _rates_to_eur.get(code)
    if rate is None:
        return None
    return amount_eur * rate


def convert(amount: float, from_currency: str, to_currency: str) -> Optional[float]:
    """Convert between any two currencies via EUR. Returns None if either is unknown."""
    if from_currency.upper() == to_currency.upper():
        return amount
    eur = to_eur(amount, from_currency)
    if eur is None:
        return None
    return from_eur(eur, to_currency)


def parse_price(price_str: str) -> Optional[float]:
    """
    Parse a price string to float, handling common non-numeric suffixes.
    Returns None if the string has no recognisable numeric value.

    Examples:
      "14990"    → 14990.0
      "350 VB"   → 350.0   (Kleinanzeigen negotiable marker stripped)
      "1250.50"  → 1250.5
      "ingyenes" → None
      "V textu"  → None
      ""         → None
    """
    if not price_str:
        return None
    # Strip known non-numeric suffixes (VB = Verhandlungsbasis = negotiable DE)
    cleaned = re.sub(r'\s*(VB|vb)\s*$', '', price_str.strip())
    # Remove thousands separators (spaces, dots in European format)
    cleaned = cleaned.replace('\xa0', '').replace(' ', '')
    # Replace comma decimal separator with dot
    cleaned = cleaned.replace(',', '.')
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def format_price(amount: float, currency: str, decimals: int = 0) -> str:
    """Format a converted price for display."""
    if decimals == 0:
        return f"{currency}{int(round(amount))}"
    return f"{currency}{amount:.{decimals}f}"


def convert_price_filter(
    amount: int,
    from_currency: str,
    to_currency: str,
) -> Optional[int]:
    """
    Convert a price filter value (min/max price) from target currency to
    provider currency. Returns None if conversion is not possible.
    Rounds to the nearest integer (prices are typically whole numbers).
    """
    result = convert(float(amount), from_currency, to_currency)
    if result is None:
        return None
    return int(round(result))
