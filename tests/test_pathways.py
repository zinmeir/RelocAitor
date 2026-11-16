"""Counterfactual visa reasoning: how could this person qualify?"""

import pytest

import pathways
from app import app
from data import get_nationalities
from eligibility import Profile

NAMES = {n["code"]: n["name"] for n in get_nationalities()}


@pytest.fixture()
def client():
    return app.test_client()


def test_gap_is_none_when_nothing_stands_in_the_way():
    assert pathways.visa_gap({"min_income": 1000}, Profile(monthly_income=1500)) is None
    assert pathways.visa_gap({}, Profile()) is None


def test_income_and_savings_gaps_are_exact():
    g = pathways.visa_gap({"min_income": 3000, "min_investment": 250000},
                          Profile(monthly_income=2400, investment_budget=200000))
    assert g["reachable"]
    kinds = {s["kind"]: s for s in g["steps"]}
    assert kinds["income"]["gap"] == 600 and kinds["savings"]["gap"] == 50000
    assert g["distance"] == pytest.approx(600 / 3000 + 50000 / 250000)
    assert "$600/mo more" in kinds["income"]["text"]


def test_passport_restriction_is_unreachable():
    g = pathways.visa_gap({"restricted_to": ["USA"]}, Profile(nationality="PAK"), NAMES)
    assert not g["reachable"] and g["distance"] is None
    assert "United States" in g["steps"][0]["text"]


def test_unknowns_ask_for_input_instead_of_guessing():
    g = pathways.visa_gap({"min_income": 3000, "restricted_to": ["USA"]}, Profile())
    assert set(g["unknown"]) == {"passport", "income"}
    assert g["steps"][-1]["kind"] == "unknown"


def test_levers_are_verified_by_rerunning_eligibility(client):
    """Every country a lever claims to open must actually open at that income."""
    profile = {"nationality": "PAK", "monthly_income": 2000, "only_qualifying": True}
    d = client.post("/api/pathways", json={"profile": profile}).get_json()
    income = [lv for lv in d["levers"] if lv["kind"] == "income"]
    assert income, "a $2,000/mo Pakistani passport holder should have income levers"
    assert [lv["value"] for lv in income] == sorted(lv["value"] for lv in income)
    first = income[0]
    before = {c["country_name"] for c in client.post("/api/score", json={"profile": profile}).get_json()["all"]}
    after = {c["country_name"] for c in client.post(
        "/api/score", json={"profile": {**profile, "monthly_income": first["value"]}}).get_json()["all"]}
    assert set(first["countries"]) == after - before
    # and one dollar less doesn't open them
    below = {c["country_name"] for c in client.post(
        "/api/score", json={"profile": {**profile, "monthly_income": first["value"] - 1}}).get_json()["all"]}
    assert not set(first["countries"]) & (below - before)


def test_near_misses_are_closed_countries_sorted_by_distance(client):
    profile = {"nationality": "PAK", "monthly_income": 2000, "only_qualifying": True}
    d = client.post("/api/pathways", json={"profile": profile}).get_json()
    open_now = {c["country_name"] for c in client.post("/api/score", json={"profile": profile}).get_json()["all"]}
    dists = [n["distance"] for n in d["near_misses"]]
    assert dists == sorted(dists) and all(0 < x <= 1 for x in dists)
    assert not {n["country"] for n in d["near_misses"]} & open_now


def test_filter_levers_report_what_relaxing_would_open(client):
    d = client.post("/api/pathways", json={"profile": {"nationality": "PAK", "require_pr": True,
                                                       "max_difficulty": "Easy"}}).get_json()
    fields = {lv["field"] for lv in d["levers"] if lv["kind"] == "filter"}
    assert {"require_pr", "max_difficulty"} <= fields


def test_insights_explain_how_to_qualify(client):
    d = client.post("/api/insights", json={"country": "Portugal",
                                           "profile": {"nationality": "PAK", "monthly_income": 500}}).get_json()
    paths = [v["path"] for v in d["visas"] if v["eligibility"]["status"] == "ineligible" and v["path"]]
    assert paths and any(s["kind"] == "income" for p in paths for s in p["steps"])
