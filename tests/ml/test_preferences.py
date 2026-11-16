"""Preference learning from pairwise choices."""

import numpy as np
import pytest

from relocaitor.datasets import load_countries
from relocaitor.ranking.factors import FACTOR_KEYS
from ml import preferences as pref
from relocaitor.ranking.scoring import factor_matrix


@pytest.fixture(scope="module")
def X():
    return factor_matrix(load_countries())[FACTOR_KEYS].to_numpy()


def test_fit_without_answers_is_neutral():
    w = pref.fit(np.zeros((0, 9)), np.zeros(0))
    assert np.allclose(w, pref.PRIOR_MEAN)


def test_fit_recovers_the_factor_driving_choices(X):
    rng = np.random.default_rng(1)
    true = np.zeros(9)
    true[FACTOR_KEYS.index("safety")] = 1.0
    diffs, y = [], []
    for _ in range(25):
        i, j = rng.choice(len(X), 2, replace=False)
        diffs.append(X[i] - X[j])
        y.append(1.0 if (X[i] - X[j]).dot(true) > 0 else 0.0)
    w = pref.fit(np.array(diffs), np.array(y))
    assert np.argmax(w) == FACTOR_KEYS.index("safety")
    assert ((w >= 0) & (w <= 1)).all()
    assert pref.consistency(np.array(diffs), np.array(y), w) >= 0.9


def test_fit_is_deterministic(X):
    d = np.array([X[0] - X[5], X[3] - X[9]])
    y = np.array([1.0, 0.0])
    assert np.array_equal(pref.fit(d, y), pref.fit(d, y))


def test_next_question_avoids_repeats(X):
    codes = list(load_countries()["country_code"])
    w = np.full(9, 0.5)
    i, j = pref.next_question(X, codes, w, set())
    i2, j2 = pref.next_question(X, codes, w, {frozenset((codes[i], codes[j]))})
    assert {i, j} != {i2, j2}


def test_slider_weights_scale_to_one():
    s = pref.to_slider_weights(np.array([0.2, 0.4, 0, 0, 0, 0, 0, 0, 0.1]))
    assert s["cost"] == 1.0 and s["salary"] == 0.5 and all(v * 20 == round(v * 20) for v in s.values())


def test_active_learning_beats_defaults_and_random():
    """Small, seeded version of ml/evaluate_preferences.py (the README reports the full run)."""
    from ml.evaluate_preferences import evaluate
    r = evaluate(n_users=40, question_counts=(8,))
    assert r["active"]["8"]["spearman"] > r["defaults"]["spearman"] + 0.05
    assert r["active"]["8"]["spearman"] >= r["random"]["8"]["spearman"]
    assert r["active"]["8"]["top5"] > r["defaults"]["top5"]


# ---------------- API ----------------

def test_api_session(client):
    answers = []
    for _ in range(8):
        d = client.post("/api/preferences", json={"answers": answers}).get_json()
        assert not d["done"] and d["question"]["a"]["name"] != d["question"]["b"]["name"]
        q = d["question"]
        better = "a" if q["a"]["values"]["safety"] >= q["b"]["values"]["safety"] else "b"
        answers.append({"a": q["a"]["name"], "b": q["b"]["name"], "choice": better})
    d = client.post("/api/preferences", json={"answers": answers}).get_json()
    assert d["done"] and d["question"] is None
    assert max(d["weights"], key=d["weights"].get) == "safety"
    assert d["consistency"] >= 0.75
    pairs = {frozenset((a["a"], a["b"])) for a in answers}
    assert len(pairs) == 8                                     # never asks the same pair twice


def test_api_skip_and_validation(client):
    d = client.post("/api/preferences", json={"answers": [{"a": "Spain", "b": "Japan", "choice": "skip"}]}).get_json()
    assert d["consistency"] is None and d["answered"] == 1
    assert client.post("/api/preferences", json={"answers": [{"a": "Atlantis", "b": "Spain", "choice": "a"}]}).status_code == 400
    assert client.post("/api/preferences", json={"answers": [{"a": "Spain", "b": "Japan", "choice": "maybe"}]}).status_code == 400
    assert client.post("/api/preferences", json={"answers": "nope"}).status_code == 400
