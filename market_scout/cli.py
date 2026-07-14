"""market-scout — multi-marketplace CLI scraper."""
from __future__ import annotations

import sys
import io
import time
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box
from rich.prompt import Prompt, Confirm

from market_scout import config as cfg_module
from market_scout.providers import PROVIDERS, resolve_providers
from market_scout.providers.base import SearchRequest
from market_scout.providers.worldwide.facebook.location_db import (
    list_countries,
    list_cities,
    resolve_locations,
)
from market_scout.output import print_table
from market_scout.save import save as save_results

app = typer.Typer(
    name="market-scout",
    help="Search product marketplaces across countries for rare items.",
    add_completion=False,
)

# Ensure UTF-8 output on Windows (city names like Győr, Pécs, etc.)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

console = Console(stderr=True, highlight=False)
out = Console(highlight=False)


def _load_cfg() -> dict:
    """Load config, creating the file if it doesn't exist."""
    cfg_module.init_config_file()
    return cfg_module.load()


# ---------------------------------------------------------------------------
# Interactive approval helpers
# ---------------------------------------------------------------------------

def _approve_translation(original: str, translated: str, lang: str) -> str:
    """Show the translation, let the user approve or override it."""
    out.print(f"\n[bold]Query translation[/bold] → {lang}")
    out.print(f"  Original : [dim]{original}[/dim]")
    out.print(f"  Suggested: [cyan]{translated}[/cyan]")
    choice = Prompt.ask(
        "  Use this translation? [Y]es / [n]o (keep original) / or type your own",
        default="y",
        console=out,
    )
    c = choice.strip()
    if c.lower() in ("y", "yes", ""):
        return translated
    if c.lower() in ("n", "no"):
        return original
    return c  # user typed their own


def _approve_suggestions(original: str, suggestions: list[str]) -> list[str]:
    """Show alternative query suggestions, let the user pick/override."""
    out.print(f"\n[bold]Alternative search terms[/bold] for [cyan]{original!r}[/cyan]:")
    for i, s in enumerate(suggestions, 1):
        marker = "[dim](original)[/dim]" if s == original else ""
        out.print(f"  {i}. {s}  {marker}")

    out.print(
        "\n  [dim]Options:[/dim]\n"
        "  [bold]all[/bold]              — use all suggestions as-is\n"
        "  [bold]none[/bold]             — use only the original query\n"
        "  [bold]1,3,5[/bold]            — keep only selected numbers\n"
        "  [bold]1,3,my own term[/bold]  — keep numbers + add your own\n"
        "  [bold]override: a,b,c[/bold]  — replace everything with your own list"
    )
    choice = Prompt.ask("  Selection", default="all", console=out)
    c = choice.strip()

    # Override mode: replace entire list with user-supplied terms
    if c.lower().startswith("override:") or c.lower().startswith("override "):
        sep = ":" if ":" in c else " "
        raw = c.split(sep, 1)[1].strip()
        overrides = [t.strip() for t in raw.split(",") if t.strip()]
        return overrides if overrides else [original]

    cl = c.lower()
    if cl in ("all", ""):
        return suggestions
    if cl == "none":
        return [original]

    # Parse number selections and optional extra terms
    kept = []
    extras = []
    for part in c.split(","):
        part = part.strip()
        try:
            idx = int(part) - 1
            if 0 <= idx < len(suggestions):
                kept.append(suggestions[idx])
        except ValueError:
            if part:
                extras.append(part)

    if kept or extras:
        result = []
        if original not in kept:
            result.append(original)
        result.extend(kept)
        result.extend(extras)
        return result if result else [original]

    return [original]


# ---------------------------------------------------------------------------
# search command
# ---------------------------------------------------------------------------

@app.command(
    epilog=(
        "Examples:\n\n"
        "  # Hungarian providers — no location needed\n"
        "  market-scout search -q 'Amiga 500' -p hardverapro\n"
        "  market-scout search -q 'C64' -p 'hardverapro,jofogas,vatera' --min-price 5000 --max-price 100000\n\n"
        "  # Facebook — auto-detect location from cookies\n"
        "  market-scout search -q 'Amiga 500' --cookies cookies.json\n\n"
        "  # Facebook — multiple countries\n"
        "  market-scout search -q 'C64' -l DE,AT,HU,PL --cookies cookies.json\n\n"
        "  # Country shorthand selects all matching providers\n"
        "  market-scout search -q 'Amiga 500' -p HU\n\n"
        "  # Translation: translate query to Hungarian for HU providers\n"
        "  market-scout search -q 'Amiga 500' -p HU --translate-to HU\n\n"
        "  # Alternative query suggestions\n"
        "  market-scout search -q 'Amiga 500' --suggest-queries\n\n"
        "  # Translate results back to English\n"
        "  market-scout search -q 'Amiga 500' -p HU --translate-results EN\n\n"
        "  # Dry run: see FB expansion plan\n"
        "  market-scout search -q 'Spectrum' -l DE,AT,PL,HU --dry-run\n"
    ),
)
def search(
    query: str = typer.Option(..., "--query", "-q", help="Search term"),
    provider: str = typer.Option(
        "", "--provider", "-p",
        help=(
            "Provider(s), comma-separated. "
            "Available: " + ", ".join(PROVIDERS) + ". "
            "Defaults to config default or all providers. "
            "You can also pass a two-letter country code to select all providers for that country "
            "(e.g. --provider HU selects hardverapro, jofogas, vatera). "
            "Hungarian-only providers (hardverapro, jofogas, vatera) ignore --location and --radius."
        ),
    ),
    location: str = typer.Option(
        "", "--location", "-l",
        help=(
            "[Facebook only] Where to search — comma-separated list of tokens. "
            "Each token is resolved in order: "
            "(1) two-letter country code (DE, AT, HU, …) → expands to all cities for that country "
            "from the built-in DB, each with its own tuned radius; "
            "(2) city slug (berlin, vienna, budapest) or numeric FB city ID → "
            "passed directly to Facebook, radius from --radius or FB default ~40 km; "
            "(3) empty → Facebook auto-detects from your cookies/account location. "
            "Tokens can be mixed freely, e.g. 'DE,vienna,warsaw'. "
            "Run 'market-scout locations' to browse all country codes and city slugs."
        ),
    ),
    min_price: Optional[int] = typer.Option(None, "--min-price", help="Minimum price filter. If --currency is set, specify in that currency; otherwise in the provider's native currency."),
    max_price: Optional[int] = typer.Option(None, "--max-price", help="Maximum price filter. If --currency is set, specify in that currency; otherwise in the provider's native currency."),
    currency: Optional[str] = typer.Option(
        None, "--currency",
        help=(
            "Display all prices in this currency and convert price filters accordingly. "
            "Example: EUR, USD, GBP. Converted prices show a ≈ prefix. "
            "Original price is shown in the HTML tooltip. "
            "Requires network access to fetch exchange rates (Frankfurter/ECB + open.er-api.com for UAH/BGN)."
        ),
    ),
    max_results: Optional[int] = typer.Option(
        None, "--max-results", "-n",
        help="Max listings to collect per city search (Facebook) or per page-run (other providers). Defaults to config value (30).",
    ),
    cookies: Optional[Path] = typer.Option(
        None, "--cookies", "-c",
        help=(
            "[Facebook only] Path to cookies JSON exported from a logged-in Chrome session. "
            "Defaults to the path in config.toml if set."
        ),
    ),
    headless: Optional[bool] = typer.Option(
        None, "--headless/--no-headless",
        help="[Facebook only] Run Chromium headlessly (default from config). Use --no-headless for first-time login.",
    ),
    scrape_details: bool = typer.Option(
        False, "--details/--no-details",
        help=(
            "Open each listing's detail page to collect the full description. "
            "Slower — one extra HTTP request or browser tab per listing. "
            "Required for --details-ai."
        ),
    ),
    details_ai: Optional[str] = typer.Option(
        None, "--details-ai",
        help=(
            "After fetching descriptions (implies --details), ask the LLM whether each listing "
            "matches your free-text question. Adds a YES/MAYBE/NO confidence column to the output. "
            "Requires OpenRouter API key. "
            "Example: --details-ai \"Is it really an Amiga 500 in good condition?\""
        ),
    ),
    radius_km: Optional[int] = typer.Option(
        None, "--radius",
        help="[Facebook only] Search radius in km (0 = use DB defaults). Defaults to config value.",
    ),
    translate_to: Optional[str] = typer.Option(
        None, "--translate-to",
        help=(
            "Translate the search query into the specified language before searching. "
            "Requires OpenRouter API key in config.toml. "
            "You will be shown the translation and asked to approve or override it. "
            "Example: --translate-to HU  (for Hungarian providers)  --translate-to DE  (for German)"
        ),
    ),
    translate_results: Optional[str] = typer.Option(
        None, "--translate-results",
        help=(
            "Translate result titles into the specified language. "
            "Overrides the user_lang setting in config.toml for this run. "
            "Example: --translate-results EN"
        ),
    ),
    no_translate: bool = typer.Option(
        False, "--no-translate",
        help=(
            "Skip automatic result translation even if user_lang is set in config.toml. "
            "Useful when you want raw titles in the original language."
        ),
    ),
    suggest_queries: bool = typer.Option(
        False, "--suggest-queries",
        help=(
            "Ask the LLM to suggest alternative search terms (abbreviations, regional names, synonyms). "
            "You will be shown the suggestions and asked to approve or edit them before searching. "
            "Each approved variant is searched separately; results are merged. "
            "Requires OpenRouter API key in config.toml."
        ),
    ),
    save_format: Optional[str] = typer.Option(
        None, "--save",
        help=(
            "Also save results to a timestamped file in ./output/. "
            "Formats: json, csv, txt, html. "
            "Can be comma-separated for multiple: --save 'csv,html'. "
            "Console output is always shown regardless of this flag."
        ),
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="[Facebook only] Show the resolved city/radius plan without running any scraping.",
    ),
    debug: bool = typer.Option(
        False, "--debug",
        help="Print provider-level debug info: exact URLs fetched, redirect chain, response size, first result title.",
    ),
):
    """Search marketplaces for items matching QUERY."""

    # --- Load config and apply defaults for unset flags ---
    cfg = _load_cfg()
    effective_providers = provider or ",".join(cfg.get("providers", []))
    effective_location = location or cfg.get("location", "")
    effective_radius = radius_km if radius_km is not None else cfg.get("radius", 0)
    effective_max = max_results if max_results is not None else cfg.get("max_results", 30)
    effective_headless = headless if headless is not None else cfg.get("headless", True)
    effective_cookies = cookies
    if effective_cookies is None and cfg.get("cookies"):
        p = Path(cfg["cookies"]).expanduser()
        if p.exists():
            effective_cookies = p

    # --- Resolve providers ---
    provider_names = resolve_providers([p.strip() for p in effective_providers.split(",") if p.strip()])
    location_tokens = [loc.strip() for loc in effective_location.split(",") if loc.strip()]

    unknown = [n for n in provider_names if n not in PROVIDERS]
    if unknown:
        console.print(f"[red]Unknown provider(s): {', '.join(unknown)}[/red]")
        console.print(f"Available: {', '.join(PROVIDERS)}")
        raise typer.Exit(code=1)

    if dry_run:
        pairs = resolve_locations(location_tokens, effective_radius)
        t = Table(title="Resolved Facebook search locations (--dry-run)", box=box.ROUNDED)
        t.add_column("City / ID", style="bold")
        t.add_column("Radius km", style="cyan")
        for slug, r in pairs:
            t.add_row(slug or "(auto-detect)", str(r) if r else "FB default (~40 km)")
        out.print(t)
        out.print(f"[dim]{len(pairs)} Facebook city search(es) would run. Other providers ignore --location.[/dim]")
        return

    # --- LLM setup ---
    llm_cfg = cfg.get("openrouter", {})
    llm_key = cfg_module.get_openrouter_key(cfg)
    llm_model = llm_cfg.get("model", "anthropic/claude-haiku-4-5")
    llm_base = llm_cfg.get("base_url", "https://openrouter.ai/api/v1")

    # Determine effective result translation target:
    # --translate-results overrides; --no-translate suppresses; otherwise use user_lang from config
    user_lang = cfg.get("user_lang", "en").strip()
    if no_translate:
        effective_translate_results = None
    elif translate_results:
        effective_translate_results = translate_results.strip()
    elif user_lang and llm_key:
        effective_translate_results = user_lang
    else:
        effective_translate_results = None

    # --details-ai implies --details
    if details_ai:
        scrape_details = True

    # Guard: abort early if an explicit LLM feature is requested but no key is configured
    if (suggest_queries or translate_to or details_ai or (translate_results and not llm_key)) and not llm_key:
        console.print(
            "\n[red]OpenRouter API key required[/red] for LLM features "
            "(--suggest-queries, --translate-to, --translate-results, --details-ai).\n"
            "\n"
            "Set it with one of:\n"
            "  [bold]market-scout config --set openrouter.api_key=sk-or-v1-your-key[/bold]\n"
            "  [bold]export OPENROUTER_API_KEY=sk-or-v1-your-key[/bold]\n"
            "\n"
            "Get a key at [link=https://openrouter.ai/keys]https://openrouter.ai/keys[/link] "
            "(free tier available).\n"
        )
        raise typer.Exit(code=1)

    # --- Build effective query list ---
    queries: list[str] = [query]

    if suggest_queries:
        console.print(f"[cyan]Asking LLM for alternative search terms...[/cyan]")
        try:
            from market_scout.llm import suggest_queries as llm_suggest
            suggestions = llm_suggest(query, llm_model, llm_key, llm_base, details_ai=details_ai or "")
            queries = _approve_suggestions(query, suggestions)
            console.print(f"[green]Using {len(queries)} search term(s):[/green] {', '.join(repr(q) for q in queries)}")
        except Exception as exc:
            console.print(f"[red]LLM suggestion failed:[/red] {exc}")
            console.print("[dim]Continuing with original query.[/dim]")

    # --- Per-query translation ---
    translated_queries: dict[str, str] = {}  # query → translated (or same if no translation)
    if translate_to:
        from market_scout.llm import translate_query as llm_translate
        for q in queries:
            console.print(f"[cyan]Translating {q!r} → {translate_to}...[/cyan]")
            try:
                translated = llm_translate(q, translate_to, llm_model, llm_key, llm_base)
                approved = _approve_translation(q, translated, translate_to)
                translated_queries[q] = approved
            except Exception as exc:
                console.print(f"[red]Translation failed:[/red] {exc}")
                translated_queries[q] = q
    else:
        for q in queries:
            translated_queries[q] = q

    # --- Run searches ---
    all_listings = []
    seen_urls: set[str] = set()
    provider_times: dict[str, float] = {}  # pname → total seconds
    total_start = time.perf_counter()

    # --- Currency setup ---
    target_currency = (currency or "").strip().upper()
    if target_currency:
        from market_scout.currency import supported as currency_supported, convert_price_filter
        if not currency_supported(target_currency):
            console.print(f"[red]Unknown or unsupported currency: {target_currency!r}[/red]")
            console.print("[dim]Rates are fetched from Frankfurter (ECB) and open.er-api.com.[/dim]")
            raise typer.Exit(code=1)

    for original_q in queries:
        effective_q = translated_queries.get(original_q, original_q)
        display_q = f"{original_q!r} [dim]({effective_q})[/dim]" if effective_q != original_q else repr(original_q)

        req = SearchRequest(
            query=effective_q,
            locations=location_tokens,
            min_price=min_price,
            max_price=max_price,
            max_results=effective_max,
            cookies_file=effective_cookies,
            headless=effective_headless,
            scrape_details=scrape_details,
            radius_km=effective_radius,
            debug=debug,
            target_currency=target_currency,
        )

        for pname in provider_names:
            prov = PROVIDERS[pname]
            if pname == "facebook":
                pairs = resolve_locations(location_tokens, effective_radius)
                loc_summary = (
                    ", ".join(f"{s or 'auto'}+{r}km" if r else (s or "auto") for s, r in pairs)
                    if location_tokens else "auto-detect"
                )
                loc_note = f"| locations: {loc_summary} | {len(pairs)} city search(es)"
            else:
                prov_countries = getattr(prov, "countries", [])
                has_geo = location_tokens and any(
                    t.upper() in prov_countries for t in location_tokens
                )
                # Warn only for multi-country providers (like Wallapop) where location
                # determines which country's pool is searched. Single-country providers
                # (like willhaben=AT) are nationwide by definition — no warning needed.
                is_multi_country = len(prov_countries) > 1 and "*" not in prov_countries
                if has_geo:
                    loc_note = f"[dim](geo-filtered: {', '.join(t for t in location_tokens if t.upper() in prov_countries)})[/dim]"
                elif is_multi_country and not has_geo:
                    loc_note = (
                        f"[yellow]⚠ no location specified[/yellow] "
                        f"[dim]— pass --location {'/'.join(prov_countries[:3])} for results[/dim]"
                    )
                else:
                    loc_note = "[dim](location ignored — nationwide)[/dim]"
            console.print(
                f"[cyan]Searching[/cyan] [bold]{pname}[/bold] for {display_q} "
                + loc_note
                + (f" | price: {min_price}–{max_price}" if min_price or max_price else "")
            )
            try:
                t0 = time.perf_counter()
                results = prov.search(req)
                elapsed = time.perf_counter() - t0
                provider_times[pname] = provider_times.get(pname, 0.0) + elapsed
                new_results = [r for r in results if r.url not in seen_urls]
                for r in new_results:
                    seen_urls.add(r.url)
                console.print(
                    f"[green]✓[/green] {len(new_results)} new result(s) from {pname} "
                    f"[dim]({elapsed:.1f}s)[/dim]"
                )
                all_listings.extend(new_results)
            except Exception as exc:
                provider_times[pname] = provider_times.get(pname, 0.0)
                console.print(f"[red]Error from {pname}:[/red] {exc}")

    # --- Normalise posted dates ---
    # Programmatic normalisation runs for all listings (free, fast).
    # LLM fallback only fires for listings whose date couldn't be parsed
    # programmatically (e.g. Facebook relative strings like "25 weeks ago").
    from market_scout.dates import normalise as normalise_date
    has_unparsed = False
    for lst in all_listings:
        if lst.posted:
            normalised = normalise_date(lst.posted)
            if normalised:
                lst.posted = normalised
            else:
                has_unparsed = True  # raw string left; may need LLM

    if has_unparsed and llm_key:
        # Collect unique unparsed values, translate in one batch
        unique_raw = list({lst.posted for lst in all_listings
                           if lst.posted and not lst.posted.startswith("20")})
        if unique_raw:
            from market_scout.dates import _llm_parse
            resolved: dict[str, str] = {}
            for raw in unique_raw:
                parsed = _llm_parse(raw, llm_model, llm_key, llm_base)
                if parsed:
                    resolved[raw] = parsed
            if resolved:
                for lst in all_listings:
                    if lst.posted in resolved:
                        lst.posted = resolved[lst.posted]

    # --- Translate results ---
    if effective_translate_results and all_listings:
        from market_scout.llm import translate_listings, _BATCH_SIZE

        # Country codes whose native language matches common user_lang values.
        # Listings from these countries are skipped when user_lang matches.
        _COUNTRY_LANG: dict[str, str] = {
            "DE": "de", "AT": "de", "CH": "de",
            "HU": "hu",
            "PL": "pl",
            "CZ": "cs",
            "SK": "sk",
            "RO": "ro",
            "PT": "pt",
            "BG": "bg",
            "UA": "uk",
            "GB": "en", "US": "en", "AU": "en",
            "FR": "fr",
            "ES": "es",
            "IT": "it",
            "NL": "nl",
        }
        target_lang = effective_translate_results.lower().strip()

        # Identify which listings actually need translation
        needs_translation = [
            lst for lst in all_listings
            if _COUNTRY_LANG.get(lst.provider_country.upper(), "").lower() != target_lang
        ]
        skip_count = len(all_listings) - len(needs_translation)

        source = "auto" if not translate_results and not no_translate else ("--translate-results" if translate_results else "config")
        n = len(needs_translation)
        if n == 0:
            console.print(
                f"[dim]Skipping translation — all results are already in {effective_translate_results}[/dim]"
            )
        else:
            batches = (n + _BATCH_SIZE - 1) // _BATCH_SIZE
            console.print(
                f"[cyan]Translating {n} result(s) → {effective_translate_results}[/cyan] "
                f"[dim]({batches} batch(es) of ≤{_BATCH_SIZE}, {skip_count} skipped — already {effective_translate_results}) (user_lang from {source})[/dim]"
            )
        try:
            if n > 0:
                # Translate titles — only for listings that need it
                titles_to_translate = [lst.title for lst in needs_translation]
                translated_titles = translate_listings(titles_to_translate, effective_translate_results, llm_model, llm_key, llm_base)
                for lst, new_title in zip(needs_translation, translated_titles):
                    if new_title and new_title != lst.title:
                        lst.title = f"{new_title} [{lst.title}]"

                # Translate conditions — only from listings that need translation
                unique_conditions = list({lst.condition for lst in needs_translation if lst.condition})
                if unique_conditions:
                    translated_conditions = translate_listings(
                        unique_conditions, effective_translate_results, llm_model, llm_key, llm_base
                    )
                    cond_map = dict(zip(unique_conditions, translated_conditions))
                    for lst in needs_translation:
                        if lst.condition and lst.condition in cond_map:
                            lst.condition = cond_map[lst.condition]

                console.print(f"[green]✓[/green] Translated to {effective_translate_results}")
        except Exception as exc:
            console.print(f"[red]Result translation failed:[/red] {exc}")

    # --- AI confidence scoring (--details-ai) ---
    if details_ai and all_listings and llm_key:
        from market_scout.llm import analyse_listing
        to_analyse = [(i, lst) for i, lst in enumerate(all_listings) if lst.description]
        no_desc = len(all_listings) - len(to_analyse)
        console.print(
            f"[cyan]Analysing {len(to_analyse)} listing(s)[/cyan] against: [bold]{details_ai!r}[/bold]"
            + (f" [dim]({no_desc} skipped — no description)[/dim]" if no_desc else "")
        )
        for i, lst in to_analyse:
            lst.ai_match = analyse_listing(lst.description, details_ai, llm_model, llm_key, llm_base, search_query=query, title=lst.title, user_lang=user_lang or "en")
        if no_desc:
            for lst in all_listings:
                if not lst.description and not lst.ai_match:
                    lst.ai_match = "MAYBE — no description available"
        console.print(f"[green]✓[/green] AI scoring complete")

    # --- Currency conversion ---
    # original_prices: {url -> (original_price_str, original_currency)}
    original_prices: dict[str, tuple[str, str]] = {}
    if target_currency and all_listings:
        from market_scout.currency import parse_price, convert
        converted_count = 0
        for lst in all_listings:
            if lst.currency.upper() == target_currency or lst.currency == "":
                continue  # already in target, or unknown/non-numeric currency
            amount = parse_price(lst.price)
            if amount is None:
                continue  # non-numeric price — skip
            result = convert(amount, lst.currency, target_currency)
            if result is None:
                continue  # unknown exchange rate — skip
            original_prices[lst.url] = (lst.price, lst.currency)
            lst.price = str(int(round(result))) if result == int(result) else f"{result:.2f}"
            lst.currency = target_currency
            converted_count += 1
        if converted_count:
            console.print(f"[dim]≈ {converted_count} price(s) converted to {target_currency}[/dim]")

    # --- Always print to console ---
    print_table(all_listings, original_prices=original_prices)

    # --- Timing summary ---
    total_elapsed = time.perf_counter() - total_start
    if provider_times:
        parts = "  ".join(
            f"{pname} {t:.1f}s" for pname, t in provider_times.items()
        )
        console.print(
            f"[dim]⏱  {parts}  │  total {total_elapsed:.1f}s[/dim]"
        )

    # --- Save to file(s) if --save is specified ---
    if save_format and all_listings:
        from datetime import datetime, timezone
        run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        meta = {
            "query": query,
            "providers": provider_names,
            "locations": location_tokens,
            "min_price": min_price,
            "max_price": max_price,
            "max_results": effective_max,
            "result_count": len(all_listings),
            "run_at": run_at,
            "translate_to": effective_translate_results,
            "target_currency": target_currency,
        }
        for fmt in [f.strip() for f in save_format.split(",") if f.strip()]:
            try:
                path = save_results(fmt, all_listings, meta, original_prices=original_prices)
                if path:
                    console.print(f"[green]✓[/green] Saved {fmt.upper()} → [bold]{path}[/bold]")
                else:
                    console.print(f"[yellow]Unknown save format:[/yellow] {fmt!r}. Use: json, csv, txt, html")
            except Exception as exc:
                console.print(f"[red]Failed to save {fmt}:[/red] {exc}")


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------

# Providers that require a one-time human action before headless use
_INIT_PROVIDERS: dict[str, dict] = {
    "facebook": {
        "label": "Facebook Marketplace",
        "note": (
            "Requires a logged-in Facebook session (cookies.json).\n"
            "The browser opens facebook.com/marketplace — log in and the cookies\n"
            "are saved automatically. Pass --cookies to specify the file path."
        ),
    },
    "allegro_pl": {
        "label": "Allegro Poland (allegro.pl)",
        "note": (
            "Allegro uses DataDome bot detection. The browser opens allegro.pl —\n"
            "solve the CAPTCHA once and the session is saved to\n"
            "~/.market-scout/allegro-profile/pl/"
        ),
    },
    "allegro_cz": {
        "label": "Allegro Czechia (allegro.cz)",
        "note": (
            "Allegro uses DataDome bot detection. The browser opens allegro.cz —\n"
            "solve the CAPTCHA once and the session is saved to\n"
            "~/.market-scout/allegro-profile/cz/"
        ),
    },
    "allegro_sk": {
        "label": "Allegro Slovakia (allegro.sk)",
        "note": (
            "Allegro uses DataDome bot detection. The browser opens allegro.sk —\n"
            "solve the CAPTCHA once and the session is saved to\n"
            "~/.market-scout/allegro-profile/sk/"
        ),
    },
}


@app.command()
def init(
    provider_name: str = typer.Argument(
        None,
        help=(
            "Provider to initialise. One of: facebook, allegro_pl, allegro_cz, allegro_sk. "
            "Omit to see the list of providers that require initialisation."
        ),
    ),
    cookies: Optional[Path] = typer.Option(
        None, "--cookies", "-c",
        help="[Facebook only] Path to save the cookies JSON file. Defaults to cookies.json in the current directory.",
    ),
):
    """Initialise a provider that requires a one-time browser session setup.

    \b
    Providers requiring init:
      facebook     — log in to Facebook once; cookies.json is saved automatically
      allegro_pl   — solve DataDome CAPTCHA once for allegro.pl
      allegro_cz   — solve DataDome CAPTCHA once for allegro.cz
      allegro_sk   — solve DataDome CAPTCHA once for allegro.sk

    \b
    Examples:
      market-scout init
      market-scout init facebook
      market-scout init facebook --cookies ~/.market-scout/cookies.json
      market-scout init allegro_pl
      market-scout init allegro_cz
    """
    if provider_name is None:
        t = Table(title="Providers requiring one-time initialisation", box=box.ROUNDED)
        t.add_column("Provider", style="bold cyan")
        t.add_column("Site")
        t.add_column("What to do")
        rows = {
            "facebook":   ("facebook.com/marketplace", "Log in with your Facebook account"),
            "allegro_pl": ("allegro.pl",                "Solve the DataDome CAPTCHA"),
            "allegro_cz": ("allegro.cz",                "Solve the DataDome CAPTCHA"),
            "allegro_sk": ("allegro.sk",                "Solve the DataDome CAPTCHA"),
        }
        for p, (site, action) in rows.items():
            t.add_row(p, site, action)
        out.print(t)
        out.print(
            "\n[dim]Run 'market-scout init <provider>' to open the browser and complete setup.[/dim]"
        )
        return

    if provider_name not in _INIT_PROVIDERS:
        console.print(f"[red]Unknown provider: {provider_name!r}[/red]")
        console.print(f"Providers that need init: {', '.join(_INIT_PROVIDERS)}")
        raise typer.Exit(code=1)

    info = _INIT_PROVIDERS[provider_name]
    console.print(f"\n[bold]Initialising:[/bold] {info['label']}")
    console.print(f"[dim]{info['note']}[/dim]\n")

    if provider_name == "facebook":
        import asyncio
        from market_scout.providers.worldwide.facebook.scraper import run_scrape
        from market_scout.providers.worldwide.facebook.config import FbScraperConfig

        cookie_path = cookies or Path("cookies.json")
        console.print(
            f"Opening Facebook Marketplace in a visible browser window.\n"
            f"Log in and wait — the browser will close automatically once the\n"
            f"session is established. Cookies will be saved to: [bold]{cookie_path}[/bold]\n"
        )
        cfg = FbScraperConfig(
            search_query="",
            max_listings=1,
            max_scrolls=0,
            headless=False,
            cookies_file=cookie_path,
        )
        asyncio.run(run_scrape(cfg))
        if cookie_path.exists():
            out.print(f"\n[green]✓[/green] Cookies saved to [bold]{cookie_path}[/bold]")
            out.print(
                f"\n[dim]Now run searches with --cookies {cookie_path}[/dim]\n"
                f"[dim]Or set it as default: market-scout config --set cookies={cookie_path}[/dim]"
            )
        else:
            console.print(f"[yellow]Warning:[/yellow] cookies.json was not written. Did login complete?")

    elif provider_name.startswith("allegro_"):
        import asyncio
        from market_scout.providers.multi.allegro.scraper import _PROFILE_DIR, _run_search
        from market_scout.providers.base import SearchRequest

        domain = provider_name.split("_")[1]  # "pl", "cz", "sk"
        profile_dir = _PROFILE_DIR / domain
        console.print(
            f"Opening allegro.{domain} in a visible browser.\n"
            f"Solve the CAPTCHA when it appears — the session will be saved to:\n"
            f"  [bold]{profile_dir}[/bold]\n"
            f"The browser will close automatically once the search page loads.\n"
        )
        req = SearchRequest(
            query="test",
            max_results=1,
            headless=False,
        )
        asyncio.run(_run_search(domain, req))
        if any(profile_dir.iterdir()):
            out.print(f"\n[green]✓[/green] Session saved to [bold]{profile_dir}[/bold]")
            out.print(f"[dim]Future headless searches for {provider_name} will reuse this session.[/dim]")
        else:
            console.print(f"[yellow]Warning:[/yellow] Profile directory is empty. Was the CAPTCHA solved?")


# ---------------------------------------------------------------------------
# providers command
# ---------------------------------------------------------------------------

@app.command()
def providers():
    """List available marketplace providers and the countries they cover."""
    t = Table(box=box.ROUNDED)
    t.add_column("Provider", style="bold cyan")
    t.add_column("Countries")
    t.add_column("Note", style="dim")
    for name, prov in PROVIDERS.items():
        countries = ", ".join(prov.countries)
        note = "location-aware (use --location)" if "*" in prov.countries else "nationwide only"
        t.add_row(name, countries, note)
    out.print(t)
    out.print("\n[dim]Pass a country code to --provider to select all matching providers, e.g. --provider HU[/dim]")


# ---------------------------------------------------------------------------
# locations command
# ---------------------------------------------------------------------------

@app.command()
def locations(
    country: Optional[str] = typer.Argument(
        None,
        help="Country code to show cities for (e.g. DE). Omit to list all countries.",
    ),
):
    """List known European countries and their Facebook city slugs."""
    if country:
        cities = list_cities(country.upper())
        if not cities:
            console.print(f"[red]Unknown country code: {country.upper()}[/red]")
            raise typer.Exit(code=1)
        t = Table(title=f"Cities for {country.upper()} (Facebook slugs)", box=box.ROUNDED)
        t.add_column("Slug", style="bold cyan")
        t.add_column("Name")
        t.add_column("Default radius km", style="green")
        t.add_column("FB ID (if known)", style="dim")
        for c in cities:
            t.add_row(c["slug"], c["name"], str(c["radius_km"]), c.get("fb_id", ""))
        out.print(t)
        out.print(f"\n[dim]Usage: --location {country.upper()}   (expands to all {len(cities)} cities)[/dim]")
    else:
        countries = list_countries()
        t = Table(title="Known European countries", box=box.ROUNDED)
        t.add_column("Code", style="bold cyan", width=6)
        t.add_column("Country")
        t.add_column("Cities", style="green", justify="right")
        for row in countries:
            t.add_row(row["code"], row["name"], str(row["city_count"]))
        out.print(t)
        out.print("\n[dim]Run 'market-scout locations DE' to see cities for a country.[/dim]")


# ---------------------------------------------------------------------------
# find-location command
# ---------------------------------------------------------------------------

@app.command("find-location")
def find_location(
    slug: str = typer.Argument(..., help="City slug or name to look up (e.g. 'gyor', 'pecs', 'miskolc')"),
    cookies: Optional[Path] = typer.Option(None, "--cookies", "-c", help="Facebook cookies JSON."),
    headless: bool = typer.Option(
        False, "--no-headless/--headless",
        help="Default: visible browser. Pass --headless only if cookies are valid.",
    ),
):
    """Look up the numeric Facebook city ID for a slug that FB doesn't recognise.

    \b
    Examples:
      market-scout find-location gyor
      market-scout find-location gyor --cookies cookies.json
      market-scout find-location miskolc --headless --cookies cookies.json

    Once you have an ID, pass it directly to --location:
      market-scout search --query "C64" --location 109233199097493 --radius 80
    """
    import asyncio
    from market_scout.providers.worldwide.facebook.scraper import discover_city_id

    console.print(f"[cyan]Looking up Facebook city ID for:[/cyan] [bold]{slug}[/bold]")
    cfg = _load_cfg()
    cookie_path = cookies
    if cookie_path is None and cfg.get("cookies"):
        cookie_path = Path(cfg["cookies"]).expanduser()
    city_id = asyncio.run(discover_city_id(slug, cookie_path or Path("cookies.json"), headless=headless))
    if city_id:
        out.print(f"\n[green]Found ID:[/green] [bold]{city_id}[/bold]")
        out.print(f"\n[dim]Use it like:[/dim]")
        out.print(f"  market-scout search --query \"<your query>\" --location {city_id} --radius 50")
    else:
        console.print(
            f"[yellow]Could not find a numeric ID for '{slug}'.[/yellow]\n"
            f"Try running with --no-headless and check the browser URL bar after it loads."
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# config command
# ---------------------------------------------------------------------------

@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="Show the current config file path and contents."),
    set_: Optional[str] = typer.Option(None, "--set", help="Set a config value: key=value (e.g. --set openrouter.api_key=sk-or-v1-...)"),
    init: bool = typer.Option(False, "--init", help="Create the config file with defaults if it doesn't exist."),
):
    """View and edit the global configuration file.

    \b
    Config file: ~/.market-scout/config.toml

    Examples:
      market-scout config --show
      market-scout config --init
      market-scout config --set openrouter.api_key=sk-or-v1-your-key-here
      market-scout config --set providers=hardverapro,jofogas,vatera
      market-scout config --set max_results=50
      market-scout config --set cookies=~/.market-scout/cookies.json
    """
    path = cfg_module.init_config_file()

    if init:
        out.print(f"[green]Config file ready:[/green] {path}")
        return

    if set_:
        if "=" not in set_:
            console.print(f"[red]Invalid format. Use key=value, e.g. --set openrouter.api_key=abc[/red]")
            raise typer.Exit(code=1)
        key, value = set_.split("=", 1)
        cfg_module.set_value(key.strip(), value.strip())
        out.print(f"[green]Set[/green] [bold]{key.strip()}[/bold] = {value.strip()}")
        out.print(f"[dim]Config file: {path}[/dim]")
        return

    if show or (not init and not set_):
        out.print(f"[bold]Config file:[/bold] {path}")
        if path.exists():
            out.print()
            out.print(path.read_text(encoding="utf-8"))
        else:
            out.print("[dim](file does not exist yet — run 'market-scout config --init')[/dim]")


if __name__ == "__main__":
    app()
