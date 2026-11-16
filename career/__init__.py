"""
career — career intelligence connected to immigration routes.

What it uses, and how it is labelled:
- Official shortage lists (data/visas.json in_demand, 4 countries)        → "official list"
- World Bank unemployment rate and the job-market factor (countries.csv)   → "national indicator"
- English proficiency (EF EPI factor)                                       → "national indicator"
- Visa routes and their researched requirements                             → the eligibility rules
- Live vacancies only through a job API (career/jobs.py), off without keys  → "vacancy", never mixed
  with the statistics above

Not available, and said so: salary ranges per occupation, qualification recognition outside the routes
that state it.
"""

from __future__ import annotations

import re
from dataclasses import replace

from eligibility import Profile, evaluate_visa, rules
import journey
import planner
import visas as V

LEVEL_UP = {"english": ["B1", "B2", "C1"], "german": ["A1", "B1", "B2"]}


def _unemployment(code: str):
    from data import get_provenance
    d = (get_provenance(code).get("job_market") or {}).get("detail", "")
    m = re.search(r"SL\.UEM\.TOTL\.ZS (\d{4})=([0-9.]+)", d)
    return {"pct": float(m.group(2)), "year": int(m.group(1)), "source": "World Bank SL.UEM.TOTL.ZS"} if m else None


def country_outlook(code: str, profile: Profile) -> dict:
    from data import load_countries
    row = load_countries().set_index("country_code").loc[code]
    entry = V.country_entry(code)
    field = profile.occupation
    demand = entry.get("in_demand")
    if not field:
        in_demand = None
    elif demand:
        in_demand = field in demand["fields"]
    else:
        in_demand = None
    routes = []
    for v in V._load().get(code, {}).get("visas", []):
        if v["type"] not in ("skilled", "startup"):
            continue
        listed = v.get("fields")
        if listed and field and field not in listed:
            continue
        verdict = evaluate_visa(v, profile)
        routes.append({"name": v["name"], "status": verdict["status"], "reasons": verdict["reasons"],
                       "requirements_note": v.get("requirements_note"),
                       "unchecked": planner.unchecked(planner.route_id(code, v["name"]))})
    return {
        "country": code, "country_name": row["country_name"],
        "field": journey.field_label(field),
        "shortage_list": ({"name": demand["list"], "source": demand["source"], "checked": demand["checked"],
                           "field_listed": in_demand} if demand else None),
        "indicators": {"job_market_score": round(float(row["job_market"]), 2),
                       "unemployment": _unemployment(code),
                       "english_score": round(float(row["english"]), 2)},
        "work_routes": routes,
        "not_available": ["salary ranges for your occupation", "qualification recognition (except where a route states it)"],
    }


def skills_gap(profile: Profile, countries: list) -> dict:
    """Which single improvement opens which work routes, by re-running the real rules."""
    candidates = []
    for lang, levels in LEVEL_UP.items():
        cur = getattr(profile, lang)
        scale = rules()["scales"]["cefr"]
        for lv in levels:
            if cur is None or scale.index(lv) > scale.index(cur):
                candidates.append((f"Reach {lang.title()} {lv} (CEFR)", {lang: lv}))
    edu_scale = rules()["scales"]["education"]
    for lv in ("bachelor", "master"):
        if profile.education is None or edu_scale.index(lv) > edu_scale.index(profile.education):
            candidates.append((f"Complete a {rules()['labels']['education'][lv]}", {"education": lv}))
    for extra in (1, 2):
        candidates.append((f"Gain {extra} more year{'s' if extra > 1 else ''} of skilled experience",
                           {"experience_years": (profile.experience_years or 0) + extra}))
    roadmap, seen = [], {}
    for label, change in candidates:
        res = planner.what_if(profile, change)
        opened = [r for r in res["opened"] + res["improved"] if r["country"] in countries]
        group = next(iter(change))
        keys = {(r["route"], r["after"]) for r in opened}
        if keys and keys <= seen.get(group, set()):
            continue                     # a smaller step in the same skill already opens these
        seen[group] = seen.get(group, set()) | keys
        if opened:
            roadmap.append({"action": label, "change": change,
                            "opens": [{"route": r["name"], "country": r["country"], "after": r["after"]} for r in opened]})
    roadmap.sort(key=lambda x: -len(x["opens"]))
    return {"roadmap": roadmap,
            "note": "Each step is re-checked against the visa rules we have researched. Routes whose requirements "
                    "we haven't researched can't show up here, and none of this is a job offer."}


def career_report(profile: Profile, countries: list) -> dict:
    return {"countries": [country_outlook(c, profile) for c in countries],
            "skills_gap": skills_gap(profile, countries),
            "vacancies_note": "Vacancies are separate from these statistics and come only from a job API (see /api/career/jobs)."}
