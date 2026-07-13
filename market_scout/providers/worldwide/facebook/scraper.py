"""
Facebook Marketplace Playwright scraper.
Adapted from https://github.com/hyuwowo/fb-marketplace-scraper (MIT)
Changes: imports use package paths; removed standalone __main__ block.
"""
import asyncio
import json
import random
import re
from pathlib import Path

from playwright.async_api import async_playwright, Page
from playwright_stealth import Stealth
from browserforge.fingerprints import FingerprintGenerator

from .config import FbScraperConfig
from .models import FbListing

CARD_LINK = 'a[href*="/marketplace/item/"]'
PRICE_RX = re.compile(r'(?:IDR|Rp|HUF|PLN|CZK|RON|HRK|BGN|SEK|NOK|DKK|CHF|[$€£¥₩])\s*[0-9]')
_fp_gen = FingerprintGenerator(slim=True)

_cached_city_id: str | None = None


async def detect_city_id(page: Page) -> str:
    global _cached_city_id
    if _cached_city_id:
        return _cached_city_id
    try:
        await page.goto("https://www.facebook.com/marketplace", wait_until="load", timeout=45000)
        await asyncio.sleep(2)
        html = await page.content()
        ids = re.findall(r'"buy_location".*?"id":"(\d+)"', html)
        if ids:
            _cached_city_id = ids[0]
            return ids[0]
    except Exception:
        pass
    return ""


def _price(t: str) -> bool:
    return bool(PRICE_RX.search(t))


def _has_number(t: str) -> bool:
    return bool(re.search(r'[0-9]', t))


def parse_card(txt: list, aria: str = "") -> dict:
    r = {"title": "", "price": "", "location": "", "posted": ""}
    if not txt:
        return r
    r["location"] = txt[-1].strip()
    for t in txt:
        if _price(t.strip()):
            r["price"] = t.strip()
    for t in txt:
        t = t.strip()
        if t and t != r["price"] and t != r["location"]:
            if not r["title"] and not _price(t) and len(t) > 2:
                r["title"] = t
    if aria and (
        not r["title"]
        or len(r["title"]) < 5
        or (r["title"].istitle() and len(r["title"]) < 15 and not _has_number(r["title"]))
    ):
        parts = [
            p.strip()
            for p in aria.replace("+", " ").split(",")
            if p.strip() and not _price(p.strip())
        ]
        parts = [
            p for p in parts
            if not re.match(r'^[0-9.\s]+$', p.strip()) and len(p.strip()) > 2
        ]
        if parts and parts[0] != r["location"]:
            r["title"] = parts[0]
    return r


def load_cookies(fp: Path) -> list:
    if not fp.exists():
        return []
    raw = json.loads(fp.read_text(encoding="utf-8"))
    out = []
    for c in raw:
        pw = {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"],
            "path": c.get("path", "/"),
            "secure": c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
        }
        ss = c.get("sameSite")
        if ss:
            ss = "".join(p.capitalize() for p in ss.split("_"))
            pw["sameSite"] = ss if ss in ("Lax", "Strict", "None") else "None"
        if c.get("expirationDate"):
            pw["expires"] = int(float(c["expirationDate"]))
        out.append(pw)
    return out


def _bezier(t, p0, p1, p2, p3):
    u = 1 - t
    return u**3 * p0 + 3 * u**2 * t * p1 + 3 * u * t**2 * p2 + t**3 * p3


async def human_mouse(page: Page, tx, ty):
    sx, sy = random.randint(100, 600), random.randint(60, 400)
    cp1x = sx + random.randint(-200, 200)
    cp1y = sy + random.randint(-100, 100)
    cp2x = tx + random.randint(-150, 150)
    cp2y = ty + random.randint(-100, 100)
    steps = random.randint(15, 30)
    for i in range(steps + 1):
        t_val = i / steps
        await page.mouse.move(
            _bezier(t_val, sx, cp1x, cp2x, tx),
            _bezier(t_val, sy, cp1y, cp2y, ty),
        )
        await asyncio.sleep(random.uniform(0.003, 0.012))


async def _sleep(a=1.0, b=4.0):
    await asyncio.sleep(random.uniform(a, b))


async def close_chat(page: Page) -> bool:
    try:
        for b in await page.query_selector_all(
            '[aria-label="Tutup chat"], [aria-label="Close chat"]'
        ):
            if await b.is_visible():
                await b.click()
                await asyncio.sleep(0.3)
                return True
    except Exception:
        pass
    return False


async def human_scroll(page: Page):
    await page.evaluate(
        f"window.scrollBy({{top: {random.randint(400, 800)}, behavior: 'smooth'}})"
    )
    await asyncio.sleep(random.uniform(0.8, 1.5))
    await close_chat(page)


async def accept_cookies(page: Page) -> bool:
    """Accept FB cookie consent dialog. Returns True if a button was clicked."""
    # Data-attribute selectors are most reliable (language-agnostic)
    css_selectors = [
        '[data-cookiebanner="accept_button"]',
        'button[title="Allow all cookies"]',
        '[data-testid="cookie-policy-manage-dialog-accept-button"]',
        '[data-testid="cookie-policy-dialog-accept-button"]',
    ]
    for sel in css_selectors:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=1500):
                await el.click()
                await asyncio.sleep(1.5)
                return True
        except Exception:
            pass
    # Accessible-name fallback (works across languages if aria-label matches)
    for name_pattern in [
        "Allow all cookies",
        "Accept all",
        "Allow essential and optional cookies",
        "Alle Cookies erlauben",
        "Accepter tous",
        "Aceptar todas",
        "Alle cookies toestaan",
    ]:
        try:
            btn = page.get_by_role("button", name=re.compile(name_pattern, re.I)).first
            if await btn.is_visible(timeout=800):
                await btn.click()
                await asyncio.sleep(1.5)
                return True
        except Exception:
            pass
    return False


async def _login_wall_visible(page: Page) -> bool:
    """Return True if a Facebook login form is currently visible on the page."""
    for sel in [
        'input[name="email"]',
        'input[name="pass"]',
        'button[name="login"]',
        '[data-testid="royal_login_button"]',
    ]:
        try:
            if await page.locator(sel).first.is_visible(timeout=600):
                return True
        except Exception:
            pass
    return False


async def handle_login_wall(page: Page, cfg: FbScraperConfig) -> bool:
    """
    Check for a login wall and handle it.
    - headless=True:  print a clear error and return False (abort scrape)
    - headless=False: pause, print instructions, and wait up to 5 min for the
                      user to log in interactively. Returns True when login
                      succeeds (marketplace cards appear), False on timeout.
    """
    if not await _login_wall_visible(page):
        return True

    if cfg.headless:
        print(
            "\n" + "!" * 60 + "\n"
            "  Facebook login wall detected — cannot proceed headlessly.\n"
            "\n"
            "  Option 1 (quick):  Add --no-headless, log in once in the\n"
            "                     browser, and your session is saved as\n"
            "                     cookies.json automatically.\n"
            "\n"
            "  Option 2 (robust): Export cookies from a logged-in Chrome\n"
            "                     session (EditThisCookie extension) and\n"
            "                     pass them with --cookies cookies.json.\n"
            "                     See README for details.\n"
            + "!" * 60 + "\n",
            flush=True,
        )
        return False

    # Non-headless: hand control to the user
    print(
        "\n" + "=" * 60 + "\n"
        "  Facebook login required.\n"
        "  Please log in in the browser window that just opened.\n"
        "  Scraping will resume automatically once you are in.\n"
        "  (Waiting up to 5 minutes)\n"
        + "=" * 60 + "\n",
        flush=True,
    )

    # Best case: user logs in via the overlay and stays on the marketplace page
    try:
        await page.wait_for_selector(CARD_LINK, timeout=300_000)
        print("  Login detected — resuming scrape...\n", flush=True)
        return True
    except Exception:
        pass

    # Fallback: user logged in but FB redirected away from the search page
    if not await _login_wall_visible(page):
        print("  Redirected after login — re-navigating to search...\n", flush=True)
        try:
            await page.goto(cfg.marketplace_url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(3)
            await accept_cookies(page)
            return True
        except Exception:
            pass

    print("  Timed out waiting for login.\n", flush=True)
    return False


async def dismiss(page: Page):
    """Dismiss generic modal popups (login nags, notification prompts, chat bubbles)."""
    for _ in range(2):
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        except Exception:
            pass
    try:
        await page.mouse.click(150, 150)
        await asyncio.sleep(0.3)
    except Exception:
        pass
    for sel in ('[aria-label="Close"]', 'text="Not Now"', '[aria-label="Tutup"]'):
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                box = await el.bounding_box()
                if box and box["y"] < 500:
                    await el.click()
                    await asyncio.sleep(0.3)
        except Exception:
            pass
    await close_chat(page)


async def dismiss_promotions(page: Page) -> bool:
    """
    Dismiss Facebook's 'Discover more when you shop' / 'Shop partner listings'
    promotional modal that appears on Marketplace before search results load.
    Returns True if a dialog was dismissed.
    """
    dismissed = False

    # Strategy 1: find a [role=dialog] containing known promo text, click its close btn
    promo_phrases = [
        "Discover more when you shop",
        "Shop partner listings",
        "partner listings on Marketplace",
    ]
    for phrase in promo_phrases:
        try:
            dialog = page.locator(f'[role="dialog"]:has-text("{phrase}")').first
            if await dialog.is_visible(timeout=1500):
                # Try close button inside the dialog first
                for close_sel in [
                    '[aria-label="Close"]',
                    '[aria-label="Schließen"]',
                    '[aria-label="Fermer"]',
                    '[aria-label="Cerrar"]',
                    'button[type="button"]',
                ]:
                    try:
                        btn = dialog.locator(close_sel).first
                        if await btn.is_visible(timeout=600):
                            await btn.click()
                            await asyncio.sleep(1.0)
                            dismissed = True
                            break
                    except Exception:
                        pass
                if not dismissed:
                    # ESC as fallback
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.5)
                    dismissed = True
                break
        except Exception:
            pass

    # Strategy 2: any visible dialog with a close/not-now button (catches translated variants)
    if not dismissed:
        for btn_sel in [
            'div[role="dialog"] [aria-label="Close"]',
            'div[role="dialog"] [aria-label="Schließen"]',
            'div[role="dialog"] button:has-text("Not now")',
            'div[role="dialog"] button:has-text("Nem most")',
            'div[role="dialog"] button:has-text("Jetzt nicht")',
            'div[role="dialog"] button:has-text("Pas maintenant")',
        ]:
            try:
                btn = page.locator(btn_sel).first
                if await btn.is_visible(timeout=600):
                    await btn.click()
                    await asyncio.sleep(1.0)
                    dismissed = True
                    break
            except Exception:
                pass

    return dismissed


async def init_stealth(page: Page, fp):
    try:
        s = Stealth(webgl_vendor_override=fp.navigator.vendor)
        await s.apply_stealth_async(page)
    except Exception:
        pass
    await page.add_init_script("""
        Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
        Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
        window.chrome={runtime:{},loadTimes:function(){},csi:function(){}};
        const _q=navigator.permissions.query;
        navigator.permissions.query=p=>p.name==='notifications'?
            Promise.resolve({state:Notification.permission}):_q(p);
    """)


async def _make_context(p, cfg: FbScraperConfig):
    while True:
        fp = _fp_gen.generate()
        ua = fp.navigator.userAgent
        if "Mobile" not in ua and "iPhone" not in ua and "Android" not in ua:
            fp.screen.width = max(fp.screen.width, 1280)
            fp.screen.height = max(fp.screen.height, 720)
            break
    br = await p.chromium.launch(
        headless=cfg.headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            f"--window-size={fp.screen.width},{fp.screen.height}",
        ],
    )
    ctx = await br.new_context(
        user_agent=ua,
        viewport={"width": fp.screen.width, "height": fp.screen.height},
        locale="en-US",
        timezone_id="Europe/Berlin",
        device_scale_factor=fp.screen.devicePixelRatio,
    )
    cks = load_cookies(cfg.cookies_file)
    if cks:
        await ctx.add_cookies(cks)
    return ctx, fp


async def scroll_load(page: Page, cfg: FbScraperConfig):
    prev = 0
    stall = 0
    for _ in range(cfg.max_scrolls):
        await human_scroll(page)
        cur = len(await page.query_selector_all(CARD_LINK))
        if cur == prev:
            stall += 1
        else:
            stall = 0
        prev = cur
        if stall >= 3 or cur >= cfg.max_listings * 2:
            break


async def extract_cards(page: Page) -> list[dict]:
    return await page.evaluate("""
        () => {
            const r=[], s=new Set();
            document.querySelectorAll('a[href*="/marketplace/item/"]').forEach(a => {
                const h=a.getAttribute('href');
                if(!h||s.has(h)) return;
                s.add(h);
                const aria=(a.getAttribute('aria-label')||'').trim();
                const img=a.querySelector('img');
                r.push({
                    aria,
                    txt: a.innerText.split('\\n').map(t=>t.trim()).filter(Boolean),
                    url: h.startsWith('http') ? h : 'https://www.facebook.com'+h,
                    image_url: img ? img.src : ''
                });
            });
            return r;
        }
    """)


async def scrape_detail(page: Page, url: str) -> dict:
    d: dict = {}
    try:
        await page.goto(url, wait_until="load", timeout=45000)
        await _sleep(2, 3)
        await dismiss(page)
        for _ in range(5):
            await page.evaluate(f"window.scrollBy(0, {random.randint(300, 700)})")
            await asyncio.sleep(random.uniform(0.5, 1.0))
        try:
            await page.mouse.click(500, 400)
            await asyncio.sleep(0.5)
        except Exception:
            pass
        await asyncio.sleep(2)

        for sel, attr, key in [
            ('meta[property="og:title"]', "content", "title"),
            ('meta[property="og:price:amount"]', "content", "price"),
            ('meta[property="og:description"]', "content", "description"),
        ]:
            el = await page.query_selector(sel)
            if el:
                v = (await el.get_attribute(attr) or "").strip()
                if v:
                    d[key] = v

        if not d.get("title"):
            for sel in ("h1 span", "h1"):
                el = await page.query_selector(sel)
                if el:
                    v = (await el.text_content() or "").strip()
                    if v and not _price(v) and len(v) > 2:
                        d["title"] = v
                        break

        full = await page.evaluate("() => document.body.innerText")
        lines = [ln.strip() for ln in full.splitlines() if ln.strip()]
        for i in range(len(lines) - 1):
            key_line = lines[i]
            val = lines[i + 1]
            if len(key_line) < 10 and 3 < len(val) < 25:
                if "-" in val and all(len(p.strip()) < 15 for p in val.split("-")):
                    d["condition"] = val
                    break

        profile_links = await page.query_selector_all('a[href*="/marketplace/profile/"]')
        found_first = False
        for link in profile_links:
            name = (await link.text_content() or "").strip()
            if name and 3 < len(name) < 60 and "/" not in name:
                if not found_first:
                    found_first = True
                    continue
                d["seller"] = name
                d["seller_url"] = await link.get_attribute("href") or ""
                break
    except Exception:
        pass
    return d


async def discover_city_id(city_slug: str, cookies_file: Path, headless: bool = False) -> str | None:
    """
    Navigate to /marketplace/{city_slug}, extract the numeric buy_location ID
    from the page source, and return it. Returns None if not found.
    Uses a real browser session so cookies/login state are respected.
    """
    cfg = FbScraperConfig(location=city_slug, search_query="", cookies_file=cookies_file, headless=headless)
    async with async_playwright() as p:
        ctx, fp = await _make_context(p, cfg)
        page = await ctx.new_page()
        await init_stealth(page, fp)
        try:
            await page.goto(
                f"https://www.facebook.com/marketplace/{city_slug}",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            await accept_cookies(page)
            await asyncio.sleep(3)
            if await _login_wall_visible(page):
                print(
                    "  Login required — re-run with --no-headless to log in first,\n"
                    "  or pass --cookies <file> with a valid session.",
                    flush=True,
                )
                return None
            html = await page.content()
            ids = re.findall(r'"buy_location"[^}]*"id"\s*:\s*"(\d+)"', html)
            if ids:
                return ids[0]
            # Also try the JSON data embedded in script tags
            ids = re.findall(r'"locationId"\s*:\s*"(\d{8,})"', html)
            if ids:
                return ids[0]
        except Exception as exc:
            print(f"  Error during discovery: {exc}", flush=True)
        finally:
            await ctx.close()
    return None


async def run_scrape(cfg: FbScraperConfig) -> list[FbListing]:
    """Run a single-pass scrape and return a list of FbListing objects."""
    listings: list[FbListing] = []

    async with async_playwright() as p:
        ctx, fp = await _make_context(p, cfg)
        page = await ctx.new_page()
        await init_stealth(page, fp)

        if not cfg.location:
            city_id = await detect_city_id(page)
            if city_id:
                cfg.location = city_id

        for attempt in range(cfg.max_retries):
            try:
                await page.goto(cfg.marketplace_url, wait_until="domcontentloaded", timeout=45000)
                await _sleep(3, 5)
                break
            except Exception:
                await asyncio.sleep(2 ** attempt * 3)
        else:
            await ctx.close()
            return listings

        # Accept cookie consent before checking for login wall
        await accept_cookies(page)
        await asyncio.sleep(1)

        # Detect and handle login wall — abort or wait for user
        if not await handle_login_wall(page, cfg):
            await ctx.close()
            return listings

        # Detect slug redirect: FB silently redirects unknown slugs to /category/search/
        # If that happened, the location filter is gone — warn and abort this city.
        final_url = page.url
        if cfg.location and "/category/search" in final_url:
            print(
                f"\n[market-scout] WARNING: location '{cfg.location}' is not a valid "
                f"Facebook slug.\n"
                f"  FB redirected to: {final_url}\n"
                f"  Results would be unfiltered by location — skipping this city.\n"
                f"\n"
                f"  Fix: find the numeric city ID with:\n"
                f"    market-scout find-location \"{cfg.location}\" --no-headless\n"
                f"  Then use the ID directly: --location <numeric_id>\n",
                flush=True,
            )
            await ctx.close()
            return listings

        await dismiss(page)
        await dismiss_promotions(page)
        await human_mouse(page, random.randint(200, 600), random.randint(100, 400))
        try:
            await page.wait_for_selector(CARD_LINK, timeout=20000)
        except Exception:
            pass

        # One more promotion check — FB sometimes shows the modal after a short delay
        await dismiss_promotions(page)

        await scroll_load(page, cfg)

        raw = await extract_cards(page)
        for item in raw[: cfg.max_listings]:
            info = parse_card(item.get("txt", []), item.get("aria", ""))
            price = info["price"]
            if price and len(price) > 50:
                title_part = re.split(r'\s*(?:Rp|IDR|[$€£¥])\s*[0-9]', price)[0].strip()
                if title_part and not info["title"]:
                    info["title"] = title_part
                m = re.search(r'(?:Rp|IDR|[$€£¥])\s*[0-9][0-9.,]*\s*$', price)
                if m:
                    price = m.group().strip()
            if price and len(price) < 40:
                parts = re.split(r'(?<=[0-9])(?=[R][p])|(?<=[0-9])(?=[$€£¥])', price)
                price = parts[0].strip()

            url = item["url"].split("?ref=")[0]
            title = info["title"]
            if title:
                title = title.replace("+", " ").replace("  ", " ").strip()

            lst = FbListing(
                title=title,
                price=price,
                location=info["location"],
                posted=info.get("posted", ""),
                url=url,
                image_url=item["image_url"],
            )
            if lst.title or lst.price:
                listings.append(lst)

        # Scrape detail pages for listings with missing/short titles
        sem = asyncio.Semaphore(3)

        async def _detail(lst: FbListing):
            async with sem:
                p2 = await ctx.new_page()
                try:
                    d = await scrape_detail(p2, lst.url)
                    if d.get("title") and len(d["title"]) > len(lst.title or ""):
                        lst.title = d["title"]
                    if d.get("price") and len(d["price"]) > len(lst.price or ""):
                        lst.price = d["price"]
                    if d.get("location"):
                        lst.location = d["location"]
                    if d.get("seller"):
                        lst.seller = d["seller"]
                    if d.get("condition"):
                        lst.condition = d["condition"]
                    if d.get("description"):
                        lst.description = d["description"]
                except Exception:
                    pass
                finally:
                    await p2.close()

        need_details = [
            lst for lst in listings
            if not lst.title or (len(lst.title) <= 18 and not _has_number(lst.title))
        ]
        if need_details and cfg.scrape_details:
            limit = min(len(need_details), cfg.max_detail_pages)
            await asyncio.gather(*[_detail(lst) for lst in need_details[:limit]])

        if cfg.scrape_details and listings:
            limit = min(len(listings), cfg.max_detail_pages)
            await asyncio.gather(*[_detail(lst) for lst in listings[:limit]])

        # Persist updated cookies
        try:
            cks = await ctx.cookies()
            cfg.cookies_file.write_text(
                json.dumps(
                    [
                        {
                            "name": c["name"],
                            "value": c["value"],
                            "domain": c["domain"],
                            "path": c["path"],
                            "secure": c["secure"],
                            "httpOnly": c["httpOnly"],
                            "sameSite": c.get("sameSite", "None"),
                            "expires": c.get("expires"),
                        }
                        for c in cks
                    ],
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

        await ctx.close()

    return listings
