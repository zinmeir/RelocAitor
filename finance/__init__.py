"""
finance — the financial life simulator.

Every line of the result says where it came from:
- "sourced"     a published statistic (OECD Taxing Wages; World Bank price levels)
- "editorial"   the dataset's editorial estimates (typical net salary, 1-bed rent)
- "input"       a number you entered
- "assumption"  a default you can change (deposit months, growth rates) — never presented as data
- "unknown"     we have nothing; the line is left out of totals and listed

Tax is the OECD effective rate (income tax + employee contributions) for a single person at the national
average wage. It is not a tax calculator: at other incomes, or with a family, your rate differs. Outside
the 38 OECD countries no tax rate is applied unless you give one.

Projections are arithmetic on your inputs and the stated assumptions, in three scenarios. They are not
forecasts.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

DATA = Path(__file__).resolve().parent.parent / "data"
YEARS = (1, 3, 5, 10)

SCENARIOS = {
    "pessimistic": {"salary_growth": 0.01, "inflation": 0.04, "rent_growth": 0.05, "jobless_months": 1.0},
    "baseline":    {"salary_growth": 0.03, "inflation": 0.025, "rent_growth": 0.03, "jobless_months": 0.0},
    "optimistic":  {"salary_growth": 0.05, "inflation": 0.02, "rent_growth": 0.02, "jobless_months": 0.0},
}


@lru_cache(maxsize=1)
def tax_table() -> dict:
    return json.loads((DATA / "finance" / "tax_oecd.json").read_text(encoding="utf-8"))


def _country_row(code: str):
    from data import load_countries
    df = load_countries()
    rows = df[df["country_code"] == code]
    if rows.empty:
        raise ValueError(f"Unknown country '{code}'")
    return rows.iloc[0]


def price_level(code: str) -> Optional[float]:
    """World Bank consumption price level relative to the US (1.0), from the dataset's provenance."""
    from data import get_provenance
    detail = (get_provenance(code).get("cost_of_living") or {}).get("detail", "")
    import re
    m = re.search(r"PRICE_LEVEL\(consumption\) \d{4}=([0-9.]+)", detail)
    return float(m.group(1)) if m else None


def _num(body: dict, key: str, lo: float = 0, hi: float = 1e9, default=None):
    v = body.get(key, default)
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        raise ValueError(f"'{key}' must be a number")
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"'{key}' must be a number") from None
    if not lo <= v <= hi:
        raise ValueError(f"'{key}' must be between {lo:g} and {hi:g}")
    return v


def simulate(body: dict) -> dict:
    code = body.get("country")
    if not isinstance(code, str):
        raise ValueError("'country' (ISO-3 code) is required")
    row = _country_row(code)
    lines, unknown = [], []

    # ---- income ----
    gross = _num(body, "gross_monthly_usd", 0, 1e6)
    tax_override = _num(body, "tax_rate_pct", 0, 90)
    if gross is not None:
        income = {"label": "Gross salary", "usd": gross, "status": "input"}
        rate = tax_override if tax_override is not None else tax_table()["rates_pct"].get(code)
        if tax_override is not None:
            tax = {"label": "Income tax and employee contributions", "pct": rate, "usd": gross * rate / 100, "status": "input"}
        elif rate is not None:
            tax = {"label": "Income tax and employee contributions", "pct": rate, "usd": gross * rate / 100,
                   "status": "sourced", "source": tax_table()["source"],
                   "note": "OECD effective rate at the national average wage for a single person (2025); yours differs at other incomes or with a family"}
        else:
            tax = {"label": "Income tax and employee contributions", "pct": None, "usd": None, "status": "unknown",
                   "note": "No sourced rate for this country (outside the OECD). Enter your expected rate to include it."}
            unknown.append("income tax")
        net = gross - (tax["usd"] or 0)
    else:
        income = {"label": "Typical net salary", "usd": float(row["salary_usd_month"]), "status": "editorial",
                  "note": "Editorial estimate of an average net salary; enter your expected gross salary instead"}
        tax = {"label": "Income tax and employee contributions", "pct": None, "usd": 0, "status": "not_applied",
               "note": "Not applied: the typical salary is already net"}
        net = income["usd"]

    # ---- spending ----
    rent_in = _num(body, "rent_usd", 0, 1e5)
    rent = ({"label": "Rent", "usd": rent_in, "status": "input"} if rent_in is not None else
            {"label": "Rent (1-bed, city centre)", "usd": float(row["rent_usd_month"]), "status": "editorial",
             "note": "Editorial estimate; cities vary a lot"})
    other_in = _num(body, "other_spend_usd", 0, 1e5)
    home_spend = _num(body, "home_spend_usd", 0, 1e5)
    home = body.get("home_country")
    if other_in is not None:
        other = {"label": "Other living costs", "usd": other_in, "status": "input"}
    elif home_spend is not None and isinstance(home, str):
        pd_, ph = price_level(code), price_level(home)
        if pd_ and ph:
            other = {"label": "Other living costs", "usd": round(home_spend * pd_ / ph, 2), "status": "sourced",
                     "note": f"Your current non-rent spending scaled by World Bank consumption price levels "
                             f"({ph:.2f} at home → {pd_:.2f} here, US = 1)"}
        else:
            other = {"label": "Other living costs", "usd": None, "status": "unknown",
                     "note": "No price level for one of the countries; enter an amount instead"}
            unknown.append("other living costs")
    else:
        other = {"label": "Other living costs", "usd": None, "status": "unknown",
                 "note": "Enter what you expect to spend besides rent, or your current spending and home country"}
        unknown.append("other living costs")
    extra = _num(body, "extra_monthly_usd", 0, 1e5)
    extras = [{"label": "Other regular costs you entered (school, insurance, childcare…)", "usd": extra, "status": "input"}] if extra else []

    spend = rent["usd"] + (other["usd"] or 0) + (extra or 0)
    monthly_savings = net - spend
    lines = [income, tax, rent, other, *extras]

    # ---- one-off costs ----
    deposit_months = _num(body, "deposit_months", 0, 12, 2)
    emergency_months = _num(body, "emergency_months", 0, 24, 3)
    flights = _num(body, "flights_usd", 0, 1e5)
    visa_fee = _num(body, "visa_fee_usd", 0, 1e6)
    one_off = [
        {"label": f"Rental deposit ({deposit_months:g} months' rent)", "usd": rent["usd"] * deposit_months, "status": "assumption"},
        {"label": f"Emergency fund ({emergency_months:g} months of spending)", "usd": spend * emergency_months, "status": "assumption"},
    ]
    if visa_fee is not None:
        one_off.append({"label": "Visa fees", "usd": visa_fee, "status": "input"})
    else:
        unknown.append("visa fees")
    if flights is not None:
        one_off.append({"label": "Flights and moving", "usd": flights, "status": "input"})
    else:
        unknown.append("flights and moving")
    upfront = sum(x["usd"] for x in one_off if x["label"].startswith(("Rental", "Visa", "Flights")))

    # ---- projections ----
    overrides = body.get("assumptions") or {}
    if not isinstance(overrides, dict):
        raise ValueError("'assumptions' must be an object")
    projections = {}
    for name, base in SCENARIOS.items():
        a = {**base, **{k: float(v) for k, v in (overrides.get(name) or {}).items() if k in base}}
        if not (-0.5 < a["salary_growth"] < 1 and -0.5 < a["inflation"] < 1 and 0 <= a["jobless_months"] <= 12):
            raise ValueError(f"Assumptions for '{name}' are out of range")
        projections[name] = {"assumptions": a, "years": _project(net, rent["usd"], spend - rent["usd"], upfront, a)}

    return {"country": code, "monthly": {"lines": lines, "net_usd": round(net, 2), "spending_usd": round(spend, 2),
                                         "savings_usd": round(monthly_savings, 2)},
            "one_off": {"lines": one_off, "upfront_usd": round(upfront, 2)},
            "projections": projections, "unknown": unknown,
            "note": "Projections are arithmetic on your inputs and the stated assumptions, not forecasts. "
                    "Totals leave out anything listed as unknown."}


def _project(net: float, rent: float, other: float, upfront: float, a: dict) -> list:
    """Cumulative savings at the end of each year, after paying the upfront costs from savings."""
    out, total = [], -upfront
    for y in range(1, max(YEARS) + 1):
        g = (1 + a["salary_growth"]) ** (y - 1)
        work_months = 12 - a["jobless_months"]
        income = net * g * work_months
        costs = (rent * (1 + a["rent_growth"]) ** (y - 1) + other * (1 + a["inflation"]) ** (y - 1)) * 12
        total += income - costs
        if y in YEARS:
            out.append({"year": y, "cumulative_savings_usd": round(total, 2),
                        "monthly_net_usd": round(net * g, 2)})
    return out


def compare(body: dict) -> dict:
    codes = body.get("countries")
    if not isinstance(codes, list) or not 2 <= len(codes) <= 4:
        raise ValueError("'countries' must list 2 to 4 ISO-3 codes")
    return {"results": [simulate({**body, "country": c}) for c in codes]}
