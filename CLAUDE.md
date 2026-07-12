# market-scout — project notes for Claude

## Provider initialization requirements

Some providers require a one-time human action before headless scraping works.
The `market-scout init <provider>` command handles all of them.

### Providers needing init

| Provider | Reason | Session stored at |
|---|---|---|
| `facebook` | Requires a logged-in Facebook account | `cookies.json` (user-configurable via `--cookies` or config `cookies=`) |
| `allegro_pl` | DataDome bot detection — CAPTCHA must be solved once | `~/.market-scout/allegro-profile/pl/` (Playwright persistent profile) |
| `allegro_cz` | DataDome bot detection — CAPTCHA must be solved once | `~/.market-scout/allegro-profile/cz/` |
| `allegro_sk` | DataDome bot detection — CAPTCHA must be solved once | `~/.market-scout/allegro-profile/sk/` |

### Providers that work headlessly without init

| Provider | Reason |
|---|---|
| `hardverapro` | Playwright solves the JS cookie challenge automatically via `networkidle` |
| `jofogas`, `vatera` | Plain httpx — no cookies needed |
| `bazos_cz`, `bazos_sk` | Plain httpx — no cookies needed |
| `kleinanzeigen` | curl_cffi Chrome TLS impersonation — no cookies needed |
| `olx_ua/pl/ro/pt/bg` | curl_cffi + public REST API — no cookies needed |

### Init command

```bash
market-scout init                  # list all providers that need init
market-scout init facebook         # open FB marketplace in browser, log in, cookies saved
market-scout init facebook --cookies ~/.market-scout/cookies.json
market-scout init allegro_pl       # solve DataDome CAPTCHA, session saved
market-scout init allegro_cz
market-scout init allegro_sk
```

After running `init facebook`, set the cookies path in config so all future runs use it:
```bash
market-scout config --set cookies=~/.market-scout/cookies.json
```

When adding a new provider that requires init (browser session, CAPTCHA, OAuth), add it to
`_INIT_PROVIDERS` in `cli.py` and implement its branch in the `init` command function there.

### DataDome session persistence (Allegro)

Allegro's DataDome checks TLS fingerprint + browser profile cookies. The Playwright persistent
context stores the full browser profile (cookies, localStorage, etc.) in
`~/.market-scout/allegro-profile/{domain}/`. If DataDome blocks again (sessions expire or
fingerprint rotates), re-run `market-scout init allegro_pl` (or _cz / _sk).

---

## Adding a new provider — checklist

Follow this checklist every time a new scraper is added:

### 1. Choose the right folder

```
providers/
  worldwide/           ← single site that covers all countries via a location param (e.g. Facebook)
  {ISO2}/              ← site serves ONLY one country (e.g. hu/, de/, pl/)
  multi/{sitename}/    ← same platform, multiple country TLDs (e.g. bazos, allegro, olx)
```

Decision rule:
- One country only → `providers/{iso2}/{sitename}/provider.py`
- Multiple TLDs, identical platform → `providers/multi/{sitename}/scraper.py` (shared) +
  `provider_{cc}.py` per country (thin wrappers that call `scrape("{cc}", req)`)
- Location-parameterized global site → `providers/worldwide/{sitename}/`

### 2. Implement the provider class

Minimum required:
```python
class MySiteProvider:
    name = "mysite"                 # must be unique in PROVIDERS
    countries = ["DE"]              # ISO codes, or ["*"] for global/worldwide

    def search(self, req: SearchRequest) -> list[Listing]:
        ...
        return [Listing(
            provider=self.name,
            provider_country="DE",  # ISO code of the site, or "*"
            title=..., price=..., currency=..., location=...,
            url=..., image_url=..., description=...,
            seller=..., condition=..., posted=...,
        )]
```

### 3. Register in `providers/__init__.py`

Add the import and a line in PROVIDERS dict. The `resolve_providers()` function automatically
handles `--provider DE` country shorthand — no extra code needed.

### 4. Check TLS fingerprinting

Several sites block Python's default TLS fingerprint (CloudFront-backed sites, Kleinanzeigen,
OLX). Test with a plain `httpx.get()` first. If you get 403, switch to `curl_cffi` with
`impersonate="chrome120"`.

### 5. If the provider needs init (browser session, cookies, CAPTCHA)

Add it to `_INIT_PROVIDERS` dict in `cli.py` and implement the init branch. See the existing
Facebook and Allegro branches as templates.

### 6. Update the README — ALWAYS

After adding any provider, update **all** of these sections in `README.md`:

- **Line 5 header** — add the new site to the "Current providers" summary line
- **`market-scout providers` sample output table** — add the new row
- **Country shorthand examples** — add `--provider XX` if it's a new country
- **Architecture tree** — add the new directory
- **Data flow diagram** — add the new provider's scraping approach
- **`providers/__init__.py` registration example** in "Adding a new provider"
- **Candidate providers table** — remove the site if it was listed as a future candidate

The README is the public-facing spec. Stale docs cause confusion. Update it in the same
commit/session as the provider implementation.

---

## Architecture overview

```
providers/
  worldwide/facebook/   — Playwright stealth, location-parameterized
  hu/hardverapro/       — Playwright + BS4 (JS cookie challenge, auto-solved)
  hu/jofogas/           — httpx + embedded JSON regex
  hu/vatera/            — httpx + BS4 data-gtm-* attrs
  de/kleinanzeigen/     — curl_cffi + private Android JSON API
  multi/bazos/          — httpx + BS4 (CZ + SK, same platform)
  multi/allegro/        — Playwright persistent profile + JSON extraction (PL/CZ/SK, DataDome)
  multi/olx/            — curl_cffi + public REST API (UA/PL/RO/PT/BG)
```

### Scraping approach decision tree

| Site type | Library | Example |
|---|---|---|
| Plain HTML, no JS | `httpx` + `BeautifulSoup` | vatera, bazos |
| JS cookie challenge (no human needed) | Playwright `networkidle` | hardverapro |
| SPA / stealth (no login) | Playwright + stealth + browserforge | facebook |
| DataDome / Cloudflare (CAPTCHA once) | Playwright persistent profile | allegro |
| TLS fingerprint block (CloudFront) | `curl_cffi` `impersonate="chrome120"` | kleinanzeigen, olx |
| Embedded JSON in HTML | `httpx` + regex split on JSON key | jofogas |
| Private mobile API | `curl_cffi` + API key from APK | kleinanzeigen |
| Public REST API | `curl_cffi` or `httpx` | olx |

### Anti-bot patterns encountered

- **Facebook**: Login wall + cookie consent + "Discover more" promo modal + slug redirect detection
- **Hardverapro**: JS sets `sid`/`vid`/`bid` cookies — plain httpx never gets them; Playwright `networkidle` required
- **Kleinanzeigen**: CloudFront blocks Python TLS; `curl_cffi` Chrome impersonation bypasses it
- **OLX**: Same CloudFront TLS block as Kleinanzeigen; same fix
- **Allegro**: DataDome — blocks all automated clients; persistent Playwright profile + human CAPTCHA once
- **Bazos**: Minimal protection; plain httpx + correct search endpoint (`search.php`, not homepage)
- **Facebook city slugs**: FB silently redirects unknown slugs to `/category/search/` dropping location filter;
  use numeric city IDs from `locations.json` or `find-location` command

---

## Key files

- `market_scout/config.py` — global config loader (`~/.market-scout/config.toml`)
- `market_scout/llm.py` — OpenRouter client (translate, suggest, batch translation)
- `market_scout/cli.py` — typer app (search, init, providers, locations, find-location, config)
- `market_scout/output.py` — Rich table renderer (sorted by provider, numbered rows, OSC 8 links)
- `market_scout/providers/__init__.py` — PROVIDERS dict + `resolve_providers()` (country code expansion)
- `market_scout/providers/worldwide/facebook/locations.json` — 30 EU countries, 110 cities, per-city FB radii + numeric IDs
- `~/.market-scout/config.toml` — user's global config (created on first run)
- `~/.market-scout/allegro-profile/{pl,cz,sk}/` — Playwright persistent profiles for Allegro

---

## LLM / translation

- Auto-translation of titles and conditions driven by `user_lang` in config (default `"en"`)
- Translation fires automatically when an OpenRouter key is set and `user_lang` is non-empty
- `--no-translate` suppresses it for a single run
- `--translate-results LANG` overrides `user_lang` for a single run
- `--translate-to LANG` translates the query before searching (interactive approval)
- `--suggest-queries` asks LLM for alternative search terms (interactive approval)
- Batched in chunks of 30 to avoid LLM token limit truncation (88 items = 3 API calls)
- Conditions are deduped before translation (e.g. 20 listings sharing "Używane" → 1 API call)
- Uses OpenRouter (not Anthropic API directly) — any model available on openrouter.ai works
- Default model: `anthropic/claude-haiku-4-5` (fast, cheap); change with `config --set openrouter.model=`

---

## Country code → provider expansion

`resolve_providers()` in `providers/__init__.py` maps two-letter ISO codes to providers:
- `--provider HU` → facebook + hardverapro + jofogas + vatera
- `--provider CZ` → facebook + bazos_cz + allegro_cz
- `--provider SK` → facebook + bazos_sk + allegro_sk
- `--provider DE` → facebook + kleinanzeigen
- `--provider PL` → facebook + allegro_pl + olx_pl
- `--provider RO` → facebook + olx_ro
- `--provider PT` → facebook + olx_pt
- `--provider BG` → facebook + olx_bg
- `--provider UA` → facebook + olx_ua

Facebook (countries=["*"]) is always included when a country code is given. This is intentional —
the user should also use `--location {CC}` alongside `--provider {CC}` so Facebook searches that
country too.

---

## Facebook location system

Facebook is city-based, not country-based. The location DB is in
`providers/worldwide/facebook/locations.json` — 30 countries, 110 cities, per-city default radii.

- Many smaller cities don't have a recognised slug on FB (e.g. `gyor` → redirected to `/category/search/`)
- Use the `fb_id` numeric ID instead (stored in locations.json where known)
- `resolve_locations()` prefers `fb_id` over slug automatically
- Add new IDs: `market-scout find-location <slug>` — opens browser, extracts ID from page source
- Slug redirect detection: scraper checks `page.url` after navigation; if it contains `/category/search/`
  the location was dropped, warns user with the `find-location` fix command

---

## CLI commands summary

| Command | Purpose |
|---|---|
| `search` | Main search — multi-provider, location expansion, LLM translation |
| `init` | One-time browser setup for Facebook and Allegro |
| `providers` | List all registered providers with countries |
| `locations` | Browse FB location DB (countries, city slugs, FB IDs) |
| `find-location` | Discover numeric FB city ID for a slug via browser |
| `config` | Show/set global config (`~/.market-scout/config.toml`) |

When adding a new CLI command, add it to:
1. `cli.py` as a `@app.command()` function
2. The README CLI reference section
3. The command table in this CLAUDE.md

---

## README maintenance rules

The README is the authoritative public spec. Keep it in sync with the code:

1. **New provider added** → update: header line, providers table, country shorthands, architecture tree, data flow diagram, `__init__.py` registration example, candidate providers table (remove if was listed there)
2. **New CLI command added** → update: CLI reference options table, examples section, command summary in README
3. **Config key added** → update: Configurable defaults table in README and the TOML template in `config.py`
4. **Provider init requirements changed** → update: "Provider initialisation" section in README and init command in `cli.py`
5. **Breaking change to any interface** → update: Architecture section, data flow diagram, Adding a new provider guide
