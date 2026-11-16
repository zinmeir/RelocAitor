"""
relocaitor/ranking/reasoning.py — Rule-based explanations for country recommendations.

Transparent by design: every sentence comes from a rule you can read below.
(The optional LLM layer lives in assistant.py.)
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from relocaitor.ranking.factors import FACTORS, factor_value


def _quality_word(v: float) -> str:
    if v >= 0.85: return "world-class"
    if v >= 0.7:  return "excellent"
    if v >= 0.55: return "strong"
    if v >= 0.4:  return "moderate"
    if v >= 0.25: return "limited"
    return "weak"


def _join(items: List[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _priorities(weights: Dict[str, float], n: int = 4) -> List[str]:
    ranked = sorted(((k, v) for k, v in weights.items() if k in FACTORS),
                    key=lambda kv: kv[1], reverse=True)
    top = [k for k, v in ranked if v > 0][:n]
    return top or [ranked[0][0]]


def generate_explanation(row: pd.Series, weights: Dict[str, float],
                         rank: Optional[int] = None, total: Optional[int] = None) -> str:
    """
    Explain the country's position. Wording depends on where it actually ranks,
    so a low-ranked country is no longer described as "ranking highly".
    """
    name = row["country_name"]
    prefs = _priorities(weights)

    def phrase(k):
        v = factor_value(row, k)
        return f"{_quality_word(v)} {FACTORS[k]['phrase']} ({v:.2f})"

    strengths = [k for k in prefs if factor_value(row, k) >= 0.55]
    weaknesses = [k for k in prefs if factor_value(row, k) < 0.45]
    pos = f"#{rank} of {total}" if rank and total else None

    top_band = rank is not None and total and (rank <= 5 or rank <= max(1, total // 5))
    low_band = rank is not None and total and rank > total * 0.6

    if top_band or (rank is None and strengths and not weaknesses):
        lead = f"{name} ranks {pos} for you" if pos else f"{name} is a strong match"
        body = _join([phrase(k) for k in (strengths or prefs)[:3]])
        text = f"{lead} because it offers {body}, which lines up with your top priorities."
        if weaknesses:
            text += f" The main drawback is {_join([phrase(k) for k in weaknesses[:1]])}."
        return text

    if low_band:
        lead = f"{name} ranks {pos}" if pos else f"{name} is a weak match"
        if weaknesses:
            text = (f"{lead} mainly because of {_join([phrase(k) for k in weaknesses[:2]])}, "
                    f"which you rated as important.")
        else:
            text = f"{lead}: it doesn't stand out on the factors you weighted most."
        if strengths:
            text += f" On the plus side, it has {_join([phrase(k) for k in strengths[:2]])}."
        return text

    lead = f"{name} ranks {pos}, a mixed match" if pos else f"{name} is a mixed match"
    parts = []
    if strengths:
        parts.append(f"it offers {_join([phrase(k) for k in strengths[:2]])}")
    if weaknesses:
        parts.append(f"it falls short on {_join([phrase(k) for k in weaknesses[:2]])}")
    if not parts:
        parts.append("it is average on most of the factors you care about")
    return f"{lead}: {', but '.join(parts)}."


def generate_tradeoffs(row: pd.Series) -> List[str]:
    """Identify trade-offs across all dimensions, plus a rent-vs-salary check."""
    tradeoffs = []
    s = row["average_salary"]; c = row["cost_of_living"]; p = row["pr_ease"]
    j = row["job_market"]; l = row["language_barrier"]; cl = row["climate"]
    sf = row["safety"]; hc = row["healthcare"]; en = row["english"]; it = row["internet"]

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
        tradeoffs.append("Pleasant climate, but English isn't widely spoken, so expect a language learning curve.")
    if sf >= 0.85 and j <= 0.55:
        tradeoffs.append("Among the safest places in the world, but the job market is somewhat soft.")
    if it >= 0.85 and s <= 0.55:
        tradeoffs.append("Excellent digital infrastructure for a modest salary base.")
    if en >= 0.85 and c >= 0.75:
        tradeoffs.append("Very English-friendly, but with one of the higher costs of living.")

    sal = row.get("salary_usd_month"); rent = row.get("rent_usd_month")
    if sal and rent:
        ratio = rent / sal
        if ratio >= 1.0:
            tradeoffs.append(f"A city-centre 1-bed (~${rent:,.0f}) costs more than the average "
                             f"net salary (~${sal:,.0f}), so living on a local salary is hard. "
                             f"Remote or foreign income helps a lot.")
        elif ratio >= 0.6:
            tradeoffs.append(f"A city-centre 1-bed (~${rent:,.0f}) costs about {ratio:.0%} of the "
                             f"average net salary (~${sal:,.0f}). Local salaries stretch thin, "
                             f"so remote or foreign income helps a lot.")
        elif ratio <= 0.35:
            tradeoffs.append(f"Rent is manageable: a city-centre 1-bed (~${rent:,.0f}) is about "
                             f"{ratio:.0%} of the average net salary (~${sal:,.0f}).")

    if not tradeoffs:
        tradeoffs.append("A relatively balanced profile with no major trade-offs.")
    return tradeoffs


def generate_user_insight(weights: Dict[str, float]) -> str:
    """Summarize the user's priorities in plain language."""
    sorted_prefs = sorted(((k, v) for k, v in weights.items() if k in FACTORS),
                          key=lambda kv: kv[1], reverse=True)
    if not sorted_prefs:
        return "No preferences set."
    values = [v for _, v in sorted_prefs]
    if max(values) == 0:
        return "All sliders are at zero, so every factor is weighted equally."
    if max(values) - min(values) < 0.05:
        return "You weigh every factor about equally. That's a well-rounded search."

    (top_key, top_val), (second_key, second_val) = sorted_prefs[0], sorted_prefs[1]
    d1, d2 = FACTORS[top_key]["descriptor"], FACTORS[second_key]["descriptor"]
    if top_val - second_val < 0.15:
        return f"You value a balance between {d1} and {d2}."
    return f"You prioritize {d1} above other factors."
