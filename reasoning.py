"""
reasoning.py — Rule-based AI reasoning for country recommendations.
Supports all 9 weighted factors.
"""

from typing import Dict, List
import pandas as pd


# Maps weight key -> (human label, country DataFrame column, invert?)
FACTOR_LABELS = {
    "salary":     ("salary potential",         "average_salary",  False),
    "cost":       ("affordability",            "cost_of_living",  True),
    "pr":         ("PR accessibility",         "pr_ease",         False),
    "job":        ("job market strength",      "job_market",      False),
    "climate":    ("climate quality",          "climate",         False),
    "safety":     ("personal safety",          "safety",          False),
    "healthcare": ("healthcare quality",       "healthcare",      False),
    "english":    ("English proficiency",      "english",         False),
    "internet":   ("internet infrastructure",  "internet",        False),
}


def generate_explanation(country_row: pd.Series, weights: Dict[str, float]) -> str:
    """Pick the user's top 2-3 priorities and explain why this country fits."""
    name = country_row["country_name"]

    sorted_prefs = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    top_prefs = [k for k, v in sorted_prefs if v > 0][:3] or [sorted_prefs[0][0]]

    highlights = []
    for key in top_prefs:
        if key not in FACTOR_LABELS:
            continue
        label, col, invert = FACTOR_LABELS[key]
        raw = country_row[col]
        value = (1.0 - raw) if invert else raw
        highlights.append(f"{_quality_word(value)} {label} ({value:.2f})")

    if len(highlights) > 1:
        joined = ", ".join(highlights[:-1]) + ", and " + highlights[-1]
    else:
        joined = highlights[0]

    return f"{name} ranks highly because it offers {joined}, which aligns with the priorities you set."


def generate_tradeoffs(country_row: pd.Series) -> List[str]:
    """Identify trade-offs across all dimensions."""
    tradeoffs = []
    s = country_row["average_salary"]
    c = country_row["cost_of_living"]
    p = country_row["pr_ease"]
    j = country_row["job_market"]
    l = country_row["language_barrier"]
    cl = country_row["climate"]
    sf = country_row["safety"]
    hc = country_row["healthcare"]
    en = country_row["english"]
    it = country_row["internet"]

    if s >= 0.7 and c >= 0.75:
        tradeoffs.append("High earning potential, but a correspondingly high cost of living.")
    if s >= 0.7 and p <= 0.45:
        tradeoffs.append("Strong salaries, but permanent residency is relatively difficult to obtain.")
    if p >= 0.75 and s <= 0.55:
        tradeoffs.append("Very accessible PR pathway, but average salaries are on the lower side.")
    if j >= 0.75 and l >= 0.6:
        tradeoffs.append("Robust job market, though a significant language barrier may limit opportunities.")
    if c <= 0.45 and j <= 0.55:
        tradeoffs.append("Affordable to live in, but the job market is less competitive.")
    if hc >= 0.85 and c >= 0.75:
        tradeoffs.append("Excellent healthcare, though the high cost of living offsets some of that benefit.")
    if cl >= 0.75 and en <= 0.4:
        tradeoffs.append("Pleasant climate, but English isn't widely spoken — expect a language curve.")
    if sf >= 0.85 and j <= 0.55:
        tradeoffs.append("Among the safest places in the world, but the job market is somewhat soft.")
    if it >= 0.85 and s <= 0.55:
        tradeoffs.append("Excellent digital infrastructure for a modest salary base.")
    if en >= 0.85 and c >= 0.75:
        tradeoffs.append("Very English-friendly, but with one of the higher costs of living.")

    if not tradeoffs:
        tradeoffs.append("A relatively balanced profile with no major trade-offs.")
    return tradeoffs


def generate_user_insight(weights: Dict[str, float]) -> str:
    """Summarize the user's priorities in plain language."""
    sorted_prefs = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    if not sorted_prefs:
        return "No preferences set."

    top_key, top_val = sorted_prefs[0]
    second_key, second_val = sorted_prefs[1] if len(sorted_prefs) > 1 else (top_key, top_val)

    descriptors = {
        "salary":     "maximizing income",
        "cost":       "keeping living costs manageable",
        "pr":         "long-term stability and permanent residency",
        "job":        "career opportunities and a strong job market",
        "climate":    "a pleasant climate and natural environment",
        "safety":     "personal safety and security",
        "healthcare": "world-class healthcare access",
        "english":    "an English-speaking environment",
        "internet":   "fast, reliable digital infrastructure",
    }

    if top_key not in descriptors:
        return "You have varied priorities across multiple factors."

    if top_val - second_val < 0.15 and second_key in descriptors:
        return f"You value a balance between {descriptors[top_key]} and {descriptors[second_key]}."
    return f"You prioritize {descriptors[top_key]} above other factors."


def _quality_word(v: float) -> str:
    if v >= 0.85: return "world-class"
    if v >= 0.7:  return "excellent"
    if v >= 0.55: return "strong"
    if v >= 0.4:  return "moderate"
    if v >= 0.25: return "limited"
    return "weak"
