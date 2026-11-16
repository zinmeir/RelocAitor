import pytest

import engine
from data import load_countries
from eligibility import Profile
from factors import FACTOR_KEYS
from scoring import categorize, compute_scores, effective_weights, find_similar_countries


def test_scores_are_normalized_globally(weights):
    scored = compute_scores(load_countries(), weights)
    assert scored["score"].max() == pytest.approx(1.0)
    assert scored["score"].min() == pytest.approx(0.0)
    assert scored["raw_score"].between(0, 1).all()


def test_contributions_sum_to_raw_score(weights):
    scored = compute_scores(load_countries(), weights)
    for _, row in scored.iterrows():
        assert sum(row["contributions"].values()) == pytest.approx(row["raw_score"], abs=1e-3)


def test_cost_is_inverted():
    only_cost = {k: 0.0 for k in FACTOR_KEYS} | {"cost": 1.0}
    scored = compute_scores(load_countries(), only_cost).sort_values("raw_score", ascending=False)
    assert scored.iloc[0]["cost_of_living"] == load_countries()["cost_of_living"].min()
    assert scored.iloc[-1]["cost_of_living"] == load_countries()["cost_of_living"].max()


def test_all_zero_weights_fall_back_to_equal():
    w = effective_weights({k: 0 for k in FACTOR_KEYS})
    assert set(w.values()) == {1.0}


def test_small_region_does_not_collapse_to_zero(weights):
    """Regression: with min-max over the region only, #2 in Oceania scored 0% / Low."""
    ranked = engine.rank(weights, "Oceania")
    assert len(ranked) == 2
    assert ranked["score"].min() > 0.5
    assert set(ranked["score_category"]) == {"High"}


def test_categorize_thresholds():
    assert categorize(0.9) == "High"
    assert categorize(0.5) == "Medium"
    assert categorize(0.1) == "Low"


def test_rank_is_sequential(weights):
    ranked = engine.rank(weights, "Europe")
    assert list(ranked["rank"]) == list(range(1, len(ranked) + 1))
    assert (ranked["region"] == "Europe").all()


def test_home_country_excluded(weights):
    ranked = engine.rank(weights, profile=Profile(nationality="CAN"))
    assert "Canada" not in set(ranked["country_name"])
    ranked = engine.rank(weights, profile=Profile(nationality="CAN", exclude_home=False))
    assert "Canada" in set(ranked["country_name"])


def test_hard_filter_reduces_results(weights):
    everyone = engine.rank(weights)
    nomad = engine.rank(weights, profile=Profile(visa_type="nomad"))
    assert 0 < len(nomad) < len(everyone)
    assert (nomad["qualifying_visas"] > 0).all()


def test_similar_countries_excludes_target():
    sim = find_similar_countries(load_countries(), "Germany", n=3)
    assert len(sim) == 3
    assert "Germany" not in set(sim["country_name"])
    assert sim["distance"].is_monotonic_increasing


def test_similar_unknown_country_is_empty():
    assert find_similar_countries(load_countries(), "Atlantis").empty


def test_what_if_only_reports_improvements(weights):
    tips = engine.what_if_country(weights, "All regions", Profile(), "Portugal")
    for t in tips:
        assert t["new_rank"] < t["old_rank"]
        assert "Portugal" in t["text"]


def test_flip_top_changes_leader(weights):
    flip = engine.what_would_flip_top(weights, "All regions", Profile())
    assert flip is not None
    if "new_leader" in flip:
        assert flip["new_leader"] != flip["leader"]
        alt = engine.rank({**weights, flip["factor"]: flip["to"]})
        assert alt.iloc[0]["country_name"] == flip["new_leader"]
