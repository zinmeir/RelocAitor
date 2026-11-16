"""
pipeline/currency.py — Exchange rates for showing money in the user's own currency.

    python -m pipeline currencies     # rebuild data/currencies.json (offline)

Every amount in RelocAitor is stored in US dollars. To show it in pesos, rupees or
yen we need one rate per currency:

1. ECB euro reference rates (data/fx.json), converted to dollars. Daily, so used first.
2. Otherwise the World Bank official rate (PA.NUS.FCRF), an annual average. Read from
   data/raw/worldbank/PA.NUS.FCRF.csv (refreshed by `python -m pipeline fetch`) and
   data/manual/fx_annual.csv (a snapshot for every country); the newer year wins.
   Rates older than MAX_AGE years are left out: a 2017 rate for a currency that has
   since collapsed would be worse than showing dollars.

Which currency a country uses comes from data/manual/currency.csv (Unicode CLDR).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
MAX_AGE = 3


def _rows(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(l for l in f if not l.startswith("#")))


def build(data_dir: Path = DATA) -> dict:
    countries = {r["country_code"]: r["currency"] for r in _rows(data_dir / "manual" / "currency.csv")}
    fx = json.loads((data_dir / "fx.json").read_text(encoding="utf-8"))

    annual = {}   # iso3 -> (year, lcu per usd)
    for r in _rows(data_dir / "manual" / "fx_annual.csv"):
        annual[r["country_code"]] = (int(r["year"]), float(r["lcu_per_usd"]))
    for r in _rows(data_dir / "raw" / "worldbank" / "PA.NUS.FCRF.csv"):
        y, v = int(float(r["year"])), float(r["value"])
        if r["country_code"] not in annual or y >= annual[r["country_code"]][0]:
            annual[r["country_code"]] = (y, v)
    newest = max((y for y, _ in annual.values()), default=0)

    rates = {"USD": {"usd_per_unit": 1.0, "basis": "dollar"}}
    for cur, usd in fx["usd_per_unit"].items():
        if cur != "USD":
            rates[cur] = {"usd_per_unit": usd, "basis": "daily"}
    for code, cur in sorted(countries.items()):
        if cur in rates or code not in annual:
            continue
        year, lcu = annual[code]
        if lcu <= 0 or year < newest - MAX_AGE + 1:
            continue
        rates[cur] = {"usd_per_unit": round(1 / lcu, 10), "basis": "annual", "year": year}

    return {
        "about": "US dollars per unit of each currency, used only to show amounts in the currency you choose. "
                 "Rankings always use dollars.",
        "daily_date": fx.get("date"),
        "daily_source": fx.get("source"),
        "annual_source": "https://data.worldbank.org/indicator/PA.NUS.FCRF",
        "countries": {k: v for k, v in sorted(countries.items()) if v in rates},
        "rates": dict(sorted(rates.items())),
    }


def write(data_dir: Path = DATA) -> dict:
    out = build(data_dir)
    (data_dir / "currencies.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out
