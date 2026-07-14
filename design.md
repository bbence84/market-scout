# market-scout — Technical Design

This document covers the internal architecture, data flow, provider interfaces, and implementation details.
For usage instructions see [README.md](README.md). To add a new provider see [adding-a-provider.md](adding-a-provider.md).

---

## Architecture

```
market-scout/
  market_scout/
    cli.py          # typer app — all commands
    config.py       # ~/.market-scout/config.toml loader/writer
    llm.py          # OpenRouter client — translation, suggestions, AI analysis
    models.py       # Listing dataclass (provider-agnostic)
    output.py       # Rich table + JSON console rendering
    save.py         # File output — JSON, CSV, TXT, HTML (timestamped)
    dates.py        # Date normalisation across provider formats → ISO YYYY-MM-DD
    providers/
      __init__.py             # PROVIDERS dict, resolve_providers()
      base.py                 # SearchRequest dataclass + BaseProvider Protocol
      worldwide/facebook/     # Playwright stealth, location-parameterized
        provider.py           #   orchestrates per-city scraping
        scraper.py            #   Playwright session, anti-bot, detail page fetch
        config.py             #   FbScraperConfig (URL params, cookies path)
        models.py             #   FbListing internal dataclass
        location_db.py        #   resolve_locations(), list_countries/cities
        locations.json        #   30 countries, ~110 cities, radii, fb_ids
      hu/hardverapro/         # Playwright + BS4 (JS cookie challenge, auto-solved)
      hu/jofogas/             # httpx + embedded JSON regex
      hu/vatera/              # httpx + BS4 data-gtm-* attrs
      de/kleinanzeigen/       # curl_cffi + private Android JSON API
      fr/leboncoin/           # httpx mobile JSON API (no auth)
      it/subito/              # curl_cffi + __NEXT_DATA__ HTML parsing
      at/willhaben/           # httpx JSON API (x-wh-client header)
      at/shpock/              # httpx GraphQL API (Austria-anchored)
      multi/bazos/            # httpx + BS4 (CZ + SK, same platform)
      multi/allegro/          # Playwright persistent profile (PL/CZ/SK, DataDome)
        scraper.py            #   shared scraper logic
        provider_pl/cz/sk.py  #   thin per-country wrappers
      multi/bazos/            # httpx + BS4 (CZ + SK, same platform)
        scraper.py            #   shared scraper logic
        provider_cz/sk.py     #   thin per-country wrappers
      multi/olx/              # curl_cffi + public REST API (UA/PL/RO/PT/BG)
        scraper.py            #   shared scraper logic
        provider_*.py         #   thin per-country wrappers
      multi/wallapop/         # httpx REST API, geo-filtered (ES/IT/PT/GB)
```

---

## Data flow

```
CLI (cli.py)
  │  loads ~/.market-scout/config.toml (defaults)
  │  (--suggest-queries) → llm.py → OpenRouter → user approves variants
  │  (--translate-to)    → llm.py → OpenRouter → user approves translation
  │  builds SearchRequest per query
  ▼
Provider.search(req)          → list[Listing]
  │  (--details)              → provider fetches detail pages → description field
  │  (--translate-results)    → llm.py → titles + conditions translated in batch
  │  (--details-ai)           → llm.py → per-listing YES/MAYBE/NO confidence score
  ▼
output.py  → Rich table (OSC 8 clickable links, country flags) or JSON
save.py    → output/YYYY-MM-DD/market-scout_HHMMSS.{json|csv|txt|html}
```

---

## Core interfaces

### SearchRequest (`providers/base.py`)

```python
@dataclass
class SearchRequest:
    query: str
    locations: list[str]      # raw tokens: country codes, city slugs, or numeric IDs
    min_price: int | None
    max_price: int | None
    max_results: int          # per city (Facebook) or per page-run (others)
    cookies_file: Path | None
    headless: bool
    scrape_details: bool
    radius_km: int            # 0 = use provider defaults
    debug: bool
```

### BaseProvider (`providers/base.py`)

```python
class BaseProvider(Protocol):
    name: str
    countries: list[str]  # ISO codes e.g. ["HU"], ["DE","AT"], or ["*"] for global
    def search(self, req: SearchRequest) -> list[Listing]: ...
```

### Listing (`models.py`)

```python
@dataclass
class Listing:
    provider: str
    provider_country: str   # ISO code, or "*" for global
    title: str
    price: str
    currency: str
    location: str
    url: str
    image_url: str
    description: str
    seller: str
    condition: str
    posted: str             # YYYY-MM-DD (normalised by dates.py)
    ai_match: str           # "YES — reason" / "MAYBE — reason" / "NO — reason"
    scraped_at: str         # ISO timestamp
```

---

## Provider registry and country resolution

`providers/__init__.py` contains the `PROVIDERS` dict and `resolve_providers()`.

`resolve_providers(["HU"])` returns all providers whose `countries` list contains `"HU"`, plus all `countries=["*"]` providers (Facebook). A two-letter code that matches no provider passes through unchanged so the CLI can report the error.

---

## Scraping approach by site type

| Site type | Library | Example |
|-----------|---------|---------|
| Plain HTML, no JS | `httpx` + `BeautifulSoup` | vatera, bazos |
| JS cookie challenge (no human) | Playwright `networkidle` | hardverapro |
| SPA / stealth (no login) | Playwright + stealth + browserforge | facebook |
| DataDome / Cloudflare (CAPTCHA once) | Playwright persistent profile | allegro |
| TLS fingerprint block (CloudFront/Akamai) | `curl_cffi` `impersonate="chrome120"` | kleinanzeigen, olx, subito |
| GraphQL endpoint | `httpx` POST | shpock |
| Mobile JSON API | `httpx` POST | leboncoin |
| Public REST API | `httpx` or `curl_cffi` | olx, wallapop, willhaben |
| Embedded JSON in HTML (`__NEXT_DATA__`) | `curl_cffi` + regex | subito |
| Embedded JSON in HTML (fragments) | `httpx` + regex split | jofogas |

---

## Facebook location system

`providers/worldwide/facebook/locations.json` — 30 countries, ~110 cities, per-city default radii and known numeric IDs.

- Smaller cities often don't have a recognised slug on FB → silent redirect to `/category/search/`, dropping the location filter
- `locations.json` stores `fb_id` for known cities; the resolver prefers it over the slug
- `market-scout find-location <slug>` opens a browser to discover a numeric ID
- `resolve_locations()` deduplicates by numeric ID across calls

---

## Date normalisation (`dates.py`)

All provider `posted` fields are normalised to `YYYY-MM-DD` via `dates.normalise()`:
- ISO datetimes → truncated to date
- Unix timestamps (Jofogas) → converted
- Bazos format `D.M.YYYY` → normalised
- Relative strings (`"ma 14:43"` = today, `"tegnap"` = yesterday, `"3 days ago"`) → computed
- Unparseable strings (e.g. `"Előresorolva"` = promoted) → `""`
- LLM fallback for free-form strings (Facebook relative dates in user's language)

---

## LLM integration (`llm.py`)

All LLM calls go through [OpenRouter](https://openrouter.ai). Default model: `anthropic/claude-haiku-4-5`.

| Function | Purpose |
|----------|---------|
| `translate_query()` | Translate search query before searching |
| `suggest_queries()` | Suggest alternative terms (returns JSON array) |
| `translate_listings()` | Batch-translate titles + conditions (chunks of 30) |
| `analyse_listing()` | YES/MAYBE/NO confidence score for a single listing |

`translate_listings()` skips listings from providers whose `provider_country` language already matches `user_lang` (e.g. Hungarian listings are not translated when `user_lang = "hu"`).

---

## File output (`save.py`)

Files are written to `output/YYYY-MM-DD/market-scout_HHMMSS.{ext}` (local time).

| Format | Content |
|--------|---------|
| `json` | Full structured JSON with `meta` + `results` (includes `description`, `ai_match`) |
| `csv` | UTF-8 BOM CSV (Excel-compatible), metadata as `#` comment rows |
| `txt` | Human-readable numbered list with all fields |
| `html` | Light typewriter-font table; description as hover tooltip; AI badge with reasoning on hover |

---

## Provider initialisation

Some providers require a one-time human action (CAPTCHA solve or Facebook login) before headless use. See `_INIT_PROVIDERS` in `cli.py` and the `market-scout init` command.

| Provider | Mechanism | Session stored at |
|----------|-----------|-------------------|
| `facebook` | Browser login | `cookies.json` |
| `allegro_pl/cz/sk` | DataDome CAPTCHA | `~/.market-scout/allegro-profile/{pl\|cz\|sk}/` |

All other providers work headlessly without any initialisation.

---

## Global configuration (`~/.market-scout/config.toml`)

Created automatically on first run. Key settings:

| Key | Default | Description |
|-----|---------|-------------|
| `providers` | `[]` (all) | Default provider list |
| `location` | `""` | Default FB location |
| `radius` | `0` | Default FB search radius in km |
| `max_results` | `30` | Per provider/city |
| `headless` | `true` | Run FB browser headlessly |
| `cookies` | `""` | Path to FB cookies JSON file |
| `user_lang` | `"en"` | Auto-translate results to this language |
| `openrouter.api_key` | `""` | Set once; also via `OPENROUTER_API_KEY` env var |
| `openrouter.model` | `"anthropic/claude-haiku-4-5"` | LLM model |
| `openrouter.base_url` | `"https://openrouter.ai/api/v1"` | OpenRouter endpoint (rarely needs changing) |

---

## CLAUDE.md

Project-level notes for AI coding assistants (Claude Code) are in [CLAUDE.md](CLAUDE.md). Covers:
- Provider initialisation requirements
- Provider folder conventions
- Anti-bot patterns encountered per site
- Country code → provider expansion table
- README maintenance rules

---

## Planned extensions

### Output folder, run IDs, and multi-search runs

Currently results only exist for the duration of a single run. A persistent output layer would enable:

**Named output folder:**
```bash
market-scout search --query "Amiga 500" --location DE,HU --out ./searches/amiga
# Writes: ./searches/amiga/<run_id>/results.json
#         ./searches/amiga/<run_id>/results.csv
#         ./searches/amiga/<run_id>/meta.json   (query, providers, date, run_id)
```

**Run ID** — auto-generated timestamp-based ID (`20260711-143022`) or user-supplied (`--run-id amiga-de-sweep`).

**Multi-search profile run:**
```bash
market-scout run --profile amiga      # runs all searches defined in market-scout.toml
market-scout run --all
market-scout run --all --out ./daily
```

**New/flagged filtering:**
```bash
market-scout search --query "Amiga 500" --only-new   # skip URLs seen in any previous run
market-scout flag <url>                               # mark a listing as dismissed
market-scout search --query "Amiga 500" --hide-flagged
```

Storage backend: SQLite (`~/.market-scout/history.db`) via the `sqlite3` stdlib.

---

### Saved search profiles (TOML config)

```toml
# market-scout.toml

[search.amiga]
query = "Amiga 500"
locations = ["DE", "AT", "HU", "PL"]
min_price = 50
max_price = 600
providers = ["facebook", "hardverapro", "jofogas", "vatera"]

[search.c64]
query = "Commodore 64"
locations = ["DE", "AT", "CH"]
max_results = 20
providers = ["facebook"]
```

Run with: `market-scout run amiga` or `market-scout run --all`.

---

### Scheduled runs (cron / watch mode)

```bash
market-scout watch --query "Amiga 500" --location DE,HU --interval 30m
market-scout watch --profile amiga --interval 2h --notify email
```

Cron (functional today with JSON output piped to a script):
```cron
0 */4 * * *  cd ~/market-scout && .venv/bin/market-scout search --query "Amiga 500" --provider hardverapro --only-new --notify pushbullet >> ~/market-scout/logs/amiga.log 2>&1
```

---

### Notifications

When new listings are found (watch/cron mode or `--notify`):

| Backend | Flag | Notes |
|---------|------|-------|
| Desktop | `--notify desktop` | via `plyer` (Windows/macOS/Linux) |
| Email | `--notify email` | stdlib `smtplib`; `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` env vars |
| Pushbullet | `--notify pushbullet` | `PUSHBULLET_API_KEY` env var |
| WhatsApp | `--notify whatsapp` | WhatsApp Business Cloud API; `WHATSAPP_TOKEN` env var |
| Telegram | `--notify telegram` | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` |
| ntfy.sh | `--notify ntfy` | Self-hostable, no account needed for public topics |
| Log file | `--notify log` | `--notify-log ./alerts.txt` |

Multiple backends: `--notify "pushbullet,email"`.

---

### MCP server

Expose market-scout as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server so AI assistants can call it as a tool:

```bash
market-scout mcp serve --port 8765
```

Implementation: `mcp` Python package. Each `@tool` maps to a provider's `search()` method. Reference: [kukshaus/magyar-elado-mcp](https://github.com/kukshaus/magyar-elado-mcp) shows this pattern for the Hungarian providers.