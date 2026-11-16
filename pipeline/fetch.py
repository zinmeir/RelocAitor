"""
fetch.py — Refresh data/raw/ from the World Bank and WHO APIs.

    python -m pipeline fetch

Only the standard library is used. Each indicator is saved as
data/raw/<worldbank|who>/<indicator>.csv with columns country_code, year, value,
keeping the most recent non-empty value per country. Manual sources
(data/manual/*.csv) have no API; update them by hand from the URLs in their headers.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

from .sources import SOURCES, WHO_GHO_API, WORLD_BANK_API

DATA = Path(__file__).resolve().parent.parent / "data"
BATCH = 22          # country codes per request (keeps URLs short)


def _get_json(url: str, timeout: float = 60.0):
    req = urllib.request.Request(url, headers={"User-Agent": "RelocAitor data pipeline"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_worldbank(payload) -> list:
    """World Bank JSON -> [(iso3, year, value)], most recent non-null per country."""
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        return []
    best = {}
    for rec in payload[1]:
        code, year, value = rec.get("countryiso3code"), rec.get("date"), rec.get("value")
        if code and value is not None and (code not in best or int(year) > int(best[code][0])):
            best[code] = (int(year), float(value))
    return sorted((c, y, v) for c, (y, v) in best.items())


def parse_who(payload, codes: set) -> list:
    """WHO GHO OData JSON -> [(iso3, year, value)], most recent per country."""
    best = {}
    for rec in (payload or {}).get("value", []):
        code, year, value = rec.get("SpatialDim"), rec.get("TimeDim"), rec.get("NumericValue")
        if code in codes and value is not None and (code not in best or int(year) > best[code][0]):
            best[code] = (int(year), float(value))
    return sorted((c, y, v) for c, (y, v) in best.items())


def fetch_all(codes: list, data_dir: Path = DATA, get=_get_json, pause: float = 0.3) -> dict:
    """Download every API source. Returns {indicator: number of countries with data}."""
    counts = {}
    for sid, spec in SOURCES.items():
        rows = []
        if spec["kind"] == "worldbank":
            for i in range(0, len(codes), BATCH):
                url = WORLD_BANK_API.format(codes=";".join(codes[i:i + BATCH]), indicator=sid)
                rows += parse_worldbank(get(url))
                time.sleep(pause)
            folder = "worldbank"
        elif spec["kind"] == "who":
            rows = parse_who(get(WHO_GHO_API.format(indicator=sid, since=2015)), set(codes))
            folder = "who"
        else:
            continue
        out = data_dir / "raw" / folder / f"{sid}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=["country_code", "year", "value"]).to_csv(out, index=False)
        counts[sid] = len(rows)
    return counts
