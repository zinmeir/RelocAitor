"""Prompt understanding: these are the behaviours users rely on."""

import json

import pytest

from relocaitor.nlp import assistant
from relocaitor.nlp import search
from relocaitor.web.app import meta


@pytest.fixture(scope="module")
def m():
    return meta()


def run(m, text):
    return search.interpret_rules(text, m)


def labels(r):
    return " | ".join(c["label"] for c in r["chips"])


def test_full_profile_prompt(m):
    r = run(m, "I'm a Pakistani software engineer earning $3k a month. I want somewhere safe and "
               "English-speaking in Europe with a path to PR, cold is fine.")
    p = r["profile"]
    assert p["nationality"] == "PAK"
    assert p["monthly_income"] == 3000
    assert p["visa_type"] == "skilled"
    assert p["require_pr"] is True and p["only_qualifying"] is True
    assert r["region"] == "Europe"
    w = r["weights"]
    assert w["safety"] >= 0.8 and w["english"] >= 0.8 and w["pr"] >= 0.8
    assert w["climate"] <= 0.1                       # "cold is fine"
    assert w["salary"] < 0.9                         # "earning $3k" is money, not a preference
    assert r["unmatched"] == []


@pytest.mark.parametrize("text,factor,low,high", [
    ("fast internet is a must", "internet", 1.0, 1.0),
    ("ideally somewhere sunny", "climate", 0.5, 0.5),
    ("good healthcare", "healthcare", 1.0, 1.0),
    ("I don't care about salary", "salary", 0.0, 0.05),
    ("salary is not important, safety is", "salary", 0.0, 0.05),
    ("no snow please", "climate", 0.8, 0.8),
    ("not too expensive", "cost", 0.8, 0.8),
    ("I hate the cold", "climate", 0.8, 0.8),
    ("I love cold winters", "climate", 0.0, 0.1),
    ("I don't want to learn a new language", "english", 0.8, 0.8),
    ("cheap rent", "cost", 0.8, 0.8),
])
def test_factor_understanding(m, text, factor, low, high):
    w = run(m, text)["weights"]
    assert low <= w[factor] <= high, (text, w)


@pytest.mark.parametrize("text,word", [
    ("good helthcare", "healthcare"),
    ("affordible", "affordable"),
    ("permanant residency", "permanent"),
    ("move to Portgual", "portugal"),
])
def test_typos_are_understood(m, text, word):
    r = run(m, text)
    assert r["understood"], text
    assert r["fuzzy"] or "Portugal" in labels(r)


@pytest.mark.parametrize("text,visa_type", [
    ("I'm a digital nomad", "nomad"),
    ("I work remotely for a US company", "nomad"),
    ("I want to do a masters", "study"),
    ("planning to retire early", "passive"),
    ("looking for a golden visa", "investor"),
    ("I want to start a company", "startup"),
    ("my wife is a citizen and I want a spouse visa", "family"),
    ("I'm a nurse", "skilled"),
])
def test_life_situations_set_visa_type(m, text, visa_type):
    assert run(m, text)["profile"].get("visa_type") == visa_type


def test_negated_intent_is_ignored(m):
    assert "visa_type" not in run(m, "I'm not a student")["profile"]
    assert "require_pr" not in run(m, "I don't have kids")["profile"]


@pytest.mark.parametrize("text,kind,amount", [
    ("earning $3k a month", "monthly_income", 3000),
    ("I make 60k a year", "monthly_income", 5000),
    ("$60k/year salary", "monthly_income", 5000),
    ("income of 2,500 usd monthly", "monthly_income", 2500),
    ("Rs 500,000 per month", "monthly_income", 1785),
    ("I have €200,000 to invest", "investment_budget", 216000),
    ("savings of 50k", "investment_budget", 50000),
    ("£1 million to invest", "investment_budget", 1270000),
])
def test_money(m, text, kind, amount):
    p = run(m, text)["profile"]
    assert p.get(kind) == pytest.approx(amount, rel=0.01), (text, p)


def test_ages_and_counts_are_not_money(m):
    p = run(m, "I'm 30 years old and want 5 countries")["profile"]
    assert "monthly_income" not in p and "investment_budget" not in p


@pytest.mark.parametrize("text,code", [
    ("I'm Pakistani", "PAK"),
    ("I am from India", "IND"),
    ("German passport holder", "DEU"),
    ("I'm a Nigerian living in Dubai", "NGA"),
    ("born in Brazil", "BRA"),
    ("I live in Karachi", "PAK"),          # weak origin, from a city
])
def test_nationality(m, text, code):
    assert run(m, text)["profile"].get("nationality") == code


def test_want_to_live_in_is_a_destination(m):
    r = run(m, "I want to live in Canada")
    assert "nationality" not in r["profile"]
    assert r["countries"] == ["Canada"]


def test_speak_german_is_not_a_passport(m):
    assert "nationality" not in run(m, "I speak German")["profile"]


def test_country_roles(m):
    r = run(m, "somewhere like Portugal but cheaper, not Spain")
    assert r["similar_to"] == "Portugal"
    assert r["exclude"] == ["Spain"]
    assert run(m, "compare Germany or Netherlands")["countries"] == ["Germany", "Netherlands"]
    assert run(m, "beaches but not the US")["exclude"] == ["United States"]
    assert run(m, "help us find a country")["exclude"] == []      # lowercase "us" isn't the USA
    assert run(m, "somewhere like Bali")["similar_to"] == "Indonesia"


def test_region_and_top_n(m):
    r = run(m, "top 3 nomad visas in southeast asia")
    assert r["region"] == "Asia" and r["top_n"] == 3


def test_easy_visa_and_qualify(m):
    p = run(m, "easiest visa I can get")["profile"]
    assert p["max_difficulty"] == "Easy" and p["only_qualifying"] is True


def test_nothing_understood(m):
    r = run(m, "hello there")
    assert not r["understood"] and r["weights"] is None


@pytest.mark.parametrize("query,expect", [
    ("golden visa", "Golden Visa"),
    ("blue card", "EU Blue Card"),
    ("express entry", "Express Entry (FSW)"),
    ("D7", "D7 Passive Income Visa"),
    ("nomad visa", "Digital Nomad Visa"),
    ("H-1B", "H-1B Specialty Worker"),
])
def test_keyword_search_finds_visas(query, expect):
    names = [h["name"] for h in search.keyword_search(query)]
    assert expect in names, (query, names)


def test_keyword_search_respects_region_and_country():
    assert all(h["country"] in ("Japan", "Malaysia", "Indonesia", "South Korea", "Thailand")
               for h in search.keyword_search("nomad visa", region="Asia"))
    assert [h["name"] for h in search.keyword_search("blue card", countries=["DEU"])] == ["EU Blue Card"]


def test_keyword_search_ignores_preference_words():
    assert search.keyword_search("I want somewhere safe with good healthcare") == []


# ---------------- API ----------------

def test_api_search(client):
    d = client.post("/api/search", json={"prompt": "somewhere like Portugal but cheaper, not Spain"}).get_json()
    assert d["interpretation"]["similar_to"] == "Portugal"
    assert d["similar"] and "Spain" not in d["similar"]
    assert client.post("/api/search", json={}).status_code == 400
    assert client.post("/api/search", json={"prompt": "x" * 2000}).status_code == 400


def test_exclude_countries_filter(client, weights):
    d = client.post("/api/score", json={"weights": weights,
                                        "profile": {"exclude_countries": ["USA", "Canada"]}}).get_json()
    names = {c["country_name"] for c in d["all"]}
    assert "United States" not in names and "Canada" not in names and len(names) == 64
    assert d["counts"]["hidden_by_filters"] == 0
    assert client.post("/api/score", json={"profile": {"exclude_countries": ["Atlantis"]}}).status_code == 400


def test_api_search_with_llm(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    reply = {"weights": {"safety": 1, "climate": 0.9}, "region": "Europe", "nationality": "Pakistan",
             "monthly_income_usd": 3000, "visa_type": "nomad", "exclude": ["Spain"], "summary": "Safe, warm Europe."}
    monkeypatch.setattr(assistant, "ask_llm_raw", lambda *a, **k: "Here you go: " + json.dumps(reply))
    i = client.post("/api/search", json={"prompt": "anything"}).get_json()["interpretation"]
    assert i["source"] == "llm"
    assert i["profile"]["nationality"] == "PAK" and i["profile"]["visa_type"] == "nomad"
    assert i["weights"]["safety"] == 1 and i["weights"]["salary"] == 0.25
    assert i["exclude"] == ["Spain"] and i["region"] == "Europe"


def test_api_search_llm_failure_falls_back(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    def boom(*a, **k):
        raise assistant.urllib.error.URLError("offline")

    monkeypatch.setattr(assistant, "ask_llm_raw", boom)
    i = client.post("/api/search", json={"prompt": "cheap and sunny"}).get_json()["interpretation"]
    assert i["source"] == "rules" and "warning" in i
    assert i["weights"]["cost"] >= 0.8


# ---------------- regressions from reviewing real prompts ----------------

def test_exclusion_lists(m):
    assert run(m, "anywhere but Russia or China")["exclude"] == ["Russia", "China"]
    assert run(m, "not the US or Canada")["exclude"] == ["United States", "Canada"]


def test_demonym_as_adjective_is_not_a_passport(m):
    r = run(m, "Japanese healthcare is great but I need english")
    assert "nationality" not in r["profile"]
    assert run(m, "UK or Ireland? I'm an Indian nurse")["profile"]["nationality"] == "IND"


def test_doctor_is_a_profession(m):
    r = run(m, "I'm a doctor from Nigeria, want to work in UK")
    assert r["profile"]["visa_type"] == "skilled" and r["profile"]["nationality"] == "NGA"
    assert run(m, "good doctors")["weights"]["healthcare"] >= 0.8


def test_deprioritising_is_local(m):
    w = run(m, "I don't mind high costs if salaries are high")["weights"]
    assert w["cost"] <= 0.05 and w["salary"] >= 0.8
    w = run(m, "I don't care about salary or climate")["weights"]
    assert w["salary"] <= 0.05 and w["climate"] <= 0.05


def test_rupee_amounts(m):
    assert run(m, "from India, budget 20 lakh")["profile"]["investment_budget"] == 24000
    assert run(m, "I'm Pakistani, 5 lakh to invest")["profile"]["investment_budget"] == 1785
    assert run(m, "I earn 1.5 lakh rupees a month in Mumbai")["profile"]["monthly_income"] == 1800


def test_money_words_after_amount_are_not_preferences(m):
    r = run(m, "$60k/year salary")
    assert r["weights"] is None and r["profile"]["monthly_income"] == 5000
    assert run(m, "my savings are $250,000")["unmatched"] == []


def test_top_n_alone_is_understood(m):
    r = run(m, "give me 7 options")
    assert r["top_n"] == 7 and r["understood"]


def test_keyword_search_skips_negated_and_non_visa_intents():
    assert search.keyword_search("I'm not a student") == []
    assert search.keyword_search("a quiet safe place with good hospitals for my family") == []
    assert search.keyword_search("I need a job offer route") == []


def test_savings_after_an_income_phrase_stay_savings(m):
    r = search.interpret_rules("I'm Pakistani earning $2,000 a month with $50k savings, safe and English-speaking", m)
    assert r["profile"]["nationality"] == "PAK"
    assert r["profile"]["monthly_income"] == 2000
    assert r["profile"]["investment_budget"] == 50000


def test_demonym_before_a_comma_is_still_a_passport(m):
    assert search.interpret_rules("I'm Pakistani, safe", m)["profile"].get("nationality") == "PAK"
    assert search.interpret_rules("I'm Indian, English-speaking please", m)["profile"].get("nationality") == "IND"


def test_adjacent_language_words_still_mean_a_language(m):
    for text in ["a Spanish-speaking country", "I speak fluent Spanish"]:
        r = search.interpret_rules(text, m)
        assert "nationality" not in r["profile"] and not r["countries"]
