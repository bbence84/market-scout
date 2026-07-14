"""
File output for market-scout search results.

All files are written to ./output/ (created if missing).
Filenames include a UTC timestamp: market-scout_20260712_143022_{format}.{ext}

Each format (except raw JSON) includes a header block with the search metadata
(query, providers, locations, price range, timestamp) so the file is self-documenting.
Console output is always printed regardless of which file formats are saved.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from market_scout.models import Listing

_OUTPUT_DIR = Path("output")


def _flag(country: str) -> str:
    if not country or country == "*":
        return "🌍"
    try:
        return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.upper() if c.isalpha())
    except Exception:
        return ""


def _timestamp() -> str:
    return datetime.now().strftime("%H%M%S")


def _output_path(fmt: str, ext: str) -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    day_dir = _OUTPUT_DIR / today
    day_dir.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    return day_dir / f"market-scout_{ts}.{ext}"


def _meta_lines(meta: dict) -> list[str]:
    """Return human-readable metadata lines for text-based headers."""
    lines = [
        f"Query    : {meta.get('query', '')}",
        f"Providers: {', '.join(meta.get('providers', []))}",
    ]
    if meta.get("locations"):
        lines.append(f"Locations: {', '.join(meta['locations'])}")
    if meta.get("min_price") or meta.get("max_price"):
        lo = meta.get("min_price", "")
        hi = meta.get("max_price", "")
        lines.append(f"Price    : {lo} – {hi}")
    lines.append(f"Run at   : {meta.get('run_at', '')}")
    lines.append(f"Results  : {meta.get('result_count', 0)}")
    return lines


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

def save_json(listings: Sequence[Listing], meta: dict) -> Path:
    """Save full structured JSON including search metadata."""
    path = _output_path("json", "json")
    payload = {
        "meta": meta,
        "results": [lst.to_dict() for lst in listings],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def save_csv(listings: Sequence[Listing], meta: dict) -> Path:
    path = _output_path("csv", "csv")
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig for Excel compat
        # Metadata header as comment rows
        for line in _meta_lines(meta):
            f.write(f"# {line}\n")
        f.write("#\n")

        fieldnames = [
            "no", "title", "price", "currency", "location", "provider",
            "provider_country", "seller", "condition", "posted", "url", "image_url",
            "description", "ai_match", "scraped_at",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, lst in enumerate(listings, 1):
            d = lst.to_dict()
            d["no"] = i
            writer.writerow({k: d.get(k, "") for k in fieldnames})
    return path


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------

def save_txt(listings: Sequence[Listing], meta: dict) -> Path:
    path = _output_path("txt", "txt")
    lines: list[str] = []

    sep = "=" * 72
    lines.append(sep)
    lines.append("  market-scout search results")
    lines.append(sep)
    for line in _meta_lines(meta):
        lines.append(f"  {line}")
    lines.append(sep)
    lines.append("")

    for i, lst in enumerate(listings, 1):
        price_str = f"{lst.currency}{lst.price}" if lst.currency else lst.price
        flag = _flag(lst.provider_country)
        lines.append(f"[{i}] {lst.title or '—'}")
        lines.append(f"    Price    : {price_str or '—'}")
        lines.append(f"    Location : {lst.location or '—'}")
        lines.append(f"    Provider : {lst.provider} {flag}")
        if lst.seller:
            lines.append(f"    Seller   : {lst.seller}")
        if lst.condition:
            lines.append(f"    Condition: {lst.condition}")
        if lst.posted:
            lines.append(f"    Posted   : {lst.posted}")
        lines.append(f"    URL      : {lst.url or '—'}")
        if lst.description:
            # Wrap description at 68 chars
            desc = lst.description[:500].replace("\n", " ")
            lines.append(f"    Desc     : {desc}")
        if lst.ai_match:
            lines.append(f"    AI Match : {lst.ai_match}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>market-scout — {query}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #f5f0e8;
    color: #1a1a1a;
    font-family: "Courier New", Courier, monospace;
    font-size: 13px;
    padding: 32px 40px;
    max-width: 1200px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 18px;
    font-weight: bold;
    letter-spacing: .04em;
    text-transform: uppercase;
    margin-bottom: 6px;
    border-bottom: 2px solid #1a1a1a;
    padding-bottom: 6px;
  }}
  .meta {{
    font-size: 12px;
    color: #555;
    margin-bottom: 24px;
    margin-top: 8px;
    line-height: 1.9;
    border-left: 3px solid #aaa;
    padding-left: 10px;
  }}
  .meta span::before {{ content: "• "; color: #999; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    border: 1px solid #ccc;
  }}
  th {{
    background: #e8e2d6;
    font-family: "Courier New", Courier, monospace;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: .06em;
    padding: 8px 10px;
    text-align: left;
    border-bottom: 2px solid #aaa;
    border-right: 1px solid #ccc;
    white-space: nowrap;
  }}
  td {{
    padding: 7px 10px;
    border-bottom: 1px solid #ddd;
    border-right: 1px solid #e8e2d6;
    vertical-align: top;
  }}
  td:last-child, th:last-child {{ border-right: none; }}
  tr:nth-child(even) td {{ background: #ede8de; }}
  tr:hover td {{ background: #ddd8cc; }}
  .num {{ color: #888; width: 30px; text-align: right; font-size: 11px; }}
  .title {{ max-width: 320px; }}
  .price {{ white-space: nowrap; font-weight: bold; }}
  .provider {{ color: #555; white-space: nowrap; font-size: 12px; }}
  .cond {{ font-size: 12px; color: #666; font-style: italic; }}
  a {{ color: #1a1a1a; text-decoration: underline; }}
  a:hover {{ color: #555; }}
  /* Description tooltip */
  .has-desc {{ position: relative; cursor: help; }}
  .has-desc::after {{
    content: attr(data-desc);
    display: none;
    position: absolute;
    left: 0; top: 100%;
    z-index: 99;
    background: #1a1a1a;
    color: #f5f0e8;
    font-size: 11px;
    font-family: "Courier New", Courier, monospace;
    line-height: 1.5;
    padding: 8px 10px;
    border-radius: 3px;
    width: 340px;
    white-space: pre-wrap;
    word-break: break-word;
    box-shadow: 2px 2px 8px rgba(0,0,0,.35);
  }}
  .has-desc:hover::after {{ display: block; }}
  .desc-dot {{
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: #888;
    margin-left: 4px;
    vertical-align: middle;
    cursor: help;
  }}
  /* AI match badge */
  .ai {{ font-size: 11px; font-weight: bold; white-space: nowrap; cursor: help; }}
  .ai-yes {{ color: #2a7a2a; }}
  .ai-maybe {{ color: #8a6a00; }}
  .ai-no {{ color: #8a0000; }}
  .ai-info {{ font-size: 10px; font-style: normal; opacity: 0.6; }}
  .img-thumb {{
    width: 56px; height: 42px;
    object-fit: cover;
    border: 1px solid #ccc;
    display: block;
  }}
  .no-img {{
    width: 56px; height: 42px;
    background: #e0dbd0;
    border: 1px solid #ccc;
    display: block;
  }}
  footer {{
    margin-top: 18px;
    color: #888;
    font-size: 11px;
    border-top: 1px solid #ccc;
    padding-top: 8px;
  }}
</style>
</head>
<body>
<h1>market-scout &mdash; search results</h1>
<div class="meta">
{meta_html}
</div>
<table>
<thead><tr>
  <th class="num">#</th>
  <th></th>
  <th>Title</th>
  <th>Price</th>
  <th>Location</th>
  <th>Provider</th>
  <th>Seller</th>
  <th>Cond.</th>
  <th>Posted</th>
  <th>AI</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
<footer>market-scout &bull; {run_at}</footer>
</body>
</html>
"""
_TEMPLATE_END_SENTINEL = True  # marks end of template block


def _esc(s: str) -> str:
    """Escape for HTML content (between tags)."""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def _esc_attr(s: str) -> str:
    """
    Escape for HTML attribute values (used in data-* and title= attributes).
    Handles all characters that break attribute parsing, including newlines,
    tabs, quotes, angle brackets, and the full Unicode range.
    """
    return (s.replace("&", "&amp;")
             .replace('"', "&quot;")
             .replace("'", "&#39;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace("\n", "&#10;")
             .replace("\r", "&#13;")
             .replace("\t", "&#9;"))


def save_html(listings: Sequence[Listing], meta: dict,
              original_prices: dict | None = None) -> Path:
    path = _output_path("html", "html")

    meta_parts = [f'<span>Query: {_esc(meta.get("query", ""))}</span>']
    if meta.get("providers"):
        meta_parts.append(f'<span>Providers: {_esc(", ".join(meta["providers"]))}</span>')
    if meta.get("locations"):
        meta_parts.append(f'<span>Locations: {_esc(", ".join(meta["locations"]))}</span>')
    if meta.get("min_price") or meta.get("max_price"):
        lo, hi = meta.get("min_price", ""), meta.get("max_price", "")
        meta_parts.append(f'<span>Price: {lo} &ndash; {hi}</span>')
    if meta.get("target_currency"):
        meta_parts.append(f'<span>Currency: {_esc(meta["target_currency"])} (≈ converted)</span>')
    meta_parts.append(f'<span>Results: {meta.get("result_count", 0)}</span>')
    meta_parts.append(f'<span>Run at: {_esc(meta.get("run_at", ""))}</span>')
    meta_html = "\n".join(meta_parts)

    op = original_prices or {}
    rows_html: list[str] = []
    for i, lst in enumerate(listings, 1):
        # Price cell — show ≈ prefix if converted; tooltip shows original
        raw_price = f"{lst.currency}{lst.price}" if lst.currency else lst.price
        if lst.url in op:
            orig_price, orig_currency = op[lst.url]
            orig_display = f"{orig_currency}{orig_price}" if orig_currency else orig_price
            tooltip = _esc_attr(f"Original: {orig_display}")
            price_cell = f'<span title="{tooltip}">≈{_esc(raw_price)}</span>'
        else:
            price_cell = _esc(raw_price) or "—"
        flag = _flag(lst.provider_country)
        img_cell = (
            f'<img class="img-thumb" src="{_esc_attr(lst.image_url)}" alt="" loading="lazy">'
            if lst.image_url else '<span class="no-img"></span>'
        )

        # Title cell: link with description tooltip when description exists
        title_text = _esc(lst.title or "—")
        if lst.description and lst.url:
            # Truncate description for tooltip (browser/CSS attr() can handle long text)
            desc_preview = _esc_attr(lst.description[:600])
            title_cell = (
                f'<span class="has-desc" data-desc="{desc_preview}">'
                f'<a href="{_esc_attr(lst.url)}">{title_text}</a>'
                f'<span class="desc-dot" title="Has description"></span>'
                f'</span>'
            )
        elif lst.description:
            desc_preview = _esc_attr(lst.description[:600])
            title_cell = (
                f'<span class="has-desc" data-desc="{desc_preview}">'
                f'{title_text}'
                f'<span class="desc-dot" title="Has description"></span>'
                f'</span>'
            )
        elif lst.url:
            title_cell = f'<a href="{_esc_attr(lst.url)}">{title_text}</a>'
        else:
            title_cell = title_text

        # AI match cell — verdict as coloured text, full reason on hover
        ai_raw = lst.ai_match or ""
        if ai_raw:
            upper = ai_raw.upper()
            if upper.startswith("YES"):
                verdict, cls = "YES", "ai-yes"
            elif upper.startswith("NO"):
                verdict, cls = "NO", "ai-no"
            else:
                verdict, cls = "MAYBE", "ai-maybe"
            reason = ai_raw.split(" — ", 1)[1] if " — " in ai_raw else ""
            if reason:
                ai_cell = (
                    f'<span class="ai {cls}" title="{_esc_attr(reason)}">'
                    f'{verdict} <span class="ai-info">ⓘ</span>'
                    f'</span>'
                )
            else:
                ai_cell = f'<span class="ai {cls}">{verdict}</span>'
        else:
            ai_cell = '<span style="color:#bbb">—</span>'

        rows_html.append(
            f"<tr>"
            f'<td class="num">{i}</td>'
            f"<td>{img_cell}</td>"
            f'<td class="title">{title_cell}</td>'
            f'<td class="price">{price_cell}</td>'
            f"<td>{_esc(lst.location or '—')}</td>"
            f'<td class="provider">{_esc(lst.provider)} {flag}</td>'
            f"<td>{_esc(lst.seller or '—')}</td>"
            f'<td class="cond">{_esc(lst.condition or "—")}</td>'
            f"<td>{_esc(lst.posted or '—')}</td>"
            f"<td>{ai_cell}</td>"
            f"</tr>"
        )

    html = _HTML_TEMPLATE.format(
        query=_esc(meta.get("query", "")),
        meta_html=meta_html,
        rows="\n".join(rows_html),
        run_at=_esc(meta.get("run_at", "")),
    )
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def save(
    format_name: str,
    listings: Sequence[Listing],
    meta: dict,
    original_prices: dict | None = None,
) -> Path | None:
    """
    Save listings to a timestamped file in ./output/.
    format_name: one of "json", "csv", "txt", "html"
    original_prices: {url -> (original_price_str, original_currency)} for converted prices
    Returns the Path written, or None if format_name is unknown.
    """
    fmt = format_name.lower().strip()
    op = original_prices or {}
    if fmt == "json":
        return save_json(listings, meta)
    elif fmt == "csv":
        return save_csv(listings, meta)
    elif fmt == "txt":
        return save_txt(listings, meta)
    elif fmt in ("html", "web"):
        return save_html(listings, meta, original_prices=op)
    return None
