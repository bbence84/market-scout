# market-scout

A CLI tool for searching product marketplaces across Europe (and beyond). Built for finding rare items — retro computers, vintage collectibles, obscure parts — across multiple countries at once. The backend is modular: providers are independent plugins, so new marketplaces can be added without touching the core.

**Current providers:** Facebook Marketplace (worldwide · Playwright), Hardverapró · Jófogás · Vatera (Hungary), Bazoš.cz · Bazoš.sk (Czech Republic/Slovakia), Kleinanzeigen (Germany), Allegro.pl/cz/sk (Poland/Czechia/Slovakia · Playwright), OLX.ua/pl/ro/pt/bg (Ukraine/Poland/Romania/Portugal/Bulgaria · curl_cffi JSON API), Wallapop (Spain/Italy/Portugal · httpx REST API), Willhaben · Shpock (Austria · httpx JSON/GraphQL API), Leboncoin (France · httpx mobile API), Subito.it (Italy · curl_cffi __NEXT_DATA__)

---

## Features at a glance

### Multi-marketplace search
- Search **15 European marketplaces** simultaneously with a single command
- Supported countries: Hungary (HU), Germany (DE), Czech Republic (CZ), Slovakia (SK), Poland (PL), Romania (RO), Portugal (PT), Bulgaria (BG), Ukraine (UA), and Facebook Marketplace worldwide
- **Country shorthand**: `--provider HU` automatically selects all providers for that country plus Facebook
- **Provider groups**: mix explicit providers with country codes, e.g. `--provider "HU,bazos_cz,kleinanzeigen"`

### Smart location handling (Facebook)
- Country codes expand to all major cities with tuned search radii
- Numeric city IDs used automatically where slugs are unreliable
- `find-location` command discovers city IDs via browser
- `--dry-run` previews the full city expansion before committing

### LLM-powered search assistance (via OpenRouter)
- **Query translation** (`--translate-to HU`) — translate your query before searching, with interactive approval
- **Alternative suggestions** (`--suggest-queries`) — LLM proposes abbreviations, regional names, synonyms; you pick, add, or fully override the list
- **Auto result translation** — titles and conditions automatically translated to your language (`user_lang` in config) after every search
- `--no-translate` skips translation for a single run

### Output
- **Console table** always shown — numbered rows, sorted by provider, flag emojis, clickable OSC 8 links
- **File output** (`--save json/csv/txt/html`) — timestamped files in `output/YYYY-MM-DD/`, all formats include search metadata and `ai_match` field
- HTML output: light typewriter-font table, ready to share or open in a browser

### Description and AI analysis
- **`--details`** — fetches each listing's detail page to collect the full description. Works for all providers (jofogas extracts it for free from the search-page JSON; Facebook, Hardverapró, and Vatera make an extra HTTP/browser request per listing)
- **`--details-ai "question"`** — after fetching descriptions, the LLM evaluates each listing against your free-text question and assigns `YES` / `MAYBE` / `NO` with a one-sentence reason. Displayed as a coloured column in the table and as numbered reasoning lines below it. Requires OpenRouter key.

### Global configuration (`~/.market-scout/config.toml`)
- Set default providers, location, max results, cookies path, user language
- Store OpenRouter API key for LLM features
- All settings overridable per-run via CLI flags

### Provider initialisation
- `market-scout init facebook` — log in once, cookies saved automatically
- `market-scout init allegro_pl/cz/sk` — solve DataDome CAPTCHA once per domain, session persists

### Timing
- Per-provider and total runtime shown after every search

---

## Contents

- [Quick start](#quick-start)
- [Features at a glance](#features-at-a-glance)
- [Provider initialisation](#provider-initialisation)
- [Global configuration](#global-configuration)
- [LLM query translation and suggestions](#llm-query-translation-and-suggestions)
- [CLI reference](#cli-reference)
- [How location search works](#how-location-search-works)
- [Getting Facebook cookies](#getting-facebook-cookies)
- [Architecture](#architecture)
- [Adding a new provider](#adding-a-new-provider)
- [Planned extensions](#planned-extensions)
  - [Output folder, run IDs, and multi-search runs](#output-folder-run-ids-and-multi-search-runs)
  - [Saved search profiles](#saved-search-profiles-toml-config)
  - [Scheduled runs and cron](#scheduled-runs-cron--watch-mode)
  - [Notifications](#notifications)
  - [MCP server](#mcp-server)
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

# Initialise providers that need a browser session (do once)
.venv\Scripts\market-scout init facebook       # log in to Facebook
.venv\Scripts\market-scout init allegro_pl     # solve Allegro CAPTCHA

# Search all providers (no flags needed once config is set)
.venv\Scripts\market-scout search --query "Amiga 500"

# Search Hungarian providers only
.venv\Scripts\market-scout search --query "Amiga 500" --provider HU

# Search Czech + Slovak Bazoš
.venv\Scripts\market-scout search --query "Amiga 500" --provider "CZ,SK"

# Facebook across Germany + Austria
.venv\Scripts\market-scout search --query "Amiga 500" --location DE,AT --cookies cookies.json

# Suggest alternative search terms (interactive)
.venv\Scripts\market-scout search --query "Amiga 500" --provider HU --suggest-queries

# Translate query to Hungarian before searching
.venv\Scripts\market-scout search --query "Amiga 500" --provider HU --translate-to HU

# Set up config so defaults apply to every run
.venv\Scripts\market-scout config --set providers=hardverapro,jofogas,vatera
.venv\Scripts\market-scout config --set openrouter.api_key=sk-or-v1-your-key
```

On Windows, prefix commands with `PYTHONIOENCODING=utf-8` if you see encoding errors with city names:
```bash
PYTHONIOENCODING=utf-8 .venv\Scripts\market-scout locations
```

---

## Provider initialisation

Some providers need a one-time browser setup before headless scraping works. Run `market-scout init` to see the list, then init each provider you plan to use:

```bash
# See which providers need initialisation
market-scout init

# Facebook — opens browser, log in, cookies.json saved automatically
market-scout init facebook
market-scout init facebook --cookies ~/.market-scout/cookies.json

# Allegro — solve the DataDome CAPTCHA once per domain
market-scout init allegro_pl
market-scout init allegro_cz
market-scout init allegro_sk
```

After init, set the Facebook cookies path in config so you don't need to pass it every time:
```bash
market-scout config --set cookies=~/.market-scout/cookies.json
```

**Providers that work without any init** (no browser, no cookies needed):
`hardverapro`, `jofogas`, `vatera`, `bazos_cz`, `bazos_sk`, `kleinanzeigen`, `olx_ua`, `olx_pl`, `olx_ro`, `olx_pt`, `olx_bg`

**Allegro session persistence:** DataDome sessions are stored in `~/.market-scout/allegro-profile/{pl|cz|sk}/`. If Allegro starts blocking again (sessions expire), re-run `market-scout init allegro_pl` etc.

---

## Global configuration

market-scout stores a global config file at `~/.market-scout/config.toml`. It is created automatically on first run with commented defaults. All values can be overridden by CLI flags on any individual run.

```bash
# Show the config file location and current contents
market-scout config --show

# Set a value
market-scout config --set openrouter.api_key=sk-or-v1-your-key-here
market-scout config --set providers=hardverapro,jofogas,vatera,bazos_cz,bazos_sk
market-scout config --set max_results=50
market-scout config --set cookies=~/.market-scout/cookies.json
market-scout config --set location=HU
```

**Configurable defaults:**

| Key | Default | Description |
|-----|---------|-------------|
| `providers` | `[]` (all) | Default provider list when `--provider` is omitted |
| `location` | `""` | Default FB location when `--location` is omitted |
| `radius` | `0` | Default FB search radius in km |
| `max_results` | `30` | Default max results per provider/city |
| `headless` | `true` | Run FB browser headlessly by default |
| `cookies` | `""` | Path to FB cookies JSON file |
| `user_lang` | `"en"` | Target language for automatic result translation. Titles are translated to this language after every search when an OpenRouter key is configured. Set to `""` to disable. Examples: `"en"`, `"de"`, `"hu"`, `"pl"` |
| `openrouter.api_key` | `""` | OpenRouter API key for LLM features |
| `openrouter.model` | `"anthropic/claude-haiku-4-5"` | LLM model for translation/suggestions |
| `openrouter.base_url` | `"https://openrouter.ai/api/v1"` | OpenRouter endpoint |

The `openrouter.api_key` can also be set via the `OPENROUTER_API_KEY` environment variable (takes precedence over config file).

**Editing the config file manually:**

The config file is plain TOML and can be opened in any text editor:
```bash
# Show the path
market-scout config --show

# Windows — open in Notepad
notepad %USERPROFILE%\.market-scout\config.toml

# Or set individual values from the command line
market-scout config --set openrouter.api_key=sk-or-v1-your-key-here
market-scout config --set providers=hardverapro,jofogas,vatera
```

**Example config for a Hungary-focused setup:**
```toml
providers = ["hardverapro", "jofogas", "vatera"]
max_results = 50
output = "json"
user_lang = "en"   # translate all titles to English automatically

[openrouter]
api_key = "sk-or-v1-your-key-here"
model = "anthropic/claude-haiku-4-5"
```

With this config, running `market-scout search --query "Amiga 500"` will search all three Hungarian providers, return up to 50 results in JSON, and automatically translate all Hungarian titles to English.

---

## LLM query translation and suggestions

market-scout can use an LLM (via [OpenRouter](https://openrouter.ai)) to translate your search query into a local language and/or suggest alternative terms that sellers commonly use.

**Requires:** An OpenRouter API key. Set it once:
```bash
market-scout config --set openrouter.api_key=sk-or-v1-your-key-here
# or: export OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

### Query translation (`--translate-to`)

Before running the search, the LLM translates your query into the specified language. You are shown the translation and can approve, reject, or replace it:

```bash
market-scout search --query "Amiga 500" --provider HU --translate-to HU
```

```
Translating 'Amiga 500' → HU...

Query translation → HU
  Original : Amiga 500
  Suggested: Amiga 500
  Use this translation? [Y]es / [n]o (keep original) / or type your own: y

Searching hardverapro for 'Amiga 500' (HU translation, same as original)...
```

Product names and model numbers are preserved exactly. If the query is already in the target language or is a proper noun, the LLM returns it unchanged.

When running a search across multiple providers, the translated query is shown in brackets next to the original in the status line:

```
Searching hardverapro for 'Amiga 500' ('Amiga 500') | ...
Searching bazos_cz for 'Amiga 500' ('Amiga 500') | ...
```

### Alternative query suggestions (`--suggest-queries`)

The LLM suggests up to 5 alternative terms that sellers commonly use — abbreviations, regional names, related models. You approve, deselect, or add your own:

```bash
market-scout search --query "Amiga 500" --provider "HU,CZ,SK" --suggest-queries
```

```
Asking LLM for alternative search terms...

Alternative search terms for 'Amiga 500':
  1. Amiga 500   (original)
  2. A500
  3. Commodore Amiga
  4. Amiga 500+
  5. A500 mini

  Enter numbers to keep (comma-separated), 'all', 'none',
  or type extra terms separated by commas.
  Selection [all]: 1,2,3,my own term

Using 4 search term(s): 'Amiga 500', 'A500', 'Commodore Amiga', 'my own term'
```

Each approved term is searched separately across all providers. Results are merged and deduplicated by URL — a listing that matches both "Amiga 500" and "A500" appears only once.

### Combining both

```bash
market-scout search --query "Amiga 500" --provider "HU,CZ,SK" \
  --suggest-queries --translate-to HU
```

Suggestions are generated first (from the original query), then each variant is translated independently before searching.

### LLM model selection

The default model is `anthropic/claude-haiku-4-5` — fast and cheap. Change it in config:

```bash
market-scout config --set openrouter.model=openai/gpt-4o-mini
market-scout config --set openrouter.model=google/gemini-flash-1.5
```

Any model available on OpenRouter works.

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
| `--provider` | `-p` | TEXT | all providers | Provider(s) or country code(s), comma-separated. Run `market-scout providers` to list. A country code (e.g. `HU`) selects all providers for that country **plus Facebook**. Defaults to config value or all providers. |
| `--location` | `-l` | TEXT | *(from config)* | [Facebook only] Country codes or city slugs. See [location section](#how-location-search-works). Ignored by all other providers. |
| `--min-price` | | INT | | Minimum price filter (all providers) |
| `--max-price` | | INT | | Maximum price filter (all providers) |
| `--max-results` | `-n` | INT | `30` (config) | Max listings per city search (Facebook) or per page-run (others) |
| `--cookies` | `-c` | PATH | *(from config)* | [Facebook only] Path to cookies JSON |
| `--headless` / `--no-headless` | | flag | headless | [Facebook only] Run Chromium visibly for debugging or first-time login |
| `--details` / `--no-details` | | flag | no-details | Open each listing's detail page to collect the full description. Slower — one extra request per listing. Required for `--details-ai`. |
| `--details-ai` | | TEXT | | After fetching descriptions (implies `--details`), ask the LLM whether each listing matches your free-text question. Adds a `YES` / `MAYBE` / `NO` confidence column to the table, with full reasoning printed below. Requires OpenRouter key. Example: `--details-ai "Is it really an Amiga 500 in good condition?"` |
| `--radius` | | INT | `0` (config) | [Facebook only] Override search radius in km for all cities |
| `--translate-to` | | TEXT | | Translate the query into this language before searching (requires OpenRouter key). Interactive approval. Example: `HU`, `DE`, `PL` |
| `--translate-results` | | TEXT | | Override `user_lang` for this run — translate result titles into the given language. Requires OpenRouter key. Example: `EN` |
| `--no-translate` | | flag | | Skip automatic title translation even if `user_lang` is configured. |
| `--suggest-queries` | | flag | | Ask LLM to suggest alternative search terms — abbreviations, synonyms, regional names. Interactive selection with numbering, extras, and full override. Requires OpenRouter key. |
| `--save` | | TEXT | | Save results to a timestamped file in `output/YYYY-MM-DD/`. Formats: `json`, `csv`, `txt`, `html`. Comma-separated for multiple: `--save csv,html`. Console output is always shown. |
| `--dry-run` | | flag | | [Facebook only] Show resolved city/radius plan without scraping |
| `--debug` | | flag | | Print provider-level debug info: URLs, redirects, response size |

**Examples:**

```bash
# Search all providers (defaults from config)
market-scout search --query "Amiga 500"

# All Hungarian providers via country shorthand
market-scout search --query "Amiga 500" --provider HU

# Czech + Slovak Bazoš
market-scout search --query "Amiga 500" --provider "CZ,SK"

# Mix all Central European providers
market-scout search --query "C64" --provider "HU,CZ,SK" --min-price 5000 --max-price 100000

# Facebook — single country expansion
market-scout search --query "C64" --location DE --cookies cookies.json

# Facebook — multiple countries with price filter
market-scout search --query "Amiga 500" --location DE,AT,HU,PL \
  --min-price 50 --max-price 500 --cookies cookies.json

# Facebook — visible browser for first-time login
market-scout search --query "C64" --location berlin --no-headless

# Facebook — full detail pages + JSON output
market-scout search --query "Amiga 500" --location DE,AT \
  --details --cookies cookies.json

# Suggest alternative search terms (interactive, requires OpenRouter key)
market-scout search --query "Amiga 500" --provider "HU,CZ,SK" --suggest-queries

# Translate query to Hungarian before searching HU providers
market-scout search --query "Amiga 500" --provider HU --translate-to HU

# Translate result titles to English after searching
market-scout search --query "Amiga 500" --provider "HU,CZ,SK" --translate-results EN

# Skip auto-translation for one run
market-scout search --query "Amiga 500" --provider HU --no-translate

# Save results to file (timestamped, in output/YYYY-MM-DD/)
market-scout search --query "Amiga 500" --provider "HU,CZ" --save html
market-scout search --query "C64" --provider "olx_pl,bazos_cz" --save "csv,json,html"

# Fetch full descriptions for each listing
market-scout search --query "Amiga 500" --provider "jofogas,hardverapro" --details

# AI confidence scoring — evaluates each description against your question
market-scout search --query "Amiga 500" --provider "jofogas,hardverapro,olx_pl" \
  --details-ai "Is this really an Amiga 500 home computer in working condition?"

# Combine: details + AI scoring + save to HTML
market-scout search --query "Amiga 500" --provider "HU,CZ,SK" \
  --details-ai "Is it an Amiga 500 in good condition?" --save html

# Dry run: see FB city expansion without scraping
market-scout search --query "Spectrum" --location DE,AT,PL,HU --dry-run

# Debug: see exact URLs fetched
market-scout search --query "Amiga 500" --provider bazos_cz --debug
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

List registered providers with their country coverage.

```bash
market-scout providers
```

```
┌──────────────┬───────────┬─────────────────────────────────┐
│ Provider     │ Countries │ Note                            │
├──────────────┼───────────┼─────────────────────────────────┤
│ facebook     │ *         │ location-aware (use --location) │
│ hardverapro  │ HU        │ nationwide only                 │
│ jofogas      │ HU        │ nationwide only                 │
│ vatera       │ HU        │ nationwide only                 │
│ bazos_cz     │ CZ        │ nationwide only                 │
│ bazos_sk     │ SK        │ nationwide only                 │
│ kleinanzeigen│ DE        │ nationwide only                 │
│ allegro_pl   │ PL        │ nationwide only                 │
│ allegro_cz   │ CZ        │ nationwide only                 │
│ allegro_sk   │ SK        │ nationwide only                 │
│ olx_ua       │ UA        │ nationwide only                 │
│ olx_pl       │ PL        │ nationwide only                 │
│ olx_ro       │ RO        │ nationwide only                 │
│ olx_pt       │ PT        │ nationwide only                 │
│ olx_bg       │ BG        │ nationwide only                 │
│ wallapop     │ ES IT PT GB│ geo-filtered by country        │
│ willhaben    │ AT        │ nationwide only                 │
│ shpock       │ AT        │ nationwide only                 │
│ leboncoin    │ FR        │ nationwide only                 │
│ subito       │ IT        │ nationwide only                 │
└──────────────┴───────────┴─────────────────────────────────┘
```

Pass a two-letter country code to `--provider` to select all providers for that country **plus Facebook Marketplace** (which is worldwide and always included on country expansion):
```bash
market-scout search --query "Amiga 500" --provider HU   # → facebook + hardverapro + jofogas + vatera
market-scout search --query "Amiga 500" --provider CZ   # → facebook + bazos_cz + allegro_cz
market-scout search --query "Amiga 500" --provider SK   # → facebook + bazos_sk + allegro_sk
market-scout search --query "Amiga 500" --provider DE   # → facebook + kleinanzeigen
market-scout search --query "Amiga 500" --provider PL   # → facebook + allegro_pl + olx_pl
market-scout search --query "Amiga 500" --provider RO   # → facebook + olx_ro
market-scout search --query "Amiga 500" --provider PT   # → facebook + olx_pt
market-scout search --query "Amiga 500" --provider BG   # → facebook + olx_bg
market-scout search --query "Amiga 500" --provider UA   # → facebook + olx_ua
market-scout search --query "Amiga 500" --provider ES   # → facebook + wallapop (Spain geo-filter)
market-scout search --query "Amiga 500" --provider IT   # → facebook + wallapop (Italy geo-filter)
market-scout search --query "Amiga 500" --provider AT   # → facebook + willhaben + shpock
market-scout search --query "Amiga 500" --provider FR   # → facebook + leboncoin
market-scout search --query "Amiga 500" --provider IT   # → facebook + wallapop + subito
```

**Note on Wallapop location filtering:** Wallapop operates a single global listing pool across Spain, Italy, and Portugal. Passing a country code (`ES`, `IT`, `PT`) sets a geographic bounding box centred on that country and post-filters results by `country_code`. Without a location token, all countries are searched together. Multiple country codes run as separate geo-filtered API calls:
```bash
# Search Spain + Italy together
market-scout search --query "Amiga" --provider wallapop --location "ES,IT"
```

**Note on Allegro (DataDome anti-bot):** Allegro uses DataDome bot detection, which blocks plain HTTP requests. On first use per domain, run with `--no-headless` to solve the CAPTCHA once in the browser window. The session is saved to `~/.market-scout/allegro-profile/{pl|cz|sk}/` and reused for subsequent runs:

```bash
# First time per domain — solve CAPTCHA in visible browser
market-scout search --query "Amiga 500" --provider allegro_pl --no-headless

# After that — runs headlessly using the saved session
market-scout search --query "Amiga 500" --provider allegro_pl
```

When using a country code, pass `--location` with the same code so Facebook searches that country too — otherwise it auto-detects from your cookies/account location:
```bash
market-scout search --query "Amiga 500" --provider HU --location HU --cookies cookies.json
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
    cli.py                          # typer app — search, locations, providers, find-location, config
    config.py                       # ~/.market-scout/config.toml loader and writer
    llm.py                          # OpenRouter client — translate_query, suggest_queries, translate_listings
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
      de/                           # Providers specific to Germany
        __init__.py
        kleinanzeigen/
          __init__.py
          provider.py               # KleinanzeigenProvider — curl_cffi + mobile JSON API
      multi/                        # Providers covering multiple countries (same platform, different TLDs)
        __init__.py
        bazos/
          __init__.py
          scraper.py                # Shared Bazos scraper (CZ + SK identical platform)
          provider_cz.py            # BazosCzProvider  (bazos.cz, CZK)
          provider_sk.py            # BazosSkProvider  (bazos.sk, EUR)
        allegro/
          __init__.py
          scraper.py                # Shared Allegro scraper — Playwright persistent profile + JSON extraction
          provider_pl.py            # AllegroPlProvider  (allegro.pl, PLN)
          provider_cz.py            # AllegroCzProvider  (allegro.cz, CZK)
          provider_sk.py            # AllegroSkProvider  (allegro.sk, EUR)
        olx/
          __init__.py
          scraper.py                # Shared OLX scraper — curl_cffi + REST API /api/v1/offers/
          provider_ua.py            # OlxUaProvider  (olx.ua, UAH)
          provider_pl.py            # OlxPlProvider  (olx.pl, PLN)
          provider_ro.py            # OlxRoProvider  (olx.ro, RON)
          provider_pt.py            # OlxPtProvider  (olx.pt, EUR)
          provider_bg.py            # OlxBgProvider  (olx.bg, BGN)
        wallapop/
          __init__.py
          provider.py               # WallapopProvider — httpx REST API, geo-filtered by country
      at/                           # Providers specific to Austria
        __init__.py
        willhaben/
          __init__.py
          provider.py               # WillhabenProvider — httpx JSON API (x-wh-client header)
        shpock/
          __init__.py
          provider.py               # ShpockProvider — httpx GraphQL API (Austria-anchored)
      fr/                           # Providers specific to France
        __init__.py
        leboncoin/
          __init__.py
          provider.py               # LeboncoinProvider — httpx mobile JSON API (no auth)
      it/                           # Providers specific to Italy
        __init__.py
        subito/
          __init__.py
          provider.py               # SubitoProvider — curl_cffi + __NEXT_DATA__ HTML parsing
        __init__.py
        bazos/
          __init__.py
          provider.py               # BazosCzProvider — thin wrapper around shared scraper
          scraper.py                # Shared Bazos scraper (used by both CZ and SK)
      sk/                           # Providers specific to Slovakia
        __init__.py
        bazos/
          __init__.py
          provider.py               # BazosSkProvider — calls scraper with tld="sk"
```

### Data flow

```
CLI (cli.py)
  │  loads ~/.market-scout/config.toml (defaults for all flags)
  │  builds effective query list
  │    ├─ (--suggest-queries) → llm.py → OpenRouter → user approves variants
  │    └─ (--translate-to)   → llm.py → OpenRouter → user approves translation
  │  builds SearchRequest per query
  ▼
Provider.search(req)
  │
  ├─ FacebookProvider  (countries=["*"])
  │    resolve_locations(tokens, radius) → [(city_or_id, radius_km), …]
  │    for each city: asyncio.run(run_scrape(cfg))  — one Playwright session
  │    convert FbListing → Listing, deduplicate by URL
  │
  ├─ HardveraproProvider  (countries=["HU"])
  │    Playwright networkidle (JS cookie challenge) → BS4 HTML parsing
  │
  ├─ JofogasProvider  (countries=["HU"])
  │    httpx GET → split on "list_id": → regex extraction
  │
  ├─ VateraProvider  (countries=["HU"])
  │    httpx GET → BS4 data-gtm-* attribute extraction, paginates &p=N
  │
  ├─ BazosCzProvider / BazosSkProvider  (multi/bazos/ — same platform, two TLDs)
  │    httpx GET search.php → BS4 div.inzeraty.inzeratyflex parsing
  │    CZ=CZK, SK=EUR; identical URL patterns and HTML structure
  │
  └─ KleinanzeigenProvider  (countries=["DE"])
       curl_cffi Chrome TLS impersonation → private Android JSON API
       api.kleinanzeigen.de/api/ads.json, page-based, no login required
  │
  ├─ AllegroPlProvider / AllegroCzProvider / AllegroSkProvider
  │    Playwright persistent profile at ~/.market-scout/allegro-profile/{pl|cz|sk}/
  │    DataDome bypass: solve CAPTCHA once with --no-headless, cookie persists
  │    Primary extraction: listing_StoreState JSON blob embedded in HTML
  │    PL=PLN, CZ=CZK, SK=EUR
  │
  ├─ OlxUaProvider / OlxPlProvider / OlxRoProvider / OlxPtProvider / OlxBgProvider
  │    curl_cffi Chrome TLS impersonation → REST API /api/v1/offers/?query=...
  │    No auth, no cookies, no login required
  │    UA=UAH, PL=PLN, RO=RON, PT=EUR, BG=BGN (dual display with EUR)
  ├─ WallapopProvider  (countries=["ES","IT","PT","GB"])
  │    httpx REST API api.wallapop.com/api/v3/search (most_relevance order)
  │    Single global listing pool; country tokens → lat/lng anchor + client-side filter
  │
  ├─ WillhabenProvider  (countries=["AT"])
  │    httpx JSON API willhaben.at/webapi/iad/search — requires x-wh-client header
  │    225+ results for popular queries; pagination via page param; EUR only
  │
  ├─ ShpockProvider  (countries=["AT"])
  │    httpx GraphQL POST shpock.com/graphql — no auth required
  │    Global pool anchored to Vienna coords; client-side AT postcode filter
  │
  ├─ LeboncoinProvider  (countries=["FR"])
  │    httpx POST api.leboncoin.fr/finder/search — mobile User-Agent required
  │    ~210 results for popular queries; full description in search results
  │    Datadome protection: auto-rotates UA on 403
  │
  ├─ SubitoProvider  (countries=["IT"])
  │    curl_cffi Chrome impersonation → HTML page → __NEXT_DATA__ JSON extraction
  │    No public API; Akamai WAF blocks plain httpx (needs TLS fingerprint match)
  │    202 results / 7 pages for popular queries; client-side price filter
  │
  │  (--translate-results) → llm.py → OpenRouter → titles translated in batch
  ▼
output.py → Rich table (clickable OSC 8 links, country flag emoji) or JSON
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

`providers/hu/hardverapro/provider.py` uses Playwright (headless) + BeautifulSoup:

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
| Multi-country, same platform | `providers/multi/sitename/` | Same codebase, multiple TLDs — e.g. Allegro (PL/CZ/SK). One shared `scraper.py`, thin per-country `provider_XX.py` wrappers |
| Multi-country / global | `providers/worldwide/` | Site operates across countries via a location parameter |

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
# new provider:
from market_scout.providers.nl.marktplaats.provider import MarktplaatsProvider  # hypothetical

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
    "marktplaats":   MarktplaatsProvider(),
}
```

That's all. The CLI's `--provider kleinanzeigen` flag, `--provider DE` country shorthand, output rendering (including the 🇩🇪 flag), JSON export, and `--debug` all work automatically.

Providers can use any scraping approach: Playwright (for JS-heavy sites), httpx + BeautifulSoup (for plain HTML), an official REST API, or a subprocess calling another language. The `BaseProvider` Protocol is the only contract.

---

## Planned extensions



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
| **Marktplaats** | Netherlands | Unofficial REST API | eBay subsidiary, dominant in NL |
| **Leboncoin** | France | httpx + session cookies | Largest French classifieds |
| **Subito.it** | Italy | JSON API from DevTools | Large Italian classifieds |
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

