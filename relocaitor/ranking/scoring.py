"""
relocaitor/ranking/scoring.py — Weighted multi-criteria scoring, score breakdowns and similarity.

score_i = Σ_f (w_f / Σw) × value_f        (cost is inverted: 1 - cost)

`raw_score` is that weighted average, an absolute number in [0, 1].
`score` is raw_score min-max normalized ACROSS ALL 66 COUNTRIES, so the scale
doesn't collapse when you filter to a small region (previously, with Oceania
selected, whichever of Australia/New Zealand came second got 0% and "Low").
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from relocaitor.ranking.factors import FACTORS, FACTOR_KEYS

# Features used in similarity calculations (all normalized to [0, 1])
SIMILARITY_FEATURES = [
    "average_salary", "cost_of_living", "pr_ease",
    "job_market", "language_barrier",
    "climate", "safety", "healthcare", "english", "internet",
]


def effective_weights(weights: dict) -> dict:
    """Known factors only; if every weight is 0, fall back to equal weights."""
    used = {k: max(0.0, float(weights.get(k, 0.0))) for k in FACTOR_KEYS}
    if sum(used.values()) == 0:
        used = {k: 1.0 for k in FACTOR_KEYS}
    return used


def factor_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """One column per factor key, oriented so higher is always better."""
    out = pd.DataFrame(index=df.index)
    for key, meta in FACTORS.items():
        col = df[meta["col"]].astype(float)
        out[key] = (1.0 - col) if meta["invert"] else col
    return out


def exact_raw(df: pd.DataFrame, weights: dict) -> pd.Series:
    """
    Unrounded weighted score, summed factor by factor in a fixed order. Used for
    ranking, so ties break identically here and in the JavaScript port.
    """
    used = effective_weights(weights)
    total = sum(used.values())
    values = factor_matrix(df)
    raw = pd.Series(0.0, index=df.index)
    for k in FACTOR_KEYS:
        raw = raw + (used[k] / total) * values[k]
    return raw


def compute_scores(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """
    Adds raw_score, score, score_category and contributions to a copy of df.

    contributions[f] = (w_f / Σw) × value_f, so the contributions of a country sum
    to its raw_score. That's what the UI's breakdown bar shows.

    Pass the FULL dataset here and filter afterwards; normalization is relative
    to whatever rows you pass in.
    """
    result = df.copy()
    used = effective_weights(weights)
    total = sum(used.values())
    shares = {k: w / total for k, w in used.items()}

    values = factor_matrix(result)
    contrib = values.mul(pd.Series(shares))
    raw = exact_raw(result, weights)

    result["raw_score"] = raw.round(4)
    r_min, r_max = raw.min(), raw.max()
    if r_max - r_min < 1e-9:
        result["score"] = 1.0
    else:
        result["score"] = ((raw - r_min) / (r_max - r_min)).round(4)
    result["score_category"] = result["score"].apply(categorize)
    result["contributions"] = [
        {k: round(float(v), 4) for k, v in row.items()} for _, row in contrib.iterrows()
    ]
    return result


def categorize(score: float) -> str:
    if score >= 0.66:
        return "High"
    if score >= 0.33:
        return "Medium"
    return "Low"


def rank_top_n(scored_df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    return scored_df.sort_values("score", ascending=False, kind="stable").head(n).reset_index(drop=True)


def find_similar_countries(df: pd.DataFrame, target_country: str, n: int = 3) -> pd.DataFrame:
    """
    Nearest neighbours. Uses the pipeline's ML country map (z-scored factors) when
    present; otherwise Euclidean distance over the raw normalized metrics.
    """
    if target_country not in df["country_name"].values:
        return df.iloc[0:0]
    from relocaitor.datasets import get_country_map
    cmap = get_country_map().get("countries", {})
    code = df.loc[df["country_name"] == target_country, "country_code"].iloc[0]
    if code in cmap:
        entry = cmap[code]
        rows = []
        for nb, d in zip(entry["neighbors"], entry["distances"]):
            hit = df[df["country_code"] == nb]
            if len(hit):
                rows.append(hit.iloc[0].to_dict() | {"distance": d})
            if len(rows) == n:
                break
        return pd.DataFrame(rows).reset_index(drop=True) if rows else df.iloc[0:0]

    target = df.loc[df["country_name"] == target_country, SIMILARITY_FEATURES].values[0]
    distances = np.linalg.norm(df[SIMILARITY_FEATURES].values - target, axis=1)

    sim = df.copy()
    sim["distance"] = distances.round(4)
    sim = sim[sim["country_name"] != target_country]
    return sim.sort_values("distance", kind="stable").head(n).reset_index(drop=True)
