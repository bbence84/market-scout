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

    table = Table(
        title=f"[bold cyan]{len(listings)} listing(s) found[/bold cyan]",
        box=box.ROUNDED,
        show_lines=True,
        expand=True,
    )
    table.add_column("#", style="dim", width=3, no_wrap=True)
    table.add_column("Title", style="bold", min_width=18, max_width=40, no_wrap=True)
    table.add_column("Price", style="green", width=13, no_wrap=True)
    table.add_column("Location", width=16, no_wrap=True)
    table.add_column("Provider", style="dim", width=14, no_wrap=True)
    table.add_column("Seller", width=14, no_wrap=True)
    table.add_column("Cond.", width=10, no_wrap=True)
    table.add_column("Link", width=20, no_wrap=True)

    for i, lst in enumerate(listings, 1):
        price_str = f"{lst.currency}{lst.price}" if lst.currency else lst.price
        label = _link_label(lst.url) if lst.url else "—"
        link_cell = f"[link={lst.url}]{label}[/link]" if lst.url else "[dim]—[/dim]"
        table.add_row(
            str(i),
            lst.title or "[dim]—[/dim]",
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
