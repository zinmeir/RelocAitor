"""
eligibility.py — Who can actually use which visa.

Turns a user's profile (passport, income, savings, age, family, job field, hard
filters) into per-visa eligibility verdicts, and adds citizenship-based
free-movement rights (EU/EEA, Common Travel Area, Trans-Tasman, GCC, Mercosur)
as extra pathways.

The rules themselves are data: data/rules.json lists the blocs and every visa
check (which visa field, which profile field, how to compare them, and the
message). This module and preview/mock_api.js are two small interpreters of the
same file, so a new rule is written once.

These rules are simplified. They are meant to surface the big, obvious
differences (an EU citizen doesn't need a Blue Card for Germany), not to
replace an immigration lawyer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path
from typing import Optional

DIFFICULTY_RANK = {"Easy": 0, "Moderate": 1, "Hard": 2}
PR_YES = {"Yes", "Eventually"}

RULES_JSON = Path(__file__).resolve().parent / "data" / "rules.json"


@lru_cache(maxsize=1)
def rules() -> dict:
    """data/rules.json: free-movement blocs and the visa checks, shared with the browser build."""
    return json.loads(RULES_JSON.read_text(encoding="utf-8"))


def blocs() -> list:
    return rules()["blocs"]


@dataclass
class Profile:
    nationality: Optional[str] = None        # ISO-3, e.g. "PAK"
    monthly_income: Optional[float] = None   # USD / month
    investment_budget: Optional[float] = None  # USD
    visa_type: str = "any"                   # hard filter: must have this visa type
    require_pr: bool = False                 # hard filter: must have a route to PR
    max_difficulty: Optional[str] = None     # hard filter: Easy | Moderate | Hard
    only_qualifying: bool = False            # hard filter: must have a visa I likely qualify for
    exclude_home: bool = True                # hide my own country from rankings
    exclude_countries: tuple = ()            # ISO-3 codes to hide ("not the US")
    age: Optional[int] = None                # years; checked against visa age limits
    partner: Optional[bool] = None           # moving with a spouse or partner?
    children: Optional[int] = None           # how many children are coming
    occupation: Optional[str] = None         # job field key from data/occupations.json
    education: Optional[str] = None          # highest level: secondary | diploma | bachelor | master | doctorate
    experience_years: Optional[float] = None  # years of skilled work experience
    english: Optional[str] = None            # CEFR level A1..C2
    german: Optional[str] = None             # CEFR level A1..C2

    @property
    def visa_filter_active(self) -> bool:
        return (self.only_qualifying or self.require_pr
                or self.visa_type not in (None, "", "any") or bool(self.max_difficulty))

    def to_dict(self) -> dict:
        return asdict(self)


def free_movement_pathways(nationality: Optional[str], dest: str) -> list:
    """Citizenship-based rights the user has in `dest` (empty if none)."""
    if not nationality or nationality == dest:
        return []
    out = []
    for bloc in blocs():
        if nationality in bloc["members"] and dest in bloc["members"]:
            out.append({
                "type": "free", "name": bloc["name"], "difficulty": "Easy",
                "duration": bloc["duration"], "pr_route": bloc["pr_route"],
                "min_income": 0, "min_investment": 0, "summary": bloc["summary"],
                "generated": True, "last_verified": None,
            })
    return out


def _get(obj: dict, path: str):
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def _money(x) -> str:
    return f"${x:,.0f}"


def _lang_text(req) -> str:
    if isinstance(req, dict):
        name = rules()["labels"]["language"].get(req.get("lang"), req.get("lang"))
        level = req.get("cefr") or req.get("test")
        return f"{name} at {level}" + (" (CEFR)" if req.get("cefr") else "")
    return str(req)


def _text(template: str, visa_value, profile_value) -> str:
    """Fill {visa}, {profile}, {visa:usd}, {profile:usd}, {visa:fields}, education and language placeholders."""
    out = template
    edu = rules()["labels"]["education"]
    if "{visa:education}" in out:
        out = out.replace("{visa:education}", edu.get(visa_value, str(visa_value)))
    if "{profile:education}" in out:
        out = out.replace("{profile:education}", edu.get(profile_value, str(profile_value)))
    if "{visa:language}" in out:
        out = out.replace("{visa:language}", _lang_text(visa_value))
    if "{profile:language}" in out:
        out = out.replace("{profile:language}", str(profile_value))
    if "{visa:fields}" in out:
        out = out.replace("{visa:fields}", ", ".join(_field_labels(visa_value)))
    if "{visa:usd}" in out:
        out = out.replace("{visa:usd}", _money(visa_value))
    if "{profile:usd}" in out:
        out = out.replace("{profile:usd}", _money(profile_value))
    return out.replace("{visa}", str(visa_value)).replace("{profile}", str(profile_value))


def _rule_outcome(rule: dict, visa: dict, profile: Profile):
    """The rule's 'fail' or 'missing' outcome if it applies to this visa and profile, else None."""
    if visa.get("type") in rule.get("skip_types", ()):
        return None
    v = _get(visa, rule["visa"])
    if v is None or v == [] or (rule.get("ignore_zero") and v == 0):
        return None
    test = rule["test"]
    if test == "flag":
        return (rule["fail"], v, None) if v else None
    if test == "language":
        p = getattr(profile, v.get("lang"), None)
        if not p:
            return (rule["missing"], v, p)
        if not v.get("cefr"):
            return (rule["incomparable"], v, p)
        scale = rules()["scales"]["cefr"]
        return (rule["fail"], v, p) if scale.index(p) < scale.index(v["cefr"]) else None
    p = getattr(profile, rule["profile"], None)
    if p is None or p == "":
        return (rule["missing"], v, p) if "missing" in rule else None
    failed = {
        "in": lambda: p not in v,
        "at_least": lambda: p < v,
        "at_most": lambda: p > v,
        "allowed": lambda: v is False and bool(p),
        "rank_at_least": lambda: rules()["scales"][rule["scale"]].index(p) < rules()["scales"][rule["scale"]].index(v),
    }[test]()
    return (rule["fail"], v, p) if failed else None


def evaluate_visa(visa: dict, profile: Profile) -> dict:
    """Return {"status": eligible|conditional|ineligible, "reasons": [...]}, applying data/rules.json in order."""
    status, reasons = "eligible", []
    for rule in rules()["visa_rules"]:
        hit = _rule_outcome(rule, visa, profile)
        if not hit:
            continue
        outcome, v, p = hit
        if rule.get("only_if_eligible") and status != "eligible":
            continue
        if outcome["status"] == "ineligible":
            status = "ineligible"
        elif status == "eligible":
            status = "conditional"
        reasons.append(_text(outcome["text"], v, p))
    return {"status": status, "reasons": reasons}


def _field_labels(keys) -> list:
    from journey import field_label
    return [field_label(k) or k for k in keys]


def matches_constraints(visa: dict, profile: Profile) -> bool:
    """Does this visa satisfy the user's hard filters (type, PR, difficulty)?"""
    vt = profile.visa_type
    # Free-movement rights let you work, study, invest… so they satisfy any type filter.
    if vt not in (None, "", "any") and visa["type"] != vt and visa["type"] != "free":
        return False
    if profile.require_pr and visa.get("pr_route") not in PR_YES:
        return False
    if profile.max_difficulty:
        max_rank = DIFFICULTY_RANK.get(profile.max_difficulty, 2)
        if DIFFICULTY_RANK.get(visa.get("difficulty"), 2) > max_rank:
            return False
    return True


def is_qualifying(visa: dict, verdict: dict, profile: Profile) -> bool:
    """A visa the user can realistically use AND that satisfies their hard filters."""
    if not matches_constraints(visa, profile):
        return False
    if verdict["status"] == "eligible":
        return True
    # A sponsor-based family visa only counts if the user explicitly asked for family routes.
    return bool(verdict["status"] == "conditional" and visa.get("requires_sponsor")
                and profile.visa_type == "family")
