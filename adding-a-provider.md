# Adding a new provider to market-scout

market-scout is designed to be extended. Adding a new classifieds site takes about 50–200 lines of Python — mostly just mapping the site's data fields to the `Listing` dataclass.

> **AI-assisted development:** Tools like [Claude Code](https://claude.ai/code) work very well for this. See the "Asking an AI assistant to add a provider" section for an example prompt.
The agent will read the existing code, research the site's API, write the provider, register it, and test it — often in a single session.

---

## Step 1 — Choose the right folder

All providers live under `market_scout/providers/`:

```
market_scout/providers/
  worldwide/      ← site operates across many countries via a location param (e.g. Facebook)
  {ISO2}/         ← site serves ONE country only (e.g. fr/leboncoin/, de/kleinanzeigen/)
  multi/{name}/   ← same platform, multiple TLDs or geo-filtered (e.g. multi/olx/, multi/allegro/)
```

**Decision:**
- One country → `market_scout/providers/{iso2}/{sitename}/provider.py`
- Multiple identical TLDs → `market_scout/providers/multi/{sitename}/scraper.py` + thin `provider_{cc}.py` per country (see `multi/olx/`, `multi/allegro/`, `multi/bazos/`)
- Single provider covering multiple countries via geo-parameters → `market_scout/providers/multi/{sitename}/provider.py` (see `multi/wallapop/` — one provider, countries filtered by lat/lng)
- Location-parameterized global site → `market_scout/providers/worldwide/{sitename}/`

Create `__init__.py` files for any new directories.

---

## Step 2 — Pick a scraping approach

| Site type | Library to use |
|-----------|---------------|
| Plain HTML, no JS | `httpx` + `BeautifulSoup` |
| JS cookie challenge (auto-solved) | Playwright with `wait_until="networkidle"` |
| Embedded JSON in HTML (`__NEXT_DATA__`, etc.) | `curl_cffi` (Akamai/Cloudflare) or `httpx` + regex |
| Public REST/JSON API | `httpx` or `curl_cffi` |
| TLS fingerprint blocking (CloudFront, Akamai) | `curl_cffi` `impersonate="chrome120"` |
| Mobile app API | `httpx` with spoofed mobile User-Agent |
| GraphQL | `httpx` POST |
| DataDome CAPTCHA (once) | Playwright persistent profile + `market-scout init` |
| Full stealth (login wall, bot detection) | Playwright + `playwright-stealth` + `browserforge` fingerprints (see Facebook provider) |

`curl_cffi`, Playwright, `httpx`, `beautifulsoup4`, `playwright-stealth`, and `browserforge` are already installed.

---

## Step 3 — Implement the provider class

Minimum required:

```python
# market_scout/providers/xx/mysite/provider.py
import httpx
from market_scout.models import Listing
from market_scout.providers.base import SearchRequest

class MySiteProvider:
    name = "mysite"
    countries = ["XX"]   # ISO-3166-1 alpha-2 codes, or ["*"] for global

    def search(self, req: SearchRequest) -> list[Listing]:
        results = []
        seen_urls: set[str] = set()

        # ... fetch and parse ...

        for raw in fetch_items(req.query, req.max_results):
            lst = Listing(
                provider=self.name,
                provider_country="XX",
                title=raw["title"],
                price=str(raw["price"]),
                currency="EUR",
                location=raw["city"],
                url=raw["url"],
                image_url=raw.get("image", ""),
                description=raw.get("description", ""),
                seller=raw.get("seller", ""),
                condition=raw.get("condition", ""),
                posted=raw.get("posted", ""),   # normalise with dates.normalise() if raw
            )
            if lst.url not in seen_urls:
                seen_urls.add(lst.url)
                results.append(lst)

        return results[:req.max_results]
```

**Tips:**
- Use `from market_scout.dates import normalise as normalise_date` to normalise raw date strings to `YYYY-MM-DD`
- Respect `req.min_price` / `req.max_price` — either pass to the API or filter client-side
- Respect `req.max_results` — stop paginating once reached
- Respect `req.debug` — print progress with `print(f"[mysite] ...", flush=True)`
- Respect `req.scrape_details` — if True, fetch each listing's detail page for `description`
- Add a 0.5–2 second delay between pages to avoid rate-limiting

---

## Step 4 — Register the provider

Edit `market_scout/providers/__init__.py`:

```python
# Add import
from market_scout.providers.xx.mysite.provider import MySiteProvider

# Add to PROVIDERS dict
PROVIDERS: dict = {
    ...existing...,
    "mysite": MySiteProvider(),
}
```

That's all. `--provider mysite`, `--provider XX` (country shorthand), output rendering, JSON export, translation, and AI analysis all work automatically.

---

## Step 5 — If the provider needs init (CAPTCHA, browser login)

Add it to `_INIT_PROVIDERS` in `cli.py` and implement its branch in the `init` command. See the Facebook and Allegro branches as templates.

---

## Step 6 — Update the README

After adding any provider, update `README.md`:
1. **Providers table** — add the new row (country code, country name, site link)
2. **Country shorthand examples** — add `market-scout search ... --provider XX` if it's a new country
3. **Architecture tree in `design.md`** — add the new directory entry

Also update `design.md` if the scraping approach is new (add a row to the data flow diagram).

---

## Asking an AI assistant to add a provider

Tools like [Claude Code](https://claude.ai/code) work very well for this. Here is a template prompt that mirrors exactly how all the current providers in this project were added:

```
Implement the provider:
- <site name> (<country> only) — <URL>

Analyze the following GitHub repos as reference and create the provider following
the existing patterns in this codebase:
- <repo 1 URL>
- <repo 2 URL>

If the repos don't have sufficient info, inspect the site directly:
check for an embedded JSON API (browser DevTools → Network tab), look for
__NEXT_DATA__ or similar JSON blobs in the HTML, and identify the exact
selectors or API endpoint.

Consult me if it's not straightforward (requires login, CAPTCHA bypass, etc.).

Update README.md and adding-a-provider.md once done.
```

**Finding reference repos on GitHub:**

Before writing any code or asking the AI agent to do the implementation, manually search GitHub for existing scrapers. Use queries like:
- `<site name> scraper`
- `<site name> api`

Filter by **"Updated in the last 6 months"** (GitHub's sort/filter options). Older repos are usually broken — classifieds sites frequently redesign their HTML, rename CSS classes, change API endpoints, or add bot detection. A scraper from 2021 is almost certainly wrong for 2026.

Look for:
- Repos that use the actual site URL (not a cached/test version)
- Working code with recent commits fixing issues (a sign the author is maintaining it)
- Clear field mapping showing how title/price/location/URL are extracted

Even if a repo is slightly outdated, it's still valuable for understanding the site's structure — you can use it as a starting point and fix the selectors by inspecting the current live site.

**What the AI agent will do:**

1. Check GitHub for the existing scrapers
2. Probe the target site's API or page structure directly
3. Read existing similar providers in this codebase to follow the same pattern
4. Implement, register, and live-test the provider
5. Update docs

**Useful context to include in your prompt:**
- Which existing provider is most similar (the agent will use it as a structural template)
- Whether login is a must (the agent will add an `init` command if so, but you should let the AI agent figure this out)