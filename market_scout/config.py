"""
Global configuration for market-scout.

Config file location: <repo>/user_config/config.toml
Created automatically on first run with commented defaults.
The user_config/ directory is git-ignored.

All CLI flags override config values for that run.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# tomllib is stdlib since Python 3.11 (required by pyproject.toml)
import tomllib

# Repo root is two levels up from this file (market_scout/config.py)
_CONFIG_DIR = Path(__file__).parent.parent / "user_config"
_CONFIG_PATH = _CONFIG_DIR / "config.toml"

_DEFAULTS: dict[str, Any] = {
    "providers": [],           # empty = all providers
    "location": "",            # empty = auto-detect (FB) / nationwide (others)
    "radius": 0,
    "max_results": 30,
    "headless": True,
    "cookies": "",             # path to FB cookies file
    "user_lang": "en",         # language for result translation
    "openrouter": {
        "api_key": "",
        "model": "anthropic/claude-haiku-4-5",
        "base_url": "https://openrouter.ai/api/v1",
    },
}

_DEFAULT_TOML = """\
# market-scout global configuration
# All values here are defaults; CLI flags override them for each run.
# Edit this file or run: market-scout config --set key=value

# --- Search defaults ---

# Comma-separated list of providers to use when --provider is not given.
# Empty = all providers.
# Example: providers = ["hardverapro", "jofogas", "vatera", "bazos_cz", "bazos_sk"]
providers = []

# Default location for Facebook searches (country codes or city slugs).
# Example: location = "HU"
location = ""

# Default FB search radius in km (0 = use per-city DB defaults).
radius = 0

# Default max results per provider/city.
max_results = 30

# Run Facebook browser headlessly by default.
headless = true

# Path to your Facebook cookies JSON file.
# Example: cookies = "~/.market-scout/cookies.json"
cookies = ""

# Language for result translation.
# Titles and conditions are automatically translated to this language after
# each search (when an OpenRouter API key is configured).
# Use any language name: "en", "de", "hu", "pl", "cs", "sk", etc.
# Set to "" to disable automatic translation.
user_lang = "en"

# --- LLM (OpenRouter) ---
[openrouter]

# Your OpenRouter API key — get one at https://openrouter.ai/keys
# You can also set this via the OPENROUTER_API_KEY environment variable.
api_key = ""

# Model to use for query translation and suggestions.
# Default is claude-haiku-4-5 (fast, cheap). Other options:
#   "openai/gpt-4o-mini", "google/gemini-flash-1.5", "mistralai/mistral-small"
model = "anthropic/claude-haiku-4-5"

# OpenRouter API base URL (usually no need to change).
base_url = "https://openrouter.ai/api/v1"
"""


def config_path() -> Path:
    return _CONFIG_PATH


def _ensure_config_dir() -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict[str, Any]:
    """Load config from file, falling back to defaults for missing keys."""
    cfg: dict[str, Any] = {}
    # Deep copy defaults
    for k, v in _DEFAULTS.items():
        cfg[k] = v.copy() if isinstance(v, dict) else v

    if not _CONFIG_PATH.exists():
        return cfg

    try:
        raw = tomllib.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return cfg

    # Merge top-level keys
    for k, v in raw.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v

    return cfg


def get_openrouter_key(cfg: dict[str, Any]) -> str:
    """Return API key from config or OPENROUTER_API_KEY env var."""
    env = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if env:
        return env
    return cfg.get("openrouter", {}).get("api_key", "").strip()


def init_config_file() -> Path:
    """Write the default config file if it doesn't exist. Returns the path."""
    _ensure_config_dir()
    if not _CONFIG_PATH.exists():
        _CONFIG_PATH.write_text(_DEFAULT_TOML, encoding="utf-8")
    return _CONFIG_PATH


def set_value(key: str, value: str) -> None:
    """
    Naive key=value setter — reads the TOML as text, updates or appends the line.
    Supports top-level keys and one level of nesting (openrouter.api_key).
    """
    init_config_file()
    text = _CONFIG_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()

    if "." in key:
        section, subkey = key.split(".", 1)
        # Find the section and update the key inside it
        in_section = False
        updated = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == f"[{section}]":
                in_section = True
            elif stripped.startswith("[") and stripped.endswith("]"):
                in_section = False
            if in_section and stripped.startswith(f"{subkey}"):
                new_lines.append(f'{subkey} = "{value}"')
                updated = True
                continue
            new_lines.append(line)
        if not updated:
            new_lines.append(f'\n[{section}]\n{subkey} = "{value}"')
        _CONFIG_PATH.write_text("\n".join(new_lines), encoding="utf-8")
    else:
        # Top-level key
        updated = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(f"{key}") and "=" in stripped:
                # Decide quoting: strings get quotes, bools/ints don't
                try:
                    int(value)
                    new_lines.append(f"{key} = {value}")
                except ValueError:
                    if value.lower() in ("true", "false"):
                        new_lines.append(f"{key} = {value}")
                    else:
                        new_lines.append(f'{key} = "{value}"')
                updated = True
                continue
            new_lines.append(line)
        if not updated:
            try:
                int(value)
                new_lines.append(f"{key} = {value}")
            except ValueError:
                if value.lower() in ("true", "false"):
                    new_lines.append(f"{key} = {value}")
                else:
                    new_lines.append(f'{key} = "{value}"')
        _CONFIG_PATH.write_text("\n".join(new_lines), encoding="utf-8")
