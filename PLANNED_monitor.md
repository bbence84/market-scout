# Plan: `monitor` command — continuous search with seen/dismissed tracking

## Context

Users want to monitor marketplaces for rare items over time (e.g. check every 30 minutes for a new Amiga 500 listing). The current `search` command is one-shot. This adds a `monitor` command that loops on a schedule, suppresses listings already seen, and lets users interactively dismiss listings they're not interested in. State is persisted to SQLite so it survives across sessions.

---

## New file: `market_scout/monitor_db.py`

SQLite wrapper using stdlib `sqlite3`. DB lives at `user_config/seen.db` (same dir as `config.toml`, already git-ignored).

```python
_DB_PATH = Path(__file__).parent.parent / "user_config" / "seen.db"

# Schema
CREATE TABLE seen_listings (
    url TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    dismissed INTEGER NOT NULL DEFAULT 0
)
CREATE INDEX idx_seen_query ON seen_listings(query)
```

Functions:
- `init_db(path=None) -> sqlite3.Connection` — create table+index if not exists, return open connection
- `filter_new(conn, listings, query) -> list[Listing]` — return listings whose URL is NOT in DB (dismissed or seen by any query)
- `mark_seen(conn, listings, query)` — `INSERT OR IGNORE` all listings with `dismissed=0`
- `mark_dismissed(conn, urls)` — `UPDATE SET dismissed=1` for given URLs
- `seen_count(conn, query) -> int`
- `dismissed_count(conn, query) -> int`

Key decisions:
- `filter_new` excludes ANY URL already in DB regardless of query — so a dismissed URL from one query never reappears under another query
- `INSERT OR IGNORE` means re-running after a crash won't double-insert
- `first_seen` = `datetime.now(timezone.utc).isoformat()`

---

## Refactor `cli.py`: extract `_run_search_once()`

Extract lines **399–615** from the `search` command into a private helper. This is the provider loop + all post-processing (dates, translation, AI scoring, currency). Both `search` and `monitor` will call it.

```python
@dataclass
class _SearchResult:
    listings: list[Listing]
    original_prices: dict[str, tuple[str, str]]
    provider_times: dict[str, float]
    total_elapsed: float

def _run_search_once(
    *,
    queries: list[str],
    translated_queries: dict[str, str],
    provider_names: list[str],
    location_tokens: list[str],
    min_price, max_price, effective_max,
    effective_cookies, effective_headless,
    scrape_details, effective_radius, debug,
    target_currency,
    llm_key, llm_model, llm_base,
    effective_translate_results,
    details_ai, user_lang, query,
) -> _SearchResult:
```

The `search` command becomes:
```python
result = _run_search_once(...)
print_table(result.listings, original_prices=result.original_prices)
# timing summary
# save logic
```

What stays in `search` (NOT extracted): config loading, provider resolution, dry-run, LLM key validation, interactive query suggestion/translation, currency validation.

---

## New command: `monitor` in `cli.py`

Same options as `search` plus `--interval` (default `"15"`, accepts `"5m"`, `"30m"`, `"1h"`).

### Interval parsing helper
```python
def _parse_interval(raw: str) -> int:
    """Returns seconds. "15" or "15m" -> 900, "1h" -> 3600."""
    raw = raw.strip().lower()
    if raw.endswith("h"):  return int(float(raw[:-1]) * 3600)
    if raw.endswith("m"):  return int(float(raw[:-1]) * 60)
    return int(float(raw) * 60)  # bare number = minutes
```

### Loop structure
```
Setup (once):
  - Load config, resolve providers, validate LLM key, parse currency
  - Interactive query suggestion + translation (runs once before the loop)
  - Open DB: conn = init_db()

try:
  while True:
    Print "── Iteration N ── HH:MM:SS"
    result = _run_search_once(...)
    new = filter_new(conn, result.listings, query)

    if new:
      print_table(new, original_prices=result.original_prices)
      Print "New: N  |  Dismissed: M  |  Total seen: K"
      mark_seen(conn, new, query)         <- before dismiss prompt so Ctrl+C mid-prompt doesn't lose state
      _prompt_dismiss(conn, new)
      if --save: save_results(new, ...)
    else:
      Print "[dim]No new listings.[/dim]"

    _countdown_sleep(interval_seconds)    <- countdown line, Ctrl+C propagates up

except KeyboardInterrupt:
  Print "Monitor stopped."
  conn.close()
```

### Dismiss prompt helper
```python
def _prompt_dismiss(conn, listings):
    choice = Prompt.ask("Mark as not interested (numbers, 'all', or Enter to skip)", default="")
    if not choice: return
    if choice.lower() == "all":
        mark_dismissed(conn, [l.url for l in listings])
        print(f"  -> {len(listings)} listing(s) dismissed.")
    else:
        urls = [listings[int(p.strip())-1].url for p in choice.split(",")
                if p.strip().isdigit() and 0 < int(p.strip()) <= len(listings)]
        if urls:
            mark_dismissed(conn, urls)
            print(f"  -> {len(urls)} listing(s) dismissed.")
```

### Countdown sleep helper
```python
def _countdown_sleep(seconds):
    for remaining in range(seconds, 0, -1):
        m, s = divmod(remaining, 60)
        print(f"\r[dim]Next check in {m}m {s:02d}s... (Ctrl+C to stop)[/dim]", end="")
        time.sleep(1)
    print("\r" + " "*60 + "\r", end="")
```

---

## Edge cases

| Case | Behaviour |
|------|-----------|
| First run | DB empty -> `filter_new` returns all -> everything is "new" |
| No new listings | Skip table + dismiss prompt, show "No new listings." |
| Ctrl+C any time | Outer `KeyboardInterrupt` handler: print "stopped", close DB |
| Ctrl+C during countdown | `time.sleep()` raises, caught by outer handler |
| Invalid `--interval` | `ValueError` in `_parse_interval` -> print error, `raise typer.Exit(1)` |
| `--save` with monitor | Each iteration saves only the NEW listings for that iteration |
| URL dismissed from query A | Still excluded from query B (exclusion is URL-level, not query-scoped) |

---

## Files modified

| File | Change |
|------|--------|
| `market_scout/monitor_db.py` | **New** — SQLite wrapper |
| `market_scout/cli.py` | Extract `_run_search_once()`, add `monitor` command + 3 helpers |

## Verification

```bash
# First run — all results appear as "new"
market-scout monitor --query "commodore 64" --provider hardverapro --interval 1m

# Second run (Ctrl+C after first iteration completes) — 0 new results
market-scout monitor --query "commodore 64" --provider hardverapro --interval 1m

# Check DB state
sqlite3 user_config/seen.db "SELECT count(*), dismissed FROM seen_listings GROUP BY dismissed"

# Test dismiss: run, dismiss entries 1,2,3, Ctrl+C, re-run, confirm those 3 don't appear
```
