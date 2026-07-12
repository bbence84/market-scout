# market-scout

A CLI tool for searching product marketplaces across Europe (and beyond). Built for finding rare items — retro computers, vintage collectibles, obscure parts — across multiple countries at once. The backend is modular: providers are independent plugins, so new marketplaces can be added without touching the core.

**Current providers:** Facebook Marketplace (Playwright stealth browser), Hardverapró (Hungarian tech classifieds, httpx + BeautifulSoup)

---

## Contents

- [Quick start](#quick-start)
- [CLI reference](#cli-reference)
- [How location search works](#how-location-search-works)
- [Getting Facebook cookies](#getting-facebook-cookies)
- [Architecture](#architecture)
- [Adding a new provider](#adding-a-new-provider)
- [Planned extensions](#planned-extensions)
  - [LLM query translation and alternative query suggestions](#llm-query-translation-and-alternative-query-suggestions)
  - [LLM result translation](#llm-result-translation)
  - [Output folder, run IDs, and multi-search runs](#output-folder-run-ids-and-multi-search-runs)
  - [Saved search profiles](#saved-search-profiles-toml-config)
  - [Scheduled runs and cron](#scheduled-runs-cron--watch-mode)
  - [Notifications](#notifications)
  - [MCP server](#mcp-server)
  - [Provider country metadata](#provider-country-metadata-and-output)
  - [More providers and implementation guide](#more-providers-and-provider-implementation-guide)
  - [Price currency normalisation](#price-currency-normalisation)

---

## Quick start

```bash
cd c:\SAPDevelop\market-scout

# First time only
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\playwright install chromium

# Search Facebook (auto-detect your location from FB account)
.venv\Scripts\market-scout search --query "Amiga 500"

# Search Hardverapró (Hungarian tech classifieds, no login required)
.venv\Scripts\market-scout search --query "Amiga 500" --provider hardverapro

# Search both providers at once
.venv\Scripts\market-scout search --query "Amiga 500" --provider "facebook,hardverapro" --location HU --cookies cookies.json

# Search across Germany + Austria on Facebook, with per-city radius from the built-in DB
.venv\Scripts\market-scout search --query "Amiga 500" --location DE,AT --cookies cookies.json

# Preview what cities would be searched, without running anything
.venv\Scripts\market-scout search --query "C64" --location DE,AT,budapest --dry-run
```

On Windows, prefix commands with `PYTHONIOENCODING=utf-8` if you see encoding errors with city names:
```bash
PYTHONIOENCODING=utf-8 .venv\Scripts\market-scout locations
```

---

## CLI reference

### `market-scout search`

The main command. Runs one browser/HTTP session per resolved city, merges and deduplicates results by URL.

```
market-scout search [OPTIONS]
```

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--query` | `-q` | TEXT | **required** | Search term |
| `--provider` | `-p` | TEXT | `facebook` | Provider(s), comma-separated. Run `market-scout providers` to list all. |
| `--location` | `-l` | TEXT | *(empty)* | Country code(s) or city slug(s), comma-separated. See [location section](#how-location-search-works). Ignored by Hardverapró (Hungary-only). |
| `--min-price` | | INT | | Minimum price filter (passed to the marketplace) |
| `--max-price` | | INT | | Maximum price filter |
| `--max-results` | `-n` | INT | `30` | Max listings to collect **per city search** |
| `--cookies` | `-c` | PATH | | Path to Facebook cookies JSON file |
| `--headless` / `--no-headless` | | flag | headless | Run Chromium visibly (`--no-headless`) for debugging or first-time FB login |
| `--details` / `--no-details` | | flag | no-details | Open each FB listing's detail page for full description, seller name, and condition |
| `--radius` | | INT | `0` | Override search radius in km for all FB cities. `0` = use DB defaults for country expansions, FB default (~40 km) for bare city slugs |
| `--translate-to` | | TEXT | | *(stub)* Target language for query/results translation — not yet implemented |
| `--output` | `-o` | `table`\|`json` | `table` | Output format |
| `--dry-run` | | flag | | Show resolved city/radius plan without scraping |
| `--debug` | | flag | | Print provider-level debug info: URLs fetched, redirect chain, response size, first result title |

**Examples:**

```bash
# Single city, auto radius (Facebook)
market-scout search --query "Amiga 500" --location berlin

# Whole country — expands to 8 German cities with tuned radii from the DB
market-scout search --query "C64" --location DE --cookies cookies.json

# Multiple countries — expands to all cities in each, deduplicates across them
market-scout search --query "Spectrum ZX" --location DE,AT,HU,PL --cookies cookies.json

# Mix: country expansion + explicit city not in the DB
market-scout search --query "retro computer" --location "DE,vienna,warsaw" --cookies cookies.json

# Override radius for every city (ignores DB defaults)
market-scout search --query "Amiga" --location DE,AT --radius 200 --cookies cookies.json

# Price range + detail pages + JSON output (Facebook)
market-scout search \
  --query "Amiga 500" \
  --location DE,AT,HU \
  --min-price 50 --max-price 500 \
  --details \
  --output json \
  --cookies cookies.json

# Visible browser for debugging (useful when FB shows a login wall)
market-scout search --query "C64" --location berlin --no-headless --cookies cookies.json

# Dry run: see the expansion plan before committing to a long scrape
market-scout search --query "Spectrum" --location DE,AT,PL,HU --dry-run

# Hardverapró — Hungarian tech classifieds, nationwide, no cookies needed
market-scout search --query "Amiga 500" --provider hardverapro --max-results 30

# Hardverapró with price filter
market-scout search --query "C64" --provider hardverapro --min-price 5000 --max-price 100000

# Debug: verify the search URL and whether the query is being applied
market-scout search --query "Amiga 500" --provider hardverapro --debug
```

---

### `market-scout locations`

Browse the built-in European location database (Facebook provider only).

```bash
# List all 30 supported countries
market-scout locations

# Show cities for a specific country (with slugs, FB IDs where known, and default radii)
market-scout locations DE
market-scout locations HU
```

**Sample output for `market-scout locations HU`:**
```
         Cities for HU (Facebook slugs)
┌──────────┬──────────┬───────────────────┬─────────────────┐
│ Slug     │ Name     │ Default radius km │ FB ID (if known)│
├──────────┼──────────┼───────────────────┼─────────────────┤
│ budapest │ Budapest │ 150               │                 │
│ debrecen │ Debrecen │ 100               │                 │
│ pecs     │ Pécs     │ 80                │ 110889042346085 │
│ gyor     │ Győr     │ 80                │ 109233199097493 │
│ miskolc  │ Miskolc  │ 80                │ 111617528847006 │
└──────────┴──────────┴───────────────────┴─────────────────┘
Usage: --location HU   (expands to all 5 cities)
```

When a city has an `FB ID`, that numeric ID is used in the search URL instead of the slug — numeric IDs always work, while slugs for smaller cities may be silently ignored by Facebook.

**Supported countries (30):**

| Code | Country | Cities |
|------|---------|--------|
| AT | Austria | 5 |
| BE | Belgium | 4 |
| BG | Bulgaria | 3 |
| CH | Switzerland | 4 |
| CZ | Czech Republic | 3 |
| DE | Germany | 8 |
| DK | Denmark | 3 |
| EE | Estonia | 2 |
| ES | Spain | 7 |
| FI | Finland | 4 |
| FR | France | 8 |
| GB | United Kingdom | 8 |
| GR | Greece | 3 |
| HR | Croatia | 3 |
| HU | Hungary | 5 |
| IE | Ireland | 3 |
| IT | Italy | 9 |
| LT | Lithuania | 2 |
| LU | Luxembourg | 1 |
| LV | Latvia | 2 |
| NL | Netherlands | 5 |
| NO | Norway | 4 |
| PL | Poland | 7 |
| PT | Portugal | 3 |
| RO | Romania | 5 |
| RS | Serbia | 2 |
| SE | Sweden | 5 |
| SI | Slovenia | 2 |
| SK | Slovakia | 3 |
| UA | Ukraine | 3 |

---

### `market-scout find-location`

Look up the numeric Facebook city ID for a city slug. Useful when `--location <slug>` silently gives wrong results (Facebook redirects unknown slugs to `/category/search/`, dropping the location filter).

```bash
market-scout find-location miskolc --cookies cookies.json
# Found ID: 111617528847006
# Use it like:
#   market-scout search --query "C64" --location 111617528847006 --radius 80

# Headless if cookies are valid; --no-headless to log in first
market-scout find-location gyor --no-headless
```

Numeric IDs can also be passed directly to `--location` — they work as-is:
```bash
market-scout search --query "Amiga" --location 109233199097493 --radius 80
```

---

### `market-scout providers`

List registered providers.

```bash
market-scout providers
# facebook
# hardverapro
```

---

## How location search works

Location handling only applies to the **Facebook** provider. Hardverapró is a nationwide Hungarian site with no location filter.

### Facebook Marketplace's location model

Facebook Marketplace is **city-based**, not country-based. Every search is scoped to a city plus a radius. The URL structure is:

```
https://www.facebook.com/marketplace/{city-slug-or-id}/search/?query=amiga&radiusKm=150
```

Country codes like `DE` are **not** valid Facebook URLs — they are a market-scout abstraction that expands into multiple city searches.

### Slug vs. numeric ID

Facebook only recognises slugs for major cities. For smaller cities, passing a slug is silently redirected to `/category/search/`, dropping the location filter entirely. The scraper detects this and warns:

```
WARNING: location 'gyor' is not a valid Facebook slug.
  FB redirected to: https://www.facebook.com/marketplace/category/search/...
  Fix: market-scout find-location "gyor" --no-headless
```

Cities in `locations.json` that have a known `fb_id` automatically use the numeric ID instead of the slug — both when expanding from a country code (`--location HU`) and when passed as a bare slug (`--location gyor`). To add an ID for a city, run `find-location` and paste the result into `locations.json`.

### Resolution order

When you pass `--location`, each comma-separated token is resolved as follows:

1. **Two-letter uppercase code** (`DE`, `AT`, `HU`, …) → all cities for that country from the built-in database, each with its `fb_id` (if known) or slug, and its tuned radius
2. **City slug** (`berlin`, `gyor`, …) → looked up in the DB; if a matching `fb_id` exists it's used instead. Radius is 0 (Facebook default) unless `--radius` is specified
3. **Numeric ID** → passed directly to Facebook unchanged
4. **Empty** → one search with no location, Facebook auto-detects from your account/cookies

When `--radius N` (N > 0) is specified, it **overrides** all radii — both DB defaults for country expansions and the FB default for bare city slugs.

Duplicates are resolved by URL: if `DE` and `AT` both return a listing near the border, it appears only once.

### Why multiple cities instead of one large radius?

Facebook silently caps or ignores very large `radiusKm` values. Using multiple cities with moderate radii is more reliable than one city with a 500 km radius. The built-in DB radii are tuned to give overlapping coverage without excessive overlap.

### Dry run

Always preview a multi-country search before running it — a 5-country search can easily mean 30+ browser sessions:

```bash
market-scout search --query "anything" --location DE,FR,IT,ES,PL --dry-run
```

Output shows exactly which cities will be searched and at what radius.

---

## Getting Facebook cookies

Without cookies, Facebook Marketplace shows limited results or redirects to login. Cookies let the scraper act as your logged-in account.

**First-time flow (easiest):** run with `--no-headless`, log in manually in the browser window, and the session is saved automatically:

```bash
market-scout search --query "C64" --no-headless
# Log in when the browser opens. Cookies are saved to cookies.json automatically.
# Subsequent runs:
market-scout search --query "C64" --cookies cookies.json
```

**Method 2 — EditThisCookie Chrome extension:**
1. Install [EditThisCookie](https://chrome.google.com/webstore/detail/editthiscookie)
2. Log in to Facebook in Chrome
3. Navigate to `facebook.com/marketplace`
4. Click the EditThisCookie icon → Export (copies JSON to clipboard)
5. Paste into `cookies.json` in the project folder

After each successful run, the scraper **updates `cookies.json`** with refreshed session cookies automatically.

---

## Architecture

```
market-scout/
  market_scout/
    cli.py                          # typer app — search, locations, providers, find-location
    models.py                       # Normalized Listing dataclass (provider-agnostic)
    output.py                       # Rich table (OSC 8 hyperlinks, country flags) + JSON rendering
    providers/
      __init__.py                   # PROVIDERS dict, resolve_providers() — the plugin registry
      base.py                       # SearchRequest dataclass + BaseProvider Protocol
      worldwide/                    # Providers that operate across multiple countries
        __init__.py
        facebook/
          __init__.py
          provider.py               # FacebookProvider — orchestrates per-city scraping
          scraper.py                # Playwright stealth scraper (one-shot, async)
          config.py                 # FbScraperConfig — maps SearchRequest → FB URL params
          models.py                 # FbListing — internal FB data model
          location_db.py            # resolve_locations() + list_countries/cities
          locations.json            # 30 countries, 110 cities, per-city default radii + fb_ids
      hu/                           # Providers specific to Hungary
        __init__.py
        hardverapro/
          __init__.py
          provider.py               # HardveraproProvider — Playwright session + BS4 parsing
        jofogas/
          __init__.py
          provider.py               # JofogasProvider — httpx + embedded JSON extraction
        vatera/
          __init__.py
          provider.py               # VateraProvider — httpx + BS4 data-gtm-* attributes
```

### Data flow

```
CLI (cli.py)
  │  builds SearchRequest (query, locations, price range, debug, …)
  ▼
Provider.search(req)
  │
  ├─ FacebookProvider
  │    calls resolve_locations(tokens, radius_override)
  │      → list of (city_slug_or_id, radius_km) pairs
  │    for each pair:
  │      builds FbScraperConfig → calls asyncio.run(run_scrape(cfg))
  │        → list[FbListing]  (one Playwright session per city)
  │    converts FbListing → Listing, deduplicates by URL
  │
  └─ HardveraproProvider
       launches Playwright, loads hardverapro.hu (networkidle — JS cookie challenge)
       paginates keres.php?stext=QUERY&… via page.goto()
       parses HTML with BeautifulSoup → list[Listing]
  ▼
list[Listing]  →  output.py  →  Rich table (clickable links) or JSON
```

### Core interfaces

**`SearchRequest`** (`providers/base.py`) — what the CLI passes to every provider:

```python
@dataclass
class SearchRequest:
    query: str
    locations: list[str]      # raw tokens: country codes, city slugs, or numeric IDs
    min_price: int | None
    max_price: int | None
    max_results: int          # per city search
    cookies_file: Path | None
    headless: bool
    scrape_details: bool
    radius_km: int            # 0 = use provider defaults
    debug: bool               # print URLs and redirect info to stdout
```

**`BaseProvider`** (`providers/base.py`) — the only interface a new provider must implement:

```python
class BaseProvider(Protocol):
    name: str
    countries: list[str]  # ISO codes e.g. ["HU"], ["DE","AT"], or ["*"] for global
    def search(self, req: SearchRequest) -> list[Listing]: ...
```

**`Listing`** (`models.py`) — the normalized output record:

```python
@dataclass
class Listing:
    provider: str
    provider_country: str  # ISO code of the site's home country, or "*" for global
    title: str
    price: str
    currency: str      # e.g. "€", "£", "HUF", "PLN"
    location: str
    url: str
    image_url: str
    description: str
    seller: str
    condition: str
    posted: str
    scraped_at: str    # ISO timestamp
```

### Facebook scraper internals

The scraper (`providers/worldwide/facebook/scraper.py`) is adapted from [hyuwowo/fb-marketplace-scraper](https://github.com/hyuwowo/fb-marketplace-scraper) (MIT). Key techniques:

- **Playwright + playwright-stealth**: headless Chromium with `navigator.webdriver` spoofed, stealth JS injected
- **browserforge fingerprints**: randomised desktop browser fingerprints (user-agent, screen, viewport, device pixel ratio) per session
- **Bezier mouse movement**: simulated human-like cursor paths to avoid bot detection
- **Human scrolling**: randomised scroll distances and delays to trigger lazy-loaded listings
- **Cookie persistence**: session cookies written back after each run so subsequent runs stay logged in
- **Zero language hardcoding**: price regex covers `$€£¥₩ HUF PLN CZK RON HRK BGN SEK NOK DKK CHF IDR Rp` — works for any country's FB locale
- **Cookie consent handling**: language-agnostic data-attribute selectors + accessible-name fallback for localised button labels
- **Login wall detection**: detects FB login form; in headless mode prints clear instructions; in `--no-headless` mode waits up to 5 minutes for the user to log in interactively
- **Promotional modal dismissal**: handles "Discover more when you shop / Shop partner listings" popup that blocks the results grid
- **Slug redirect detection**: if FB silently redirects an unknown city slug to `/category/search/`, the scraper aborts and prints a `find-location` hint rather than returning unfiltered results
- **Detail pages**: only opened when `--details` is explicitly passed (no silent tab opening)

The scraper runs **one Playwright session per city** and returns a `list[FbListing]`. All sessions are run sequentially to avoid hitting FB rate limits.

### Hardverapró scraper internals

`providers/hardverapro/provider.py` uses Playwright (headless) + BeautifulSoup:

- **JS cookie challenge**: the site sets `sid`/`vid`/`bid` cookies via JavaScript. A plain HTTP client (httpx) never gets them — Playwright with `wait_until="networkidle"` is required to complete the challenge before search requests work
- **Pure HTML parsing**: once the session is established, pages are fetched via `page.goto()` and parsed with BeautifulSoup/lxml — no extra tabs or JS evaluation needed
- **No login required**: only anonymous session cookies, obtained automatically on the first page load
- **Pagination**: increments `offset` by 100 until `max_results` is reached or no more pages exist
- **Price format**: `"14 990 Ft"` → currency `HUF`, amount `"14990"`
- **Location**: ignored — the site is Hungary-only with no location filter in the search API

### Location database

`providers/facebook/locations.json` — a hand-curated JSON file:

```json
{
  "HU": {
    "name": "Hungary",
    "cities": [
      {"slug": "budapest",  "radius_km": 150, "name": "Budapest"},
      {"slug": "gyor",      "fb_id": "109233199097493", "radius_km": 80, "name": "Győr"}
    ]
  }
}
```

`slug` is the FB URL path segment. `radius_km` is the default radius. `fb_id`, when present, is always used instead of the slug — numeric IDs work for any city regardless of whether FB has indexed the slug. Run `find-location <slug>` to discover an ID and paste it in.

---

## Adding a new provider

Providers live under a **country-scoped subfolder**:

| Scope | Folder | When to use |
|-------|--------|-------------|
| Single country | `providers/XX/` (ISO code) | Site serves only that country — e.g. `providers/hu/`, `providers/de/` |
| Multi-country / global | `providers/worldwide/` | Site operates across countries, uses location params |

1. **Create** the provider file in the right subfolder, e.g. `market_scout/providers/de/kleinanzeigen/provider.py`:

```python
from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

class KleinanzeigenProvider:
    name = "kleinanzeigen"
    countries = ["DE"]   # ISO codes this provider covers

    def search(self, req: SearchRequest) -> list[Listing]:
        results = []
        # req.query, req.min_price, req.max_price, req.max_results, req.debug available
        # req.locations is a list of raw tokens — interpret as your site requires
        for raw in fetch_from_site(req.query, ...):
            results.append(Listing(
                provider=self.name,
                provider_country="DE",
                title=raw["title"],
                price=raw["price"],
                currency="€",
                location=raw["city"],
                url=raw["url"],
                image_url=raw.get("image", ""),
                description=raw.get("desc", ""),
                seller="",
                condition="",
                posted="",
            ))
        return results
```

2. **Register** it in `market_scout/providers/__init__.py`:

```python
from market_scout.providers.worldwide.facebook.provider import FacebookProvider
from market_scout.providers.hu.hardverapro.provider import HardveraproProvider
from market_scout.providers.hu.jofogas.provider import JofogasProvider
from market_scout.providers.hu.vatera.provider import VateraProvider
from market_scout.providers.de.kleinanzeigen.provider import KleinanzeigenProvider

PROVIDERS: dict = {
    "facebook":      FacebookProvider(),
    "hardverapro":   HardveraproProvider(),
    "jofogas":       JofogasProvider(),
    "vatera":        VateraProvider(),
    "kleinanzeigen": KleinanzeigenProvider(),
}
```

That's all. The CLI's `--provider kleinanzeigen` flag, `--provider DE` country shorthand, output rendering (including the 🇩🇪 flag), JSON export, and `--debug` all work automatically.

Providers can use any scraping approach: Playwright (for JS-heavy sites), httpx + BeautifulSoup (for plain HTML), an official REST API, or a subprocess calling another language. The `BaseProvider` Protocol is the only contract.

---

## Planned extensions

### LLM query translation and alternative query suggestions

The `--translate-to LANG` flag is already wired in the CLI (`cli.py`) but currently a no-op. Full implementation would add two features:

**Query translation** — before searching a country-specific provider, translate the query into the site's language:
```bash
market-scout search --query "Amiga 500" --location DE,AT,PL --translate-to EN
# Searches FB Germany as "Amiga 500" (same), Poland as "Amiga 500" (same),
# Hungary as "Amiga 500" (same), but e.g. Czech as translated form if needed
```

**Alternative query suggestions** — an LLM call before searching to suggest regional synonyms or common abbreviations that sellers use:
```bash
market-scout search --query "Amiga 500" --suggest-queries
# LLM returns: ["Amiga 500", "A500", "Commodore Amiga", "Amiga számítógép"]
# All variants are searched and merged
```

Implementation: Anthropic API (`claude-haiku-4-5` for cost). Batch all listing titles for translation in a single API call to avoid per-listing overhead. System prompt: `"Translate the following marketplace listing titles from any language to {lang}. Preserve product names, model numbers, and prices exactly."` Hook points already exist in `cli.py`.

---

### LLM result translation

Independent of query translation: translate returned titles and descriptions into the user's language regardless of which provider or country they came from.

```bash
market-scout search --query "Amiga 500" --provider "hardverapro,vatera,jofogas" --results-lang EN
```

Hungarian titles like `"Amiga 500 , The A500 mini a Retro Games Ltd-től"` → `"Amiga 500, The A500 Mini from Retro Games Ltd"`.

Since providers like `jofogas` return the full listing description in the JSON, this would also translate the description field when `--details` is passed.

---

### Output folder, run IDs, and multi-search runs

Currently results only exist for the duration of a single run. A persistent output layer would enable:

**Named output folder:**
```bash
market-scout search --query "Amiga 500" --location DE,HU --out ./searches/amiga
# Writes: ./searches/amiga/<run_id>/results.json
#         ./searches/amiga/<run_id>/results.csv
#         ./searches/amiga/<run_id>/meta.json   (query, providers, date, run_id)
```

**Run ID** — auto-generated timestamp-based ID (`20260711-143022`) or user-supplied (`--run-id amiga-de-sweep`). Allows correlating results across runs.

**Multi-search profile run:**
```bash
market-scout run --profile amiga      # runs all searches defined in market-scout.toml
market-scout run --all                # runs every profile
market-scout run --all --out ./daily  # saves each profile's results in named subfolders
```

**New/flagged filtering:**
```bash
market-scout search --query "Amiga 500" --only-new   # skip URLs seen in any previous run
market-scout flag <url>                               # mark a listing as dismissed/irrelevant
market-scout search --query "Amiga 500" --hide-flagged  # suppress flagged listings
```

Storage backend: SQLite (`~/.market-scout/history.db`) via the `sqlite3` stdlib — one table for seen URLs, one for flagged URLs, one for run metadata.

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

**Watch mode** — run a search on a repeating schedule, notify on new listings:
```bash
market-scout watch --query "Amiga 500" --location DE,HU --interval 30m
market-scout watch --profile amiga --interval 2h --notify email
```

**Cron integration** — the tool already produces clean JSON output; a cron entry like the below is functional today. A dedicated `market-scout cron install` command would write the crontab entry automatically:
```cron
0 */4 * * *  cd ~/market-scout && .venv/bin/market-scout search --query "Amiga 500" --provider hardverapro --only-new --notify pushbullet >> ~/market-scout/logs/amiga.log 2>&1
```

---

### Notifications

When new listings are found (in watch/cron mode or any run with `--notify`):

| Backend | Flag | Notes |
|---------|------|-------|
| Desktop notification | `--notify desktop` | via `plyer`, works on Windows/macOS/Linux |
| Email | `--notify email` | stdlib `smtplib`; configured via `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS` env vars |
| Pushbullet | `--notify pushbullet` | REST API, `PUSHBULLET_API_KEY` env var; delivers to phone and desktop |
| WhatsApp | `--notify whatsapp` | via WhatsApp Business Cloud API or Twilio sandbox; `WHATSAPP_TOKEN` env var |
| Telegram | `--notify telegram` | Bot API, `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`; free, reliable |
| ntfy.sh | `--notify ntfy` | Self-hostable push notifications, no account needed for public topics |
| Log file | `--notify log` | Append-only plaintext file, `--notify-log ./alerts.txt` |

Notification content: listing title, price with currency, location, provider, and the clickable URL.

Multiple backends can be combined: `--notify "pushbullet,email"`.

---

### MCP server

Expose market-scout as an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server so Claude and other AI assistants can call it as a tool:

```bash
market-scout mcp serve --port 8765
```

This would expose one MCP tool per provider (or a combined `search_marketplace` tool), letting an AI assistant say "search for Amiga 500 across European classifieds" and get structured results back. The `kukshaus/magyar-elado-mcp` repo (referenced during development) shows exactly this pattern for the Hungarian providers.

MCP server implementation: `mcp` Python package (`pip install mcp`). Each `@tool` function maps directly to a provider's `search()` method. Output is the normalized `Listing` list serialized as JSON.

---

### More providers and provider implementation guide

**Candidate providers:**

| Provider | Country | Approach | Notes |
|----------|---------|----------|-------|
| **eBay Kleinanzeigen** | Germany | httpx + BS4 or unofficial API | Largest German classifieds |
| **Marktplaats** | Netherlands | Unofficial REST API | eBay subsidiary, dominant in NL |
| **Leboncoin** | France | httpx + session cookies | Largest French classifieds |
| **Wallapop** | Spain | Unofficial JSON API | Well-documented by open-source community |
| **OLX** | PL/RO/BG | REST API, no auth for reads | Same platform across Eastern Europe |
| **Subito.it** | Italy | JSON API from DevTools | Large Italian classifieds |
| **Bazos** | CZ/SK | httpx + BS4 | Simple HTML, easy to scrape |
| **Ricardo.ch** | Switzerland | Official API | Requires API key registration |
| **DBA.dk** | Denmark | JSON API | Dominant Danish classifieds |
| **Finn.no** | Norway | Official API | Well-documented REST API |
| **eBay** | Global | Official API | Requires app key; covers all EU countries |
| **Tradera** | Sweden | Official API | Largest Swedish auction site |

**Provider implementation guide** (to be written as `CONTRIBUTING.md`):

The minimum a provider must implement:
1. A class with `name: str`, `countries: list[str]`, and `search(req: SearchRequest) -> list[Listing]`
2. Placed in `providers/XX/sitename/provider.py` (country code subfolder) or `providers/worldwide/sitename/provider.py`
3. Registered in `market_scout/providers/__init__.py`

Scraping approach by site type:
- **Plain HTML, no JS** → `httpx` + `BeautifulSoup` (see `vatera`, `hardverapro`)
- **JS cookie challenge** → Playwright with `wait_until="networkidle"` (see `hardverapro`)
- **Embedded JSON in HTML** → `httpx` + regex/string-split (see `jofogas`)
- **Official REST API** → `httpx` with API key from env var
- **Heavy JS SPA** → Playwright stealth (see `facebook`)

---

### Price currency normalisation

Listings from different countries come with different currencies (€, £, zł, Ft, etc.). A `--currency EUR` flag would convert all prices using the ECB's free daily XML exchange-rate feed:

```bash
market-scout search --query "Amiga 500" --provider "facebook,hardverapro,vatera" -l DE,HU --currency EUR
```

