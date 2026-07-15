r"""
Batch-discover (or refresh) Facebook city IDs for all cities in locations.json.
Uses the Marketplace location picker UI — types the city name, selects the first
suggestion, clicks Apply, and reads the resulting URL's location ID.

Usage:
    # Fill in cities that have no fb_id yet (default)
    cd c:\SAPDevelop\market-scout
    .venv\Scripts\python scripts\discover_all_fb_ids.py --cookies cookies.json

    # Refresh / re-verify ALL cities (including ones already having an ID)
    .venv\Scripts\python scripts\discover_all_fb_ids.py --cookies cookies.json --force

    # Visible browser (useful if cookies are stale or need refreshing)
    .venv\Scripts\python scripts\discover_all_fb_ids.py --cookies cookies.json --no-headless

    # Single country only
    .venv\Scripts\python scripts\discover_all_fb_ids.py --cookies cookies.json --country HU

    # Dry run (print plan, no changes)
    .venv\Scripts\python scripts\discover_all_fb_ids.py --dry-run

Options:
  --cookies PATH      Path to Facebook cookies JSON  [default: cookies.json]
  --no-headless       Show browser window
  --force             Re-discover IDs even for cities that already have one
  --batch-size N      Cities per batch  [default: 5]
  --delay N           Seconds between cities  [default: 6]
  --country CC        Only process this country code (e.g. HU, DE)
  --dry-run           Print what would be done, don't touch the JSON
"""
import argparse
import asyncio
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_scout.providers.worldwide.facebook.scraper import _make_context, init_stealth, accept_cookies
from market_scout.providers.worldwide.facebook.config import FbScraperConfig
from playwright.async_api import async_playwright

LOCATIONS_PATH = (
    Path(__file__).parent.parent
    / "market_scout" / "providers" / "worldwide" / "facebook" / "locations.json"
)
_SEARCH_URL = "https://www.facebook.com/marketplace/budapest/search/?query=amiga"


def load_locations() -> dict:
    return json.loads(LOCATIONS_PATH.read_text(encoding="utf-8"))


def save_locations(data: dict) -> None:
    LOCATIONS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def cities_needing_ids(data: dict, country_filter: str = "", force: bool = False) -> list[tuple[str, int, dict]]:
    needed = []
    for cc, country in data.items():
        if country_filter and cc.upper() != country_filter.upper():
            continue
        for i, city in enumerate(country["cities"]):
            if force or not city.get("fb_id"):
                needed.append((cc, i, city))
    return needed


async def get_city_id_via_picker(
    page,
    city_name: str,
    country_name: str,
) -> tuple[str | None, str]:
    """
    Use the Marketplace location picker to discover the city's fb_id.
    Returns (fb_id_or_None, first_suggestion_text).
    """
    query = f"{city_name}, {country_name}" if country_name else city_name

    # Navigate to a search page so the location filter is visible
    await page.goto(_SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
    await accept_cookies(page)
    await asyncio.sleep(3)

    # Open the location dialog
    await page.locator('[aria-label*="Location"]').first.click()
    await asyncio.sleep(2)

    # Clear the input and type the city query
    inp = page.locator('div[role="dialog"] input').first
    await inp.click(click_count=3)
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    await asyncio.sleep(0.2)
    await inp.type(query, delay=80)
    await asyncio.sleep(3)

    # Read the first suggestion
    opts = await page.query_selector_all('[role="option"]')
    if not opts:
        return None, ""
    first_text = (await opts[0].text_content() or "").strip()
    await opts[0].click()
    await asyncio.sleep(2)

    # Click the Apply button (find visible one by text)
    all_btns = await page.query_selector_all("button, [role='button']")
    for btn in all_btns:
        t = (await btn.text_content() or "").strip()
        vis = await btn.is_visible()
        if vis and t in ("Apply", "Alkalmazás", "Alkalmaz", "Применить", "Застосувати"):
            await btn.click()
            await asyncio.sleep(3)
            break

    # Extract location from URL
    final_url = page.url
    m = re.search(r"/marketplace/([^/]+)/search/", final_url)
    location = m.group(1) if m else None

    # If the URL still shows the starting city (budapest), the picker didn't change
    if location == "budapest":
        location = None

    return location, first_text


async def run_batch(
    batch: list[tuple[str, int, dict]],
    data: dict,
    cookies_file: Path,
    headless: bool,
    delay: float,
    country_names: dict[str, str],
    dry_run: bool,
) -> dict[str, str]:
    results: dict[str, str] = {}

    cfg = FbScraperConfig(
        location="", search_query="", cookies_file=cookies_file, headless=headless
    )
    async with async_playwright() as p:
        ctx, fp = await _make_context(p, cfg)
        page = await ctx.new_page()
        await init_stealth(page, fp)

        for cc, city_idx, city in batch:
            slug = city["slug"]
            name = city["name"]
            country_name = country_names.get(cc, "")
            print(f"  [{cc}] {name} ({slug}) ...", end=" ", flush=True)

            if dry_run:
                print("(dry-run, skipped)")
                results[slug] = ""
                continue

            try:
                location, suggestion = await get_city_id_via_picker(page, name, country_name)
                if location and re.match(r"^\d{10,}$", location):
                    # Valid 10+ digit numeric ID
                    print(f"✓ {location}  (from: {suggestion!r})")
                    data[cc]["cities"][city_idx]["fb_id"] = location
                    save_locations(data)
                    results[slug] = location
                elif location and not location.isdigit():
                    # Got a slug back — also useful
                    print(f"~ slug={location!r}  (from: {suggestion!r})")
                    results[slug] = location
                else:
                    print(f"✗ no valid ID (suggestion: {suggestion!r})")
                    results[slug] = ""
            except Exception as exc:
                print(f"✗ error: {exc}")
                results[slug] = ""

            if (cc, city_idx, city) != batch[-1]:
                await asyncio.sleep(delay + random.uniform(0, 2))

        await ctx.close()

    return results


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover Facebook city IDs via the Marketplace location picker"
    )
    parser.add_argument("--cookies", default="cookies.json")
    parser.add_argument("--no-headless", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="Re-discover IDs even for cities that already have one")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--delay", type=float, default=6.0)
    parser.add_argument("--country", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cookies_file = Path(args.cookies)
    headless = not args.no_headless

    data = load_locations()
    country_names = {cc: c["name"] for cc, c in data.items()}
    needed = cities_needing_ids(data, args.country, force=args.force)

    print(f"\nLocations file: {LOCATIONS_PATH}")
    print(f"Cities needing fb_id: {len(needed)}")
    if args.country:
        print(f"Filtering to: {args.country.upper()}")
    if args.force:
        print("--force: re-discovering IDs for all cities (including existing)")
    if args.dry_run:
        print("DRY RUN — no changes\n")
    print()

    if not needed:
        print("All cities already have fb_id.")
        return

    batch_size = args.batch_size
    total_batches = (len(needed) + batch_size - 1) // batch_size
    not_found: list[str] = []
    found = 0

    for batch_num in range(total_batches):
        batch = needed[batch_num * batch_size : (batch_num + 1) * batch_size]
        print(f"Batch {batch_num + 1}/{total_batches} ({len(batch)} cities):")

        results = await run_batch(
            batch, data, cookies_file, headless, args.delay, country_names, args.dry_run
        )

        found += sum(1 for v in results.values() if v)
        not_found.extend(s for s, v in results.items() if not v and not args.dry_run)

        if batch_num < total_batches - 1:
            pause = random.uniform(12, 20)
            print(f"  [Batch pause: {pause:.0f}s]\n")
            await asyncio.sleep(pause)

    print(f"\n{'='*60}")
    print(f"Done. Found: {found}  /  Needed: {len(needed)}")
    if not_found:
        print(f"\nCould not resolve ({len(not_found)} cities): {', '.join(not_found)}")
        print("These cities may not be recognised by Facebook's location picker.")


if __name__ == "__main__":
    asyncio.run(main())
