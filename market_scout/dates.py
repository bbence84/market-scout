"""
Date normalisation for market-scout listings.

Goal: convert all provider-specific date formats to ISO 8601 date string "YYYY-MM-DD".
Falls back to "" when parsing fails (never raises).

Programmatic approach handles all structured formats.
LLM fallback handles free-text relative strings (e.g. Facebook: "25 weeks ago", "Yesterday").
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# Reference date — always use real "now" so relative strings work correctly
def _today() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Programmatic parsers
# ---------------------------------------------------------------------------

# Map of compiled patterns → strptime format strings (tried in order)
_STRUCTURED_FORMATS = [
    # ISO 8601 variants
    (re.compile(r"^\d{4}-\d{2}-\d{2}T"), "%Y-%m-%dT%H:%M:%S"),    # 2026-07-13T14:30:00
    (re.compile(r"^\d{4}-\d{2}-\d{2} "), "%Y-%m-%d %H:%M:%S"),     # 2026-07-13 14:30:00
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d"),              # 2026-07-13
    # Vatera / some HU sites
    (re.compile(r"^\d{4}/\d{2}/\d{2} "), "%Y/%m/%d %H:%M:%S"),     # 2026/07/21 19:12:00
    # Bazos (D.M.YYYY or DD.MM.YYYY)
    (re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$"), None),              # 13.7.2026 — handled separately
    # OLX UA / some Eastern European
    (re.compile(r"^\d{2}\.\d{2}\.\d{4}$"), "%d.%m.%Y"),            # 13.07.2026
]

_MONTH_NAMES: dict[str, int] = {
    # Czech / Slovak
    "ledna":1,"února":2,"března":3,"dubna":4,"května":5,"června":6,
    "července":7,"srpna":8,"září":9,"října":10,"listopadu":11,"prosince":12,
    "januára":1,"februára":2,"marca":3,"apríla":4,"mája":5,"júna":6,
    "júla":7,"augusta":8,"septembra":9,"októbra":10,"novembra":11,"decembra":12,
    # Polish
    "stycznia":1,"lutego":2,"marca":3,"kwietnia":4,"maja":5,"czerwca":6,
    "lipca":7,"sierpnia":8,"września":9,"października":10,"listopada":11,"grudnia":12,
    # Romanian
    "ian":1,"feb":2,"mar":3,"apr":4,"mai":5,"iun":6,
    "iul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
    # Hungarian
    "január":1,"február":2,"március":3,"április":4,"május":5,"június":6,
    "július":7,"augusztus":8,"szeptember":9,"október":10,"november":11,"december":12,
    # Ukrainian
    "січня":1,"лютого":2,"березня":3,"квітня":4,"травня":5,"червня":6,
    "липня":7,"серпня":8,"вересня":9,"жовтня":10,"листопада":11,"грудня":12,
}


def _parse_relative(text: str) -> str:
    """
    Parse relative date strings programmatically.
    Returns ISO date string or "" if not recognised.
    """
    t = text.strip().lower()
    today = _today()

    # "today" / local equivalents
    if t in ("today", "dnes", "ma", "heute", "azi", "dziś", "сьогодні", "днес"):
        return today.strftime("%Y-%m-%d")
    # "today HH:MM" variants — starts with today keyword
    for today_word in ("ma ", "dnes ", "heute ", "today "):
        if t.startswith(today_word):
            return today.strftime("%Y-%m-%d")

    # "yesterday"
    if t in ("yesterday", "včera", "tegnap", "gestern", "ieri", "wczoraj", "вчора", "вчера", "вчера"):
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")

    # "N days/weeks/months ago" — English and common translations
    m = re.search(
        r"(\d+)\s*"
        r"(day|week|month|hour|minute|"          # English
        r"den|dní|dne|týden|týdnů|měsíc|měsíců|"  # Czech
        r"nap|hét|hónap|"                          # Hungarian
        r"zi|zile|săptămână|săptămâni|lună|luni|"  # Romanian
        r"dzień|dni|tydzień|tygodnie|miesięcy|miesiąc|"  # Polish
        r"день|дні|тиждень|тижні|місяць|місяців|"  # Ukrainian
        r"Tag|Tage|Woche|Wochen|Monat|Monate"      # German
        r")",
        t,
    )
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit in ("hour", "minute"):
            return today.strftime("%Y-%m-%d")
        if re.match(r"day|den|dní|dne|nap|zi|zile|dzień|dni|день|дні|tag|tage", unit):
            return (today - timedelta(days=n)).strftime("%Y-%m-%d")
        if re.match(r"week|týden|týdnů|hét|săptămână|săptămâni|tydzień|tygodnie|тиждень|тижні|woche|wochen", unit):
            return (today - timedelta(weeks=n)).strftime("%Y-%m-%d")
        if re.match(r"month|měsíc|měsíců|hónap|lună|luni|miesięcy|miesiąc|місяць|місяців|monat|monate", unit):
            # Approximate: 30 days per month
            return (today - timedelta(days=n * 30)).strftime("%Y-%m-%d")

    # "N minutes/hours ago" → today
    if re.search(r"\d+\s*(min|hour|óra|godz|год)", t):
        return today.strftime("%Y-%m-%d")

    return ""


def _parse_structured(text: str) -> str:
    """Parse structured date strings. Returns ISO date or ""."""
    t = text.strip()
    if not t:
        return ""

    # Unix timestamp (integer seconds since epoch)
    if re.match(r"^\d{10,13}$", t):
        ts = int(t)
        if ts > 1e12:
            ts //= 1000  # milliseconds → seconds
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            return ""

    # ISO 8601 — fast path
    if re.match(r"^\d{4}-\d{2}-\d{2}", t):
        return t[:10]

    # YYYY/MM/DD HH:MM:SS (Vatera)
    if re.match(r"^\d{4}/\d{2}/\d{2}", t):
        return t[:10].replace("/", "-")

    # D.M.YYYY or DD.MM.YYYY (Bazos)
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return ""

    # "13 Jul 2026" or "13 July 2026" style
    m = re.match(r"^(\d{1,2})\s+(\w+)\s+(\d{4})$", t)
    if m:
        day, month_str, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        mo = _MONTH_NAMES.get(month_str)
        if mo:
            try:
                return datetime(year, mo, day).strftime("%Y-%m-%d")
            except ValueError:
                return ""

    return ""


def normalise(raw: str, use_llm: bool = False,
              llm_model: str = "", llm_key: str = "", llm_base: str = "") -> str:
    """
    Normalise any posted-date string to "YYYY-MM-DD".
    Tries programmatic parsing first; falls back to LLM if use_llm=True and a key is set.
    Returns "" if parsing fails.
    """
    if not raw:
        return ""

    t = raw.strip()

    # 1. Try structured parsing
    result = _parse_structured(t)
    if result:
        return result

    # 2. Try relative/keyword parsing
    result = _parse_relative(t)
    if result:
        return result

    # 3. LLM fallback for anything else (e.g. Facebook "25 weeks ago" in user's language)
    if use_llm and llm_key:
        try:
            result = _llm_parse(t, llm_model, llm_key, llm_base)
            if result:
                return result
        except Exception:
            pass

    return ""


def _llm_parse(raw: str, model: str, api_key: str, base_url: str) -> str:
    """Ask the LLM to convert a free-text date to YYYY-MM-DD."""
    from market_scout.llm import _chat
    today_str = _today().strftime("%Y-%m-%d")
    messages = [
        {
            "role": "system",
            "content": (
                f"Today is {today_str}. "
                "Convert the following date expression to ISO format YYYY-MM-DD. "
                "Return ONLY the date string, nothing else. "
                "If you cannot determine the date, return empty string."
            ),
        },
        {"role": "user", "content": raw},
    ]
    result = _chat(messages, model, api_key, base_url).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", result):
        return result
    return ""
