"""
relocaitor/career/jobs.py — live vacancies through a job API. Off unless configured.

    ADZUNA_APP_ID, ADZUNA_APP_KEY   enable Adzuna (https://developer.adzuna.com), which covers
                                    the countries in COUNTRIES below

Without keys the endpoint says vacancies are unavailable; it never substitutes examples. Results are
real listings returned by the provider, with its link, and are labelled as vacancies.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Callable

COUNTRIES = {"GBR": "gb", "USA": "us", "CAN": "ca", "AUS": "au", "NZL": "nz", "DEU": "de", "FRA": "fr",
             "NLD": "nl", "AUT": "at", "BEL": "be", "CHE": "ch", "ESP": "es", "ITA": "it", "POL": "pl",
             "IND": "in", "SGP": "sg", "ZAF": "za", "BRA": "br", "MEX": "mx"}
QUERY = {"tech": "software developer", "healthcare": "nurse", "engineering": "engineer", "education": "teacher",
         "trades": "electrician", "finance": "accountant", "science": "research scientist", "hospitality": "chef"}


def enabled() -> bool:
    return bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))


def _get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "RelocAitor"}), timeout=15) as r:
        return json.loads(r.read().decode())


def search(country: str, field: str, what: str = None, fetch: Callable = _get) -> dict:
    if not enabled():
        return {"enabled": False, "vacancies": [],
                "reason": "Live vacancies need a job API key (set ADZUNA_APP_ID and ADZUNA_APP_KEY)."}
    cc = COUNTRIES.get(country)
    if not cc:
        return {"enabled": True, "vacancies": [], "reason": f"The job API doesn't cover {country}."}
    q = what or QUERY.get(field, field or "")
    params = urllib.parse.urlencode({"app_id": os.environ["ADZUNA_APP_ID"], "app_key": os.environ["ADZUNA_APP_KEY"],
                                     "what": q, "results_per_page": 10, "content-type": "application/json"})
    try:
        data = fetch(f"https://api.adzuna.com/v1/api/jobs/{cc}/search/1?{params}")
    except Exception as err:   # network or provider errors
        return {"enabled": True, "vacancies": [], "reason": f"The job API didn't answer: {str(err)[:120]}"}
    out = [{"title": j.get("title"), "company": (j.get("company") or {}).get("display_name"),
            "location": (j.get("location") or {}).get("display_name"), "salary_min": j.get("salary_min"),
            "salary_max": j.get("salary_max"), "posted": j.get("created"), "url": j.get("redirect_url")}
           for j in data.get("results", [])]
    return {"enabled": True, "vacancies": out, "query": q, "provider": "Adzuna",
            "note": "Live listings from the provider. They are vacancies, not demand statistics, and don't imply visa sponsorship."}
