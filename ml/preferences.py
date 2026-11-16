"""
preferences.py — Learn a user's factor weights from pairwise choices.

Model (Bradley–Terry with a linear utility):
    utility(country) = w · x            x = the country's 9 factor values (0–1, higher = better)
    P(user prefers A over B) = σ(β · w · (x_A − x_B))

Given the answers so far, w is the MAP estimate under a Gaussian prior centred
on neutral weights, constrained to [0, 1] (projected gradient descent, fixed
iterations, so results are deterministic and reproducible in the JavaScript port).

Question selection (active learning): among realistic candidates (the top
countries under the current estimate), ask the pair the model is most unsure
about and that differs most, i.e. maximise p(1−p)·‖x_A − x_B‖².

Pure numpy at runtime; evaluated by simulation in ml/evaluate_preferences.py.
"""

from __future__ import annotations

from itertools import combinations
from typing import Optional

import numpy as np

from factors import FACTOR_KEYS, FACTORS

BETA = 6.0            # sharpness of choices
PRIOR_MEAN = 0.5      # neutral weight for every factor
PRIOR_STRENGTH = 0.5  # λ in the L2 prior
ITERATIONS = 600
CANDIDATES = 16       # questions are drawn from the top-N countries under the current estimate
DEFAULT_QUESTIONS = 8

WORDS = {   # factor -> (more, less) for "how these two differ"
    "salary": ("higher salaries", "lower salaries"), "cost": ("cheaper living", "more expensive"),
    "pr": ("easier PR", "harder PR"), "job": ("stronger job market", "weaker job market"),
    "climate": ("warmer", "cooler"), "safety": ("safer", "less safe"),
    "healthcare": ("better healthcare", "weaker healthcare"), "english": ("more English spoken", "less English"),
    "internet": ("more people online", "fewer people online"),
}


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-z))


def fit(diffs: np.ndarray, outcomes: np.ndarray) -> np.ndarray:
    """
    diffs: (n, 9) rows x_A − x_B for each answered question.
    outcomes: (n,) 1 if A was chosen, 0 if B.
    Returns w in [0, 1]^9 (MAP estimate).
    """
    w = np.full(len(FACTOR_KEYS), PRIOR_MEAN)
    if len(diffs) == 0:
        return w
    # Step = 1/L, where L bounds the gradient's Lipschitz constant (σ' ≤ 1/4, ‖D‖₂² ≤ ‖D‖_F²):
    # guarantees steady convergence however many answers there are.
    lipschitz = BETA * BETA * 0.25 * float((diffs * diffs).sum()) + 2 * PRIOR_STRENGTH
    step = 1.0 / lipschitz
    for _ in range(ITERATIONS):
        p = sigmoid(BETA * diffs.dot(w))
        grad = -BETA * diffs.T.dot(outcomes - p) + 2 * PRIOR_STRENGTH * (w - PRIOR_MEAN)
        w = np.clip(w - step * grad, 0.0, 1.0)
    return w


def to_slider_weights(w: np.ndarray) -> dict:
    """Rescale so the top factor is 1.0 and round to the sliders' 0.05 steps."""
    top = float(w.max()) or 1.0
    return {k: round(round(float(v) / top * 20) / 20, 2) for k, v in zip(FACTOR_KEYS, w)}


def _pair_score(wv: np.ndarray, d: np.ndarray) -> float:
    p = float(sigmoid(BETA * d.dot(wv)))
    return round(p * (1 - p) * float(d.dot(d)), 9)


def next_question(X: np.ndarray, codes: list, w: np.ndarray, asked: set) -> Optional[tuple]:
    """Index pair (i, j) of the most informative unasked pair among the current top candidates."""
    utility = X.dot(w)
    order = sorted(range(len(codes)), key=lambda i: (-round(float(utility[i]), 9), codes[i]))
    pool = order[:CANDIDATES]
    best, best_score = None, -1.0
    for i, j in combinations(sorted(pool, key=lambda k: codes[k]), 2):
        if frozenset((codes[i], codes[j])) in asked:
            continue
        s = _pair_score(w, X[i] - X[j])
        if s > best_score:
            best, best_score = (i, j), s
    return best


def describe_difference(x_a: np.ndarray, x_b: np.ndarray, name_a: str, name_b: str, limit: int = 3) -> list:
    d = x_a - x_b
    out = []
    for k in np.argsort(-np.abs(d), kind="stable")[:limit]:
        if abs(d[k]) < 0.1:
            break
        key = FACTOR_KEYS[k]
        more, _ = WORDS[key]
        winner = name_a if d[k] > 0 else name_b
        out.append({"factor": key, "text": f"{more[0].upper()}{more[1:]} in {winner}", "gap": round(float(abs(d[k])), 2)})
    return out


def consistency(diffs: np.ndarray, outcomes: np.ndarray, w: np.ndarray) -> Optional[float]:
    """Share of the user's answers the learned weights reproduce (None before any answer)."""
    if len(diffs) == 0:
        return None
    pred = (diffs.dot(w) > 0).astype(float)
    return round(float((pred == outcomes).mean()), 2)


def factor_labels() -> dict:
    return {k: FACTORS[k]["label"] for k in FACTOR_KEYS}
