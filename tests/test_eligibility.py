from eligibility import Profile, evaluate_visa, free_movement_pathways, is_qualifying, matches_constraints
from visas import visas_for_profile


def _visa(**kw):
    base = {"type": "skilled", "name": "Test", "difficulty": "Moderate", "duration": "1y",
            "pr_route": "Eventually", "min_income": 0, "min_investment": 0, "summary": "x"}
    return base | kw


def test_eu_citizen_gets_free_movement_in_germany():
    paths = free_movement_pathways("FRA", "DEU")
    assert len(paths) == 1 and paths[0]["type"] == "free"


def test_no_free_movement_for_non_members():
    assert free_movement_pathways("PAK", "DEU") == []
    assert free_movement_pathways("GBR", "DEU") == []  # UK left the EU
    assert free_movement_pathways("DEU", "DEU") == []  # own country


def test_cta_and_trans_tasman():
    assert free_movement_pathways("GBR", "IRL")
    assert free_movement_pathways("NZL", "AUS")


def test_income_threshold():
    v = _visa(min_income=3000)
    assert evaluate_visa(v, Profile(monthly_income=2000))["status"] == "ineligible"
    assert evaluate_visa(v, Profile(monthly_income=3500))["status"] == "eligible"
    assert evaluate_visa(v, Profile())["status"] == "eligible"  # unknown income: don't block


def test_investment_threshold():
    v = _visa(type="investor", min_investment=250000)
    assert evaluate_visa(v, Profile(investment_budget=100000))["status"] == "ineligible"
    assert evaluate_visa(v, Profile(investment_budget=300000))["status"] == "eligible"


def test_nationality_restriction():
    v = _visa(restricted_to=["USA"])
    assert evaluate_visa(v, Profile(nationality="USA"))["status"] == "eligible"
    assert evaluate_visa(v, Profile(nationality="PAK"))["status"] == "ineligible"
    assert evaluate_visa(v, Profile())["status"] == "conditional"


def test_family_visa_is_conditional():
    v = _visa(type="family", requires_sponsor=True)
    verdict = evaluate_visa(v, Profile())
    assert verdict["status"] == "conditional"
    assert not is_qualifying(v, verdict, Profile())
    assert is_qualifying(v, verdict, Profile(visa_type="family"))


def test_constraints():
    v = _visa(difficulty="Hard", pr_route="No")
    assert not matches_constraints(v, Profile(max_difficulty="Moderate"))
    assert not matches_constraints(v, Profile(require_pr=True))
    assert not matches_constraints(v, Profile(visa_type="nomad"))
    assert matches_constraints(_visa(type="free"), Profile(visa_type="nomad"))


def test_daft_only_for_americans():
    us = {v["name"]: v for v in visas_for_profile("NLD", Profile(nationality="USA"))["visas"]}
    pk = {v["name"]: v for v in visas_for_profile("NLD", Profile(nationality="PAK"))["visas"]}
    assert us["DAFT (US treaty)"]["eligibility"]["status"] == "eligible"
    assert pk["DAFT (US treaty)"]["eligibility"]["status"] == "ineligible"


def test_home_flag():
    assert visas_for_profile("PRT", Profile(nationality="PRT"))["is_home"]
