"""Ranking confidence: Monte Carlo over weights and data quality."""

import numpy as np
import pytest

import confidence
from app import app
from factors import FACTOR_KEYS


@pytest.fixture()
def client():
    return app.test_client()


def test_mulberry32_matches_the_reference_sequence():
    # First values of mulberry32(42) as produced by the canonical JavaScript implementation.
    u = confidence.mulberry32(42, 3)
    assert np.allclose(u, [0.6011037519201636, 0.44829055899754167, 0.8524657934904099])
    assert ((u >= 0) & (u < 1)).all()


def test_results_are_deterministic(client):
    body = {"weights": {k: 0.5 for k in FACTOR_KEYS}}
    a = client.post("/api/confidence", json=body).get_json()
    b = client.post("/api/confidence", json=body).get_json()
    assert a == b


def test_probabilities_and_ranges_are_consistent(client):
    d = client.post("/api/confidence", json={"top_n": 5}).get_json()
    assert d["samples"] == confidence.SAMPLES
    assert sum(c["p_first"] for c in d["countries"]) <= 1 + 1e-9
    for c in d["countries"]:
        assert 0 <= c["p_first"] <= c["p_top"] <= 1
        assert c["rank_lo"] <= c["rank_median"] <= c["rank_hi"]
        assert c["rank_lo"] <= c["rank"] + 3          # the point estimate sits inside or near its range


def test_a_dominant_country_is_called_clear():
    rows = [{"country_name": "A", "country_code": "AAA", **{c: 0.95 for c in _cols()}},
            {"country_name": "B", "country_code": "BBB", **{c: 0.40 for c in _cols()}}]
    for r in rows:
        r["cost_of_living"] = 1 - r["cost_of_living"]
    d = confidence.simulate(rows, {k: 0.5 for k in FACTOR_KEYS}, top_n=2)
    assert d["verdict"]["level"] == "clear" and d["countries"][0]["p_first"] == 1.0


def test_identical_countries_are_a_tie():
    rows = [{"country_name": n, "country_code": c, **{col: 0.6 for col in _cols()}}
            for n, c in (("A", "AAA"), ("B", "BBB"))]
    d = confidence.simulate(rows, {k: 0.5 for k in FACTOR_KEYS}, top_n=2)
    assert d["verdict"]["level"] in ("likely", "close")
    assert d["ties"] and 0.35 <= d["ties"][0]["p_a_ahead"] <= 0.65


def test_reliability_reflects_provenance():
    w = {k: (1.0 if k == "healthcare" else 0.0) for k in FACTOR_KEYS}
    hk = confidence.reliability("HKG", w)          # Hong Kong's healthcare score is ML-imputed
    de = confidence.reliability("DEU", w)
    assert de["value"] > hk["value"]
    assert any("ML-imputed" in x["text"] for x in hk["weak"])


def test_editorial_pr_lowers_reliability_only_when_pr_matters():
    only_pr = {k: (1.0 if k == "pr" else 0.0) for k in FACTOR_KEYS}
    no_pr = {k: (0.0 if k == "pr" else 1.0) for k in FACTOR_KEYS}
    assert confidence.reliability("CAN", only_pr)["level"] == "Low"
    assert confidence.reliability("CAN", no_pr)["value"] > confidence.reliability("CAN", only_pr)["value"]


def _cols():
    from factors import FACTORS
    return [FACTORS[k]["col"] for k in FACTOR_KEYS]
