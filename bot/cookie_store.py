"""Persistent cookie store for authenticated web fetching.

Cookies are stored per-domain in ``data/cookies.json``.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_COOKIE_FILE = Path(__file__).parent.parent / "data" / "cookies.json"


def _load() -> dict:
    try:
        if _COOKIE_FILE.exists():
            return json.loads(_COOKIE_FILE.read_text())
    except Exception as e:
        logger.warning("Failed to load cookies: %s", e)
    return {}


def _save(store: dict) -> None:
    try:
        _COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _COOKIE_FILE.write_text(json.dumps(store, indent=2))
    except Exception as e:
        logger.warning("Failed to save cookies: %s", e)


def get_cookies(domain: str) -> dict:
    """Get stored cookies for a domain (and its parent domain)."""
    store = _load()
    # Try exact match first, then progressively shorter domains
    parts = domain.strip().lower().split(".")
    for i in range(len(parts)):
        key = ".".join(parts[i:])
        if key in store:
            return dict(store[key])
    return {}


def set_cookies(domain: str, cookie_string: str) -> None:
    """Store cookies for a domain.

    Parameters
    ----------
    domain : str
        Domain name (e.g. ``example.com``).
    cookie_string : str
        Cookie string in ``name=value; name2=value2`` format.
    """
    store = _load()
    cookies = {}
    for pair in cookie_string.split(";"):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            cookies[k.strip()] = v.strip()
    if cookies:
        store[domain.strip().lower()] = cookies
        _save(store)
        logger.info("Cookies saved for %s (%d entries)", domain, len(cookies))


def clear_cookies(domain: str = "") -> None:
    """Clear stored cookies.

    Parameters
    ----------
    domain : str
        If provided, clear cookies only for that domain.
        If empty, clear all stored cookies.
    """
    if domain:
        store = _load()
        key = domain.strip().lower()
        if key in store:
            del store[key]
            _save(store)
            logger.info("Cookies cleared for %s", domain)
    else:
        _save({})
        logger.info("All cookies cleared")


def list_domains() -> list[str]:
    """Return list of domains with stored cookies."""
    return sorted(_load().keys())
