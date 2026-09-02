"""
ExamShield v1.4 — External TOML Configuration Loader
Reads examshield.toml from the project root and overrides Config defaults.
"""
import os
import tomllib

from src.config import Config


def load():
    """
    Load examshield.toml if present.  Recognized top-level keys map to
    Config attributes: version, blocked_websites, allowed_websites,
    selective_blocking, blocked_keys extend_with, etc.
    Returns the parsed dict (empty if file missing).
    """
    toml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examshield.toml")
    if not os.path.isfile(toml_path):
        return {}

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)

    _apply(data)
    return data


def _apply(data: dict):
    """Apply recognised keys from the parsed TOML onto Config."""
    top = data.get("security", {})
    if "block_internet" in top:
        Config.BLOCK_INTERNET = top["block_internet"]
    if "full_internet_block" in top:
        Config.FULL_INTERNET_BLOCK = top["full_internet_block"]

    sel = data.get("selective_blocking", {})
    if sel:
        Config.SELECTIVE_BLOCKING.update(sel)

    sites = data.get("blocked_websites", {}).get("extend_with", [])
    if sites:
        for s in sites:
            if s not in Config.BLOCKED_WEBSITES:
                Config.BLOCKED_WEBSITES.append(s)

    allowed = data.get("allowed_websites", {}).get("extend_with", [])
    if allowed:
        for a in allowed:
            if a not in Config.ALLOWED_WEBSITES:
                Config.ALLOWED_WEBSITES.append(a)

    keys_ext = data.get("blocked_keys", {}).get("extend_with", [])
    if keys_ext:
        for k in keys_ext:
            if k not in Config.BLOCKED_KEYS:
                Config.BLOCKED_KEYS.append(k)
