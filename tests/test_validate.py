"""Data files match their schemas and agree with each other (pipeline/validate.py)."""

import copy
import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from app import app                    # noqa: E402
from pipeline import validate         # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


def _schema(name):
    return jsonschema.Draft202012Validator(json.loads((DATA / f"schemas/{name}.schema.json").read_text(encoding="utf-8")))


def _visas():
    return json.loads((DATA / "visas.json").read_text(encoding="utf-8"))


def test_all_data_files_are_valid():
    assert validate.problems() == []


@pytest.mark.parametrize("mutate,expect", [
    (lambda v: v["fee"].update(ammount=v["fee"].pop("amount")), "'ammount' was unexpected"),
    (lambda v: v.update(pr_route="Maybe"), "'Maybe' is not one of"),
    (lambda v: v.update(years_to_pr=-1), "less than the minimum"),
    (lambda v: v.pop("sources"), "'sources' is a dependency of 'fee'"),
    (lambda v: v["family"].update(partner="yes"), "is not of type 'boolean'"),
    (lambda v: v.update(sources=["http://insecure.example"]), "does not match"),
])
def test_schema_catches_typos_and_impossible_values(mutate, expect):
    data = _visas()
    visa = next(v for v in data["GBR"]["visas"] if v["name"] == "Innovator Founder Visa")
    mutate(visa)
    messages = [e.message for e in _schema("visas").iter_errors(data)]
    assert any(expect in m for m in messages), messages


def test_unresearched_visas_need_no_sources():
    data = _visas()
    assert not list(_schema("visas").iter_errors({"KEN": data["KEN"]}))


def test_cross_file_checks_find_unknown_currency_and_job_field(monkeypatch):
    data = _visas()
    bad = copy.deepcopy(data)
    v = bad["GBR"]["visas"][0]
    v["fee"]["currency"] = "ZZZ"
    v["fields"] = ["astronomy"]
    real = validate._load
    monkeypatch.setattr(validate, "_load", lambda name: bad if name == "visas.json" else real(name))
    found = " ".join(validate.cross_file_errors())
    assert "no exchange rate for ZZZ" in found and "unknown job field 'astronomy'" in found


def test_data_version_is_served_with_results():
    c = app.test_client()
    v = json.loads((DATA / "version.json").read_text(encoding="utf-8"))["data_version"]
    assert c.get("/api/meta").get_json()["data_version"] == v
    assert c.post("/api/score", json={}).get_json()["data_version"] == v
    assert c.post("/api/insights", json={"country": "Japan"}).get_json()["data_version"] == v


# ---------- rules as data ----------

def test_a_new_rule_is_a_data_change_only(monkeypatch):
    """Adding a check to data/rules.json changes verdicts without touching code."""
    import eligibility
    from eligibility import Profile, evaluate_visa
    rules = copy.deepcopy(eligibility.rules())
    rules["visa_rules"].append({"id": "min_savings_note", "visa": "min_investment", "profile": "investment_budget",
                                "test": "at_least", "ignore_zero": True,
                                "missing": {"status": "conditional", "text": "Needs about {visa:usd} in savings. Add yours to check."},
                                "fail": {"status": "ineligible", "text": "unused"}})
    monkeypatch.setattr(eligibility, "rules", lambda: rules)
    visa = {"type": "investor", "min_income": 0, "min_investment": 250000}
    v = evaluate_visa(visa, Profile())
    assert v == {"status": "conditional", "reasons": ["Needs about $250,000 in savings. Add yours to check."]}


def test_rule_schema_rejects_unknown_tests():
    rules = json.loads((DATA / "rules.json").read_text(encoding="utf-8"))
    rules["visa_rules"][0]["test"] = "roughly"
    assert any("is not one of" in e.message for e in _schema("rules").iter_errors(rules))


def test_rules_read_real_fields():
    rules = json.loads((DATA / "rules.json").read_text(encoding="utf-8"))
    assert {r["id"] for r in rules["visa_rules"]} >= {"passport", "income", "investment", "age_max", "partner",
                                                      "children", "job_list", "sponsor"}
    assert not [p for p in validate.cross_file_errors() if p.startswith("rules.json")]


def test_prompt_patterns_come_from_the_lexicon(monkeypatch):
    import search
    lex = copy.deepcopy(search.lexicon())
    lex["personal"]["age_range"] = [16, 40]
    monkeypatch.setattr(search, "lexicon", lambda: lex)
    search.personal_patterns.cache_clear()
    try:
        assert search.extract_personal("I'm 52")["age"] is None
    finally:
        search.personal_patterns.cache_clear()
