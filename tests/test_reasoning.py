from data import load_countries
from factors import FACTOR_KEYS
from reasoning import generate_explanation, generate_tradeoffs, generate_user_insight
from scoring import compute_scores


def _row(name, weights):
    scored = compute_scores(load_countries(), weights)
    return scored[scored["country_name"] == name].iloc[0]


def test_low_ranked_country_is_not_described_as_ranking_highly(weights):
    """Regression: every country used to 'rank highly'."""
    text = generate_explanation(_row("Nigeria", weights), weights, rank=66, total=66)
    assert "ranks highly" not in text
    assert "#66 of 66" in text
    assert "mainly because" in text


def test_top_ranked_country_explanation(weights):
    text = generate_explanation(_row("Australia", weights), weights, rank=1, total=66)
    assert text.startswith("Australia ranks #1 of 66")


def test_mixed_match_wording(weights):
    text = generate_explanation(_row("Spain", weights), weights, rank=30, total=66)
    assert "mixed match" in text


def test_tradeoffs_always_nonempty(weights):
    for name in load_countries()["country_name"]:
        assert generate_tradeoffs(_row(name, weights))


def test_rent_tradeoff_uses_real_figures(weights):
    text = " ".join(generate_tradeoffs(_row("Nigeria", weights)))
    assert "$" in text


def test_user_insight_variants():
    assert "equally" in generate_user_insight({k: 0.5 for k in FACTOR_KEYS})
    assert "zero" in generate_user_insight({k: 0 for k in FACTOR_KEYS})
    w = {k: 0.1 for k in FACTOR_KEYS} | {"safety": 1.0}
    assert generate_user_insight(w) == "You prioritize personal safety and security above other factors."
