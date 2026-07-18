# market-scout

Ever wanted to get your hands on something rare — a piece of retro computing history, a vintage collectible, an obscure spare part? Are you manually searching dozens of European sites, translating queries yourself, hoping to find what you're after? **market-scout** makes that effortless.

It's a command-line tool that searches the most popular classifieds sites across Europe simultaneously — translating queries, fetching descriptions, and using an LLM to tell you which listings are actually worth looking at.

---

## What it does

**Multi-country search across 20 providers** — one command searches Hungary, Germany, Austria, France, Italy, Poland, Czechia, Slovakia, Romania, Bulgaria, Ukraine, Portugal, Spain, and more.

**Smart query handling** — suggest alternative search terms (sellers use different names in different languages), translate your query into the local language before searching.

**Description and AI analysis** — fetch each listing's full description, then ask the LLM a question like *"Is this actually a working Commodore 64 or just accessories?"* and get a YES / MAYBE / NO confidence score with reasoning.

**Automatic result translation** — all titles and conditions are translated back to your language (configurable, default English) so you can read results from any country.

**Rich output** — colour-coded console table with clickable links, or save to HTML / JSON / CSV / TXT.

---

## Providers

| Country | Flag | Sites |
|---------|------|-------|
| 🌍 Worldwide | | [Facebook Marketplace](https://www.facebook.com/marketplace) |
| 🇭🇺 Hungary | | [Hardverapró](https://hardverapro.hu) · [Jófogás](https://www.jofogas.hu) · [Vatera](https://www.vatera.hu) |
| 🇩🇪 Germany | | [Kleinanzeigen](https://www.kleinanzeigen.de) |
| 🇦🇹 Austria | | [Willhaben](https://www.willhaben.at) · [Shpock](https://www.shpock.com) |
| 🇫🇷 France | | [Leboncoin](https://www.leboncoin.fr) |
| 🇮🇹 Italy | | [Subito.it](https://www.subito.it) · [Wallapop](https://it.wallapop.com) |
| 🇪🇸 Spain | | [Wallapop](https://es.wallapop.com) |
| 🇵🇱 Poland | | [Allegro](https://allegro.pl) · [OLX](https://www.olx.pl) |
| 🇨🇿 Czech Republic | | [Bazoš.cz](https://www.bazos.cz) · [Allegro](https://allegro.cz) |
| 🇸🇰 Slovakia | | [Bazoš.sk](https://www.bazos.sk) · [Allegro](https://allegro.sk) |
| 🇷🇴 Romania | | [OLX](https://www.olx.ro) |
| 🇧🇬 Bulgaria | | [OLX](https://www.olx.bg) |
| 🇵🇹 Portugal | | [OLX](https://www.olx.pt) · [Wallapop](https://pt.wallapop.com) |
| 🇺🇦 Ukraine | | [OLX](https://www.olx.ua) |

---

## Quick start

### Install (recommended)

[pipx](https://pipx.pypa.io) installs market-scout into an isolated environment and puts it on PATH — works on Windows, macOS, and Linux with no venv management.

**1. Install pipx** (once per machine):

```bash
# macOS
brew install pipx && pipx ensurepath

# Windows (PowerShell)
python -m pip install --user pipx
python -m pipx ensurepath
# Restart your terminal after this
```

**2. Install market-scout:**

```bash
# From a local clone
pipx install /path/to/market-scout

# Or directly from GitHub
pipx install git+https://github.com/yourname/market-scout
```

**3. Install browser binaries** (one-time):

```bash
playwright install chromium
```

`market-scout` is now available in any terminal window, in any directory.

```bash
# Optional: set up AI features
market-scout config --set openrouter.api_key=sk-or-v1-XXXXXXXX
market-scout config --set user_lang=en

# One-time browser login for providers that need it
market-scout init facebook      # log in to Facebook in the browser
market-scout init allegro_pl    # solve CAPTCHA once for Allegro Poland

# Search
market-scout search --query "Commodore 64" --provider HU
market-scout search --query "Commodore 64" --provider "HU,CZ,SK,AT,DE"
```

**Upgrading:** `pipx upgrade market-scout`

**Config file location:** Run `market-scout config --show` to find the exact path after installing.

### Developer install (to modify code or add a provider)

If you want to hack on the code, add a provider, or run from source:

```bash
git clone https://github.com/yourname/market-scout
cd market-scout
python -m venv .venv

# Windows
.venv\Scripts\pip install -e .
.venv\Scripts\playwright install chromium

# macOS / Linux
.venv/bin/pip install -e .
.venv/bin/playwright install chromium
```

Changes to the source take effect immediately without reinstalling. See [adding-a-provider.md](adding-a-provider.md) for a guide to adding new scrapers.

On Windows, prefix commands with `PYTHONIOENCODING=utf-8` if you see encoding errors.

---

## Examples

### Basic: search Hungary + Central Europe

```bash
market-scout search --query "Commodore 64" --provider "HU,CZ,SK,AT" --max-results 20
```

Searches Facebook Marketplace, Hardverapró, Jófogás, Vatera, Bazoš.cz, Bazoš.sk, Allegro.cz, Allegro.sk, Willhaben, and Shpock simultaneously. Results are sorted by provider with country flag emojis and clickable links.

→ **[See example output — 160 results across 10 providers, with AI assisted analysis](https://htmlpreview.github.io/?https://github.com/bbence84/market-scout/blob/main/examples/commodore64-ai-analysis.html)**

---

### With price filter and file output

```bash
market-scout search --query "Commodore 64" \
  --provider "HU,CZ,SK,AT,DE,FR,IT" \
  --min-price 50 --max-price 500 \
  --save "html,csv"
```

Saves a timestamped HTML file (light typewriter-font table, hover tooltips) and CSV to `output/YYYY-MM-DD/`.

---

### Translate results to English

Set `user_lang = "en"` in your config once and all results are automatically translated:

```bash
market-scout config --set user_lang=en
market-scout config --set openrouter.api_key=sk-or-v1-your-key

market-scout search --query "Commodore 64" --provider HU
# Hungarian titles like "Commodore 64 gép szép állapotban"
# become: "Commodore 64 machine in nice condition [Commodore 64 gép szép állapotban]"
```

Skip translation for one run: `--no-translate`

---

### Suggest alternative search terms

```bash
market-scout search --query "Commodore 64" --provider "HU,CZ,SK" --suggest-queries
```

```
Alternative search terms for 'Commodore 64':
  1. Commodore 64   (original)
  2. C64
  3. CBM 64
  4. Commodore64
  5. C-64

  Selection [all]: 1,2,3
Using 3 search term(s): 'Commodore 64', 'C64', 'CBM 64'
```

Each approved variant is searched separately; results are merged and deduplicated.

---

### Translate query before searching

```bash
market-scout search --query "Commodore 64" --provider HU --translate-to HU
```

```
Query translation → HU
  Original : Commodore 64
  Suggested: Commodore 64
  Use this translation? [Y]es / [n]o / or type your own: y
```

For rare items with local names, this ensures sellers find the listing even when they use regional terminology.

---

### AI description analysis

Fetch full listing descriptions and ask the LLM a specific question:

```bash
market-scout search --query "Commodore 64" \
  --provider "HU,CZ,SK,AT,DE,FR,IT" \
  --details \
  --details-ai "I am looking for the actual Commodore 64 machine, not accessories, disks, or games" \
  --save html
```

The AI column shows `YES`, `MAYBE`, or `NO` with reasoning for each listing. In the HTML output, hover over the verdict to see the full explanation.

Example output:
```
  5.  YES  — title and description both confirm it is a complete C64 set with computer, power supply, and cables
  6.  NO   — this is a cleaning floppy disk for the C64, not the machine itself
  62. YES  — listing describes a complete, working C64C with power supply
  98. NO   — this is a Commodore 64-related magazine, not the machine
 107. NO   — bundle is primarily marketed with Datassette and game cassettes, which the buyer wants to avoid
```

→ **[See full example output with AI analysis (160 results, 10 providers)](examples/commodore64-ai-analysis.html)**

---

## Configuration

Set defaults so you don't repeat flags every run:

```bash
market-scout config --show              # view current config
market-scout config --set openrouter.api_key=sk-or-v1-your-key
market-scout config --set user_lang=en
market-scout config --set max_results=30
market-scout config --set cookies=~/.market-scout/cookies.json
market-scout config --set disable_facebook=true   # exclude FB from all searches
```

Config file: `user_config/config.toml` inside the repo directory (git-ignored) — plain TOML, edit in any text editor.

**LLM features** (translation, suggestions, AI analysis) all use [OpenRouter](https://openrouter.ai). Register for free, top up to use paid models, or use free-tier models. Default model: `anthropic/claude-haiku-4-5` (fast, cheap).

```bash
market-scout config --set openrouter.model=openai/gpt-4o-mini
```

---

## Provider initialisation

Some providers use bot-detection that requires a **one-time human action** before headless searches work. After that, the session is saved and all future runs are fully automatic.

### Facebook Marketplace

Facebook requires you to be logged in. Run init once to save your session cookies:

```bash
market-scout init facebook
```

A browser window opens at `facebook.com/marketplace`. Log in normally (or dismiss any prompts if already logged in) — cookies are saved automatically to `cookies.json` in the current directory.

Then tell market-scout where the file lives so every future run picks it up:

```bash
market-scout config --set cookies=./cookies.json
```

> **If Facebook blocks searches later**: cookies expire every few weeks. Re-run `market-scout init facebook` to refresh them.

---

### Allegro (Poland · Czech Republic · Slovakia)

Allegro uses [DataDome](https://datadome.co) bot protection. You need to solve a CAPTCHA once per country domain — after that the browser profile is saved and headless searches work indefinitely.

```bash
market-scout init allegro_pl   # allegro.pl  → saved to ~/.market-scout/allegro-profile/pl/
market-scout init allegro_cz   # allegro.cz  → saved to ~/.market-scout/allegro-profile/cz/
market-scout init allegro_sk   # allegro.sk  → saved to ~/.market-scout/allegro-profile/sk/
```

A browser window opens — simply solve the CAPTCHA (slide puzzle or click challenge) and the session is saved. You don't need to log in to Allegro.

> **If Allegro blocks headless searches again**: DataDome sessions eventually expire or rotate fingerprints. Re-run the relevant `market-scout init allegro_*` command to refresh the session.

---

### Providers that work without any init

The following providers work out of the box — no setup needed:

| Provider | Method |
|----------|--------|
| Hardverapró, Jófogás, Vatera | Plain HTTP |
| Bazoš.cz, Bazoš.sk | Plain HTTP |
| Kleinanzeigen | Chrome TLS impersonation (curl_cffi) |
| OLX (UA/PL/RO/PT/BG) | Public REST API |
| Wallapop | Public REST API |
| Willhaben, Shpock | Plain HTTP |
| Leboncoin, Subito | Plain HTTP |

---

### Quick reference

```bash
market-scout init                  # list all providers that need init
market-scout init facebook         # FB: log in once, cookies saved
market-scout init allegro_pl       # Allegro PL: solve CAPTCHA once
market-scout init allegro_cz       # Allegro CZ: solve CAPTCHA once
market-scout init allegro_sk       # Allegro SK: solve CAPTCHA once
```

The `market-scout providers` command shows which providers are flagged as requiring init and the exact command to run.

---

## All CLI options

| Option | Description |
|--------|-------------|
| `--query`, `-q` | Search term (required) |
| `--provider`, `-p` | Provider(s) or country code(s), comma-separated. Omit for all. |
| `--location`, `-l` | [Facebook only] Country codes or city slugs |
| `--min-price` / `--max-price` | Price filter (all providers) |
| `--max-results`, `-n` | Max listings per provider (default: 30) |
| `--details` | Fetch full description for each listing |
| `--details-ai "question"` | AI confidence scoring (implies `--details`) |
| `--translate-to LANG` | Translate query before searching (interactive) |
| `--translate-results LANG` | Override auto-translation language for this run |
| `--no-translate` | Skip auto-translation for this run |
| `--suggest-queries` | LLM suggests alternative search terms (interactive) |
| `--save FORMAT` | Save to file: `json`, `csv`, `txt`, `html` (or `csv,html`) |
| `--no-facebook` | Exclude Facebook Marketplace from this run |
| `--cookies PATH` | [Facebook] Path to cookies JSON |
| `--no-headless` | [Facebook/Allegro] Show browser window |
| `--radius N` | [Facebook] Override search radius in km |
| `--dry-run` | [Facebook] Preview city expansion without searching |
| `--debug` | Print URLs and response info |

Other commands: `market-scout providers` · `market-scout locations [CC]` · `market-scout find-location SLUG` · `market-scout init [PROVIDER]` · `market-scout config [--show] [--set KEY=VALUE]`

---

## Contributing

Feel free to try it and send feedback or PRs!

**Adding a new provider** takes about 50–200 lines of Python. See **[adding-a-provider.md](adding-a-provider.md)** for a step-by-step guide, including how to use AI tools like Claude Code to vibe-code the extension.

**Technical details** — architecture, data flow, provider internals, interface definitions — are in **[design.md](design.md)**.

## 🤝 Contributing

Issues and PRs are welcome!

## 📄 License

[MIT](LICENSE).

---

## Magyar összefoglaló

A **market-scout** egy parancssori eszköz, amely egyidejűleg keres több európai apróhirdetési oldalon — Magyarországon és azon túl. Egy paranccsal átkutatható a Hardverapró, Jófogás, Vatera, Facebook Marketplace, és tucatnyi más oldal Csehországtól Ukrajnáig.

**Főbb funkciók:**
- Több ország, egy keresés — `--provider HU` automatikusan keres a Hardveraprón, Jófogáson, Vatera-n és a Facebook Marketplace-en
- Automatikus fordítás — a találatok címe és állapota magyarra (vagy bármely más nyelvre) fordítható OpenRouter API kulccsal
- AI-elemzés — teljes hirdetésszöveg lekérése után egy LLM megválaszolja a kérdésedet (pl. *"Ez tényleg működő gép, vagy csak tartozék?"*), YES / MAYBE / NO értékeléssel
- Alternatív keresőkifejezések — az LLM javasol más neveket, amelyeken az eladók ugyanazt a terméket hirdetheti
- Kimeneti formátumok — Rich táblázat a terminálban, vagy mentés HTML / CSV / JSON / TXT fájlba

**Gyors példa (telepítés után):**
```bash
market-scout init facebook          # egyszeri Facebook bejelentkezés
market-scout search -q "Commodore 64" --provider HU
```

Az összes elérhető opciót a fenti táblázat tartalmazza.