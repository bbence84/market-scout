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
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>market-scout — {query}</title>
<style>
  :root {{
    --bg: #f8f9fa;
    --surface: #ffffff;
    --surface2: #f1f3f5;
    --border: #e0e4e8;
    --border-strong: #c8cdd3;
    --text: #1a1d21;
    --text-muted: #6c737a;
    --text-subtle: #9aa0a8;
    --accent: #4f7ef7;
    --accent-hover: #3a68e0;
    --row-hover: #eef2ff;
    --th-bg: #f1f3f5;
    --tag-bg: #e8edf5;
    --tag-text: #3d5a99;
    --yes: #1a7f3c;
    --yes-bg: #d4edda;
    --maybe: #7a5c00;
    --maybe-bg: #fff3cd;
    --no: #9e1c1c;
    --no-bg: #fde8e8;
    --thumb-bg: #e8edf5;
    --tooltip-bg: #1a1d21;
    --tooltip-text: #f8f9fa;
    --shadow: 0 1px 3px rgba(0,0,0,.08), 0 4px 12px rgba(0,0,0,.06);
    --radius: 10px;
  }}
  [data-theme="dark"] {{
    --bg: #0f1117;
    --surface: #1a1d23;
    --surface2: #22262f;
    --border: #2e333d;
    --border-strong: #404650;
    --text: #e8eaf0;
    --text-muted: #8b92a0;
    --text-subtle: #5a6170;
    --accent: #6b93ff;
    --accent-hover: #8aaaff;
    --row-hover: #1e2340;
    --th-bg: #1e2129;
    --tag-bg: #1e2a45;
    --tag-text: #7aaaf5;
    --yes: #4caf73;
    --yes-bg: #0d2e1a;
    --maybe: #e0a830;
    --maybe-bg: #2a1e00;
    --no: #e05555;
    --no-bg: #2e0d0d;
    --thumb-bg: #1e2333;
    --tooltip-bg: #e8eaf0;
    --tooltip-text: #1a1d23;
    --shadow: 0 1px 3px rgba(0,0,0,.3), 0 4px 12px rgba(0,0,0,.25);
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif;
    font-size: 13.5px;
    line-height: 1.5;
    padding: 28px 32px 48px;
    max-width: 1280px;
    margin: 0 auto;
    transition: background .2s, color .2s;
  }}
  /* ── Header ── */
  .header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 20px;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--border);
  }}
  .logo {{
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .logo-icon {{
    width: 30px; height: 30px;
    background: var(--accent);
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    color: #fff;
    font-size: 15px;
    font-weight: 700;
    flex-shrink: 0;
  }}
  h1 {{
    font-size: 17px;
    font-weight: 600;
    letter-spacing: -.01em;
    color: var(--text);
  }}
  h1 span {{ color: var(--text-muted); font-weight: 400; }}
  /* ── Theme toggle ── */
  .theme-btn {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 5px 12px;
    font-size: 12px;
    color: var(--text-muted);
    cursor: pointer;
    display: flex; align-items: center; gap: 6px;
    transition: background .15s, color .15s;
    white-space: nowrap;
  }}
  .theme-btn:hover {{ background: var(--border); color: var(--text); }}
  .theme-icon {{ font-size: 14px; }}
  /* ── Meta pills ── */
  .meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 20px;
  }}
  .meta span {{
    background: var(--tag-bg);
    color: var(--tag-text);
    border-radius: 20px;
    padding: 3px 10px;
    font-size: 11.5px;
    font-weight: 500;
    letter-spacing: .01em;
  }}
  /* ── Table ── */
  .table-wrap {{
    border-radius: var(--radius);
    border: 1px solid var(--border);
    overflow: hidden;
    box-shadow: var(--shadow);
    background: var(--surface);
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
  }}
  th {{
    background: var(--th-bg);
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .07em;
    color: var(--text-muted);
    padding: 9px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  td {{
    padding: 9px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
  }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: var(--row-hover); }}
  .num {{
    color: var(--text-subtle);
    width: 28px;
    text-align: right;
    font-size: 11px;
    padding-right: 6px;
  }}
  .title {{ max-width: 300px; }}
  .title a {{
    color: var(--text);
    text-decoration: none;
    font-weight: 500;
  }}
  .title a:hover {{ color: var(--accent); }}
  .price {{
    white-space: nowrap;
    font-weight: 600;
    color: var(--text);
    font-size: 13px;
  }}
  .provider {{
    white-space: nowrap;
    font-size: 12px;
    color: var(--text-muted);
  }}
  .cond {{
    font-size: 11.5px;
    color: var(--text-muted);
  }}
  .posted {{
    font-size: 11.5px;
    color: var(--text-subtle);
    white-space: nowrap;
  }}
  /* ── Description tooltip ── */
  .has-desc {{ position: relative; }}
  .has-desc::after {{
    content: attr(data-desc);
    display: none;
    position: absolute;
    left: 0; top: calc(100% + 4px);
    z-index: 99;
    background: var(--tooltip-bg);
    color: var(--tooltip-text);
    font-size: 12px;
    line-height: 1.55;
    padding: 10px 12px;
    border-radius: 8px;
    width: 360px;
    white-space: pre-wrap;
    word-break: break-word;
    box-shadow: 0 4px 16px rgba(0,0,0,.25);
    pointer-events: none;
  }}
  .has-desc:hover::after {{ display: block; }}
  .desc-dot {{
    display: inline-block;
    width: 5px; height: 5px;
    border-radius: 50%;
    background: var(--accent);
    margin-left: 5px;
    vertical-align: middle;
    opacity: .6;
    cursor: help;
  }}
  /* ── AI badge ── */
  .ai {{
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-size: 11px;
    font-weight: 600;
    border-radius: 4px;
    padding: 2px 7px;
    white-space: nowrap;
    cursor: help;
  }}
  .ai-yes  {{ color: var(--yes);   background: var(--yes-bg);   }}
  .ai-maybe{{ color: var(--maybe); background: var(--maybe-bg); }}
  .ai-no   {{ color: var(--no);    background: var(--no-bg);    }}
  .ai-info {{ opacity: .55; font-size: 10px; }}
  /* ── Thumbnail ── */
  .img-thumb {{
    width: 60px; height: 46px;
    object-fit: cover;
    border-radius: 6px;
    border: 1px solid var(--border);
    display: block;
  }}
  .no-img {{
    width: 60px; height: 46px;
    background: var(--thumb-bg);
    border-radius: 6px;
    border: 1px solid var(--border);
    display: block;
  }}
  /* ── Footer ── */
  footer {{
    margin-top: 20px;
    color: var(--text-subtle);
    font-size: 11.5px;
    text-align: right;
  }}
</style>
</head>
<body>
<div class="header">
  <div class="logo">
    <div class="logo-icon">M</div>
    <h1>market-scout <span>&mdash; search results</span></h1>
  </div>
  <button class="theme-btn" onclick="toggleTheme()" id="themeBtn">
    <span class="theme-icon">🌙</span><span id="themeLbl">Dark</span>
  </button>
</div>
<div class="meta">
{meta_html}
</div>
<div class="table-wrap">
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
</div>
<footer>market-scout &bull; {run_at}</footer>
<script>
  (function() {{
    var stored = localStorage.getItem('ms-theme');
    if (stored) {{ document.documentElement.setAttribute('data-theme', stored); updateBtn(stored); }}
  }})();
  function toggleTheme() {{
    var cur = document.documentElement.getAttribute('data-theme');
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('ms-theme', next);
    updateBtn(next);
  }}
  function updateBtn(theme) {{
    var icon = document.getElementById('themeIcon');
    var lbl  = document.getElementById('themeLbl');
    if (!lbl) return;
    if (theme === 'dark') {{ document.querySelector('.theme-icon').textContent = '☀️'; lbl.textContent = 'Light'; }}
    else                  {{ document.querySelector('.theme-icon').textContent = '🌙'; lbl.textContent = 'Dark';  }}
  }}
</script>
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
