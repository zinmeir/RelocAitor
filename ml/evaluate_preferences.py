"""
evaluate_preferences.py — Does learning from choices actually recover what users want?

Simulation: each synthetic user has hidden "true" weights. They answer
questions noisily (they pick A with probability σ(β_true · w* · (x_A − x_B)),
so close calls are sometimes answered "wrongly"). We then compare how well each
strategy reproduces the ranking the user would have produced with their true weights:

    defaults   no questions; the app's default sliders
    random     N random country pairs, then the same model fit
    active     N questions chosen by the model (what the app does)

Metrics: Spearman rank correlation over all 66 countries, and top-5 overlap
(how many of the user's true top 5 appear in the predicted top 5).

    python -m ml.evaluate_preferences            # writes ml/preference_eval.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from relocaitor.datasets import load_countries            # noqa: E402
from relocaitor.ranking.factors import DEFAULT_WEIGHTS, FACTOR_KEYS  # noqa: E402
from ml import preferences as pref          # noqa: E402
from relocaitor.ranking.scoring import factor_matrix           # noqa: E402

TRUE_BETA = 8.0
OUT = Path(__file__).resolve().parent / "preference_eval.json"


def _rank(v: np.ndarray) -> np.ndarray:
    order = np.argsort(-v, kind="stable")
    r = np.empty(len(v))
    r[order] = np.arange(len(v))
    return r


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(_rank(a), _rank(b))[0, 1])


def top_overlap(a: np.ndarray, b: np.ndarray, k: int = 5) -> int:
    return len(set(np.argsort(-a, kind="stable")[:k]) & set(np.argsort(-b, kind="stable")[:k]))


def sample_user(rng) -> np.ndarray:
    # Most people care a lot about a few things and little about others.
    return rng.uniform(0, 1, len(FACTOR_KEYS)) ** 2


def run_session(X, codes, true_w, n, strategy, rng):
    diffs, outcomes, asked = [], [], set()
    w = np.full(len(FACTOR_KEYS), pref.PRIOR_MEAN)
    for _ in range(n):
        if strategy == "active":
            pair = pref.next_question(X, codes, w, asked)
        else:
            i, j = rng.choice(len(codes), size=2, replace=False)
            pair = (int(i), int(j))
        i, j = pair
        asked.add(frozenset((codes[i], codes[j])))
        d = X[i] - X[j]
        chose_a = rng.random() < 1 / (1 + np.exp(-TRUE_BETA * d.dot(true_w)))
        diffs.append(d)
        outcomes.append(1.0 if chose_a else 0.0)
        w = pref.fit(np.array(diffs), np.array(outcomes))
    return w


def evaluate(n_users: int = 200, question_counts=(4, 8, 12), seed: int = 7) -> dict:
    df = load_countries()
    X = factor_matrix(df)[FACTOR_KEYS].to_numpy()
    codes = list(df["country_code"])
    default_w = np.array([DEFAULT_WEIGHTS[k] for k in FACTOR_KEYS])
    rng = np.random.default_rng(seed)
    users = [sample_user(rng) for _ in range(n_users)]

    results = {"n_users": n_users, "metric_notes": {
        "spearman": "rank correlation with the user's true ranking of all countries (1 = identical)",
        "top5": "how many of the user's true top-5 countries appear in the predicted top 5 (0–5)"}}
    base = [(spearman(X.dot(default_w), X.dot(u)), top_overlap(X.dot(default_w), X.dot(u))) for u in users]
    results["defaults"] = {"spearman": round(float(np.mean([b[0] for b in base])), 3),
                           "top5": round(float(np.mean([b[1] for b in base])), 2)}
    for strategy in ("random", "active"):
        results[strategy] = {}
        for n in question_counts:
            srng = np.random.default_rng(seed + n)
            scores = []
            for u in users:
                w = run_session(X, codes, u, n, strategy, srng)
                scores.append((spearman(X.dot(w), X.dot(u)), top_overlap(X.dot(w), X.dot(u))))
            results[strategy][str(n)] = {"spearman": round(float(np.mean([s[0] for s in scores])), 3),
                                         "top5": round(float(np.mean([s[1] for s in scores])), 2)}
    return results


if __name__ == "__main__":
    res = evaluate()
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
