"""Configuration — loads from ~/.config/kn/config.toml with env var overrides."""

import tomllib
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "kn"
CONFIG_PATH = CONFIG_DIR / "config.toml"

DEFAULTS = {
    "amazon_domain": "amazon.com",
}


def load_config() -> dict:
    """Load config from TOML file, with env var overrides (KN_AMAZON_DOMAIN)."""
    import os

    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            cfg.update(tomllib.load(f))

    # Env vars override file config
    if v := os.environ.get("KN_AMAZON_DOMAIN"):
        cfg["amazon_domain"] = v

    return cfg
