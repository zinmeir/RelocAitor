"""
relocaitor/web/validation.py — Request parsing. Every API input goes through here, so a bad
value gives a clear 400 error instead of a 500 stack trace.
"""

from __future__ import annotations

from typing import Any, Optional

from relocaitor.datasets import country_codes, get_nationalities, get_regions
from relocaitor.visas.eligibility import DIFFICULTY_RANK, Profile
from relocaitor.ranking.factors import DEFAULT_WEIGHTS, FACTOR_KEYS
from relocaitor.visas.catalog import VISA_TYPES

ALL_REGIONS = "All regions"
MAX_COMPARE = 3


class BadRequest(ValueError):
    """Raised for invalid client input; the API turns it into a 400 response."""


def _float(value: Any, field: str, lo: float = None, hi: float = None) -> float:
    if isinstance(value, bool):
        raise BadRequest(f"'{field}' must be a number")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise BadRequest(f"'{field}' must be a number") from None
    if v != v or v in (float("inf"), float("-inf")):
        raise BadRequest(f"'{field}' must be a finite number")
    if lo is not None and v < lo:
        raise BadRequest(f"'{field}' must be ≥ {lo}")
    if hi is not None and v > hi:
        raise BadRequest(f"'{field}' must be ≤ {hi}")
    return v


def _optional_money(value: Any, field: str) -> Optional[float]:
    if value in (None, ""):
        return None
    return _float(value, field, lo=0, hi=1e12)


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def parse_weights(raw: Any) -> dict:
    """Known factors only, clamped to [0, 1]; missing factors use the defaults."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BadRequest("'weights' must be an object")
    out = {}
    for k in FACTOR_KEYS:
        v = raw.get(k, DEFAULT_WEIGHTS[k])
        out[k] = min(1.0, max(0.0, _float(v, f"weights.{k}")))
    return out


def parse_region(raw: Any) -> str:
    if raw in (None, "", ALL_REGIONS):
        return ALL_REGIONS
    if raw not in get_regions():
        raise BadRequest(f"Unknown region '{raw}'")
    return raw


def parse_top_n(raw: Any, default: int = 5) -> int:
    if raw in (None, ""):
        return default
    v = _float(raw, "top_n")
    if v != int(v):
        raise BadRequest("'top_n' must be a whole number")
    return int(min(len(country_codes()), max(1, v)))


def parse_profile(raw: Any) -> Profile:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BadRequest("'profile' must be an object")

    nat = raw.get("nationality") or None
    if nat is not None:
        nat = str(nat).upper()
        if nat not in {n["code"] for n in get_nationalities()}:
            raise BadRequest(f"Unknown nationality '{nat}'")

    vt = raw.get("visa_type") or "any"
    if vt != "any" and vt not in VISA_TYPES:
        raise BadRequest(f"Unknown visa_type '{vt}'")

    md = raw.get("max_difficulty") or None
    if md is not None and md not in DIFFICULTY_RANK:
        raise BadRequest(f"'max_difficulty' must be one of {list(DIFFICULTY_RANK)}")

    excl = raw.get("exclude_countries") or []
    if not isinstance(excl, list) or len(excl) > 250:
        raise BadRequest("'exclude_countries' must be a list")
    by_name = {n["name"].lower(): n["code"] for n in get_nationalities()}
    codes = country_codes()
    exclude = []
    for x in excl:
        code = x.upper() if isinstance(x, str) and x.upper() in codes else by_name.get(str(x).lower())
        if code not in codes:
            raise BadRequest(f"Unknown country in exclude_countries: '{x}'")
        exclude.append(code)

    occ = raw.get("occupation") or None
    if occ is not None and occ not in _occupations():
        raise BadRequest(f"Unknown occupation '{occ}'")
    age = raw.get("age")
    age = None if age in (None, "") else int(_float(age, "age", lo=16, hi=100))
    kids = raw.get("children")
    kids = None if kids in (None, "") else int(_float(kids, "children", lo=0, hi=12))
    partner = raw.get("partner")
    partner = None if partner in (None, "") else _bool(partner)

    from relocaitor.visas.eligibility import rules as _rules
    scales = _rules()["scales"]
    edu = raw.get("education") or None
    if edu is not None and edu not in scales["education"]:
        raise BadRequest(f"'education' must be one of {scales['education']}")
    exp = raw.get("experience_years")
    exp = None if exp in (None, "") else round(_float(exp, "experience_years", lo=0, hi=60), 1)
    langs = {}
    for lang in ("english", "german"):
        lv = raw.get(lang) or None
        if lv is not None and lv not in scales["cefr"]:
            raise BadRequest(f"'{lang}' must be a CEFR level {scales['cefr']}")
        langs[lang] = lv

    return Profile(
        education=edu, experience_years=exp, **langs,
        age=age, partner=partner, children=kids, occupation=occ,
        exclude_countries=tuple(dict.fromkeys(exclude)),
        nationality=nat,
        monthly_income=_optional_money(raw.get("monthly_income"), "monthly_income"),
        investment_budget=_optional_money(raw.get("investment_budget"), "investment_budget"),
        visa_type=vt,
        require_pr=_bool(raw.get("require_pr", False)),
        max_difficulty=md,
        only_qualifying=_bool(raw.get("only_qualifying", False)),
        exclude_home=_bool(raw.get("exclude_home", True)),
    )


def parse_country(raw: Any, names: set) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise BadRequest("'country' is required")
    if raw not in names:
        raise NotFound(f"Country '{raw}' not found")
    return raw


def parse_country_list(raw: Any, names: set) -> list:
    if not isinstance(raw, list) or not raw:
        raise BadRequest("'countries' must be a non-empty list")
    if len(raw) > MAX_COMPARE:
        raise BadRequest(f"Compare at most {MAX_COMPARE} countries")
    out = []
    for c in raw:
        name = parse_country(c, names)
        if name not in out:
            out.append(name)
    return out


def _occupations() -> dict:
    from relocaitor.visas.journey import occupations
    return occupations()


class NotFound(LookupError):
    """Raised for unknown resources; the API turns it into a 404 response."""
