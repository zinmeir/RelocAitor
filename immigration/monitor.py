"""
immigration/monitor.py — Notice when an official page changes, so a person re-checks the routes on it.

    python -m immigration monitor            # needs internet; reads only pages robots.txt allows

This deliberately does not extract figures from pages: immigration pages are long, change layout often
and many render with JavaScript, so automated extraction would produce confident wrong numbers. What can
be done reliably is to notice that a page is different from last time and flag the routes that cite it.
The re-check then goes through the proposal workflow like any other update.

Fetching is injected (`fetch`, `allowed`) so tests run offline and a deployment can swap in an API
or feed reader for publishers that offer one.
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
import urllib.robotparser
from datetime import date
from typing import Callable, Optional
from urllib.parse import urlparse

USER_AGENT = "RelocAitor-monitor/1.0 (+https://github.com/; checks official immigration pages for changes)"


def _get(url: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


_robots_cache: dict = {}


def _allowed(url: str) -> bool:
    host = urlparse(url)
    base = f"{host.scheme}://{host.netloc}"
    rp = _robots_cache.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser(base + "/robots.txt")
        try:
            rp.read()
        except OSError:
            return False          # can't read robots.txt: don't fetch
        _robots_cache[base] = rp
    return rp.can_fetch(USER_AGENT, url)


def fingerprint(html: str) -> str:
    """Hash of the page's visible text, so a new cookie banner timestamp or script tag isn't a 'change'."""
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(text.encode()).hexdigest()


def check_pages(sources: list, hashes: dict, fetch: Callable = _get, allowed: Callable = _allowed,
                today: Optional[str] = None) -> dict:
    """Return {"hashes": updated store, "events": [...]}; events say which routes to re-check."""
    today = today or date.today().isoformat()
    hashes = dict(hashes)
    events = []
    for src in sources:
        for url in src["urls"]:
            if not allowed(url):
                events.append({"url": url, "event": "not_allowed", "routes": src["routes"], "date": today})
                continue
            try:
                fp = fingerprint(fetch(url))
            except Exception as err:   # network errors, 4xx/5xx
                events.append({"url": url, "event": "unreachable", "error": str(err)[:200],
                               "routes": src["routes"], "date": today})
                continue
            before = hashes.get(url)
            if before and before["sha256"] != fp:
                events.append({"url": url, "event": "changed", "routes": src["routes"], "date": today,
                               "last_seen": before["checked"]})
            hashes[url] = {"sha256": fp, "checked": today}
    return {"hashes": hashes, "events": events}
