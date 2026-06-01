"""
scoring.py — Weighted multi-criteria scoring + similarity search.

Factors:
  salary, cost (inverted), pr_ease, job_market,
  climate, safety, healthcare, english, internet
"""

from __future__ import annotations
import numpy as np
import pandas as pd


# Features used in similarity calculations
SIMILARITY_FEATURES = [
    "average_salary", "cost_of_living", "pr_ease",
    "job_market", "language_barrier",
    "climate", "safety", "healthcare", "english", "internet",
]

# All scorable factors and how each maps to a country column.
# "invert" means the user wants LOW values (currently only cost).
FACTORS = {
    "salary":     {"col": "average_salary", "invert": False},
    "cost":       {"col": "cost_of_living", "invert": True},
    "pr":         {"col": "pr_ease",        "invert": False},
    "job":        {"col": "job_market",     "invert": False},
    "climate":    {"col": "climate",        "invert": False},
    "safety":     {"col": "safety",         "invert": False},
    "healthcare": {"col": "healthcare",     "invert": False},
    "english":    {"col": "english",        "invert": False},
    "internet":   {"col": "internet",       "invert": False},
}


def compute_scores(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """
    Weighted score across all factors. Weights dict keys correspond to FACTORS.
    Missing keys default to 0. Final score normalized to [0, 1].
    """
    result = df.copy()

    # Filter to known factors with positive weight
    used = {k: float(weights.get(k, 0.0)) for k in FACTORS}
    total_w = sum(used.values())
    if total_w == 0:
        used = {k: 1.0 for k in FACTORS}
        total_w = float(len(FACTORS))

    raw = pd.Series(0.0, index=result.index)
    for key, w in used.items():
        if w == 0:
            continue
        meta = FACTORS[key]
        col_vals = result[meta["col"]]
        contribution = (1.0 - col_vals) if meta["invert"] else col_vals
        raw = raw + (w / total_w) * contribution

    # Min-max normalize for display
    r_min, r_max = raw.min(), raw.max()
    if r_max - r_min < 1e-9:
        result["score"] = 1.0
    else:
        result["score"] = (raw - r_min) / (r_max - r_min)

    result["score_category"] = result["score"].apply(_categorize)
    return result


def _categorize(score: float) -> str:
    if score >= 0.66: return "High"
    if score >= 0.33: return "Medium"
    return "Low"


def rank_top_n(scored_df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    return scored_df.sort_values("score", ascending=False).head(n).reset_index(drop=True)


def find_similar_countries(
    scored_df: pd.DataFrame, target_country: str, n: int = 2
) -> pd.DataFrame:
    if target_country not in scored_df["country_name"].values:
        return scored_df.iloc[0:0]

    target = scored_df.loc[
        scored_df["country_name"] == target_country, SIMILARITY_FEATURES
    ].values[0]

    matrix = scored_df[SIMILARITY_FEATURES].values
    distances = np.linalg.norm(matrix - target, axis=1)

    sim = scored_df.copy()
    sim["distance"] = distances
    sim = sim[sim["country_name"] != target_country]
    return sim.sort_values("distance").head(n).reset_index(drop=True)
