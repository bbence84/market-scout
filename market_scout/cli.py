"""market-scout — multi-marketplace CLI scraper."""
from __future__ import annotations

import sys
import io
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from market_scout.providers import PROVIDERS, resolve_providers
from market_scout.providers.base import SearchRequest
from market_scout.providers.worldwide.facebook.location_db import (
    list_countries,
    list_cities,
    resolve_locations,
)
from market_scout.output import print_table, print_json

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


class OutputFormat(str, Enum):
    table = "table"
    json = "json"


@app.command(
    epilog=(
        "Examples:\n\n"
        "  # Hungarian providers — no location needed\n"
        "  market-scout search -q 'Amiga 500' -p hardverapro\n"
        "  market-scout search -q 'C64' -p 'hardverapro,jofogas,vatera' --min-price 5000 --max-price 100000\n\n"
        "  # Facebook — auto-detect location from cookies\n"
        "  market-scout search -q 'Amiga 500' --cookies cookies.json\n\n"
        "  # Facebook — single country (expands to all known cities)\n"
        "  market-scout search -q 'Amiga 500' -l DE --cookies cookies.json\n\n"
        "  # Facebook — multiple countries\n"
        "  market-scout search -q 'C64' -l DE,AT,HU,PL --cookies cookies.json\n\n"
        "  # Facebook — mix country code + bare city slug\n"
        "  market-scout search -q 'retro' -l 'DE,vienna,warsaw' --cookies cookies.json\n\n"
        "  # Facebook — override radius for all cities\n"
        "  market-scout search -q 'Amiga' -l DE,AT --radius 200 --cookies cookies.json\n\n"
        "  # Facebook — visible browser (first login / debugging)\n"
        "  market-scout search -q 'C64' -l berlin --no-headless\n\n"
        "  # Preview FB city expansion without scraping\n"
        "  market-scout search -q 'anything' -l DE,AT,HU --dry-run\n\n"
        "  # All Hungarian providers + Facebook together\n"
        "  market-scout search -q 'Amiga 500' -p 'facebook,hardverapro,jofogas,vatera' -l HU --cookies cookies.json\n\n"
        "  # Debug: see URLs being fetched\n"
        "  market-scout search -q 'Amiga 500' -p hardverapro --debug\n"
    ),
)
def search(
    query: str = typer.Option(..., "--query", "-q", help="Search term"),
    provider: str = typer.Option(
        "", "--provider", "-p",
        help=(
            "Provider(s), comma-separated. "
            "Available: " + ", ".join(PROVIDERS) + ". "
            "Defaults to all providers when omitted. "
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
            "(2) city slug (berlin, vienna, budapest) or numeric FB city ID (109233199097493) → "
            "passed directly to Facebook, radius from --radius or FB default ~40 km; "
            "(3) empty → Facebook auto-detects from your cookies/account location. "
            "Tokens can be mixed freely, e.g. 'DE,vienna,warsaw'. "
            "Run 'market-scout locations' to browse all country codes and city slugs. "
            "Run 'market-scout find-location <slug>' to get the numeric ID for a city."
        ),
    ),
    min_price: Optional[int] = typer.Option(None, "--min-price", help="Minimum price filter (all providers)"),
    max_price: Optional[int] = typer.Option(None, "--max-price", help="Maximum price filter (all providers)"),
    max_results: int = typer.Option(
        30, "--max-results", "-n",
        help="Max listings to collect per city search (Facebook) or per page-run (other providers)",
    ),
    cookies: Optional[Path] = typer.Option(
        None, "--cookies", "-c",
        help=(
            "[Facebook only] Path to cookies JSON exported from a logged-in Chrome session "
            "(use the EditThisCookie extension). "
            "Without cookies, Facebook shows limited results or a login wall. "
            "Cookies are refreshed and saved back automatically after each run."
        ),
    ),
    headless: bool = typer.Option(
        True, "--headless/--no-headless",
        help=(
            "[Facebook only] Run Chromium in headless mode (default). "
            "Use --no-headless to see the browser — required for first-time login "
            "or when debugging bot detection issues. "
            "After logging in with --no-headless, cookies are saved and future runs can be headless."
        ),
    ),
    scrape_details: bool = typer.Option(
        False, "--details/--no-details",
        help=(
            "[Facebook only] Open each listing's detail page to collect "
            "full description, seller name, and condition. "
            "Significantly slower — one extra browser tab per listing."
        ),
    ),
    radius_km: int = typer.Option(
        0, "--radius",
        help=(
            "[Facebook only] Search radius in km around each city. "
            "When 0 (default): country expansions use the per-city radius from the built-in DB "
            "(e.g. berlin=150, vienna=120); bare city slugs use Facebook's default (~40 km). "
            "When set to any positive value: overrides ALL per-city radii. "
            "Example: --radius 200 searches a 200 km circle around every resolved city."
        ),
    ),
    translate_to: Optional[str] = typer.Option(
        None, "--translate-to",
        help="[stub, not yet implemented] Target language for query and results translation.",
    ),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output", "-o", help="Output format: table (default) or json"),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help=(
            "[Facebook only] Show the resolved city/radius plan without running any scraping. "
            "Use before a large multi-country search to see how many browser sessions would run."
        ),
    ),
    debug: bool = typer.Option(
        False, "--debug",
        help="Print provider-level debug info: exact URLs fetched, redirect chain, response size, first result title.",
    ),
):
    """Search marketplaces for items matching QUERY."""
    if translate_to:
        console.print(
            "[yellow]Warning:[/yellow] --translate-to is not yet implemented. "
            "Query and results will remain in the original language."
        )

    provider_names = resolve_providers([p.strip() for p in provider.split(",") if p.strip()])
    location_tokens = [loc.strip() for loc in location.split(",") if loc.strip()]

    unknown = [n for n in provider_names if n not in PROVIDERS]
    if unknown:
        console.print(f"[red]Unknown provider(s): {', '.join(unknown)}[/red]")
        console.print(f"Available: {', '.join(PROVIDERS)}")
        raise typer.Exit(code=1)

    if dry_run:
        pairs = resolve_locations(location_tokens, radius_km)
        t = Table(title="Resolved Facebook search locations (--dry-run)", box=box.ROUNDED)
        t.add_column("City / ID", style="bold")
        t.add_column("Radius km", style="cyan")
        for slug, r in pairs:
            t.add_row(slug or "(auto-detect)", str(r) if r else "FB default (~40 km)")
        out.print(t)
        out.print(f"[dim]{len(pairs)} Facebook city search(es) would run. Other providers ignore --location.[/dim]")
        return

    req = SearchRequest(
        query=query,
        locations=location_tokens,
        min_price=min_price,
        max_price=max_price,
        max_results=max_results,
        cookies_file=cookies,
        headless=headless,
        scrape_details=scrape_details,
        radius_km=radius_km,
        debug=debug,
    )

    all_listings = []
    for pname in provider_names:
        prov = PROVIDERS[pname]
        if pname == "facebook":
            pairs = resolve_locations(location_tokens, radius_km)
            loc_summary = (
                ", ".join(f"{s or 'auto'}+{r}km" if r else (s or "auto") for s, r in pairs)
                if location_tokens else "auto-detect"
            )
            loc_note = f"| locations: {loc_summary} | {len(pairs)} city search(es)"
        else:
            loc_note = "[dim](location ignored — nationwide)[/dim]"
        console.print(
            f"[cyan]Searching[/cyan] [bold]{pname}[/bold] for [bold]{query!r}[/bold] "
            + loc_note
            + (f" | price: {min_price}–{max_price}" if min_price or max_price else "")
        )
        try:
            results = prov.search(req)
            console.print(f"[green]✓[/green] {len(results)} result(s) from {pname}")
            all_listings.extend(results)
        except Exception as exc:
            console.print(f"[red]Error from {pname}:[/red] {exc}")

    if output == OutputFormat.json:
        print_json(all_listings)
    else:
        print_table(all_listings)


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
        t = Table(
            title=f"Cities for {country.upper()} (Facebook slugs)",
            box=box.ROUNDED,
        )
        t.add_column("Slug", style="bold cyan")
        t.add_column("Name")
        t.add_column("Default radius km", style="green")
        t.add_column("FB ID (if known)", style="dim")
        for c in cities:
            t.add_row(c["slug"], c["name"], str(c["radius_km"]), c.get("fb_id", ""))
        out.print(t)
        out.print(
            f"\n[dim]Usage: --location {country.upper()}   (expands to all {len(cities)} cities)[/dim]"
        )
    else:
        countries = list_countries()
        t = Table(title="Known European countries", box=box.ROUNDED)
        t.add_column("Code", style="bold cyan", width=6)
        t.add_column("Country")
        t.add_column("Cities", style="green", justify="right")
        for row in countries:
            t.add_row(row["code"], row["name"], str(row["city_count"]))
        out.print(t)
        out.print(
            "\n[dim]Run 'market-scout locations DE' to see cities for a country.[/dim]"
        )


@app.command("find-location")
def find_location(
    slug: str = typer.Argument(..., help="City slug or name to look up (e.g. 'gyor', 'pecs', 'miskolc')"),
    cookies: Optional[Path] = typer.Option(
        None, "--cookies", "-c",
        help="Facebook cookies JSON. If provided, the browser starts logged in.",
    ),
    headless: bool = typer.Option(
        False, "--no-headless/--headless",
        help="Default: visible browser (--no-headless). Pass --headless only if cookies are valid and no login is needed.",
    ),
):
    """Look up the numeric Facebook city ID for a slug that FB doesn't recognise.

    Facebook silently drops unrecognised city slugs (redirects to /category/search/).
    Numeric IDs always work. This command opens a browser, navigates to
    facebook.com/marketplace/<slug>, and extracts the city ID from the page source.

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
    city_id = asyncio.run(discover_city_id(slug, cookies or Path("cookies.json"), headless=headless))
    if city_id:
        out.print(f"\n[green]Found ID:[/green] [bold]{city_id}[/bold]")
        out.print(f"\n[dim]Use it like:[/dim]")
        out.print(f"  market-scout search --query \"<your query>\" --location {city_id} --radius 50")
    else:
        console.print(
            f"[yellow]Could not find a numeric ID for '{slug}'.[/yellow]\n"
            f"Try running with --no-headless and check the browser URL bar after it loads.\n"
            f"Or look up the city manually on facebook.com/marketplace and note the city ID in the URL."
        )
        raise typer.Exit(code=1)



