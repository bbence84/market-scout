"""
Jofogas.hu provider — general Hungarian classifieds (OLX-owned).

Strategy from kukshaus/magyar-elado-mcp (MIT):
  The search results page embeds listing data as JSON fragments inside the HTML.
  We split the raw HTML on '"list_id":' and regex-extract fields from each chunk.
  No browser required; a single httpx request per page is enough.
  No login required for anonymous search.

Pagination: not supported by the site in a clean way — results page is a single
SPA-style page; we collect up to max_results from one fetch.
"""
from __future__ import annotations

import json
import re
import time
import random

import httpx

from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

_SEARCH = "https://www.jofogas.hu/magyarorszag"

# Regex patterns for extracting fields from each JSON chunk
_RE_URL     = re.compile(r'"url":"(https:(?:[^"\\]|\\.)+?\.htm)"')
_RE_SUBJECT = re.compile(r'"subject":"((?:[^"\\]|\\.)*?)"')
_RE_PRICE   = re.compile(r'"price":\{"label":"([^"]+)"')
_RE_COMPANY = re.compile(r'"company_ad":(true|false)')
_RE_REGION  = re.compile(r'"region":\{"label":"([^"]+)"')
_RE_USER    = re.compile(r'"user_name":"((?:[^"\\]|\\.)*?)"')
_RE_IMAGE   = re.compile(r'"images":\[\{"mime_type":"[^"]+","name":"[^"]+","extension_name":"[^"]+","url":"(https://img\.jofogas\.hu/thumbs/[^"]+)"')

# Jofogas prices: "340 000 Ft", "5 500 Ft", "Ingyenes", etc.
_RE_DIGITS  = re.compile(r'[\d\s]+')


def _parse_price(label: str) -> tuple[str, str]:
    """Return (amount_str, currency). Strips whitespace from number."""
    label = label.strip()
    if not label or label.lower() in ("ingyenes", "0 ft"):
        return label, "HUF"
    # "340 000 Ft" → "340000"
    m = _RE_DIGITS.match(label)
    if m:
        amount = m.group(0).replace(" ", "").replace("\xa0", "")
        return amount, "HUF"
    return label, "HUF"


def _make_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


class JofogasProvider:
    name = "jofogas"
    countries = ["HU"]

    def search(self, req: SearchRequest) -> list[Listing]:
        """
        Search jofogas.hu. Location tokens are ignored (site is Hungary-only).
        Fetches one page (jofogas embeds all results in a single page response).
        """
        results: list[Listing] = []
        seen_urls: set[str] = set()

        params = {"q": req.query}
        if req.min_price:
            params["ar_tol"] = str(req.min_price)
        if req.max_price:
            params["ar_ig"] = str(req.max_price)

        if req.debug:
            url = _SEARCH + "?" + "&".join(f"{k}={v}" for k, v in params.items())
            print(f"[jofogas] GET {url}", flush=True)

        try:
            with httpx.Client(headers=_make_headers(), follow_redirects=True, timeout=20) as client:
                resp = client.get(_SEARCH, params=params)
                resp.raise_for_status()
        except Exception as exc:
            print(f"[jofogas] HTTP error: {exc}", flush=True)
            return results

        if req.debug:
            print(f"[jofogas] Final URL: {resp.url}", flush=True)
            print(f"[jofogas] Response size: {len(resp.text)} bytes", flush=True)

        html = resp.text
        chunks = html.split('"list_id":')[1:]  # first element is before any listing

        if req.debug:
            print(f"[jofogas] JSON chunks found: {len(chunks)}", flush=True)

        for chunk in chunks:
            if len(results) >= req.max_results:
                break

            m_url     = _RE_URL.search(chunk)
            m_subject = _RE_SUBJECT.search(chunk)
            m_price   = _RE_PRICE.search(chunk)
            m_region  = _RE_REGION.search(chunk)
            m_user    = _RE_USER.search(chunk)
            m_image   = _RE_IMAGE.search(chunk)

            if not m_url or not m_subject or not m_price:
                continue

            try:
                url   = json.loads(f'"{m_url.group(1)}"')
                title = json.loads(f'"{m_subject.group(1)}"')
            except (json.JSONDecodeError, ValueError):
                continue

            if url in seen_urls:
                continue
            seen_urls.add(url)

            amount, currency = _parse_price(m_price.group(1))

            location = m_region.group(1) if m_region else ""
            try:
                seller = json.loads(f'"{m_user.group(1)}"') if m_user else ""
            except (json.JSONDecodeError, ValueError):
                seller = m_user.group(1) if m_user else ""
            image_url = m_image.group(1) if m_image else ""

            results.append(Listing(
                provider="jofogas",
                provider_country="HU",
                title=title,
                price=amount,
                currency=currency,
                location=location,
                url=url,
                image_url=image_url,
                description="",
                seller=seller,
                condition="",
                posted="",
            ))

        if req.debug:
            print(f"[jofogas] Parsed {len(results)} listing(s)", flush=True)

        return results
