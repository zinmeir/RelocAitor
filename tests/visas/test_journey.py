"""Visa costs and timelines, job fields, family and age rules, cities (journey.py and friends)."""

import json
from pathlib import Path

import pytest

from relocaitor.visas import journey
from relocaitor.nlp import search
from relocaitor.web.app import app, meta
from relocaitor.visas.eligibility import Profile, evaluate_visa
from pipeline import visa_details
from relocaitor.visas.catalog import visas_for_profile
from relocaitor import paths

ROOT = paths.ROOT


@pytest.fixture()
def client():
    return app.test_client()


# ---------- data ----------

def test_visas_json_matches_research_record():
    assert visa_details.main(["--check"]) == 0


def test_every_researched_visa_names_an_official_source_and_date():
    data = json.loads((ROOT / "data/visas.json").read_text(encoding="utf-8"))
    researched = [v for c in data.values() for v in c["visas"] if "checked" in v]
    assert len(researched) == len(visa_details.VISAS_RESEARCH)
    for v in researched:
        assert v["sources"] and all(u.startswith("https://") for u in v["sources"])
        assert "wikipedia" not in " ".join(v["sources"])           # visa figures are official-only
        if "fee" in v:
            assert v["fee"]["currency"] in journey.fx()["usd_per_unit"]


def test_citizenship_is_labelled_as_a_secondary_source():
    data = json.loads((ROOT / "data/visas.json").read_text(encoding="utf-8"))
    for code, entry in data.items():
        if "citizenship" in entry:
            assert entry["citizenship"]["source_kind"] == "secondary"
    assert "SGP" not in visa_details.CITIZENSHIP     # discretionary: left out rather than guessed


def test_job_fields_in_shortage_lists_exist():
    keys = set(journey.occupations())
    for lst in visa_details.IN_DEMAND.values():
        assert set(lst["fields"]) <= keys


# ---------- timeline ----------

def test_timeline_for_direct_pr_route():
    t = journey.timeline({"pr_route": "Yes", "years_to_pr": 0, "fee": {"amount": 6450, "currency": "NZD"}},
                         {"citizenship": {"years": 5, "after_pr": 5}})
    assert t["pr_years"] == 0 and t["citizenship_years"] == 5
    assert t["fee"].startswith("NZ$6,450 (about $")
    assert [s["label"] for s in t["steps"]] == ["Apply", "Permanent residence on arrival", "Citizenship"]
    assert t["complete"]


def test_citizenship_waits_for_time_as_permanent_resident():
    # UK: 5 years to settlement, then 12 months as a settled person -> 6, not 5.
    assert journey.citizenship_at(5, {"years": 5, "after_pr": 1}) == 6
    assert journey.citizenship_at(3, {"years": 5, "after_pr": 1}) == 5
    assert journey.citizenship_at(None, {"years": 5}) is None


def test_no_timeline_without_research_and_none_for_routes_without_pr():
    assert journey.timeline({"pr_route": "Eventually"}, {}) is None
    t = journey.timeline({"pr_route": "No", "years_to_pr": 3, "fee": {"amount": 100, "currency": "USD"}},
                         {"citizenship": {"years": 5}})
    assert t["pr_years"] is None and t["citizenship_years"] is None and t["fee"] == "$100"


def test_unknown_currency_shows_local_amount_only():
    assert journey.fee_text({"amount": 2000, "currency": "XYZ"}) == "2,000 XYZ"


# ---------- eligibility ----------

VISA = {"type": "skilled", "name": "Test", "pr_route": "Yes", "min_income": 0, "min_investment": 0,
        "age_max": 55, "family": {"partner": True, "children": False}, "fields": ["healthcare", "tech"]}


def test_age_limit():
    assert evaluate_visa(VISA, Profile(age=58, occupation="tech"))["status"] == "ineligible"
    assert evaluate_visa(VISA, Profile(age=55, occupation="tech"))["status"] == "eligible"
    assert evaluate_visa(VISA, Profile(occupation="tech"))["status"] == "eligible"   # unknown age never blocks


def test_family_rules_only_block_when_the_member_is_coming():
    assert evaluate_visa(VISA, Profile(partner=True, occupation="tech"))["status"] == "eligible"
    v = evaluate_visa(VISA, Profile(children=2, occupation="tech"))
    assert v["status"] == "ineligible" and "Children can't come" in v["reasons"][0]
    assert evaluate_visa(VISA, Profile(children=0, occupation="tech"))["status"] == "eligible"


def test_job_list_visas():
    assert evaluate_visa(VISA, Profile())["status"] == "conditional"
    assert evaluate_visa(VISA, Profile(occupation="trades"))["status"] == "ineligible"
    assert evaluate_visa(VISA, Profile(occupation="healthcare"))["status"] == "eligible"


def test_new_zealand_smc_age_limit_from_research():
    info = visas_for_profile("NZL", Profile(age=58))
    smc = next(v for v in info["visas"] if v["name"] == "Skilled Migrant Category")
    assert smc["eligibility"]["status"] == "ineligible"
    assert smc["timeline"]["citizenship_years"] == 5


def test_field_in_demand_flag(client):
    r = client.post("/api/score", json={"profile": {"occupation": "healthcare"}}).get_json()
    by = {c["country_code"]: c["field_in_demand"] for c in r["all"]}
    assert by["NZL"] is True and by["CAN"] is True
    assert by["USA"] is None                                    # no researched list
    r = client.post("/api/score", json={"profile": {"occupation": "hospitality"}}).get_json()
    assert {c["country_code"]: c["field_in_demand"] for c in r["all"]}["NZL"] is False


def test_insights_include_journey_fields(client):
    d = client.post("/api/insights", json={"country": "United States"}).get_json()
    assert d["citizenship"]["years"] == 5 and d["cities"][0]["name"] == "New York City"
    assert any(v["timeline"] for v in d["visas"])
    d = client.post("/api/insights", json={"country": "Kenya"}).get_json()
    assert d["cities"] == [] and d["in_demand"] is None


@pytest.mark.parametrize("profile,msg", [({"occupation": "astronaut"}, "occupation"), ({"age": 9}, "age"),
                                         ({"children": 40}, "children"), ({"age": "old"}, "age")])
def test_profile_validation(client, profile, msg):
    r = client.post("/api/score", json={"profile": profile})
    assert r.status_code == 400 and msg in r.get_json()["error"]


# ---------- reading it from a prompt ----------

@pytest.mark.parametrize("text,expected", [
    ("I'm a 34-year-old Pakistani nurse moving with my wife and two kids",
     {"occupation": "healthcare", "age": 34, "partner": True, "children": 2}),
    ("software engineer, 29 years old, single", {"occupation": "tech", "age": 29, "partner": False}),
    ("we are a couple with a baby, I work as a teacher", {"occupation": "education", "partner": True, "children": 1}),
    ("no kids, my husband is a doctor", {"occupation": "healthcare", "partner": True, "children": 0}),
    ("I'm a mechanical engineer", {"occupation": "engineering"}),
    ("I like to cook and want sunny places", {}),                 # "cook" needs "I'm a" / "work as a"
    ("I work as a cook", {"occupation": "hospitality"}),
    ("I'm 3k a month in debt", {}),                                # not an age
    ("top 10 countries, I'm 45", {"age": 45}),
])
def test_extract_personal(text, expected):
    got = {k: v for k, v in search.extract_personal(text).items()
           if k in ("occupation", "age", "partner", "children") and v is not None}
    assert got == expected


def test_prompt_sets_profile_and_chips_and_city():
    r = search.interpret_rules("Is Toronto good for a data scientist aged 31?", meta(), use_model=False, use_semantic=False)
    assert r["profile"]["occupation"] == "tech" and r["profile"]["age"] == 31
    assert r["city"] == "Toronto" and r["countries"] == ["Canada"]
    labels = [c["label"] for c in r["chips"]]
    assert "Field: Tech & IT" in labels and "Looking at Toronto, Canada" in labels


def test_follow_up_updates_family_and_age(client):
    state = {"weights": {}, "region": "All regions", "profile": {"occupation": "tech"}, "top_n": 5}
    d = client.post("/api/refine", json={"prompt": "I'm 61 now, with my wife", "state": state}).get_json()
    p = d["state"]["profile"]
    assert p["age"] == 61 and p["partner"] is True and p["occupation"] == "tech"
    assert {"Age: 61", "Moving with your partner"} <= {c["label"] for c in d["changes"]}
