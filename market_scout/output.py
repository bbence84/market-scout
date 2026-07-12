import json
from typing import Sequence

from rich.console import Console
from rich.table import Table
from rich import box

from market_scout.models import Listing

console = Console()

# Unicode flag emoji from ISO-3166-1 alpha-2 country code.
# Each letter maps to a Regional Indicator Symbol (U+1F1E6 + offset).
def _flag(country: str) -> str:
    if not country or country == "*":
        return "🌍"
    try:
        return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.upper() if c.isalpha())
    except Exception:
        return ""


def _provider_cell(lst: Listing) -> str:
    flag = _flag(lst.provider_country)
    return f"{lst.provider} {flag}" if flag else lst.provider


def _link_label(url: str) -> str:
    """Short display label for a URL — last meaningful path segment."""
    path = url.rstrip("/").rsplit("/", 1)[-1]
    if path in ("friss.html", "index.html", ""):
        path = url.rstrip("/").rsplit("/", 2)[-2]
    if path.isdigit():
        return f"#{path}"
    return (path[:18] + "…") if len(path) > 19 else path


def print_table(listings: Sequence[Listing], show_images: bool = False) -> None:
    if not listings:
        console.print("[yellow]No listings found.[/yellow]")
        return

    # Sort by provider name so all results from each source are grouped together
    sorted_listings = sorted(listings, key=lambda lst: (lst.provider, lst.scraped_at))

    table = Table(
        title=f"[bold cyan]{len(sorted_listings)} listing(s) found[/bold cyan]",
        box=box.ROUNDED,
        show_lines=True,
        expand=False,
    )
    table.add_column("Title", style="bold", min_width=24, max_width=44, no_wrap=True)
    table.add_column("Price", style="green", min_width=10, max_width=14, no_wrap=True)
    table.add_column("Location", min_width=12, max_width=18, no_wrap=True)
    table.add_column("Provider", style="dim", min_width=12, max_width=16, no_wrap=True)
    table.add_column("Seller", min_width=10, max_width=16, no_wrap=True)
    table.add_column("Cond.", min_width=6, max_width=12, no_wrap=True)
    table.add_column("Link", min_width=16, max_width=22, no_wrap=True)

    for i, lst in enumerate(sorted_listings, 1):
        price_str = f"{lst.currency}{lst.price}" if lst.currency else lst.price
        label = _link_label(lst.url) if lst.url else "—"
        link_cell = f"[link={lst.url}]{label}[/link]" if lst.url else "[dim]—[/dim]"
        # Embed the row number into the title so it's always visible
        title_cell = f"[dim]{i}.[/dim] {lst.title}" if lst.title else f"[dim]{i}. —[/dim]"
        table.add_row(
            title_cell,
            price_str or "[dim]—[/dim]",
            lst.location or "[dim]—[/dim]",
            _provider_cell(lst),
            lst.seller or "[dim]—[/dim]",
            lst.condition or "[dim]—[/dim]",
            link_cell,
        )

    console.print(table)


def print_json(listings: Sequence[Listing]) -> None:
    print(json.dumps([lst.to_dict() for lst in listings], indent=2, ensure_ascii=False))
