"""
journey.py — What a visa costs, how long it takes, and where it leads.

Researched figures live next to each visa in data/visas.json and are all optional:

    fee:             {"amount": 819, "currency": "GBP", "note": "..."}  main applicant, government fees
    processing:      "About 3 weeks from outside the UK"                 official service standard, as text
    processing_weeks: 3                                                  the same as a number, for the timeline
    years_to_pr:     5        years on this route before you can apply for permanent residence (0 = direct PR)
    pr_note:         "..."    when the wait depends on something (German level, for example)
    family:          {"partner": true, "children": true}                 can they come with you on this visa?
    age_min / age_max: 18 / 45                                           only when the route sets an age limit
    fields:          ["healthcare", ...]                                  only when the route is limited to listed jobs
    sources:         ["https://..."], checked: "2026-11-16"

Country-level facts sit beside the visa list:

    citizenship: {"years": 5, "after_pr": 1, "note": "...", "source": "..."}
    in_demand:   {"fields": ["healthcare", "tech"], "list": "Critical Skills Occupations List", "source": "..."}

Anything not confirmed from an official source is left out rather than guessed,
so every function here copes with missing values.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

DATA = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=1)
def fx() -> dict:
    """{"date", "source", "usd_per_unit": {"EUR": 1.08, ...}}; empty rates if the file is missing."""
    path = DATA / "fx.json"
    if not path.exists():
        return {"date": None, "source": None, "usd_per_unit": {"USD": 1.0}}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def currencies() -> dict:
    """data/currencies.json (built by `python -m pipeline currencies`): rates to show money in your own currency."""
    path = DATA / "currencies.json"
    if not path.exists():
        return {"countries": {}, "rates": {"USD": {"usd_per_unit": 1.0, "basis": "dollar"}}}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def occupations() -> dict:
    return json.loads((DATA / "occupations.json").read_text(encoding="utf-8"))["fields"]


def field_label(key: Optional[str]) -> Optional[str]:
    return occupations().get(key, {}).get("label") if key else None


SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "INR": "₹",
           "CAD": "CA$", "AUD": "A$", "NZD": "NZ$", "SGD": "S$", "HKD": "HK$"}


def to_usd(amount: Optional[float], currency: Optional[str]) -> Optional[float]:
    if amount is None or not currency:
        return None
    rate = fx()["usd_per_unit"].get(currency)
    return None if rate is None else round(amount * rate)


def fee_text(fee: Optional[dict]) -> Optional[str]:
    """'£819 (about $1,100)' or None."""
    if not fee or fee.get("amount") is None:
        return None
    cur, amt = fee["currency"], fee["amount"]
    symbol = SYMBOLS.get(cur)
    local = f"{symbol}{amt:,.0f}" if symbol else f"{amt:,.0f} {cur}"
    usd = to_usd(amt, cur)
    if cur == "USD" or usd is None:
        return local
    return f"{local} (about ${usd:,.0f})"


def citizenship_at(years_to_pr: Optional[float], cit: Optional[dict]) -> Optional[float]:
    """Earliest year (from arrival) you could naturalise on this route, if both facts are known."""
    if years_to_pr is None or not cit or cit.get("years") is None:
        return None
    return max(float(cit["years"]), float(years_to_pr) + float(cit.get("after_pr") or 0))


def timeline(visa: dict, country: dict) -> Optional[dict]:
    """
    A visa's road from application to citizenship, using only researched figures:
      {"fee", "fee_usd", "fee_note", "processing", "processing_weeks",
       "pr_years", "citizenship_years", "steps": [{"at": years, "label"}], "complete"}
    Returns None when nothing about the route has been researched yet.
    """
    if visa.get("generated"):
        return None
    fee = visa.get("fee")
    pr_years = visa.get("years_to_pr")
    if visa.get("pr_route") == "No":
        pr_years = None
    cit = country.get("citizenship")
    cit_years = citizenship_at(pr_years, cit) if visa.get("pr_route") != "No" else None
    if not any([fee, visa.get("processing"), pr_years is not None]):
        return None

    weeks = visa.get("processing_weeks")
    steps = [{"at": 0, "label": "Apply"}]
    if weeks:
        steps.append({"at": round(weeks / 52, 2), "label": "Visa decision"})
    if pr_years is not None:
        steps.append({"at": pr_years, "label": "Permanent residence" if pr_years else "Permanent residence on arrival"})
    if cit_years is not None:
        steps.append({"at": cit_years, "label": "Citizenship"})
    return {
        "fee": fee_text(fee),
        "fee_usd": to_usd(fee["amount"], fee["currency"]) if fee else None,
        "fee_note": fee.get("note") if fee else None,
        "processing": visa.get("processing"),
        "processing_weeks": weeks,
        "pr_years": pr_years,
        "pr_note": visa.get("pr_note"),
        "citizenship_years": cit_years,
        "steps": steps,
        "complete": fee is not None and pr_years is not None and cit_years is not None,
    }


@lru_cache(maxsize=1)
def _cities() -> dict:
    path = DATA / "cities.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"cities": {}}


def cities(country_code: str) -> list:
    """Researched figures for a country's major cities (empty when none were researched)."""
    return [dict(c) for c in _cities()["cities"].get(country_code, [])]


def cities_meta() -> dict:
    """Everything the prompt reader and the static build need about cities."""
    data = _cities()
    return {"about": data.get("_about"), "cities": data["cities"]}


def field_in_demand(country: dict, field: Optional[str]) -> Optional[bool]:
    """True/False when the country publishes a shortage list and you set a field; else None."""
    lst = country.get("in_demand")
    if not field or not lst:
        return None
    return field in lst.get("fields", [])
