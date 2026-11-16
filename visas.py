"""
visas.py — Curated visa pathway data, loaded from data/visas.json.

Each country entry has an `official_url` (government immigration portal) and a
list of pathways. Each pathway has:
- type:            skilled | nomad | investor | study | family | startup | passive
                   ("free" is generated at runtime for free-movement rights)
- name:            official or common visa name
- difficulty:      Easy | Moderate | Hard (subjective, relative to peers)
- duration:        typical initial validity / pathway duration
- pr_route:        Yes | Eventually | No
- min_income:      approximate minimum monthly income in USD (0 if N/A)
- min_investment:  approximate minimum investment in USD (0 if N/A)
- summary:         one-line description
- restricted_to:   optional list of ISO-3 nationalities allowed to apply
- requires_sponsor: optional, True for family routes
- note:            optional caveat shown in the UI
- last_verified:   ISO date when someone last checked this against the official
                   source, or null if never verified

Visa rules change frequently. Always confirm with the official source.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

import journey
from eligibility import (
    DIFFICULTY_RANK, Profile, evaluate_visa, free_movement_pathways, is_qualifying,
)

VISAS_JSON = Path(__file__).resolve().parent / "data" / "visas.json"

VISA_TYPES = {
    "skilled":  "Skilled worker",
    "nomad":    "Digital nomad",
    "investor": "Investor / golden visa",
    "study":    "Study route",
    "startup":  "Startup founder",
    "family":   "Family / partner",
    "passive":  "Passive income / retiree",
}
VALID_PR = {"Yes", "Eventually", "No"}


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(VISAS_JSON, encoding="utf-8") as f:
        return json.load(f)


def clear_cache() -> None:
    _load.cache_clear()


def official_url(country_code: str) -> Optional[str]:
    entry = _load().get(country_code)
    return entry["official_url"] if entry else None


def get_visas_for(country_code: str) -> list:
    """Raw visa pathways for a country (copies, safe to mutate)."""
    entry = _load().get(country_code)
    return [dict(v) for v in entry["visas"]] if entry else []


def visas_for_profile(country_code: str, profile: Optional[Profile] = None) -> dict:
    """
    Visa pathways annotated for this user:
      {visas: [... each with "eligibility" and "qualifies"], qualifying_count,
       is_home, official_url}
    Free-movement rights are prepended when the user's passport grants them.
    """
    profile = profile or Profile()
    is_home = bool(profile.nationality) and profile.nationality == country_code

    entry = country_entry(country_code)
    visas = free_movement_pathways(profile.nationality, country_code) + get_visas_for(country_code)
    qualifying = 0
    for v in visas:
        verdict = evaluate_visa(v, profile)
        v["eligibility"] = verdict
        v["qualifies"] = is_qualifying(v, verdict, profile)
        v["timeline"] = journey.timeline(v, entry)
        if v.get("fields") and profile.occupation:
            v["field_match"] = profile.occupation in v["fields"]
        qualifying += v["qualifies"]

    return {
        "visas": visas,
        "qualifying_count": qualifying,
        "is_home": is_home,
        "official_url": official_url(country_code),
        "researched": country_code in _load(),
        "citizenship": entry.get("citizenship"),
        "in_demand": entry.get("in_demand"),
        "field_in_demand": journey.field_in_demand(entry, profile.occupation),
    }


def country_entry(country_code: str) -> dict:
    """Country-level facts (citizenship rules, shortage list) without the visa list."""
    entry = _load().get(country_code) or {}
    return {k: v for k, v in entry.items() if k != "visas"}


def filter_visas(visas: list, visa_type: str = None, max_difficulty: str = None) -> list:
    """Optionally filter visas by type and/or max difficulty."""
    out = visas
    if visa_type and visa_type != "any":
        out = [v for v in out if v["type"] == visa_type]
    if max_difficulty:
        max_rank = DIFFICULTY_RANK.get(max_difficulty, 2)
        out = [v for v in out if DIFFICULTY_RANK.get(v["difficulty"], 2) <= max_rank]
    return out


def all_visa_types() -> list:
    """[{key, label}] for every visa category that actually appears in the data."""
    present = {v["type"] for c in _load().values() for v in c["visas"]}
    return [{"key": k, "label": lbl} for k, lbl in VISA_TYPES.items() if k in present]
