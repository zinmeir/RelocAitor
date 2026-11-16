"""
engine.py — Puts data, scoring and eligibility together.

    rank(weights, region, profile) -> ranked DataFrame of countries that pass
                                      the region + hard filters

Everything that needs "where does country X rank for this user?" (the API,
what-if analysis, comparisons, the assistant) goes through here so they all
agree.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from data import load_countries
from eligibility import Profile
from factors import FACTORS, FACTOR_KEYS
from scoring import compute_scores, exact_raw
from visas import visas_for_profile

ALL_REGIONS = "All regions"


def qualification_table(profile: Profile, codes) -> dict:
    """{country_code: visas_for_profile(...)}. Independent of weights, so compute once."""
    return {code: visas_for_profile(code, profile) for code in codes}


def rank(weights: dict, region: Optional[str] = ALL_REGIONS,
         profile: Optional[Profile] = None, qual: Optional[dict] = None) -> pd.DataFrame:
    """
    Score all countries, then drop those excluded by region / home country /
    hard visa filters, and add `rank` (1 = best) within what's left.
    `global_rank` is the rank among all 66 countries regardless of filters.
    """
    profile = profile or Profile()
    df = load_countries()
    scored = compute_scores(df, weights)
    # Stable sort on a rounded key so countries with equal scores keep dataset order
    # (deterministic ties, and identical results on every platform).
    scored["_key"] = exact_raw(df, weights).round(6)
    scored = (scored.sort_values("_key", ascending=False, kind="stable")
              .drop(columns="_key").reset_index(drop=True))
    scored["global_rank"] = range(1, len(scored) + 1)

    if qual is None:
        qual = qualification_table(profile, scored["country_code"])
    scored["qualifying_visas"] = scored["country_code"].map(lambda c: qual[c]["qualifying_count"])
    scored["is_home"] = scored["country_code"].map(lambda c: qual[c]["is_home"])
    # True/False only when the country publishes a shortage list and the user set a job field.
    scored["field_in_demand"] = [qual[c]["field_in_demand"] for c in scored["country_code"]]
    # Countries whose visas haven't been researched yet stay in the list (tagged in the UI) when a visa
    # filter is on: "no data" is not "no visa".
    scored["visas_researched"] = [qual[c]["researched"] for c in scored["country_code"]]

    mask = pd.Series(True, index=scored.index)
    if region and region != ALL_REGIONS:
        mask &= scored["region"] == region
    if profile.exclude_home:
        mask &= ~scored["is_home"]
    if profile.exclude_countries:
        mask &= ~scored["country_code"].isin(list(profile.exclude_countries))
    if profile.visa_filter_active:
        mask &= (scored["qualifying_visas"] > 0) | ~scored["visas_researched"]

    out = scored[mask].reset_index(drop=True)
    out["rank"] = range(1, len(out) + 1)
    return out


def excluded_count(weights, region, profile, qual=None) -> dict:
    """How many countries in the region were removed by the visa / home filters."""
    # Baseline keeps explicit exclusions ("not the US"), which are reported separately in the UI.
    in_region = rank(weights, region, Profile(exclude_countries=profile.exclude_countries), qual=None)
    kept = rank(weights, region, profile, qual=qual)
    return {"in_region": len(in_region), "shown": len(kept),
            "hidden_by_filters": max(0, len(in_region) - len(kept))}


def rank_of(ranked: pd.DataFrame, country_name: str) -> Optional[int]:
    hit = ranked.loc[ranked["country_name"] == country_name, "rank"]
    return int(hit.iloc[0]) if len(hit) else None


# ---------------------------------------------------------------------------
# What-if analysis
# ---------------------------------------------------------------------------

def _variants(current: float):
    """Candidate new weights for one factor, smallest change first."""
    cands = {round(max(0.0, current - 0.3), 2), round(min(1.0, current + 0.3), 2), 0.0, 1.0}
    cands.discard(round(current, 2))
    return sorted(cands, key=lambda v: abs(v - current))


def what_if_country(weights: dict, region, profile: Profile, country_name: str,
                    qual: Optional[dict] = None, limit: int = 3) -> list:
    """
    For one country: which single slider change would move it up the most?
    Returns [{factor, from, to, old_rank, new_rank, text}], best improvements first.
    """
    base = rank(weights, region, profile, qual)
    old = rank_of(base, country_name)
    if old is None:
        return []
    best_per_factor = []
    for key in FACTOR_KEYS:
        cur = float(weights.get(key, 0.0))
        best = None
        for target in (0.0, 1.0):
            if abs(target - cur) < 0.05:
                continue
            new_rank = rank_of(rank({**weights, key: target}, region, profile, qual), country_name)
            if new_rank is not None and new_rank < old and (best is None or new_rank < best[1]):
                best = (target, new_rank)
        if best:
            target, new_rank = best
            verb = "Raising" if target > cur else "Lowering"
            best_per_factor.append({
                "factor": key, "from": round(cur, 2), "to": target,
                "old_rank": old, "new_rank": new_rank,
                "text": f"{verb} {FACTORS[key]['label']} to {target:.1f} would move "
                        f"{country_name} from #{old} to #{new_rank}.",
            })
    best_per_factor.sort(key=lambda d: d["new_rank"])
    return best_per_factor[:limit]


def what_would_flip_top(weights: dict, region, profile: Profile,
                        qual: Optional[dict] = None) -> Optional[dict]:
    """The smallest single-slider change that changes who is #1."""
    base = rank(weights, region, profile, qual)
    if len(base) < 2:
        return None
    leader = base.iloc[0]["country_name"]
    best = None
    for key in FACTOR_KEYS:
        cur = float(weights.get(key, 0.0))
        for target in _variants(cur):
            alt = rank({**weights, key: target}, region, profile, qual)
            new_leader = alt.iloc[0]["country_name"]
            if new_leader != leader:
                delta = abs(target - cur)
                if best is None or delta < best["delta"]:
                    best = {"factor": key, "from": round(cur, 2), "to": target,
                            "delta": round(delta, 2), "leader": leader, "new_leader": new_leader}
                break  # variants are ordered by size; first flip is smallest for this factor
    if not best:
        return {"text": f"{leader} stays #1 no matter which single slider you move. "
                        f"It's a robust match.", "leader": leader}
    phrase = FACTORS[best["factor"]]["label"].lower()
    direction = "less" if best["to"] < best["from"] else "more"
    best["text"] = (f"If you cared {direction} about {phrase} "
                    f"({best['from']:.2f} → {best['to']:.2f}), {best['new_leader']} "
                    f"would take #1 from {leader}.")
    return best
