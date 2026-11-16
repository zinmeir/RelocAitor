"""
relocaitor/immigration/catalogue.py — Every attribute an immigration route can have, and what we know about it.

The list follows the brief's data model (country, visa, requirements, costs, timelines, rights,
sources). Each field says where its value comes from in data/visas.json, if anywhere yet, and how
long a checked value stays current before it is shown as outdated.

A field with `key=None` has no data anywhere in the project yet. It is still listed so that every
route reports it as "unknown" instead of silently leaving it out: the gap is part of the answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Field:
    name: str                     # stable id used in records, proposals and the API
    label: str                    # shown to people
    group: str                    # requirements | costs | timeline | rights | identity
    key: Optional[str]            # where the value lives on a visa in visas.json (None = not collected yet)
    fresh_days: int = 730         # a checked value older than this is "outdated"
    legacy: bool = False          # curated by hand before per-field sources were recorded
    get: Optional[Callable] = None  # custom reader (visa, country entry) -> value


def _processing(v, _e):
    if v.get("processing") is None and v.get("processing_weeks") is None:
        return None
    return {"text": v.get("processing"), "weeks": v.get("processing_weeks")}


def _pr(v, _e):
    out = {k: v[k] for k in ("pr_route", "years_to_pr", "pr_note") if v.get(k) is not None}
    return out or None


def _age(v, _e):
    out = {k: v[k] for k in ("age_min", "age_max") if v.get(k) is not None}
    return out or None


def _citizenship(_v, e):
    return e.get("citizenship")


FIELDS = (
    # Requirements
    Field("nationality_restrictions", "Nationality restrictions", "requirements", "restricted_to", legacy=True),
    Field("min_income", "Minimum income", "requirements", "min_income", fresh_days=365, legacy=True),
    Field("min_savings", "Minimum savings", "requirements", None, fresh_days=365),
    Field("investment", "Investment requirement", "requirements", "min_investment", fresh_days=365, legacy=True),
    Field("education", "Educational qualifications", "requirements", "education_min"),
    Field("work_experience", "Work experience", "requirements", "experience_years"),
    Field("language", "Language requirements", "requirements", "language"),
    Field("age", "Age requirements", "requirements", "age_max", get=_age),
    Field("sponsorship", "Employment or sponsorship", "requirements", "requires_sponsor", legacy=True),
    Field("occupations", "Eligible occupations", "requirements", "fields"),
    Field("healthcare", "Health insurance or medical requirements", "requirements", None),
    Field("documents", "Required documents", "requirements", None),
    # Costs
    Field("fees", "Application fees", "costs", "fee", fresh_days=365),
    # Timeline
    Field("processing_time", "Processing time", "timeline", "processing", fresh_days=180, get=_processing),
    Field("duration", "Visa duration", "timeline", "duration", legacy=True),
    Field("renewal", "Renewal conditions", "timeline", None),
    Field("residence_requirements", "Residence requirements", "timeline", None),
    Field("pr_pathway", "Permanent residency pathway", "timeline", "pr_route", get=_pr),
    Field("citizenship_pathway", "Citizenship pathway", "timeline", "citizenship", get=_citizenship),
    # Rights
    Field("dependants", "Dependants eligibility", "rights", "family"),
    Field("spouse_work_rights", "Spouse work rights", "rights", None),
    Field("tax", "Tax implications", "rights", None),
    # Where to apply
    Field("application_url", "Official application page", "identity", None),
    Field("difficulty", "Difficulty (editorial rating)", "identity", "difficulty", legacy=True),
)

BY_NAME = {f.name: f for f in FIELDS}

# The values a proposal may change, mapped to the field that reports them.
EDITABLE_KEYS = {
    "restricted_to": "nationality_restrictions", "min_income": "min_income", "min_investment": "investment",
    "age_min": "age", "age_max": "age", "requires_sponsor": "sponsorship", "fields": "occupations",
    "fee": "fees", "processing": "processing_time", "processing_weeks": "processing_time",
    "duration": "duration", "pr_route": "pr_pathway", "years_to_pr": "pr_pathway", "pr_note": "pr_pathway",
    "family": "dependants", "difficulty": "difficulty",
    "education_min": "education", "experience_years": "work_experience", "language": "language",
}

# Research keys merged by pipeline/visa_details.py: when a route has `sources` and `checked`,
# these fields came from those official pages.
RESEARCHED_KEYS = {"fee", "processing", "processing_weeks", "years_to_pr", "pr_note", "family",
                   "age_min", "age_max", "fields", "education_min", "experience_years", "language"}

STATUSES = ("verified", "sourced", "third_party", "estimated", "unknown", "outdated")
STATUS_LABEL = {
    "verified": "Officially verified",
    "sourced": "Officially sourced, awaiting verification",
    "third_party": "Third-party source",
    "estimated": "Estimated or unsourced",
    "unknown": "Unknown",
    "outdated": "Outdated",
}


def value_of(field: Field, visa: dict, entry: dict):
    if field.get:
        return field.get(visa, entry)
    if field.key is None:
        return None
    v = visa.get(field.key)
    if field.name in ("investment", "min_income") and v == 0:
        return 0            # 0 is a real answer ("no minimum") for curated routes, kept as such
    return v
