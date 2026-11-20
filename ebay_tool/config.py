"""Load settings and stored tokens from local JSON files (never committed)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
TOKENS_PATH = ROOT / "tokens.json"
DATA_DIR = Path(os.environ.get("EBAY_TOOL_DATA_DIR") or ROOT / "data")  # override for tests/demo


class ConfigError(Exception):
    pass


def load_config(require_ebay=True):
    if not CONFIG_PATH.exists():
        raise ConfigError(
            "config.json fehlt. Kopiere config.example.json nach config.json "
            "und trage die eBay-Schlüssel ein (siehe SETUP.md)."
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    ebay = cfg.setdefault("ebay", {})
    if require_ebay:
        missing = ebay_missing(cfg)
        if missing:
            raise ConfigError("In config.json fehlt ebay.%s (siehe SETUP.md)." % missing)
    ebay.setdefault("marketplace_id", "EBAY_DE")
    ebay.setdefault("site_id", "77")
    return cfg


def load_tokens():
    if not TOKENS_PATH.exists():
        return {}
    with open(TOKENS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_tokens(tokens):
    tmp = TOKENS_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
    os.chmod(tmp, 0o600)
    tmp.replace(TOKENS_PATH)


def ebay_missing(cfg):
    ebay = cfg.get("ebay", {})
    for key in ("client_id", "client_secret", "ru_name"):
        if not ebay.get(key) or str(ebay[key]).startswith("PASTE_"):
            return key
    return None


def sevdesk_configured(cfg):
    t = cfg.get("sevdesk", {}).get("api_token") or ""
    return bool(t) and not t.startswith("PASTE_")
